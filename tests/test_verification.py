# -*- coding: utf-8 -*-
"""« Désolé, impossible d'accéder à cette page. »

Message d'Edge, reçu en photo depuis l'officine. Il ne dit ni que
l'application n'était pas démarrée, ni comment la démarrer — il dit
seulement que `localhost` a refusé une connexion, ce qui ne veut rien
dire pour quelqu'un qui voulait ouvrir son inventaire.

`verifier-installation.bat` répond à cette question, et aux six autres
qui ont coûté une matinée chacune dans cette installation : Python
est-il là ? les compléments ? l'application tourne-t-elle ? quelle
version ? quel montage ? qui d'autre travaille sur le dossier ? les
données sont-elles bien présentes ?

Sa règle est absolue et c'est ce qui le rend utilisable sans crainte :
**il regarde, il ne touche à rien.** Un outil de diagnostic qui répare
tout seul est un outil qu'on n'ose plus lancer quand ça va mal.

Personne ne l'exécute ici : c'est cmd qui l'interprète, sur un Windows
qu'on n'a pas.
"""

from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
SCRIPT = RACINE / "verifier-installation.bat"


def _texte() -> str:
    return SCRIPT.read_text(encoding="ascii")


def _instructions() -> list:
    """Les lignes que cmd exécute : sans les REM ni le vide."""
    return [ligne for ligne in _texte().splitlines()
            if ligne.strip() and not ligne.strip().upper().startswith("REM")]


class TestPresent:
    def test_le_script_existe(self):
        assert SCRIPT.is_file()

    def test_sans_accent(self):
        """cmd lit ce fichier dans une page de codes qui n'est pas celle de
        l'éditeur : un « é » y devient un caractère illisible, au milieu
        d'un message qu'on lit justement quand rien ne marche."""
        try:
            _texte()
        except UnicodeDecodeError as erreur:
            pytest.fail(f"caractère non ASCII en {erreur.start}")

    def test_il_fonctionne_depuis_un_partage_reseau(self):
        """Le dossier vit sur `\\\\srv-lafoa\\…`. Tout doit passer par
        `%~dp0` : cmd refuse un chemin UNC comme répertoire courant."""
        fautives = [l for l in _instructions()
                    if l.strip().lower().startswith(("cd ", "cd/"))]
        assert not fautives, fautives


class TestIlNeToucheARien:
    """La règle qui le rend lançable sans réfléchir.

    On le double-clique quand ça va déjà mal. S'il pouvait modifier
    quoi que ce soit, il faudrait se demander avant de le lancer si
    c'est prudent — et on ne le lancerait pas.
    """

    #: Tout ce qui écrit, déplace ou supprime.
    DANGEREUX = ("robocopy", "del ", "erase ", "rmdir", "rd ", "move ",
                 "copy ", "xcopy", "mkdir", "md ", "ren ", "schtasks",
                 "taskkill", "stop-process", "pip install")

    def test_aucune_commande_ne_modifie_le_poste(self):
        fautives = [l for l in _instructions()
                    if any(m in l.strip().lower() for m in self.DANGEREUX)]
        assert not fautives, fautives

    def test_il_n_ecrit_dans_aucun_fichier(self):
        """Aucune redirection vers un fichier.

        Seules deux destinations sont permises : `nul`, qui jette, et
        `&1`, qui replie la sortie d'erreur sur la sortie normale. Toute
        autre cible serait un fichier — donc une modification.
        """
        for ligne in _instructions():
            nu = ligne.replace("^", "")
            for morceau in nu.split(">")[1:]:
                reste = morceau.lstrip(">").strip()
                cible = reste.split()[0] if reste else ""
                assert cible.lower().startswith(("nul", "&1")), (
                    f"écriture vers {cible!r} : {ligne}")

    def test_il_ne_demarre_pas_l_application(self):
        """Il DIT de lancer `lancer.bat`, il ne le fait pas : le démarrage
        est une décision, pas un effet de bord d'un diagnostic."""
        fautives = [l for l in _instructions()
                    if l.strip().lower().startswith("start ")]
        assert not fautives, fautives
        assert "lancer.bat" in _texte(), "il doit au moins dire quoi faire"


class TestCeQuIlControle:
    def test_le_programme_est_bien_la(self):
        assert 'if not exist "%~dp0app.py"' in _texte()

    def test_python_est_reellement_demarre(self):
        """`where python` trouve le raccourci vers le Microsoft Store et
        déclare Python présent sans qu'aucun Python ne démarre."""
        texte = _texte()
        assert "python --version >nul 2>nul" in texte
        assert "py -3 --version >nul 2>nul" in texte, "repli sur « py »"
        assert "where python" not in "\n".join(_instructions())

    def test_les_complements_python(self):
        assert '-c "import streamlit, pandas"' in _texte()

    def test_l_application_repond_ou_non(self):
        """LA question derrière « localhost a refusé de se connecter »."""
        assert "connect_ex(('127.0.0.1',8501))" in _texte()

    def test_le_controle_du_port_ne_lit_pas_netstat(self):
        """Les états de netstat changent de nom d'un Windows à l'autre.
        Tenter la connexion pose la question comme le navigateur la pose."""
        assert "netstat" not in "\n".join(_instructions())

    def test_la_version_installee(self):
        assert 'findstr /b "VERSION_APP"' in _texte()

    def test_le_montage_est_reconnu(self):
        """`adresse-serveur.txt` dit à lui seul si l'application tourne
        ailleurs ou sur ce poste."""
        assert "adresse-serveur.txt" in _texte()

    def test_qui_travaille_sur_le_dossier(self):
        assert "presence.py" in _texte()
        assert "--lister" in _texte()

    def test_les_donnees_de_la_pharmacie(self):
        texte = _texte()
        for fichier in ("stock_ferme.csv", "stock_ferme_produits.csv",
                        "commandes_speciales.csv", "historique_commandes.csv",
                        "config.yaml"):
            assert fichier in texte, fichier

    def test_les_donnees_sont_datees(self):
        """« Il est là » ne suffit pas : un fichier figé depuis trois
        semaines se remarque à sa date, pas à son existence."""
        assert "%%~tf" in _texte()


class TestCeQuIlDit:
    def test_il_traduit_le_message_du_navigateur(self):
        """C'est tout l'objet du script : faire le pont entre ce qu'Edge
        affiche et ce qu'il faut faire."""
        texte = _texte()
        assert "localhost a refuse de se connecter" in texte
        message = texte[texte.index(":application_arretee"):][:800]
        assert "lancer.bat" in message
        assert "fenetre noire" in message

    def test_python_absent_dit_quoi_telecharger(self):
        texte = _texte()
        message = texte[texte.index(":sans_python"):][:700]
        assert "-amd64.exe" in message
        assert "Add python.exe to PATH" in message

    def test_le_verdict_final_est_explicite(self):
        texte = _texte()
        assert "Tout est en place" in texte
        assert "Au moins un point a corriger" in texte

    @pytest.mark.parametrize("etiquette", [":fichier", ":fin"])
    def test_on_ne_tombe_pas_dans_les_sous_programmes(self, etiquette):
        """`:fichier` est appelé, pas parcouru : y tomber réafficherait une
        ligne de données au milieu du verdict."""
        lignes = _texte().splitlines()
        indice = lignes.index(etiquette)
        avant = [l.strip() for l in lignes[:indice] if l.strip()
                 and not l.strip().upper().startswith("REM")][-1]
        assert avant.startswith(("exit /b", "goto ")), (
            f"on tombe dans {etiquette} après « {avant} »")

    def test_chaque_saut_a_son_etiquette(self):
        """Un `goto` vers une étiquette absente fait sortir cmd du script
        en silence, au milieu du bilan."""
        texte = _texte()
        etiquettes = {l[1:].strip() for l in texte.splitlines()
                      if l.startswith(":")}
        for ligne in _instructions():
            nu = ligne.strip()
            if " goto " in f" {nu} ":
                cible = nu.split("goto ", 1)[1].split()[0].lstrip(":")
                assert cible in etiquettes, f"goto {cible} — {ligne}"
