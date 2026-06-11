#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# FrogFind! NG — Full Setup & Deploy Script
# by Ray Trunk
#
# Usage:
#   chmod +x deploy.sh
#   sudo ./deploy.sh          # fresh server setup
#   ./deploy.sh               # re-deploy (Docker already installed)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Colors & logging ──────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

log()     { echo -e "${GREEN}[✓]${NC} $*"; }
info()    { echo -e "${BLUE}[→]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
die()     { echo -e "${RED}[✗] $*${NC}"; exit 1; }
header()  { echo -e "\n${BOLD}${CYAN}── $* ──────────────────────────────${NC}"; }
ask()     { echo -e "${YELLOW}[?]${NC} $*"; }

# ── Must run from project root ────────────────────────────────────────────────
[[ -f "docker-compose.yml" ]] || die "Run this script from the frogfind-ng directory."

# ── Root check ────────────────────────────────────────────────────────────────
SUDO=""
if [[ $EUID -ne 0 ]]; then
    command -v sudo >/dev/null 2>&1 || die "Not root and sudo not found. Run as root or install sudo."
    SUDO="sudo"
    warn "Not running as root — will use sudo for system commands."
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Detect Linux distribution
# ─────────────────────────────────────────────────────────────────────────────
header "Step 1: Detecting Linux distribution"

OS_ID=""
OS_LIKE=""
OS_VERSION=""

if [[ -f /etc/os-release ]]; then
    source /etc/os-release
    OS_ID="${ID:-unknown}"
    OS_LIKE="${ID_LIKE:-}"
    OS_VERSION="${VERSION_ID:-}"
else
    die "Cannot detect OS — /etc/os-release not found."
fi

# Normalize: treat derivatives like their parent
is_debian_based() {
    [[ "$OS_ID" =~ ^(debian|ubuntu|raspbian|linuxmint|pop|kali|elementary)$ ]] || \
    [[ "$OS_LIKE" =~ debian ]] || [[ "$OS_LIKE" =~ ubuntu ]]
}
is_rhel_based() {
    [[ "$OS_ID" =~ ^(centos|rhel|fedora|rocky|almalinux|ol)$ ]] || \
    [[ "$OS_LIKE" =~ rhel ]] || [[ "$OS_LIKE" =~ fedora ]]
}
is_arch_based() {
    [[ "$OS_ID" =~ ^(arch|manjaro|endeavouros|garuda)$ ]] || \
    [[ "$OS_LIKE" =~ arch ]]
}
is_alpine() {
    [[ "$OS_ID" == "alpine" ]]
}

if is_debian_based; then
    PKG_MGR="apt"
    log "Detected: Debian/Ubuntu-based (${PRETTY_NAME:-$OS_ID})"
elif is_rhel_based; then
    PKG_MGR="dnf"
    command -v dnf >/dev/null 2>&1 || PKG_MGR="yum"
    log "Detected: RHEL/CentOS-based (${PRETTY_NAME:-$OS_ID})"
elif is_arch_based; then
    PKG_MGR="pacman"
    log "Detected: Arch-based (${PRETTY_NAME:-$OS_ID})"
elif is_alpine; then
    PKG_MGR="apk"
    log "Detected: Alpine Linux"
else
    warn "Unknown distribution '${OS_ID}' — will use Docker install script as fallback."
    PKG_MGR="unknown"
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1b — Detect container environment (LXC/OpenVZ) & fix Docker storage
# ─────────────────────────────────────────────────────────────────────────────
fix_docker_lxc() {
    # Detect container environment (LXC / OpenVZ / KVM / bare-metal)
    local virt=""
    command -v systemd-detect-virt >/dev/null 2>&1 && virt=$(systemd-detect-virt 2>/dev/null || echo "")
    [[ -f /proc/1/environ ]] && grep -qa "container=lxc" /proc/1/environ 2>/dev/null && virt="lxc"

    local need_fuse=false
    if [[ "$virt" == "lxc" || "$virt" == "openvz" ]]; then
        warn "LXC/OpenVZ container detected — overlay2 not supported."
        need_fuse=true
    fi

    # Also check if overlay mount actually works (catches undetected LXC)
    if ! $SUDO mount -t overlay overlay -o lowerdir=/tmp,upperdir=/tmp,workdir=/tmp /tmp \
            >/dev/null 2>&1; then
        warn "Overlay filesystem not supported on this kernel — using fuse-overlayfs."
        need_fuse=true
    fi
    # Clean up test mount silently
    $SUDO umount /tmp 2>/dev/null || true

    $SUDO mkdir -p /etc/docker
    local current_driver
    current_driver=$(python3 -c "import json,sys; \
        d=json.load(open('/etc/docker/daemon.json')) if __import__('os').path.exists('/etc/docker/daemon.json') else {}; \
        print(d.get('storage-driver',''))" 2>/dev/null || echo "")

    # Build desired daemon.json config
    local driver="overlay2"
    if $need_fuse; then
        # Install fuse-overlayfs
        if ! command -v fuse-overlayfs >/dev/null 2>&1; then
            info "Installing fuse-overlayfs..."
            case "$PKG_MGR" in
                apt)     $SUDO apt-get install -y --no-install-recommends fuse-overlayfs ;;
                dnf|yum) $SUDO "$PKG_MGR" install -y fuse-overlayfs ;;
                pacman)  $SUDO pacman -Sy --noconfirm fuse-overlayfs ;;
                *)       warn "Cannot auto-install fuse-overlayfs — falling back to vfs." ;;
            esac
        fi
        command -v fuse-overlayfs >/dev/null 2>&1 && driver="fuse-overlayfs" || driver="vfs"
    fi

    # Always ensure DNS is set for Docker containers (prevents apt-get failures in LXC)
    local needs_restart=false
    local daemon_json="{}"
    [[ -f /etc/docker/daemon.json ]] && daemon_json=$(cat /etc/docker/daemon.json)

    local new_config
    new_config=$(python3 -c "
import json, sys
d = json.loads('''${daemon_json}''')
changed = False
if d.get('storage-driver') != '${driver}':
    d['storage-driver'] = '${driver}'
    changed = True
if '8.8.8.8' not in d.get('dns', []):
    d['dns'] = ['8.8.8.8', '1.1.1.1']
    changed = True
print(json.dumps(d, indent=2))
print('CHANGED=' + str(changed), file=sys.stderr)
" 2>/tmp/docker_cfg_status)
    grep -q "CHANGED=True" /tmp/docker_cfg_status && needs_restart=true

    if $needs_restart; then
        echo "$new_config" | $SUDO tee /etc/docker/daemon.json > /dev/null
        info "Docker daemon.json updated (driver=${driver}, dns=8.8.8.8/1.1.1.1)"
        $SUDO systemctl restart docker
        sleep 2
        log "Docker restarted with new configuration."
    else
        log "Docker daemon.json already up to date (driver=${current_driver})."
    fi
}

# Run LXC fix before Docker install step
fix_docker_lxc

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Install system dependencies
# ─────────────────────────────────────────────────────────────────────────────
header "Step 2: Installing system dependencies"

install_packages() {
    info "Installing: $*"
    case "$PKG_MGR" in
        apt)
            $SUDO apt-get update -qq
            $SUDO apt-get install -y --no-install-recommends "$@"
            ;;
        dnf|yum)
            $SUDO "$PKG_MGR" install -y "$@"
            ;;
        pacman)
            $SUDO pacman -Sy --noconfirm "$@"
            ;;
        apk)
            $SUDO apk add --no-cache "$@"
            ;;
        *)
            warn "Cannot auto-install packages — please install manually: $*"
            ;;
    esac
}

# Ensure curl, openssl, python3, pip are present
MISSING_PKGS=()
command -v curl     >/dev/null 2>&1 || MISSING_PKGS+=("curl")
command -v openssl  >/dev/null 2>&1 || MISSING_PKGS+=("openssl")
command -v python3  >/dev/null 2>&1 || MISSING_PKGS+=("python3")

# Python3-pip: check differently per distro
if ! python3 -m pip --version >/dev/null 2>&1; then
    case "$PKG_MGR" in
        apt)    MISSING_PKGS+=("python3-pip") ;;
        dnf|yum) MISSING_PKGS+=("python3-pip") ;;
        pacman) MISSING_PKGS+=("python-pip") ;;
        apk)    MISSING_PKGS+=("py3-pip") ;;
    esac
fi

if [[ ${#MISSING_PKGS[@]} -gt 0 ]]; then
    install_packages "${MISSING_PKGS[@]}"
else
    log "System dependencies already installed."
fi

# Install bcrypt for admin password hashing
if ! python3 -c "import bcrypt" >/dev/null 2>&1; then
    info "Installing Python bcrypt..."
    $SUDO python3 -m pip install --quiet bcrypt 2>/dev/null || \
    python3 -m pip install --quiet bcrypt --break-system-packages 2>/dev/null || \
    warn "Could not install bcrypt via pip — admin hash generation may fail."
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Install Docker
# ─────────────────────────────────────────────────────────────────────────────
header "Step 3: Docker"

install_docker_debian() {
    info "Installing Docker (Debian/Ubuntu)..."
    $SUDO apt-get update -qq
    $SUDO apt-get install -y --no-install-recommends \
        ca-certificates gnupg lsb-release

    $SUDO install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/${OS_ID}/gpg | \
        $SUDO gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    $SUDO chmod a+r /etc/apt/keyrings/docker.gpg

    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/${OS_ID} $(lsb_release -cs) stable" | \
        $SUDO tee /etc/apt/sources.list.d/docker.list > /dev/null

    $SUDO apt-get update -qq
    $SUDO apt-get install -y docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin
}

install_docker_rhel() {
    info "Installing Docker (RHEL/CentOS)..."
    $SUDO "$PKG_MGR" install -y yum-utils
    $SUDO yum-config-manager --add-repo \
        https://download.docker.com/linux/centos/docker-ce.repo
    $SUDO "$PKG_MGR" install -y docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin
}

install_docker_arch() {
    info "Installing Docker (Arch)..."
    $SUDO pacman -Sy --noconfirm docker docker-compose
}

install_docker_alpine() {
    info "Installing Docker (Alpine)..."
    $SUDO apk add --no-cache docker docker-compose
    $SUDO rc-update add docker boot
}

install_docker_script() {
    info "Installing Docker via official install script..."
    curl -fsSL https://get.docker.com | $SUDO sh
}

if command -v docker >/dev/null 2>&1; then
    log "Docker already installed: $(docker --version)"
else
    case "$PKG_MGR" in
        apt)    install_docker_debian ;;
        dnf|yum) install_docker_rhel ;;
        pacman) install_docker_arch ;;
        apk)    install_docker_alpine ;;
        *)      install_docker_script ;;
    esac

    $SUDO systemctl enable docker 2>/dev/null || true
    $SUDO systemctl start  docker 2>/dev/null || \
    $SUDO service docker start    2>/dev/null || true

    # Add current user to docker group
    if [[ -n "${SUDO_USER:-}" ]]; then
        $SUDO usermod -aG docker "$SUDO_USER"
        warn "User '$SUDO_USER' added to docker group. Re-login may be required."
    fi

    log "Docker installed: $(docker --version)"
fi

# Confirm compose is available
if ! docker compose version >/dev/null 2>&1; then
    die "docker compose plugin not found. Install docker-compose-plugin and retry."
fi
log "Docker Compose: $(docker compose version --short)"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Domain setup
# ─────────────────────────────────────────────────────────────────────────────
header "Step 4: Domain configuration"

ask "Enter your domain name (leave blank for localhost):"
read -r DOMAIN
DOMAIN="${DOMAIN:-localhost}"
DOMAIN="${DOMAIN#https://}"     # strip protocol if accidentally pasted
DOMAIN="${DOMAIN#http://}"
DOMAIN="${DOMAIN%%/*}"          # strip path

log "Domain: $DOMAIN"

# Update Nginx server_name
sed -i "s|server_name .*;|server_name ${DOMAIN};|g" nginx/conf.d/default.conf
log "Nginx config updated → server_name ${DOMAIN}"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Environment setup (.env)
# ─────────────────────────────────────────────────────────────────────────────
header "Step 5: Environment configuration"

# Create .env from example if it doesn't exist
if [[ ! -f .env ]]; then
    cp .env.example .env
    info "Created .env from .env.example"
fi

# ── Helper: set or replace a key in .env ─────────────────────────────────────
env_set() {
    local key="$1" val="$2"
    if grep -qE "^${key}=" .env; then
        # Replace existing (use | as delimiter to avoid issues with / in values)
        sed -i "s|^${key}=.*|${key}=${val}|" .env
    else
        echo "${key}=${val}" >> .env
    fi
}

env_get() { grep -E "^$1=" .env 2>/dev/null | cut -d= -f2- || echo ""; }

# ── Redis password ────────────────────────────────────────────────────────────
CURRENT_REDIS_PW=$(env_get "REDIS_PASSWORD")
if [[ -z "$CURRENT_REDIS_PW" || "$CURRENT_REDIS_PW" == "changeme" ]]; then
    NEW_REDIS_PW=$(openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 32)
    env_set "REDIS_PASSWORD" "$NEW_REDIS_PW"
    env_set "REDIS_URL"      "redis://:${NEW_REDIS_PW}@redis:6379"
    log "Redis password generated and set."
else
    NEW_REDIS_PW="$CURRENT_REDIS_PW"
    log "Redis password already set — keeping existing."
fi

# ── Admin credentials ─────────────────────────────────────────────────────────
CURRENT_ADMIN_HASH=$(env_get "ADMIN_PASSWORD_HASH")
if [[ -z "$CURRENT_ADMIN_HASH" ]]; then
    ask "Set admin panel password:"
    read -rs ADMIN_PASS
    echo ""
    ask "Confirm admin password:"
    read -rs ADMIN_PASS2
    echo ""
    [[ "$ADMIN_PASS" == "$ADMIN_PASS2" ]] || die "Passwords do not match."
    [[ ${#ADMIN_PASS} -ge 8 ]]           || die "Password must be at least 8 characters."

    info "Generating bcrypt hash..."
    ADMIN_HASH=$(echo "$ADMIN_PASS" | python3 -c "
import sys, bcrypt
pw = sys.stdin.readline().strip()
print(bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode())
")
    env_set "ADMIN_PASSWORD_HASH" "$ADMIN_HASH"
    log "Admin password hash stored."
else
    log "Admin password already configured — keeping existing."
fi

CURRENT_ADMIN_PATH=$(env_get "ADMIN_PATH")
if [[ -z "$CURRENT_ADMIN_PATH" ]]; then
    NEW_ADMIN_PATH="admin-$(openssl rand -hex 8)"
    env_set "ADMIN_PATH" "$NEW_ADMIN_PATH"
    log "Admin path generated: /${NEW_ADMIN_PATH}/"
else
    NEW_ADMIN_PATH="$CURRENT_ADMIN_PATH"
    log "Admin path already set: /${NEW_ADMIN_PATH}/"
fi

CURRENT_SECRET=$(env_get "ADMIN_SECRET_KEY")
if [[ -z "$CURRENT_SECRET" ]]; then
    env_set "ADMIN_SECRET_KEY" "$(openssl rand -hex 32)"
    log "Admin secret key generated."
fi

# ── Domain in .env ────────────────────────────────────────────────────────────
env_set "APP_DOMAIN" "$DOMAIN"

# ── Optional: Reddit OAuth2 ───────────────────────────────────────────────────
CURRENT_REDDIT_ID=$(env_get "REDDIT_CLIENT_ID")
if [[ -z "$CURRENT_REDDIT_ID" ]]; then
    echo ""
    ask "Reddit API credentials (optional — enables post detail + comments)."
    ask "Register free at: https://www.reddit.com/prefs/apps"
    ask "Enter REDDIT_CLIENT_ID (or press Enter to skip):"
    read -r REDDIT_ID
    if [[ -n "$REDDIT_ID" ]]; then
        ask "Enter REDDIT_CLIENT_SECRET:"
        read -rs REDDIT_SECRET
        echo ""
        env_set "REDDIT_CLIENT_ID"     "$REDDIT_ID"
        env_set "REDDIT_CLIENT_SECRET" "$REDDIT_SECRET"
        log "Reddit credentials saved."
    else
        info "Skipping Reddit OAuth — RSS mode will be used."
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Build & Start
# ─────────────────────────────────────────────────────────────────────────────
header "Step 6: Building and starting FrogFind! NG"

info "Building Docker images (this may take a few minutes)..."
docker compose build --no-cache

info "Starting services..."
docker compose up -d

info "Waiting for health checks..."
sleep 8

# ── Status ────────────────────────────────────────────────────────────────────
docker compose ps

echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║        FrogFind! NG is running!                      ║${NC}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${CYAN}Search:${NC}        http://${DOMAIN}/"
echo -e "  ${CYAN}Wikipedia:${NC}     http://${DOMAIN}/wiki"
echo -e "  ${CYAN}Reddit:${NC}        http://${DOMAIN}/reddit"
echo -e "  ${CYAN}News:${NC}          http://${DOMAIN}/news"
echo -e "  ${CYAN}Weather:${NC}       http://${DOMAIN}/weather"
echo -e "  ${CYAN}Admin panel:${NC}   http://${DOMAIN}/${NEW_ADMIN_PATH}/login"
echo ""
echo -e "  ${YELLOW}Logs:${NC}          docker compose logs -f"
echo -e "  ${YELLOW}Stop:${NC}          docker compose down"
echo -e "  ${YELLOW}Update:${NC}        git pull && ./deploy.sh"
echo ""
