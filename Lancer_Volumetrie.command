#!/bin/bash
# ==============================================================================
# Lancer_Volumetrie.command
# Lanceur interactif macOS double-cliquable pour la plateforme HepaVol
# (Volumétrie Hépatique par IA avec 3D Slicer & TotalSegmentator)
# ==============================================================================

# Se positionner dans le dossier du script
cd "$( dirname "${BASH_SOURCE[0]}" )" || exit 1

# Couleurs du terminal
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m' # No Color

clear
echo -e "${CYAN}${BOLD}"
echo "========================================================================"
echo "      🏥  HepaVol - Plateforme de Volumétrie Hépatique par IA         "
echo "        Intégration 3D Slicer • TotalSegmentator • Web Moderne         "
echo "========================================================================"
echo -e "${NC}"

# 1. Vérification de Python 3
echo -e "${BOLD}[1/4] Vérification de l'environnement Python...${NC}"
if command -v python3 >/dev/null 2>&1; then
    PY_VER=$(python3 --version)
    echo -e "  ${GREEN}✓${NC} $PY_VER détecté."
else
    echo -e "  ${RED}✗ Erreur : Python 3 n'est pas installé sur ce Mac.${NC}"
    echo "  Veuillez installer Python 3 depuis https://www.python.org/downloads/"
    echo "Appuyez sur une touche pour quitter..."
    read -n 1
    exit 1
fi

# 2. Vérification des dépendances Python
echo -e "\n${BOLD}[2/4] Vérification des modules requis (FastAPI, Uvicorn)...${NC}"
python3 -c "import fastapi, uvicorn, jinja2, PIL, multipart" >/dev/null 2>&1
if [ $? -ne 0 ]; then
    echo -e "  ${YELLOW}! Installation des modules Python manquants...${NC}"
    pip3 install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo -e "  ${RED}✗ Échec de l'installation des dépendances.${NC}"
        echo "Appuyez sur une touche pour quitter..."
        read -n 1
        exit 1
    fi
else
    echo -e "  ${GREEN}✓${NC} Dépendances Python prêtes."
fi

# 3. Vérification de 3D Slicer
echo -e "\n${BOLD}[3/4] Détection de l'application 3D Slicer...${NC}"
SLICER_PATH="/Applications/Slicer.app/Contents/MacOS/Slicer"
if [ -f "$SLICER_PATH" ]; then
    echo -e "  ${GREEN}✓${NC} 3D Slicer détecté : $SLICER_PATH"
elif [ -f "$HOME/Applications/Slicer.app/Contents/MacOS/Slicer" ]; then
    SLICER_PATH="$HOME/Applications/Slicer.app/Contents/MacOS/Slicer"
    export SLICER_PATH
    echo -e "  ${GREEN}✓${NC} 3D Slicer détecté : $SLICER_PATH"
else
    echo -e "  ${YELLOW}! Attention : 3D Slicer n'a pas été trouvé dans /Applications/Slicer.app${NC}"
    echo -e "  L'interface web se lancera, mais vous devrez vérifier l'installation de Slicer."
fi

# 4. Gestion du port et libération des anciennes instances
echo -e "\n${BOLD}[4/4] Préparation du port réseau et démarrage...${NC}"
PORT=8000
OLD_PID=$(lsof -ti tcp:$PORT 2>/dev/null)
if [ -n "$OLD_PID" ]; then
    echo -e "  ${YELLOW}! Une ancienne instance utilise le port $PORT (PID $OLD_PID). Fermeture...${NC}"
    kill -9 $OLD_PID 2>/dev/null
    sleep 1
    if lsof -ti tcp:$PORT >/dev/null 2>&1; then
        PORT=8001
        echo -e "  ${YELLOW}! Utilisation du port alternatif : $PORT${NC}"
    else
        echo -e "  ${GREEN}✓${NC} Port $PORT libéré."
    fi
fi

URL="http://localhost:$PORT"
echo -e "  Adresse de l'application : ${CYAN}${BOLD}$URL${NC}"
echo -e "  ${GREEN}✓ Ouverture automatique de votre navigateur dans 2 secondes...${NC}\n"

# Ouverture du navigateur dans un sous-processus
(
    sleep 2
    open "$URL"
) &

# Nettoyage lors de la fermeture
cleanup() {
    echo -e "\n\n${YELLOW}Arrêt du serveur HepaVol...${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM

echo -e "${BOLD}------------------------------------------------------------------------${NC}"
echo -e "  ${GREEN}Le serveur est actif et à l'écoute sur $URL${NC}"
echo -e "  Pour arrêter le serveur, appuyez sur ${BOLD}Ctrl + C${NC} dans cette fenêtre."
echo -e "${BOLD}------------------------------------------------------------------------${NC}\n"

# Lancement de l'application FastAPI
python3 app.py "$PORT"
