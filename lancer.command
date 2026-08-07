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

# Mise à jour automatique avant lancement : l'application n'est pas encore
# démarrée, c'est le seul moment où remplacer des fichiers est sans danger.
python3 maj_auto.py --verbeux
# Code 10 : l'application répond déjà. On ouvre le navigateur dessus plutôt
# que d'échouer sur un port occupé.
if [ $? -eq 10 ]; then
    echo "L'application est déjà ouverte : affichage dans le navigateur."
    open http://localhost:8501 2>/dev/null || true
    exit 0
fi

# Port fixe : voir lancer.bat — un basculement silencieux sur un
# autre port ferait regarder l'ancienne version.
python3 -m streamlit run app.py --server.port 8501
