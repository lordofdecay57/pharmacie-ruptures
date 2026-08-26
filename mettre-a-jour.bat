@echo off
REM ============================================================
REM  Mise a jour en un clic de l'utilitaire Pilotage pharmacie
REM  Telecharge la derniere version depuis GitHub puis relance
REM  l'application. Vos donnees (config.yaml, historique) sont
REM  conservees.
REM ============================================================
title Mise a jour - Pilotage pharmacie
REM  pushd, et NON "cd /d" : le dossier peut vivre sur un partage
REM  reseau. cmd REFUSE un chemin \\serveur\... comme repertoire
REM  courant : il se rabat sur C:\Windows sans rien demander, et
REM  tout ce qui suit cherche alors app.py dans C:\Windows.
REM  pushd, lui, monte un lecteur temporaire le temps du script.
pushd "%~dp0"
REM  Le script est forcement dans son propre dossier : s'il n'y est
REM  pas, c'est que pushd a echoue et qu'on est ailleurs.
if not exist "%~nx0" goto pas_de_dossier

echo.
echo  ====================================================
echo    Mise a jour de l'utilitaire Pilotage pharmacie
echo  ====================================================
echo.

REM --- 0. Verifier que Python est disponible -----------------
REM --- Recherche de Python -------------------------------------
REM  "where python" ne suffit pas : Windows 10/11 pose un faux
REM  python.exe dans WindowsApps qui ouvre le Microsoft Store au
REM  lieu de demarrer Python. Il repond a "where", mais pas a
REM  "--version" : on teste donc ce qui compte vraiment.
REM  Repli sur le lanceur "py", installe meme quand la case
REM  "Add python.exe to PATH" a ete oubliee.
set "PY="
python --version >nul 2>nul
if not errorlevel 1 set "PY=python"
if not defined PY py -3 --version >nul 2>nul
if not defined PY if not errorlevel 1 set "PY=py -3"
if not defined PY goto pas_de_python

REM --- 0 bis. Qui d'autre travaille sur ce dossier ? ------------
REM  Dossier partage : les autres comptoirs lancent LEUR Streamlit
REM  sur CES fichiers. Les remplacer sous leur session casse leur
REM  ecran en pleine dispensation - Streamlit recharge ses modules
REM  a chaud. La mise a jour automatique s'en garde toute seule ;
REM  ici, c'est quelqu'un qui decide, alors on lui montre qui il
REM  va interrompre.
REM  "--autres" et non "--lister" : sa propre application sera de
REM  toute facon redemarree. Se compter soi-meme ferait apparaitre
REM  l'avertissement a chaque fois, et on apprendrait a passer
REM  outre sans le lire.
set "AUTRES="
for /f "delims=" %%p in ('%PY% presence.py --autres 2^>nul') do set "AUTRES=1"
if defined AUTRES goto postes_ouverts
:dossier_libre

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
robocopy "%EXDIR%\pharmacie-ruptures-main" "%~dp0." /E /NFL /NDL /NJH /NJS /NP /XF mettre-a-jour.bat mettre-a-jour-serveur.bat config.yaml historique_commandes.csv etat_stock_precedent.csv etat_stock_precedent.sig stock_ferme.csv stock_ferme_produits.csv commandes_speciales.csv base_medicaments.csv >nul
if %ERRORLEVEL% GEQ 8 (
    echo  [ERREUR] Copie des fichiers impossible.
    echo.
    pause
    exit /b 1
)
%PY% -m pip install -r requirements.txt --quiet

REM  Icone du Bureau. Elle est aussi posee par lancer.bat, mais qui met a
REM  jour depuis CE script ne passe jamais par lancer.bat : sans cet appel,
REM  l'icone n'apparaitrait tout simplement jamais sur son poste.
REM  /sipremier : rien a faire si elle a deja ete posee une fois.
call "%~dp0creer-raccourci.bat" /silencieux /sipremier

REM  Affiche la version qui vient d'etre installee : sans ce reperage, une
REM  mise a jour qui n'a pas pris passe inapercue.
REM  L'espace fait partie des delimiteurs, et %%~v retire les guillemets :
REM  "VERSION_APP = "3.4"" donne directement 3.4, sans les manipulations
REM  de chaine a guillemets impairs qui trainaient ici.
for /f "tokens=2 delims== " %%v in ('findstr /b "VERSION_APP" app.py') do set "VER=%%~v"
echo.
echo  Version installee : v%VER%
echo  ^(elle doit s'afficher a l'identique dans le bandeau de l'application^)

REM --- 4. Fermeture de l'ancienne version ----------------------
REM  Une ancienne version encore ouverte occupe le port 8501 : la nouvelle
REM  demarrerait alors sur 8502, et l'onglet localhost:8501 continuerait
REM  d'afficher l'ANCIENNE - la mise a jour semblerait sans effet. On ferme
REM  donc nous-memes le processus qui ecoute sur 8501, plutot que de
REM  demander a l'utilisateur d'y penser.
echo  [4/5] Fermeture de la version precedente...
REM  Une seule ligne, tout entre guillemets : cmd ne reinterprete alors ni
REM  le | ni les parentheses. Le try/catch couvre les Windows depourvus de
REM  Get-NetTCPConnection - la mise a jour ne doit jamais echouer ici.
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
REM  Dossier partage : ce poste annonce qu'il travaille sur ces
REM  fichiers, et le retire en partant. Sans cela, un poste qui
REM  demarre a 08h05 remplacerait le code sous la session du
REM  comptoir voisin, en pleine dispensation.
%PY% presence.py --entrer
%PY% -m streamlit run app.py --server.port 8501
REM  La place est rendue : la mise a jour de demain matin pourra
REM  se faire des que tout le monde aura ferme.
%PY% presence.py --sortir
pause
exit /b 0

:postes_ouverts
echo.
echo  [ATTENTION] Ces postes utilisent le dossier en ce moment :
echo.
%PY% presence.py --autres
echo.
echo  Remplacer les fichiers maintenant interrompra leur ecran, en
echo  pleine dispensation. Demandez-leur de fermer leur fenetre, ou
echo  refaites cette mise a jour avant l'ouverture de la pharmacie.
echo.
set "REPONSE="
set /p REPONSE=  Continuer quand meme ? (o/N) : 
if /i "%REPONSE%"=="o" goto dossier_libre
echo.
echo  Mise a jour abandonnee - rien n'a ete modifie.
echo.
pause
exit /b 0

:pas_de_python
echo.
echo  [ERREUR] Python est introuvable sur cet ordinateur.
echo.
echo  1. Installez-le depuis https://www.python.org/downloads/windows/
echo     Prenez "Windows installer (64-bit)" : le nom du fichier doit
echo     finir par -amd64.exe. Un fichier .msix ne s'installe pas ici.
echo  2. Dans la premiere fenetre, cochez "Add python.exe to PATH".
echo  3. FERMEZ cette fenetre noire, puis relancez ce fichier : une
echo     fenetre deja ouverte garde l'ancien PATH et ne verra rien.
echo.
echo  Si ce message revient alors que Python est bien installe, tapez
echo  py --version dans une invite de commandes. Si cela repond, c'est
echo  le PATH qui manque : relancez l'installeur, choisissez Modify,
echo  et cochez la case.
echo.
pause
exit /b 1

:pas_de_dossier
echo.
echo  [ERREUR] Impossible de se placer dans le dossier de l'utilitaire.
echo.
echo      %~dp0
echo.
echo  Ce dossier est sur un partage reseau, et Windows n'a pas pu lui
echo  attribuer de lettre de lecteur temporaire.
echo.
echo  Deux solutions :
echo    - connectez le partage a une lettre de lecteur (clic droit sur
echo      le dossier reseau, puis "Connecter un lecteur reseau"), et
echo      relancez depuis cette lettre ;
echo    - ou copiez le dossier sur le disque de cet ordinateur.
echo.
if /i not "%~1"=="/silencieux" pause
exit /b 1
