#!/bin/sh
# Starts or stops one judge's llama.cpp sidecar on the home server's AMD card, around its worker's
# window. The 4 GB card holds one model, so starting a sidecar first stops the other one.
#
#   sidecar-window.sh start kev | stop kev | start pplx | stop pplx
#   sidecar-window.sh start-kev                 # one-word form, for the systemd template units
#
# Run by the host's timers (install-sidecar-timers.sh): Kev's 00:55-05:03, pplx's 05:03-07:03,
# Africa/Cairo, around the workers' windows 01:00-05:00 and 05:05-07:00. Idempotent: starting a
# running sidecar or stopping a stopped one does nothing.
#
# Refuses to start a sidecar unless the card is in "manual" performance mode, which the udev rule
# 99-amdgpu-clock-limit.rules sets together with the clock-state limit: without the limit, a job on
# this card resets the whole server (docs/ai/kev-llamacpp.md).
#
# Environment (tests and other layouts): MAKHZAN_AI_DIR (the compose stack's folder; default: this
# script's), DOCKER (default: docker), SYSFS (default: /sys).
set -eu

STACK_DIR=${MAKHZAN_AI_DIR:-$(cd "$(dirname "$0")" && pwd)}
DOCKER=${DOCKER:-docker}
SYSFS=${SYSFS:-/sys}

log() { echo "sidecar-window: $*"; }
usage() { echo "usage: $0 start|stop kev|pplx  (or start-kev, stop-pplx, ...)" >&2; exit 2; }

if [ $# -eq 1 ]; then
  case $1 in *-*) action=${1%%-*}; model=${1#*-} ;; *) usage ;; esac
elif [ $# -eq 2 ]; then
  action=$1; model=$2
else
  usage
fi

case $model in
  kev) service=kev-llamacpp; profile=llamacpp; other=pplx-llamacpp; other_profile=llamacpp-pplx ;;
  pplx) service=pplx-llamacpp; profile=llamacpp-pplx; other=kev-llamacpp; other_profile=llamacpp ;;
  *) usage ;;
esac

compose() { (cd "$STACK_DIR" && $DOCKER compose "$@"); }

# The amdgpu card's performance mode ("manual" once the udev rule has applied), or "none".
gpu_mode() {
  for h in "$SYSFS"/class/drm/card*/device/hwmon/hwmon*; do
    [ "$(cat "$h/name" 2>/dev/null)" = amdgpu ] || continue
    cat "$h/../../power_dpm_force_performance_level" 2>/dev/null && return 0
  done
  echo none
}

case $action in
  start)
    mode=$(gpu_mode)
    if [ "$mode" != manual ]; then
      log "REFUSED to start $service: the card's performance mode is '$mode', not 'manual'."
      log "Install the udev rule 99-amdgpu-clock-limit.rules (README.md): without its clock limit"
      log "a job on this card resets the server."
      exit 3
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
