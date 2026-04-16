#!/usr/bin/env bash
# =============================================================================
# setup_vps.sh — Installation initiale de Little Rocky sur un VPS
#
# Compatible : Rocky Linux / RHEL / AlmaLinux ET Debian / Ubuntu
#
# Usage :
#   sudo bash setup_vps.sh
# =============================================================================
set -euo pipefail

APP_DIR="/opt/little-rocky"
APP_USER="little-rocky"
REPO_URL="https://github.com/alexchicag/ttt.git"
SERVICE_NAME="little-rocky"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── 0. Vérifications ──────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && error "Lancez ce script en root : sudo bash setup_vps.sh"

info "=== Installation de Little Rocky sur VPS ==="

# ── 1. Détection de la distribution ──────────────────────────────────────────
if command -v dnf &>/dev/null; then
    DISTRO="rhel"
    info "Distribution détectée : Rocky Linux / RHEL / AlmaLinux"
elif command -v apt-get &>/dev/null; then
    DISTRO="debian"
    info "Distribution détectée : Debian / Ubuntu"
else
    error "Distribution non supportée (ni dnf ni apt-get trouvé)."
fi

# ── 2. Paquets système ────────────────────────────────────────────────────────
info "Installation des paquets système..."

if [[ "$DISTRO" == "rhel" ]]; then
    dnf install -y -q git python3 python3-devel \
        gcc gcc-c++ make openssl-devel curl sudo unzip

    # pip pour python3 (pas toujours inclus sur RHEL/Rocky)
    if ! python3 -m pip --version &>/dev/null 2>&1; then
        info "Installation de pip..."
        curl -sS https://bootstrap.pypa.io/get-pip.py | python3
    fi

else
    apt-get update -q
    apt-get install -y -q git python3 python3-venv python3-dev \
        build-essential libssl-dev curl sudo unzip
fi

# Trouver le meilleur Python disponible (3.12, 3.11, 3.10, fallback python3)
PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" &>/dev/null; then
        PYTHON=$(command -v "$candidate")
        break
    fi
done
[[ -z "$PYTHON" ]] && error "Aucun Python 3 trouvé. Installez python3 et relancez."
info "Python utilisé : $PYTHON ($($PYTHON --version))"

# ── 3. Utilisateur système dédié ─────────────────────────────────────────────
if ! id -u "$APP_USER" &>/dev/null; then
    info "Création de l'utilisateur '$APP_USER'..."
    useradd --system --shell /bin/bash --create-home \
        --home-dir "$APP_DIR" "$APP_USER"
else
    info "Utilisateur '$APP_USER' existe déjà."
fi

# ── 4. Clone du dépôt ─────────────────────────────────────────────────────────
if [[ ! -d "$APP_DIR/.git" ]]; then
    info "Clonage du dépôt dans $APP_DIR..."
    git clone "$REPO_URL" "$APP_DIR"
    chown -R "$APP_USER:$APP_USER" "$APP_DIR"
else
    info "Dépôt déjà cloné — mise à jour..."
    cd "$APP_DIR"
    sudo -u "$APP_USER" git fetch origin
    sudo -u "$APP_USER" git reset --hard origin/main 2>/dev/null \
        || sudo -u "$APP_USER" git reset --hard origin/master
    chown -R "$APP_USER:$APP_USER" "$APP_DIR"
fi

# ── 5. Environnement Python (venv) ────────────────────────────────────────────
info "Création du venv Python dans $APP_DIR/.venv ..."

if [[ "$DISTRO" == "rhel" ]]; then
    # Sur Rocky, python3.11 -m venv peut nécessiter l'option --without-pip
    sudo -u "$APP_USER" "$PYTHON" -m venv "$APP_DIR/.venv" || \
    sudo -u "$APP_USER" "$PYTHON" -m venv "$APP_DIR/.venv" --without-pip
    # Installer/mettre à jour pip manuellement si besoin
    sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" -m ensurepip --upgrade 2>/dev/null || true
else
    sudo -u "$APP_USER" "$PYTHON" -m venv "$APP_DIR/.venv"
fi

info "Installation des dépendances Python..."
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip -q
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install \
    -r "$APP_DIR/little-rocky/requirements.txt" -q

# ── 6. Fichier .env ────────────────────────────────────────────────────────────
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

# ── 7. Service systemd ────────────────────────────────────────────────────────
info "Installation du service systemd..."
cp "$APP_DIR/little-rocky/deploy/little-rocky.service" \
   "/etc/systemd/system/${SERVICE_NAME}.service"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

# Ouvrir le firewall si firewalld est actif (Rocky Linux)
if systemctl is-active --quiet firewalld 2>/dev/null; then
    info "firewalld détecté — aucun port à ouvrir pour ce bot."
fi

# ── 8. Sudoers pour redémarrage sans mot de passe ────────────────────────────
SUDOERS_FILE="/etc/sudoers.d/little-rocky"
if [[ ! -f "$SUDOERS_FILE" ]]; then
    info "Configuration sudoers (restart sans mot de passe)..."
    cat > "$SUDOERS_FILE" <<EOF
$APP_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart ${SERVICE_NAME}, /bin/systemctl is-active ${SERVICE_NAME}
EOF
    chmod 440 "$SUDOERS_FILE"
fi

# ── 9. Clé SSH pour GitHub Actions ───────────────────────────────────────────
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
    chmod 644 "${KEY_FILE}.pub"

    # Autoriser cette clé à se connecter en SSH
    cat "${KEY_FILE}.pub" >> "$SSH_DIR/authorized_keys"
    chmod 600 "$SSH_DIR/authorized_keys"

    # Sur SELinux (Rocky), corriger le contexte
    if command -v restorecon &>/dev/null; then
        restorecon -R "$SSH_DIR" 2>/dev/null || true
    fi
fi

# ── Résumé final ──────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         Installation terminée avec succès !           ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  App dir   : $APP_DIR"
echo "  Venv      : $APP_DIR/.venv"
echo "  Service   : sudo systemctl {start|stop|status|restart} $SERVICE_NAME"
echo "  Logs      : sudo journalctl -u $SERVICE_NAME -f"
echo ""
echo -e "${YELLOW}Étapes suivantes :${NC}"
echo "  1. Renseignez vos clés API  : sudo nano $ENV_FILE"
echo "  2. Démarrez le bot          : sudo systemctl start $SERVICE_NAME"
echo ""
echo -e "${YELLOW}Secrets à ajouter sur GitHub (Settings → Secrets → Actions) :${NC}"
echo ""
VPS_IP=$(hostname -I | awk '{print $1}' 2>/dev/null || echo '<IP_VPS>')
echo "  VPS_HOST     = $VPS_IP"
echo "  VPS_USER     = $APP_USER"
echo "  VPS_PORT     = 22"
echo "  VPS_APP_PATH = $APP_DIR"
echo "  VPS_SSH_KEY  = (copiez le bloc ci-dessous EN ENTIER)"
echo ""
echo -e "${GREEN}══ Clé privée SSH (VPS_SSH_KEY) ══${NC}"
cat "$KEY_FILE"
echo -e "${GREEN}══════════════════════════════════${NC}"
echo ""
