#!/usr/bin/env bash
# RIX_SUPPORT_BOT one-line installer
# Usage: bash <(curl -fsSL https://raw.githubusercontent.com/amirmayeli1211/RIX_SUPPORT_BOT/main/install.sh)
set -euo pipefail

REPO="amirmayeli1211/RIX_SUPPORT_BOT"
BRANCH="main"
INSTALL_DIR="/opt/rix-support-bot"
SERVICE_NAME="rix-support-bot"
PYTHON_BIN="${PYTHON_BIN:-python3}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info(){ echo -e "${CYAN}[*]${NC} $*"; }
ok(){ echo -e "${GREEN}[OK]${NC} $*"; }
warn(){ echo -e "${YELLOW}[!]${NC} $*"; }
fail(){ echo -e "${RED}[ERR]${NC} $*"; exit 1; }

echo "=============================================="
echo "   RIX_SUPPORT_BOT installer (Telegram CRM)"
echo "=============================================="

# --- OS check ---
if [[ ! -f /etc/os-release ]]; then fail "Unsupported OS (no /etc/os-release)."; fi
. /etc/os-release
case "${ID:-}" in
  ubuntu|debian) ;;
  *) warn "Tested on Ubuntu/Debian; detected: ${ID:-unknown}. Continuing anyway." ;;
esac

# --- root check ---
if [[ $EUID -ne 0 ]]; then fail "Run as root: sudo bash ..."; fi

# --- deps ---
info "Installing system dependencies..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-pip git curl ca-certificates >/dev/null 2>&1 || \
  apt-get install -y python3 python3-pip git curl ca-certificates
ok "Dependencies ready."

# --- prompts ---
echo
read -rp "Bot token (from @BotFather): " BOT_TOKEN
[[ -z "${BOT_TOKEN}" ]] && fail "BOT_TOKEN is required."
read -rp "Owner Telegram user ID (numeric): " OWNER_TG_ID
[[ -z "${OWNER_TG_ID}" ]] && fail "OWNER_TG_ID is required."
[[ "${OWNER_TG_ID}" =~ ^[0-9]+$ ]] || fail "OWNER_TG_ID must be numeric."

# optional extra admins
read -rp "Extra admin IDs (comma-separated, or empty): " EXTRA_ADMINS
EXTRA_ADMINS="${EXTRA_ADMINS:-}"

# data dir (persistent)
DATA_DIR="${DATA_DIR:-/data}"
mkdir -p "${DATA_DIR}"

# --- clone / update ---
if [[ -d "${INSTALL_DIR}/.git" ]]; then
  info "Existing install found, updating..."
  git -C "${INSTALL_DIR}" fetch --quiet origin "${BRANCH}"
  git -C "${INSTALL_DIR}" reset --hard "origin/${BRANCH}" >/dev/null
else
  info "Cloning repository..."
  rm -rf "${INSTALL_DIR}"
  git clone --quiet --branch "${BRANCH}" "https://github.com/${REPO}.git" "${INSTALL_DIR}"
fi
ok "Code ready at ${INSTALL_DIR}."

# --- .env ---
ENV_FILE="${INSTALL_DIR}/.env"
cat > "${ENV_FILE}" <<EOF
BOT_TOKEN=${BOT_TOKEN}
OWNER_TG_ID=${OWNER_TG_ID}
DATA_DIR=${DATA_DIR}
EXTRA_ADMINS=${EXTRA_ADMINS}
EOF
chmod 600 "${ENV_FILE}"
ok ".env written."

# --- systemd service ---
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=RIX_SUPPORT_BOT Telegram CRM
After=network.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${PYTHON_BIN} ${INSTALL_DIR}/bot.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}" >/dev/null 2>&1
ok "Service enabled & started."

# --- wait & health check ---
info "Waiting for bot to start..."
sleep 3
if systemctl is-active --quiet "${SERVICE_NAME}"; then
  ok "Bot is RUNNING."
else
  warn "Service not active. Recent logs:"
  journalctl -u "${SERVICE_NAME}" -n 30 --no-pager || true
  fail "Install finished but service failed to start. Check logs above."
fi

echo
echo "=============================================="
echo "   Install complete!"
echo "=============================================="
echo "  Dir:     ${INSTALL_DIR}"
echo "  Data:    ${DATA_DIR}"
echo "  Service: ${SERVICE_NAME}"
echo "  Logs:    journalctl -u ${SERVICE_NAME} -f"
echo "  Restart: systemctl restart ${SERVICE_NAME}"
echo "  Update:  bash <(curl -fsSL https://raw.githubusercontent.com/${REPO}/main/install.sh)"
echo "=============================================="
