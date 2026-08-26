@echo off
REM ============================================================
REM  Desactive la mise a jour automatique au demarrage de Windows.
REM  L'application continue de se mettre a jour au lancement
REM  (lancer.bat) et par mettre-a-jour.bat.
REM ============================================================
title Mise a jour automatique - Pilotage pharmacie
REM  Aucun changement de repertoire : tout ce que ce script touche
REM  est designe par %~dp0, le chemin de CE fichier. Il fonctionne
REM  donc depuis un partage reseau (\\serveur\...), que cmd refuse
REM  comme repertoire courant - il se rabattrait sur C:\Windows.

set "TACHE=Pilotage pharmacie - mise a jour"

echo.
echo  ====================================================
echo    Desactivation de la mise a jour automatique
echo  ====================================================
echo.

schtasks /Delete /TN "%TACHE%" /F >nul 2>nul
if errorlevel 1 (
    echo  Aucune tache automatique n'etait active.
) else (
    echo  Mise a jour automatique DESACTIVEE.
)
echo.
echo  L'utilitaire se mettra toujours a jour :
echo    - au lancement, via lancer.bat ;
echo    - a la demande, via mettre-a-jour.bat.
echo.
pause
exit /b 0
