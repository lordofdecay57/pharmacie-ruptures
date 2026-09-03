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
import os
import socket
import subprocess
import time
import zipfile
from pathlib import Path

import pytest

import maj_auto
import presence
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

    def test_un_fichier_ouvert_ailleurs_annule_TOUT(self, tmp_path):
        """Le cas réel : l'Explorateur garde `pharmacie.ico` ouvert pour
        chaque raccourci du Bureau qui pointe dessus. La copie avançait
        jusque-là puis s'arrêtait — laissant un `app.py` neuf sur un
        `ui_stock_ferme.py` ancien, donc un écran qui plante sur une
        fonction qui n'existe pas encore.

        Un dossier à moitié mis à jour est pire qu'un dossier en retard.
        """
        import maj_auto as module
        dossier = _installation(tmp_path, "3.0")
        (dossier / "pharmacie.ico").write_bytes(b"ancienne icone")
        archive = _archive({"app.py": 'VERSION_APP = "3.4"\n',
                            "pharmacie.ico": "neuve",
                            "ui_stock_ferme.py": "# neuf\n"})

        # Windows refuse le remplacement ; ailleurs, on simule le refus.
        vrai = module.fichiers_bloques
        module.fichiers_bloques = lambda d, r: ["pharmacie.ico"]
        try:
            with pytest.raises(module.FichiersBloques) as echec:
                installer_archive(archive, dossier)
        finally:
            module.fichiers_bloques = vrai

        assert "pharmacie.ico" in str(echec.value)
        assert "Rien n'a été modifié" in str(echec.value)
        # RIEN n'a bougé, pas même les fichiers qui, eux, étaient libres.
        assert lire_version(dossier / "app.py") == "3.0"
        assert not (dossier / "ui_stock_ferme.py").exists()

    def test_un_fichier_libre_ne_bloque_rien(self, tmp_path):
        dossier = _installation(tmp_path, "3.0")
        (dossier / "app.py").write_text("x", encoding="utf-8")
        assert maj_auto.fichiers_bloques(dossier, ["app.py"]) == []

    def test_un_fichier_qu_on_ne_peut_pas_reecrire_est_detecte(self,
                                                              tmp_path):
        """Windows verrouille, un partage en lecture seule refuse : dans
        les deux cas le fichier ne peut pas être remplacé, et il faut le
        savoir AVANT d'avoir touché aux autres.

        Un vrai verrou Windows n'est pas reproductible ici, et les droits
        de fichier ne le sont pas non plus sous root. On prend donc un
        chemin qui refuse `open(..., "r+b")` de façon certaine : il
        emprunte exactement le même code, jusqu'à l'`OSError`."""
        (tmp_path / "pharmacie.ico").mkdir()
        assert maj_auto.fichiers_bloques(tmp_path, ["pharmacie.ico"]) \
            == ["pharmacie.ico"]

    def test_un_fichier_absent_ne_bloque_rien(self, tmp_path):
        """Un fichier neuf ne peut être ouvert par personne."""
        assert maj_auto.fichiers_bloques(tmp_path, ["jamais_vu.py"]) == []

    def test_le_controle_precede_la_moindre_ecriture(self, tmp_path):
        """Vérifier au fil de l'eau reviendrait à s'arrêter au milieu."""
        source = (RACINE / "maj_auto.py").read_text(encoding="utf-8")
        corps = source[source.index("def installer_archive"):]
        assert corps.index("fichiers_bloques(") < corps.index("shutil.copy2")

    def test_le_blocage_remonte_comme_un_echec_explicite(self, tmp_path,
                                                         monkeypatch):
        """`executer` ne lève jamais : le blocage doit ressortir en message
        français, pas en trace Python."""
        import maj_auto as module
        dossier = _installation(tmp_path, "3.0")
        monkeypatch.setattr(module, "application_en_cours", lambda: False)
        monkeypatch.setattr(module, "version_publiee", lambda *a, **k: "3.4")
        monkeypatch.setattr(module, "_telecharger",
                            lambda *a, **k: _archive(
                                {"app.py": 'VERSION_APP = "3.4"\n'}))
        monkeypatch.setattr(module, "fichiers_bloques",
                            lambda d, r: ["pharmacie.ico"])
        resultat, message = module.executer(dossier)
        assert resultat == ECHEC
        assert "pharmacie.ico" in message
        assert lire_version(dossier / "app.py") == "3.0"

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


class TestPostesSurLeMemeDossier:
    """Le dossier vit sur un partage : qui d'autre travaille dessus ?

    Le test du port ne voit que cette machine. Les marqueurs de
    ``presence.py`` disent qui d'autre a ouvert l'application sur CES
    fichiers — et c'est le seul garde-fou pour les autres comptoirs.
    """

    def _sans_reseau(self, monkeypatch, publiee="3.4"):
        monkeypatch.setattr(maj_auto, "application_en_cours", lambda *a: False)
        monkeypatch.setattr(maj_auto, "version_publiee", lambda *a, **k: publiee)
        monkeypatch.setattr(maj_auto, "_telecharger", lambda *a: _archive(
            {"app.py": f'VERSION_APP = "{publiee}"\n'}))

    def test_un_autre_poste_ouvert_reporte_la_mise_a_jour(self, tmp_path,
                                                          monkeypatch):
        """Remplacer les fichiers sous la session du comptoir voisin, c'est
        son écran qui part en erreur au milieu d'un scan."""
        dossier = _installation(tmp_path, "3.0")
        self._sans_reseau(monkeypatch)
        presence.entrer(dossier, "COMPTOIR-2")
        resultat, message = executer(dossier)
        assert resultat == APPLICATION_EN_COURS
        assert "COMPTOIR-2" in message          # on NOMME le poste en cause
        assert lire_version(dossier / "app.py") == "3.0"

    def test_son_propre_marqueur_oublie_ne_bloque_pas_le_poste(self, tmp_path,
                                                               monkeypatch):
        """LE blocage silencieux : la mise à jour ne se faisait plus.

        Fermer la fenêtre noire par la croix — la façon documentée
        d'arrêter l'application — tue cmd avant sa dernière ligne,
        ``presence.py --sortir``. Le marqueur du poste restait donc là, et
        valait seize heures. Au lancement suivant, ``maj_auto`` s'y voyait
        lui-même, refusait de se mettre à jour, et affichait « Dossier en
        cours d'utilisation par POSTE-COMPTOIR-2 » **sur** le poste
        COMPTOIR-2. La session en cours de ce poste-ci, elle, est déjà
        couverte par le test du port, qui répond avant.
        """
        dossier = _installation(tmp_path, "3.0")
        self._sans_reseau(monkeypatch)
        presence.entrer(dossier)                # marqueur de CE poste
        resultat, message = executer(dossier)
        assert resultat == MISE_A_JOUR, message
        assert lire_version(dossier / "app.py") == "3.4"

    def test_un_marqueur_perime_ne_bloque_plus(self, tmp_path, monkeypatch):
        """Un poste débranché ne doit pas figer la pharmacie pour toujours."""
        dossier = _installation(tmp_path, "3.0")
        self._sans_reseau(monkeypatch)
        vieux = presence.marqueur(dossier, "POSTE-ETEINT")
        presence.entrer(dossier, "POSTE-ETEINT")
        ancien = time.time() - (presence.DUREE_MAX_H + 1) * 3600
        os.utime(vieux, (ancien, ancien))
        assert executer(dossier)[0] == MISE_A_JOUR

    def test_le_port_passe_avant_les_marqueurs(self, tmp_path, monkeypatch):
        """L'application de CE poste tourne : on s'arrête là, sans même
        aller lire les marqueurs du partage."""
        dossier = _installation(tmp_path, "3.0")
        monkeypatch.setattr(maj_auto, "application_en_cours", lambda *a: True)
        monkeypatch.setattr(
            presence, "autres_postes",
            lambda *a, **k: pytest.fail("le port répond : rien à lire"))
        assert executer(dossier)[0] == APPLICATION_EN_COURS


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


class TestLArchiveNeContientQueLeProgramme:
    """Le ZIP lui-même, et non plus seulement ce qu'on en installe.

    Jusqu'ici l'archive descendait entière — 2,4 Mo de tests compris — et
    c'est à l'installation qu'on les écartait. Celui qui téléchargeait le
    ZIP à la main, lui, dépliait tout dans le dossier de l'officine.

    ``export-ignore`` retire ces chemins de ce que produit ``git
    archive``, et c'est exactement ce que GitHub exécute pour son bouton
    « Download ZIP ». Les fichiers restent dans le dépôt : ils ne sont
    pas supprimés, ils ne sont pas EXPORTÉS.
    """

    FICHIER = RACINE / ".gitattributes"

    def _exportes_ignores(self) -> set:
        chemins = set()
        for ligne in self.FICHIER.read_text(encoding="utf-8").splitlines():
            nu = ligne.strip()
            if not nu or nu.startswith("#") or "export-ignore" not in nu:
                continue
            chemins.add(nu.split()[0].rstrip("/"))
        return chemins

    def test_le_fichier_existe(self):
        assert self.FICHIER.is_file(), (
            "sans .gitattributes, GitHub met TOUT dans le ZIP")

    @pytest.mark.parametrize("dossier", ["tests", "outils"])
    def test_les_dossiers_de_fabrication_ne_sont_pas_exportes(self, dossier):
        assert dossier in self._exportes_ignores()

    def test_aucun_dossier_de_developpement_suivi_n_est_oublie(self):
        """Les deux listes doivent dire la même chose. ``maj_auto`` écarte
        ces dossiers à l'installation ; l'archive doit les écarter à la
        source. Un dossier ajouté d'un côté et oublié de l'autre remettrait
        les tests dans le dossier de la pharmacie.

        On interroge **git**, et non le disque : ``__pycache__`` et
        ``.pytest_cache`` existent bien ici, mais ils sont ignorés — ils
        n'entrent dans aucune archive, et les inscrire ne protégerait de
        rien. Seul ce que git SUIT peut se retrouver dans le ZIP.
        """
        suivis = subprocess.run(
            ["git", "ls-files"], cwd=RACINE, capture_output=True, text=True)
        if suivis.returncode != 0:              # pragma: no cover
            pytest.skip("dépôt git indisponible")
        dossiers = {chemin.split("/")[0]
                    for chemin in suivis.stdout.splitlines() if "/" in chemin}
        a_exclure = dossiers & set(maj_auto.DOSSIERS_DE_DEVELOPPEMENT)
        oublies = a_exclure - self._exportes_ignores()
        assert not oublies, f"absents de .gitattributes : {sorted(oublies)}"

    def test_le_programme_lui_reste_dans_l_archive(self):
        """Le garde-fou dans l'autre sens : exclure `app.py` ou un `.bat`
        livrerait un ZIP qui ne démarre pas."""
        exclus = self._exportes_ignores()
        for indispensable in ("app.py", "lancer.bat", "requirements.txt",
                              "stock_ferme.py", "presence.py", "maj_auto.py",
                              "pharmacie.ico", ".streamlit"):
            assert indispensable not in exclus, indispensable

    def test_maj_auto_garde_son_propre_filtre(self):
        """Ceinture ET bretelles, volontairement : un poste peut installer
        une archive plus ancienne, faite avant ce .gitattributes. Le filtre
        de `maj_auto` est ce qui la rend inoffensive."""
        assert set(maj_auto.DOSSIERS_DE_DEVELOPPEMENT) >= {"tests", "outils"}
