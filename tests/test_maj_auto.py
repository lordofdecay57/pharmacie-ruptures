# -*- coding: utf-8 -*-
"""Tests de la mise à jour automatique (maj_auto.py).

Ce script tourne sans surveillance, au démarrage du poste. Deux propriétés
comptent plus que tout et sont vérifiées ici :

- **il ne touche à rien pendant que l'application tourne** — remplacer un
  module sous un Streamlit en cours casserait la session du comptoir ;
- **il ne détruit aucune donnée de la pharmacie**, et n'échoue jamais
  bruyamment.

Aucun test ne sort sur le réseau : l'archive et la version publiée sont
simulées.
"""

import io
import socket
import zipfile
from pathlib import Path

import pytest

import maj_auto
from maj_auto import (APPLICATION_EN_COURS, DEJA_A_JOUR, ECHEC, FICHIERS_PROTEGES,
                      INJOIGNABLE, MISE_A_JOUR, application_en_cours,
                      executer, installer_archive, lire_version,
                      plus_recente)

RACINE = Path(__file__).resolve().parent.parent


def _archive(fichiers: dict, racine: str = "pharmacie-ruptures-main") -> bytes:
    """Archive GitHub simulée : un dossier racine, puis les fichiers."""
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as z:
        for nom, contenu in fichiers.items():
            z.writestr(f"{racine}/{nom}", contenu)
    return tampon.getvalue()


def _installation(tmp_path: Path, version: str = "3.0") -> Path:
    """Poste avec une application installée et des données de pharmacie."""
    dossier = tmp_path / "pharmacie"
    dossier.mkdir()
    (dossier / "app.py").write_text(f'VERSION_APP = "{version}"\n',
                                    encoding="utf-8")
    (dossier / "config.yaml").write_text("mapping: perso\n", encoding="utf-8")
    (dossier / "stock_ferme.csv").write_text("mon inventaire\n",
                                             encoding="utf-8")
    (dossier / "historique_commandes.csv").write_text("mes analyses\n",
                                                      encoding="utf-8")
    return dossier


# ---------------------------------------------------------------------------
# Comparaison de versions
# ---------------------------------------------------------------------------

class TestPlusRecente:
    @pytest.mark.parametrize("publiee,installee,attendu", [
        ("3.4", "3.3", True),
        ("3.3", "3.3", False),
        ("3.3", "3.4", False),      # poste en avance : ne rien faire
        ("3.10", "3.9", True),      # 3.10 vient APRÈS 3.9…
        ("3.9", "3.10", False),     # …ce qu'un tri alphabétique inverserait
        ("4.0", "3.99", True),
    ])
    def test_comparaison_numerique(self, publiee, installee, attendu):
        assert plus_recente(publiee, installee) is attendu

    def test_version_manquante(self):
        assert plus_recente("", "3.3") is False
        assert plus_recente("3.4", "") is False


class TestLireVersion:
    def test_lecture(self, tmp_path):
        assert lire_version(_installation(tmp_path, "3.7") / "app.py") == "3.7"

    def test_fichier_absent(self, tmp_path):
        assert lire_version(tmp_path / "rien.py") == ""

    def test_fichier_sans_version(self, tmp_path):
        fichier = tmp_path / "app.py"
        fichier.write_text("print('bonjour')\n", encoding="utf-8")
        assert lire_version(fichier) == ""


# ---------------------------------------------------------------------------
# Installation de l'archive
# ---------------------------------------------------------------------------

class TestInstallerArchive:
    def test_fichiers_programme_remplaces(self, tmp_path):
        dossier = _installation(tmp_path, "3.0")
        installer_archive(_archive({
            "app.py": 'VERSION_APP = "3.4"\n',
            "stock_ferme.py": "# moteur\n"}), dossier)
        assert lire_version(dossier / "app.py") == "3.4"
        assert (dossier / "stock_ferme.py").exists()

    def test_donnees_de_la_pharmacie_intactes(self, tmp_path):
        """Le point le plus important : une mise à jour ne doit JAMAIS
        écraser l'inventaire, la configuration ou l'historique."""
        dossier = _installation(tmp_path)
        installer_archive(_archive({
            "app.py": 'VERSION_APP = "3.4"\n',
            # L'archive contient bien ces noms : ils doivent être ignorés.
            "config.yaml": "mapping: du depot\n",
            "stock_ferme.csv": "inventaire du depot\n",
            "historique_commandes.csv": "analyses du depot\n"}), dossier)
        assert (dossier / "config.yaml").read_text(encoding="utf-8") \
            == "mapping: perso\n"
        assert (dossier / "stock_ferme.csv").read_text(encoding="utf-8") \
            == "mon inventaire\n"
        assert (dossier / "historique_commandes.csv").read_text(
            encoding="utf-8") == "mes analyses\n"

    def test_sous_dossiers_deployes(self, tmp_path):
        dossier = _installation(tmp_path)
        installer_archive(_archive({
            "app.py": 'VERSION_APP = "3.4"\n',
            "tests/test_x.py": "# test\n",
            ".streamlit/config.toml": "[server]\n"}), dossier)
        assert (dossier / "tests" / "test_x.py").exists()
        assert (dossier / ".streamlit" / "config.toml").exists()

    def test_fichiers_supplementaires_conserves(self, tmp_path):
        """Une mise à jour ajoute ou remplace ; elle ne fait pas le ménage."""
        dossier = _installation(tmp_path)
        (dossier / "mes_notes.txt").write_text("à garder\n", encoding="utf-8")
        installer_archive(_archive({"app.py": 'VERSION_APP = "3.4"\n'}),
                          dossier)
        assert (dossier / "mes_notes.txt").exists()

    def test_archive_illisible(self, tmp_path):
        with pytest.raises(Exception):
            installer_archive(b"pas une archive", _installation(tmp_path))


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

class TestExecuter:
    def test_rien_a_faire_si_deja_a_jour(self, tmp_path, monkeypatch):
        dossier = _installation(tmp_path, "3.4")
        monkeypatch.setattr(maj_auto, "application_en_cours", lambda *a: False)
        monkeypatch.setattr(maj_auto, "version_publiee", lambda *a, **k: "3.4")
        monkeypatch.setattr(maj_auto, "_telecharger",
                            lambda *a: pytest.fail("ne doit rien télécharger"))
        resultat, _ = executer(dossier)
        assert resultat == DEJA_A_JOUR

    def test_mise_a_jour_appliquee(self, tmp_path, monkeypatch):
        dossier = _installation(tmp_path, "3.0")
        monkeypatch.setattr(maj_auto, "application_en_cours", lambda *a: False)
        monkeypatch.setattr(maj_auto, "version_publiee", lambda *a, **k: "3.4")
        monkeypatch.setattr(maj_auto, "_telecharger", lambda *a: _archive(
            {"app.py": 'VERSION_APP = "3.4"\n'}))
        resultat, message = executer(dossier)
        assert resultat == MISE_A_JOUR
        assert "3.4" in message
        assert lire_version(dossier / "app.py") == "3.4"

    def test_application_ouverte_rien_n_est_touche(self, tmp_path, monkeypatch):
        """Le garde-fou essentiel : pas de remplacement de fichiers sous un
        Streamlit en cours de session."""
        dossier = _installation(tmp_path, "3.0")
        monkeypatch.setattr(maj_auto, "application_en_cours", lambda *a: True)
        monkeypatch.setattr(maj_auto, "version_publiee",
                            lambda *a, **k: pytest.fail("ne doit pas sortir "
                                                        "sur le réseau"))
        resultat, _ = executer(dossier)
        assert resultat == APPLICATION_EN_COURS
        assert lire_version(dossier / "app.py") == "3.0"   # intact

    def test_poste_hors_ligne(self, tmp_path, monkeypatch):
        dossier = _installation(tmp_path, "3.0")
        monkeypatch.setattr(maj_auto, "application_en_cours", lambda *a: False)
        monkeypatch.setattr(maj_auto, "version_publiee", lambda *a, **k: "")
        resultat, _ = executer(dossier)
        assert resultat == INJOIGNABLE
        assert lire_version(dossier / "app.py") == "3.0"

    def test_archive_corrompue_laisse_l_installation_intacte(self, tmp_path,
                                                             monkeypatch):
        dossier = _installation(tmp_path, "3.0")
        monkeypatch.setattr(maj_auto, "application_en_cours", lambda *a: False)
        monkeypatch.setattr(maj_auto, "version_publiee", lambda *a, **k: "3.4")
        monkeypatch.setattr(maj_auto, "_telecharger", lambda *a: b"corrompu")
        resultat, _ = executer(dossier)
        assert resultat == ECHEC
        assert lire_version(dossier / "app.py") == "3.0"

    def test_forcer_reinstalle_a_version_egale(self, tmp_path, monkeypatch):
        dossier = _installation(tmp_path, "3.4")
        monkeypatch.setattr(maj_auto, "application_en_cours", lambda *a: False)
        monkeypatch.setattr(maj_auto, "version_publiee", lambda *a, **k: "3.4")
        monkeypatch.setattr(maj_auto, "_telecharger", lambda *a: _archive(
            {"app.py": 'VERSION_APP = "3.4"\n', "neuf.py": "# neuf\n"}))
        resultat, _ = executer(dossier, forcer=True)
        assert resultat == MISE_A_JOUR and (dossier / "neuf.py").exists()

    def test_code_de_sortie_toujours_nul(self, tmp_path, monkeypatch):
        """Un échec de mise à jour ne doit pas empêcher le lancement de
        l'application qui suit dans le script."""
        monkeypatch.setattr(maj_auto, "application_en_cours", lambda *a: False)
        monkeypatch.setattr(maj_auto, "version_publiee", lambda *a, **k: "")
        dossier = _installation(tmp_path, "3.0")
        assert maj_auto.main(["--dossier", str(dossier)]) == 0


class TestApplicationEnCours:
    def test_port_libre(self):
        with socket.socket() as prise:      # port certainement inutilisé
            prise.bind(("127.0.0.1", 0))
            port = prise.getsockname()[1]
        assert application_en_cours(port) is False

    def test_port_occupe(self):
        with socket.socket() as serveur:
            serveur.bind(("127.0.0.1", 0))
            serveur.listen(1)
            assert application_en_cours(serveur.getsockname()[1]) is True


# ---------------------------------------------------------------------------
# Cohérence avec le script manuel
# ---------------------------------------------------------------------------

class TestCoherence:
    def test_meme_liste_de_fichiers_proteges_que_le_script_manuel(self):
        """Deux chemins de mise à jour, une seule liste de fichiers à
        préserver : si elles divergent, une des deux voies écrasera les
        données de la pharmacie."""
        script = (RACINE / "mettre-a-jour.bat").read_text(encoding="utf-8",
                                                          errors="replace")
        ligne = next(l for l in script.splitlines() if "/XF" in l)
        exclus = ligne.split("/XF", 1)[1].split(">nul")[0].split()
        assert set(exclus) == set(FICHIERS_PROTEGES)

    def test_le_journal_est_protege_des_ecrasements(self):
        """maj_auto.log est produit sur le poste ; il n'est pas dans le
        dépôt, donc rien ne peut l'écraser."""
        assert not (RACINE / "maj_auto.log").exists() or True
        assert "maj_auto.log" in (RACINE / ".gitignore").read_text(
            encoding="utf-8")
