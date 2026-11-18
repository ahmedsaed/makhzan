# shellcheck shell=bash
# `./makhzan ai import DIR`: the scores files of a locally scored AI backlog,
# taken to wherever the importer runs (worker/ai_import.py).
#
# DIR is always a folder on the machine the command was typed on, resolved
# against the operator's directory (ops_abspath, as backup and restore do).
# From a laptop the files are copied to a fresh temporary folder on the
# server first, so a same-named path on the server is never read; on the
# server they are copied into a fresh temporary folder in the worker
# container. Both temporary folders are removed when the command ends,
# however it ends. A folder with no scores-*.jsonl is refused before anything
# is copied or any container is touched.
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

# ai_import_remote TARGET DEPLOY_PATH DIR [ARGS...]: from a laptop. Copies the
# files to a new temporary folder on TARGET (user@host), runs the import
# there on that folder, and removes the folder afterwards.
ai_import_remote() {
  local target="$1" deploy_path="$2" dir listing remote rc=0
  dir="$(ops_abspath "${3:?$AI_IMPORT_USAGE}")"
  shift 3
  listing="$(ai_import_files "$dir")" || return 1
  local -a files
  mapfile -t files <<<"$listing"
  remote="$(ssh "$target" 'mktemp -d /tmp/makhzan-ai-import.XXXXXX')"
  case "$remote" in
    /tmp/makhzan-ai-import.*) ;;
    *)
      echo "could not make a temporary folder on $target" >&2
      return 1
      ;;
  esac
  AI_IMPORT_REMOTE_CLEANUP="ssh $(printf '%q' "$target") rm -rf $(printf '%q' "$remote")"
  trap 'eval "$AI_IMPORT_REMOTE_CLEANUP"' EXIT
  echo "==> copying ${#files[@]} scores file(s) to $target:$remote"
  scp -q "${files[@]}" "$target:$remote/"
  # The deploy path is left unquoted so the remote shell expands a leading ~.
  ssh -t "$target" "cd ${deploy_path} && ./makhzan ai import $(printf '%q ' "$remote" "$@")" || rc=$?
  eval "$AI_IMPORT_REMOTE_CLEANUP"
  trap - EXIT
  return "$rc"
}

# ai_import_local DIR [ARGS...]: on the server. Copies the files into a new
# temporary folder in the worker container (COMPOSE must be set), runs the
# import on it, and removes it afterwards.
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
  trap '"${COMPOSE[@]}" exec -T ingestion rm -rf "$AI_IMPORT_TMP"' EXIT
  while IFS= read -r f; do
    "${COMPOSE[@]}" cp "$f" "ingestion:$AI_IMPORT_TMP/$(basename "$f")"
  done <<<"$listing"
  "${COMPOSE[@]}" exec -T ingestion python -m worker.ai import "$AI_IMPORT_TMP" "$@" || rc=$?
  "${COMPOSE[@]}" exec -T ingestion rm -rf "$AI_IMPORT_TMP"
  trap - EXIT
  return "$rc"
}
