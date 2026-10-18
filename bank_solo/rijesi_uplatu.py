"""
Poveži nepovezanu uplatu s polaznikom - kad sustav nije uspio sam.

Uplata se ne prepozna kad u opisu plaćanja ne piše ime polaznika: netko
plati za drugoga, upiše samo "tečaj", ili iskrivi ime. Dosad je takva
uplata stizala mailom kao upozorenje i tu je priča stajala - izvod se čita
samo jednom, pa je za sustav te uplate nakon toga nije ni bilo.

Sad čeka u bazi, a ovdje joj se kaže čija je. Tada se dogodi sve ono što bi
se dogodilo i da je prepoznata odmah:

  1. izda se Solo ponuda na uplaćeni iznos
  2. iznos se pribroji u koloni "Payment Received" tog polaznika
  3. uplata se označi obrađenom, pa se više ne javlja kao greška
  4. ako je uključeno, polazniku ode potvrda uplate

Pokretanje (iz korijena repozitorija ili iz bank_solo):
    python3 bank_solo/rijesi_uplatu.py --popis
    python3 bank_solo/rijesi_uplatu.py --ref 1234567 --email ana@primjer.hr
    python3 bank_solo/rijesi_uplatu.py --ref 1234567 --email ana@primjer.hr --stvarno
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mailer import send_payment_confirmation
from oib_lookup import discover_registration_folders, find_oib
from registrants import add_payment, load_registrants
from solo_client import SoloAPIError, SoloClient
from state import StateStore
from sync import load_config, resolve_description, spoji_imap


def nadji_polaznika(registrants: list, email: str):
    trazeno = email.strip().lower()
    pogodci = [r for r in registrants if (r.get("email") or "").strip().lower() == trazeno]
    if not pogodci:
        sys.exit(f"Nijedan polaznik nema adresu {email!r}.")
    if len(pogodci) > 1:
        gdje = ", ".join(f"{r['course_code']}/{r['location']}" for r in pogodci)
        sys.exit(f"Adresa {email!r} se pojavljuje na više tečajeva ({gdje}). "
                 f"Ne znam na koji bi uplata išla - riješi ručno.")
    return pogodci[0]


def ispisi_popis(state: StateStore) -> None:
    uplate = state.open_unmatched()
    if not uplate:
        print("Nema nepovezanih uplata.")
        return
    print(f"Nepovezane uplate ({len(uplate)}):\n")
    for u in uplate:
        print(f"  ref {u['ref_id']}  {u['date']}  {u['amount']:.2f} EUR")
        print(f"      uplatitelj: {u['name'] or '?'}")
        print(f"      opis:       {u['description'] or '(nema)'}")
        print(f"      razlog:     {u['razlog'] or '-'}\n")


def oib_polaznika(config: dict, email: str) -> str:
    """OIB iz izvorne prijave. Ako se do maila ne može, ponuda ide bez
    OIB-a - isto kao i kod automatske obrade."""
    try:
        imap = spoji_imap(config)
    except Exception as e:
        print(f"  (ne mogu do maila za OIB: {e} - ponuda ide bez OIB-a)")
        return ""
    try:
        imap.login(config["zoho_email"], config["zoho_app_password"])
        folders = discover_registration_folders(
            imap, config.get("course_folder_roots", []))
        return find_oib(imap, config["sender_filter"], folders, email) or ""
    except Exception as e:
        print(f"  (OIB nije dohvaćen: {e} - ponuda ide bez OIB-a)")
        return ""
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def rijesi(state: StateStore, config: dict, ref_id: str, email: str,
           stvarno: bool) -> None:
    uplata = state.get_unmatched(ref_id)
    if uplata is None:
        sys.exit(f"Nema nepovezane uplate s oznakom {ref_id!r}.")
    if uplata["resolved_at"]:
        sys.exit(f"Uplata {ref_id} je već povezana "
                 f"({uplata['resolved_at']}, {uplata['resolved_to']}).")
    if state.is_transaction_processed(ref_id):
        sys.exit(f"Uplata {ref_id} je već proknjižena - ne diram je.")

    registrants = load_registrants(Path(config["excel_dir"]))
    polaznik = nadji_polaznika(registrants, email)
    puno_ime = f"{polaznik['first_name']} {polaznik['last_name']}".strip()
    iznos = float(uplata["amount"])

    opis = resolve_description(config, iznos, polaznik["course_code"])
    if opis is None:
        sys.exit(f"Kod tečaja {polaznik['course_code']!r} nema opisa u "
                 f"course_description_map - dopuni config.json pa pokušaj opet.")

    napomene = f"{polaznik['course_code']} - {polaznik['location']}".strip(" -")
    print(f"Uplata {iznos:.2f} EUR od {uplata['name'] or '?'} ({uplata['date']})")
    print(f"  opis uplate: {uplata['description'] or '(nema)'}")
    print(f"  ide na:      {puno_ime} <{polaznik['email']}>")
    print(f"  tečaj:       {napomene}")
    print(f"  na ponudi:   {opis}")
    print(f"  tablica:     {Path(polaznik['file_path']).name}, redak {polaznik['row']}")

    if not stvarno:
        print("\nPregled - ništa nije promijenjeno. Za stvarno dodaj --stvarno")
        return

    oib = oib_polaznika(config, polaznik["email"])
    if not oib:
        print(f"  (OIB nije pronađen za {puno_ime} - ponuda se šalje bez OIB-a)")

    solo = SoloClient(api_token=config["solo_api_token"])
    try:
        ponuda = solo.create_ponuda(
            tip_kupca=config["solo_tip_kupca"],
            tip_usluge=config["solo_tip_usluge"],
            nacin_placanja=config["solo_nacin_placanja"],
            kupac_naziv=puno_ime,
            kupac_adresa=polaznik.get("address") or None,
            kupac_oib=oib or None,
            stavke=[{"opis": opis, "cijena": iznos, "kolicina": 1,
                     "porez_stopa": config["solo_default_tax_rate"]}],
            napomene=napomene,
        )
    except SoloAPIError as e:
        sys.exit(f"[GREŠKA] Solo ponuda za {puno_ime} ({ref_id}): {e}")

    broj_ponude = ponuda.get("broj_ponude")
    # Tek kad je ponuda izdana diramo tablicu i stanje - da se uplata ne
    # proknjiži dvaput ako Solo zakaže pa pokušaš ponovno.
    novi_ukupno = add_payment(polaznik["file_path"], polaznik["row"], iznos)
    state.mark_transaction_processed(ref_id, iznos, puno_ime, broj_ponude)
    state.resolve_unmatched(ref_id, puno_ime)

    print(f"\nGotovo. Solo ponuda {broj_ponude}, ukupno uplaćeno sad: "
          f"{novi_ukupno:.2f} EUR.")

    if config.get("send_payment_confirmation"):
        try:
            if send_payment_confirmation(config, polaznik, iznos, novi_ukupno):
                print(f"  Poslana potvrda uplate na {polaznik['email']}")
            else:
                print("  Potvrda uplate nije poslana (nema email adrese ili teksta)")
        except Exception as e:
            print(f"  [!] Potvrda uplate na {polaznik.get('email')} nije poslana: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Poveži nepovezanu bankovnu uplatu s polaznikom.")
    parser.add_argument("--popis", action="store_true",
                        help="Ispiši nepovezane uplate i stani")
    parser.add_argument("--ref", help="Oznaka transakcije (ref_id)")
    parser.add_argument("--email", help="Adresa polaznika kojem uplata pripada")
    parser.add_argument("--stvarno", action="store_true",
                        help="Stvarno proknjiži; bez ovoga je samo pregled")
    args = parser.parse_args()

    config = load_config()
    state = StateStore(config["state_db_path"])
    try:
        if args.popis:
            ispisi_popis(state)
            return
        if not args.ref or not args.email:
            sys.exit("Trebaju --ref i --email (ili --popis).")
        rijesi(state, config, args.ref, args.email, args.stvarno)
    finally:
        state.close()


if __name__ == "__main__":
    main()
