@echo off
REM ============================================================
REM  OUVERTURE AUTOMATIQUE DU MATIN
REM
REM  Lance par la tache planifiee que pose
REM  planifier-ouverture-poste.bat. On ne le double-clique pas :
REM  pour ouvrir l'utilitaire a la main, il y a l'icone du
REM  Bureau.
REM
REM  Il n'ouvre l'utilitaire QU'UNE FOIS PAR JOUR. La tache se
REM  represente tous les quarts d'heure pendant la matinee, pour
REM  rattraper les postes allumes apres l'heure dite ; sans ce
REM  garde-fou, l'ecran surgirait toutes les quinze minutes au
REM  milieu du travail.
REM ============================================================
setlocal
REM  Aucun changement de repertoire : tout est designe par %~dp0,
REM  le chemin de CE fichier. Le dossier peut donc etre un partage
REM  reseau, que cmd refuse comme repertoire courant.

REM  Le temoin est LOCAL au poste. Pose dans le dossier partage,
REM  le premier poste ouvert priverait tous les autres de leur
REM  ouverture du matin.
set "DOSSIER=%LOCALAPPDATA%\Pharmacie"
set "MARQUE=%DOSSIER%\ouvert-le.txt"

REM  La date telle que Windows l'ecrit ici. Le format change d'un
REM  poste a l'autre, mais pas sur un meme poste : c'est tout ce
REM  qu'il faut pour repondre a "est-ce deja fait aujourd'hui ?".
set "AUJOURDHUI=%DATE%"

REM  La lecture est sur sa propre ligne : une redirection accrochee
REM  a un "if" d'une seule ligne est traitee AVANT le test, et se
REM  plaint quand le fichier n'est pas la - c'est-a-dire le premier
REM  matin, exactement le cas qui doit marcher.
set "DEJA="
if not exist "%MARQUE%" goto sans_temoin
set /p DEJA=<"%MARQUE%"
:sans_temoin
if "%DEJA%"=="%AUJOURDHUI%" goto deja_ouvert

REM  Deux installations, et le geste du matin n'est pas le meme :
REM    - avec serveur : le poste ouvre une adresse dans son
REM      navigateur, l'application tourne ailleurs ;
REM    - poste isole : il faut demarrer l'application elle-meme.
REM  adresse-serveur.txt, ecrit par lancer-serveur.bat, tranche
REM  sans rien demander a personne.
set "ADRESSE="
if not exist "%~dp0adresse-serveur.txt" goto sans_serveur
set /p ADRESSE=<"%~dp0adresse-serveur.txt"
:sans_serveur
if not defined ADRESSE goto poste_isole

REM  On accepte "192.168.1.10" comme l'adresse complete : le
REM  fichier peut avoir ete recopie a la main depuis le navigateur.
echo %ADRESSE% | findstr /b /i "http" >nul
if errorlevel 1 set "ADRESSE=http://%ADRESSE%:8501"

REM  Le serveur est-il debout ? A 08:00 il peut encore demarrer.
REM  Ouvrir le navigateur sur un serveur endormi n'afficherait
REM  qu'une page d'erreur - et le temoin du jour empecherait
REM  ensuite toute nouvelle tentative. On prefere ne rien faire et
REM  laisser la tache repasser dans un quart d'heure.
REM  curl est livre avec Windows depuis 2018 ; s'il manque, on
REM  ouvre sans verifier plutot que de ne jamais rien ouvrir.
where curl >nul 2>nul
if errorlevel 1 goto ouvrir_adresse
curl -s -o nul --max-time 5 "%ADRESSE%"
if errorlevel 1 goto pas_encore_pret

:ouvrir_adresse
start "" "%ADRESSE%"
goto marquer

:poste_isole
if not exist "%~dp0lancer.bat" goto rien_a_lancer
REM  "start" et non un appel direct : lancer.bat garde la main tant
REM  que l'application tourne, et la tache planifiee resterait
REM  ouverte derriere elle toute la journee.
start "" "%~dp0lancer.bat"
goto marquer

:marquer
if not exist "%DOSSIER%" mkdir "%DOSSIER%" >nul 2>nul
> "%MARQUE%" echo %AUJOURDHUI%
exit /b 0

:deja_ouvert
REM  Deja ouvert ce matin : c'est le cas NORMAL des repassages du
REM  quart d'heure, pas une anomalie.
exit /b 0

:pas_encore_pret
REM  Rien n'est marque : la prochaine repetition reessaiera, et
REM  ouvrira des que le serveur repondra.
exit /b 0

:rien_a_lancer
exit /b 1
