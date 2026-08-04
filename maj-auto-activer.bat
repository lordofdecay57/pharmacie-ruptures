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
where pythonw >nul 2>nul
if errorlevel 1 (
    echo  [ERREUR] Python n'est pas installe ou absent du PATH.
    echo  Installez-le depuis https://www.python.org/downloads/
    echo  en cochant "Add Python to PATH" pendant l'installation.
    echo.
    pause
    exit /b 1
)

REM --- Creation de la tache -----------------------------------
REM  /RL LIMITED : droits de l'utilisateur, aucune elevation.
REM  /F : remplace la tache si elle existe deja.
schtasks /Create /TN "%TACHE%" /SC ONLOGON /RL LIMITED /F ^
  /TR "pythonw \"%~dp0maj_auto.py\"" >nul 2>nul
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
