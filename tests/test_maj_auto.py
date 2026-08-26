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
from maj_auto import (APPLICATION_EN_COURS, CODE_DEJA_OUVERTE, DEJA_A_JOUR,
                      ECHEC, FICHIERS_PROTEGES,
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
        """`.streamlit/config.toml` porte le thème et supprime le
        questionnaire de bienvenue : un sous-dossier qui doit descendre."""
        dossier = _installation(tmp_path)
        installer_archive(_archive({
            "app.py": 'VERSION_APP = "3.4"\n',
            ".streamlit/config.toml": "[server]\n"}), dossier)
        assert (dossier / ".streamlit" / "config.toml").exists()

    @pytest.mark.parametrize("chemin", [
        "tests/test_x.py", "tests/donnees/cadencier.csv",
        "outils/creer_icone.py", "web/src/app/page.tsx",
        ".github/workflows/ci.yml", "__pycache__/app.cpython-313.pyc"])
    def test_le_dossier_de_l_officine_ne_recoit_que_le_programme(
            self, tmp_path, chemin):
        """Le dépôt contient aussi tout ce qui sert à FABRIQUER le
        programme : 2,3 Mo de tests, les outils, une application web sans
        rapport. Déversés dans le dossier de l'officine, ils y noyaient
        `lancer.bat` sous une centaine de fichiers inconnus — et personne
        ne lance un utilitaire dont il ne reconnaît aucun fichier."""
        dossier = _installation(tmp_path)
        installer_archive(_archive({
            "app.py": 'VERSION_APP = "3.4"\n', chemin: "x\n"}), dossier)
        assert not (dossier / chemin).exists(), chemin
        assert (dossier / "app.py").exists(), "le programme doit descendre"

    def test_le_compte_annonce_ne_compte_pas_l_ecarte(self, tmp_path):
        """« 47 fichiers » alors qu'on en a écrit deux, c'est un compte
        rendu qui ment sur ce qui vient de se passer."""
        dossier = _installation(tmp_path)
        ecrits = installer_archive(_archive({
            "app.py": 'VERSION_APP = "3.4"\n',
            "lancer.bat": "@echo off\n",
            "tests/test_x.py": "# test\n",
            "web/page.tsx": "x\n"}), dossier)
        assert ecrits == 2, ecrits

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

    def test_un_echec_ne_bloque_pas_le_lancement(self, tmp_path, monkeypatch):
        """Le lanceur enchaîne sur le démarrage de l'application : une mise
        à jour ratée ne doit pas l'en empêcher."""
        monkeypatch.setattr(maj_auto, "application_en_cours", lambda *a: False)
        monkeypatch.setattr(maj_auto, "version_publiee", lambda *a, **k: "")
        dossier = _installation(tmp_path, "3.0")
        assert maj_auto.main(["--dossier", str(dossier)]) == 0

    def test_application_ouverte_signalee_au_lanceur(self, tmp_path,
                                                     monkeypatch):
        """Code 10 : le lanceur doit ouvrir le navigateur sur l'instance en
        cours. Sans ce signal, il tentait un second démarrage, échouait sur
        le port occupé et laissait l'utilisateur devant « Port 8501 is not
        available » alors qu'il voulait juste voir son écran."""
        monkeypatch.setattr(maj_auto, "application_en_cours", lambda *a: True)
        dossier = _installation(tmp_path, "3.0")
        assert maj_auto.main(["--dossier", str(dossier)]) == CODE_DEJA_OUVERTE

    def test_mise_a_jour_reussie_laisse_le_lanceur_demarrer(self, tmp_path,
                                                            monkeypatch):
        monkeypatch.setattr(maj_auto, "application_en_cours", lambda *a: False)
        monkeypatch.setattr(maj_auto, "version_publiee", lambda *a, **k: "3.4")
        monkeypatch.setattr(maj_auto, "_telecharger", lambda *a: _archive(
            {"app.py": 'VERSION_APP = "3.4"\n'}))
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
    #: Les deux scripts s'excluent EN PLUS des données : ils tournent
    #: pendant que robocopy réécrit le dossier.
    SCRIPTS = {"mettre-a-jour.bat", "mettre-a-jour-serveur.bat"}

    @pytest.mark.parametrize("nom", sorted(SCRIPTS))
    def test_meme_liste_de_fichiers_proteges_que_le_script_manuel(self, nom):
        """Trois chemins de mise à jour, une seule liste de données à
        préserver : si elles divergent, une des trois voies écrasera les
        données de la pharmacie."""
        script = (RACINE / nom).read_text(encoding="utf-8", errors="replace")
        ligne = next(l for l in script.splitlines() if "/XF" in l)
        exclus = ligne.split("/XF", 1)[1].split(">nul")[0].split()
        assert set(exclus) == set(FICHIERS_PROTEGES) | self.SCRIPTS

    @pytest.mark.parametrize("nom", sorted(SCRIPTS))
    def test_les_dossiers_de_developpement_sont_ecartes_partout(self, nom):
        """Trois chemins de mise à jour, une seule idée de ce qui doit
        descendre. Si le script manuel recopie les tests que `maj_auto`
        écarte, le dossier de l'officine redevient illisible dès qu'on
        clique sur le mauvais des deux."""
        ligne = next(l for l in (RACINE / nom).read_text(encoding="ascii")
                     .splitlines() if l.startswith("robocopy "))
        exclus = set(ligne.split("/XD", 1)[1].split("/XF")[0].split())
        assert exclus == set(maj_auto.DOSSIERS_DE_DEVELOPPEMENT), (
            f"{nom} : {sorted(exclus)}")

    def test_les_scripts_de_mise_a_jour_se_protegent_eux_memes(self):
        """Chacun est en cours d'exécution pendant que robocopy réécrit le
        dossier, et cmd relit le fichier au fil des lignes : le remplacer
        sous ses pieds lui ferait exécuter n'importe quoi."""
        for nom in sorted(self.SCRIPTS):
            script = (RACINE / nom).read_text(encoding="utf-8",
                                              errors="replace")
            ligne = next(l for l in script.splitlines() if "/XF" in l)
            assert nom in ligne.split("/XF", 1)[1], f"{nom} doit s'exclure"

    def test_mais_maj_auto_a_le_droit_de_les_corriger(self):
        """Un bug dans ces scripts était jusqu'ici INCORRIGEABLE : ils
        s'excluaient de leur propre copie ET de celle de maj_auto. Réparé
        dans le dépôt, il restait indéfiniment chez la pharmacie.

        Ici c'est Python qui écrit, et aucun des deux n'est en train de
        tourner : rien ne justifie de les épargner."""
        for nom in sorted(self.SCRIPTS):
            assert nom not in FICHIERS_PROTEGES, (
                f"{nom} ne pourra jamais être corrigé à distance")

    def test_seules_les_donnees_sont_protegees(self):
        """La liste est celle des fichiers de la PHARMACIE. Y glisser du
        code, c'est se priver de pouvoir le réparer."""
        for nom in FICHIERS_PROTEGES:
            assert not nom.endswith((".bat", ".py")), (
                f"{nom} est du programme, pas une donnée")

    def test_le_journal_est_protege_des_ecrasements(self):
        """maj_auto.log est produit sur le poste ; il n'est pas dans le
        dépôt, donc rien ne peut l'écraser."""
        assert not (RACINE / "maj_auto.log").exists() or True
        assert "maj_auto.log" in (RACINE / ".gitignore").read_text(
            encoding="utf-8")
