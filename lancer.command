#!/bin/bash
# Lancement en un double-clic (Mac).
# Première fois : installe les dépendances, puis ouvre l'app dans le navigateur.
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
    echo "Python n'est pas installé. Installez-le depuis https://www.python.org/downloads/"
    read -r -p "Appuyez sur Entrée pour fermer…"
    exit 1
fi
python3 -m pip install -r requirements.txt --quiet
# Port fixe : voir lancer.bat — un basculement silencieux sur un
# autre port ferait regarder l'ancienne version.
python3 -m streamlit run app.py --server.port 8501
