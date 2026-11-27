#!/bin/sh
# Installs (or removes) the systemd units that start and stop the llama.cpp sidecars around the
# workers' windows. Run as root from the compose stack's folder (the one holding compose.yml and
# sidecar-window.sh):
#
#   sudo sh install-sidecar-timers.sh            # install and enable
#   sudo sh install-sidecar-timers.sh remove     # disable and remove
#   systemctl list-timers 'makhzan-sidecar-*'    # check the next runs
#   journalctl -u 'makhzan-sidecar*'             # what each run did
#
# System units run as the invoking user (SUDO_USER, who must be in the docker group), so no
# lingering user session is needed. The times carry their own time zone (systemd >= 245), so the
# server's UTC clock does not matter:
#   00:55:00  start-kev    5 min before Kev's 01:00 window
#   01:00:20  start-kev    again (idempotent): on the night Egypt's clocks spring forward
#                          (00:00 -> 01:00, the last Friday of April) 00:55 does not exist
#   05:03:00  stop-kev     Kev's last request ends by about 05:01:40 (60 s GPU timeout + posts)
#   05:03:30  start-pplx   (stops Kev's first anyway) 90 s before pplx's 05:05 window
#   07:03:00  stop-pplx    pplx's last request ends by about 07:01:40
# and makhzan-sidecar-boot.service, after Docker at every boot: `sidecar-window.sh boot` starts the
# sidecar whose window it is (the sidecars have `restart: "no"`, so nothing else would).
#
# MAKHZAN_UNITS_DIR (tests): write the units there and skip systemctl and the root checks.
set -eu
STACK_DIR=$(cd "$(dirname "$0")" && pwd)
UNITS=${MAKHZAN_UNITS_DIR:-/etc/systemd/system}
TZONE=Africa/Cairo
TIMERS="start-kev:00:55:00,01:00:20 stop-kev:05:03:00 start-pplx:05:03:30 stop-pplx:07:03:00"

systemd() { [ -n "${MAKHZAN_UNITS_DIR:-}" ] || systemctl "$@"; }

if [ -z "${MAKHZAN_UNITS_DIR:-}" ]; then
  [ "$(id -u)" = 0 ] || { echo "run as root (sudo)"; exit 1; }
fi
RUN_AS=${SUDO_USER:?run with sudo from your own account}

if [ "${1:-}" = remove ]; then
  for t in $TIMERS; do
    name=${t%%:*}
    systemd disable --now "makhzan-sidecar-$name.timer" 2>/dev/null || true
    rm -f "$UNITS/makhzan-sidecar-$name.timer"
  done
  systemd disable makhzan-sidecar-boot.service 2>/dev/null || true
  rm -f "$UNITS/makhzan-sidecar@.service" "$UNITS/makhzan-sidecar-boot.service"
  systemd daemon-reload
  echo "removed the makhzan sidecar units"
  exit 0
fi

[ -x "$STACK_DIR/sidecar-window.sh" ] || chmod +x "$STACK_DIR/sidecar-window.sh"
if [ -z "${MAKHZAN_UNITS_DIR:-}" ]; then
  id -nG "$RUN_AS" | tr ' ' '\n' | grep -qx docker || { echo "$RUN_AS is not in the docker group"; exit 1; }
fi

cat > "$UNITS/makhzan-sidecar@.service" <<UNIT
[Unit]
Description=makhzan AI: %i (llama.cpp sidecar on the AMD card)
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
User=$RUN_AS
Environment=MAKHZAN_AI_DIR=$STACK_DIR
ExecStart=$STACK_DIR/sidecar-window.sh %i
# A hung docker compose must not block the next activation (01:00:20 after 00:55, say).
TimeoutStartSec=180
UNIT

cat > "$UNITS/makhzan-sidecar-boot.service" <<UNIT
[Unit]
Description=makhzan AI: start the due llama.cpp sidecar at boot
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
User=$RUN_AS
Environment=MAKHZAN_AI_DIR=$STACK_DIR
ExecStart=$STACK_DIR/sidecar-window.sh boot
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
UNIT

for t in $TIMERS; do
  name=${t%%:*}
  ats=${t#*:}
  {
    printf '[Unit]\nDescription=makhzan AI: %s at %s %s\n\n[Timer]\n' "$name" "$ats" "$TZONE"
    for at in $(echo "$ats" | tr ',' ' '); do
      printf 'OnCalendar=*-*-* %s %s\n' "$at" "$TZONE"
    done
    printf 'AccuracySec=1s\nPersistent=false\nUnit=makhzan-sidecar@%s.service\n\n' "$name"
    printf '[Install]\nWantedBy=timers.target\n'
  } > "$UNITS/makhzan-sidecar-$name.timer"
done

systemd daemon-reload
systemd enable makhzan-sidecar-boot.service
for t in $TIMERS; do systemd enable --now "makhzan-sidecar-${t%%:*}.timer"; done
systemd list-timers 'makhzan-sidecar-*' --no-pager
echo "installed the makhzan sidecar units in $UNITS"
