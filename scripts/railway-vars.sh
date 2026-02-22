#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────
# railway-vars.sh — Manage environment variables for the
# "caring-alignment" Railway project.
#
# Usage:
#   ./scripts/railway-vars.sh list   [service]            List all variables
#   ./scripts/railway-vars.sh get    [service] KEY        Get a single variable
#   ./scripts/railway-vars.sh set    [service] KEY=VALUE  Set / update a variable
#   ./scripts/railway-vars.sh delete [service] KEY        Delete a variable
#
# Services: ghost (default) | pgvector | MySQL
#
# Examples:
#   ./scripts/railway-vars.sh list
#   ./scripts/railway-vars.sh list pgvector
#   ./scripts/railway-vars.sh get ghost GHOST_ADMIN_API_KEY
#   ./scripts/railway-vars.sh set ghost url=https://example.com
#   ./scripts/railway-vars.sh delete MySQL OLD_VAR
# ────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration ───────────────────────────────────────────────
PROJECT_NAME="caring-alignment"
DEFAULT_SERVICE="ghost"
ENVIRONMENT="production"
VALID_SERVICES=("ghost" "pgvector" "MySQL")

# ── Colours (disabled when piped) ───────────────────────────────
if [[ -t 1 ]]; then
  RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
  CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
else
  RED=''; GREEN=''; YELLOW=''; CYAN=''; BOLD=''; NC=''
fi

# ── Helpers ─────────────────────────────────────────────────────
info()  { printf "${CYAN}ℹ ${NC}%s\n" "$*"; }
ok()    { printf "${GREEN}✔ ${NC}%s\n" "$*"; }
warn()  { printf "${YELLOW}⚠ ${NC}%s\n" "$*" >&2; }
error() { printf "${RED}✖ ${NC}%s\n" "$*" >&2; exit 1; }

usage() {
  sed -n '2,/^# ─.*─$/{ /^# ─.*─$/!s/^# //p; }' "$0"
  exit 0
}

# ── Pre-flight checks ──────────────────────────────────────────
preflight() {
  command -v railway >/dev/null 2>&1 \
    || error "Railway CLI not found. Install: https://docs.railway.app/guides/cli"

  railway whoami >/dev/null 2>&1 \
    || error "Not logged in. Run: railway login"

  # Ensure we're linked to the correct project
  local status
  status=$(railway status 2>&1) || true

  if ! echo "$status" | grep -q "$PROJECT_NAME"; then
    warn "Not linked to $PROJECT_NAME — linking now…"
    railway link 2>&1 \
      || error "Failed to link project. Run: railway link"
  fi

  info "Project: ${BOLD}$PROJECT_NAME${NC}  Environment: ${BOLD}$ENVIRONMENT${NC}"
}

# ── Service validation ──────────────────────────────────────────
validate_service() {
  local svc="$1"
  for valid in "${VALID_SERVICES[@]}"; do
    [[ "$svc" == "$valid" ]] && return 0
  done
  error "Unknown service '$svc'. Valid services: ${VALID_SERVICES[*]}"
}

# Link to the requested service (idempotent)
use_service() {
  local svc="$1"
  validate_service "$svc"
  railway service "$svc" >/dev/null 2>&1 \
    || error "Failed to select service '$svc'"
  info "Service: ${BOLD}$svc${NC}"
}

# ── Commands ────────────────────────────────────────────────────
cmd_list() {
  local svc="${1:-$DEFAULT_SERVICE}"
  use_service "$svc"
  railway variables
}

cmd_get() {
  local svc="${1:-$DEFAULT_SERVICE}"
  local key="${2:?Missing KEY argument}"
  use_service "$svc"

  local val
  val=$(railway variables --json 2>/dev/null \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('$key',''))" 2>/dev/null) \
    || val=$(railway variables 2>/dev/null | grep -E "^\s*$key\s" | awk -F'│' '{gsub(/^[ \t]+|[ \t]+$/,"",$2); print $2}')

  if [[ -z "$val" ]]; then
    error "Variable '$key' not found in service '$svc'"
  fi
  printf "%s=%s\n" "$key" "$val"
}

cmd_set() {
  local svc="${1:-$DEFAULT_SERVICE}"
  local pair="${2:?Missing KEY=VALUE argument}"

  [[ "$pair" == *=* ]] || error "Expected KEY=VALUE format, got: $pair"

  local key="${pair%%=*}"
  local value="${pair#*=}"

  use_service "$svc"
  railway variables set "$key=$value" 2>&1 \
    || error "Failed to set variable '$key'"

  ok "Set ${BOLD}$key${NC} on service ${BOLD}$svc${NC}"
}

cmd_delete() {
  local svc="${1:-$DEFAULT_SERVICE}"
  local key="${2:?Missing KEY argument}"
  use_service "$svc"

  # Safety prompt
  if [[ -t 0 ]]; then
    printf "${YELLOW}Delete ${BOLD}%s${NC}${YELLOW} from ${BOLD}%s${NC}? [y/N] " "$key" "$svc"
    read -r confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || { info "Aborted."; exit 0; }
  fi

  railway variables set "$key=" 2>&1 \
    || error "Failed to delete variable '$key'"

  ok "Deleted ${BOLD}$key${NC} from service ${BOLD}$svc${NC}"
}

# ── Main ────────────────────────────────────────────────────────
main() {
  [[ $# -eq 0 ]] && usage

  local action="$1"; shift

  case "$action" in
    list|ls)      preflight; cmd_list "$@" ;;
    get|g)        preflight; cmd_get "$@" ;;
    set|s)        preflight; cmd_set "$@" ;;
    delete|del|d) preflight; cmd_delete "$@" ;;
    -h|--help|help) usage ;;
    *) error "Unknown action '$action'. Use: list | get | set | delete" ;;
  esac
}

main "$@"
