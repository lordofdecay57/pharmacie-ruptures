# -*- coding: utf-8 -*-
"""Tests de la pose de l'icône du Bureau depuis l'application.

Le vrai raccourci Windows (.lnk) ne peut pas être fabriqué ici : il faut
PowerShell et le composant WScript.Shell. Ce qui EST vérifiable, et qui
couvre les pannes réellement rencontrées, c'est le reste : où l'on cherche
le Bureau, ce qui se passe quand PowerShell manque, et le fait que rien
n'explose jamais — un bouton d'aide qui fait tomber l'application serait
pire que pas de bouton du tout.
"""

from pathlib import Path

import pytest

import raccourci


@pytest.fixture
def installation(tmp_path):
    """Un dossier d'application crédible : lanceur + icône."""
    dossier = tmp_path / "pharmacie-ruptures"
    dossier.mkdir()
    (dossier / raccourci.NOM_LANCEUR).write_text("@echo off\n")
    (dossier / raccourci.NOM_ICONE).write_bytes(b"\x00\x00\x01\x00")
    return dossier


@pytest.fixture
def poste(tmp_path):
    """Un profil utilisateur avec un Bureau."""
    accueil = tmp_path / "utilisateur"
    (accueil / "Desktop").mkdir(parents=True)
    return accueil


class TestSurWindows:
    def test_ailleurs_rien_n_est_propose(self):
        """L'application tourne aussi sur Mac : mieux vaut ne rien proposer
        qu'un bouton qui échoue."""
        assert raccourci.sur_windows("nt") is True
        assert raccourci.sur_windows("posix") is False


class TestOuChercherLeBureau:
    def test_onedrive_passe_avant_le_chemin_en_dur(self, tmp_path):
        """Sur les postes d'entreprise, le Bureau est souvent redirigé vers
        OneDrive : le chemin en dur pointe alors sur un dossier vide que
        personne ne regarde jamais."""
        pistes = raccourci.dossiers_bureau(
            accueil=tmp_path / "u",
            environnement={"OneDrive": str(tmp_path / "od")})
        assert pistes[0] == tmp_path / "od" / "Desktop"
        assert tmp_path / "u" / "Desktop" in pistes

    def test_pas_de_doublon(self, tmp_path):
        """Deux variables d'environnement pointent parfois sur le même
        dossier : la même piste essayée deux fois n'apporte rien."""
        pistes = raccourci.dossiers_bureau(
            accueil=tmp_path,
            environnement={"OneDrive": str(tmp_path / "od"),
                           "OneDriveCommercial": str(tmp_path / "od")})
        assert len(pistes) == len(set(str(p) for p in pistes))

    def test_on_retient_le_dossier_qui_existe(self, tmp_path):
        vrai = tmp_path / "od" / "Desktop"
        vrai.mkdir(parents=True)
        trouve = raccourci.bureau(
            accueil=tmp_path / "u",
            environnement={"OneDrive": str(tmp_path / "od")})
        assert trouve == vrai

    def test_aucun_bureau_ne_leve_pas(self, tmp_path):
        assert raccourci.bureau(accueil=tmp_path / "vide",
                                environnement={}) is None


class TestRaccourciExistant:
    def test_detecte_le_lnk(self, poste):
        (poste / "Desktop" / raccourci.NOM_RACCOURCI).write_bytes(b"x")
        assert raccourci.raccourci_existant(poste, {}) is not None

    def test_detecte_le_repli_url(self, poste):
        """Le repli compte comme une icône : c'est bien elle qui est sur le
        Bureau, la reproposer serait absurde."""
        (poste / "Desktop" / raccourci.NOM_REPLI).write_text("x")
        assert raccourci.raccourci_existant(poste, {}) is not None

    def test_absent(self, poste):
        assert raccourci.raccourci_existant(poste, {}) is None


class TestCommandePowerShell:
    def test_les_chemins_passent_par_l_environnement(self, installation,
                                                     tmp_path):
        """Un dossier contenant une apostrophe ou un accent casse le
        meilleur des échappements en ligne de commande."""
        lien = tmp_path / "Desktop" / raccourci.NOM_RACCOURCI
        commande = raccourci.commande_powershell(installation, lien)
        assert commande[0] == "powershell"
        ligne = commande[-1]
        assert str(installation) not in ligne
        assert "$env:PHARMA_CIBLE" in ligne and "$env:PHARMA_LIEN" in ligne

        variables = raccourci.environnement_powershell(installation, lien, {})
        assert variables["PHARMA_CIBLE"] == str(installation /
                                                raccourci.NOM_LANCEUR)
        assert variables["PHARMA_ICONE"] == str(installation /
                                                raccourci.NOM_ICONE)
        assert variables["PHARMA_LIEN"] == str(lien)

    def test_l_icone_absente_n_empeche_pas_le_raccourci(self, installation,
                                                       tmp_path):
        """Mieux vaut un raccourci sans icône qu'aucun raccourci."""
        ligne = raccourci.commande_powershell(
            installation, tmp_path / raccourci.NOM_RACCOURCI)[-1]
        assert "Test-Path $env:PHARMA_ICONE" in ligne


class TestContenuUrl:
    def test_barres_obliques(self, installation):
        """``file:///`` veut des barres obliques : un chemin Windows
        recopié tel quel donne un lien mort."""
        contenu = raccourci.contenu_url(Path(r"C:\Program Files\pharmacie"))
        assert "URL=file:///C:/Program Files/pharmacie/lancer.bat" in contenu
        assert "\\" in contenu.split("IconFile=")[1]   # l'icône reste native

    def test_sections_attendues(self, installation):
        contenu = raccourci.contenu_url(installation)
        assert contenu.startswith("[InternetShortcut]")
        assert "IconIndex=0" in contenu


class TestCreer:
    def _powershell_qui_fabrique(self, lien: Path):
        def executer(commande, env=None, **kwargs):
            Path(env["PHARMA_LIEN"]).write_bytes(b"faux-lnk")
            return None
        return executer

    def test_cas_nominal(self, installation, poste):
        lien = poste / "Desktop" / raccourci.NOM_RACCOURCI
        succes, message = raccourci.creer(
            installation, accueil=poste, environnement={},
            executer=self._powershell_qui_fabrique(lien))
        assert succes is True
        assert lien.is_file()
        assert "Bureau" in message

    def test_repli_quand_powershell_manque(self, installation, poste):
        """Certains postes d'officine interdisent PowerShell par stratégie
        de groupe : l'icône doit tout de même apparaître."""
        def absent(*a, **k):
            raise FileNotFoundError("powershell")

        succes, message = raccourci.creer(
            installation, accueil=poste, environnement={}, executer=absent)
        assert succes is True
        replacement = poste / "Desktop" / raccourci.NOM_REPLI
        assert replacement.is_file()
        assert "[InternetShortcut]" in replacement.read_text(encoding="utf-8")

    def test_powershell_qui_echoue_sans_lever(self, installation, poste):
        """Un PowerShell qui rend la main sans rien créer (stratégie
        d'exécution refusée) doit basculer sur le repli, pas se croire
        réussi."""
        succes, _ = raccourci.creer(installation, accueil=poste,
                                    environnement={},
                                    executer=lambda *a, **k: None)
        assert succes is True
        assert (poste / "Desktop" / raccourci.NOM_REPLI).is_file()

    def test_sans_lanceur_on_le_dit(self, tmp_path, poste):
        """Une icône qui n'aurait rien à ouvrir n'est pas une icône."""
        vide = tmp_path / "vide"
        vide.mkdir()
        succes, message = raccourci.creer(vide, accueil=poste,
                                          environnement={})
        assert succes is False
        assert raccourci.NOM_LANCEUR in message

    def test_sans_bureau_on_explique_la_manoeuvre_a_la_main(self, installation,
                                                            tmp_path):
        succes, message = raccourci.creer(installation,
                                          accueil=tmp_path / "nulle-part",
                                          environnement={})
        assert succes is False
        assert "Envoyer vers" in message

    def test_bureau_en_lecture_seule_ne_leve_pas(self, installation, poste,
                                                 monkeypatch):
        """Le poste peut être verrouillé : le bouton doit rendre un message,
        jamais faire tomber l'application."""
        def refuse(*a, **k):
            raise OSError("accès refusé")

        monkeypatch.setattr(Path, "write_text", refuse)
        succes, message = raccourci.creer(installation, accueil=poste,
                                          environnement={},
                                          executer=lambda *a, **k: None)
        assert succes is False
        assert "Envoyer vers" in message


class TestIsolation:
    def test_aucune_dependance_lourde(self):
        """Ce module doit rester utilisable partout : ni Streamlit, ni
        pandas, ni aucun module du projet."""
        source = (Path(raccourci.__file__)).read_text(encoding="utf-8")
        for interdit in ("import streamlit", "import pandas",
                         "import stock_ferme", "import commun"):
            assert interdit not in source
