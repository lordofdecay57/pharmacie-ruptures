@echo off
REM ============================================================
REM  ICONE SUR UN POSTE DE LA PHARMACIE
REM
REM  A lancer UNE FOIS sur chaque poste. Il pose sur le Bureau
REM  une icone "Pharmacie" qui ouvre l'utilitaire tournant sur
REM  le SERVEUR.
REM
REM  Rien n'est installe sur le poste : ni Python, ni
REM  l'application, ni donnees. L'icone n'est qu'une adresse.
REM
REM  Usage :
REM    creer-raccourci-poste.bat                (demande l'adresse)
REM    creer-raccourci-poste.bat 192.168.1.10   (adresse donnee)
REM ============================================================
setlocal
title Icone Pharmacie - poste de travail

REM  1. L'adresse donnee en parametre l'emporte.
REM  2. Sinon celle laissee par le serveur a cote de ce script
REM     (dossier partage) : personne n'a de chiffres a recopier.
REM  3. Sinon on la demande.
set "ADRESSE=%~1"
if not defined ADRESSE if exist "%~dp0adresse-serveur.txt" set /p ADRESSE=<"%~dp0adresse-serveur.txt"
if not defined ADRESSE (
    echo.
    echo  Adresse du serveur de la pharmacie.
    echo  Elle est affichee dans la fenetre noire du serveur,
    echo  par exemple :  192.168.1.10
    echo.
    set /p ADRESSE=  Adresse du serveur :
)
if not defined ADRESSE goto manquant

REM  On accepte aussi bien "192.168.1.10" que l'adresse complete
REM  recopiee depuis le navigateur : les deux doivent marcher, on ne
REM  va pas reprocher a quelqu'un d'avoir colle ce qu'il voyait.
echo %ADRESSE% | findstr /b /i "http" >nul
if errorlevel 1 set "ADRESSE=http://%ADRESSE%:8501"

echo.
echo  Icone vers %ADRESSE%

REM  Ou poser l'icone ? Le Bureau est souvent redirige vers OneDrive
REM  sur les postes d'entreprise : le chemin en dur pointe alors sur un
REM  dossier vide que personne ne regarde.
set "BUREAU="
for /f "delims=" %%b in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "[Environment]::GetFolderPath('Desktop')" 2^>nul') do set "BUREAU=%%b"
if not defined BUREAU set "BUREAU=%USERPROFILE%\Desktop"
if not exist "%BUREAU%" if defined OneDrive if exist "%OneDrive%\Desktop" set "BUREAU=%OneDrive%\Desktop"
if not exist "%BUREAU%" goto echec

REM  L'icone est COPIEE sur le poste : la laisser sur le partage rend
REM  le Bureau dependant du serveur pour dessiner une image, et une
REM  icone blanche le jour ou le reseau tousse inquiete pour rien.
set "ICONE="
if exist "%~dp0pharmacie.ico" (
    if not exist "%LOCALAPPDATA%\Pharmacie" mkdir "%LOCALAPPDATA%\Pharmacie" >nul 2>nul
    copy /y "%~dp0pharmacie.ico" "%LOCALAPPDATA%\Pharmacie\pharmacie.ico" >nul 2>nul
    if exist "%LOCALAPPDATA%\Pharmacie\pharmacie.ico" set "ICONE=%LOCALAPPDATA%\Pharmacie\pharmacie.ico"
)

REM  Un raccourci Internet : du texte brut, que cmd sait ecrire seul.
REM  Windows l'ouvre dans le navigateur par defaut, avec notre icone.
REM  Aucun PowerShell requis - certains postes d'officine l'interdisent.
set "LIEN=%BUREAU%\Pharmacie.url"
> "%LIEN%" echo [InternetShortcut]
>> "%LIEN%" echo URL=%ADRESSE%
if defined ICONE >> "%LIEN%" echo IconFile=%ICONE%
if defined ICONE >> "%LIEN%" echo IconIndex=0
if not exist "%LIEN%" goto echec

echo.
echo  C'est fait. Double-cliquez sur l'icone "Pharmacie" du Bureau.
echo.
echo  Si l'application ne s'ouvre pas :
echo    - verifiez que la fenetre noire du serveur est toujours ouverte ;
echo    - verifiez que le pare-feu du serveur laisse passer le port 8501.
echo.
pause
exit /b 0

:manquant
echo.
echo  [ERREUR] Aucune adresse de serveur : rien n'a ete cree.
echo.
pause
exit /b 1

:echec
echo.
echo  [ERREUR] L'icone n'a pas pu etre creee sur le Bureau.
echo  Vous pouvez ouvrir l'utilitaire directement dans le navigateur,
echo  a l'adresse : %ADRESSE%
echo.
pause
exit /b 1
