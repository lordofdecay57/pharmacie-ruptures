# -*- coding: utf-8 -*-
"""L'utilitaire s'ouvre tout seul le matin, sur chaque poste.

Demande de la pharmacie : à 08:00, heure de Nouméa, l'écran du matin
(péremptions, commandes à facturer, commandes à passer) doit être là
**avant** qu'on y pense — pas après, quand la journée a commencé.

Deux scripts, et toute la difficulté est dans le second :

- `planifier-ouverture-poste.bat` pose la tâche Windows. À lancer une
  fois par poste, depuis le dossier partagé, comme
  `creer-raccourci-poste.bat` : Windows ne connaît que les tâches de la
  machine où on les crée, il n'y a pas de réglage central.
- `ouvrir-le-matin.bat` est ce que la tâche exécute.

Trois pièges que ces tests gardent :

1. **Une tâche « tous les jours à 08:00 » ne part jamais** sur un poste
   allumé à 08h10 — c'est-à-dire le cas ordinaire d'une officine. D'où la
   répétition de rattrapage.
2. **La répétition rouvrirait l'écran tous les quarts d'heure** au milieu
   du travail. D'où le témoin « déjà ouvert aujourd'hui », qui doit être
   local au poste : posé sur le partage, le premier poste ouvert priverait
   tous les autres.
3. **Le serveur peut encore démarrer à 08:00.** Ouvrir le navigateur sur
   un serveur endormi n'affiche qu'une page d'erreur — et le témoin du
   jour empêcherait ensuite toute nouvelle tentative.

Personne n'exécute ces scripts ici : c'est cmd qui les interprète, sur un
Windows qu'on n'a pas.
"""

from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
PLANIFIER = RACINE / "planifier-ouverture-poste.bat"
OUVRIR = RACINE / "ouvrir-le-matin.bat"

#: L'heure demandée par la pharmacie, en clair et en un seul endroit.
HEURE = "08:00"


def _texte(chemin: Path) -> str:
    return chemin.read_text(encoding="ascii")


def _instructions(chemin: Path) -> list:
    """Les lignes que cmd exécute : sans les REM ni le vide.

    Les commentaires expliquent les pièges — les inclure ferait échouer
    les tests sur leur propre explication.
    """
    return [ligne for ligne in _texte(chemin).splitlines()
            if ligne.strip() and not ligne.strip().upper().startswith("REM")]


class TestScriptsPresents:
    @pytest.mark.parametrize("chemin", [PLANIFIER, OUVRIR])
    def test_le_script_existe(self, chemin):
        assert chemin.is_file(), f"{chemin.name} manquant à la racine"

    @pytest.mark.parametrize("chemin", [PLANIFIER, OUVRIR])
    def test_sans_accent(self, chemin):
        """cmd lit ces fichiers dans une page de codes qui n'est pas celle
        de l'éditeur : un « é » y devient un caractère illisible."""
        try:
            _texte(chemin)
        except UnicodeDecodeError as erreur:
            pytest.fail(f"{chemin.name} : caractère non ASCII "
                        f"(position {erreur.start})")

    def test_la_tache_lance_bien_le_script_livre(self):
        """Une tâche qui pointe sur un fichier absent se crée sans broncher
        et échoue chaque matin en silence."""
        assert "ouvrir-le-matin.bat" in _texte(PLANIFIER)
        assert OUVRIR.is_file()


class TestPlanification:
    def test_huit_heures_par_defaut(self):
        """L'heure demandée par la pharmacie doit être celle qu'on obtient
        sans rien taper : personne ne lira le mode d'emploi."""
        assert f'if not defined HEURE set "HEURE={HEURE}"' in _texte(PLANIFIER)

    def test_une_autre_heure_reste_possible(self):
        assert 'set "HEURE=%~1"' in _texte(PLANIFIER)

    def test_la_tache_est_quotidienne_a_l_heure_dite(self):
        ligne = next(l for l in _instructions(PLANIFIER)
                     if l.startswith("schtasks /create"))
        assert "/sc daily" in ligne
        assert "/st %HEURE%" in ligne

    def test_le_poste_allume_en_retard_est_rattrape(self):
        """LE point du dispositif. Une tâche « tous les jours à 08:00 »
        sans répétition ne part jamais sur un poste allumé à 08h10 —
        et c'est le cas ordinaire d'une officine, pas l'exception."""
        ligne = next(l for l in _instructions(PLANIFIER)
                     if l.startswith("schtasks /create"))
        assert "/ri %REPETITION%" in ligne, "aucun rattrapage"
        assert "/du %DUREE%" in ligne, "rattrapage sans fin"

    def test_le_rattrapage_couvre_la_matinee_et_s_arrete(self):
        """À midi, personne n'a plus besoin qu'on lui ouvre son écran du
        matin : la tâche doit renoncer, pas insister toute la journée."""
        texte = _texte(PLANIFIER)
        assert 'set "REPETITION=15"' in texte
        assert 'set "DUREE=04:00"' in texte

    def test_la_tache_tourne_dans_la_session_de_l_utilisateur(self):
        """Lancée par SYSTEM, elle ouvrirait le navigateur dans une session
        invisible. C'est aussi ce qui évite de devoir être administrateur
        pour poser la tâche."""
        ligne = next(l for l in _instructions(PLANIFIER)
                     if l.startswith("schtasks /create"))
        assert "/ru" not in ligne

    def test_elle_sait_se_retirer(self):
        texte = _texte(PLANIFIER)
        assert '"%~1"=="/supprimer"' in texte
        assert "schtasks /delete" in texte

    def test_la_tache_creee_est_affichee(self):
        """Une ligne « c'est fait » ne prouve rien ; la fiche de Windows
        si. Le même choix que pour la mise à jour du serveur."""
        assert "schtasks /query" in _texte(PLANIFIER)

    def test_il_dit_qu_il_faut_le_refaire_sur_chaque_poste(self):
        """Il n'y a pas de réglage central : une tâche n'existe que sur la
        machine où on la crée. Le croire fait de l'ouverture du matin
        quelque chose qui « ne marche que sur un poste », sans qu'on
        comprenne pourquoi."""
        assert "SUR CHAQUE POSTE" in _texte(PLANIFIER)


class TestFuseauHoraire:
    """« 08:00 heure de Calédonie » n'existe pas pour Windows.

    Windows ne connaît que le fuseau réglé sur la machine. Un poste réglé
    ailleurs partirait à côté sans que rien ne le signale — et il faudrait
    des mois pour s'en apercevoir.
    """

    def test_le_fuseau_du_poste_est_montre(self):
        assert "tzutil /g" in _texte(PLANIFIER)

    def test_l_heure_courante_est_montree(self):
        """Le nom du fuseau ne parle à personne ; l'heure affichée, si.
        C'est elle qui permet de dire « oui, c'est bien l'heure d'ici »."""
        assert "%TIME:~0,5%" in _texte(PLANIFIER)

    def test_le_fuseau_de_noumea_est_nomme(self):
        """Nouvelle-Calédonie = « Central Pacific Standard Time » (UTC+11).
        Sans le nom exact, la vérification ne peut pas se faire."""
        texte = _texte(PLANIFIER)
        assert "Central Pacific Standard Time" in texte
        assert "UTC+11" in texte

    def test_un_autre_fuseau_declenche_un_avertissement(self):
        texte = _texte(PLANIFIER)
        assert 'if /i "%FUSEAU%"=="Central Pacific Standard Time"' in texte
        assert "[ATTENTION]" in texte


class TestOuvertureUneSeuleFoisParJour:
    """La répétition du quart d'heure ne doit pas devenir un harcèlement."""

    def test_un_temoin_porte_la_date_du_jour(self):
        texte = _texte(OUVRIR)
        assert 'set "AUJOURDHUI=%DATE%"' in texte
        assert '"%DEJA%"=="%AUJOURDHUI%"' in texte

    def test_le_temoin_est_local_au_poste(self):
        """Posé dans le dossier partagé, le premier poste ouvert priverait
        TOUS les autres de leur ouverture du matin."""
        texte = _texte(OUVRIR)
        assert 'set "DOSSIER=%LOCALAPPDATA%\\Pharmacie"' in texte
        marque = next(l for l in _instructions(OUVRIR)
                      if l.startswith('set "MARQUE='))
        assert "%~dp0" not in marque, (
            "le témoin est sur le partage : un poste priverait les autres")

    def test_le_temoin_n_est_ecrit_qu_apres_une_ouverture_reussie(self):
        """Écrit d'avance, il condamnerait la journée sur un simple échec
        d'ouverture."""
        texte = _texte(OUVRIR)
        ecriture = texte.index('> "%MARQUE%" echo %AUJOURDHUI%')
        assert texte.index(":marquer") < ecriture
        # Les deux chemins d'échec sortent AVANT d'atteindre :marquer.
        for echec in (":pas_encore_pret", ":rien_a_lancer"):
            assert texte.index(echec) > ecriture, echec

    def test_la_lecture_du_temoin_n_est_pas_accrochee_a_un_if(self):
        """Piège classique de cmd : une redirection sur un « if » d'une
        seule ligne est traitée AVANT le test, et se plaint quand le
        fichier n'est pas là — c'est-à-dire le tout premier matin."""
        for ligne in _texte(OUVRIR).splitlines():
            nu = ligne.strip().lower()
            if nu.startswith("if ") and "set /p" in nu and "<" in nu:
                pytest.fail(f"redirection accrochée à un « if » : {ligne}")


class TestQuoiOuvrir:
    """Deux installations, deux gestes du matin différents."""

    def test_l_adresse_du_serveur_tranche(self):
        """`adresse-serveur.txt` est écrit par `lancer-serveur.bat` : sa
        présence dit à elle seule si l'application tourne ailleurs."""
        assert "adresse-serveur.txt" in _texte(OUVRIR)

    def test_avec_serveur_on_ouvre_le_navigateur(self):
        texte = _texte(OUVRIR)
        assert 'start "" "%ADRESSE%"' in texte
        # Le fichier peut porter "192.168.1.10" comme l'adresse complète
        # recopiée depuis le navigateur : les deux doivent marcher.
        assert 'findstr /b /i "http"' in texte
        assert 'set "ADRESSE=http://%ADRESSE%:8501"' in texte

    def test_sans_serveur_on_demarre_l_application(self):
        assert 'start "" "%~dp0lancer.bat"' in _texte(OUVRIR)

    def test_lancer_bat_est_demarre_detache(self):
        """`lancer.bat` garde la main tant que l'application tourne : appelé
        directement, il laisserait la tâche planifiée ouverte derrière lui
        toute la journée, et Windows finirait par la tuer."""
        ligne = next(l for l in _instructions(OUVRIR)
                     if "lancer.bat" in l and not l.startswith("if "))
        assert ligne.startswith('start ""'), ligne


class TestServeurPasEncorePret:
    """À 08:00, le serveur peut encore démarrer."""

    def test_on_verifie_que_le_serveur_repond(self):
        texte = _texte(OUVRIR)
        assert "curl -s -o nul --max-time 5" in texte

    def test_un_serveur_absent_ne_consomme_pas_la_journee(self):
        """Ouvrir sur un serveur endormi afficherait une page d'erreur, et
        le témoin du jour empêcherait ensuite toute nouvelle tentative.
        On ne marque donc rien : la répétition du quart d'heure ouvrira
        dès que le serveur répondra."""
        texte = _texte(OUVRIR)
        assert "if errorlevel 1 goto pas_encore_pret" in texte
        bloc = texte[texte.index(":pas_encore_pret"):]
        assert '> "%MARQUE%"' not in bloc

    def test_curl_absent_n_empeche_pas_l_ouverture(self):
        """curl est livré avec Windows depuis 2018 ; sur un poste plus
        ancien, mieux vaut ouvrir sans vérifier que ne jamais rien
        ouvrir."""
        texte = _texte(OUVRIR)
        assert "where curl" in texte
        assert "if errorlevel 1 goto ouvrir_adresse" in texte


class TestExecutionSansPersonne:
    """La tâche part sans que personne ne regarde l'écran."""

    def test_aucune_attente_de_touche(self):
        """Un `pause` laisserait une fenêtre suspendue jusqu'au soir, et
        l'ouverture du lendemain se ferait derrière elle."""
        fautives = [l for l in _instructions(OUVRIR)
                    if l.strip().lower() == "pause"]
        assert not fautives, "ouvrir-le-matin.bat attend une touche"

    @pytest.mark.parametrize("etiquette", [":deja_ouvert", ":pas_encore_pret",
                                           ":rien_a_lancer"])
    def test_on_ne_tombe_pas_dans_les_sorties(self, etiquette):
        """Ces étiquettes sont des fins de parcours : y arriver par le haut
        ferait marquer la journée comme ouverte alors qu'elle ne l'est
        pas, ou renvoyer un échec après un succès."""
        lignes = _texte(OUVRIR).splitlines()
        indice = lignes.index(etiquette)
        avant = [l.strip() for l in lignes[:indice] if l.strip()][-1]
        assert avant.startswith(("exit /b", "goto ")), (
            f"on tombe dans {etiquette} après « {avant} »")
