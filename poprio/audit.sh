#!/bin/bash
# Sigurnosna provjera servera. SAMO ČITA - ništa ne mijenja, ništa ne restarta.
# Pokretati kao root:  bash audit.sh
REPO="${1:-/tmp/tgdgd/poprio}"
o(){ printf '\n========== %s ==========\n' "$1"; }

o "1. DOZVOLE NA TAJNAMA I PODACIMA"
stat -c '%n  %U:%G  %a' /opt/poprio/config.json 2>/dev/null
echo "   treba: poprio:poprio 600"
stat -c '%n  %U:%G  %a' /var/lib/poprio /var/lib/poprio/state.sqlite3 2>/dev/null
echo "   treba: mapa 700"
stat -c '%n  %U:%G  %a' /var/backups/poprio 2>/dev/null
echo "   treba: 700"
ls -l /var/backups/poprio/ 2>/dev/null | sed -n '2,4p'
echo "   treba: -rw------- (600)"

o "2. JE LI ITKO DIRAO POPRIJEV KOD"
if [ -d "$REPO" ]; then
  for f in /opt/poprio/*.py; do
    n=$(basename "$f")
    a=$(md5sum "$f" 2>/dev/null | cut -d' ' -f1)
    b=$(md5sum "$REPO/$n" 2>/dev/null | cut -d' ' -f1)
    [ "$a" = "$b" ] && echo "  $n  jednako repou" || echo "  $n  *** RAZLIKUJE SE OD REPOA ***"
  done
else
  echo "  (repo nije na $REPO - preskačem usporedbu)"
fi
stat -c '  %n  %U:%G  %a' /opt/poprio /opt/poprio/sync.py 2>/dev/null
find /opt/poprio -maxdepth 1 -newermt '-14 days' -printf '  mijenjano zadnjih 14 dana: %p  %TY-%Tm-%Td\n' 2>/dev/null | head

o "3. OGRAĐIVANJE POPRIO SERVISA"
systemctl show poprio -p User -p NoNewPrivileges -p ProtectSystem -p ProtectHome \
  -p PrivateTmp -p PrivateDevices -p RestrictNamespaces -p LockPersonality 2>/dev/null
echo "   treba: NoNewPrivileges=yes ProtectSystem=strict ProtectHome=yes"

o "4. SSH"
sshd -T 2>/dev/null | grep -E '^(port|passwordauthentication|permitrootlogin|kbdinteractiveauthentication|permitemptypasswords|x11forwarding|allowtcpforwarding|maxauthtries)'
echo "-- ovlašteni ključevi (root) --"
ssh-keygen -lf /root/.ssh/authorized_keys 2>/dev/null | sed 's/^/  /'
echo "-- ovlašteni ključevi (ostali korisnici) --"
for h in /home/*; do
  [ -f "$h/.ssh/authorized_keys" ] && { echo "  $h:"; ssh-keygen -lf "$h/.ssh/authorized_keys" 2>/dev/null | sed 's/^/    /'; }
done
ls -la /etc/ssh/sshd_config.d/ 2>/dev/null | sed -n '2,20p'

o "5. KORISNICI I OVLASTI"
echo "-- računi s ljuskom za prijavu --"
getent passwd | awk -F: '$7 !~ /nologin|false/ {printf "  %s uid=%s %s\n", $1, $3, $7}'
echo "-- članovi sudo/admin grupa --"
getent group sudo admin wheel 2>/dev/null | sed 's/^/  /'
echo "-- dodatna sudo pravila --"
ls -la /etc/sudoers.d/ 2>/dev/null | sed -n '2,20p'
echo "-- računi bez lozinke --"
awk -F: '$2 == "" {print "  *** " $1 " nema lozinku ***"}' /etc/shadow 2>/dev/null || echo "  (nema)"

o "6. VATROZID I FAIL2BAN"
ufw status verbose 2>/dev/null | sed -n '1,20p'
echo "fail2ban: $(systemctl is-active fail2ban 2>/dev/null)"
fail2ban-client status sshd 2>/dev/null | sed -n '2,9p'

o "7. ŠTO SLUŠA NA MREŽI"
ss -tulnp 2>/dev/null | awk 'NR==1 || !/127\.0\.0\.|::1/' | head -20

o "8. SERVISI I AUTOMATSKI POSLOVI"
echo "-- uključeni servisi --"
systemctl list-unit-files --state=enabled --type=service --no-pager 2>/dev/null | awk '{print "  "$1}' | head -30
echo "-- jedinice mijenjane zadnjih 14 dana --"
find /etc/systemd/system -maxdepth 2 -name '*.service' -newermt '-14 days' -printf '  %p  %TY-%Tm-%Td\n' 2>/dev/null
echo "-- cron --"
for u in $(cut -d: -f1 /etc/passwd); do c=$(crontab -l -u "$u" 2>/dev/null | grep -v '^#' | grep -c .); [ "${c:-0}" -gt 0 ] && echo "  $u ima $c cron unosa"; done
ls /etc/cron.d/ /etc/cron.daily/ 2>/dev/null | sed 's/^/  /'
echo "-- timeri --"
systemctl list-timers --no-pager 2>/dev/null | sed -n '2,8p'

o "9. ZAKRPE I NEDAVNE INSTALACIJE"
[ -f /var/run/reboot-required ] && echo "  TREBA RESTART" || echo "  restart ne treba"
echo "  zakrpa na čekanju: $(apt list --upgradable 2>/dev/null | grep -c upgradable)"
grep -h Unattended /etc/apt/apt.conf.d/20auto-upgrades 2>/dev/null | sed 's/^/  /'
echo "-- zadnjih 8 apt zahvata (najnoviji na dnu) --"
awk '/^Start-Date/{d=$2" "$3} /^Commandline/{sub(/^Commandline: /,""); print "  "d"  "$0}' \
  /var/log/apt/history.log 2>/dev/null | tail -8
echo "  zadnji unattended-upgrade:"
tail -3 /var/log/unattended-upgrades/unattended-upgrades.log 2>/dev/null | sed 's/^/    /'
echo "-- snapovi (ne pojavljuju se u apt povijesti) --"
snap list 2>/dev/null | sed 's/^/  /'
echo "-- zadnje promjene snapova --"
snap changes 2>/dev/null | tail -5 | sed 's/^/  /'

o "10. PRIJAVE"
echo "  neuspjelih (24h): $(journalctl -t sshd-session --since '24 hours ago' --no-pager 2>/dev/null | grep -c 'Failed\|Invalid user')"
echo "-- USPJELE prijave, 14 dana (svaka mora biti tvoja) --"
journalctl -t sshd-session --since '14 days ago' --no-pager 2>/dev/null | grep "Accepted" | awk '{print "  "$1,$2,$3,$9,$11,$NF}' | sort | uniq -c | sort -rn | head -12

o "11. CURE LI TAJNE U LOG"
python3 - <<'PY'
import json, subprocess
try:
    c = json.load(open("/opt/poprio/config.json"))
except Exception as e:
    print("  ne mogu pročitati config:", e); raise SystemExit
log = subprocess.run(["journalctl", "--since", "14 days ago", "--no-pager"],
                     capture_output=True, text=True).stdout
for k in ("cliniko_api_key", "solo_api_token", "smtp_password", "healthcheck_url"):
    v = str(c.get(k) or "")
    if len(v) > 8:
        print(f"  {k}: {'*** PROCURILO U LOG ***' if v in log else 'nema ga u logu'}")
PY

o "12. RADI LI POPRIO"
systemctl is-active poprio; systemctl is-enabled poprio
sudo -u poprio /opt/poprio/venv/bin/python /opt/poprio/sync.py --status 2>&1 | head -12
