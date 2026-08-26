@echo off
REM ============================================================
REM  DEMARRAGE SUR LE SERVEUR
REM
REM  A double-cliquer sur l'ORDINATEUR SERVEUR uniquement.
REM  L'application tourne alors sur cette machine, et tous les
REM  postes de la pharmacie s'y connectent par leur navigateur :
REM  une seule base de donnees, une seule mise a jour.
REM
REM  Les postes n'ont RIEN a installer. Ils recoivent seulement
REM  une icone, posee par creer-raccourci-poste.bat.
REM
REM  IMPORTANT : la fenetre noire qui s'ouvre EST l'application.
REM  La fermer arrete l'utilitaire pour toute la pharmacie.
REM ============================================================
setlocal EnableDelayedExpansion
REM  pushd, et NON "cd /d" : le dossier peut vivre sur un partage
REM  reseau. cmd REFUSE un chemin \\serveur\... comme repertoire
REM  courant : il se rabat sur C:\Windows sans rien demander, et
REM  tout ce qui suit cherche alors app.py dans C:\Windows.
REM  pushd, lui, monte un lecteur temporaire le temps du script.
pushd "%~dp0"
REM  Le script est forcement dans son propre dossier : s'il n'y est
REM  pas, c'est que pushd a echoue et qu'on est ailleurs.
if not exist "%~nx0" goto pas_de_dossier
title Serveur - Pilotage pharmacie  (NE PAS FERMER)

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
%PY% -m pip install -r requirements.txt --quiet

REM  Mise a jour AVANT le demarrage : c'est le seul moment ou remplacer
REM  des fichiers est sans danger. Sur le serveur, cela met a jour la
REM  pharmacie entiere d'un coup.
%PY% maj_auto.py --verbeux
if errorlevel 10 (
    echo.
    echo  [ATTENTION] Une application repond deja sur le port 8501.
    echo  Le serveur est donc DEJA demarre : il n'y a rien a faire.
    echo  Cherchez sa fenetre noire dans la barre des taches.
    echo.
    pause
    exit /b 0
)

REM --- Adresse a donner aux postes -----------------------------
REM  L'adresse de CETTE machine sur le reseau de la pharmacie. On
REM  prend celle de la carte qui porte la passerelle : un poste
REM  avec plusieurs cartes (Wi-Fi, VPN, machine virtuelle) en
REM  affiche sinon une qu'aucun autre poste ne sait joindre.
set "IP="
for /f "delims=" %%a in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$c = Get-NetIPConfiguration ^| Where-Object { $_.IPv4DefaultGateway -ne $null } ^| Select-Object -First 1; if ($c) { $c.IPv4Address.IPAddress }" 2^>nul') do set "IP=%%a"
if not defined IP for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do if not defined IP set "IP=%%a"
set "IP=%IP: =%"
if not defined IP set "IP=adresse-du-serveur"

REM  L'adresse est ecrite a cote de l'application : si ce dossier est
REM  partage sur le reseau, creer-raccourci-poste.bat la lit tout seul
REM  et personne n'a de chiffres a recopier.
> "%~dp0adresse-serveur.txt" echo http://%IP%:8501

echo.
echo  ============================================================
echo    L'utilitaire demarre sur ce serveur.
echo.
echo    Adresse a ouvrir depuis les postes :
echo.
echo        http://%IP%:8501
echo.
echo    Sur chaque poste, lancez une seule fois
echo    creer-raccourci-poste.bat : il pose l'icone du Bureau.
echo.
echo    Un serveur qui tourne en continu ne se met JAMAIS a jour
echo    tout seul. Lancez une fois planifier-maj-serveur.bat :
echo    Windows s'en chargera chaque nuit.
echo.
echo    NE FERMEZ PAS cette fenetre : elle EST l'application.
echo  ============================================================
echo.

REM  Ecoute sur toutes les cartes reseau : sans cela, seule cette
REM  machine pourrait ouvrir l'application. Port fixe, pour que
REM  l'adresse donnee aux postes reste vraie d'un jour a l'autre.
%PY% -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
echo.
echo  Le serveur s'est arrete. Les postes ne peuvent plus s'y connecter.
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
