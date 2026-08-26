@echo off
REM ============================================================
REM  MISE A JOUR AUTOMATIQUE DU SERVEUR, CHAQUE NUIT
REM
REM  A lancer UNE FOIS sur le serveur. Il demande a Windows de
REM  lancer mettre-a-jour-serveur.bat tous les jours a heure
REM  creuse.
REM
REM  Pourquoi c'est necessaire : la mise a jour automatique
REM  habituelle n'a lieu qu'au DEMARRAGE, et elle se reporte
REM  tant que l'application repond. Un serveur qui tourne en
REM  continu ne remplit jamais ces deux conditions - sans cette
REM  tache, il resterait indefiniment sur sa version du
REM  premier jour.
REM
REM  Usage :
REM    planifier-maj-serveur.bat              tous les jours a 05:00
REM    planifier-maj-serveur.bat 04:30        a l'heure voulue
REM    planifier-maj-serveur.bat /supprimer   retire la tache
REM ============================================================
setlocal
REM  Aucun changement de repertoire : tout ce que ce script touche
REM  est designe par %~dp0, le chemin de CE fichier. Il fonctionne
REM  donc depuis un partage reseau (\\serveur\...), que cmd refuse
REM  comme repertoire courant - il se rabattrait sur C:\Windows.
title Mise a jour automatique du serveur - Pilotage pharmacie

set "TACHE=Pilotage pharmacie - mise a jour"
set "SCRIPT=%~dp0mettre-a-jour-serveur.bat"

if /i "%~1"=="/supprimer" goto supprimer

set "HEURE=%~1"
if not defined HEURE set "HEURE=05:00"

if not exist "%SCRIPT%" (
    echo.
    echo  [ERREUR] mettre-a-jour-serveur.bat est introuvable dans ce dossier.
    echo  Placez ce script a cote de lui.
    echo.
    pause
    exit /b 1
)

echo.
echo  Creation de la tache "%TACHE%"
echo  Tous les jours a %HEURE%.
echo.

REM  Pas de /ru SYSTEM : la tache doit s'executer dans la session de
REM  l'utilisateur connecte, car c'est la que vit la fenetre noire de
REM  l'application. Lancee par SYSTEM, la nouvelle instance demarrerait
REM  dans une session invisible et personne ne pourrait plus l'arreter.
REM  C'est aussi ce qui evite d'avoir a lancer ce script en
REM  administrateur.
schtasks /create /tn "%TACHE%" /tr "\"%SCRIPT%\" /silencieux" /sc daily /st %HEURE% /f
if errorlevel 1 (
    echo.
    echo  [ERREUR] La tache n'a pas pu etre creee.
    echo  Verifiez le format de l'heure : deux chiffres, deux points,
    echo  deux chiffres. Par exemple 05:00 ou 04:30.
    echo.
    pause
    exit /b 1
)

echo.
echo  Voici ce qui a ete enregistre :
echo.
REM  On AFFICHE la tache plutot que d'affirmer qu'elle existe : une
REM  ligne de confirmation ne prouve rien, la fiche de Windows si.
schtasks /query /tn "%TACHE%"
echo.
echo  C'est fait. Chaque nuit a %HEURE%, le serveur se mettra a jour
echo  et redemarrera tout seul.
echo.
echo  A savoir :
echo    - la session Windows du serveur doit rester OUVERTE (ecran
echo      verrouille, c'est bien ; deconnecte, la tache ne partira pas^) ;
echo    - la mise a jour redemarre l'application : les postes perdent
echo      leur page quelques secondes ;
echo    - le compte rendu de chaque nuit est dans maj_serveur.log.
echo.
pause
exit /b 0

:supprimer
echo.
echo  Suppression de la tache "%TACHE%"...
schtasks /delete /tn "%TACHE%" /f
if errorlevel 1 (
    echo.
    echo  [ATTENTION] La tache n'existait pas, ou n'a pas pu etre retiree.
    echo.
    pause
    exit /b 1
)
echo.
echo  C'est fait. Le serveur ne se mettra plus a jour tout seul :
echo  double-cliquez sur mettre-a-jour-serveur.bat quand le bandeau
echo  de l'application signale une nouvelle version.
echo.
pause
exit /b 0
