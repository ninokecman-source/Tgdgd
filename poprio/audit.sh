#!/bin/bash
# Sigurnosna provjera servera - SAMO ČITA, ništa ne mijenja.
echo "============ 1. TAJNE I DOZVOLE ============"
stat -c '%n  vlasnik=%U:%G  prava=%a' /opt/poprio/config.json 2>/dev/null
echo "   (treba: vlasnik=poprio:poprio prava=600)"
stat -c '%n  vlasnik=%U:%G  prava=%a' /var/lib/poprio /var/lib/poprio/state.sqlite3 2>/dev/null
echo "   (treba: mapa 700)"
echo "-- kopije baze --"
stat -c '%n  vlasnik=%U:%G  prava=%a' /var/backups/poprio 2>/dev/null
ls -l /var/backups/poprio/ 2>/dev/null | head -8
echo
echo "============ 2. TKO SMIJE MIJENJATI KOD ============"
stat -c '%n  vlasnik=%U:%G  prava=%a' /opt/poprio /opt/poprio/sync.py 2>/dev/null
echo "   (ako je vlasnik poprio, servis može prepisati vlastiti kod)"
echo
echo "============ 3. SSH ============"
sshd -T 2>/dev/null | grep -E '^(passwordauthentication|permitrootlogin|kbdinteractiveauthentication|port|x11forwarding)' 
echo "-- ovlašteni ključevi --"
awk '{print NR") "$1" "$NF}' /root/.ssh/authorized_keys 2>/dev/null
stat -c '%n prava=%a' /root/.ssh /root/.ssh/authorized_keys 2>/dev/null
echo
echo "============ 4. VATROZID I FAIL2BAN ============"
ufw status verbose 2>/dev/null | head -12
systemctl is-active fail2ban 2>/dev/null | sed 's/^/fail2ban: /'
fail2ban-client status sshd 2>/dev/null | sed -n '2,8p'
echo
echo "============ 5. OTVORENI PORTOVI ============"
ss -tulnp 2>/dev/null | grep -v '127.0.0.1\|::1' | head -15
echo
echo "============ 6. ZAKRPE ============"
[ -f /var/run/reboot-required ] && echo "TREBA RESTART" || echo "restart ne treba"
apt list --upgradable 2>/dev/null | grep -c upgradable | sed 's/^/zakrpa na čekanju: /'
grep -h Unattended /etc/apt/apt.conf.d/20auto-upgrades 2>/dev/null
echo
echo "============ 7. POKUŠAJI PROVALE (zadnja 24h) ============"
journalctl -t sshd-session --since "24 hours ago" --no-pager 2>/dev/null | grep -c "Failed\|Invalid user" | sed 's/^/neuspjelih prijava: /'
journalctl -t sshd-session --since "24 hours ago" --no-pager 2>/dev/null | grep -oE 'from [0-9.]+' | sort | uniq -c | sort -rn | head -5
echo "-- uspjele prijave (7 dana) --"
journalctl -t sshd-session --since "7 days ago" --no-pager 2>/dev/null | grep "Accepted" | tail -5
echo
echo "============ 8. SERVIS ============"
systemctl is-active poprio; systemctl is-enabled poprio
systemctl show poprio -p User -p NoNewPrivileges -p ProtectSystem -p PrivateTmp -p ProtectHome 2>/dev/null
echo
echo "============ 9. CURE LI TAJNE U LOG ============"
# Traži tajne u logu usporedbom sa stvarnim vrijednostima iz configa,
# umjesto da ih ima upisane u sebi.
python3 - <<'PY'
import json, re, subprocess
try:
    c = json.load(open("/opt/poprio/config.json"))
except Exception as e:
    print("ne mogu pročitati config:", e); raise SystemExit
tajne = {k: str(v) for k, v in c.items()
         if k in ("cliniko_api_key", "solo_api_token", "smtp_password", "healthcheck_url")
         and len(str(v)) > 8}
log = subprocess.run(["journalctl", "-u", "poprio", "--since", "7 days ago", "--no-pager"],
                     capture_output=True, text=True).stdout
for k, v in tajne.items():
    print(f"  {k}: {'PROCURILO U LOG' if v in log else 'nema ga u logu'}")
PY
