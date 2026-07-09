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
python -m streamlit run app.py
pause
