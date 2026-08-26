@echo off
REM ============================================================
REM  OUVERTURE AUTOMATIQUE A 08:00, SUR CE POSTE
REM
REM  A lancer UNE FOIS sur chaque poste de la pharmacie, comme
REM  creer-raccourci-poste.bat - et depuis le meme dossier
REM  partage. Il n'y a pas de reglage central : Windows ne
REM  connait que les taches de la machine ou on les cree.
REM
REM  Chaque matin, l'utilitaire s'ouvre tout seul : l'ecran du
REM  matin (peremptions, commandes a facturer, a commander) est
REM  la avant qu'on y pense, plutot qu'apres.
REM
REM  L'ouverture n'a lieu qu'UNE FOIS par jour, meme si le poste
REM  est allume en retard : la tache repasse tous les quarts
REM  d'heure pendant quatre heures et s'arrete des qu'elle a
REM  reussi.
REM
REM  Usage :
REM    planifier-ouverture-poste.bat              tous les jours a 08:00
REM    planifier-ouverture-poste.bat 07:45        a l'heure voulue
REM    planifier-ouverture-poste.bat /supprimer   retire la tache
REM ============================================================
setlocal
REM  Aucun changement de repertoire : tout ce que ce script touche
REM  est designe par %~dp0, le chemin de CE fichier. Il fonctionne
REM  donc depuis un partage reseau (\\serveur\...), que cmd refuse
REM  comme repertoire courant - il se rabattrait sur C:\Windows.
title Ouverture automatique du matin - Pilotage pharmacie

set "TACHE=Pilotage pharmacie - ouverture du matin"
set "SCRIPT=%~dp0ouvrir-le-matin.bat"

REM  Quatre heures de rattrapage, un essai par quart d'heure. Le
REM  poste allume a 08h20 ouvre donc a 08h30, et celui qui reste
REM  eteint jusqu'a midi n'ouvre rien du tout - a midi, personne
REM  n'a plus besoin qu'on lui ouvre son ecran du matin.
set "REPETITION=15"
set "DUREE=04:00"

if /i "%~1"=="/supprimer" goto supprimer

set "HEURE=%~1"
if not defined HEURE set "HEURE=08:00"

if not exist "%SCRIPT%" (
    echo.
    echo  [ERREUR] ouvrir-le-matin.bat est introuvable dans ce dossier.
    echo  Placez ce script a cote de lui.
    echo.
    pause
    exit /b 1
)

echo.
echo  ====================================================
echo    Ouverture automatique de l'utilitaire, chaque matin
echo  ====================================================
echo.

REM  L'heure est celle de CE poste : Windows ne connait pas
REM  "l'heure de Noumea", il ne connait que son propre fuseau.
REM  Un poste regle ailleurs partirait a cote sans que rien ne le
REM  signale - autant le voir maintenant, pas dans trois mois.
set "FUSEAU="
for /f "delims=" %%z in ('tzutil /g 2^>nul') do set "FUSEAU=%%z"
if not defined FUSEAU set "FUSEAU=inconnu"
echo  Fuseau horaire de ce poste : %FUSEAU%
echo  Il est actuellement        : %TIME:~0,5%
echo.
if /i "%FUSEAU%"=="Central Pacific Standard Time" goto fuseau_ok
echo  [ATTENTION] Ce poste n'est pas regle sur le fuseau de la
echo  Nouvelle-Caledonie, qui est "Central Pacific Standard Time"
echo  ^(UTC+11, Noumea^). La tache partira a %HEURE% de l'heure
echo  affichee ci-dessus, et non de l'heure de Noumea.
echo.
echo  Si l'heure affichee est la bonne, il n'y a rien a faire.
echo  Sinon, corrigez le fuseau dans les reglages de Windows
echo  ^(Heure et langue^), puis relancez ce script.
echo.
:fuseau_ok

echo  Creation de la tache "%TACHE%"
echo  Tous les jours a %HEURE%, heure de ce poste.
echo.

REM  Pas de /ru SYSTEM : la tache doit s'executer dans la session
REM  de la personne qui travaille, car c'est la que s'ouvrent le
REM  navigateur et la fenetre de l'application. Lancee par SYSTEM,
REM  elle ouvrirait tout dans une session invisible. C'est aussi ce
REM  qui evite d'avoir a lancer ce script en administrateur.
REM
REM  /ri et /du : le rattrapage. Une tache "tous les jours a 08:00"
REM  toute seule ne part JAMAIS sur un poste allume a 08h10 - et
REM  c'est le cas ordinaire d'une officine.
schtasks /create /tn "%TACHE%" /tr "\"%SCRIPT%\"" /sc daily /st %HEURE% /ri %REPETITION% /du %DUREE% /f
if errorlevel 1 (
    echo.
    echo  [ERREUR] La tache n'a pas pu etre creee.
    echo  Verifiez le format de l'heure : deux chiffres, deux points,
    echo  deux chiffres. Par exemple 08:00 ou 07:45.
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
echo  C'est fait. Chaque matin a %HEURE%, l'utilitaire s'ouvrira
echo  tout seul sur ce poste.
echo.
echo  A savoir :
echo    - il ne s'ouvre qu'UNE FOIS par jour, meme si vous fermez
echo      la fenetre : le matin suivant, il reviendra ;
echo    - poste allume en retard ? La tache repasse tous les
echo      %REPETITION% minutes pendant %DUREE%, puis renonce ;
echo    - la session Windows doit etre ouverte ^(ecran verrouille,
echo      c'est bien ; deconnecte, la tache ne partira pas^) ;
echo    - avec un serveur, l'ouverture attend que le serveur
echo      reponde : elle n'affichera pas de page d'erreur.
echo.
echo  A REFAIRE SUR CHAQUE POSTE : Windows ne connait que les
echo  taches de la machine ou on les cree.
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
echo  C'est fait. L'utilitaire ne s'ouvrira plus tout seul sur ce
echo  poste : passez par l'icone "Pharmacie" du Bureau.
echo.
pause
exit /b 0
