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
    base = {"Patient": "Mme DUPONT", "Matériel loué": "Lit médicalisé",
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
            {"Patient": "M. TRANQUILLE", "Matériel loué": "Fauteuil roulant",
             "Début de location": "2026-01-01", "Entente préalable": "2026-08-01",
             "Validité (mois)": 12, "Dernière facturation": "2026-09-10",
             "Notes": ""},
            # Échéance dans 30 jours : à renouveler.
            {"Patient": "Mme URGENTE", "Matériel loué": "Lit médicalisé",
             "Début de location": "2026-02-01", "Entente préalable": "2026-04-18",
             "Validité (mois)": 6, "Dernière facturation": "2026-09-05",
             "Notes": ""},
            # Expirée, et trois mois de facturation oubliés.
            {"Patient": "M. OUBLIE", "Matériel loué": "Concentrateur O2",
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
        assert compte == {"dossiers": 3, "a_renouveler": 1, "expirees": 1,
                          "a_facturer": 1, "mois_dus": 3}

    def test_un_dossier_vide_ne_plante_rien(self):
        vide = loc.dossier_vide()
        assert loc.a_renouveler(vide, AUJOURDHUI).empty
        assert loc.a_facturer(vide, AUJOURDHUI).empty
        assert loc.resume(vide, AUJOURDHUI)["dossiers"] == 0


class TestClassement:
    def test_par_echeance_au_plus_proche(self):
        """Ce qui expire en premier doit sauter aux yeux."""
        lignes = [
            {"Patient": "B", "Matériel loué": "X", "Début de location": "",
             "Entente préalable": "2026-08-01", "Validité (mois)": 12,
             "Dernière facturation": "", "Notes": ""},
            {"Patient": "A", "Matériel loué": "Y", "Début de location": "",
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
            {"Patient": "SANS", "Matériel loué": "X", "Début de location": "",
             "Entente préalable": "", "Validité (mois)": 6,
             "Dernière facturation": "", "Notes": ""},
            {"Patient": "AVEC", "Matériel loué": "Y", "Début de location": "",
             "Entente préalable": "2026-10-01", "Validité (mois)": 6,
             "Dernière facturation": "", "Notes": ""},
        ]
        vue = loc.vue_affichable(pd.DataFrame(lignes,
                                              columns=loc.COLONNES_DOSSIER),
                                 AUJOURDHUI)
        assert list(vue["Patient"]) == ["AVEC", "SANS"]

    def test_par_patient(self):
        lignes = [
            {"Patient": "Zoé", "Matériel loué": "X", "Début de location": "",
             "Entente préalable": "2026-01-01", "Validité (mois)": 6,
             "Dernière facturation": "", "Notes": ""},
            {"Patient": "Éric", "Matériel loué": "Y", "Début de location": "",
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
            {"Patient": "", "Matériel loué": "Lit", "Début de location": "",
             "Entente préalable": "", "Validité (mois)": 6,
             "Dernière facturation": "", "Notes": ""},
            {"Patient": "Mme MARTIN", "Matériel loué": "", "Début de location": "",
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
