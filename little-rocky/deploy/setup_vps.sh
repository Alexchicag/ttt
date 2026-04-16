#!/usr/bin/env bash
# =============================================================================
# setup_vps.sh — Installation initiale de Little Rocky sur un VPS
#
# Usage (en root ou sudo) :
#   curl -fsSL https://raw.githubusercontent.com/alexchicag/ttt/main/little-rocky/deploy/setup_vps.sh | bash
#   # ou
#   bash setup_vps.sh
#
# Ce script :
#   1. Installe Python 3.11 et git
#   2. Crée un utilisateur système dédié
#   3. Clone le dépôt dans /opt/little-rocky
#   4. Crée le venv et installe les dépendances
#   5. Installe et active le service systemd
#   6. Génère une clé SSH pour le déploiement auto GitHub Actions
# =============================================================================
set -euo pipefail

APP_DIR="/opt/little-rocky"
APP_USER="little-rocky"
REPO_URL="https://github.com/alexchicag/ttt.git"
SERVICE_NAME="little-rocky"
PYTHON="python3.11"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── 0. Vérifications ──────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && error "Lancez ce script en root (sudo bash setup_vps.sh)"
command -v apt-get &>/dev/null || error "Ce script requiert un système Debian/Ubuntu."

info "=== Installation de Little Rocky sur VPS ==="

# ── 1. Paquets système ────────────────────────────────────────────────────────
info "Mise à jour des paquets..."
apt-get update -q
apt-get install -y -q git python3.11 python3.11-venv python3.11-dev \
    build-essential libssl-dev curl sudo

# ── 2. Utilisateur système dédié ─────────────────────────────────────────────
if ! id -u "$APP_USER" &>/dev/null; then
    info "Création de l'utilisateur '$APP_USER'..."
    useradd --system --shell /bin/bash --create-home \
        --home-dir "$APP_DIR" "$APP_USER"
else
    info "Utilisateur '$APP_USER' existe déjà."
fi

# ── 3. Clone du dépôt ─────────────────────────────────────────────────────────
if [[ ! -d "$APP_DIR/.git" ]]; then
    info "Clonage du dépôt..."
    git clone "$REPO_URL" "$APP_DIR"
    chown -R "$APP_USER:$APP_USER" "$APP_DIR"
else
    info "Dépôt déjà cloné — mise à jour..."
    cd "$APP_DIR"
    sudo -u "$APP_USER" git pull origin main || sudo -u "$APP_USER" git pull origin master
fi

# ── 4. Environnement Python ────────────────────────────────────────────────────
info "Création du venv Python..."
sudo -u "$APP_USER" "$PYTHON" -m venv "$APP_DIR/.venv"

info "Installation des dépendances..."
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip -q
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install \
    -r "$APP_DIR/little-rocky/requirements.txt" -q

# ── 5. Fichier .env ────────────────────────────────────────────────────────────
ENV_FILE="$APP_DIR/little-rocky/.env"
if [[ ! -f "$ENV_FILE" ]]; then
    info "Création du fichier .env depuis l'exemple..."
    cp "$APP_DIR/little-rocky/.env.example" "$ENV_FILE"
    chown "$APP_USER:$APP_USER" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    warn "⚠  Éditez $ENV_FILE et renseignez vos clés avant de démarrer !"
else
    info ".env existe déjà — non écrasé."
fi

# ── 6. Service systemd ─────────────────────────────────────────────────────────
info "Installation du service systemd..."
cp "$APP_DIR/little-rocky/deploy/little-rocky.service" \
   "/etc/systemd/system/${SERVICE_NAME}.service"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

# ── 7. Sudoers pour le redémarrage sans mot de passe ─────────────────────────
SUDOERS_FILE="/etc/sudoers.d/little-rocky"
if [[ ! -f "$SUDOERS_FILE" ]]; then
    info "Configuration sudoers pour restart sans mot de passe..."
    echo "$APP_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart $SERVICE_NAME, /bin/systemctl is-active $SERVICE_NAME" \
        > "$SUDOERS_FILE"
    chmod 440 "$SUDOERS_FILE"
fi

# ── 8. Clé SSH pour GitHub Actions ────────────────────────────────────────────
SSH_DIR="$APP_DIR/.ssh"
KEY_FILE="$SSH_DIR/github_deploy"

if [[ ! -f "$KEY_FILE" ]]; then
    info "Génération de la clé SSH pour GitHub Actions..."
    mkdir -p "$SSH_DIR"
    sudo -u "$APP_USER" ssh-keygen -t ed25519 -C "little-rocky-deploy" \
        -f "$KEY_FILE" -N ""
    chown -R "$APP_USER:$APP_USER" "$SSH_DIR"
    chmod 700 "$SSH_DIR"
    chmod 600 "$KEY_FILE"

    # Autoriser cette clé à se connecter
    cat "$KEY_FILE.pub" >> "$SSH_DIR/authorized_keys"
    chmod 600 "$SSH_DIR/authorized_keys"
fi

# ── Résumé ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║          Installation terminée avec succès !          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  App dir   : $APP_DIR"
echo "  Venv      : $APP_DIR/.venv"
echo "  Service   : systemctl {start|stop|status|restart} $SERVICE_NAME"
echo "  Logs      : journalctl -u $SERVICE_NAME -f"
echo ""
echo -e "${YELLOW}Étapes suivantes :${NC}"
echo "  1. Renseignez vos clés dans : $ENV_FILE"
echo "  2. Démarrez le bot          : sudo systemctl start $SERVICE_NAME"
echo ""
echo -e "${YELLOW}Pour activer le déploiement automatique GitHub Actions :${NC}"
echo "  Ajoutez ces secrets dans GitHub → Settings → Secrets → Actions :"
echo ""
echo "  VPS_HOST     = $(hostname -I | awk '{print $1}' 2>/dev/null || echo '<IP_VPS>')"
echo "  VPS_USER     = $APP_USER"
echo "  VPS_PORT     = 22"
echo "  VPS_APP_PATH = $APP_DIR"
echo "  VPS_SSH_KEY  = (contenu de la clé privée ci-dessous)"
echo ""
echo -e "${GREEN}Clé privée SSH à copier dans VPS_SSH_KEY :${NC}"
echo "────────────────────────────────────────────"
cat "$KEY_FILE"
echo "────────────────────────────────────────────"
echo ""
