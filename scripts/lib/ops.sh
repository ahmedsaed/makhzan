# shellcheck shell=bash
# Shared by the scripts that change the production stack. Source it from the
# repository root.

# ops_stack: which stack to act on. Production unless MAKHZAN_ENV_FILE says
# otherwise; MAKHZAN_COMPOSE_FILE likewise for the compose file. Sets COMPOSE
# (the docker compose command), STACK_ENV (the variables to repeat in any
# command printed for the operator, empty for production) and loads the env file.
#
# Prefixed names on purpose: a stray exported ENV_FILE or COMPOSE_FILE, which
# other tools use, must never point these scripts somewhere else.
ops_stack() {
  MAKHZAN_COMPOSE_FILE="${MAKHZAN_COMPOSE_FILE:-docker-compose.prod.yml}"
  MAKHZAN_ENV_FILE="${MAKHZAN_ENV_FILE:-.env.prod}"
  case "$MAKHZAN_ENV_FILE" in /* | ./* | ../*) ;; *) MAKHZAN_ENV_FILE="./$MAKHZAN_ENV_FILE" ;; esac
  # The compose file's env_file: follows it, as do the scripts these call.
  export MAKHZAN_COMPOSE_FILE MAKHZAN_ENV_FILE

  set -a
  # shellcheck disable=SC1090
  . "$MAKHZAN_ENV_FILE"
  set +a

  STACK_ENV=""
  if [ "$MAKHZAN_ENV_FILE" != ./.env.prod ] || [ "$MAKHZAN_COMPOSE_FILE" != docker-compose.prod.yml ]; then
    # Without its own project name, another env file still addresses the
    # production containers and volumes, with the wrong passwords.
    if [ -z "${COMPOSE_PROJECT_NAME:-}" ]; then
      echo "MAKHZAN_ENV_FILE/MAKHZAN_COMPOSE_FILE point away from production, but" >&2
      echo "COMPOSE_PROJECT_NAME is not set, so this would act on the production" >&2
      echo "containers. Set COMPOSE_PROJECT_NAME to the other stack's project." >&2
      exit 1
    fi
    export COMPOSE_PROJECT_NAME
    # shellcheck disable=SC2034 # read by the scripts that source this
    STACK_ENV="COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME MAKHZAN_ENV_FILE=$MAKHZAN_ENV_FILE MAKHZAN_COMPOSE_FILE=$MAKHZAN_COMPOSE_FILE "
  fi
  COMPOSE=(docker compose -f "$MAKHZAN_COMPOSE_FILE" --env-file "$MAKHZAN_ENV_FILE")
}

# ops_project: the compose project name the stack resolves to.
ops_project() {
  "${COMPOSE[@]}" config 2>/dev/null | sed -n 's/^name: //p' | head -1
}

# ops_lock NAME: one backup, restore or deploy at a time. A deploy mid-restore
# would start api, ingestion and migrate against a half-restored database; a
# backup mid-restore would dump one. Fails at once rather than queueing, so a
# collision is seen. A script run by one that holds the lock (backup-db.sh
# from restore-db.sh, deploy.sh re-executing itself) inherits it.
#
# The lock is fd 9, which every child inherits: anything started while holding
# it that may outlive the script (git's gc --auto, an ssh ControlPersist master)
# must be started with 9>&-, or it keeps the lock after the script is gone.
ops_lock() {
  [ "${MAKHZAN_OPS_LOCK_HELD:-}" = 1 ] && return 0
  # Deploys never needed backups/ before; a root-owned one (made by a backup run
  # under sudo) would otherwise stop them with a bare "Permission denied".
  if ! mkdir -p backups 2>/dev/null || ! (: >>backups/.ops.lock) 2>/dev/null; then
    echo "Cannot write the operations lock $PWD/backups/.ops.lock." >&2
    echo "Is backups/ owned by another user? Fix: sudo chown -R $(id -un) $PWD/backups" >&2
    exit 1
  fi
  exec 9>>backups/.ops.lock
  if ! flock -n 9; then
    echo "Another backup, restore or deploy holds the lock: $(cat backups/.ops.lock.owner 2>/dev/null || echo unknown)." >&2
    echo "Wait for it to finish. If that pid is gone, a process it left behind still" >&2
    echo "holds the lock; find it with: fuser -v backups/.ops.lock (or lsof backups/.ops.lock)" >&2
    exit 1
  fi
  echo "$1 (pid $$, since $(date '+%F %T'))" > backups/.ops.lock.owner
  export MAKHZAN_OPS_LOCK_HELD=1
}

# ops_production_only: for the commands that only ever act on production
# (deploy.sh, migrate.sh, ./makhzan). A stray exported MAKHZAN_ENV_FILE,
# MAKHZAN_COMPOSE_FILE or COMPOSE_PROJECT_NAME from testing another stack must
# not redirect them; docker compose itself reads the last.
ops_production_only() {
  local v
  for v in MAKHZAN_ENV_FILE MAKHZAN_COMPOSE_FILE COMPOSE_PROJECT_NAME; do
    if [ -n "${!v:-}" ]; then
      echo "note: ignoring $v=${!v}; this command acts on production only" >&2
      unset "$v"
    fi
  done
}

# ops_abspath PATH: PATH made absolute against the directory the operator ran
# the command from (the scripts cd to the repository root).
ops_abspath() {
  case "$1" in
    /*) printf '%s\n' "$1" ;;
    *) printf '%s/%s\n' "${MAKHZAN_CALLER_PWD:-$PWD}" "$1" ;;
  esac
}
