#!/usr/bin/env bash
# Ask each supplier host what it thinks of us, from wherever this is run.
#
#   ./scripts/probe-suppliers.sh
#
# Written for the question CLAUDE.md tells you to ask first when a source starts
# returning 403/429: is it the User-Agent, or is it us? It sends the crawler's
# exact headers at two browser versions, so a WAF objecting to a stale version
# looks different from one objecting to the address.
#
# Run it on the server and on a laptop and compare. Same result in both places
# means the header or the site; different results mean the egress IP, and no
# amount of header tuning will help.
#
# Read-only: two requests per host, several seconds apart.
set -u

OLD_VERSION="${OLD_VERSION:-139}"
NEW_VERSION="${NEW_VERSION:-153}"
DELAY="${DELAY:-5}"

# Which hosts to ask is configuration, not code: one "label|url" per line, each
# the same endpoint the adapter actually calls, so a WAF rule scoped to the API
# path still shows up. It lives in the private configuration beside this repo
# (probe-sites.txt); point SITES_FILE elsewhere to use another list.
here="$(cd "$(dirname "$0")/.." && pwd)"
SITES_FILE="${SITES_FILE:-${MAKHZAN_CONFIG_DIR:-$here/../makhzan-config}/probe-sites.txt}"
if [ ! -f "$SITES_FILE" ]; then
  echo "No site list at $SITES_FILE (set SITES_FILE, or clone the private configuration there)." >&2
  exit 1
fi
SITES="$(grep -v '^[[:space:]]*#' "$SITES_FILE")"

probe() { # host-label, url, chrome-version
  curl -sS -o /dev/null -m 25 --compressed \
    -w '%{http_code}' \
    -H "User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/$3.0.0.0 Safari/537.36" \
    -H 'Accept: application/json, text/plain, */*' \
    -H 'Accept-Language: en-US,en;q=0.9,ar;q=0.8' \
    -H "sec-ch-ua: \"Chromium\";v=\"$3\", \"Not;A=Brand\";v=\"99\"" \
    -H 'sec-ch-ua-mobile: ?0' \
    -H 'sec-ch-ua-platform: "Linux"' \
    -H 'Sec-Fetch-Dest: empty' \
    -H 'Sec-Fetch-Mode: cors' \
    -H 'Sec-Fetch-Site: same-origin' \
    -H 'From: crawler@merope.dev' \
    "$2" 2>/dev/null || echo "ERR"
}

echo "egress IP: $(curl -sS -m 15 https://api.ipify.org 2>/dev/null || echo unknown)"
echo "host:      $(hostname)"
echo
printf '%-12s %-18s %-18s\n' "source" "Chrome/$OLD_VERSION" "Chrome/$NEW_VERSION"
printf '%-12s %-18s %-18s\n' "------" "---------" "---------"

echo "$SITES" | while IFS='|' read -r name url; do
  [ -n "$name" ] || continue
  old=$(probe "$name" "$url" "$OLD_VERSION"); sleep "$DELAY"
  new=$(probe "$name" "$url" "$NEW_VERSION"); sleep "$DELAY"
  printf '%-12s %-18s %-18s\n' "$name" "$old" "$new"
done

echo
echo "200 everywhere        → the hosts are fine with us from here."
echo "403/429 in both cols  → not the browser version. Compare with another IP."
echo "403 old, 200 new      → the User-Agent was stale; bump CHROME_VERSION."
