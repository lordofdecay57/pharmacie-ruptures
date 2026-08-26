# -*- coding: utf-8 -*-
"""Un poste ne met pas à jour le dossier pendant que les autres l'utilisent.

La pharmacie a posé l'utilitaire sur le disque du serveur et le partage
aux postes : chacun lance **son propre** Streamlit sur les **mêmes**
fichiers. Or `maj_auto` vérifiait qu'aucune application ne tournait —
sur `127.0.0.1`, c'est-à-dire chez elle seule.

Le scénario, entièrement plausible un matin ordinaire :

1. le comptoir 1 ouvre l'application à 07h55 ;
2. le comptoir 2 la lance à 08h05. Son port 8501 à lui est libre, donc
   `maj_auto` se croit seul, télécharge la nouvelle version et **remplace
   les fichiers du dossier partagé** ;
3. Streamlit, chez le comptoir 1, recharge ses modules à chaud — et
   l'écran part en erreur au milieu d'un scan.

Chaque lancement dépose donc un marqueur à son nom, et le retire en
partant. Le marqueur **périme** au bout d'une journée : un poste éteint
brutalement laisse le sien, et sans péremption une seule coupure de
courant figerait la pharmacie sur sa version pour toujours.
"""

import time
from pathlib import Path

import pytest

import maj_auto
import presence

RACINE = Path(__file__).resolve().parent.parent

#: Les scripts qui démarrent Streamlit au PREMIER PLAN : ils vivent le
#: temps de la session, donc ils peuvent rendre leur place en partant.
LANCEURS = ["lancer.bat", "lancer-serveur.bat", "mettre-a-jour.bat",
            "mettre-a-jour-serveur.bat"]

HEURE = 3600.0


class TestNomDuPoste:
    def test_il_y_a_toujours_un_nom(self, monkeypatch):
        """Il apparaît dans « utilisé par … » : sans nom, le message ne
        dirait pas à qui aller demander de fermer sa fenêtre."""
        assert presence.nom_du_poste()

    def test_le_nom_windows_l_emporte(self, monkeypatch):
        monkeypatch.setenv("COMPUTERNAME", "COMPTOIR-2")
        assert presence.nom_du_poste() == "COMPTOIR-2"

    def test_un_nom_hostile_ne_sort_pas_du_dossier(self, monkeypatch, tmp_path):
        """Le nom vient de l'environnement et sert à fabriquer un chemin :
        un « .. » y écrirait ailleurs que dans le dossier prévu."""
        monkeypatch.setenv("COMPUTERNAME", "../../evade")
        chemin = presence.marqueur(tmp_path)
        assert presence.dossier_marqueurs(tmp_path) == chemin.parent
        assert ".." not in chemin.name

    def test_un_nom_vide_a_un_repli(self, monkeypatch):
        monkeypatch.setenv("COMPUTERNAME", "   ")
        monkeypatch.setattr(presence.platform, "node", lambda: "")
        monkeypatch.setattr(presence.socket, "gethostname", lambda: "")
        assert presence.nom_du_poste() == "poste"


class TestEntrerEtSortir:
    def test_un_dossier_neuf_n_a_personne(self, tmp_path):
        assert presence.postes_actifs(tmp_path) == []

    def test_entrer_se_voit(self, tmp_path):
        presence.entrer(tmp_path, "COMPTOIR-1")
        assert presence.postes_actifs(tmp_path) == ["COMPTOIR-1"]

    def test_sortir_rend_la_place(self, tmp_path):
        presence.entrer(tmp_path, "COMPTOIR-1")
        presence.sortir(tmp_path, "COMPTOIR-1")
        assert presence.postes_actifs(tmp_path) == []

    def test_plusieurs_postes_coexistent(self, tmp_path):
        for nom in ("COMPTOIR-2", "COMPTOIR-1", "BUREAU"):
            presence.entrer(tmp_path, nom)
        # Triés : le message « utilisé par … » doit être stable d'un
        # matin à l'autre, sinon on croit que la liste a changé.
        assert presence.postes_actifs(tmp_path) == ["BUREAU", "COMPTOIR-1",
                                                    "COMPTOIR-2"]

    def test_un_poste_qui_part_ne_libere_que_lui(self, tmp_path):
        presence.entrer(tmp_path, "COMPTOIR-1")
        presence.entrer(tmp_path, "COMPTOIR-2")
        presence.sortir(tmp_path, "COMPTOIR-1")
        assert presence.postes_actifs(tmp_path) == ["COMPTOIR-2"]

    def test_relancer_deux_fois_ne_cree_pas_deux_marqueurs(self, tmp_path):
        presence.entrer(tmp_path, "COMPTOIR-1")
        presence.entrer(tmp_path, "COMPTOIR-1")
        assert presence.postes_actifs(tmp_path) == ["COMPTOIR-1"]

    def test_sortir_sans_etre_entre_ne_leve_pas(self, tmp_path):
        """Une fenêtre fermée deux fois, un script relancé : ça ne doit
        surtout pas faire échouer le lancement."""
        assert presence.sortir(tmp_path, "FANTOME") is False

    def test_un_dossier_en_lecture_seule_ne_leve_pas(self, tmp_path,
                                                     monkeypatch):
        """Partage en lecture seule, disque plein, réseau coupé : tant pis
        pour la protection, l'application doit s'ouvrir."""
        def refuser(*a, **kw):
            raise OSError("lecture seule")
        monkeypatch.setattr(presence.Path, "mkdir", refuser)
        assert presence.entrer(tmp_path, "COMPTOIR-1") is False


class TestPeremption:
    """Un poste débranché ne doit pas figer la pharmacie pour toujours."""

    def _vieillir(self, tmp_path, poste, heures):
        chemin = presence.marqueur(tmp_path, poste)
        quand = time.time() - heures * HEURE
        import os
        os.utime(chemin, (quand, quand))

    def test_un_marqueur_du_jour_compte(self, tmp_path):
        presence.entrer(tmp_path, "COMPTOIR-1")
        self._vieillir(tmp_path, "COMPTOIR-1", 8)
        assert presence.postes_actifs(tmp_path) == ["COMPTOIR-1"]

    def test_un_marqueur_abandonne_ne_bloque_plus(self, tmp_path):
        """Sans cela, une seule coupure de courant suffirait à ce que la
        pharmacie ne se mette plus JAMAIS à jour — et personne ne saurait
        pourquoi."""
        presence.entrer(tmp_path, "COMPTOIR-1")
        self._vieillir(tmp_path, "COMPTOIR-1", presence.DUREE_MAX_H + 1)
        assert presence.postes_actifs(tmp_path) == []

    def test_la_duree_couvre_une_journee_de_travail(self):
        """Une session ouverte de 8 h à 19 h ne doit jamais être prise pour
        un marqueur abandonné."""
        assert presence.DUREE_MAX_H >= 12

    def test_le_menage_efface_les_abandonnes(self, tmp_path):
        presence.entrer(tmp_path, "PARTI")
        presence.entrer(tmp_path, "PRESENT")
        self._vieillir(tmp_path, "PARTI", presence.DUREE_MAX_H + 1)
        assert presence.purger(tmp_path) == 1
        assert presence.postes_actifs(tmp_path) == ["PRESENT"]
        assert not presence.marqueur(tmp_path, "PARTI").exists()

    def test_c_est_la_date_du_fichier_qui_fait_foi(self, tmp_path):
        """Pas son contenu : un poste dont l'horloge est fausse mentirait
        sur l'heure, la date posée par le système, non."""
        presence.entrer(tmp_path, "COMPTOIR-1")
        chemin = presence.marqueur(tmp_path, "COMPTOIR-1")
        chemin.write_text("1999-01-01 00:00:00", encoding="utf-8")
        assert presence.postes_actifs(tmp_path) == ["COMPTOIR-1"]


class TestMiseAJourReportee:
    """Le garde-fou, vu depuis maj_auto."""

    def test_un_poste_voisin_reporte_la_mise_a_jour(self, tmp_path,
                                                    monkeypatch):
        """LE scénario : le comptoir 2 démarre à 08h05, son port 8501 à lui
        est libre, et il remplacerait le code sous le comptoir 1."""
        monkeypatch.setattr(maj_auto, "application_en_cours", lambda: False)
        presence.entrer(tmp_path, "COMPTOIR-1")
        resultat, message = maj_auto.executer(tmp_path)
        assert resultat == maj_auto.APPLICATION_EN_COURS
        assert "COMPTOIR-1" in message, (
            "le message doit NOMMER le poste : sinon on ne sait pas à qui "
            "demander de fermer sa fenêtre")

    def test_sans_personne_la_mise_a_jour_continue(self, tmp_path,
                                                   monkeypatch):
        """Le premier poste du matin doit pouvoir mettre à jour : c'est le
        seul moment où c'est sans danger."""
        monkeypatch.setattr(maj_auto, "application_en_cours", lambda: False)
        monkeypatch.setattr(maj_auto, "version_publiee", lambda *a, **k: "")
        resultat, _ = maj_auto.executer(tmp_path)
        assert resultat == maj_auto.INJOIGNABLE

    def test_un_marqueur_abandonne_ne_reporte_rien(self, tmp_path,
                                                   monkeypatch):
        monkeypatch.setattr(maj_auto, "application_en_cours", lambda: False)
        monkeypatch.setattr(maj_auto, "version_publiee", lambda *a, **k: "")
        presence.entrer(tmp_path, "PARTI")
        chemin = presence.marqueur(tmp_path, "PARTI")
        quand = time.time() - (presence.DUREE_MAX_H + 1) * HEURE
        import os
        os.utime(chemin, (quand, quand))
        resultat, _ = maj_auto.executer(tmp_path)
        assert resultat == maj_auto.INJOIGNABLE


class TestCablageDesLanceurs:
    """Un module que personne n'appelle ne protège rien."""

    @pytest.mark.parametrize("nom", LANCEURS)
    def test_le_lanceur_annonce_et_rend_sa_place(self, nom):
        texte = (RACINE / nom).read_text(encoding="ascii")
        assert "%PY% presence.py --entrer" in texte, f"{nom} n'annonce rien"
        assert "%PY% presence.py --sortir" in texte, (
            f"{nom} ne rend jamais sa place : la mise à jour du lendemain "
            f"serait bloquée jusqu'à péremption")

    @pytest.mark.parametrize("nom", LANCEURS)
    def test_la_place_est_prise_avant_streamlit_et_rendue_apres(self, nom):
        lignes = [l.strip() for l in
                  (RACINE / nom).read_text(encoding="ascii").splitlines()]
        entrer = lignes.index("%PY% presence.py --entrer")
        sortir = lignes.index("%PY% presence.py --sortir")
        streamlit = next(i for i, l in enumerate(lignes)
                         if l.startswith("%PY% -m streamlit run"))
        assert entrer < streamlit < sortir, (
            f"{nom} : l'ordre entrer / streamlit / sortir n'est pas tenu")

    def test_la_mise_a_jour_precede_l_annonce(self):
        """`maj_auto` tourne AVANT que ce poste ne prenne sa place : sinon
        il se verrait lui-même et ne mettrait plus jamais à jour."""
        for nom in ("lancer.bat", "lancer-serveur.bat"):
            lignes = [l.strip() for l in
                      (RACINE / nom).read_text(encoding="ascii").splitlines()]
            maj = next(i for i, l in enumerate(lignes) if "maj_auto.py" in l)
            entrer = lignes.index("%PY% presence.py --entrer")
            assert maj < entrer, nom

    def test_le_serveur_detache_ne_prend_pas_de_place(self):
        """Cette instance-là vit indéfiniment : elle ne rendrait jamais sa
        place. Elle n'en a pas besoin — la mise à jour d'un serveur passe
        par mettre-a-jour-serveur.bat, qui ne consulte pas les marqueurs."""
        ligne = next(l for l in (RACINE / "mettre-a-jour-serveur.bat")
                     .read_text(encoding="ascii").splitlines()
                     if l.startswith("start "))
        assert "presence.py" not in ligne


class TestAutresPostes:
    """« Est-ce que je vais casser l'écran de quelqu'un d'autre ? »

    C'est la question de la mise à jour MANUELLE — celle qu'un humain
    déclenche. Sa propre application sera de toute façon redémarrée : se
    compter soi-même ferait apparaître l'avertissement à chaque fois, et
    on apprendrait à passer outre sans le lire.
    """

    def test_on_ne_se_compte_pas_soi_meme(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COMPUTERNAME", "MOI")
        presence.entrer(tmp_path)
        assert presence.postes_actifs(tmp_path) == ["MOI"]
        assert presence.autres_postes(tmp_path) == []

    def test_les_voisins_sont_comptes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COMPUTERNAME", "MOI")
        presence.entrer(tmp_path)
        presence.entrer(tmp_path, "COMPTOIR-1")
        assert presence.autres_postes(tmp_path) == ["COMPTOIR-1"]

    def test_un_voisin_abandonne_ne_compte_pas(self, tmp_path, monkeypatch):
        import os
        monkeypatch.setenv("COMPUTERNAME", "MOI")
        presence.entrer(tmp_path, "PARTI")
        quand = time.time() - (presence.DUREE_MAX_H + 1) * HEURE
        os.utime(presence.marqueur(tmp_path, "PARTI"), (quand, quand))
        assert presence.autres_postes(tmp_path) == []


class TestMiseAJourManuelle:
    """La pharmacie installe chaque poste EN LANÇANT mettre-a-jour.bat.

    Ce script réécrit le dossier partagé sans rien demander : lancé à
    10 heures depuis un poste, il coupe l'écran de tous les autres. La
    mise à jour automatique s'en garde toute seule ; ici, c'est quelqu'un
    qui décide — on lui montre donc qui il va interrompre.
    """

    MANUELS = ["mettre-a-jour.bat", "mettre-a-jour-serveur.bat"]

    @pytest.mark.parametrize("nom", MANUELS)
    def test_il_regarde_qui_travaille_avant_de_reecrire(self, nom):
        texte = (RACINE / nom).read_text(encoding="ascii")
        assert "presence.py --autres" in texte, (
            f"{nom} réécrit le dossier partagé sans regarder qui l'utilise")

    @pytest.mark.parametrize("nom", MANUELS)
    def test_le_controle_precede_la_copie(self, nom):
        """Prévenir après avoir écrasé les fichiers ne sert plus à rien."""
        lignes = [l.strip() for l in
                  (RACINE / nom).read_text(encoding="ascii").splitlines()]
        controle = next(i for i, l in enumerate(lignes)
                        if "presence.py --autres" in l)
        copie = next(i for i, l in enumerate(lignes)
                     if l.startswith("robocopy "))
        assert controle < copie, f"{nom} : l'avertissement arrive trop tard"

    @pytest.mark.parametrize("nom", MANUELS)
    def test_les_postes_sont_nommes_pas_seulement_comptes(self, nom):
        """« Occupé » n'aide personne. « COMPTOIR-1 » dit à qui aller
        demander de fermer sa fenêtre."""
        lignes = [l.strip() for l in
                  (RACINE / nom).read_text(encoding="ascii").splitlines()]
        affichages = [l for l in lignes
                      if l.startswith("%PY% presence.py --autres")]
        assert affichages, f"{nom} n'affiche jamais la liste"

    def test_le_dossier_libre_ne_pose_aucune_question(self):
        """Le cas courant — un poste isolé, personne d'autre — doit rester
        un simple double-clic."""
        for nom in self.MANUELS:
            texte = (RACINE / nom).read_text(encoding="ascii")
            saut = "if defined AUTRES goto postes_ouverts" in texte \
                or "if not defined AUTRES goto dossier_libre" in texte
            assert saut, f"{nom} : la question est posée dans tous les cas"

    def test_la_nuit_le_serveur_renonce_au_lieu_de_demander(self):
        """Personne n'est devant : la question resterait sans réponse
        jusqu'au matin, application arrêtée. On renonce, on le consigne,
        et la nuit suivante réessaiera."""
        texte = (RACINE / "mettre-a-jour-serveur.bat").read_text(
            encoding="ascii")
        avertissement = texte.index("presence.py --autres")
        branche = texte.index("if defined SILENCE goto echec", avertissement)
        question = texte.index("set /p REPONSE", avertissement)
        assert branche < question, (
            "la question est posée avant que le mode silencieux ne sorte")


class TestCopieQuiNeSeFigePas:
    """« [3/5] Installation des fichiers... » et plus rien, indéfiniment.

    Vu en officine, sur un poste qu'il fallait installer. Trois causes
    empilées, dont aucune ne s'annonçait :

    1. `robocopy` réessaie **un million de fois**, trente secondes entre
       chaque, par défaut. Un seul fichier verrouillé, et c'est près d'un
       an d'attente.
    2. `>nul` masquait chaque tentative : l'écran restait figé sur une
       ligne qui laissait croire à une copie en cours.
    3. L'application était fermée à l'étape **suivante** — on remplaçait
       donc les fichiers pendant qu'elle tournait encore.

    Et le fichier verrouillé avait un nom : `pharmacie.ico`. Chaque
    raccourci du Bureau pointait dessus **sur le partage**, et
    l'Explorateur le garde ouvert.
    """

    MANUELS = ["mettre-a-jour.bat", "mettre-a-jour-serveur.bat"]

    @pytest.mark.parametrize("nom", MANUELS)
    def test_la_copie_renonce_au_lieu_de_reessayer_un_an(self, nom):
        ligne = next(l for l in (RACINE / nom).read_text(encoding="ascii")
                     .splitlines() if l.startswith("robocopy "))
        assert "/R:" in ligne, (
            "sans /R, robocopy reessaie 1 000 000 de fois : pres d'un an "
            "d'attente sur un seul fichier verrouille")
        assert "/W:" in ligne, "sans /W, trente secondes entre chaque essai"
        essais = int(ligne.split("/R:")[1].split()[0])
        attente = int(ligne.split("/W:")[1].split()[0])
        assert essais * attente <= 60, (
            f"{essais} essais x {attente} s : personne n'attend devant un "
            f"ecran fige aussi longtemps")

    @pytest.mark.parametrize("nom", MANUELS)
    def test_l_application_est_fermee_avant_la_copie(self, nom):
        """On ne remplace pas les fichiers d'un programme qui tourne :
        robocopy n'y arrive pas, et réessaie."""
        lignes = [l.strip() for l in
                  (RACINE / nom).read_text(encoding="ascii").splitlines()]
        fermeture = next(i for i, l in enumerate(lignes)
                         if "Stop-Process" in l)
        copie = next(i for i, l in enumerate(lignes)
                     if l.startswith("robocopy "))
        assert fermeture < copie, (
            f"{nom} : la copie passe AVANT la fermeture — elle bute sur "
            f"les fichiers encore ouverts")

    @pytest.mark.parametrize("nom", MANUELS)
    def test_les_etapes_restent_numerotees_dans_l_ordre(self, nom):
        """L'écran annonce « [3/5] », « [4/5] » : deux blocs échangés sans
        renuméroter, et le compteur repart en arrière sous les yeux de
        quelqu'un qui attend."""
        # Seulement ce qui S'AFFICHE : les commentaires citent les
        # etapes, et les compter ferait echouer le test sur sa propre
        # explication.
        affichees = [l for l in
                     (RACINE / nom).read_text(encoding="ascii").splitlines()
                     if l.startswith(("echo  [", "call :dire \"["))]
        vus = [int(t.split("/")[0]) for l in affichees
               for t in l.split("[")[1:]
               if len(t) > 3 and t[1] == "/" and t[0].isdigit()]
        assert vus == sorted(vus), f"{nom} : compteur en arriere — {vus}"
        assert vus == list(range(1, len(vus) + 1)), vus

    def test_l_icone_du_bureau_ne_reste_pas_sur_le_partage(self):
        """C'est ELLE que l'Explorateur tenait ouverte, sur chaque poste
        équipé. Une mise à jour ne pouvait plus la remplacer."""
        texte = (RACINE / "creer-raccourci.bat").read_text(encoding="ascii")
        assert 'copy /y "%ICONE%" "%LOCAL_PHARMACIE%\\pharmacie.ico"' in texte
        derniere = [l for l in texte.splitlines()
                    if l.strip().startswith(('set "ICONE=',
                                             'if exist "%LOCAL_PHARMACIE%'))][-1]
        assert "%LOCAL_PHARMACIE%" in derniere, (
            "le raccourci pointe encore sur l'icone du partage")

    def test_l_echec_de_copie_nomme_la_cause_la_plus_probable(self):
        """« Copie impossible » tout court n'apprend rien à qui doit
        décider quoi fermer."""
        texte = (RACINE / "mettre-a-jour.bat").read_text(encoding="ascii")
        message = texte[texte.index("Copie des fichiers impossible"):][:600]
        assert "encore ouvert" in message
        assert "Rien n'a ete modifie" in message


class TestScriptsCorrigeablesADistance:
    """Un bug dans `mettre-a-jour.bat` était jusqu'ici incorrigible.

    Il s'excluait de sa propre copie — à raison, cmd relit un .bat au fil
    des lignes — mais AUSSI de celle de `maj_auto`, qui est du Python et
    ne l'exécute pas. Réparé dans le dépôt, il restait indéfiniment sur
    le disque de la pharmacie. C'est exactement ce qui s'est passé : le
    poste tournait encore sur une version affichant « [3/4] ».
    """

    def test_maj_auto_peut_corriger_les_scripts_de_mise_a_jour(self):
        assert "mettre-a-jour.bat" not in maj_auto.FICHIERS_PROTEGES
        assert "mettre-a-jour-serveur.bat" not in maj_auto.FICHIERS_PROTEGES

    def test_ils_continuent_de_s_exclure_de_leur_propre_copie(self):
        """Là, c'est cmd qui relit le fichier ligne à ligne pendant qu'il
        s'exécute : le remplacer sous ses pieds reste interdit."""
        for nom in ("mettre-a-jour.bat", "mettre-a-jour-serveur.bat"):
            ligne = next(l for l in (RACINE / nom).read_text(encoding="ascii")
                         .splitlines() if l.startswith("robocopy "))
            assert nom in ligne.split("/XF", 1)[1]

    def test_aucun_fichier_de_programme_n_est_protege(self):
        """Protéger du code, c'est se priver de pouvoir le réparer."""
        for nom in maj_auto.FICHIERS_PROTEGES:
            assert not nom.endswith((".bat", ".py", ".ico")), nom


class TestIsolation:
    def test_presence_n_importe_aucun_module_du_projet(self):
        """Il est appelé par maj_auto au démarrage du poste, avant que quoi
        que ce soit d'autre ne soit chargé : il doit tenir sur la
        bibliothèque standard seule."""
        import ast
        source = (RACINE / "presence.py").read_text(encoding="utf-8")
        modules = {n.name.split(".")[0]
                   for noeud in ast.walk(ast.parse(source))
                   if isinstance(noeud, ast.Import) for n in noeud.names}
        modules |= {noeud.module.split(".")[0]
                    for noeud in ast.walk(ast.parse(source))
                    if isinstance(noeud, ast.ImportFrom) and noeud.module}
        locaux = {p.stem for p in RACINE.glob("*.py")} - {"presence"}
        assert not (modules & locaux), sorted(modules & locaux)
        assert "streamlit" not in modules and "pandas" not in modules
