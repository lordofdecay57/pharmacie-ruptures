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
cd /d "%~dp0"
title Serveur - Pilotage pharmacie  (NE PAS FERMER)

where python >nul 2>nul
if errorlevel 1 (
    echo Python n'est pas installe. Installez-le depuis https://www.python.org/downloads/
    echo (cochez "Add Python to PATH" pendant l'installation^)
    pause
    exit /b 1
)
python -m pip install -r requirements.txt --quiet

REM  Mise a jour AVANT le demarrage : c'est le seul moment ou remplacer
REM  des fichiers est sans danger. Sur le serveur, cela met a jour la
REM  pharmacie entiere d'un coup.
python maj_auto.py --verbeux
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
python -m streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
echo.
echo  Le serveur s'est arrete. Les postes ne peuvent plus s'y connecter.
pause
