@echo off
REM ============================================================
REM  MISE A JOUR DU SERVEUR
REM
REM  Meme travail que mettre-a-jour.bat, mais pour une machine
REM  qui fait tourner l'application pour toute la pharmacie :
REM  elle est relancee en mode SERVEUR (ecoute sur le reseau),
REM  et non en mode poste isole.
REM
REM  A double-cliquer quand le bandeau signale une version, ou
REM  a laisser faire par la tache planifiee la nuit
REM  (voir planifier-maj-serveur.bat).
REM
REM  Option :
REM    /silencieux   aucune pause, aucune attente de frappe.
REM                  C'est ce que lance la tache planifiee : un
REM                  "Appuyez sur une touche" la bloquerait
REM                  jusqu'au matin, application arretee.
REM
REM  ATTENTION : la mise a jour REDEMARRE l'application. Les
REM  postes perdent leur page quelques secondes, et une fiche
REM  en cours de saisie est perdue. D'ou l'heure creuse.
REM ============================================================
setlocal
REM  pushd, et NON "cd /d" : le dossier peut vivre sur un partage
REM  reseau. cmd REFUSE un chemin \\serveur\... comme repertoire
REM  courant : il se rabat sur C:\Windows sans rien demander, et
REM  tout ce qui suit cherche alors app.py dans C:\Windows.
REM  pushd, lui, monte un lecteur temporaire le temps du script.
pushd "%~dp0"
REM  Le script est forcement dans son propre dossier : s'il n'y est
REM  pas, c'est que pushd a echoue et qu'on est ailleurs.
if not exist "%~nx0" goto pas_de_dossier

set "SILENCE="
if /i "%~1"=="/silencieux" set "SILENCE=1"
if not defined SILENCE title Mise a jour du serveur - Pilotage pharmacie

set "JOURNAL=%~dp0maj_serveur.log"
set "URL=https://github.com/lordofdecay57/pharmacie-ruptures/archive/refs/heads/main.zip"
set "ZIP=%TEMP%\pharmacie-maj-serveur.zip"
set "EXDIR=%TEMP%\pharmacie-maj-serveur"

REM  Horodatage pour le journal. Une mise a jour faite a 5 h du matin
REM  doit rester explicable au matin, sans que personne ne l'ait vue.
for /f "tokens=1-2 delims= " %%a in ("%DATE% %TIME%") do set "QUAND=%%a %%b"

call :dire "===================================================="
call :dire "  Mise a jour du serveur - %QUAND%"
call :dire "===================================================="

REM --- 0. Python -----------------------------------------------
REM  "where python" ne suffit pas : Windows pose un faux python.exe
REM  dans WindowsApps qui ouvre le Microsoft Store au lieu de demarrer
REM  Python. Il repond a "where", mais pas a "--version". Repli sur le
REM  lanceur "py", installe meme quand la case "Add python.exe to PATH"
REM  a ete oubliee - c'est l'oubli le plus courant de l'installation.
set "PY="
python --version >nul 2>nul
if not errorlevel 1 set "PY=python"
if not defined PY py -3 --version >nul 2>nul
if not defined PY if not errorlevel 1 set "PY=py -3"
if not defined PY goto pas_de_python

REM  Version avant, pour que le journal dise d'ou l'on part.
set "AVANT="
for /f "tokens=2 delims== " %%v in ('findstr /b "VERSION_APP" app.py 2^>nul') do set "AVANT=%%~v"
if not defined AVANT set "AVANT=?"

REM --- 1. Telechargement ---------------------------------------
call :dire "[1/5] Telechargement de la derniere version..."
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri '%URL%' -OutFile '%ZIP%' -UseBasicParsing } catch { exit 1 }"
if errorlevel 1 (
    call :dire "[ERREUR] Telechargement impossible - verifiez la connexion Internet."
    goto echec
)

REM --- 2. Extraction -------------------------------------------
call :dire "[2/5] Extraction..."
if exist "%EXDIR%" rmdir /s /q "%EXDIR%"
powershell -NoProfile -Command "try { Expand-Archive -Path '%ZIP%' -DestinationPath '%EXDIR%' -Force } catch { exit 1 }"
if errorlevel 1 (
    call :dire "[ERREUR] Extraction impossible."
    goto echec
)

REM --- 3. Installation -----------------------------------------
REM  On ne remplace ni les scripts de mise a jour (ils sont en cours
REM  d'execution : cmd relit le fichier au fil des lignes, et le
REM  reecrire sous ses pieds lui ferait executer n'importe quoi), ni
REM  les donnees de la pharmacie. Cette liste doit rester identique a
REM  celle de mettre-a-jour.bat et a maj_auto.FICHIERS_PROTEGES : un
REM  test le verifie.
call :dire "[3/5] Installation des fichiers..."
robocopy "%EXDIR%\pharmacie-ruptures-main" "%~dp0." /E /NFL /NDL /NJH /NJS /NP /XF mettre-a-jour.bat mettre-a-jour-serveur.bat config.yaml historique_commandes.csv etat_stock_precedent.csv etat_stock_precedent.sig stock_ferme.csv stock_ferme_produits.csv commandes_speciales.csv base_medicaments.csv >nul
if %ERRORLEVEL% GEQ 8 (
    call :dire "[ERREUR] Copie des fichiers impossible."
    goto echec
)
%PY% -m pip install -r requirements.txt --quiet

set "APRES="
for /f "tokens=2 delims== " %%v in ('findstr /b "VERSION_APP" app.py 2^>nul') do set "APRES=%%~v"
if not defined APRES set "APRES=?"
call :dire "  Version : v%AVANT% vers v%APRES%"

REM  Pas d'icone du Bureau ici : sur un serveur, personne ne s'assoit
REM  devant. Les postes ont la leur, posee par creer-raccourci-poste.bat.

REM --- 4. Arret de la version en cours --------------------------
REM  L'ancienne version occupe le port 8501 : la nouvelle demarrerait
REM  sur 8502 et les postes continueraient d'afficher l'ANCIENNE, sans
REM  que rien ne le signale. On ferme donc nous-memes le processus qui
REM  ecoute, plutot que d'esperer que quelqu'un y pense.
call :dire "[4/5] Arret de la version precedente..."
powershell -NoProfile -Command "try { Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } } catch { }" >nul 2>nul
timeout /t 3 /nobreak >nul

powershell -NoProfile -Command "try { exit ((Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count) } catch { exit 0 }"
if errorlevel 1 (
    call :dire "[ATTENTION] Le port 8501 est toujours occupe - demarrage tente quand meme."
)

REM --- 5. Redemarrage en mode serveur ---------------------------
REM  Les deux options sont ce qui distingue un serveur d'un poste :
REM  ecoute sur toutes les cartes reseau, et aucun navigateur a ouvrir.
REM  Les oublier relancerait l'application avec les reglages d'un poste
REM  isole - et le contrat de lancer-serveur.bat cesserait de valoir.
call :dire "[5/5] Redemarrage du serveur..."
call :dire "  L'application repart sur le port 8501 de ce serveur."
call :dire ""
if defined SILENCE goto detache

REM  Double-clic : l'application vit dans CETTE fenetre, comme avec
REM  lancer-serveur.bat. La fermer arrete le serveur - c'est la regle
REM  que la pharmacie connait deja, on ne la change pas.
%PY% -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
call :dire "Le serveur s'est arrete. Les postes ne peuvent plus s'y connecter."
pause
exit /b 0

:detache
REM  Lancee par la tache planifiee. L'application doit alors vivre PLUS
REM  LONGTEMPS que la tache qui la demarre : le planificateur de Windows
REM  arrete par defaut toute tache depassant 72 heures, et la garder au
REM  premier plan tuerait donc le serveur tous les trois jours, en pleine
REM  journee, sans que rien ne l'explique.
REM  "start" lui donne son propre processus : la tache se termine en
REM  quelques secondes, l'application reste.
REM  L'enfant monte SON PROPRE lecteur : il herite du repertoire
REM  courant, mais pas du montage temporaire qui le rend valide.
REM  Ce montage appartient a cette fenetre-ci, qui se termine
REM  dans la seconde - le serveur repartirait alors sans dossier.
start "Serveur - Pilotage pharmacie" /min cmd /c pushd "%~dp0" ^& %PY% -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
call :dire "Serveur redemarre dans sa propre fenetre."
exit /b 0

:pas_de_python
call :dire "[ERREUR] Python est introuvable sur ce serveur."
call :dire "  Installez-le depuis https://www.python.org/downloads/windows/"
call :dire "  Prenez Windows installer 64-bit : le nom du fichier doit"
call :dire "  finir par -amd64.exe. Un fichier .msix ne s'installe pas ici."
call :dire "  Cochez Add python.exe to PATH dans la premiere fenetre, puis"
call :dire "  FERMEZ cette fenetre et relancez ce fichier."
goto echec

:echec
call :dire "Mise a jour abandonnee - rien n'a ete modifie, l'application"
call :dire "en cours continue de tourner."
if not defined SILENCE pause
exit /b 1

REM  Un seul endroit qui ecrit : a l'ecran ET dans le journal. Deux
REM  appels separes finiraient par diverger, et le journal ne raconterait
REM  plus la meme histoire que la fenetre.
REM
REM  %~1 RETIRE les guillemets : un message contenant < > | ou ^& serait
REM  alors compris comme une redirection, et cmd irait ecrire dans un
REM  fichier au lieu d'afficher la phrase. Un test l'interdit.
:dire
echo.%~1
>> "%JOURNAL%" echo.%~1
exit /b 0

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
