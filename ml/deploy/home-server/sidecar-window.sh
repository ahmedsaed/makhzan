#!/bin/sh
# Starts or stops one judge's llama.cpp sidecar on the home server's AMD card, around its worker's
# window. The 4 GB card holds one model, so starting a sidecar first stops the other one.
#
#   sidecar-window.sh start kev | stop kev | start pplx | stop pplx
#   sidecar-window.sh start-kev                 # one-word form, for the systemd template units
#   sidecar-window.sh boot                      # at boot: start whichever window's sidecar is due
#
# Run by the host's timers (install-sidecar-timers.sh): Kev's 00:55-05:03, pplx's 05:03:30-07:03,
# Africa/Cairo, around the workers' windows 01:00-05:00 and 05:05-07:00, and by a boot unit. The
# sidecars have `restart: "no"`: a server that was down at a start time, or a sidecar that crashed,
# comes back only through here, so the checks below always apply. Idempotent: starting a running
# sidecar or stopping a stopped one does nothing.
#
# Refuses to start a sidecar unless
#   - the card is in "manual" performance mode, which the udev rule 99-amdgpu-clock-limit.rules
#     sets together with the clock-state limit (without the limit a job on this card resets the
#     whole server; docs/ai/kev-llamacpp.md). sysfs cannot show the clock-state mask itself, so
#     "manual" is necessary, not sufficient: the rule sets both together;
#   - .env sets RENDER_GID and VIDEO_GID: without them the sidecar cannot open the card.
#
# Environment (tests and other layouts): MAKHZAN_AI_DIR (the compose stack's folder; default: this
# script's), DOCKER (default: docker), SYSFS (default: /sys), NOW (boot: the time as HHMMSS in
# Africa/Cairo; default: now), BOOT_WAIT_S (boot: how long to wait for the udev rule; default 60).
set -eu

STACK_DIR=${MAKHZAN_AI_DIR:-$(cd "$(dirname "$0")" && pwd)}
DOCKER=${DOCKER:-docker}
SYSFS=${SYSFS:-/sys}

log() { echo "sidecar-window: $*"; }
usage() { echo "usage: $0 start|stop kev|pplx  (or start-kev, stop-pplx, ...) | boot" >&2; exit 2; }
compose() { (cd "$STACK_DIR" && $DOCKER compose "$@"); }

# The amdgpu card's performance mode ("manual" once the udev rule has applied), or "none".
gpu_mode() {
  for h in "$SYSFS"/class/drm/card*/device/hwmon/hwmon*; do
    [ "$(cat "$h/name" 2>/dev/null)" = amdgpu ] || continue
    cat "$h/../../power_dpm_force_performance_level" 2>/dev/null && return 0
  done
  echo none
}

# KEY's value in the stack's .env (quotes stripped), or nothing.
env_value() {
  [ -f "$STACK_DIR/.env" ] || return 0
  sed -n "s/^$1=//p" "$STACK_DIR/.env" | tail -1 | tr -d "\"' \t\r"
}

# start | stop, kev | pplx
run() {
  action=$1
  case $2 in
    kev) service=kev-llamacpp; profile=llamacpp; other=pplx-llamacpp; other_profile=llamacpp-pplx ;;
    pplx) service=pplx-llamacpp; profile=llamacpp-pplx; other=kev-llamacpp; other_profile=llamacpp ;;
    *) usage ;;
  esac
  case $action in
    start)
      mode=$(gpu_mode)
      if [ "$mode" != manual ]; then
        log "REFUSED to start $service: the card's performance mode is '$mode', not 'manual'."
        log "Install the udev rule 99-amdgpu-clock-limit.rules (README.md): without its clock limit"
        log "a job on this card resets the server."
        exit 3
      fi
      if [ -z "$(env_value RENDER_GID)" ] || [ -z "$(env_value VIDEO_GID)" ]; then
        log "REFUSED to start $service: .env must set RENDER_GID and VIDEO_GID"
        log "(getent group render video): without them the sidecar cannot open the card."
        exit 4
      fi
      log "stopping $other first (the card holds one model)"
      compose --profile "$other_profile" stop "$other"
      log "starting $service"
      compose --profile "$profile" up -d "$service"
      ;;
    stop)
      log "stopping $service"
      compose --profile "$profile" stop "$service"
      ;;
    *) usage ;;
  esac
}

# At boot: which sidecar window is it now (Africa/Cairo)? The timers' own times: Kev's
# 00:55:00-05:03:00, pplx's 05:03:30-07:03:00. Waits up to BOOT_WAIT_S for the udev rule, which may
# apply after Docker is up, then starts it through the same checks as a timer.
boot() {
  now=${NOW:-$(TZ=Africa/Cairo date +%H%M%S)}
  now=$(expr "$now" + 0)
  if [ "$now" -ge 5500 ] && [ "$now" -lt 50300 ]; then due=kev
  elif [ "$now" -ge 50330 ] && [ "$now" -lt 70300 ]; then due=pplx
  else
    log "boot at $now (Africa/Cairo): outside the sidecar windows, nothing to start"
    return 0
  fi
  log "boot inside $due's sidecar window"
  waited=0
  while [ "$(gpu_mode)" != manual ] && [ "$waited" -lt "${BOOT_WAIT_S:-60}" ]; do
    sleep 5
    waited=$((waited + 5))
  done
  run start "$due"
}

if [ $# -eq 1 ]; then
  case $1 in
    boot) boot ;;
    *-*) run "${1%%-*}" "${1#*-}" ;;
    *) usage ;;
  esac
elif [ $# -eq 2 ]; then
  run "$1" "$2"
else
  usage
fi
