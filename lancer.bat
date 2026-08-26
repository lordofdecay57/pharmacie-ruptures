@echo off
REM Lancement en un double-clic (Windows).
REM Premiere fois : installe les dependances, puis ouvre l'app dans le navigateur.
REM  pushd, et NON "cd /d" : le dossier peut vivre sur un partage
REM  reseau. cmd REFUSE un chemin \\serveur\... comme repertoire
REM  courant : il se rabat sur C:\Windows sans rien demander, et
REM  tout ce qui suit cherche alors app.py dans C:\Windows.
REM  pushd, lui, monte un lecteur temporaire le temps du script.
pushd "%~dp0"
REM  Le script est forcement dans son propre dossier : s'il n'y est
REM  pas, c'est que pushd a echoue et qu'on est ailleurs.
if not exist "%~nx0" goto pas_de_dossier
REM --- Recherche de Python -------------------------------------
REM  "where python" ne suffit pas : Windows 10/11 pose un faux
REM  python.exe dans WindowsApps qui ouvre le Microsoft Store au
REM  lieu de demarrer Python. Il repond a "where", mais pas a
REM  "--version" : on teste donc ce qui compte vraiment.
REM  Repli sur le lanceur "py", installe meme quand la case
REM  "Add python.exe to PATH" a ete oubliee.
set "PY="
python --version >nul 2>nul
if not errorlevel 1 set "PY=python"
if not defined PY py -3 --version >nul 2>nul
if not defined PY if not errorlevel 1 set "PY=py -3"
if not defined PY goto pas_de_python
%PY% -m pip install -r requirements.txt --quiet

REM  Icone du Bureau : posee UNE SEULE FOIS, au tout premier lancement.
REM  /sipremier gere le temoin (une icone supprimee volontairement ne
REM  revient pas). Un echec n'empeche jamais l'application de demarrer.
call "%~dp0creer-raccourci.bat" /silencieux /sipremier

REM  Mise a jour automatique AVANT de lancer : c'est le seul moment ou
REM  remplacer des fichiers est sans danger, l'application n'est pas encore
REM  demarree. Le script ne fait rien s'il n'y a pas de nouvelle version,
REM  si le poste est hors ligne, ou si une instance tourne deja.
%PY% maj_auto.py --verbeux

REM  Code 10 : l'application repond deja. Tenter un second demarrage
REM  echouerait sur le port occupe et laisserait l'utilisateur devant une
REM  erreur, alors qu'il voulait simplement voir son ecran. On ouvre donc
REM  le navigateur sur l'instance en cours.
if errorlevel 10 (
    echo.
    echo  L'application est deja ouverte : affichage dans le navigateur.
    echo  Pour l'arreter, fermez sa fenetre noire.
    start "" http://localhost:8501
    exit /b 0
)

REM  Port fixe : si 8501 est deja occupe par une autre instance,
REM  Streamlit le DIT au lieu de basculer en silence sur 8502 -
REM  on regarderait sinon l'ancienne version sans le savoir.
REM  Dossier partage : ce poste annonce qu'il travaille sur ces
REM  fichiers, et le retire en partant. Sans cela, un poste qui
REM  demarre a 08h05 remplacerait le code sous la session du
REM  comptoir voisin, en pleine dispensation.
%PY% presence.py --entrer
%PY% -m streamlit run app.py --server.port 8501
REM  La place est rendue : la mise a jour de demain matin pourra
REM  se faire des que tout le monde aura ferme.
%PY% presence.py --sortir
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

:pas_de_dossier
echo.
echo  [ERREUR] Impossible de se placer dans le dossier de l'utilitaire.
echo.
echo      %~dp0
echo.
echo  Ce dossier est sur un partage reseau, et Windows n'a pas pu lui
echo  attribuer de lettre de lecteur temporaire.
echo.
echo  Deux solutions :
echo    - connectez le partage a une lettre de lecteur (clic droit sur
echo      le dossier reseau, puis "Connecter un lecteur reseau"), et
echo      relancez depuis cette lettre ;
echo    - ou copiez le dossier sur le disque de cet ordinateur.
echo.
if /i not "%~1"=="/silencieux" pause
exit /b 1
