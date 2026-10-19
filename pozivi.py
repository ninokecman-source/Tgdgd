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


def redoslijed(config: dict) -> list:
    return [kljuc_tecaja(k) for k in
            (config.get("module_order") or ZADANI_REDOSLIJED)]


def prethodni_modul(config: dict, kod: str):
    """Kod modula koji dolazi prije ovoga, ili None."""
    popis = redoslijed(config)
    kljuc = kljuc_tecaja(kod)
    if kljuc not in popis:
        return None
    mjesto = popis.index(kljuc)
    return popis[mjesto - 1] if mjesto > 0 else None


def naziv_prethodnog(config: dict, kod: str) -> str:
    """Prethodni modul napisan onako kako stoji u configu - to ide u tekst
    poruke, pa ne smije biti svedeni ključ ('modul 1&2')."""
    kljuc = prethodni_modul(config, kod)
    if kljuc is None:
        return ""
    for napisan in (config.get("module_order") or ZADANI_REDOSLIJED):
        if kljuc_tecaja(napisan) == kljuc:
            return napisan
    return kljuc


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
