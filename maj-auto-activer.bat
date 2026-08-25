@echo off
REM ============================================================
REM  Active la mise a jour automatique au demarrage de Windows.
REM
REM  Cree une tache planifiee qui, a chaque ouverture de session,
REM  verifie discretement si une nouvelle version est publiee et
REM  l'installe. La tache ne fait RIEN si l'application tourne
REM  deja : remplacer des fichiers sous une session ouverte
REM  casserait le travail en cours.
REM
REM  pythonw.exe (et non python.exe) : aucune fenetre noire.
REM ============================================================
title Mise a jour automatique - Pilotage pharmacie
cd /d "%~dp0"

set "TACHE=Pilotage pharmacie - mise a jour"

echo.
echo  ====================================================
echo    Mise a jour automatique au demarrage de Windows
echo  ====================================================
echo.

REM --- Python doit etre disponible ----------------------------
REM  On teste la version CONSOLE (python, puis le lanceur py) : cmd
REM  attend vraiment sa fin et son code de sortie veut dire quelque
REM  chose. pythonw rend la main aussitot, sans rien signaler.
REM  Le repli "py" sert quand la case "Add python.exe to PATH" a ete
REM  oubliee a l'installation - l'oubli le plus courant.
set "PYW="
python --version >nul 2>nul
if not errorlevel 1 set "PYW=pythonw"
if not defined PYW py -3 --version >nul 2>nul
if not defined PYW if not errorlevel 1 set "PYW=pyw -3"
if not defined PYW goto pas_de_python

REM --- Creation de la tache -----------------------------------
REM  /RL LIMITED : droits de l'utilisateur, aucune elevation.
REM  /F : remplace la tache si elle existe deja.
schtasks /Create /TN "%TACHE%" /SC ONLOGON /RL LIMITED /F ^
  /TR "%PYW% \"%~dp0maj_auto.py\"" >nul 2>nul
if errorlevel 1 (
    echo  [ERREUR] Impossible de creer la tache planifiee.
    echo  Relancez ce fichier par un clic droit, puis Executer en tant
    echo  qu'administrateur.
    echo.
    pause
    exit /b 1
)

echo  Mise a jour automatique ACTIVEE.
echo.
echo  A chaque ouverture de session Windows, l'utilitaire verifiera
echo  discretement s'il existe une nouvelle version et l'installera.
echo.
echo  - Rien n'est touche si l'application est ouverte.
echo  - Rien n'est touche si le poste est hors ligne.
echo  - Vos donnees ^(inventaire, historique, reglages^) sont
echo    toujours preservees.
echo  - Le detail est consigne dans le fichier maj_auto.log.
echo.
echo  Pour desactiver : double-cliquez sur maj-auto-desactiver.bat
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
