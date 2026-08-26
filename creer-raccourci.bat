@echo off
REM ============================================================
REM  Cree sur le Bureau une icone "Pilotage pharmacie" qui lance
REM  l'utilitaire en un double-clic.
REM
REM  Appele automatiquement par lancer.bat ET par
REM  mettre-a-jour.bat : selon l'habitude de chacun, l'un ou
REM  l'autre peut ne jamais etre lance, et l'icone doit
REM  apparaitre dans les deux cas.
REM
REM  Vous pouvez aussi le double-cliquer a tout moment pour
REM  recreer l'icone si elle a ete supprimee.
REM
REM  Options :
REM    /silencieux  ni titre ni pause (appel automatique)
REM    /sipremier   ne rien faire si l'icone a deja ete posee
REM                 une fois sur ce poste
REM ============================================================
setlocal
REM  Aucun changement de repertoire : tout ce que ce script touche
REM  est designe par %~dp0, le chemin de CE fichier. Il fonctionne
REM  donc depuis un partage reseau (\\serveur\...), que cmd refuse
REM  comme repertoire courant - il se rabattrait sur C:\Windows.

set "SILENCE="
set "SIPREMIER="
if /i "%~1"=="/silencieux" set "SILENCE=1"
if /i "%~2"=="/silencieux" set "SILENCE=1"
if /i "%~1"=="/sipremier" set "SIPREMIER=1"
if /i "%~2"=="/sipremier" set "SIPREMIER=1"
if not defined SILENCE title Raccourci Bureau - Pilotage pharmacie

REM  Chemins passes a PowerShell par variables d'environnement plutot
REM  qu'en ligne de commande : un dossier contenant un espace, une
REM  apostrophe ou un accent casse le meilleur des echappements.
set "APP=%~dp0"
set "CIBLE=%~dp0lancer.bat"
REM  Le temoin est LOCAL au poste, jamais dans le dossier de
REM  l'application : celui-ci peut etre un partage reseau, et le
REM  premier poste equipe priverait alors TOUS les autres de leur
REM  icone - ils liraient "deja fait" devant un Bureau vide.
set "LOCAL_PHARMACIE=%LOCALAPPDATA%\Pharmacie"
set "TEMOIN=%LOCAL_PHARMACIE%\raccourci-bureau.txt"
REM  L'icone est COPIEE sur le poste, comme le fait deja
REM  creer-raccourci-poste.bat. La laisser sur le partage a deux
REM  effets : le Bureau depend du serveur pour dessiner une image,
REM  et surtout l'Explorateur GARDE LE FICHIER OUVERT pour chaque
REM  raccourci pose. Une mise a jour ne pouvait alors plus le
REM  remplacer : robocopy reessayait sans fin, ecran fige sur
REM  "Installation des fichiers...".
set "ICONE=%~dp0pharmacie.ico"
if exist "%ICONE%" (
    if not exist "%LOCAL_PHARMACIE%" mkdir "%LOCAL_PHARMACIE%" >nul 2>nul
    copy /y "%ICONE%" "%LOCAL_PHARMACIE%\pharmacie.ico" >nul 2>nul
)
if exist "%LOCAL_PHARMACIE%\pharmacie.ico" set "ICONE=%LOCAL_PHARMACIE%\pharmacie.ico"
REM  Le MEME nom partout : ce script, creer-raccourci-poste.bat
REM  et raccourci.py posent la meme icone. S'ils divergent, un
REM  poste finit avec deux icones et personne ne sait laquelle
REM  ouvre quoi.
set "NOM=Pilotage pharmacie.lnk"
set "NOM_URL=Pilotage pharmacie.url"

REM  Temoin : il contient la version pour laquelle l'icone a ete posee.
REM   - meme version : on ne fait rien, une icone supprimee volontairement
REM     ne revient pas a chaque demarrage ;
REM   - version differente : on la repose une fois. C'est ce qui rafraichit
REM     le cache d'icones de Windows quand le visuel a change - sans quoi
REM     le Bureau continue d'afficher l'ancien dessin.
REM  Tout se fait hors bloc parenthese : cmd n'y developpe les variables
REM  qu'une fois, avant execution, et la comparaison serait faussee.
set "VER="
for /f "tokens=2 delims== " %%v in ('findstr /b "VERSION_APP" "%~dp0app.py" 2^>nul') do set "VER=%%~v"
if not defined VER set "VER=?"
REM  La lecture est sur sa propre ligne : une redirection accrochee a un
REM  "if" d'une seule ligne est l'un des pieges classiques de cmd.
set "DEJA="
if not exist "%TEMOIN%" goto sans_temoin
set /p DEJA=<"%TEMOIN%"
:sans_temoin
REM  Le temoin dit que l'icone a ete POSEE, pas qu'elle EXISTE. Une
REM  pose ratee - PowerShell interdit par strategie de groupe, Bureau
REM  redirige vers OneDrive - l'ecrivait quand meme, et /sipremier ne
REM  reessayait alors PLUS JAMAIS : le Bureau restait vide sans que rien
REM  ne le signale. C'est le "l'icone n'apparait pas sur certains
REM  postes" remonte par la pharmacie. On regarde donc le Bureau.
set "DEJA_LA="
if not defined SIPREMIER goto poser
if not "%DEJA%"=="%VER%" goto poser
call :chercher_icone
if defined DEJA_LA exit /b 0
:poser

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
    echo  Creation de l'icone "Pilotage pharmacie" sur le Bureau...
)

REM --- Methode normale : un vrai raccourci Windows (.lnk) -------
REM  GetFolderPath('Desktop') plutot que %USERPROFILE%\Desktop : sur les
REM  postes ou le Bureau est redirige (OneDrive, profil itinerant), le
REM  chemin en dur pointe sur un dossier vide que personne ne voit.
REM  Une seule ligne entre guillemets : cmd ne reinterprete alors ni le
REM  point-virgule ni les parentheses.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$bureau = [Environment]::GetFolderPath('Desktop'); if (-not $bureau) { exit 1 }; $chemin = Join-Path $bureau $env:NOM; $lien = (New-Object -ComObject WScript.Shell).CreateShortcut($chemin); $lien.TargetPath = $env:CIBLE; $lien.WorkingDirectory = $env:APP; $lien.Description = 'Pilotage pharmacie - stock, ruptures et stock ferme'; if (Test-Path $env:ICONE) { $lien.IconLocation = $env:ICONE }; $lien.Save(); if (Test-Path $chemin) { Write-Host ('  Icone posee sur le Bureau : ' + $chemin) } else { exit 1 }"
if not errorlevel 1 goto pose

REM --- Repli : un raccourci Internet (.url) --------------------
REM  Certains postes d'officine interdisent PowerShell par strategie de
REM  groupe. Le .url est du texte brut : cmd sait l'ecrire seul, et
REM  Windows l'affiche avec notre icone comme n'importe quel raccourci.
set "BUREAU=%USERPROFILE%\Desktop"
if not exist "%BUREAU%" if defined OneDrive if exist "%OneDrive%\Desktop" set "BUREAU=%OneDrive%\Desktop"
if not exist "%BUREAU%" goto echec

set "URLCIBLE=%CIBLE:\=/%"
> "%BUREAU%\%NOM_URL%" echo [InternetShortcut]
>> "%BUREAU%\%NOM_URL%" echo URL=file:///%URLCIBLE%
>> "%BUREAU%\%NOM_URL%" echo IconFile=%ICONE%
>> "%BUREAU%\%NOM_URL%" echo IconIndex=0
if not exist "%BUREAU%\%NOM_URL%" goto echec
echo  Icone posee sur le Bureau : %BUREAU%\%NOM_URL%

:pose
REM  L'ancienne icone "Pharmacie" est retiree : deux icones cote a
REM  cote, dont une qui pointe peut-etre sur une installation
REM  supprimee, c'est la garantie qu'on cliquera un jour la mauvaise.
call :retirer "%USERPROFILE%\Desktop"
if defined OneDrive call :retirer "%OneDrive%\Desktop"
REM  Windows garde les icones en cache : sans ce rafraichissement, le
REM  Bureau affiche encore l'ancien dessin, ou un carre blanc. La
REM  commande n'existe pas partout - son echec est sans consequence.
ie4uinit.exe -show >nul 2>nul

REM  Le temoin n'est ecrit qu'en cas de succes : une tentative ratee sera
REM  refaite au lancement suivant.
if not exist "%LOCAL_PHARMACIE%" mkdir "%LOCAL_PHARMACIE%" >nul 2>nul
> "%TEMOIN%" echo %VER%
if not defined SILENCE (
    echo.
    echo  C'est fait. Double-cliquez sur l'icone "Pilotage pharmacie"
    echo  pour ouvrir l'utilitaire.
    echo.
    pause
)
exit /b 0

REM  L'icone est-elle reellement sur le Bureau ? On regarde les deux
REM  emplacements possibles - le Bureau peut etre redirige vers OneDrive
REM  sur les postes d'entreprise - et les deux formes, .lnk et .url.
:retirer
if exist "%~1\Pharmacie.lnk" del /q "%~1\Pharmacie.lnk" >nul 2>nul
if exist "%~1\Pharmacie.url" del /q "%~1\Pharmacie.url" >nul 2>nul
exit /b 0

:chercher_icone
set "DEJA_LA="
call :voir "%USERPROFILE%\Desktop"
if defined OneDrive call :voir "%OneDrive%\Desktop"
exit /b 0

:voir
if exist "%~1\%NOM%" set "DEJA_LA=1"
if exist "%~1\%NOM_URL%" set "DEJA_LA=1"
exit /b 0

:echec
REM  Meme en mode silencieux, on le DIT : une icone qui n'apparait pas
REM  sans un mot d'explication laisse chercher longtemps.
echo.
echo  [ATTENTION] L'icone du Bureau n'a pas pu etre creee.
echo  Faites-la a la main : clic droit sur lancer.bat, puis
echo  "Envoyer vers" ^> "Bureau (creer un raccourci)".
echo.
if not defined SILENCE pause
exit /b 1
