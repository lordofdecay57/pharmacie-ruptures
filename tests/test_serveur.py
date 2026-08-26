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
MAJ_SERVEUR = RACINE / "mettre-a-jour-serveur.bat"
PLANIFIER = RACINE / "planifier-maj-serveur.bat"
#: L'ouverture automatique du matin : posée sur chaque poste, à la même
#: visite que l'icône du Bureau.
OUVERTURE = RACINE / "planifier-ouverture-poste.bat"
README = RACINE / "README.md"
#: La procédure imprimable, en texte brut : elle s'ouvre au Bloc-notes,
#: se pose à côté du serveur, et ne suppose pas de savoir lire un Markdown.
CONSIGNE = RACINE / "INSTALLATION-SERVEUR.txt"
#: Le même parcours en PDF : une étape par page, à imprimer
#: et à cocher au fur et à mesure devant la machine.
GUIDE = RACINE / "Guide-installation-serveur.pdf"

#: Tous les scripts d'installation serveur, pour les contrôles communs.
SCRIPTS = [SERVEUR, POSTE, MAJ_SERVEUR, PLANIFIER, OUVERTURE,
           RACINE / "ouvrir-le-matin.bat"]

PORT = "8501"


def _texte(chemin: Path) -> str:
    return chemin.read_text(encoding="ascii")


def _consigne() -> str:
    return CONSIGNE.read_text(encoding="ascii")


def _phrase() -> str:
    """La consigne avec les espaces réduits à un seul.

    Le document est enveloppé à 63 colonnes pour s'imprimer : une phrase
    y est presque toujours coupée par un retour à la ligne. La chercher
    telle quelle échouerait sur la mise en page, pas sur le fond.
    """
    return " ".join(_consigne().split())


class TestScriptsPresents:
    @pytest.mark.parametrize("chemin", SCRIPTS)
    def test_le_script_existe(self, chemin):
        assert chemin.is_file(), f"{chemin.name} manquant à la racine"

    @pytest.mark.parametrize("chemin", SCRIPTS)
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


class TestMiseAJourDuServeur:
    """Un serveur qui tourne en continu ne se met jamais à jour tout seul.

    La mise à jour automatique n'a lieu qu'au démarrage, et elle se reporte
    tant que l'application répond : deux conditions qu'une machine allumée
    en permanence ne remplit jamais. Ces scripts sont la seule voie qui
    reste — s'ils se trompent, la pharmacie reste sur sa version du premier
    jour sans que rien ne le signale.
    """

    def test_relance_en_mode_serveur(self):
        """Écrit noir sur blanc plutôt que laissé au défaut de Streamlit
        (qui écoute aujourd'hui sur toutes les cartes réseau) : un serveur
        ne doit pas dépendre d'un défaut susceptible de changer, et
        l'intention doit se lire dans le script."""
        texte = _texte(MAJ_SERVEUR)
        assert "--server.address 0.0.0.0" in texte
        assert "--server.headless true" in texte
        assert f"--server.port {PORT}" in texte

    def test_le_readme_situe_les_deux_scripts_l_un_par_rapport_a_l_autre(self):
        """Les deux noms se ressemblent trop pour laisser deviner. Et la
        différence doit être dite JUSTE : employer celui du poste isolé sur
        un serveur n'est pas une catastrophe — les postes retrouveraient
        l'application — c'est simplement moins propre et sans journal."""
        texte = README.read_text(encoding="utf-8")
        situe = texte.split("préférez `mettre-a-jour-serveur.bat`", 1)
        assert len(situe) > 1, "le README doit comparer les deux scripts"
        assert "**fonctionnerait**" in situe[1][:600], (
            "ne pas laisser croire que le mauvais script coupe la pharmacie")

    def test_silencieux_ne_bloque_sur_aucune_touche(self):
        """La tâche de nuit lance le script sans personne devant : un
        « Appuyez sur une touche » laisserait l'application arrêtée jusqu'au
        matin, pharmacie hors service.

        On ne regarde que le chemin RÉELLEMENT parcouru en mode silencieux :
        le script saute la branche du double-clic, qui a le droit d'attendre
        une touche puisque quelqu'un est devant.
        """
        lignes = _texte(MAJ_SERVEUR).splitlines()
        saute, silencieux = False, []
        for ligne in lignes:
            nu = ligne.strip().lower()
            if nu.startswith("if defined silence goto "):
                saute = True                       # début de la branche écran
                continue
            if saute and nu.startswith(":"):
                saute = False                      # la branche muette reprend
            if not saute:
                silencieux.append(ligne)

        assert len(silencieux) < len(lignes), (
            "aucun embranchement trouvé : le test ne vérifierait rien")
        for ligne in silencieux:
            nu = ligne.strip().lower()
            if nu == "pause" or nu.startswith("pause "):
                pytest.fail(f"pause atteignable sans personne devant : "
                            f"{ligne!r}")
            if nu.startswith("timeout ") and "/nobreak" not in nu:
                pytest.fail(f"attente interruptible au clavier : {ligne!r}")
            if nu.startswith("set /p "):
                pytest.fail(f"question posée à personne — la nuit, le script "
                            f"attendrait une réponse jusqu'au matin : "
                            f"{ligne!r}")

    def test_la_tache_de_nuit_ne_retient_pas_l_application(self):
        """Le planificateur de Windows arrête par défaut toute tâche qui
        dépasse 72 heures. Si la tâche gardait l'application au premier
        plan, le serveur mourrait tous les trois jours, en pleine journée,
        sans que rien ne l'explique. En mode silencieux, l'application doit
        donc partir dans son propre processus."""
        texte = _texte(MAJ_SERVEUR)
        detache = texte.split(":detache", 1)
        assert len(detache) > 1, "il faut un chemin distinct pour la tâche"
        assert "start " in detache[1], (
            "l'application doit être lancée détachée, pas tenue par la tâche")
        assert "streamlit run" in detache[1]

    def test_ne_pose_pas_d_icone_sur_le_serveur(self):
        """Personne ne s'assoit devant le serveur : une icône de Bureau y
        est du bruit."""
        assert "creer-raccourci.bat" not in _texte(MAJ_SERVEUR)

    def test_journalise_chaque_execution(self):
        """Une mise à jour faite à 5 h du matin doit rester explicable au
        matin."""
        texte = _texte(MAJ_SERVEUR)
        assert "maj_serveur.log" in texte
        assert "VERSION_APP" in texte, "le journal doit dire d'où l'on part"

    def test_aucun_message_ne_se_transforme_en_redirection(self):
        """``:dire`` affiche ``%~1``, ce qui RETIRE les guillemets : un
        message contenant ``<``, ``>``, ``|`` ou ``&`` serait alors compris
        comme une redirection, et cmd irait écrire dans un fichier au lieu
        d'afficher la phrase. Le cas s'est produit avec un
        « http://<ce serveur>:8501 » d'apparence inoffensive."""
        for numero, ligne in enumerate(_texte(MAJ_SERVEUR).splitlines(), 1):
            nu = ligne.strip()
            if not nu.lower().startswith("call :dire"):
                continue
            message = nu.split('"', 1)[-1].rsplit('"', 1)[0]
            interdits = [c for c in "<>|&" if c in message]
            assert not interdits, (
                f"ligne {numero} : {interdits} dans un message affiché "
                f"sans guillemets — {ligne}")

    def test_un_echec_ne_ferme_pas_la_pharmacie(self):
        """Internet coupé, archive illisible : rien n'est modifié et
        l'application en cours continue de tourner."""
        assert ":echec" in _texte(MAJ_SERVEUR)


class TestPlanification:
    def test_enregistre_verifie_et_sait_se_retirer(self):
        texte = _texte(PLANIFIER)
        assert "schtasks /create" in texte
        assert "schtasks /delete" in texte
        assert "schtasks /query" in texte, (
            "afficher la fiche de Windows vaut mieux qu'affirmer que "
            "la tâche existe")

    def test_tourne_dans_la_session_de_l_utilisateur(self):
        """Sous ``SYSTEM``, la nouvelle instance démarrerait dans une
        session invisible : plus personne ne pourrait l'arrêter, et la
        fenêtre noire de l'application aurait disparu."""
        for ligne in _texte(PLANIFIER).splitlines():
            nu = ligne.strip().lower()
            if nu.startswith("rem"):        # le commentaire l'explique
                continue
            assert "/ru system" not in nu, ligne

    def test_lance_le_script_serveur_en_silencieux(self):
        texte = _texte(PLANIFIER)
        assert "mettre-a-jour-serveur.bat" in texte
        assert "/silencieux" in texte

    def test_une_heure_par_defaut_en_creux(self):
        """Une mise à jour redémarre l'application : elle ne doit pas
        tomber en pleine journée."""
        assert "05:00" in _texte(PLANIFIER)


class TestConsigneImprimable:
    """La procédure serveur en texte brut, à poser à côté de la machine.

    Le README la contient aussi, mais il fait mille lignes et suppose de
    savoir ouvrir un fichier Markdown — ce qui n'est pas le cas de tout le
    monde. Celle-ci s'ouvre au Bloc-notes et s'imprime.
    """

    def test_le_document_existe(self):
        assert CONSIGNE.is_file(), "INSTALLATION-SERVEUR.txt manquant"

    def test_il_est_lisible_par_le_bloc_notes(self):
        """Un « é » dans un fichier texte lu avec la mauvaise page de codes
        devient un caractère illisible — au milieu d'une consigne qu'on lit
        justement quand on ne sait pas quoi faire."""
        try:
            CONSIGNE.read_text(encoding="ascii")
        except UnicodeDecodeError as erreur:
            pytest.fail(f"caractère non ASCII en position {erreur.start}")

    def test_il_s_imprime_sans_se_couper(self):
        """Une seule ligne a le droit d'être longue : la commande netsh, qui
        doit rester d'un seul tenant pour être copiée."""
        longues = [ligne for ligne in _consigne().splitlines()
                   if len(ligne) > 66]
        assert len(longues) == 1 and longues[0].startswith("netsh"), longues

    def test_la_commande_longue_est_annoncee_comme_telle(self):
        """Imprimée, elle apparaît coupée : sans avertissement, on la
        recopie avec un retour à la ligne au milieu, et elle échoue."""
        texte = _consigne()
        avant = _phrase().split("netsh advfirewall firewall add rule", 1)[0]
        assert "UNE SEULE LIGNE" in avant

    def test_les_neuf_etapes_y_sont_toutes(self):
        texte = _phrase()
        for numero in range(1, 10):
            assert f"ETAPE {numero} " in texte, f"ETAPE {numero} manquante"

    def test_elle_nomme_les_scripts_reellement_livres(self):
        """Une consigne qui nomme un fichier absent du dossier envoie
        chercher ce qui n'existe pas."""
        texte = _phrase()
        for script in (SERVEUR, POSTE, PLANIFIER, OUVERTURE):
            assert script.name in texte, script.name

    def test_la_recuperation_des_donnees_vient_en_premier(self):
        """C'est la seule étape irréversible : elle doit être lue AVANT
        d'installer quoi que ce soit, pas découverte à la fin."""
        texte = _phrase()
        assert "AVANT DE COMMENCER" in texte
        assert texte.index("stock_ferme.csv") < texte.index("ETAPE 1 ")
        assert "NE SUPPRIMEZ RIEN" in texte

    def test_elle_previent_du_piege_du_profil_reseau(self):
        """La règle de pare-feu ne s'applique pas sur un réseau « Public » :
        c'est la cause la plus fréquente d'un « j'ai pourtant ouvert le
        port »."""
        assert "show currentprofile" in _phrase()

    def test_elle_dit_comment_savoir_si_l_ip_est_deja_fixe(self):
        texte = _phrase()
        assert "DHCP active" in texte
        assert "Baux statiques" in texte

    def test_elle_signale_les_donnees_nominatives(self):
        """Le module 4 porte des noms de patients, et l'application n'a pas
        de mot de passe : cela se décide en connaissance de cause."""
        texte = _phrase()
        assert "NOMS DE PATIENTS" in texte
        assert "n'a PAS de mot de passe" in texte

    def test_le_guide_du_poste_isole_y_renvoie(self):
        """Qui ouvre INSTALLATION.txt pour équiper toute la pharmacie doit
        être redirigé, pas installer un poste isolé de plus."""
        simple = (RACINE / "INSTALLATION.txt").read_text(encoding="ascii")
        assert CONSIGNE.name in simple


class TestGuideImprimable:
    """Le PDF : une étape par page, avec des cases à cocher.

    Il ne remplace pas le texte brut, il répond à une autre situation : le
    .txt s'ouvre sans rien installer et se copie ; le PDF **s'imprime**, se
    coche, et se lit debout devant la machine sans perdre sa place au milieu
    d'une installation qui dure trois quarts d'heure.

    Le risque, avec deux documents : qu'ils divergent en silence. Ces tests
    comparent ce qui est vérifiable entre les deux.
    """

    def _texte_pdf(self) -> str:
        fitz = pytest.importorskip("pymupdf",
                                   reason="lecture PDF indisponible")
        if not GUIDE.is_file():
            pytest.fail("Guide-installation-serveur.pdf manquant")
        with fitz.open(GUIDE) as document:
            pages = [page.get_text() for page in document]
        return " ".join(" ".join(pages).split())

    def test_le_guide_est_livre_avec_le_dossier(self):
        """Comme pharmacie.ico : le poste de la pharmacie n'a pas forcément
        ReportLab pour le fabriquer."""
        assert GUIDE.is_file()
        assert GUIDE.read_bytes().startswith(b"%PDF")

    def test_une_page_par_etape(self):
        fitz = pytest.importorskip("pymupdf")
        with fitz.open(GUIDE) as document:
            pages = document.page_count
        # couverture + 10 étapes (dont l'étape 0) + quotidien + dépannage
        assert pages >= 13, f"{pages} pages : une étape s'est fait écraser"

    def test_les_dix_etapes_y_sont(self):
        texte = self._texte_pdf()
        assert "AVANT DE COMMENCER" in texte
        for numero in range(1, 10):
            assert f"ÉTAPE {numero}" in texte, f"ÉTAPE {numero} manquante"

    def test_il_dit_la_meme_chose_que_le_texte_brut(self):
        """Deux documents, une seule procédure. Les faits sur lesquels on se
        trompe le plus cher doivent figurer dans les deux."""
        pdf, txt = self._texte_pdf(), _phrase()
        for fait in ("lancer-serveur.bat", "creer-raccourci-poste.bat",
                     "planifier-maj-serveur.bat", "8501",
                     "show currentprofile", "Baux statiques",
                     "maj_serveur.log", "NOMS DE PATIENTS"):
            assert fait in pdf, f"« {fait} » absent du PDF"
            assert fait in txt, f"« {fait} » absent du texte brut"

    def test_la_recuperation_des_donnees_precede_l_installation(self):
        """Comme dans le texte brut : la seule étape irréversible se lit
        AVANT d'installer, pas après."""
        texte = self._texte_pdf()
        assert texte.index("stock_ferme.csv") < texte.index("ÉTAPE 1")
        assert "NE SUPPRIMEZ RIEN" in texte

    def test_la_commande_longue_est_annoncee_dans_son_encadre(self):
        """Imprimée, elle tient sur deux lignes. Sans ce rappel sous les
        yeux, on la recopie avec un retour à la ligne au milieu."""
        texte = self._texte_pdf()
        avant = texte.split("netsh advfirewall firewall add rule", 1)[0]
        assert "UNE SEULE LIGNE" in avant

    def test_aucun_emoji_ne_s_y_est_glisse(self):
        """Les polices PDF standard n'en ont pas le glyphe : ils sortiraient
        en carrés noirs à l'impression."""
        texte = self._texte_pdf()
        egares = {c for c in texte if ord(c) > 0x2100}
        assert not egares, f"caractères sans glyphe PDF : {egares}"

    def test_le_generateur_et_le_guide_livre_ne_divergent_pas(self, tmp_path):
        """Le PDF est versionné, mais il se régénère : si quelqu'un modifie
        le générateur sans relancer, les deux se contredisent."""
        pytest.importorskip("reportlab")
        pytest.importorskip("pymupdf")
        import importlib.util

        chemin = RACINE / "outils" / "creer_guide_serveur.py"
        spec = importlib.util.spec_from_file_location("gen_guide", chemin)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        refait = module.creer(tmp_path / "guide.pdf")

        import pymupdf
        with pymupdf.open(refait) as neuf, pymupdf.open(GUIDE) as livre:
            assert neuf.page_count == livre.page_count
            for numero, (a, b) in enumerate(zip(neuf, livre), 1):
                assert " ".join(a.get_text().split()) == \
                       " ".join(b.get_text().split()), (
                    f"page {numero} : relancez "
                    "« python outils/creer_guide_serveur.py »")


class TestLiensDuReadme:
    """Les renvois internes doivent mener quelque part.

    Un lien mort dans une procédure d'installation est pire qu'une absence
    de lien : on clique, il ne se passe rien, et on croit avoir manqué une
    étape. Le cas réellement rencontré : le sélecteur de variante d'un
    emoji (U+FE0F) resté dans l'ancre d'un titre — invisible à la lecture.
    """

    def _ancre(self, titre: str) -> str:
        """Ancre telle que GitHub la fabrique : minuscules, ponctuation
        retirée (emoji compris), espaces en tirets, accents conservés."""
        nu = "".join(c for c in titre.strip().lower()
                     if c.isalnum() or c in " -_")
        return "#" + nu.replace(" ", "-")

    def test_aucun_renvoi_ne_pointe_dans_le_vide(self):
        import re
        texte = README.read_text(encoding="utf-8")
        ancres = {self._ancre(t)
                  for t in re.findall(r"^#{2,4} (.+)$", texte, re.M)}
        liens = re.findall(r"\]\((#[^)]*)\)", texte)
        assert liens, "aucun renvoi trouvé : le test ne vérifierait rien"
        casses = [l for l in liens if l not in ancres]
        assert not casses, f"renvois morts : {casses}"

    def test_la_procedure_serveur_est_une_liste_ordonnee_complete(self):
        """Elle doit se suffire à elle-même : quelqu'un qui la déroule sans
        rien lire d'autre doit arriver au bout avec une pharmacie qui
        marche — mise à jour et récupération des données comprises."""
        texte = README.read_text(encoding="utf-8")
        procedure = texte.split("### La procédure complète", 1)[1]
        procedure = procedure.split("\n#### ", 1)[0]
        for attendu in ("lancer-serveur.bat", "port 8501", "IP fixe",
                        "veille", "planifier-maj-serveur.bat",
                        "creer-raccourci-poste.bat", "récupérer ses"):
            assert attendu in procedure, (
                f"« {attendu} » manque à la procédure ordonnée")


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

    def test_le_readme_dit_comment_savoir_si_l_ip_est_deja_fixe(self):
        """Une réservation dans la box donne toujours la même adresse tout
        en passant par le DHCP : « DHCP activé : Oui » ne prouve donc pas
        que l'adresse bouge. Sans cette nuance, on refait un réglage déjà
        fait — ou on croit à tort être tranquille."""
        texte = README.read_text(encoding="utf-8")
        for attendu in ("DHCP activé", "Baux statiques", "sans** réservation"):
            assert attendu in texte, f"« {attendu} » absent du README"

    def test_le_readme_dit_comment_reparer_une_adresse_changee(self):
        """Les icônes des postes sont du texte : personne ne doit croire
        qu'il faut tout réinstaller."""
        texte = README.read_text(encoding="utf-8")
        assert "Pharmacie.url" in texte and "Bloc-notes" in texte

    def test_le_readme_explique_la_mise_a_jour_du_serveur(self):
        """C'est le point sur lequel une pharmacie peut rester bloquée des
        mois sans s'en apercevoir : rien ne signale qu'on ne se met plus à
        jour, sinon un bandeau que personne ne lit deux fois."""
        texte = README.read_text(encoding="utf-8")
        for attendu in ("planifier-maj-serveur.bat",
                        "mettre-a-jour-serveur.bat",
                        "05:00",
                        "maj_serveur.log",
                        "session Windows du serveur doit rester ouverte",
                        "redémarre l'application"):
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
