"""
python -m cezih provjeri                      - provjeri vezu i certifikat (GET /metadata)
python -m cezih posalji OIB "Naslov" tekst.txt [nalaz.pdf]
python -m cezih nalazi OIB [YYYY-MM-DD]
"""

import sys
from pathlib import Path

from . import config, nalaz
from .client import CezihGreska, CezihKlijent


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    try:
        k = CezihKlijent(config.ucitaj())
        if argv[0] == "provjeri":
            m = k.get("metadata")
            print("Veza radi. FHIR verzija:", m.get("fhirVersion", "?"))
        elif argv[0] == "posalji" and len(argv) >= 4:
            pdf = Path(argv[4]).read_bytes() if len(argv) > 4 else None
            nalaz.posalji_nalaz(k, pacijent_oib=argv[1], naslov=argv[2],
                                tekst=Path(argv[3]).read_text(encoding="utf-8"), pdf=pdf)
            print("Nalaz poslan.")
        elif argv[0] == "nalazi" and len(argv) >= 2:
            for n in nalaz.nalazi_pacijenta(k, argv[1], argv[2] if len(argv) > 2 else None):
                print(n.get("issued", "?"), "-", (n.get("code") or {}).get("text", "?"))
        else:
            print(__doc__)
            return 2
    except (config.ConfigGreska, CezihGreska, ValueError) as e:
        print("GREŠKA:", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
