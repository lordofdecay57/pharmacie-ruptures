@echo off
REM Lancement en un double-clic (Windows).
REM Premiere fois : installe les dependances, puis ouvre l'app dans le navigateur.
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
    echo Python n'est pas installe. Installez-le depuis https://www.python.org/downloads/
    echo (cochez "Add Python to PATH" pendant l'installation^)
    pause
    exit /b 1
)
python -m pip install -r requirements.txt --quiet

REM  Mise a jour automatique AVANT de lancer : c'est le seul moment ou
REM  remplacer des fichiers est sans danger, l'application n'est pas encore
REM  demarree. Le script ne fait rien s'il n'y a pas de nouvelle version,
REM  si le poste est hors ligne, ou si une instance tourne deja.
python maj_auto.py --verbeux

REM  Port fixe : si 8501 est deja occupe par une autre instance,
REM  Streamlit le DIT au lieu de basculer en silence sur 8502 —
REM  on regarderait sinon l'ancienne version sans le savoir.
python -m streamlit run app.py --server.port 8501
pause
