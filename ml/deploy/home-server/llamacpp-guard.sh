#!/bin/sh
# The llama.cpp router's entrypoint (compose.yml, service "llamacpp"): it refuses to start unless
# the AMD card is held to its safe clock states, then runs llama-server with the arguments given.
#
# Why: at its top clock and voltage states the card's power feed (a SATA adapter on the original
# 320 W supply) cuts out and hard-resets the whole server (docs/ai/kev-llamacpp.md). The host's
# udev rule 99-amdgpu-clock-limit.rules holds it to states 0-2, which needs manual mode; without
# the rule the mode reads "auto" and this refuses. Containers see the host's /sys read-only, so
# the check needs no mount. sysfs cannot show the state mask itself, so "manual" is necessary,
# not sufficient: the rule writes both together (README.md).
#
# A refusal is an exit, which `restart: unless-stopped` repeats: a restart loop with this
# message in `docker compose logs llamacpp`, never an unlimited card.
# GUARD_SYSFS and LLAMA_SERVER exist for the tests only; compose sets neither.
set -u
found=0
for f in "${GUARD_SYSFS:-/sys}"/class/drm/card*/device/power_dpm_force_performance_level; do
  [ -r "$f" ] || continue
  found=1
  mode=$(cat "$f")
  if [ "$mode" != manual ]; then
    echo "llamacpp-guard: $f reads '$mode', not 'manual': the clock-limit udev rule" \
      "(99-amdgpu-clock-limit.rules) is not applied. Refusing to start." >&2
    exit 1
  fi
done
if [ "$found" = 0 ]; then
  echo "llamacpp-guard: no AMD card's clock mode found under ${GUARD_SYSFS:-/sys}/class/drm." \
    "Refusing to start." >&2
  exit 1
fi
exec "${LLAMA_SERVER:-/app/llama-server}" "$@"
