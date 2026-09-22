# -*- coding: utf-8 -*-
"""Tests du Module 5 — Location de matériel et ententes préalables CAFAT.

Ce que ce module promet, et qu'il faut donc éprouver :

- une **échéance juste**. Le 31 janvier plus un mois n'est pas le
  31 février, et une entente de six mois qui expire cinq jours trop tôt
  laisse un patient sans prise en charge ;
- une **alerte qui arrive à temps** — trente jours, le temps de revoir le
  médecin et d'attendre la réponse de la caisse ;
- des **mois de retard comptés**. Une location facturée en janvier et
  oubliée jusqu'en avril, ce sont trois mois dus, pas un : afficher « à
  facturer » sans le nombre ferait encaisser un mois et croire le dossier
  à jour.

Rien ici n'invente de règle CAFAT : la durée de validité est **saisie par
dossier**, la caisse l'accordant au cas par cas selon le matériel.
"""

import ast
import pathlib
from datetime import date, timedelta

import pandas as pd
import pytest

import location as loc

AUJOURDHUI = date(2026, 9, 18)


def _dossier(**kw):
    base = {"Patient": "Mme DUPONT", "Matériel": "Lit médicalisé",
            "Début de location": "2026-01-15", "Entente préalable": "2026-03-01",
            "Validité (mois)": 6, "Dernière facturation": "2026-09-01",
            "Notes": ""}
    base.update(kw)
    return pd.DataFrame([base], columns=loc.COLONNES_DOSSIER)


# ---------------------------------------------------------------------------
# Les dates, d'abord : tout le reste en dépend
# ---------------------------------------------------------------------------

class TestAjouterMois:
    """Le calcul dont dépendent l'échéance ET la facturation."""

    @pytest.mark.parametrize("depart,mois,attendu", [
        (date(2026, 3, 1), 6, date(2026, 9, 1)),
        (date(2026, 1, 31), 1, date(2026, 2, 28)),   # février n'a pas 31 jours
        (date(2028, 1, 31), 1, date(2028, 2, 29)),   # …et 2028 est bissextile
        (date(2026, 8, 31), 1, date(2026, 9, 30)),
        (date(2026, 12, 15), 1, date(2027, 1, 15)),  # passage d'année
        (date(2026, 7, 10), 24, date(2028, 7, 10)),
    ])
    def test_on_reste_dans_le_calendrier(self, depart, mois, attendu):
        assert loc.ajouter_mois(depart, mois) == attendu

    def test_trente_jours_ne_suffiraient_pas(self):
        """Ajouter 30 jours au lieu d'un mois ferait dériver l'échéance : sur
        six mois, l'entente expirerait cinq jours trop tôt — et le patient
        ne serait plus pris en charge pendant ces cinq jours."""
        depart = date(2026, 1, 1)
        assert loc.ajouter_mois(depart, 6) == date(2026, 7, 1)
        assert depart + timedelta(days=180) == date(2026, 6, 30)

    def test_sans_date_de_depart(self):
        assert loc.ajouter_mois(None, 6) is None


class TestParserDate:
    @pytest.mark.parametrize("saisi", ["18/09/2026", "18-09-2026", "18.09.2026",
                                       "2026-09-18", "18/09/26"])
    def test_formats_acceptes(self, saisi):
        assert loc.parser_date(saisi) == AUJOURDHUI

    def test_une_faute_de_frappe_ne_leve_pas(self):
        """Ces dossiers sont saisis à la main. Une date illisible ne peut pas
        faire tomber l'écran de toute une pharmacie."""
        assert loc.parser_date("pas une date") is None
        assert loc.parser_date("") is None
        assert loc.parser_date(None) is None


class TestParserMois:
    def test_zero_vaut_non_renseigne(self):
        """Zéro mois voudrait dire « expire le jour même », ce que la caisse
        n'accorde pas : c'est une case vide, pas une durée."""
        assert loc.parser_mois(0) == loc.VALIDITE_DEFAUT_MOIS
        assert loc.parser_mois("") == loc.VALIDITE_DEFAUT_MOIS
        assert loc.parser_mois(None) == loc.VALIDITE_DEFAUT_MOIS

    def test_un_negatif_ne_peut_pas_raccourcir_une_entente(self):
        assert loc.parser_mois(-3) == loc.VALIDITE_DEFAUT_MOIS

    def test_la_valeur_saisie_gagne_sur_le_defaut(self):
        """C'est tout l'objet du choix : la caisse accorde au cas par cas."""
        assert loc.parser_mois(12) == 12
        assert loc.parser_mois("3") == 3


# ---------------------------------------------------------------------------
# L'entente préalable
# ---------------------------------------------------------------------------

class TestEcheance:
    def test_accord_plus_validite(self):
        assert loc.echeance("2026-03-01", 6) == date(2026, 9, 1)

    def test_la_validite_saisie_prime(self):
        assert loc.echeance("2026-03-01", 12) == date(2027, 3, 1)

    def test_sans_accord_il_n_y_a_pas_d_echeance(self):
        """Un dossier sans accord n'est pas un dossier qui expire : c'est un
        dossier qui n'a jamais commencé. Lui inventer une échéance le ferait
        remonter dans « à renouveler » alors qu'il n'y a rien à renouveler."""
        assert loc.echeance("", 6) is None
        assert loc.echeance(None, 6) is None


class TestStatutEntente:
    def test_sans_entente(self):
        assert loc.statut_entente("", 6, AUJOURDHUI) == loc.STATUT_SANS_ENTENTE

    def test_valide_loin_de_l_echeance(self):
        assert loc.statut_entente("2026-09-01", 6,
                                  AUJOURDHUI) == loc.STATUT_ENTENTE_VALIDE

    def test_a_renouveler_dans_les_trente_jours(self):
        """Monter un dossier prend du temps : ordonnance, accord du médecin,
        envoi à la caisse. Une échéance vue le jour où elle tombe est une
        échéance manquée."""
        # Accordée le 18/04, six mois → échéance au 18/10, dans 30 jours.
        assert loc.statut_entente("2026-04-18", 6,
                                  AUJOURDHUI) == loc.STATUT_A_RENOUVELER

    def test_le_dernier_jour_compte_encore(self):
        """L'échéance elle-même est couverte : expirer « aujourd'hui » et
        « hier » n'appellent pas le même geste."""
        assert loc.statut_entente("2026-03-18", 6,
                                  AUJOURDHUI) == loc.STATUT_A_RENOUVELER

    def test_expiree_des_le_lendemain(self):
        assert loc.statut_entente("2026-03-17", 6,
                                  AUJOURDHUI) == loc.STATUT_EXPIREE

    def test_le_delai_d_alerte_est_reglable(self):
        """Si la caisse répond vite, trente jours encombrent la liste."""
        assert loc.statut_entente("2026-04-18", 6, AUJOURDHUI,
                                  alerte_j=15) == loc.STATUT_ENTENTE_VALIDE

    def test_le_signe_des_jours_restants_se_lit(self):
        """« Expirée depuis 12 jours » et « expire dans 12 jours » ne
        demandent pas le même geste."""
        assert loc.jours_avant_echeance("2026-03-18", 6, AUJOURDHUI) == 0
        assert loc.jours_avant_echeance("2026-03-01", 6, AUJOURDHUI) < 0
        assert loc.jours_avant_echeance("2026-06-18", 6, AUJOURDHUI) > 0


# ---------------------------------------------------------------------------
# La facturation mensuelle
# ---------------------------------------------------------------------------

class TestFacturation:
    def test_jamais_facturee_est_due_maintenant(self):
        """C'est le cas le plus facile à oublier : aucune date ne vient le
        rappeler."""
        assert loc.statut_facturation("", AUJOURDHUI) == loc.STATUT_JAMAIS_FACTUREE
        assert loc.jours_avant_facturation("", AUJOURDHUI) == 0

    def test_facturee_ce_mois_ci_peut_attendre(self):
        assert loc.statut_facturation("2026-09-01",
                                      AUJOURDHUI) == loc.STATUT_FACTURATION_A_JOUR

    def test_un_mois_ecoule_rouvre_la_facturation(self):
        assert loc.statut_facturation("2026-08-18",
                                      AUJOURDHUI) == loc.STATUT_A_FACTURER

    def test_jamais_de_compte_a_rebours_negatif(self):
        """« Facturable depuis 40 jours » et « facturable » ne demandent pas
        deux gestes différents, et un négatif dans une colonne se lit mal."""
        assert loc.jours_avant_facturation("2026-01-01", AUJOURDHUI) == 0


class TestMoisDeRetard:
    def test_aucun_retard_quand_c_est_a_jour(self):
        assert loc.mois_de_retard("2026-09-01", AUJOURDHUI) == 0

    def test_trois_mois_oublies_font_trois_mois_dus(self):
        """LE piège : afficher « à facturer » sans le nombre ferait encaisser
        un mois et croire le dossier à jour — les deux autres seraient
        perdus."""
        assert loc.mois_de_retard("2026-06-01", AUJOURDHUI) == 3

    def test_jamais_facturee_ne_compte_pas_de_retard(self):
        """Sans première facturation, il n'y a pas de rythme à rattraper :
        on ne peut pas savoir depuis quand la location tourne."""
        assert loc.mois_de_retard("", AUJOURDHUI) == 0

    def test_une_date_aberrante_ne_boucle_pas_sans_fin(self):
        """Une faute de frappe — « 1926 » pour « 2026 » — ne doit pas figer
        l'écran en comptant mille mois."""
        assert loc.mois_de_retard("1926-01-01", AUJOURDHUI) <= 240


# ---------------------------------------------------------------------------
# Les trois listes
# ---------------------------------------------------------------------------

class TestLesTroisVues:
    def _trois_dossiers(self):
        lignes = [
            # Valide, facturée ce mois-ci : rien à faire.
            {"Patient": "M. TRANQUILLE", "Matériel": "Fauteuil roulant",
             "Début de location": "2026-01-01", "Entente préalable": "2026-08-01",
             "Validité (mois)": 12, "Dernière facturation": "2026-09-10",
             "Notes": ""},
            # Échéance dans 30 jours : à renouveler.
            {"Patient": "Mme URGENTE", "Matériel": "Lit médicalisé",
             "Début de location": "2026-02-01", "Entente préalable": "2026-04-18",
             "Validité (mois)": 6, "Dernière facturation": "2026-09-05",
             "Notes": ""},
            # Expirée, et trois mois de facturation oubliés.
            {"Patient": "M. OUBLIE", "Matériel": "Concentrateur O2",
             "Début de location": "2025-11-01", "Entente préalable": "2026-01-01",
             "Validité (mois)": 6, "Dernière facturation": "2026-06-01",
             "Notes": ""},
        ]
        return pd.DataFrame(lignes, columns=loc.COLONNES_DOSSIER)

    def test_a_renouveler_ne_retient_que_ce_qui_presse(self):
        liste = loc.a_renouveler(self._trois_dossiers(), AUJOURDHUI)
        assert list(liste["Patient"]) == ["M. OUBLIE", "Mme URGENTE"]

    def test_les_expirees_passent_devant(self):
        """Elles ne sont plus prises en charge : chaque jour compte double."""
        liste = loc.a_renouveler(self._trois_dossiers(), AUJOURDHUI)
        assert liste.iloc[0]["Entente"] == loc.STATUT_EXPIREE

    def test_a_facturer_retient_les_dues_et_les_jamais_facturees(self):
        dossier = pd.concat([self._trois_dossiers(),
                             _dossier(Patient="Mme NEUVE",
                                      **{"Dernière facturation": ""})],
                            ignore_index=True)
        liste = loc.a_facturer(dossier, AUJOURDHUI)
        assert set(liste["Patient"]) == {"M. OUBLIE", "Mme NEUVE"}

    def test_le_nombre_de_mois_dus_remonte_dans_la_liste(self):
        liste = loc.a_facturer(self._trois_dossiers(), AUJOURDHUI)
        oublie = liste[liste["Patient"] == "M. OUBLIE"].iloc[0]
        assert oublie["Mois dus"] == 3

    def test_le_resume_compte_juste(self):
        compte = loc.resume(self._trois_dossiers(), AUJOURDHUI)
        assert compte == {"dossiers": 3, "patients": 3, "locations": 3,
                          "achats": 0, "a_renouveler": 1, "expirees": 1,
                          "a_facturer": 1, "mois_dus": 3,
                          "demandes_en_attente": 0, "dernier_mois": 0,
                          "hors_caisse": 0, "cautions": 0}

    def test_un_dossier_vide_ne_plante_rien(self):
        vide = loc.dossier_vide()
        assert loc.a_renouveler(vide, AUJOURDHUI).empty
        assert loc.a_facturer(vide, AUJOURDHUI).empty
        assert loc.resume(vide, AUJOURDHUI)["dossiers"] == 0


class TestClassement:
    def test_par_echeance_au_plus_proche(self):
        """Ce qui expire en premier doit sauter aux yeux."""
        lignes = [
            {"Patient": "B", "Matériel": "X", "Début de location": "",
             "Entente préalable": "2026-08-01", "Validité (mois)": 12,
             "Dernière facturation": "", "Notes": ""},
            {"Patient": "A", "Matériel": "Y", "Début de location": "",
             "Entente préalable": "2026-01-01", "Validité (mois)": 6,
             "Dernière facturation": "", "Notes": ""},
        ]
        vue = loc.vue_affichable(pd.DataFrame(lignes,
                                              columns=loc.COLONNES_DOSSIER),
                                 AUJOURDHUI)
        assert list(vue["Patient"]) == ["A", "B"]

    def test_les_dossiers_sans_entente_passent_en_queue(self):
        """Rien ne presse à leur sujet tant qu'aucun accord n'a été demandé."""
        lignes = [
            {"Patient": "SANS", "Matériel": "X", "Début de location": "",
             "Entente préalable": "", "Validité (mois)": 6,
             "Dernière facturation": "", "Notes": ""},
            {"Patient": "AVEC", "Matériel": "Y", "Début de location": "",
             "Entente préalable": "2026-10-01", "Validité (mois)": 6,
             "Dernière facturation": "", "Notes": ""},
        ]
        vue = loc.vue_affichable(pd.DataFrame(lignes,
                                              columns=loc.COLONNES_DOSSIER),
                                 AUJOURDHUI)
        assert list(vue["Patient"]) == ["AVEC", "SANS"]

    def test_par_patient(self):
        lignes = [
            {"Patient": "Zoé", "Matériel": "X", "Début de location": "",
             "Entente préalable": "2026-01-01", "Validité (mois)": 6,
             "Dernière facturation": "", "Notes": ""},
            {"Patient": "Éric", "Matériel": "Y", "Début de location": "",
             "Entente préalable": "2026-12-01", "Validité (mois)": 6,
             "Dernière facturation": "", "Notes": ""},
        ]
        vue = loc.vue_affichable(pd.DataFrame(lignes,
                                              columns=loc.COLONNES_DOSSIER),
                                 AUJOURDHUI, tri=loc.TRI_PATIENT)
        # « Éric » avant « Zoé » : l'accent ne doit pas le rejeter en fin de
        # liste, comme il le ferait sur un tri brut.
        assert list(vue["Patient"]) == ["Éric", "Zoé"]


class TestAffichage:
    def test_les_cases_vides_sont_vraiment_vides(self):
        """Streamlit affiche « None » pour une date absente : une colonne
        pleine de « None » se lit comme une panne."""
        vue = loc.pour_affichage(loc.vue_affichable(
            _dossier(**{"Entente préalable": "", "Dernière facturation": ""}),
            AUJOURDHUI))
        ligne = vue.iloc[0]
        assert ligne["Échéance"] == ""
        assert ligne["Dernière facturation"] == ""
        assert ligne["Jours avant échéance"] == ""

    def test_les_dates_sont_au_format_francais(self):
        vue = loc.pour_affichage(loc.vue_affichable(_dossier(), AUJOURDHUI))
        assert vue.iloc[0]["Échéance"] == "01/09/2026"


# ---------------------------------------------------------------------------
# Mouvements
# ---------------------------------------------------------------------------

class TestMouvements:
    def test_ouvrir_un_dossier(self):
        d = loc.ajouter_dossier(loc.dossier_vide(), "Mme MARTIN", "Déambulateur",
                                debut="2026-09-01", entente="2026-09-05",
                                validite_mois=3)
        assert len(d) == 1
        # Stocké en TEXTE : le dossier est un tableau de texte de bout en
        # bout, et un entier glissé dans une colonne adossée à Arrow fait
        # tomber l'écran au moment d'enregistrer.
        assert d.iloc[0]["Validité (mois)"] == "3"

    def test_un_patient_peut_louer_deux_appareils(self):
        """C'est le COUPLE patient + matériel qui identifie le dossier."""
        d = loc.ajouter_dossier(loc.dossier_vide(), "Mme MARTIN", "Lit")
        d = loc.ajouter_dossier(d, "Mme MARTIN", "Fauteuil")
        assert len(d) == 2

    def test_le_meme_dossier_est_complete_et_non_duplique(self):
        """Deux lignes pour le même patient et le même appareil, c'est un
        historique coupé en deux et une échéance suivie sur la mauvaise."""
        d = loc.ajouter_dossier(loc.dossier_vide(), "Mme MARTIN", "Lit")
        d = loc.ajouter_dossier(d, "mme martin", "LIT", entente="2026-09-05")
        assert len(d) == 1
        assert d.iloc[0]["Entente préalable"] == "2026-09-05"

    def test_une_case_vide_n_efface_pas_ce_qu_on_sait_deja(self):
        d = loc.ajouter_dossier(loc.dossier_vide(), "Mme MARTIN", "Lit",
                                entente="2026-09-05")
        d = loc.ajouter_dossier(d, "Mme MARTIN", "Lit", notes="à surveiller")
        assert d.iloc[0]["Entente préalable"] == "2026-09-05"
        assert d.iloc[0]["Notes"] == "à surveiller"

    def test_un_dossier_sans_patient_ou_sans_materiel_est_refuse(self):
        assert loc.ajouter_dossier(loc.dossier_vide(), "", "Lit").empty
        assert loc.ajouter_dossier(loc.dossier_vide(), "Mme MARTIN", "").empty

    def test_enregistrer_l_entente_repart_l_echeance(self):
        d = loc.ajouter_dossier(loc.dossier_vide(), "Mme MARTIN", "Lit")
        d = loc.enregistrer_entente(d, "Mme MARTIN", "Lit", "2026-09-18", 6)
        assert loc.echeance(d.iloc[0]["Entente préalable"],
                            d.iloc[0]["Validité (mois)"]) == date(2027, 3, 18)

    def test_facturer_repart_l_horloge(self):
        d = _dossier(**{"Dernière facturation": "2026-06-01"})
        assert loc.statut_facturation(d.iloc[0]["Dernière facturation"],
                                      AUJOURDHUI) == loc.STATUT_A_FACTURER
        d = loc.enregistrer_facturation(d, "Mme DUPONT", "Lit médicalisé",
                                        AUJOURDHUI)
        assert loc.statut_facturation(d.iloc[0]["Dernière facturation"],
                                      AUJOURDHUI) == loc.STATUT_FACTURATION_A_JOUR

    def test_supprimer_quand_le_materiel_revient(self):
        d = loc.supprimer_dossier(_dossier(), "Mme DUPONT", "Lit médicalisé")
        assert d.empty

    def test_supprimer_un_dossier_absent_ne_casse_rien(self):
        d = loc.supprimer_dossier(_dossier(), "M. INCONNU", "Lit")
        assert len(d) == 1


class TestTableauEdite:
    def test_une_ligne_sans_patient_est_abandonnee(self):
        tableau = pd.DataFrame([
            {"Patient": "", "Matériel": "Lit", "Début de location": "",
             "Entente préalable": "", "Validité (mois)": 6,
             "Dernière facturation": "", "Notes": ""},
            {"Patient": "Mme MARTIN", "Matériel": "", "Début de location": "",
             "Entente préalable": "", "Validité (mois)": 6,
             "Dernière facturation": "", "Notes": ""},
        ], columns=loc.COLONNES_DOSSIER)
        assert loc.normaliser_tableau_edite(tableau).empty

    def test_les_dates_corrigees_a_la_main_sont_relues(self):
        tableau = _dossier(**{"Entente préalable": "05/09/2026"})
        propre = loc.normaliser_tableau_edite(tableau)
        assert propre.iloc[0]["Entente préalable"] == "2026-09-05"

    def test_une_validite_effacee_reprend_le_defaut(self):
        propre = loc.normaliser_tableau_edite(_dossier(**{"Validité (mois)": ""}))
        assert propre.iloc[0]["Validité (mois)"] == str(
            loc.VALIDITE_DEFAUT_MOIS)


# ---------------------------------------------------------------------------
# Persistance
# ---------------------------------------------------------------------------

class TestPersistance:
    def test_aller_retour_sur_disque(self, tmp_path):
        chemin = tmp_path / "location.csv"
        loc.sauver(_dossier(), chemin)
        relu = loc.charger(chemin)
        assert relu.iloc[0]["Patient"] == "Mme DUPONT"
        assert relu.iloc[0]["Entente préalable"] == "2026-03-01"

    def test_fichier_absent(self, tmp_path):
        assert loc.charger(tmp_path / "rien.csv").empty

    def test_fichier_illisible_ne_bloque_pas_l_ouverture(self, tmp_path):
        """Un fichier édité à la main et cassé ne doit pas empêcher la
        pharmacie d'ouvrir son module : l'ancien reste sur le disque."""
        chemin = tmp_path / "location.csv"
        chemin.write_bytes(b"\xff\xfe pas du CSV \x00")
        assert loc.charger(chemin).empty

    def test_l_ecriture_passe_par_le_verrou_partage(self, tmp_path):
        """Plusieurs comptoirs sur les mêmes fichiers : on relit sous verrou
        et on applique le mouvement, on n'écrase jamais une photo."""
        chemin = tmp_path / "location.csv"
        loc.sauver(_dossier(), chemin)
        ecriture = loc.appliquer_aux_dossiers(
            chemin, lambda courant: loc.ajouter_dossier(
                courant, "M. SECOND", "Fauteuil"))
        assert len(ecriture.tableau) == 2
        assert len(loc.charger(chemin)) == 2

    def test_l_export_reprend_la_vue_affichee(self, tmp_path):
        octets = loc.exporter_csv(_dossier(), AUJOURDHUI)
        texte = octets.decode("utf-8-sig")
        assert "Mme DUPONT" in texte and "01/09/2026" in texte

    def test_le_nom_de_fichier_est_date(self):
        assert loc.nom_fichier("csv", AUJOURDHUI) == "location_2026-09-18.csv"


class TestIsolation:
    def test_le_module_n_importe_aucun_autre_metier(self):
        """Il ne connaît que ses propres dossiers : ni cadencier, ni stock
        interne, ni commandes spéciales. Une dépendance ajoutée un jour de
        hâte se paie des mois plus tard."""
        racine = pathlib.Path(__file__).resolve().parent.parent
        arbre = ast.parse((racine / "location.py").read_text(encoding="utf-8"))
        projet = {f.stem for f in racine.glob("*.py")}
        importes = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                importes |= {a.name.split(".")[0] for a in noeud.names}
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                importes.add(noeud.module.split(".")[0])
        assert (importes & projet) <= {"stockage_partage"}

    def test_le_module_n_importe_pas_streamlit(self):
        """La logique doit être éprouvable sans navigateur."""
        source = (pathlib.Path(__file__).resolve().parent.parent
                  / "location.py").read_text(encoding="utf-8")
        assert "import streamlit" not in source


# ---------------------------------------------------------------------------
# Louer OU acheter : le même dossier, deux suites différentes
# ---------------------------------------------------------------------------

class TestModes:
    """« On peut soit acheter soit louer, mais harmonisé par patient. »

    Les deux passent par une entente préalable — c'est ce qui permet de les
    tenir dans un seul dossier. Ce qui les sépare vient après : la location
    se facture tous les mois et se renouvelle, l'achat se facture une fois
    et se termine.
    """

    def test_ce_qui_n_est_pas_un_achat_est_une_location(self):
        """Le défaut penche du côté SURVEILLÉ : une location prise pour un
        achat cesserait d'être facturée tous les mois et sortirait des
        renouvellements, sans que rien ne le signale."""
        assert loc.parser_mode("") == loc.MODE_LOCATION
        assert loc.parser_mode(None) == loc.MODE_LOCATION
        assert loc.parser_mode("n'importe quoi") == loc.MODE_LOCATION
        assert loc.parser_mode(loc.MODE_LOCATION) == loc.MODE_LOCATION

    @pytest.mark.parametrize("saisi", ["Achat", "achat", "ACHAT", "acheté",
                                       "achete", "🛒 Achat"])
    def test_un_achat_se_reconnait_comme_il_s_ecrit(self, saisi):
        """Ces cases sont corrigées à la main dans le tableau : « achat »
        sans majuscule ni accent doit valoir « 🛒 Achat »."""
        assert loc.parser_mode(saisi) == loc.MODE_ACHAT

    def _achat(self, **kw):
        base = {"Patient": "Mme ACHETEUSE", "Matériel": "Fauteuil roulant",
                "Mode": loc.MODE_ACHAT, "Début de location": "2026-01-10",
                "Entente préalable": "2026-01-05", "Validité (mois)": 6,
                "Dernière facturation": "2026-01-20", "Notes": ""}
        base.update(kw)
        return pd.DataFrame([base], columns=loc.COLONNES_DOSSIER)

    def test_un_achat_regle_ne_revient_pas_tous_les_mois(self):
        """Une location facturée en janvier redevient due en février. Un
        fauteuil payé en janvier est payé — lui calculer une échéance ferait
        facturer deux fois le même fauteuil."""
        assert loc.statut_facturation("2026-01-20", AUJOURDHUI,
                                      mode=loc.MODE_ACHAT) == loc.STATUT_ACHAT_REGLE
        assert loc.prochaine_facturation("2026-01-20",
                                         mode=loc.MODE_ACHAT) is None
        assert loc.mois_de_retard("2026-01-20", AUJOURDHUI,
                                  mode=loc.MODE_ACHAT) == 0

    def test_la_meme_date_en_location_compte_sept_mois_dus(self):
        """Le contraste, sur la MÊME date : c'est tout l'objet du mode.

        Sept et non huit : facturé le 20 janvier, le dossier redevient dû
        les 20 février, mars, avril, mai, juin, juillet et août. Celle du
        20 septembre n'est pas encore échue le 18."""
        assert loc.mois_de_retard("2026-01-20", AUJOURDHUI,
                                  mode=loc.MODE_LOCATION) == 7

    def test_un_achat_jamais_facture_reste_du(self):
        """Livré et jamais facturé : le cas qu'aucune date ne rappelle."""
        dossier = self._achat(**{"Dernière facturation": ""})
        assert loc.statut_facturation("", AUJOURDHUI,
                                      mode=loc.MODE_ACHAT) == loc.STATUT_JAMAIS_FACTUREE
        assert list(loc.a_facturer(dossier, AUJOURDHUI)["Patient"]) == [
            "Mme ACHETEUSE"]

    def test_un_achat_regle_sort_de_la_facturation(self):
        """Et il en sort POUR DE BON, contrairement à une location."""
        assert loc.a_facturer(self._achat(), AUJOURDHUI).empty

    def test_un_achat_regle_ne_se_renouvelle_pas(self):
        """Le fauteuil est payé, il est au patient : son entente a servi et
        peut expirer sans que personne n'ait rien à faire. L'y laisser
        noierait les vraies échéances sous des dossiers clos."""
        # Entente du 05/01, six mois → expirée depuis longtemps.
        assert loc.a_renouveler(self._achat(), AUJOURDHUI).empty
        assert loc.resume(self._achat(), AUJOURDHUI)["expirees"] == 0

    def test_un_achat_NON_regle_se_renouvelle_encore(self):
        """Tant qu'il n'est pas facturé, il n'est pas acquis : l'entente
        doit être valide le jour où la caisse paiera."""
        pas_regle = self._achat(**{"Dernière facturation": ""})
        assert list(loc.a_renouveler(pas_regle, AUJOURDHUI)["Patient"]) == [
            "Mme ACHETEUSE"]

    def test_louer_puis_acheter_fait_deux_dossiers(self):
        """On loue un fauteuil quelques mois, puis on l'achète. Deux
        ententes, deux facturations : les confondre écraserait l'historique
        de la location le jour de l'achat."""
        d = loc.ajouter_dossier(loc.dossier_vide(), "M. DOUBLE", "Fauteuil",
                                entente="2026-01-01",
                                mode=loc.MODE_LOCATION)
        d = loc.ajouter_dossier(d, "M. DOUBLE", "Fauteuil",
                                entente="2026-07-01", mode=loc.MODE_ACHAT)
        assert len(d) == 2
        assert set(d["Mode"]) == {loc.MODE_LOCATION, loc.MODE_ACHAT}

    def test_rouvrir_le_meme_mode_complete_au_lieu_de_dupliquer(self):
        d = loc.ajouter_dossier(loc.dossier_vide(), "M. DOUBLE", "Fauteuil",
                                mode=loc.MODE_ACHAT)
        d = loc.ajouter_dossier(d, "M. DOUBLE", "Fauteuil",
                                entente="2026-07-01", mode=loc.MODE_ACHAT)
        assert len(d) == 1
        assert d.iloc[0]["Entente préalable"] == "2026-07-01"

    def test_un_geste_peut_viser_un_mode_precis(self):
        """Facturer l'achat ne doit pas relancer l'horloge de la location
        du même appareil."""
        d = loc.ajouter_dossier(loc.dossier_vide(), "M. DOUBLE", "Fauteuil",
                                derniere_facturation="2026-09-01",
                                mode=loc.MODE_LOCATION)
        d = loc.ajouter_dossier(d, "M. DOUBLE", "Fauteuil",
                                mode=loc.MODE_ACHAT)
        d = loc.enregistrer_facturation(d, "M. DOUBLE", "Fauteuil",
                                        AUJOURDHUI, mode=loc.MODE_ACHAT)
        location = d[d["Mode"] == loc.MODE_LOCATION].iloc[0]
        achat = d[d["Mode"] == loc.MODE_ACHAT].iloc[0]
        assert location["Dernière facturation"] == "2026-09-01"
        assert achat["Dernière facturation"] == AUJOURDHUI.isoformat()

    def test_le_mode_se_lit_dans_toutes_les_listes(self):
        """Une liste où l'on ne voit pas si la ligne est louée ou achetée
        oblige à retourner au tableau complet pour chaque patient."""
        for colonnes in (loc.COLONNES_ENTENTES, loc.COLONNES_FACTURATION,
                         loc.COLONNES_RENOUVELLEMENT):
            assert "Mode" in colonnes, colonnes

    def test_la_vue_des_achats_tait_ce_qui_n_existe_pas(self):
        """Ni « prochaine facturation » ni « mois dus » : montrer deux
        colonnes vides ferait douter d'une panne."""
        assert "Prochaine facturation" not in loc.COLONNES_ACHATS
        assert "Mois dus" not in loc.COLONNES_ACHATS

    def test_du_mode_separe_sans_recalculer(self):
        dossier = pd.concat([self._achat(), _dossier()], ignore_index=True)
        vue = loc.vue_affichable(dossier, AUJOURDHUI)
        assert list(loc.du_mode(vue, loc.MODE_ACHAT)["Patient"]) == [
            "Mme ACHETEUSE"]
        assert list(loc.du_mode(vue, loc.MODE_LOCATION)["Patient"]) == [
            "Mme DUPONT"]

    def test_un_mode_inconnu_est_corrige_a_l_ecriture(self, tmp_path):
        """Un fichier relu ne doit jamais porter de troisième valeur : ces
        lignes disparaîtraient des DEUX sous-onglets."""
        dossier = self._achat(Mode="n'importe quoi")
        chemin = tmp_path / "location.csv"
        loc.sauver(dossier, chemin)
        assert loc.charger(chemin).iloc[0]["Mode"] == loc.MODE_LOCATION

    def test_une_ligne_ajoutee_a_la_main_devient_une_location(self):
        """Le « + » du tableau laisse la case vide : le mode surveillé est
        le défaut sans danger."""
        edite = pd.DataFrame(
            [{"Patient": "M. NEUF", "Matériel": "Déambulateur", "Mode": "",
              "Début de location": "", "Entente préalable": "",
              "Validité (mois)": "", "Dernière facturation": "", "Notes": ""}],
            columns=loc.COLONNES_DOSSIER)
        assert loc.normaliser_tableau_edite(edite).iloc[0]["Mode"] == (
            loc.MODE_LOCATION)


class TestRecapitulatifParPatient:
    """« Il faut que ça soit harmonisé par patient. »

    Le patient au téléphone ne demande pas « où en est ma location de
    lit » : il demande où il en est. Éclaté en deux listes, il fallait le
    chercher deux fois et recoller les réponses de tête — et c'est là qu'on
    oublie le second appareil.
    """

    def _deux_patients(self):
        lignes = [
            {"Patient": "Mme MIXTE", "Matériel": "Lit médicalisé",
             "Mode": loc.MODE_LOCATION, "Début de location": "2026-01-01",
             "Entente préalable": "2026-08-01", "Validité (mois)": 12,
             "Dernière facturation": "2026-09-15", "Notes": ""},
            {"Patient": "mme mixte", "Matériel": "Déambulateur",
             "Mode": loc.MODE_ACHAT, "Début de location": "2026-02-01",
             "Entente préalable": "2026-02-01", "Validité (mois)": 6,
             "Dernière facturation": "2026-02-10", "Notes": ""},
            # Expirée : c'est elle qui doit remonter en tête.
            {"Patient": "M. TOMBE", "Matériel": "Concentrateur O2",
             "Mode": loc.MODE_LOCATION, "Début de location": "2025-11-01",
             "Entente préalable": "2026-01-01", "Validité (mois)": 6,
             "Dernière facturation": "2026-09-10", "Notes": ""},
        ]
        return pd.DataFrame(lignes, columns=loc.COLONNES_DOSSIER)

    def test_une_ligne_par_patient_tous_modes_confondus(self):
        recap = loc.par_patient(self._deux_patients(), AUJOURDHUI)
        assert len(recap) == 2
        mixte = recap[recap["Patient"].str.upper() == "MME MIXTE"].iloc[0]
        assert mixte["Locations"] == 1
        assert mixte["Achats"] == 1

    def test_la_casse_du_nom_ne_coupe_pas_le_patient_en_deux(self):
        """« Mme MIXTE » et « mme mixte » sont la même personne : deux
        lignes, c'est un appareil qu'on oublie."""
        recap = loc.par_patient(self._deux_patients(), AUJOURDHUI)
        assert list(recap["Patient"].str.upper()).count("MME MIXTE") == 1

    def test_le_pire_statut_du_patient_remonte(self):
        """Si l'un de ses appareils n'est plus pris en charge, c'est ce
        qu'il faut voir en ouvrant sa ligne — pas une moyenne."""
        recap = loc.par_patient(self._deux_patients(), AUJOURDHUI)
        assert recap.iloc[0]["Patient"] == "M. TOMBE"
        assert recap.iloc[0]["Entente"] == loc.STATUT_EXPIREE

    def test_le_pire_gagne_meme_quand_il_vient_en_second(self):
        """Le cas qui distingue « le pire » de « le premier venu » : les
        dossiers sont classés par échéance, et celui qui n'a PAS d'entente
        n'en a pas — il passe donc en queue. Prendre le premier dirait
        « valide » d'un patient dont un appareil n'est couvert par rien."""
        lignes = [
            {"Patient": "M. DEUX", "Matériel": "Lit médicalisé",
             "Mode": loc.MODE_LOCATION, "Début de location": "2026-01-01",
             "Entente préalable": "2026-09-01", "Validité (mois)": 12,
             "Dernière facturation": "2026-09-15", "Notes": ""},
            {"Patient": "M. DEUX", "Matériel": "Déambulateur",
             "Mode": loc.MODE_LOCATION, "Début de location": "2026-09-01",
             "Entente préalable": "", "Validité (mois)": 6,
             "Dernière facturation": "2026-09-15", "Notes": ""},
        ]
        dossier = pd.DataFrame(lignes, columns=loc.COLONNES_DOSSIER)
        vue = loc.vue_affichable(dossier, AUJOURDHUI, loc.TRI_PATIENT)
        assert vue.iloc[0]["Entente"] == loc.STATUT_ENTENTE_VALIDE
        recap = loc.par_patient(dossier, AUJOURDHUI)
        assert recap.iloc[0]["Entente"] == loc.STATUT_SANS_ENTENTE

    def test_l_achat_regle_ne_gonfle_pas_le_a_renouveler(self):
        recap = loc.par_patient(self._deux_patients(), AUJOURDHUI)
        mixte = recap[recap["Patient"].str.upper() == "MME MIXTE"].iloc[0]
        assert mixte["À renouveler"] == 0

    def test_un_dossier_vide_ne_plante_rien(self):
        assert loc.par_patient(loc.dossier_vide(), AUJOURDHUI).empty

    def test_le_resume_distingue_les_deux_modes(self):
        compte = loc.resume(self._deux_patients(), AUJOURDHUI)
        assert compte["locations"] == 2
        assert compte["achats"] == 1
        assert compte["patients"] == 2


# ---------------------------------------------------------------------------
# La DEMANDE d'entente : ce qui précède l'accord
# ---------------------------------------------------------------------------

class TestDemandeDEntente:
    """« Il y a des demandes d'entente préalable à effectuer. »

    L'étape manquait : un dossier parti à la caisse se lisait comme un
    dossier oublié — et on le refaisait. Elle porte une date ET un prénom,
    parce que trois semaines plus tard, c'est la seule façon de savoir à
    qui demander ce qui a été envoyé.
    """

    def test_rien_de_fait_et_demande_envoyee_ne_se_lisent_pas_pareil(self):
        assert loc.statut_entente("", 6, AUJOURDHUI) == loc.STATUT_SANS_ENTENTE
        assert loc.statut_entente("", 6, AUJOURDHUI,
                                  demande_le="2026-09-01") == (
            loc.STATUT_DEMANDE_ENVOYEE)

    def test_l_accord_recu_efface_l_attente(self):
        """Une fois l'accord arrivé, la date de demande n'est plus un
        statut : c'est une archive."""
        assert loc.statut_entente("2026-09-01", 6, AUJOURDHUI,
                                  demande_le="2026-08-01") == (
            loc.STATUT_ENTENTE_VALIDE)

    def test_les_jours_d_attente_se_comptent(self):
        """Une demande qui dort depuis six semaines est une location que
        personne ne paie, et rien d'autre ne la rappelle."""
        assert loc.jours_depuis_demande("2026-09-01", AUJOURDHUI) == 17
        assert loc.jours_depuis_demande("", AUJOURDHUI) is None

    def test_le_prenom_de_qui_a_demande_est_conserve(self):
        d = loc.ajouter_dossier(loc.dossier_vide(), "M. SUIVI", "Lit")
        d = loc.enregistrer_demande(d, "M. SUIVI", "Lit", "2026-09-01",
                                    "Sophie")
        assert d.iloc[0]["Demande le"] == "2026-09-01"
        assert d.iloc[0]["Demandée par"] == "Sophie"

    def test_la_liste_des_relances_met_les_plus_anciennes_devant(self):
        d = loc.ajouter_dossier(loc.dossier_vide(), "M. RECENT", "Lit",
                                demande_le="2026-09-10", demandee_par="Léa")
        d = loc.ajouter_dossier(d, "Mme ANCIENNE", "VNI",
                                demande_le="2026-07-01", demandee_par="Sophie")
        # Celui-ci a son accord : il n'attend plus rien.
        d = loc.ajouter_dossier(d, "M. SERVI", "Fauteuil",
                                demande_le="2026-06-01", entente="2026-06-20")
        liste = loc.en_attente_de_reponse(d, AUJOURDHUI)
        assert list(liste["Patient"]) == ["Mme ANCIENNE", "M. RECENT"]

    def test_le_commentaire_d_entente_ne_se_melange_pas_aux_notes(self):
        """Les notes décrivent la location, le commentaire raconte le
        dossier CAFAT. Mélangés, on ne retrouve ni l'un ni l'autre."""
        d = loc.ajouter_dossier(loc.dossier_vide(), "M. SUIVI", "Lit",
                                notes="livré le 3, étage 2")
        d = loc.enregistrer_commentaire(d, "M. SUIVI", "Lit",
                                        "relancé la caisse le 12/09")
        assert d.iloc[0]["Notes"] == "livré le 3, étage 2"
        assert d.iloc[0]["Commentaire entente"] == "relancé la caisse le 12/09"

    def test_le_commentaire_remonte_dans_la_vue_des_ententes(self):
        assert "Commentaire entente" in loc.COLONNES_ENTENTES
        assert "Demande le" in loc.COLONNES_ENTENTES
        assert "Demandée par" in loc.COLONNES_ENTENTES


# ---------------------------------------------------------------------------
# Le dernier mois couvert : le moment où proposer le renouvellement
# ---------------------------------------------------------------------------

class TestDernierMoisCouvert:
    """« Au moment de la facturation du dernier mois, une proposition de
    renouvellement du dossier d'entente préalable. »

    C'est LE moment utile : la facturation est le seul geste mensuel
    certain sur une location. Attendre l'échéance, c'est la découvrir une
    fois passée ; prévenir plus tôt, c'est prévenir tous les mois pour
    rien.
    """

    def test_le_mois_du_milieu_ne_declenche_rien(self):
        # Entente du 01/03, six mois → échéance au 01/09. Facturé le 01/05,
        # la suivante tombe le 01/06 : il reste des mois couverts.
        assert not loc.au_dernier_mois("2026-03-01", 6, "2026-05-01")

    def test_le_dernier_mois_se_reconnait(self):
        """Facturé le 15/08, la suivante tomberait le 15/09 — après
        l'échéance du 01/09. Il n'y aura pas de mois d'après."""
        assert loc.au_dernier_mois("2026-03-01", 6, "2026-08-15")

    def test_la_facturation_qui_tombe_PILE_sur_l_echeance_est_couverte(self):
        """La borne, et elle se joue à un jour près.

        Entente du 01/01, six mois → échéance au 01/07. Facturé le 01/06,
        la suivante tombe le 01/07 : le jour de l'échéance est ENCORE
        couvert — comme partout ailleurs dans le module. Déclencher ici
        proposerait le renouvellement un mois trop tôt, tous les mois."""
        assert not loc.au_dernier_mois("2026-01-01", 6, "2026-06-01")
        # Un jour plus tard, en revanche, la suivante passe derrière.
        assert loc.au_dernier_mois("2026-01-01", 6, "2026-06-02")

    def test_sans_entente_il_n_y_a_pas_de_dernier_mois(self):
        assert not loc.au_dernier_mois("", 6, "2026-08-15")

    def test_sans_facturation_il_n_y_a_pas_de_dernier_mois(self):
        """On ne peut pas dire « c'était le dernier » d'un mois jamais
        facturé."""
        assert not loc.au_dernier_mois("2026-03-01", 6, "")

    def test_un_achat_n_a_pas_de_mois_suivant(self):
        assert not loc.au_dernier_mois("2026-03-01", 6, "2026-08-15",
                                       loc.MODE_ACHAT)

    def test_le_statut_le_dit_avant_le_compte_a_rebours(self):
        """Il passe DEVANT « à renouveler » : c'est un signal de
        facturation, et il tombe parfois avant que le délai d'alerte,
        réglable, ne se déclenche."""
        # Entente du 01/04, six mois → échéance au 01/10, encore devant
        # nous. Facturé le 15/09, la suivante tomberait le 15/10 : après.
        statut = loc.statut_entente("2026-04-01", 6, AUJOURDHUI,
                                    derniere_facturation="2026-09-15")
        assert statut == loc.STATUT_DERNIER_MOIS

    def test_il_remonte_dans_a_renouveler_meme_si_l_alerte_est_courte(self):
        """Une alerte réglée à 2 jours ne doit pas faire manquer le seul
        moment où l'on tenait le dossier en main."""
        d = loc.ajouter_dossier(loc.dossier_vide(), "M. DERNIER", "Lit",
                                entente="2026-04-01", validite_mois=6,
                                derniere_facturation="2026-09-15")
        liste = loc.a_renouveler(d, AUJOURDHUI, alerte_j=2)
        assert list(liste["Patient"]) == ["M. DERNIER"]
        assert liste.iloc[0]["Entente"] == loc.STATUT_DERNIER_MOIS


# ---------------------------------------------------------------------------
# Louer hors caisse : aérosols et tensiomètres
# ---------------------------------------------------------------------------

class TestSansEntenteRequise:
    """« Un sous-onglet pour les locations sans besoin d'entente préalable,
    à savoir aérosol et tensiomètre. »

    Tensiomètre : non remboursé, caution 3 000 F.
    Aérosol : remboursé sous conditions, caution 5 000 F.

    Les mêler aux dossiers soumis à entente les afficherait « rien de
    fait » à vie, c'est-à-dire comme un manquement. Ils n'en sont pas un.
    """

    @pytest.mark.parametrize("nom,caution,rembourse", [
        ("Tensiomètre", 3000, "Non remboursé"),
        ("tensiometre OMRON", 3000, "Non remboursé"),
        ("TENSIOMÈTRE bras", 3000, "Non remboursé"),
        ("Aérosol", 5000, "Remboursé sous conditions"),
        ("aerosol Pari Boy", 5000, "Remboursé sous conditions"),
    ])
    def test_le_nom_du_materiel_propose_le_regime_et_la_caution(
            self, nom, caution, rembourse):
        """« Aérosol Pari Boy » et « aerosol » doivent tomber sur la même
        fiche : sinon il faudrait écrire le libellé au caractère près."""
        assert loc.regime_propose(nom) == loc.REGIME_LIBRE
        assert loc.caution_proposee(nom) == caution
        assert loc.remboursement(nom) == rembourse

    def test_le_reste_du_materiel_reste_soumis_a_entente(self):
        """Le défaut penche du côté SURVEILLÉ : un dossier classé hors
        caisse par erreur sortirait des renouvellements en silence."""
        assert loc.regime_propose("Lit médicalisé") == loc.REGIME_ENTENTE
        assert loc.caution_proposee("Lit médicalisé") == 0
        assert loc.remboursement("Lit médicalisé") == ""

    def test_un_tensiometre_n_est_pas_un_dossier_sans_entente(self):
        """Il n'a pas d'entente parce qu'il n'en demande pas — et cela ne
        se lit pas comme « rien de fait »."""
        d = loc.ajouter_dossier(loc.dossier_vide(), "Mme TENSION",
                                "Tensiomètre")
        vue = loc.vue_affichable(d, AUJOURDHUI)
        assert vue.iloc[0]["Entente"] == loc.STATUT_ENTENTE_NON_REQUISE
        assert vue.iloc[0]["Caution (F)"] == 3000

    def test_il_ne_remonte_jamais_dans_a_renouveler(self):
        """Sans cette exclusion, il y resterait à vie : aucun geste ne l'en
        sortirait, puisqu'il n'y a pas d'accord à obtenir."""
        d = loc.ajouter_dossier(loc.dossier_vide(), "Mme TENSION",
                                "Tensiomètre")
        assert loc.a_renouveler(d, AUJOURDHUI).empty

    def test_sa_liste_le_retient_lui_et_pas_les_autres(self):
        d = loc.ajouter_dossier(loc.dossier_vide(), "Mme TENSION",
                                "Tensiomètre")
        d = loc.ajouter_dossier(d, "M. LIT", "Lit médicalisé",
                                entente="2026-09-01")
        liste = loc.sans_entente_requise(d, AUJOURDHUI)
        assert list(liste["Patient"]) == ["Mme TENSION"]
        assert liste.iloc[0]["Remboursement"] == "Non remboursé"

    def test_le_regime_reste_modifiable_a_la_main(self):
        """Une proposition, jamais une contrainte : un cas qui sort de
        l'ordinaire doit pouvoir être reclassé."""
        d = loc.ajouter_dossier(loc.dossier_vide(), "M. CAS", "Aérosol",
                                regime=loc.REGIME_ENTENTE)
        assert d.iloc[0]["Régime"] == loc.REGIME_ENTENTE
        vue = loc.vue_affichable(d, AUJOURDHUI)
        assert vue.iloc[0]["Entente"] == loc.STATUT_SANS_ENTENTE

    def test_un_dossier_d_avant_la_mise_a_jour_se_rattrape(self):
        """Un tensiomètre saisi quand la colonne « Régime » n'existait pas
        se lirait « rien de fait » à vie. Le nom du matériel le rattrape."""
        ancien = pd.DataFrame([{"Patient": "Mme AVANT",
                                "Matériel": "Tensiomètre", "Régime": ""}],
                              columns=loc.COLONNES_DOSSIER).fillna("")
        vue = loc.vue_affichable(ancien, AUJOURDHUI)
        assert vue.iloc[0]["Entente"] == loc.STATUT_ENTENTE_NON_REQUISE


class TestCautions:
    """La caution est de l'argent encaissé qui appartient au patient tant
    qu'il n'a pas rendu l'appareil. Ne pas la suivre, c'est laisser
    5 000 F dans la caisse de quelqu'un d'autre."""

    def _deux_cautions(self):
        d = loc.ajouter_dossier(loc.dossier_vide(), "Mme TENSION",
                                "Tensiomètre")
        return loc.ajouter_dossier(d, "M. SOUFFLE", "Aérosol")

    def test_le_total_detenu_se_compte(self):
        vue = loc.vue_affichable(self._deux_cautions(), AUJOURDHUI)
        assert loc.cautions_detenues(vue) == 8000

    def test_une_caution_rendue_sort_du_total(self):
        d = loc.enregistrer_caution_rendue(self._deux_cautions(),
                                           "Mme TENSION", "Tensiomètre",
                                           AUJOURDHUI)
        vue = loc.vue_affichable(d, AUJOURDHUI)
        assert loc.cautions_detenues(vue) == 5000

    def test_un_montant_negatif_est_refuse(self):
        """Une caution négative, c'est de l'argent que la pharmacie devrait
        au patient sans l'avoir encaissé."""
        assert loc.parser_montant(-3000) == 0
        assert loc.parser_montant("") == 0
        assert loc.parser_montant("pas un montant") == 0

    def test_un_montant_espace_reste_lisible(self):
        """Recopié depuis un tableur, « 3 000 » doit valoir 3000."""
        assert loc.parser_montant("3 000") == 3000

    def test_le_montant_s_affiche_avec_son_unite(self):
        """« 3 000 F » se lit d'un coup d'œil là où « 3000 » se compte."""
        vue = loc.pour_affichage(loc.vue_affichable(self._deux_cautions(),
                                                    AUJOURDHUI))
        assert "3 000 F" in list(vue["Caution (F)"])

    def test_un_dossier_sans_caution_affiche_une_case_vide(self):
        """Une colonne de zéros se lit comme une panne, pas comme « rien à
        encaisser »."""
        d = loc.ajouter_dossier(loc.dossier_vide(), "M. LIT", "Lit")
        vue = loc.pour_affichage(loc.vue_affichable(d, AUJOURDHUI))
        assert list(vue["Caution (F)"]) == [""]

    def test_le_resume_et_le_recap_patient_disent_le_meme_total(self):
        compte = loc.resume(self._deux_cautions(), AUJOURDHUI)
        recap = loc.par_patient(self._deux_cautions(), AUJOURDHUI)
        assert compte["cautions"] == 8000
        assert compte["hors_caisse"] == 2
        assert int(recap["Caution détenue (F)"].sum()) == 8000
