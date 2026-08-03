@echo off
REM ============================================================
REM  Mise a jour en un clic de l'utilitaire Pilotage pharmacie
REM  Telecharge la derniere version depuis GitHub puis relance
REM  l'application. Vos donnees (config.yaml, historique) sont
REM  conservees.
REM ============================================================
title Mise a jour - Pilotage pharmacie
cd /d "%~dp0"

echo.
echo  ====================================================
echo    Mise a jour de l'utilitaire Pilotage pharmacie
echo  ====================================================
echo.

REM --- 0. Verifier que Python est disponible -----------------
where python >nul 2>nul
if errorlevel 1 (
    echo  [ERREUR] Python n'est pas installe ou absent du PATH.
    echo  Installez-le depuis https://www.python.org/downloads/
    echo  en cochant "Add Python to PATH" pendant l'installation.
    echo.
    pause
    exit /b 1
)

set "URL=https://github.com/lordofdecay57/pharmacie-ruptures/archive/refs/heads/main.zip"
set "ZIP=%TEMP%\pharmacie-maj.zip"
set "EXDIR=%TEMP%\pharmacie-maj"

REM --- 1. Telechargement --------------------------------------
echo  [1/4] Telechargement de la derniere version...
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri '%URL%' -OutFile '%ZIP%' -UseBasicParsing } catch { exit 1 }"
if errorlevel 1 (
    echo  [ERREUR] Telechargement impossible - verifiez votre connexion Internet.
    echo.
    pause
    exit /b 1
)

REM --- 2. Extraction ------------------------------------------
echo  [2/4] Extraction...
if exist "%EXDIR%" rmdir /s /q "%EXDIR%"
powershell -NoProfile -Command "try { Expand-Archive -Path '%ZIP%' -DestinationPath '%EXDIR%' -Force } catch { exit 1 }"
if errorlevel 1 (
    echo  [ERREUR] Extraction impossible.
    echo.
    pause
    exit /b 1
)

REM --- 3. Installation des nouveaux fichiers ------------------
REM  On ne remplace ni ce script, ni vos donnees personnelles
REM  (mapping des colonnes, historique des analyses, etat du stock
REM  min/max et inventaire du stock ferme).
echo  [3/4] Installation des fichiers...
robocopy "%EXDIR%\pharmacie-ruptures-main" "%~dp0." /E /NFL /NDL /NJH /NJS /NP /XF mettre-a-jour.bat config.yaml historique_commandes.csv etat_stock_precedent.csv etat_stock_precedent.sig stock_ferme.csv stock_ferme_produits.csv >nul
if %ERRORLEVEL% GEQ 8 (
    echo  [ERREUR] Copie des fichiers impossible.
    echo.
    pause
    exit /b 1
)
python -m pip install -r requirements.txt --quiet

REM --- 4. Lancement -------------------------------------------
echo  [4/4] Lancement de l'application...
echo.
echo  Mise a jour terminee. L'application va s'ouvrir dans le navigateur.
echo  Gardez CETTE fenetre ouverte pendant l'utilisation.
echo  Pour arreter l'application : fermez cette fenetre ou appuyez sur Ctrl+C.
echo.
python -m streamlit run app.py
pause
