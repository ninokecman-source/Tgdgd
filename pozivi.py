"""
Koga pozvati na tečaj - polaznici prethodnog modula koji se još nisu
prijavili.

Tko je završio Modul 1&2 prirodni je kandidat za Modul 3, tko je završio
Modul 3 za Modul 4, i tako redom. Redoslijed modula stoji u config.json pod
'module_order'; kod tečaja koji nije na tom popisu (npr. ponavljanje) nema
prethodnika, pa ni kandidata.

Mjesto se NE gleda. Tko je M1&2 radio u Splitu može doći na M3 u Zagreb, a
skripta to ne može znati umjesto tebe - zato se kandidati vraćaju grupirani
po tečaju s kojeg dolaze, pa se na stranici odznači koga ne treba.

Iz popisa izlaze tri skupine:

  - oni koji su već na tom tečaju (po adresi)
  - oni kojima je poziv već poslan (poslani_pozivi.json)
  - oni bez upisane adrese - njima se ne može ni poslati

Radi nad tečajevima onako kako ih je pročitao web/skupi.py, pa ne otvara
nijednu tablicu dvaput.
"""

from predlosci import kljuc_tecaja

ZADANI_REDOSLIJED = ["Modul 1&2", "Modul 3", "Modul 4", "Modul 5", "Modul 6"]

# Što se radi na kojem modulu - za poziv na sljedeći tečaj, da čovjek vidi
# što dobiva, a ne samo datum. Prepisano s emmett-hr.com, sa stranice
# "Praktičarski EMMETT tečaj", uz ispravljene očite tipfelere (popis je tamo
# pisan za stranicu, a ovo ide u mail polazniku).
#
# Mijenja se u config.json pod "module_procedures", po modulu; što ondje
# nije navedeno, uzima se odavde. Kod modula koji ovdje nema - ponavljanja,
# praktičarski dan - poziv jednostavno nema taj odlomak.
ZADANE_PROCEDURE = {
    "Modul 1&2": [
        "O Rossu Emmettu",
        "EMMETT principi",
        "7 A-ova (podsvjesni trigeri liječenja)",
        "QL / 12. rebro (rotacija tijela)",
        "Piriformis / TFL (piriformis i gluteusi)",
        "Iliacus / obliqusi (zdjelica i kuk)",
        "Psoas / 12. rebro (psoas i hamstringsi)",
        "Psoas s podignutim koljenom (psoas i lumbalna kralježnica)",
        "Gastroc opuštanje potkoljenice (problemi s listovima i balans)",
        "Gornji trapeziusi (ramena i vrat)",
        "Levator scapulae 45 (ramena i vrat)",
        "Rhomboid 45 (vrat)",
        "Rhomboid 90 (ramena)",
        "Rhomboid 30 (ruka i prsti)",
        "SCM (vrat)",
        "AC / biceps (ramena)",
    ],
    "Modul 3": [
        "Ponavljanje Modula 1 i 2",
        "Ingvinalni psoas (psoas i lumbalna kralježnica)",
        "Teres minor (ramena)",
        "Sacrum (sacrum)",
        "Podlaktica (stisak šake, lakat i ramena)",
        "Opuštanje koljena",
        "ITB (noga, kuk i koljeno)",
        "ITB / sartorius (koljeno)",
        "Balans stopala (balans)",
        "Dijafragma",
        "Rescue (balans cijelog tijela)",
    ],
    "Modul 4": [
        "Ponavljanje Modula 3",
        "Abdominalno opuštanje",
        "Pectoralis minor opuštanje (rame)",
        "Skapula - rub (romboideusi)",
        "Skapula - srednji i donji dio (skapula)",
        "Latissimus dorsi (leđa i ramena)",
        "Biceps, dvije glave (biceps i ramena)",
        "Triceps (triceps)",
        "Hamstringsi (hamstringsi i lumbalna kralježnica)",
        "Opuštanje (soleus i Ahilova tetiva)",
        "Opuštanje boli u koljenu (koljeno)",
    ],
    "Modul 5": [
        "Ponavljanje Modula 4",
        "Čeljust (čeljust, oči, uši)",
        "Glava / čeljust",
        "Prsni koš / rhomboid 45 (rotatorna manšeta i prsni koš)",
        "Scalenus / pectoralis minor (rame i vrat)",
        "Prsni koš / sinusi (kongestija sinusa)",
        "Koljeno",
        "Opuštanje gležnja (gležanj i stopalo)",
        "Opuštanje quadricepsa (quadricepsi i koljeno)",
        "Sacrum / TFL (gluteusi)",
        "Piriformis (piriformis)",
    ],
    "Modul 6": [
        "Ponavljanje Modula 5",
        "Rhomboid 45 x ingvinalni psoas (abdominalna fascija)",
        "Mjehur",
        "Aduktor",
        "Bol u stopalu (stopalo i gležanj)",
        "Vrat (oči, čeljust, vrat, ramena i ruke)",
        "Trbuh bicepsa (grč bicepsa)",
        "Sakralni usjek (duboka bol oko zdjelice)",
        "Limfna drenaža",
    ],
}


def redoslijed(config: dict) -> list:
    return [kljuc_tecaja(k) for k in
            (config.get("module_order") or ZADANI_REDOSLIJED)]


def procedure(config: dict, kod: str) -> list:
    """Popis procedura tog modula. Prazan ako za njega nema zapisa.

    Config ima prednost pred ugrađenim popisom, i to po modulu: tko u
    config.json upiše samo Modul 4, za ostale i dalje vrijedi ugrađeno."""
    kljuc = kljuc_tecaja(kod)
    for popis in (config.get("module_procedures") or {}, ZADANE_PROCEDURE):
        for zapis, stavke in popis.items():
            if kljuc_tecaja(zapis) == kljuc and stavke:
                return [str(s).strip() for s in stavke if str(s).strip()]
    return []


def odlomak_procedura(config: dict, kod: str) -> str:
    """Odlomak za poziv, ili prazan tekst kad za modul nema popisa.

    Vodeći prazan redak je namjeran: u predlošku {procedure} stoji u svom
    retku, pa kad popisa nema, od njega ostane običan razmak između
    odlomaka, a ne rupa."""
    stavke = procedure(config, kod)
    if not stavke:
        return ""
    return "\nNa ovom modulu radimo:\n\n" + "\n".join(f"- {s}" for s in stavke) + "\n"


def prethodni_modul(config: dict, kod: str):
    """Kod modula koji dolazi prije ovoga, ili None."""
    popis = redoslijed(config)
    kljuc = kljuc_tecaja(kod)
    if kljuc not in popis:
        return None
    mjesto = popis.index(kljuc)
    return popis[mjesto - 1] if mjesto > 0 else None


def sljedeci_modul(config: dict, kod: str):
    """Kod modula koji dolazi poslije ovoga, ili None (zadnji modul, ili
    tečaj koji uopće nije u nizu - ponavljanje, praktičarski dan)."""
    popis = redoslijed(config)
    kljuc = kljuc_tecaja(kod)
    if kljuc not in popis:
        return None
    mjesto = popis.index(kljuc)
    return popis[mjesto + 1] if mjesto + 1 < len(popis) else None


def napisan(config: dict, kljuc: str) -> str:
    """Svedeni ključ natrag u zapis iz configa - to ide u tekst poruke, pa
    ne smije ostati 'modul 1&2'."""
    if kljuc is None:
        return ""
    for zapis in (config.get("module_order") or ZADANI_REDOSLIJED):
        if kljuc_tecaja(zapis) == kljuc:
            return zapis
    return kljuc


def naziv_sljedeceg(config: dict, kod: str) -> str:
    return napisan(config, sljedeci_modul(config, kod))


def naziv_prethodnog(config: dict, kod: str) -> str:
    """Prethodni modul napisan onako kako stoji u configu - to ide u tekst
    poruke, pa ne smije biti svedeni ključ ('modul 1&2')."""
    return napisan(config, prethodni_modul(config, kod))


def kandidati(tecaj: dict, svi_tecajevi: list, config: dict,
              vec_pozvani=()) -> list:
    """[{tecaj, mjesto, datumi, ljudi: [{ime, email}]}] - po jedan unos za
    svaki prošli tečaj prethodnog modula koji ima koga ponuditi."""
    prethodni = prethodni_modul(config, tecaj.get("kod", ""))
    if prethodni is None:
        return []

    # tko je već ovdje, i tko je već pozvan - adresa je jedina jedinstvena
    izbaci = {p["email"].lower() for p in tecaj["polaznici"] if p.get("email")}
    izbaci |= {a.lower() for a in vec_pozvani}

    skupine = []
    for izvor in svi_tecajevi:
        if izvor["oznaka"] == tecaj["oznaka"]:
            continue
        if kljuc_tecaja(izvor.get("kod", "")) != prethodni:
            continue
        if izvor.get("stanje") != "prosao":
            continue      # s tečaja koji tek dolazi nema koga zvati

        ljudi = []
        for p in izvor["polaznici"]:
            adresa = (p.get("email") or "").strip()
            if not adresa or adresa.lower() in izbaci:
                continue
            izbaci.add(adresa.lower())   # isti čovjek na dva tečaja - jednom
            ljudi.append({"ime": p["ime"], "email": adresa})

        if ljudi:
            skupine.append({
                "tecaj": izvor.get("kod", ""),
                "mjesto": izvor.get("mjesto", ""),
                "datumi": izvor.get("datumi", ""),
                "kraj": izvor.get("kraj"),
                "ljudi": ljudi,
            })

    # najnoviji izvorni tečaj prvi - njegovi su polaznici najsvježiji
    skupine.sort(key=lambda s: s["kraj"] or "", reverse=True)
    return skupine
