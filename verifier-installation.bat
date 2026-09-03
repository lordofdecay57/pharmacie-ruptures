@echo off
REM ============================================================
REM  VERIFICATION DE L'INSTALLATION
REM
REM  A double-cliquer sur n'importe quel poste, quand quelque
REM  chose ne marche pas. Il ne repare rien et ne modifie rien :
REM  il REGARDE, et il dit ce qu'il voit.
REM
REM  Ecrit apres une matinee perdue devant un navigateur qui
REM  affichait "localhost a refuse de se connecter" - message
REM  d'Edge, qui ne dit ni que l'application n'etait pas
REM  demarree, ni comment la demarrer. Sept controles valent
REM  mieux qu'un message d'erreur qui ne parle de rien.
REM ============================================================
setlocal
REM  Aucun changement de repertoire : tout est designe par %~dp0,
REM  le chemin de CE fichier. Il fonctionne donc depuis un partage
REM  reseau, que cmd refuse comme repertoire courant.
title Verification de l'installation - Pilotage pharmacie

set "SOUCIS=0"

echo.
echo  ====================================================
echo    Verification de l'installation
echo  ====================================================
echo.
echo  Dossier examine :
echo      %~dp0
echo.

REM --- 1. Le dossier de l'application --------------------------
if not exist "%~dp0app.py" goto sans_application
echo  [OK]      Le programme est bien dans ce dossier.
goto verifier_python

:sans_application
echo  [PROBLEME] app.py est introuvable dans ce dossier.
echo             Ce fichier a ete copie ailleurs que dans le
echo             dossier de l'utilitaire. Remettez-le a cote de
echo             lancer.bat.
set "SOUCIS=1"
goto fin

REM --- 2. Python ------------------------------------------------
:verifier_python
REM  On DEMARRE Python au lieu de chercher son nom : Windows pose
REM  un faux python.exe qui ouvre le Microsoft Store et repond a
REM  "where" sans rien demarrer.
set "PY="
python --version >nul 2>nul
if not errorlevel 1 set "PY=python"
if not defined PY py -3 --version >nul 2>nul
if not defined PY if not errorlevel 1 set "PY=py -3"
if not defined PY goto sans_python
for /f "delims=" %%v in ('%PY% --version 2^>^&1') do set "VERSION_PY=%%v"
echo  [OK]      %VERSION_PY% ^(commande : %PY%^)
goto verifier_streamlit

:sans_python
echo  [PROBLEME] Python est introuvable sur ce poste.
echo             L'application tourne sur CE poste : Python doit y
echo             etre installe. Prenez "Windows installer (64-bit)"
echo             sur python.org/downloads/windows - le fichier doit
echo             finir par -amd64.exe - et cochez
echo             "Add python.exe to PATH".
set "SOUCIS=1"
goto verifier_version

REM --- 3. Les complements Python -------------------------------
:verifier_streamlit
%PY% -c "import streamlit, pandas" >nul 2>nul
if errorlevel 1 goto sans_streamlit
echo  [OK]      Les complements Python sont installes.
goto verifier_port

:sans_streamlit
echo  [PROBLEME] Les complements Python manquent sur ce poste.
echo             Double-cliquez sur lancer.bat : il les installe
echo             tout seul au premier demarrage ^(une a deux
echo             minutes de texte qui defile, c'est normal^).
set "SOUCIS=1"
goto verifier_port

REM --- 4. L'application tourne-t-elle ? ------------------------
REM  C'EST la question derriere "localhost a refuse de se
REM  connecter" : le navigateur ne peut rien afficher si rien
REM  n'ecoute. On pose la question comme le navigateur la pose -
REM  en tentant une connexion - plutot qu'en lisant netstat, dont
REM  les etats changent de nom d'un Windows a l'autre. C'est aussi
REM  le controle exact que fait la mise a jour avant de toucher
REM  aux fichiers.
:verifier_port
if not defined PY goto verifier_version
%PY% -c "import socket,sys; s=socket.socket(); s.settimeout(0.6); sys.exit(0 if s.connect_ex(('127.0.0.1',8501))==0 else 1)" >nul 2>nul
if errorlevel 1 goto application_arretee
echo  [OK]      L'application repond sur le port 8501.
echo            Ouvrez http://localhost:8501 dans le navigateur.
goto verifier_version

:application_arretee
echo  [ARRETEE] L'application n'est pas demarree sur ce poste.
echo            C'est ce que veut dire "localhost a refuse de se
echo            connecter" dans le navigateur : il n'y a rien a
echo            afficher tant qu'elle ne tourne pas.
echo.
echo            Double-cliquez sur lancer.bat, ou sur l'icone
echo            "Pharmacie" du Bureau. La fenetre noire qui
echo            s'ouvre EST l'application : la fermer l'arrete.
set "SOUCIS=1"

REM --- 5. La version : celle du dossier ET celle publiee --------
REM  "Mes modifications n'apparaissent pas" : la question revient a
REM  chaque mise a jour, et personne ne peut y repondre sans
REM  comparer les deux numeros. Alors on les affiche cote a cote.
:verifier_version
set "VER="
for /f "tokens=2 delims== " %%v in ('findstr /b "VERSION_APP" "%~dp0app.py" 2^>nul') do set "VER=%%~v"
if not defined VER set "VER=?"
echo  [INFO]    Version dans CE dossier : v%VER%

if not defined PY goto sans_comparaison
REM  La version publiee, lue par maj_auto lui-meme : deux facons de
REM  la chercher finiraient par ne plus donner la meme reponse.
set "PUBLIEE="
for /f "delims=" %%v in ('%PY% -c "import sys; sys.path.insert(0, sys.argv[1]); import maj_auto; print(maj_auto.version_publiee(10))" "%~dp0." 2^>nul') do set "PUBLIEE=%%v"
if not defined PUBLIEE goto sans_comparaison
echo  [INFO]    Derniere version publiee : v%PUBLIEE%
if "%VER%"=="%PUBLIEE%" goto version_a_jour

echo  [PROBLEME] Ce dossier n'est PAS a jour.
echo             Remplacez son contenu par l'archive du depot, en
echo             gardant vos fichiers .csv et config.yaml.
echo             ATTENTION : fermez d'abord toutes les fenetres
echo             noires de l'application. Windows ne peut pas
echo             remplacer un fichier qu'un programme tient ouvert,
echo             et la copie echoue en silence.
set "SOUCIS=1"
goto sans_comparaison

:version_a_jour
echo  [OK]      Ce dossier est a jour.
echo            Si l'ecran affiche encore l'ancienne version, c'est
echo            que l'application n'a pas ete RELANCEE : elle garde
echo            son programme en memoire. Fermez la fenetre noire,
echo            rouvrez-la, puis Ctrl + Maj + R dans le navigateur.

:sans_comparaison

REM --- 6. Le mode d'installation -------------------------------
if not exist "%~dp0adresse-serveur.txt" goto sans_adresse
set "ADRESSE="
set /p ADRESSE=<"%~dp0adresse-serveur.txt"
echo  [INFO]    Un serveur a demarre depuis ce dossier : %ADRESSE%
echo            Les postes ouvrent cette adresse dans leur
echo            navigateur, ils ne lancent pas l'application.
goto verifier_postes

:sans_adresse
echo  [INFO]    Pas de serveur declare : chaque poste lance
echo            l'application lui-meme, depuis ce dossier.

REM --- 7. Qui travaille sur ce dossier en ce moment ------------
:verifier_postes
if not defined PY goto verifier_donnees
if not exist "%~dp0presence.py" goto verifier_donnees
REM  "%~dp0." et non "%~dp0" : le chemin se termine par un
REM  antislash, et Python lit alors \" comme un guillemet echappe -
REM  le dossier arriverait ampute de sa fermeture de citation.
set "QUELQU_UN="
for /f "delims=" %%p in ('%PY% "%~dp0presence.py" --dossier "%~dp0." --lister 2^>nul') do set "QUELQU_UN=1"
if not defined QUELQU_UN goto personne
echo  [INFO]    Postes utilisant ce dossier en ce moment :
%PY% "%~dp0presence.py" --dossier "%~dp0." --lister
goto verifier_donnees

:personne
echo  [INFO]    Personne d'autre n'utilise ce dossier.
echo            Une mise a jour peut se faire sans risque.

REM --- 8. Les donnees de la pharmacie --------------------------
:verifier_donnees
echo.
echo  Donnees de la pharmacie presentes dans ce dossier :
set "AUCUNE=1"
call :fichier "stock_ferme.csv" "inventaire du stock interne"
call :fichier "stock_ferme_produits.csv" "produits memorises"
call :fichier "commandes_speciales.csv" "commandes speciales"
call :fichier "historique_commandes.csv" "historique des analyses"
call :fichier "config.yaml" "reglages"
if defined AUCUNE echo      aucune - normal sur une installation neuve

echo.
echo  ====================================================
if "%SOUCIS%"=="0" goto tout_va_bien
echo    Au moins un point a corriger - voir [PROBLEME]
echo    et [ARRETEE] ci-dessus.
goto termine

:tout_va_bien
echo    Tout est en place.

:termine
echo  ====================================================
echo.
pause
exit /b 0

REM  Une ligne par fichier de donnees, avec sa date : "il est la"
REM  ne suffit pas, un fichier fige depuis trois semaines se
REM  remarque a sa date, pas a son existence.
:fichier
if not exist "%~dp0%~1" exit /b 0
set "AUCUNE="
for %%f in ("%~dp0%~1") do echo      %~1 - %~2 - %%~zf octets - %%~tf
exit /b 0

:fin
echo.
pause
exit /b 1
