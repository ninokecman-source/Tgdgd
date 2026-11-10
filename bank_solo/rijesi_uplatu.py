"""
Poveži nepovezanu uplatu s polaznikom - kad sustav nije uspio sam.

Uplata se ne prepozna kad u opisu plaćanja ne piše ime polaznika: netko
plati za drugoga, upiše samo "tečaj", ili iskrivi ime. Dosad je takva
uplata stizala mailom kao upozorenje i tu je priča stajala - izvod se čita
samo jednom, pa je za sustav te uplate nakon toga nije ni bilo.

Sad čeka u bazi, a ovdje joj se kaže čija je. Tada se:

  1. iznos pribroji u koloni "Payment Received" tog polaznika
  2. uplata označi obrađenom, pa se više ne javlja kao greška
  3. ako je uključeno, polazniku pošalje potvrda uplate

Solo ponuda se NE izdaje. Kod uplata koje sustav prepozna sam ponuda ide
automatski, ali ovdje je riječ o uplati koju je trebalo razriješiti rukom -
pa se i račun izdaje rukom, s podacima koje skripta ispiše na kraju. Tako
nijedan dokument ne nastane na temelju pretpostavke.

Pokretanje (iz korijena repozitorija ili iz bank_solo):
    python3 bank_solo/rijesi_uplatu.py --popis
    python3 bank_solo/rijesi_uplatu.py --ref 1234567 --email ana@primjer.hr
    python3 bank_solo/rijesi_uplatu.py --ref 1234567 --email ana@primjer.hr --stvarno
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mailer import send_payment_confirmation
from registrants import add_payment, load_registrants
from state import StateStore
from sync import load_config

# Umask 077, isto što radi prava.py u korijenu: nove datoteke nastaju kao 600,
# mape kao 700. Ovdje se ne uvozi prava.py jer bi korijen na sys.pathu zasjenio
# bank_solo/setup_config.py onim iz korijena - isti naziv, drugi posao.
os.umask(0o077)

# Oznaka kojom se u bazi vidi da uplata nije kotizacija nego zanemarena.
# Isti niz stoji u web/skupi.py (ZANEMARENO), koji po njemu takve uplate
# izostavlja iz ukupnog iznosa i popisa zadnjih.
OZNAKA_ZANEMARENO = "zanemareno"


def nadji_polaznika(registrants: list, email: str, tecaj: str = None):
    """Polaznik po adresi, a ako je zadan i tečaj - onaj iz te tablice.

    Tečaj je potreban jer ista adresa stoji na svakom modulu koji polaznik
    sluša: tko je prošao Modul 3 i nastavio na Modul 4 je u obje tablice.
    Bez tečaja se takva uplata nije dala povezati nego bi skripta stala."""
    trazeno = email.strip().lower()
    pogodci = [r for r in registrants if (r.get("email") or "").strip().lower() == trazeno]
    if not pogodci:
        sys.exit(f"Nijedan polaznik nema adresu {email!r}.")
    if tecaj:
        u_tablici = [r for r in pogodci if Path(r["file_path"]).name == tecaj]
        if not u_tablici:
            gdje = ", ".join(sorted({Path(r["file_path"]).name for r in pogodci}))
            sys.exit(f"U tablici {tecaj!r} nema polaznika s adresom {email!r} "
                     f"(ima ga u: {gdje}).")
        pogodci = u_tablici
    if len(pogodci) > 1:
        gdje = ", ".join(f"{r['course_code']}/{r['location']}" for r in pogodci)
        sys.exit(f"Adresa {email!r} se pojavljuje na više tečajeva ({gdje}). "
                 f"Dodaj --tecaj \"NAZIV.xlsx\" da kažeš na koji uplata ide.")
    return pogodci[0]


def zanemari(state: StateStore, ref_id: str, stvarno: bool) -> None:
    """Uplata nije kotizacija - skloni je s popisa, bez knjiženja.

    Ovamo idu vlastiti prijenosi, povrati i svaki novac koji nema polaznika.
    Zapisuju se DVIJE stvari, i obje su potrebne:

      - resolved_at: uplata nestane s popisa nepovezanih
      - zapis u processed_transactions s oznakom 'zanemareno': sync.py
        preskače svaki ref_id koji je ondje, pa se uplata ne može proknjižiti
        ni ako izvod jednom stigne ponovno i ime se slučajno upari

    Iznos se zapisuje pravi, ne nula - web ga po oznaci izostavlja iz
    ukupnog, pa baza ostaje točna a brojka na stranici nije napuhana."""
    uplata = state.get_unmatched(ref_id)
    if uplata is None:
        sys.exit(f"Nema nepovezane uplate s oznakom {ref_id!r}.")
    if uplata["resolved_at"]:
        sys.exit(f"Uplata {ref_id} je već riješena "
                 f"({uplata['resolved_at']}, {uplata['resolved_to']}).")
    if state.is_transaction_processed(ref_id):
        sys.exit(f"Uplata {ref_id} je već proknjižena - ne diram je.")

    iznos = float(uplata["amount"])
    print(f"Uplata {iznos:.2f} EUR od {uplata['name'] or '?'} ({uplata['date']})")
    print(f"  opis uplate: {uplata['description'] or '(nema)'}")
    print("  nikome se ne pripisuje i ne ide u tablicu")

    if not stvarno:
        print("\nPregled - ništa nije promijenjeno. Za stvarno dodaj --stvarno")
        return

    state.mark_transaction_processed(ref_id, iznos, OZNAKA_ZANEMARENO,
                                    OZNAKA_ZANEMARENO)
    state.resolve_unmatched(ref_id, OZNAKA_ZANEMARENO)
    print("\nZanemareno. Nema je više među nepovezanima, a ako izvod stigne "
          "ponovno, preskače se.")


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


def rijesi(state: StateStore, config: dict, ref_id: str, email: str,
           stvarno: bool, tecaj: str = None) -> None:
    uplata = state.get_unmatched(ref_id)
    if uplata is None:
        sys.exit(f"Nema nepovezane uplate s oznakom {ref_id!r}.")
    if uplata["resolved_at"]:
        sys.exit(f"Uplata {ref_id} je već povezana "
                 f"({uplata['resolved_at']}, {uplata['resolved_to']}).")
    if state.is_transaction_processed(ref_id):
        sys.exit(f"Uplata {ref_id} je već proknjižena - ne diram je.")

    registrants = load_registrants(Path(config["excel_dir"]))
    polaznik = nadji_polaznika(registrants, email, tecaj)
    puno_ime = f"{polaznik['first_name']} {polaznik['last_name']}".strip()
    iznos = float(uplata["amount"])
    tecaj = f"{polaznik['course_code']} - {polaznik['location']}".strip(" -")

    print(f"Uplata {iznos:.2f} EUR od {uplata['name'] or '?'} ({uplata['date']})")
    print(f"  opis uplate: {uplata['description'] or '(nema)'}")
    print(f"  ide na:      {puno_ime} <{polaznik['email']}>")
    print(f"  tečaj:       {tecaj}")
    print(f"  tablica:     {Path(polaznik['file_path']).name}, redak {polaznik['row']}")

    if not stvarno:
        print("\nPregled - ništa nije promijenjeno. Za stvarno dodaj --stvarno")
        return

    novi_ukupno = add_payment(polaznik["file_path"], polaznik["row"], iznos)
    # 'rucno' umjesto broja ponude: u bazi se tako vidi da za ovu uplatu
    # ponuda nije izdana automatski.
    state.mark_transaction_processed(ref_id, iznos, puno_ime, "rucno")
    state.resolve_unmatched(ref_id, puno_ime)

    print(f"\nUpisano u tablicu. {puno_ime} ima sad ukupno "
          f"{novi_ukupno:.2f} EUR.")
    print("\nSolo ponuda NIJE izdana - izdaj je sam, s ovim podacima:")
    print(f"  kupac:  {puno_ime}")
    if polaznik.get("address"):
        print(f"  adresa: {polaznik['address']}")
    print(f"  iznos:  {iznos:.2f} EUR")
    print(f"  tečaj:  {tecaj}")

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
    parser.add_argument("--tecaj", metavar="NAZIV.xlsx",
                        help="Tablica tečaja na koji uplata ide; treba kad je "
                             "polaznik upisan na više modula")
    parser.add_argument("--zanemari", action="store_true",
                        help="Uplata nije kotizacija - skloni je s popisa, "
                             "bez knjiženja i bez upisa u tablicu")
    parser.add_argument("--stvarno", action="store_true",
                        help="Stvarno proknjiži; bez ovoga je samo pregled")
    args = parser.parse_args()

    config = load_config()
    state = StateStore(config["state_db_path"])
    try:
        if args.popis:
            ispisi_popis(state)
            return
        if args.zanemari:
            if not args.ref:
                sys.exit("Za --zanemari treba --ref.")
            zanemari(state, args.ref, args.stvarno)
            return
        if not args.ref or not args.email:
            sys.exit("Trebaju --ref i --email (ili --popis, ili --zanemari).")
        rijesi(state, config, args.ref, args.email, args.stvarno, args.tecaj)
    finally:
        state.close()


if __name__ == "__main__":
    main()
