import json
import unittest
from unittest import mock

from cezih import nalaz, oib
from cezih.client import CezihGreska, CezihKlijent
from cezih.config import CezihConfig

CFG = CezihConfig(base_url="https://x/fhir", client_cert="c", client_key="k",
                  organizacija_id="123", retries=2)
OIB = "69435151530"  # ispravan testni OIB


class Odg:
    def __init__(self, status, tijelo):
        self.status_code, self._t = status, tijelo
        self.content = json.dumps(tijelo).encode()
        self.text = json.dumps(tijelo)

    def json(self):
        return self._t


class OibTest(unittest.TestCase):
    def test_oib(self):
        self.assertTrue(oib.je_ispravan(OIB))
        self.assertFalse(oib.je_ispravan("69435151531"))
        self.assertFalse(oib.je_ispravan("abc"))


class NalazTest(unittest.TestCase):
    def test_bundle(self):
        b = nalaz.sastavi_nalaz(CFG, OIB, "Krvna slika", "Nalaz uredan", pdf=b"%PDF")
        r = b["entry"][0]["resource"]
        self.assertEqual(r["subject"]["identifier"]["value"], OIB)
        self.assertEqual(r["performer"][0]["identifier"]["value"], "123")
        self.assertIn("presentedForm", r)

    def test_los_oib_i_prazan_nalaz(self):
        with self.assertRaises(ValueError):
            nalaz.sastavi_nalaz(CFG, "123", "x", "y")
        with self.assertRaises(ValueError):
            nalaz.sastavi_nalaz(CFG, OIB, "x", "  ")

    def test_4xx_se_ne_ponavlja(self):
        s = mock.Mock()
        s.request.return_value = Odg(422, {"resourceType": "OperationOutcome",
                                           "issue": [{"severity": "error", "code": "invalid",
                                                      "diagnostics": "OIB nepoznat"}]})
        k = CezihKlijent(CFG, session=s)
        with self.assertRaises(CezihGreska) as ctx:
            nalaz.posalji_nalaz(k, pacijent_oib=OIB, naslov="a", tekst="b")
        self.assertIn("OIB nepoznat", str(ctx.exception))
        self.assertEqual(s.request.call_count, 1)

    def test_5xx_se_ponavlja(self):
        s = mock.Mock()
        s.request.side_effect = [Odg(503, {}), Odg(200, {"entry": [{"response": {"status": "201"}}]})]
        k = CezihKlijent(CFG, session=s)
        with mock.patch("cezih.client.time.sleep"):
            nalaz.posalji_nalaz(k, pacijent_oib=OIB, naslov="a", tekst="b")
        self.assertEqual(s.request.call_count, 2)

    def test_odbijen_unos_u_bundleu(self):
        s = mock.Mock()
        s.request.return_value = Odg(200, {"entry": [{"response": {"status": "400 Bad Request"}}]})
        with self.assertRaises(CezihGreska):
            nalaz.posalji_nalaz(CezihKlijent(CFG, session=s), pacijent_oib=OIB, naslov="a", tekst="b")


if __name__ == "__main__":
    unittest.main()
