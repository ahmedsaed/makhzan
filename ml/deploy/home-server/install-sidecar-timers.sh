#!/bin/sh
# Installs (or removes) the systemd timers that start and stop the llama.cpp sidecars around the
# workers' windows. Run as root from the compose stack's folder (the one holding compose.yml and
# sidecar-window.sh):
#
#   sudo sh install-sidecar-timers.sh            # install and enable
#   sudo sh install-sidecar-timers.sh remove     # disable and remove
#   systemctl list-timers 'makhzan-sidecar-*'    # check the next runs
#   journalctl -u 'makhzan-sidecar@*'            # what each run did
#
# System units run as the invoking user (SUDO_USER, who must be in the docker group), so no
# lingering user session is needed. The times carry their own time zone (systemd >= 245), so the
# server's UTC clock does not matter:
#   00:55:00  start-kev    5 min before Kev's 01:00 window
#   05:03:00  stop-kev     Kev's last request ends by about 05:01:40 (60 s GPU timeout + posts)
#   05:03:30  start-pplx   (stops Kev's first anyway) 90 s before pplx's 05:05 window
#   07:03:00  stop-pplx    pplx's last request ends by about 07:01:40
set -eu
[ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }
STACK_DIR=$(cd "$(dirname "$0")" && pwd)
RUN_AS=${SUDO_USER:?run with sudo from your own account}
UNITS=/etc/systemd/system
TZONE=Africa/Cairo
TIMERS="start-kev:00:55:00 stop-kev:05:03:00 start-pplx:05:03:30 stop-pplx:07:03:00"

if [ "${1:-}" = remove ]; then
  for t in $TIMERS; do
    name=${t%%:*}
    systemctl disable --now "makhzan-sidecar-$name.timer" 2>/dev/null || true
    rm -f "$UNITS/makhzan-sidecar-$name.timer"
  done
  rm -f "$UNITS/makhzan-sidecar@.service"
  systemctl daemon-reload
  echo "removed the makhzan sidecar timers"
  exit 0
fi

[ -x "$STACK_DIR/sidecar-window.sh" ] || chmod +x "$STACK_DIR/sidecar-window.sh"
id -nG "$RUN_AS" | tr ' ' '\n' | grep -qx docker || { echo "$RUN_AS is not in the docker group"; exit 1; }

cat > "$UNITS/makhzan-sidecar@.service" <<EOF
[Unit]
Description=makhzan AI: %i (llama.cpp sidecar on the AMD card)
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
User=$RUN_AS
Environment=MAKHZAN_AI_DIR=$STACK_DIR
ExecStart=$STACK_DIR/sidecar-window.sh %i
EOF

for t in $TIMERS; do
  name=${t%%:*}; at=${t#*:}
  cat > "$UNITS/makhzan-sidecar-$name.timer" <<EOF
[Unit]
Description=makhzan AI: $name at $at $TZONE

[Timer]
OnCalendar=*-*-* $at $TZONE
AccuracySec=1s
Persistent=false
Unit=makhzan-sidecar@$name.service

[Install]
WantedBy=timers.target
EOF
done

systemctl daemon-reload
for t in $TIMERS; do systemctl enable --now "makhzan-sidecar-${t%%:*}.timer"; done
systemctl list-timers 'makhzan-sidecar-*' --no-pager
