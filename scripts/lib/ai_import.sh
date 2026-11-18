# shellcheck shell=bash
# `./makhzan ai import DIR`: the scores files of a locally scored AI backlog,
# taken to wherever the importer runs (worker/ai_import.py).
#
# DIR is always a folder on the machine the command was typed on, resolved
# against the operator's directory (ops_abspath, as backup and restore do).
# From a laptop the files are copied to a fresh temporary folder on the
# server first, so a same-named path on the server is never read; on the
# server they are streamed into a fresh temporary folder in the worker
# container, as its own user. Both temporary folders are removed when the
# command ends, however it ends. A folder with no scores-*.jsonl is refused
# before anything is copied or any container is touched.
#
# Needs ops_abspath (scripts/lib/ops.sh).

# ai_import_files DIR: the scores-*.jsonl files in DIR, one per line; fails,
# saying why, when DIR is not a folder or holds none.
ai_import_files() {
  local dir="$1" f found=0
  if [ ! -d "$dir" ]; then
    echo "no such folder: $dir" >&2
    return 1
  fi
  for f in "$dir"/scores-*.jsonl; do
    [ -f "$f" ] || continue
    printf '%s\n' "$f"
    found=1
  done
  if [ "$found" != 1 ]; then
    echo "no scores-*.jsonl in $dir: nothing to import" >&2
    return 1
  fi
}

AI_IMPORT_USAGE="usage: ./makhzan ai import DIR [--dry-run|--verify] [--policy NAME]"

# A failing command in an EXIT trap replaces the script's exit code, so every
# clean-up warns instead of failing: the import's own code is what is returned.

ai_import_remote_cleanup() {
  ssh "$AI_IMPORT_TARGET" rm -rf "$AI_IMPORT_REMOTE" ||
    echo "warning: could not remove $AI_IMPORT_TARGET:$AI_IMPORT_REMOTE; remove it by hand" >&2
}

# ai_import_remote TARGET DEPLOY_PATH DIR [ARGS...]: from a laptop. Copies the
# files to a new temporary folder on TARGET (user@host), runs the import
# there on that folder, and removes the folder afterwards.
ai_import_remote() {
  local deploy_path="$2" dir listing rc=0
  AI_IMPORT_TARGET="$1"
  dir="$(ops_abspath "${3:?$AI_IMPORT_USAGE}")"
  shift 3
  listing="$(ai_import_files "$dir")" || return 1
  local -a files
  mapfile -t files <<<"$listing"
  AI_IMPORT_REMOTE="$(ssh "$AI_IMPORT_TARGET" 'mktemp -d /tmp/makhzan-ai-import.XXXXXX')"
  case "$AI_IMPORT_REMOTE" in
    /tmp/makhzan-ai-import.*) ;;
    *)
      echo "could not make a temporary folder on $AI_IMPORT_TARGET" >&2
      return 1
      ;;
  esac
  trap ai_import_remote_cleanup EXIT
  echo "==> copying ${#files[@]} scores file(s) to $AI_IMPORT_TARGET:$AI_IMPORT_REMOTE"
  scp -q "${files[@]}" "$AI_IMPORT_TARGET:$AI_IMPORT_REMOTE/"
  # The deploy path is left unquoted so the remote shell expands a leading ~.
  ssh -t "$AI_IMPORT_TARGET" \
    "cd ${deploy_path} && ./makhzan ai import $(printf '%q ' "$AI_IMPORT_REMOTE" "$@")" || rc=$?
  trap - EXIT
  ai_import_remote_cleanup
  return "$rc"
}

ai_import_local_cleanup() {
  "${COMPOSE[@]}" exec -T ingestion rm -rf "$AI_IMPORT_TMP" ||
    echo "warning: could not remove $AI_IMPORT_TMP in the worker container" >&2
}

# ai_import_local DIR [ARGS...]: on the server. Streams the files into a new
# temporary folder in the worker container (COMPOSE must be set), as the
# container's own user so the importer can read them, runs the import on it,
# and removes it afterwards.
ai_import_local() {
  local dir listing f rc=0
  dir="$(ops_abspath "${1:?$AI_IMPORT_USAGE}")"
  shift
  listing="$(ai_import_files "$dir")" || return 1
  AI_IMPORT_TMP="$("${COMPOSE[@]}" exec -T ingestion mktemp -d /tmp/ai-import.XXXXXX)"
  case "$AI_IMPORT_TMP" in
    /tmp/ai-import.*) ;;
    *)
      echo "could not make a temporary folder in the worker container" >&2
      return 1
      ;;
  esac
  trap ai_import_local_cleanup EXIT
  while IFS= read -r f; do
    # Not `docker compose cp`, which writes as root with the host file's
    # mode: written by the app user, the file is the importer's to read.
    "${COMPOSE[@]}" exec -T ingestion sh -c 'cat > "$1"' sh \
      "$AI_IMPORT_TMP/$(basename "$f")" <"$f"
  done <<<"$listing"
  "${COMPOSE[@]}" exec -T ingestion python -m worker.ai import "$AI_IMPORT_TMP" "$@" || rc=$?
  trap - EXIT
  ai_import_local_cleanup
  return "$rc"
}
