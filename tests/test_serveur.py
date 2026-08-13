# -*- coding: utf-8 -*-
"""Installation sur un serveur : les deux scripts qui la rendent possible.

Personne ne les exécute pendant les tests — c'est cmd qui les interprète,
sur un Windows qu'on n'a pas ici. Ce qu'on peut vérifier, et qui suffit à
éviter les pannes réellement redoutées : que le serveur écoute bien sur le
réseau et non sur lui-même seul, que le port annoncé aux postes est celui
sur lequel il démarre, et que les scripts restent lisibles par cmd.
"""

from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
SERVEUR = RACINE / "lancer-serveur.bat"
POSTE = RACINE / "creer-raccourci-poste.bat"
README = RACINE / "README.md"

PORT = "8501"


def _texte(chemin: Path) -> str:
    return chemin.read_text(encoding="ascii")


class TestScriptsPresents:
    @pytest.mark.parametrize("chemin", [SERVEUR, POSTE])
    def test_le_script_existe(self, chemin):
        assert chemin.is_file(), f"{chemin.name} manquant à la racine"

    @pytest.mark.parametrize("chemin", [SERVEUR, POSTE])
    def test_sans_accent(self, chemin):
        """cmd lit ces fichiers dans une page de codes qui n'est pas celle
        de l'éditeur : un « é » y devient un caractère illisible, au milieu
        d'un message qu'on lit justement quand quelque chose ne va pas."""
        try:
            _texte(chemin)
        except UnicodeDecodeError as erreur:
            pytest.fail(f"{chemin.name} contient un caractère non ASCII "
                        f"(position {erreur.start})")


class TestServeur:
    def test_ecoute_sur_le_reseau(self):
        """Sans ``--server.address 0.0.0.0``, l'application n'est joignable
        que depuis le serveur : les postes ne verraient rien."""
        assert "--server.address 0.0.0.0" in _texte(SERVEUR)

    def test_le_port_annonce_est_le_port_ouvert(self):
        """L'adresse donnée aux postes et le port de démarrage viennent du
        même script : s'ils divergent, chaque poste reçoit une icône qui ne
        mène nulle part."""
        texte = _texte(SERVEUR)
        assert f"--server.port {PORT}" in texte
        assert f":{PORT}" in texte, "l'adresse affichée doit porter le port"

    def test_ne_tente_pas_d_ouvrir_un_navigateur(self):
        """Un serveur tourne souvent sans session ouverte : Streamlit doit
        démarrer sans chercher de navigateur."""
        assert "--server.headless true" in _texte(SERVEUR)

    def test_met_a_jour_avant_de_demarrer(self):
        """Le seul instant où remplacer des fichiers est sans danger."""
        assert "maj_auto.py" in _texte(SERVEUR)

    def test_previent_si_le_serveur_tourne_deja(self):
        """Code 10 de ``maj_auto`` : l'application répond déjà. Démarrer une
        seconde fois échouerait sur le port occupé."""
        assert "errorlevel 10" in _texte(SERVEUR)

    def test_laisse_l_adresse_pour_les_postes(self):
        """Écrite à côté de l'application : si le dossier est partagé,
        personne n'a de chiffres à recopier."""
        assert "adresse-serveur.txt" in _texte(SERVEUR)

    def test_dit_de_ne_pas_fermer_la_fenetre(self):
        """La fenêtre noire EST l'application — pour toute la pharmacie."""
        assert "NE FERMEZ PAS" in _texte(SERVEUR)


class TestRaccourciPoste:
    def test_ecrit_un_raccourci_internet(self):
        """Du texte brut : aucun PowerShell requis, certains postes
        d'officine l'interdisent par stratégie de groupe."""
        texte = _texte(POSTE)
        assert "[InternetShortcut]" in texte
        assert "URL=%ADRESSE%" in texte

    def test_lit_l_adresse_laissee_par_le_serveur(self):
        assert "adresse-serveur.txt" in _texte(POSTE)

    def test_la_lecture_n_est_pas_accrochee_a_un_if(self):
        """Piège classique de cmd : une redirection sur un « if » d'une seule
        ligne est traitée AVANT le test, et se plaint quand le fichier n'est
        pas là — c'est-à-dire dans le cas normal, hors dossier partagé."""
        for ligne in _texte(POSTE).splitlines():
            nu = ligne.strip().lower()
            if nu.startswith("if ") and "set /p" in nu and "<" in nu:
                pytest.fail(f"redirection accrochée à un « if » : {ligne}")

    def test_accepte_une_adresse_deja_complete(self):
        """On ne va pas reprocher à quelqu'un d'avoir collé ce qu'il voyait
        dans la barre du navigateur."""
        texte = _texte(POSTE)
        assert 'findstr /b /i "http"' in texte
        assert f"http://%ADRESSE%:{PORT}" in texte

    def test_le_bureau_redirige_est_pris_en_compte(self):
        """OneDrive déplace le Bureau : le chemin en dur pointe alors sur un
        dossier vide que personne ne regarde."""
        texte = _texte(POSTE)
        assert "GetFolderPath('Desktop')" in texte
        assert "OneDrive" in texte

    def test_l_icone_est_copiee_sur_le_poste(self):
        """La laisser sur le partage rend le Bureau dépendant du serveur
        pour dessiner une image."""
        texte = _texte(POSTE)
        assert "LOCALAPPDATA" in texte
        assert "pharmacie.ico" in texte

    def test_n_installe_rien_sur_le_poste(self):
        """Le poste ne reçoit qu'une adresse : ni Python, ni l'application,
        ni données. Un ``pip install`` ici serait une erreur de conception,
        pas un détail."""
        texte = _texte(POSTE)
        assert "pip install" not in texte
        assert "streamlit run" not in texte


class TestDocumentation:
    def test_le_readme_explique_l_installation_serveur(self):
        texte = README.read_text(encoding="utf-8")
        for attendu in ("lancer-serveur.bat", "creer-raccourci-poste.bat",
                        "port 8501", "adresse IP fixe"):
            assert attendu in texte, f"« {attendu} » absent du README"

    def test_les_reglages_windows_sont_donnes_pas_seulement_nommes(self):
        """« Autorisez le port dans le pare-feu » n'aide personne devant la
        machine : il faut la commande, le chemin des fenêtres, et le piège
        qui va avec."""
        texte = README.read_text(encoding="utf-8")
        for attendu in ("netsh advfirewall firewall add rule",
                        "wf.msc",
                        "show currentprofile",       # profil public = tout bloqué
                        "ipconfig /all",
                        "netsh interface ip set address",
                        "Longueur du préfixe de sous-réseau",
                        "hors de la plage distribuée par la box"):
            assert attendu in texte, f"« {attendu} » absent du README"

    def test_le_readme_previent_de_la_mise_en_veille(self):
        """Un serveur endormi ne répond plus, et les postes affichent une
        page blanche sans explication."""
        texte = README.read_text(encoding="utf-8")
        assert "mise en veille" in texte.lower()
        assert "Alimentation" in texte

    def test_le_readme_previent_de_recuperer_les_donnees(self):
        """Supprimer l'installation d'un poste sans récupérer son
        inventaire, c'est perdre ce qui n'existe nulle part ailleurs."""
        texte = README.read_text(encoding="utf-8")
        assert "Avant de supprimer" in texte
        assert "stock_ferme.csv" in texte

    def test_l_adresse_du_serveur_n_est_pas_versionnee(self):
        """Elle dépend du réseau de la pharmacie : la livrer écraserait
        celle du serveur à chaque mise à jour."""
        ignores = (RACINE / ".gitignore").read_text(encoding="utf-8")
        assert "adresse-serveur.txt" in ignores
