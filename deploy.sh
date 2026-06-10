#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# FrogFind! NG — Deploy Script
# by Ray Trunk
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

log()  { echo -e "${GREEN}[deploy]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC}  $*"; }
die()  { echo -e "${RED}[error]${NC} $*"; exit 1; }

# ── Pre-flight checks ─────────────────────────────────────────────────────────
command -v docker        >/dev/null 2>&1 || die "docker not found"
command -v docker compose >/dev/null 2>&1 || \
  docker-compose version  >/dev/null 2>&1 || die "docker compose not found"

[[ -f .env ]] || die ".env not found — copy .env.example and fill in values:\n  cp .env.example .env"

# Check required .env keys
for key in ADMIN_PATH ADMIN_PASSWORD_HASH ADMIN_SECRET_KEY REDIS_PASSWORD; do
    val=$(grep -E "^${key}=" .env | cut -d= -f2-)
    [[ -n "$val" ]] || die "${key} is empty in .env — run: python scripts/generate_admin.py"
done

# Warn if REDIS_PASSWORD is still the default
REDIS_PW=$(grep -E "^REDIS_PASSWORD=" .env | cut -d= -f2-)
[[ "$REDIS_PW" == "changeme" ]] && warn "REDIS_PASSWORD is still 'changeme' — change it in .env!"

log "Pre-flight OK"

# ── Build & start ─────────────────────────────────────────────────────────────
log "Building images..."
docker compose build --no-cache

log "Starting services..."
docker compose up -d

log "Waiting for health checks..."
sleep 5

# Show status
docker compose ps

ADMIN_PATH=$(grep -E "^ADMIN_PATH=" .env | cut -d= -f2-)
echo ""
echo -e "${GREEN}✓ FrogFind! NG is running${NC}"
echo "  Search:      http://localhost/"
echo "  Admin panel: http://localhost/${ADMIN_PATH}/login"
echo ""
echo "Logs: docker compose logs -f"
