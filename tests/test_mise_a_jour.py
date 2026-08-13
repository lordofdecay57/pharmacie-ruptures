# -*- coding: utf-8 -*-
"""Installer la nouvelle version depuis l'application, en un clic.

Rien n'est exécuté ici : le lanceur est injecté, et la suite tourne sous
Linux. Ce qui est vérifiable, et qui couvre les pannes réellement
redoutées : que ce soit le BON script (se tromper sur un serveur coupe
tous les comptoirs), qu'il parte DÉTACHÉ (le script commence par nous
tuer), et que rien n'explose jamais — un bouton d'aide qui fait tomber
l'application serait pire que pas de bouton du tout.
"""

import subprocess
from pathlib import Path

import pytest

import mise_a_jour


class _Lanceur:
    """Retient l'appel au lieu de démarrer quoi que ce soit."""

    def __init__(self, erreur=None):
        self.appels = []
        self.erreur = erreur

    def __call__(self, commande, **options):
        self.appels.append((commande, options))
        if self.erreur:
            raise self.erreur
        return object()


@pytest.fixture
def installation(tmp_path):
    """Un dossier d'application portant les deux scripts de mise à jour."""
    dossier = tmp_path / "pharmacie-ruptures"
    dossier.mkdir()
    for nom in (mise_a_jour.NOM_SCRIPT_POSTE, mise_a_jour.NOM_SCRIPT_SERVEUR):
        (dossier / nom).write_text("@echo off\n")
    return dossier


class TestSurWindows:
    def test_ailleurs_rien_n_est_propose(self):
        """Les scripts sont des « .bat » : sur Mac, mieux vaut ne rien
        proposer qu'un bouton qui échoue."""
        assert mise_a_jour.sur_windows("nt")
        assert not mise_a_jour.sur_windows("posix")


class TestChoixDuScript:
    def test_un_poste_isole_prend_son_script(self, installation):
        script = mise_a_jour.script_a_lancer(installation)
        assert script.name == mise_a_jour.NOM_SCRIPT_POSTE

    def test_un_serveur_prend_le_sien(self, installation):
        """`mettre-a-jour.bat` relance sans `--server.address` : l'employer
        sur un serveur le remettrait en marche avec les réglages d'un poste
        isolé, et couperait tous les comptoirs sans un mot."""
        script = mise_a_jour.script_a_lancer(installation, mode_serveur=True)
        assert script.name == mise_a_jour.NOM_SCRIPT_SERVEUR

    def test_un_script_absent_se_dit(self, tmp_path):
        """Les scripts de mise à jour ne sont jamais remplacés par une mise
        à jour : sur une installation ancienne, le script serveur peut ne
        jamais avoir été livré."""
        assert mise_a_jour.script_a_lancer(tmp_path) is None
        assert mise_a_jour.script_a_lancer(tmp_path, mode_serveur=True) is None


class TestLancement:
    def test_le_script_part_detache(self, installation):
        """Le script commence par arrêter le processus qui écoute sur 8501
        — c'est-à-dire nous. Un enfant ordinaire mourrait avec nous avant
        d'avoir rien copié."""
        lanceur = _Lanceur()
        succes, _ = mise_a_jour.lancer(installation, demarrer=lanceur)
        assert succes
        (commande, options), = lanceur.appels
        assert commande[0].endswith(mise_a_jour.NOM_SCRIPT_POSTE)
        assert options["cwd"] == str(installation)
        assert "creationflags" in options, (
            "sans détachement, la mise à jour meurt avec l'application")

    @pytest.mark.skipif(not hasattr(subprocess, "CREATE_NEW_CONSOLE"),
                        reason="drapeaux Windows absents")
    def test_nouvelle_console_et_nouveau_groupe(self, installation):
        """La console rend la mise à jour visible ; le groupe séparé évite
        qu'un Ctrl+C dans la fenêtre de l'application ne l'interrompe en
        pleine copie de fichiers."""
        lanceur = _Lanceur()
        mise_a_jour.lancer(installation, demarrer=lanceur)
        drapeaux = lanceur.appels[0][1]["creationflags"]
        assert drapeaux & subprocess.CREATE_NEW_CONSOLE
        assert drapeaux & subprocess.CREATE_NEW_PROCESS_GROUP

    def test_le_mode_serveur_lance_le_script_serveur(self, installation):
        lanceur = _Lanceur()
        mise_a_jour.lancer(installation, mode_serveur=True, demarrer=lanceur)
        assert lanceur.appels[0][0][0].endswith(
            mise_a_jour.NOM_SCRIPT_SERVEUR)

    def test_le_message_annonce_le_rechargement(self, installation):
        """Sans cet avertissement, la perte de connexion du navigateur passe
        pour une panne — et quelqu'un rappelle la pharmacie."""
        _, texte = mise_a_jour.lancer(installation, demarrer=_Lanceur())
        assert "recharger" in texte
        assert mise_a_jour.DELAI_RETOUR in texte

    def test_le_message_du_serveur_parle_du_serveur(self, installation):
        _, texte = mise_a_jour.lancer(installation, mode_serveur=True,
                                      demarrer=_Lanceur())
        assert "serveur" in texte.lower()


class TestRienNExplose:
    def test_script_manquant_rend_un_message_francais(self, tmp_path):
        succes, texte = mise_a_jour.lancer(tmp_path, demarrer=_Lanceur())
        assert not succes
        assert mise_a_jour.NOM_SCRIPT_POSTE in texte
        assert "à la main" in texte

    def test_un_lancement_refuse_ne_leve_pas(self, installation):
        """Poste d'officine interdisant l'exécution des scripts, droits
        insuffisants : l'application doit rester debout et le dire."""
        lanceur = _Lanceur(erreur=OSError("acces refuse"))
        succes, texte = mise_a_jour.lancer(installation, demarrer=lanceur)
        assert not succes
        assert "à la main" in texte
        assert mise_a_jour.NOM_SCRIPT_POSTE in texte


class TestCablageDansLApplication:
    """Le module le mieux écrit ne sert à rien s'il n'est jamais appelé."""

    def _source(self) -> str:
        return (Path(__file__).resolve().parent.parent
                / "app.py").read_text(encoding="utf-8")

    def test_la_proposition_est_affichee(self):
        source = self._source()
        assert "import mise_a_jour" in source
        assert "def _proposer_mise_a_jour()" in source
        assert "\n_proposer_mise_a_jour()\n" in source, (
            "la fonction doit être APPELÉE, pas seulement définie")

    def test_le_mode_serveur_se_lit_sur_le_drapeau_de_demarrage(self):
        """``--server.address 0.0.0.0`` est passé par ``lancer-serveur.bat``
        et par lui seul. Un fichier témoin survivrait à un changement de
        mode ; ``server.headless`` est aussi passé par la suite de tests
        navigateur, qui se prendrait alors pour un serveur."""
        source = self._source()
        assert 'st.get_option("server.address")' in source
        assert 'st.get_option("server.headless")' not in source

    def test_le_meme_interrupteur_que_le_bandeau(self):
        """Qui coupe la vérification de version ne doit pas se voir proposer
        d'installer quand même : une seule source de vérité."""
        source = self._source()
        panneau = source.split("def _proposer_mise_a_jour()", 1)[1]
        panneau = panneau.split("\ndef ", 1)[0]
        assert 'st.session_state.get("verifier_version", True)' in panneau
        assert "_version_publiee_cache()" in panneau, (
            "le bouton doit lire la MÊME version publiée que le bandeau")

    def test_le_bandeau_renvoie_vers_le_bouton(self):
        """Nommer un « .bat » n'aide personne : Windows en masque
        l'extension, et depuis un poste sans installation locale ce fichier
        n'existe même pas."""
        source = self._source()
        bandeau = source.split('class="maj"', 1)[1].split("\n\n", 1)[0]
        assert "barre latérale" in bandeau
        assert ".bat" not in bandeau
