"""Obavijesti mailom kad nešto traži ljudsku pažnju.

Bez ovoga sve završava u logu koji nitko ne gleda: računi se tiho prestanu
fiskalizirati, a otkrije se tek kad knjigovođa usporedi promet.

Prigušivanje: isti problem se javlja najviše jednom u `MIN_INTERVAL_HOURS`,
jer bi kvar koji traje uz provjeru svakih 15 sekundi inače poslao stotine
mailova. Kad problem prestane, šalje se jedna obavijest o oporavku.

VAŽNO: ovo ne može javiti da je sama skripta prestala raditi - mrtav proces
ne šalje mailove. Za to služi `healthcheck_url` (vidi sync.py::ping_healthcheck).
"""

import sys

from mailer import send_alert

MIN_INTERVAL_HOURS = 6


class Alerter:
    def __init__(self, config, state):
        self.config = config
        self.state = state
        self.to_email = (config.get("alert_email") or "").strip()

    @property
    def enabled(self):
        return bool(self.to_email)

    def problem(self, key, subject, body, min_interval_hours=MIN_INTERVAL_HOURS):
        """Javlja problem, ali ne češće od zadanog razmaka za isti `key`."""
        if not self.enabled:
            return
        if not self.state.alert_due(key, min_interval_hours):
            return
        self._send(subject, body)

    def resolved(self, key, subject, body):
        """Javlja oporavak - samo ako je za taj `key` prije poslan problem."""
        if not self.enabled or not self.state.alert_was_sent(key):
            return
        self.state.clear_alert(key)
        self._send(subject, body)

    def _send(self, subject, body):
        # Neuspjeh slanja obavijesti ne smije srušiti sinkronizaciju - fiskalizacija
        # je važnija od maila, a greška ionako ostaje u logu.
        try:
            send_alert(self.config, self.to_email, subject, body)
        except Exception as e:
            print(f"[UPOZORENJE] Obavijest '{subject}' nije poslana: {e}", file=sys.stderr)
