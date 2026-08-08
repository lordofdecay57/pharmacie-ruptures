@echo off
REM ============================================================
REM  Cree sur le Bureau une icone "Pharmacie" qui lance
REM  l'utilitaire en un double-clic.
REM
REM  Ce script est appele tout seul au premier lancement
REM  (voir lancer.bat). Vous pouvez aussi le double-cliquer a
REM  tout moment pour recreer l'icone si elle a ete supprimee.
REM
REM  Argument /silencieux : ni affichage ni pause (appel
REM  automatique depuis lancer.bat).
REM ============================================================
setlocal
cd /d "%~dp0"

set "SILENCE="
if /i "%~1"=="/silencieux" set "SILENCE=1"
if not defined SILENCE title Raccourci Bureau - Pilotage pharmacie

REM  Chemins passes a PowerShell par variables d'environnement plutot
REM  qu'en ligne de commande : un dossier contenant un espace, une
REM  apostrophe ou un accent casse le meilleur des echappements.
set "APP=%~dp0"
set "CIBLE=%~dp0lancer.bat"
set "ICONE=%~dp0pharmacie.ico"
set "NOM=Pharmacie.lnk"

if not exist "%CIBLE%" (
    if not defined SILENCE (
        echo.
        echo  [ERREUR] lancer.bat est introuvable dans ce dossier.
        echo  Placez ce script a cote de lancer.bat.
        echo.
        pause
    )
    exit /b 1
)

if not defined SILENCE (
    echo.
    echo  Creation de l'icone "Pharmacie" sur le Bureau...
)

REM  GetFolderPath('Desktop') plutot que %USERPROFILE%\Desktop : sur les
REM  postes ou le Bureau est redirige (OneDrive, profil itinerant), le
REM  chemin en dur pointe sur un dossier vide que personne ne voit.
REM  Une seule ligne entre guillemets : cmd ne reinterprete alors ni le
REM  point-virgule ni les parentheses.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$bureau = [Environment]::GetFolderPath('Desktop'); if (-not $bureau) { exit 1 }; $chemin = Join-Path $bureau $env:NOM; $lien = (New-Object -ComObject WScript.Shell).CreateShortcut($chemin); $lien.TargetPath = $env:CIBLE; $lien.WorkingDirectory = $env:APP; $lien.Description = 'Pilotage pharmacie - stock, ruptures et stock ferme'; if (Test-Path $env:ICONE) { $lien.IconLocation = $env:ICONE }; $lien.Save(); if (Test-Path $chemin) { Write-Host ('  Icone creee : ' + $chemin) } else { exit 1 }"

if errorlevel 1 (
    if not defined SILENCE (
        echo.
        echo  [ERREUR] L'icone n'a pas pu etre creee.
        echo  Vous pouvez la faire a la main : clic droit sur lancer.bat,
        echo  puis "Envoyer vers" ^> "Bureau (creer un raccourci)".
        echo.
        pause
    )
    exit /b 1
)

if not defined SILENCE (
    echo.
    echo  C'est fait. Double-cliquez sur l'icone "Pharmacie" du Bureau
    echo  pour ouvrir l'utilitaire.
    echo.
    pause
)
exit /b 0
