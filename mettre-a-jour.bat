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
echo  [1/5] Telechargement de la derniere version...
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri '%URL%' -OutFile '%ZIP%' -UseBasicParsing } catch { exit 1 }"
if errorlevel 1 (
    echo  [ERREUR] Telechargement impossible - verifiez votre connexion Internet.
    echo.
    pause
    exit /b 1
)

REM --- 2. Extraction ------------------------------------------
echo  [2/5] Extraction...
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
echo  [3/5] Installation des fichiers...
robocopy "%EXDIR%\pharmacie-ruptures-main" "%~dp0." /E /NFL /NDL /NJH /NJS /NP /XF mettre-a-jour.bat config.yaml historique_commandes.csv etat_stock_precedent.csv etat_stock_precedent.sig stock_ferme.csv stock_ferme_produits.csv base_medicaments.csv >nul
if %ERRORLEVEL% GEQ 8 (
    echo  [ERREUR] Copie des fichiers impossible.
    echo.
    pause
    exit /b 1
)
python -m pip install -r requirements.txt --quiet

REM  Affiche la version qui vient d'etre installee : sans ce reperage, une
REM  mise a jour qui n'a pas pris passe inapercue.
REM  L'espace fait partie des delimiteurs, et %%~v retire les guillemets :
REM  « VERSION_APP = "3.4" » donne directement 3.4, sans les manipulations
REM  de chaine a guillemets impairs qui trainaient ici.
for /f "tokens=2 delims== " %%v in ('findstr /b "VERSION_APP" app.py') do set "VER=%%~v"
echo.
echo  Version installee : v%VER%
echo  ^(elle doit s'afficher a l'identique dans le bandeau de l'application^)

REM --- 4. Fermeture de l'ancienne version ----------------------
REM  Une ancienne version encore ouverte occupe le port 8501 : la nouvelle
REM  demarrerait alors sur 8502, et l'onglet localhost:8501 continuerait
REM  d'afficher l'ANCIENNE — la mise a jour semblerait sans effet. On ferme
REM  donc nous-memes le processus qui ecoute sur 8501, plutot que de
REM  demander a l'utilisateur d'y penser.
echo  [4/5] Fermeture de la version precedente...
REM  Une seule ligne, tout entre guillemets : cmd ne reinterprete alors ni
REM  le | ni les parentheses. Le try/catch couvre les Windows depourvus de
REM  Get-NetTCPConnection — la mise a jour ne doit jamais echouer ici.
powershell -NoProfile -Command "try { Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } } catch { }" >nul 2>nul
REM  Laisse le port se liberer avant de relancer.
timeout /t 3 /nobreak >nul

REM  Ceinture et bretelles : si quelque chose tient encore le port, mieux
REM  vaut le dire que de laisser l'utilisateur devant une version fantome.
REM  Le code de sortie vaut le NOMBRE de processus qui ecoutent (0 = libre).
powershell -NoProfile -Command "try { exit ((Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count) } catch { exit 0 }"
if errorlevel 1 (
    echo.
    echo  [ATTENTION] Le port 8501 est toujours occupe.
    echo  Fermez toutes les fenetres noires de l'application, puis
    echo  relancez ce script.
    echo.
    pause
)

echo  [5/5] Lancement de l'application...
echo.
echo  Mise a jour terminee. L'application va s'ouvrir dans le navigateur.
echo  Gardez CETTE fenetre ouverte pendant l'utilisation.
echo  Pour arreter l'application : fermez cette fenetre ou appuyez sur Ctrl+C.
echo.
REM  Port fixe : si 8501 est occupe, Streamlit le DIT au lieu de basculer en
REM  silence sur un autre port.
python -m streamlit run app.py --server.port 8501
pause
