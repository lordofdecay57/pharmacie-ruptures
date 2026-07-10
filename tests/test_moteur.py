# -*- coding: utf-8 -*-
"""Tests du Module 2 — Gestion des ruptures (moteur_ruptures.py).

Logique d'apparition STRICTE + cas de référence (validés en conversation
avec le pharmacien) :
  - Titanoréine : réappro 16 j, stock 18 j → écarté (18 ≥ 16).
  - Ozempic 1 mg : stock 5, ~16,5/mois → ~9 j → retenu, MODÉRÉ.
  - Aranesp 150 : stock 0, réappro dans 2 j → retenu, URGENT, Cmd ≥ 1.

Les fonctions purement partagées (parsing, chargement de fichiers,
statistiques de consommation) sont testées dans test_commun.py. Le Module 1
(stock min/max) est testé dans test_stock_rotation.py.
"""

from datetime import date

import pandas as pd
import pytest

from moteur_ruptures import (ANTICIPER, MODERE, URGENT, Correspondance,
                             _indexer, analyser, apparier, classer_urgence,
                             comparer_a_analyse_precedente,
                             compter_occurrences_historique,
                             compter_reports_reappro, doit_apparaitre,
                             exporter_excel, nom_fichier_sortie,
                             normaliser_cip, probabilite_rupture,
                             quantite_a_commander, rotation_possiblement_sous_estimee,
                             score_priorite, taux_de_service)

DATE_ANALYSE = date(2026, 5, 13)


# ---------------------------------------------------------------------------
# Étape 3 — règle d'apparition STRICTE (le point critique)
# ---------------------------------------------------------------------------

class TestRegleApparition:
    def test_titanoreine_ecartee(self):
        # Réappro dans 16 j, stock 18 j → 18 ≥ 16 → n'apparaît PAS.
        assert doit_apparaitre(stock_jours=18, jours_avant_reappro=16) is False

    def test_stock_insuffisant_avant_reappro(self):
        assert doit_apparaitre(stock_jours=10, jours_avant_reappro=16) is True

    def test_egalite_stricte_ecartee(self):
        # AUCUN buffer : stock_jours == jours_avant_reappro → écarté.
        assert doit_apparaitre(stock_jours=16, jours_avant_reappro=16) is False

    def test_sans_date_seuil_30(self):
        assert doit_apparaitre(stock_jours=29.9, jours_avant_reappro=None) is True
        assert doit_apparaitre(stock_jours=30, jours_avant_reappro=None) is False
        assert doit_apparaitre(stock_jours=45, jours_avant_reappro=None) is False

    def test_stock_zero_apparait_toujours(self):
        assert doit_apparaitre(stock_jours=0, jours_avant_reappro=2) is True
        assert doit_apparaitre(stock_jours=0, jours_avant_reappro=None) is True


# ---------------------------------------------------------------------------
# Étape 6 — classification d'urgence
# ---------------------------------------------------------------------------

class TestUrgence:
    def test_stock_zero_urgent(self):
        assert classer_urgence(0, 0) == URGENT

    def test_trois_jours_urgent(self):
        assert classer_urgence(2, 3) == URGENT

    def test_ozempic_modere(self):
        assert classer_urgence(5, 9.09) == MODERE

    def test_quinze_jours_modere(self):
        assert classer_urgence(10, 15) == MODERE

    def test_plus_de_quinze_anticiper(self):
        assert classer_urgence(20, 22) == ANTICIPER


# ---------------------------------------------------------------------------
# Étape 5 — quantité à commander
# ---------------------------------------------------------------------------

class TestQuantite:
    def test_aranesp_minimum_1(self):
        # Stock 0, ~4/mois, réappro 2 j → cible 0,27 → Cmd = 1 (minimum).
        assert quantite_a_commander(4, 2, 0) == 1

    def test_couverture_30_jours(self):
        # 16,5/mois × 30 j = 16,5 ; stock 5 → ceil(11,5) = 12 (cas Ozempic).
        assert quantite_a_commander(16.5, 30, 5) == 12

    def test_arrondi_superieur(self):
        assert quantite_a_commander(10, 30, 3.5) == 7  # ceil(10 - 3.5)

    def test_conditionnement(self):
        # Cmd brut 7, conditionnement 5 → arrondi au multiple → 10.
        assert quantite_a_commander(10, 30, 3.5, conditionnement=5) == 10


# ---------------------------------------------------------------------------
# Matching produit (CIP prioritaire, fuzzy loggé)
# ---------------------------------------------------------------------------

class TestMatching:
    def test_cip_prioritaire(self):
        # CIP identique mais libellés différents → le CIP doit gagner.
        idx_cip = {"3401": 7}
        corr = apparier("LIBELLE TOTALEMENT DIFFERENT", "3401", idx_cip, {}, [])
        assert corr.index == 7 and corr.methode == "cip"

    def test_exact_normalise(self):
        idx_lib = {"OZEMPIC 1MG": 3}
        corr = apparier("ozempic 1mg ®", "", {}, idx_lib, [])
        assert corr.index == 3 and corr.methode == "exact"

    def test_fuzzy_incertain_marque(self):
        pytest.importorskip("rapidfuzz")
        libs = [("SALBUTAMOL VIATRIS 100UG FL 200D", 1)]
        corr = apparier("SALBUTAMOL VIA", "", {}, {}, libs)
        assert isinstance(corr, Correspondance)
        if corr.index is not None:  # accepté → doit être marqué incertain
            assert corr.methode == "fuzzy"

    def test_aucune_correspondance(self):
        corr = apparier("PRODUIT INTROUVABLE XYZ", "", {}, {}, [])
        assert corr.index is None and corr.methode == "aucune"


class TestCipReels:
    """Formats réels des exports : CIP13 ↔ CIP7, placeholder « 0 »."""

    def test_apparier_cip13_contre_cadencier_cip7(self):
        idx_cip = {"3230077": 4}  # cadencier indexé en CIP7
        corr = apparier("TITANOREINE SUP BT12", "3400932300778",
                        idx_cip, {}, [])
        assert corr.index == 4 and corr.methode == "cip"

    def test_indexation_cip13_cherchee_en_cip7(self):
        df = pd.DataFrame({"Libelle": ["TITANOREINE SUP BT12"],
                           "CIP13": ["3400932300778"]})
        idx_cip, _, _ = _indexer(df, "Libelle", "CIP13")
        assert idx_cip.get("3230077") == 0  # les deux formes indexées
        assert idx_cip.get("3400932300778") == 0

    def test_cip_zero_traite_comme_absent(self):
        # Placeholder « 0 » des exports : ne doit jamais servir au matching.
        corr = apparier("PRODUIT X", normaliser_cip("0"), {"0": 3}, {}, [])
        assert corr.methode != "cip"


# ---------------------------------------------------------------------------
# Analyse de bout en bout (les onglets de décision)
# ---------------------------------------------------------------------------

def _mapping():
    return {
        "cadencier": {"libelle": "Produit", "cip": "CIP", "stock": "Stock",
                      "ventes": ["V1", "V2", "V3"], "conditionnement": None,
                      "commande_en_cours": None, "peremption": None},
        "gpnc": {"libelle": "Libellé", "cip": "CIP", "date_reappro": "Réappro"},
        "unipharma": {"libelle": "Désignation", "cip": "CIP"},
    }


def _jeu_de_donnees():
    """Jeu reproduisant les cas de la conversation du 13/05/2026."""
    cadencier = pd.DataFrame({
        "Produit": ["TITANOREINE SUPPO", "OZEMPIC 1MG", "ARANESP 150",
                    "DALACINE 300", "PRODUIT DORMANT", "TAHOR 10"],
        "CIP": ["1001", "1002", "1003", "1004", "1005", "1006"],
        "Stock": [18 * 0.2, 5, 0, 2, 4, 0],       # Titanoréine : 18 j × 0,2/j
        "V1": [6, 16.5, 4, 13, 0, 8],
        "V2": [6, 16.5, 4, 13, 0, 8],
        "V3": [6, 16.5, 4, 13, 0, 8],             # rotations mensuelles stables
    })
    ruptures_gpnc = pd.DataFrame({
        "Libellé": ["TITANOREINE SUPPO", "OZEMPIC 1MG", "ARANESP 150",
                    "DALACINE 300", "PRODUIT DORMANT", "TAHOR 10",
                    "PRODUIT NON VENDU"],
        "CIP": ["1001", "1002", "1003", "1004", "1005", "1006", "9999"],
        # Titanoréine : réappro à J+16 (29/05) alors que le stock couvre 18 j.
        "Réappro": ["29/05/2026", "", "15/05/2026", "", "", "04/06/2026", ""],
    })
    ruptures_unipharma = pd.DataFrame({
        "Désignation": ["DALACINE 300", "TAHOR 10"],
        "CIP": ["1004", "1006"],
    })
    return cadencier, ruptures_gpnc, ruptures_unipharma


class TestAnalyseComplete:
    @pytest.fixture()
    def resultat(self):
        cad, gpnc, uni = _jeu_de_donnees()
        return analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE, "annuelle")

    def test_titanoreine_absente_des_onglets_1_et_2(self, resultat):
        # 18 j de stock ≥ 16 j avant réappro → nulle part sauf traçabilité.
        assert "TITANOREINE SUPPO" not in resultat.onglet1["Produit"].values
        assert "TITANOREINE SUPPO" not in resultat.onglet2["Produit"].values
        ligne = resultat.onglet3[resultat.onglet3["Produit"] == "TITANOREINE SUPPO"]
        assert ligne["Décision"].iloc[0] == "Écarté"

    def test_ozempic_retenu_modere_cmd_12(self, resultat):
        ligne = resultat.onglet1[resultat.onglet1["Produit"] == "OZEMPIC 1MG"]
        assert len(ligne) == 1
        assert ligne["Urgence"].iloc[0] == MODERE
        assert ligne["Qté à commander (Cmd)"].iloc[0] == 12  # 16,5 − 5 → ceil

    def test_aranesp_urgent_cmd_1(self, resultat):
        ligne = resultat.onglet1[resultat.onglet1["Produit"] == "ARANESP 150"]
        assert len(ligne) == 1
        assert ligne["Urgence"].iloc[0] == URGENT
        assert ligne["Qté à commander (Cmd)"].iloc[0] >= 1

    def test_dalacine_onglet2_pas_de_solution(self, resultat):
        # Rupture GPNC + UNIPHARMA → onglet 2, pas onglet 1.
        assert "DALACINE 300" in resultat.onglet2["Produit"].values
        assert "DALACINE 300" not in resultat.onglet1["Produit"].values

    def test_onglet2_stock_zero_en_premier(self, resultat):
        # TAHOR (stock 0) doit passer devant DALACINE (stock 2).
        assert resultat.onglet2["Produit"].iloc[0] == "TAHOR 10"

    def test_produit_dormant_ecarte_rotation_nulle(self, resultat):
        ligne = resultat.onglet3[resultat.onglet3["Produit"] == "PRODUIT DORMANT"]
        assert ligne["Décision"].iloc[0] == "Écarté"
        assert "Rotation nulle" in ligne["Motif"].iloc[0]

    def test_produit_non_vendu_trace_mais_ecarte(self, resultat):
        ligne = resultat.onglet3[resultat.onglet3["Produit"] == "PRODUIT NON VENDU"]
        assert ligne["Vendu (O/N)"].iloc[0] == "N"
        assert ligne["Décision"].iloc[0] == "Écarté"

    def test_urgents_tries_en_premier(self, resultat):
        urgences = list(resultat.onglet1["Urgence"])
        assert urgences == sorted(urgences, key=[URGENT, MODERE, ANTICIPER].index)

    def test_resume(self, resultat):
        assert resultat.resume["ruptures_gpnc"] == 7
        assert resultat.resume["a_commander"] == len(resultat.onglet1)
        assert resultat.resume["sans_solution"] == 2

    def test_toutes_les_ruptures_tracees_onglet3(self, resultat):
        assert len(resultat.onglet3) == 7  # audit complet, retenus ET écartés


class TestReapproPassee:
    def test_date_passee_traitee_comme_sans_date(self):
        cad, gpnc, uni = _jeu_de_donnees()
        # Réappro déjà passée pour Ozempic → règle des 30 jours + alerte.
        gpnc.loc[gpnc["Libellé"] == "OZEMPIC 1MG", "Réappro"] = "01/05/2026"
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE)
        ligne = resultat.onglet1[resultat.onglet1["Produit"] == "OZEMPIC 1MG"]
        assert len(ligne) == 1  # 9 j < 30 → toujours retenu
        assert any("dépassée" in a for a in resultat.alertes)


class TestExportRuptures:
    def test_export_excel_cinq_onglets(self):
        cad, gpnc, uni = _jeu_de_donnees()
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE)
        contenu = exporter_excel(resultat)
        relu = pd.read_excel(pd.io.common.BytesIO(contenu), sheet_name=None)
        assert set(relu) == {"À commander UNIPHARMA", "Rupture GPNC+UNIPHARMA",
                             "Vigilance stock", "Écartés de justesse",
                             "Analyse complète"}

    def test_nom_fichier(self):
        assert nom_fichier_sortie(DATE_ANALYSE) == "commande_ruptures_2026-05-13.xlsx"


# ---------------------------------------------------------------------------
# Fiabilité de la rotation (indice de rupture passée)
# ---------------------------------------------------------------------------

class TestFiabiliteRotation:
    def test_mois_a_zero_signale(self):
        # Ventes stables sauf un mois à 0 → rupture passée probable.
        assert rotation_possiblement_sous_estimee([10, 0, 10]) is True

    def test_toutes_ventes_nulles_non_signale(self):
        # Rotation nulle réelle (produit non vendu) : pas un indice de rupture.
        assert rotation_possiblement_sous_estimee([0, 0, 0]) is False

    def test_aucun_zero_non_signale(self):
        assert rotation_possiblement_sous_estimee([10, 12, 8]) is False

    def test_liste_vide_non_signale(self):
        assert rotation_possiblement_sous_estimee([]) is False


# ---------------------------------------------------------------------------
# Historique (suivi d'une analyse à l'autre)
# ---------------------------------------------------------------------------

class TestHistorique:
    def test_compte_occurrences_anterieures(self):
        historique = pd.DataFrame({
            "Date analyse": ["2026-04-29", "2026-05-06", "2026-05-06"],
            "Produit": ["OZEMPIC 1MG", "OZEMPIC 1MG", "ARANESP 150"],
        })
        assert compter_occurrences_historique(
            "OZEMPIC 1MG", historique, date(2026, 5, 13)) == 2

    def test_ignore_dates_egales_ou_futures(self):
        historique = pd.DataFrame({
            "Date analyse": ["2026-05-13"], "Produit": ["OZEMPIC 1MG"],
        })
        assert compter_occurrences_historique(
            "OZEMPIC 1MG", historique, date(2026, 5, 13)) == 0

    def test_historique_vide(self):
        assert compter_occurrences_historique(
            "OZEMPIC 1MG", pd.DataFrame(), date(2026, 5, 13)) == 0


# ---------------------------------------------------------------------------
# Suivi quotidien (nouveaux / résolus par rapport à l'analyse précédente)
# ---------------------------------------------------------------------------

class TestComparaisonQuotidienne:
    HISTORIQUE = pd.DataFrame({
        "Date analyse": ["2026-05-11", "2026-05-12", "2026-05-12"],
        "Produit": ["VENTOLINE 100", "OZEMPIC 1MG", "ARANESP 150"],
    })

    def test_nouveaux_et_resolus(self):
        # Hier (12/05) : Ozempic + Aranesp. Aujourd'hui : Ozempic + Dalacine.
        prec, nouveaux, resolus = comparer_a_analyse_precedente(
            ["OZEMPIC 1MG", "DALACINE 300"], self.HISTORIQUE, date(2026, 5, 13))
        assert prec == date(2026, 5, 12)  # la plus récente antérieure, pas le 11
        assert nouveaux == ["DALACINE 300"]
        assert resolus == ["ARANESP 150"]

    def test_premiere_analyse_tout_nouveau(self):
        prec, nouveaux, resolus = comparer_a_analyse_precedente(
            ["OZEMPIC 1MG"], pd.DataFrame(), date(2026, 5, 13))
        assert prec is None
        assert nouveaux == ["OZEMPIC 1MG"] and resolus == []

    def test_ignore_l_analyse_du_jour_meme(self):
        # Une ré-analyse le même jour ne doit pas se comparer à elle-même.
        historique = pd.DataFrame({
            "Date analyse": ["2026-05-13"], "Produit": ["OZEMPIC 1MG"],
        })
        prec, nouveaux, _ = comparer_a_analyse_precedente(
            ["OZEMPIC 1MG"], historique, date(2026, 5, 13))
        assert prec is None and nouveaux == ["OZEMPIC 1MG"]


# ---------------------------------------------------------------------------
# Commande en cours (évite de recommander ce qui est déjà en route)
# ---------------------------------------------------------------------------

class TestCommandeEnCours:
    def test_reduit_la_quantite_et_le_stock_jours(self):
        cad, gpnc, uni = _jeu_de_donnees()
        cad["En cours"] = [0, 5, 0, 0, 0, 0]  # 5 déjà commandées pour Ozempic
        mapping = _mapping()
        mapping["cadencier"]["commande_en_cours"] = "En cours"
        resultat = analyser(cad, gpnc, uni, mapping, DATE_ANALYSE, "annuelle")
        ligne = resultat.onglet1[resultat.onglet1["Produit"] == "OZEMPIC 1MG"]
        # Stock effectif 5+5=10 → jours ≈ 18,2 → À ANTICIPER, Cmd = ceil(16,5−10)
        assert ligne["Urgence"].iloc[0] == ANTICIPER
        assert ligne["Qté à commander (Cmd)"].iloc[0] == 7
        assert ligne["Commande en cours"].iloc[0] == 5

    def test_non_fourni_par_defaut(self):
        cad, gpnc, uni = _jeu_de_donnees()
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE, "annuelle")
        ligne = resultat.onglet1[resultat.onglet1["Produit"] == "OZEMPIC 1MG"]
        assert ligne["Commande en cours"].iloc[0] == ""


# ---------------------------------------------------------------------------
# Péremption (DLUO proche)
# ---------------------------------------------------------------------------

class TestPeremption:
    def test_alerte_peremption_proche(self):
        cad, gpnc, uni = _jeu_de_donnees()
        cad["DLUO"] = ["", "", "", "", "", "01/08/2026"]  # TAHOR 10 → proche
        mapping = _mapping()
        mapping["cadencier"]["peremption"] = "DLUO"
        resultat = analyser(cad, gpnc, uni, mapping, DATE_ANALYSE, "annuelle")
        assert any("péremption proche" in a for a in resultat.alertes)

    def test_pas_d_alerte_si_lointaine(self):
        cad, gpnc, uni = _jeu_de_donnees()
        cad["DLUO"] = ["", "", "", "", "", "01/08/2028"]
        mapping = _mapping()
        mapping["cadencier"]["peremption"] = "DLUO"
        resultat = analyser(cad, gpnc, uni, mapping, DATE_ANALYSE, "annuelle")
        assert not any("péremption proche" in a for a in resultat.alertes)


# ---------------------------------------------------------------------------
# Anticipation — vigilance stock (ruptures à venir hors ruptures GPNC)
# ---------------------------------------------------------------------------

class TestVigilance:
    def test_produit_faible_couverture_detecte(self):
        cad, gpnc, uni = _jeu_de_donnees()
        # Eliquis : 30/mois, stock 3 → 3 j de couverture, PAS en rupture GPNC.
        cad.loc[len(cad)] = ["ELIQUIS 5MG", "2001", 3, 30, 30, 30]
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE)
        assert "ELIQUIS 5MG" in resultat.vigilance["Produit"].values
        assert resultat.resume["vigilance"] == 1

    def test_produit_bien_couvert_absent(self):
        cad, gpnc, uni = _jeu_de_donnees()
        cad.loc[len(cad)] = ["ELIQUIS 5MG", "2001", 60, 30, 30, 30]  # 60 j
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE)
        assert "ELIQUIS 5MG" not in resultat.vigilance["Produit"].values

    def test_produits_en_rupture_gpnc_non_dupliques(self):
        # Aranesp est déjà traité via les ruptures GPNC → pas en vigilance.
        cad, gpnc, uni = _jeu_de_donnees()
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE)
        assert "ARANESP 150" not in resultat.vigilance["Produit"].values

    def test_produit_dormant_ignore(self):
        # Rotation nulle → rien à anticiper, pas de fausse alerte.
        cad, gpnc_vide, uni = _jeu_de_donnees()
        resultat = analyser(cad, gpnc_vide.iloc[0:0], uni, _mapping(),
                            DATE_ANALYSE)
        assert "PRODUIT DORMANT" not in resultat.vigilance["Produit"].values

    def test_seuil_parametrable(self):
        cad, gpnc, uni = _jeu_de_donnees()
        cad.loc[len(cad)] = ["ELIQUIS 5MG", "2001", 10, 30, 30, 30]  # 10 j
        strict = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE,
                          seuil_vigilance_jours=7)
        large = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE,
                         seuil_vigilance_jours=15)
        assert "ELIQUIS 5MG" not in strict.vigilance["Produit"].values
        assert "ELIQUIS 5MG" in large.vigilance["Produit"].values


# ---------------------------------------------------------------------------
# Anticipation — écartés de justesse (règle stricte, marge faible)
# ---------------------------------------------------------------------------

class TestEcartesJustesse:
    def test_titanoreine_marge_2_jours_listee(self):
        # Stock 18 j, réappro 16 j → écartée MAIS marge 2 j < 3 → visible.
        cad, gpnc, uni = _jeu_de_donnees()
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE)
        assert "TITANOREINE SUPPO" in resultat.ecartes_justesse["Produit"].values
        ligne = resultat.ecartes_justesse[
            resultat.ecartes_justesse["Produit"] == "TITANOREINE SUPPO"]
        assert ligne["Marge (jours)"].iloc[0] == pytest.approx(2.0, abs=0.1)
        # Elle reste ÉCARTÉE des onglets de commande (règle stricte intacte).
        assert "TITANOREINE SUPPO" not in resultat.onglet1["Produit"].values

    def test_marge_confortable_non_listee(self):
        cad, gpnc, uni = _jeu_de_donnees()
        cad.loc[cad["Produit"] == "TITANOREINE SUPPO", "Stock"] = 30 * 0.2  # 30 j
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE)
        assert ("TITANOREINE SUPPO"
                not in resultat.ecartes_justesse["Produit"].values)

    def test_seuil_marge_parametrable(self):
        cad, gpnc, uni = _jeu_de_donnees()
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE,
                            seuil_marge_jours=1)  # marge 2 j ≥ 1 → non listée
        assert ("TITANOREINE SUPPO"
                not in resultat.ecartes_justesse["Produit"].values)


# ---------------------------------------------------------------------------
# Anticipation — délai de livraison UNIPHARMA
# ---------------------------------------------------------------------------

class TestDelaiLivraison:
    def test_cmd_couvre_le_delai(self):
        cad, gpnc, uni = _jeu_de_donnees()
        sans = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE)
        avec = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE,
                        delai_livraison_jours=2)
        # Ozempic sans date : 30 j → Cmd 12 ; 32 j → ceil(17,6 − 5) = 13.
        cmd_sans = sans.onglet1.loc[sans.onglet1["Produit"] == "OZEMPIC 1MG",
                                    "Qté à commander (Cmd)"].iloc[0]
        cmd_avec = avec.onglet1.loc[avec.onglet1["Produit"] == "OZEMPIC 1MG",
                                    "Qté à commander (Cmd)"].iloc[0]
        assert cmd_sans == 12 and cmd_avec == 13

    def test_delai_ne_change_pas_la_regle_d_apparition(self):
        # Titanoréine reste écartée même avec un délai : la règle stricte
        # d'apparition n'est pas modifiée par le délai de livraison.
        cad, gpnc, uni = _jeu_de_donnees()
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE,
                            delai_livraison_jours=5)
        assert "TITANOREINE SUPPO" not in resultat.onglet1["Produit"].values


# ---------------------------------------------------------------------------
# Anticipation — rotation prudente (max des deux moyennes)
# ---------------------------------------------------------------------------

class TestRotationPrudente:
    def test_produit_en_croissance_mieux_couvert(self):
        # 12 mois de recul pour que les deux moyennes DIFFÈRENT vraiment :
        # annuelle (9×10 + 3×20)/12 = 12,5 < 3 mois 20 → prudent retient 20.
        cad, gpnc, uni = _jeu_de_donnees()
        for i in range(4, 13):  # V4..V12 : 12 colonnes de ventes au total
            cad[f"V{i}"] = 10.0
        colonnes = [f"V{i}" for i in range(4, 13)] + ["V1", "V2", "V3"]
        cad.loc[cad["Produit"] == "OZEMPIC 1MG",
                ["V1", "V2", "V3"]] = [20, 20, 20]
        mapping = _mapping()
        mapping["cadencier"]["ventes"] = colonnes  # chrono, récent en dernier
        normal = analyser(cad, gpnc, uni, mapping, DATE_ANALYSE, "annuelle")
        prudent = analyser(cad, gpnc, uni, mapping, DATE_ANALYSE, "annuelle",
                           rotation_prudente=True)
        rot_normal = normal.onglet1.loc[
            normal.onglet1["Produit"] == "OZEMPIC 1MG", "Rotation/mois"].iloc[0]
        rot_prudent = prudent.onglet1.loc[
            prudent.onglet1["Produit"] == "OZEMPIC 1MG", "Rotation/mois"].iloc[0]
        assert rot_normal == pytest.approx(12.5)
        assert rot_prudent == pytest.approx(20)  # max(annuelle, 3 mois)


# ---------------------------------------------------------------------------
# Anticipation — dates de réappro repoussées (fournisseur peu fiable)
# ---------------------------------------------------------------------------

class TestReportsReappro:
    def test_glissement_detecte_depuis_l_historique(self):
        historique = pd.DataFrame({
            "Date analyse": ["2026-05-11", "2026-05-12"],
            "Produit": ["ARANESP 150", "ARANESP 150"],
            "Date réappro": ["13/05/2026", "15/05/2026"],  # déjà repoussée 1×
        })
        assert compter_reports_reappro("ARANESP 150", historique) == 1

    def test_glissement_du_jour_compte(self):
        historique = pd.DataFrame({
            "Date analyse": ["2026-05-12"], "Produit": ["ARANESP 150"],
            "Date réappro": ["13/05/2026"],
        })
        # Aujourd'hui la date annoncée passe au 20/05 → 1 report dès ce jour.
        assert compter_reports_reappro("ARANESP 150", historique,
                                       date(2026, 5, 20)) == 1

    def test_date_stable_aucun_report(self):
        historique = pd.DataFrame({
            "Date analyse": ["2026-05-11", "2026-05-12"],
            "Produit": ["ARANESP 150", "ARANESP 150"],
            "Date réappro": ["15/05/2026", "15/05/2026"],
        })
        assert compter_reports_reappro("ARANESP 150", historique,
                                       date(2026, 5, 15)) == 0

    def test_ancien_historique_sans_colonne(self):
        historique = pd.DataFrame({
            "Date analyse": ["2026-05-12"], "Produit": ["ARANESP 150"],
        })
        assert compter_reports_reappro("ARANESP 150", historique) == 0

    def test_alerte_dans_l_analyse(self):
        cad, gpnc, uni = _jeu_de_donnees()
        historique = pd.DataFrame({
            "Date analyse": ["2026-05-12"], "Produit": ["ARANESP 150"],
            "Date réappro": ["13/05/2026"], "Urgence": ["🔴 URGENT"],
            "Qté à commander (Cmd)": [1],
        })
        # Le jeu annonce le 15/05 pour Aranesp → repoussée vs le 13/05 d'hier.
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE,
                            historique=historique)
        assert any("repoussée 1 fois" in a for a in resultat.alertes)


# ---------------------------------------------------------------------------
# Anticipation — rupture longue (ventes écrasées à 0 mais déjà signalé)
# ---------------------------------------------------------------------------

class TestRuptureLongue:
    def test_deja_signale_passe_en_a_verifier(self):
        cad, gpnc, uni = _jeu_de_donnees()
        # Dalacine : plus aucune vente sur la période (rupture longue).
        cad.loc[cad["Produit"] == "DALACINE 300", ["V1", "V2", "V3"]] = [0, 0, 0]
        historique = pd.DataFrame({
            "Date analyse": ["2026-05-06"], "Produit": ["DALACINE 300"],
            "Urgence": ["🟡 MODÉRÉ"], "Qté à commander (Cmd)": [13],
            "Date réappro": [""],
        })
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE,
                            historique=historique)
        ligne = resultat.onglet3[resultat.onglet3["Produit"] == "DALACINE 300"]
        assert ligne["Décision"].iloc[0] == "À vérifier"
        assert any("rupture longue" in a for a in resultat.alertes)

    def test_jamais_signale_reste_ecarte(self):
        cad, gpnc, uni = _jeu_de_donnees()
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE)
        ligne = resultat.onglet3[resultat.onglet3["Produit"] == "PRODUIT DORMANT"]
        assert ligne["Décision"].iloc[0] == "Écarté"


# ---------------------------------------------------------------------------
# Vigilance — plancher de rotation (anti-bruit)
# ---------------------------------------------------------------------------

class TestVigilanceRotationMin:
    def test_rotation_lente_ignoree_par_defaut(self):
        cad, gpnc, uni = _jeu_de_donnees()
        # 2/mois < plancher 5 : stock 0 mais pas de vigilance (bruit).
        cad.loc[len(cad)] = ["HOMEOPATHIE RARE", "2002", 0, 2, 2, 2]
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE)
        assert "HOMEOPATHIE RARE" not in resultat.vigilance["Produit"].values

    def test_plancher_reglable(self):
        cad, gpnc, uni = _jeu_de_donnees()
        cad.loc[len(cad)] = ["HOMEOPATHIE RARE", "2002", 0, 2, 2, 2]
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE,
                            rotation_min_vigilance=1)
        assert "HOMEOPATHIE RARE" in resultat.vigilance["Produit"].values


# ---------------------------------------------------------------------------
# Correctifs issus de l'audit de correction
# ---------------------------------------------------------------------------

class TestCorrectifsAudit:
    def test_reanalyse_antidatee_ignore_les_annonces_futures(self):
        # Une ré-analyse antidatée ne doit pas se comparer à des annonces
        # enregistrées APRÈS sa propre date (audit A3/C3).
        cad, gpnc, uni = _jeu_de_donnees()
        historique = pd.DataFrame({
            "Date analyse": ["2026-05-20"], "Produit": ["ARANESP 150"],
            "Urgence": ["🔴 URGENT"], "Qté à commander (Cmd)": [1],
            "Date réappro": ["13/05/2026"],
        })
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE,
                            historique=historique)
        assert not any("repoussée" in a for a in resultat.alertes)

    def test_lignes_surveillance_hors_comparatif_quotidien(self):
        # Un écarté de justesse mémorisé ne compte ni comme « déjà signalé »
        # ni comme « résolu » dans le comparatif (audit B4).
        historique = pd.DataFrame({
            "Date analyse": ["2026-05-12", "2026-05-12"],
            "Produit": ["TITANOREINE SUPPO", "OZEMPIC 1MG"],
            "Urgence": ["⚠️ SURVEILLANCE", "🟡 MODÉRÉ"],
            "Qté à commander (Cmd)": ["", 12],
            "Date réappro": ["29/05/2026", ""],
            "Type": ["surveillance", "commande"],
        })
        assert compter_occurrences_historique(
            "TITANOREINE SUPPO", historique, date(2026, 5, 13)) == 0
        _, nouveaux, resolus = comparer_a_analyse_precedente(
            ["OZEMPIC 1MG"], historique, date(2026, 5, 13))
        assert nouveaux == [] and resolus == []

    def test_surveillance_alimente_le_suivi_des_reports(self):
        # MAIS sa date annoncée sert au suivi des réappros repoussées :
        # Titanoréine annonce le 29/05 dans le jeu, hier disait le 25/05.
        cad, gpnc, uni = _jeu_de_donnees()
        historique = pd.DataFrame({
            "Date analyse": ["2026-05-12"], "Produit": ["TITANOREINE SUPPO"],
            "Urgence": ["⚠️ SURVEILLANCE"], "Qté à commander (Cmd)": [""],
            "Date réappro": ["25/05/2026"], "Type": ["surveillance"],
        })
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE,
                            historique=historique)
        assert any("TITANOREINE" in a and "repoussée 1 fois" in a
                   for a in resultat.alertes)
        ligne = resultat.ecartes_justesse[
            resultat.ecartes_justesse["Produit"] == "TITANOREINE SUPPO"]
        assert "repoussée 1 fois" in ligne["Commentaire"].iloc[0]

    def test_report_signale_aussi_sur_onglet2(self):
        # Rupture chez les deux + date repoussée → commentaire enrichi (B4).
        cad, gpnc, uni = _jeu_de_donnees()
        gpnc.loc[gpnc["Libellé"] == "TAHOR 10", "Réappro"] = "10/06/2026"
        historique = pd.DataFrame({
            "Date analyse": ["2026-05-12"], "Produit": ["TAHOR 10"],
            "Urgence": ["❌ SANS SOLUTION"], "Qté à commander (Cmd)": [""],
            "Date réappro": ["04/06/2026"], "Type": ["commande"],
        })
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE,
                            historique=historique)
        ligne = resultat.onglet2[resultat.onglet2["Produit"] == "TAHOR 10"]
        assert "repoussée 1 fois" in ligne["Commentaire"].iloc[0]


# ---------------------------------------------------------------------------
# Correction des faux zéros — effet sur l'analyse complète (la fonction pure
# corriger_faux_zeros est testée dans test_commun.py)
# ---------------------------------------------------------------------------

class TestCorrectionFauxZerosAnalyse:
    def test_analyse_corrige_la_rotation(self):
        # Dalacine avec un mois de rupture : [13, 0, 13] → rotation 13, pas 8,7.
        cad, gpnc, uni = _jeu_de_donnees()
        cad.loc[cad["Produit"] == "DALACINE 300", ["V1", "V2", "V3"]] = [13, 0, 13]
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE)
        ligne = resultat.onglet2[resultat.onglet2["Produit"] == "DALACINE 300"]
        assert ligne["Rotation/mois"].iloc[0] == pytest.approx(13.0)

    def test_desactivable(self):
        cad, gpnc, uni = _jeu_de_donnees()
        cad.loc[cad["Produit"] == "DALACINE 300", ["V1", "V2", "V3"]] = [13, 0, 13]
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE,
                            corriger_ruptures_passees=False)
        ligne = resultat.onglet2[resultat.onglet2["Produit"] == "DALACINE 300"]
        assert ligne["Rotation/mois"].iloc[0] == pytest.approx(8.7, abs=0.1)


# ---------------------------------------------------------------------------
# Probabilité de rupture à horizon (utilisée par le score de priorité)
# ---------------------------------------------------------------------------

class TestProbabiliteRupture:
    def test_stock_nul_demande_active(self):
        assert probabilite_rupture(0, 30, [30, 30, 30], 7) > 0.99

    def test_stock_confortable(self):
        # 60 j de stock, demande stable → risque à 7 j quasi nul.
        assert probabilite_rupture(60, 30, [30, 30, 30, 30], 7) < 0.01

    def test_stock_egal_demande_moyenne(self):
        # Stock = demande moyenne de l'horizon → ~50 % par symétrie.
        proba = probabilite_rupture(7, 30, [20, 30, 40], 7)
        assert proba == pytest.approx(0.5, abs=0.05)

    def test_sans_variabilite_deterministe(self):
        assert probabilite_rupture(5, 30, [30, 30], 7) == 1.0   # 7 j = 7 > 5
        assert probabilite_rupture(10, 30, [30, 30], 7) == 0.0  # 10 > 7


class TestScorePriorite:
    def test_a_risque_devant_c_a_sec(self):
        # Produit A à fort risque > produit C déjà à sec : le volume pèse.
        score_a = score_priorite(0.9, "A")
        score_c = score_priorite(1.0, "C")
        assert score_a > score_c

    def test_bornes(self):
        assert score_priorite(1.0, "A", reports=2) == 100
        assert score_priorite(0.0, "C") == 6

    def test_onglet1_trie_par_priorite(self):
        cad, gpnc, uni = _jeu_de_donnees()
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE)
        priorites = list(resultat.onglet1["Priorité"])
        assert priorites == sorted(priorites, reverse=True)
        assert "Classe" in resultat.onglet1.columns
        assert "P(rupture 7 j)" in resultat.onglet1.columns


class TestPolitiqueAbc:
    def test_desactivee_reference_intacte(self):
        # OFF (défaut) : Ozempic garde sa Cmd de référence (12, cible 30 j).
        cad, gpnc, uni = _jeu_de_donnees()
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE)
        ligne = resultat.onglet1[resultat.onglet1["Produit"] == "OZEMPIC 1MG"]
        assert ligne["Qté à commander (Cmd)"].iloc[0] == 12

    def test_activee_cible_par_classe(self):
        # ON : Ozempic est classe A → cible 21 j → ceil(16,5/30×21 − 5) = 7.
        cad, gpnc, uni = _jeu_de_donnees()
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE,
                            politique_abc=True)
        ligne = resultat.onglet1[resultat.onglet1["Produit"] == "OZEMPIC 1MG"]
        assert ligne["Classe"].iloc[0] == "A"
        assert ligne["Qté à commander (Cmd)"].iloc[0] == 7

    def test_regle_apparition_inchangee(self):
        # La politique ABC ne fait ni apparaître ni disparaître un produit.
        cad, gpnc, uni = _jeu_de_donnees()
        avec = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE,
                        politique_abc=True)
        sans = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE)
        assert set(avec.onglet1["Produit"]) == set(sans.onglet1["Produit"])


# ---------------------------------------------------------------------------
# Taux de service (métrique de RUPTURES — dépend de l'historique de ce
# module, indépamment du Module 1 « stock en rotation »)
# ---------------------------------------------------------------------------

class TestTauxDeService:
    def test_taux_de_service_calcule(self):
        historique = pd.DataFrame({
            "Date analyse": ["2026-05-11", "2026-05-12"],
            "Produit": ["OZEMPIC 1MG", "OZEMPIC 1MG"],
            "Urgence": ["🟡 MODÉRÉ", "🟡 MODÉRÉ"],
            "Qté à commander (Cmd)": [12, 12],
            "Date réappro": ["", ""], "Type": ["commande", "commande"],
        })
        # 2 produits A suivis sur 2 jours ; Ozempic en rupture les 2 jours
        # → 2 ruptures / 4 couples → taux de service 50 %.
        taux, jours = taux_de_service(["OZEMPIC 1MG", "ARANESP 150"],
                                      historique, date(2026, 5, 13))
        assert jours == 2
        assert taux == pytest.approx(0.5)

    def test_taux_sans_historique(self):
        taux, jours = taux_de_service(["X"], pd.DataFrame(), date(2026, 5, 13))
        assert taux is None and jours == 0
