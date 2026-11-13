# shellcheck shell=bash
# Backup retention, sourced by backup-db.sh and run in the checkout's root
# (tests source it in a scratch directory: apps/ingestion/tests/test_backup_prune.py).
#
# Regular backups (backups/makhzan-*.dump and legacy *.sql.gz):
#   - the 14 newest at most, and
#   - none older than 30 days, because a dump holds what the privacy page
#     says is erased (a report's email after 90 days, an address hash after
#     24 hours) and /privacy promises a backup keeps it at most 30 days more.
#     The newest backup is kept even when it is older than that, so a server
#     whose backups lapsed is never left with none.
# Safety copies (*-pre-restore.dump): a week of them, never fewer than the 3
# newest, so repeated restore attempts never push out the copy taken before
# the trouble began; but none older than 30 days either, for the same reason
# as regular backups (even the newest: a safety copy is never the only one).
#
# MAKHZAN_KEEP_FILE (a realpath) names one file never to prune: the one being
# restored. Pruning failures are the caller's to report as warnings.

#: Regular backups older than this many days are deleted (all but the newest).
BACKUP_MAX_DAYS=30

# prune KEEP DAYS FILE...: delete every FILE beyond the KEEP newest that is also
# older than DAYS days (DAYS 0: age does not matter). Never MAKHZAN_KEEP_FILE.
prune() {
  local keep="$1" days="$2" f i=0
  shift 2
  [ "$#" -gt "$keep" ] || return 0
  # shellcheck disable=SC2012 # our own names, no newlines
  ls -1td -- "$@" | while read -r f; do
    i=$((i + 1))
    [ "$i" -gt "$keep" ] || continue
    [ "$days" = 0 ] || [ -n "$(find "$f" -maxdepth 0 -mmin +"$((days * 1440))")" ] || continue
    [ "$(realpath -- "$f")" != "${MAKHZAN_KEEP_FILE:-}" ] || continue
    rm -- "$f" || echo "warning: could not prune $f" >&2
  done
}

# prune_backups: apply the rules above to ./backups.
prune_backups() {
  local f status=0
  local -a regular=()
  shopt -s nullglob
  for f in backups/makhzan-*.dump backups/makhzan-*.sql.gz; do
    case "$f" in *-pre-restore.dump) ;; *) regular+=("$f") ;; esac
  done
  prune 14 0 "${regular[@]}" || status=1
  # Then by age: everything past 30 days but the newest (keep 1).
  regular=()
  for f in backups/makhzan-*.dump backups/makhzan-*.sql.gz; do
    case "$f" in *-pre-restore.dump) ;; *) regular+=("$f") ;; esac
  done
  prune 1 "$BACKUP_MAX_DAYS" "${regular[@]}" || status=1
  prune 3 7 backups/makhzan-*-pre-restore.dump || status=1
  prune 0 "$BACKUP_MAX_DAYS" backups/makhzan-*-pre-restore.dump || status=1
  return "$status"
}
