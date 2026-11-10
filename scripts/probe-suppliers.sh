#!/usr/bin/env bash
# Ask each supplier host what it thinks of us, from wherever this is run.
#
#   ./scripts/probe-suppliers.sh                 # identity mode (the default)
#   MODE=versions ./scripts/probe-suppliers.sh   # two browser versions
#
# Identity mode is the check to run before switching a shop to the honest
# `makhzanbot` identity (docs/crawler-identity.md). For each host it sends:
#
#   browser     the headers sources use today (worker/identity.py BROWSER_HEADERS)
#   makhzanbot  the honest identity, unsigned
#   signed      makhzanbot with a fresh Web Bot Auth signature — only when a key
#               is available to SIGN_CMD (below); "-" otherwise
#
# A shop answering 200 to makhzanbot can be switched. One that refuses
# makhzanbot but serves the browser is a shop to write to (and, once the key is
# registered, to re-probe signed) — never a reason to keep looking like a
# browser. Versions mode compares two Chrome versions; it exists to tell a stale
# header from an address problem, not to find a version that gets past a WAF.
#
# Run it on the server and on a laptop and compare. Same result in both places
# means the headers or the site; different results mean the egress IP, and no
# header will fix an address problem.
#
# Read-only: one GET per column per host, at least 15 s apart on the same host
# (the crawler's own pace). Nothing is retried.
set -u

MODE="${MODE:-identity}"
DELAY="${DELAY:-15}"
if [ "${DELAY%.*}" -lt 15 ]; then
  echo "DELAY is at least 15 seconds (the crawler's pace); using 15." >&2
  DELAY=15
fi
CHROME_VERSION="${CHROME_VERSION:-153}"   # what worker/identity.py sends today
OLD_VERSION="${OLD_VERSION:-139}"
NEW_VERSION="${NEW_VERSION:-$CHROME_VERSION}"
CONTACT="crawler@merope.dev"

here="$(cd "$(dirname "$0")/.." && pwd)"

# Which hosts to ask is configuration, not code: one "label|url" per line, each
# the same endpoint the adapter actually calls, so a WAF rule scoped to the API
# path still shows up. It lives in the private configuration beside this repo
# (probe-sites.txt); point SITES_FILE elsewhere to use another list.
SITES_FILE="${SITES_FILE:-${MAKHZAN_CONFIG_DIR:-$here/../makhzan-config}/probe-sites.txt}"
if [ ! -f "$SITES_FILE" ]; then
  echo "No site list at $SITES_FILE (set SITES_FILE, or clone the private configuration there)." >&2
  exit 1
fi
SITES="$(grep -v '^[[:space:]]*#' "$SITES_FILE")"

# makhzanbot's User-Agent names the public site, which is configuration: SITE_URL,
# else the one in .env.prod.
if [ -z "${SITE_URL:-}" ] && [ -f "$here/.env.prod" ]; then
  SITE_URL="$(sed -n 's/^SITE_URL=//p' "$here/.env.prod" | tail -n1)"
fi
SITE_URL="${SITE_URL%/}"
export SITE_URL

# Prints the signed makhzanbot headers for a URL, one "Name: value" per line.
# On the server, where the worker's environment holds the key:
#   SIGN_CMD="docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T ingestion python -m worker.botauth headers --sign"
SIGN_CMD="${SIGN_CMD:-poetry -C $here/apps/ingestion run python -m worker.botauth headers --sign}"

browser_headers() { # chrome-version
  BH=(
    -H "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/$1.0.0.0 Safari/537.36"
    -H 'Accept: application/json, text/plain, */*'
    -H 'Accept-Language: en-US,en;q=0.9,ar;q=0.8'
    -H "sec-ch-ua: \"Chromium\";v=\"$1\", \"Not;A=Brand\";v=\"99\""
    -H 'sec-ch-ua-mobile: ?0'
    -H 'sec-ch-ua-platform: "Linux"'
    -H 'Sec-Fetch-Dest: empty'
    -H 'Sec-Fetch-Mode: cors'
    -H 'Sec-Fetch-Site: same-origin'
    -H "From: $CONTACT"
  )
}

bot_headers() {
  BH=(
    -H "User-Agent: makhzanbot/1.0 (+$SITE_URL/how-we-crawl; $CONTACT)"
    -H 'Accept: application/json, text/html;q=0.9, */*;q=0.8'
    -H 'Accept-Language: en-US,en;q=0.9,ar;q=0.8'
    -H "From: $CONTACT"
  )
}

signed_headers() { # url — fresh signature (60 s lifetime), so built right before sending
  BH=()
  local line
  while IFS= read -r line; do
    [ -n "$line" ] && BH+=(-H "$line")
  done < <($SIGN_CMD "$1" 2>/dev/null)
  [ "${#BH[@]}" -gt 0 ]
}

probe() { # url — sends BH
  curl -sS -o /dev/null -m 25 --compressed -w '%{http_code}' "${BH[@]}" "$1" 2>/dev/null || echo "ERR"
}

echo "egress IP: $(curl -sS -m 15 https://api.ipify.org 2>/dev/null || echo unknown)"
echo "host:      $(hostname)"
echo

case "$MODE" in
  identity)
    if [ -z "$SITE_URL" ]; then
      echo "Set SITE_URL (the public site, e.g. from .env.prod): makhzanbot's User-Agent names it." >&2
      exit 1
    fi
    can_sign=no
    if signed_headers "$SITE_URL/"; then can_sign=yes; fi
    echo "makhzanbot UA: makhzanbot/1.0 (+$SITE_URL/how-we-crawl; $CONTACT)"
    echo "signing:       $can_sign$([ "$can_sign" = no ] && echo " (no key for SIGN_CMD; the signed column is skipped)")"
    echo
    printf '%-12s %-10s %-12s %-10s\n' "source" "browser" "makhzanbot" "signed"
    printf '%-12s %-10s %-12s %-10s\n' "------" "-------" "----------" "------"
    echo "$SITES" | while IFS='|' read -r name url; do
      [ -n "$name" ] || continue
      browser_headers "$CHROME_VERSION"; b=$(probe "$url"); sleep "$DELAY"
      bot_headers; m=$(probe "$url")
      s="-"
      if [ "$can_sign" = yes ]; then
        sleep "$DELAY"
        if signed_headers "$url"; then s=$(probe "$url"); else s="ERR"; fi
      fi
      printf '%-12s %-10s %-12s %-10s\n' "$name" "$b" "$m" "$s"
      sleep "$DELAY"
    done
    echo
    echo "200 for makhzanbot       → the shop can be switched (docs/crawler-identity.md)."
    echo "browser 200, bot 403/429 → the shop's edge refuses unknown bots. Register the key,"
    echo "                           re-probe signed, and write to the shop. A shop already"
    echo "                           on makhzanbot is not switched back to get past it."
    echo "403/429 in every column  → not the headers. Compare with another IP."
    ;;
  versions)
    printf '%-12s %-18s %-18s\n' "source" "Chrome/$OLD_VERSION" "Chrome/$NEW_VERSION"
    printf '%-12s %-18s %-18s\n' "------" "---------" "---------"
    echo "$SITES" | while IFS='|' read -r name url; do
      [ -n "$name" ] || continue
      browser_headers "$OLD_VERSION"; old=$(probe "$url"); sleep "$DELAY"
      browser_headers "$NEW_VERSION"; new=$(probe "$url"); sleep "$DELAY"
      printf '%-12s %-18s %-18s\n' "$name" "$old" "$new"
    done
    echo
    echo "200 everywhere        → the hosts are fine with us from here."
    echo "403/429 in both cols  → not the browser version. Compare with another IP."
    echo "403 old, 200 new      → the shop scores browser versions. That is a bot check doing"
    echo "                        its job: switch the shop to makhzanbot (MODE=identity first)."
    ;;
  *)
    echo "MODE is identity or versions, not '$MODE'." >&2
    exit 1
    ;;
esac
