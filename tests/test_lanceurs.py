# -*- coding: utf-8 -*-
"""« Python n'est pas retrouvé après installation » — le blocage n°1.

Signalé sur le serveur de la pharmacie, après une installation qui s'était
pourtant bien déroulée. Trois causes, toutes invisibles depuis la fenêtre
noire qui se contentait d'annoncer « Python n'est pas installé » :

1. **Le faux `python.exe` de Windows.** Windows 10/11 pose un raccourci
   dans `WindowsApps` dont le seul rôle est d'ouvrir le Microsoft Store.
   Il répond à `where python` — donc l'ancien test passait — mais ne
   démarre aucun Python.
2. **La case « Add python.exe to PATH » oubliée.** C'est l'oubli le plus
   courant de l'installeur. Python est bel et bien là, mais `python` ne
   répond pas. Le lanceur `py`, lui, est installé dans tous les cas.
3. **Une fenêtre déjà ouverte.** Elle garde le PATH d'avant
   l'installation : même une installation parfaite semble n'avoir rien
   changé.

Personne n'exécute ces scripts ici — c'est cmd qui les interprète, sur un
Windows qu'on n'a pas. Ce qui se vérifie, et qui suffit : que la détection
teste ce qui compte, qu'elle ait un repli, et que le message d'échec dise
quoi faire.
"""

from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent

#: Tous les scripts qui ont besoin de Python pour faire leur travail.
#: Les tenir dans une seule liste : un nouveau lanceur qui oublierait la
#: détection ramènerait exactement le blocage que ce fichier traite.
LANCEURS = ["lancer.bat", "lancer-serveur.bat", "mettre-a-jour.bat",
            "mettre-a-jour-serveur.bat", "maj-auto-activer.bat"]

#: La sonde : elle DÉMARRE Python au lieu de chercher son nom.
SONDE = "python --version >nul 2>nul"
#: Le repli, quand la case « Add python.exe to PATH » a été oubliée.
REPLI = "py -3 --version >nul 2>nul"


def _texte(nom: str) -> str:
    return (RACINE / nom).read_text(encoding="ascii")


def _lignes(nom: str) -> list:
    return _texte(nom).splitlines()


def _instructions(nom: str) -> list:
    """Les lignes que cmd exécute vraiment : sans les REM ni le vide.

    Les commentaires expliquent justement pourquoi `where` ne suffit
    pas — les inclure ferait échouer le test sur sa propre explication.
    """
    return [ligne for ligne in _lignes(nom)
            if ligne.strip() and not ligne.strip().upper().startswith("REM")]


@pytest.mark.parametrize("nom", LANCEURS)
class TestDetection:
    def test_sans_accent(self, nom):
        """cmd lit ces fichiers dans une page de codes qui n'est pas celle
        de l'éditeur : un « é » y devient un caractère illisible, au milieu
        d'un message qu'on lit justement quand rien ne marche."""
        try:
            _texte(nom)
        except UnicodeDecodeError as erreur:
            pytest.fail(f"{nom} : caractère non ASCII en {erreur.start}")

    def test_python_est_reellement_demarre_pas_seulement_cherche(self, nom):
        """`where python` trouve le raccourci vers le Microsoft Store et
        déclare Python présent. Le script partait alors confiant, et
        échouait trois lignes plus loin sur un message incompréhensible."""
        assert SONDE in _texte(nom), f"{nom} : Python n'est jamais démarré"
        cherche = [ligne for ligne in _instructions(nom)
                   if "where python" in ligne]
        assert not cherche, (
            f"{nom} : « where » ne distingue pas le vrai Python du "
            f"raccourci vers le Microsoft Store — {cherche}")

    def test_le_lanceur_py_sert_de_repli(self, nom):
        """Sans la case « Add python.exe to PATH », `python` ne répond pas
        alors que Python est installé. `py` est posé dans tous les cas :
        c'est la différence entre « ça ne marche pas » et « ça marche »."""
        assert REPLI in _texte(nom), f"{nom} : aucun repli sur « py »"

    def test_aucun_appel_ne_court_circuite_la_detection(self, nom):
        """Trouver le bon Python et en appeler un autre trois lignes plus
        bas ne servirait à rien. Toutes les invocations passent par la
        variable, la sonde exceptée."""
        fautifs = [ligne for ligne in _lignes(nom)
                   if ligne.lstrip().startswith(("python ", "pythonw ",
                                                 "py ", "pyw "))
                   and ligne.strip() not in (SONDE, REPLI)]
        assert not fautifs, f"{nom} : {fautifs}"

    def test_l_echec_a_sa_sortie_et_elle_est_atteignable(self, nom):
        texte = _texte(nom)
        assert "goto pas_de_python" in texte, f"{nom} : échec sans issue"
        assert "\n:pas_de_python\n" in texte, f"{nom} : étiquette absente"

    def test_on_ne_tombe_pas_dans_le_message_d_erreur(self, nom):
        """L'étiquette est en fin de fichier : sans un `exit` ou un `goto`
        juste avant, cmd y entre à la suite d'un lancement RÉUSSI et
        annonce « Python est introuvable » à quelqu'un dont l'application
        vient de s'ouvrir."""
        lignes = _lignes(nom)
        indice = lignes.index(":pas_de_python")
        avant = [l.strip() for l in lignes[:indice] if l.strip()][-1]
        assert avant.startswith(("exit /b", "goto ")), (
            f"{nom} : on tombe dans :pas_de_python après « {avant} »")


@pytest.mark.parametrize("nom", LANCEURS)
class TestMessageDEchec:
    """Le message est lu par quelqu'un de bloqué devant une fenêtre noire.

    Il doit contenir les trois gestes qui débloquent, pas seulement le
    constat — l'ancien se contentait de « Python n'est pas installé »,
    ce que l'utilisateur savait déjà faux : il venait de l'installer.
    """

    def _message(self, nom: str) -> str:
        texte = _texte(nom)
        return texte[texte.index(":pas_de_python"):]

    def test_il_donne_l_adresse_de_telechargement(self, nom):
        assert "python.org/downloads/windows" in self._message(nom)

    def test_il_previent_du_piege_du_msix(self, nom):
        """Le fichier `.msix` téléchargé sur le serveur ne s'ouvrait pas :
        Windows Server n'a pas « App Installer », et proposait le
        Bloc-notes. C'est exactement là que la pharmacie s'est arrêtée."""
        message = self._message(nom)
        assert ".msix" in message
        assert "-amd64.exe" in message

    def test_il_rappelle_la_case_du_path(self, nom):
        assert "Add python.exe to PATH" in self._message(nom)

    def test_il_dit_de_refermer_la_fenetre(self, nom):
        """Une fenêtre ouverte avant l'installation garde l'ancien PATH.
        Sans cette phrase, on réinstalle Python trois fois de suite en
        constatant que « ça ne change rien »."""
        message = self._message(nom).lower()
        assert "fermez" in message


class TestModeSilencieux:
    """La mise à jour de nuit ne doit jamais attendre une touche.

    `mettre-a-jour-serveur.bat` est lancé par une tâche planifiée sur un
    serveur où personne n'est assis. Un `pause` sur le chemin d'échec y
    laisserait le script suspendu jusqu'au matin.
    """

    def test_l_echec_python_passe_par_la_sortie_commune(self):
        texte = _texte("mettre-a-jour-serveur.bat")
        bloc = texte[texte.index(":pas_de_python"):texte.index("\n:echec")]
        assert "pause" not in bloc, (
            "le chemin d'échec de la nuit ne doit attendre aucune touche")
        assert bloc.rstrip().endswith("goto echec")

    def test_l_echec_est_consigne_dans_le_journal(self):
        """`:dire` écrit à l'écran ET dans maj_auto.log. Un échec de nuit
        qui ne laisse aucune trace ne se diagnostique pas le lendemain."""
        texte = _texte("mettre-a-jour-serveur.bat")
        bloc = texte[texte.index(":pas_de_python"):texte.index("\n:echec")]
        assert "call :dire" in bloc

    def test_aucun_message_ne_se_transforme_en_redirection(self):
        """`:dire` affiche `%~1`, ce qui RETIRE les guillemets : un message
        contenant `<`, `>`, `|` ou `&` partirait dans un fichier au lieu de
        s'afficher."""
        texte = _texte("mettre-a-jour-serveur.bat")
        bloc = texte[texte.index(":pas_de_python"):texte.index("\n:echec")]
        for numero, ligne in enumerate(bloc.splitlines(), 1):
            if not ligne.strip().lower().startswith("call :dire"):
                continue
            message = ligne.split('"', 1)[-1].rsplit('"', 1)[0]
            interdits = [c for c in "<>|&" if c in message]
            assert not interdits, f"ligne {numero} : {interdits} — {ligne}"


class TestTacheDeFond:
    """La mise à jour au démarrage n'ouvre aucune fenêtre noire."""

    def test_la_tache_reste_sans_fenetre(self):
        """`pythonw` (ou `pyw`) et non `python` : la tâche se déclenche à
        l'ouverture de session, une fenêtre noire surgissant sur le bureau
        passerait pour un virus."""
        texte = _texte("maj-auto-activer.bat")
        assert 'set "PYW=pythonw"' in texte
        assert 'set "PYW=pyw -3"' in texte
        assert '/TR "%PYW% ' in texte

    def test_la_sonde_reste_la_version_console(self):
        """`pythonw` rend la main aussitôt, sans attendre : cmd n'obtient
        aucun code de sortie exploitable. On teste donc `python` / `py`,
        dont cmd attend vraiment la fin, et on en déduit l'autre."""
        texte = _texte("maj-auto-activer.bat")
        assert "pythonw --version" not in texte
        assert SONDE in texte
