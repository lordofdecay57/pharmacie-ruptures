# -*- coding: utf-8 -*-
"""Tests du moteur métier — logique d'apparition STRICTE + cas de référence.

Cas connus (validés en conversation avec le pharmacien) :
  - Titanoréine : réappro 16 j, stock 18 j → écarté (18 ≥ 16).
  - Ozempic 1 mg : stock 5, ~16,5/mois → ~9 j → retenu, MODÉRÉ.
  - Aranesp 150 : stock 0, réappro dans 2 j → retenu, URGENT, Cmd ≥ 1.
"""

import math
from datetime import date

import pandas as pd
import pytest

from moteur_ruptures import (ANTICIPER, MODERE, URGENT, Correspondance,
                             analyser, apparier, calculer_rotation_mensuelle,
                             calculer_stock_jours, charger_fichier,
                             classer_urgence, doit_apparaitre, exporter_excel,
                             nom_fichier_sortie, normaliser_cip,
                             normaliser_libelle, parser_date, parser_nombre,
                             quantite_a_commander)

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
# Étape 2 — stock en jours
# ---------------------------------------------------------------------------

class TestStockJours:
    def test_ozempic(self):
        # Stock 5, 16,5/mois → 5 / (16,5/30) ≈ 9,09 j.
        assert calculer_stock_jours(5, 16.5) == pytest.approx(9.09, abs=0.01)

    def test_stock_zero(self):
        assert calculer_stock_jours(0, 8) == 0.0

    def test_rotation_nulle_infini(self):
        # Division par zéro gérée : rotation nulle → couverture infinie.
        assert math.isinf(calculer_stock_jours(5, 0))


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
# Rotation annuelle vs 3 mois
# ---------------------------------------------------------------------------

class TestRotation:
    VENTES = [10, 10, 10, 10, 10, 10, 10, 10, 10, 20, 20, 20]  # récent en dernier

    def test_annuelle(self):
        assert calculer_rotation_mensuelle(self.VENTES, "annuelle") == pytest.approx(12.5)

    def test_trois_mois(self):
        assert calculer_rotation_mensuelle(self.VENTES, "3mois") == pytest.approx(20)

    def test_virgule_francaise(self):
        assert calculer_rotation_mensuelle(["16,5"], "annuelle") == pytest.approx(16.5)

    def test_vide(self):
        assert calculer_rotation_mensuelle([], "annuelle") == 0.0


# ---------------------------------------------------------------------------
# Normalisation / parsing
# ---------------------------------------------------------------------------

class TestParsing:
    def test_normaliser_libelle(self):
        assert (normaliser_libelle("  Titanoréine® suppo. B/12 ")
                == "TITANOREINE SUPPO B 12")

    def test_normaliser_cip_float_excel(self):
        assert normaliser_cip("3400930123456.0") == "3400930123456"

    def test_parser_nombre(self):
        assert parser_nombre("16,5") == 16.5
        assert parser_nombre(None) == 0.0
        assert parser_nombre("") == 0.0

    def test_parser_date_formats(self):
        assert parser_date("15/05/2026") == date(2026, 5, 15)
        assert parser_date("2026-05-15") == date(2026, 5, 15)
        assert parser_date("") is None
        assert parser_date("n'importe quoi illisible xyz") is None


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


# ---------------------------------------------------------------------------
# Analyse de bout en bout (les 3 onglets)
# ---------------------------------------------------------------------------

def _mapping():
    return {
        "cadencier": {"libelle": "Produit", "cip": "CIP", "stock": "Stock",
                      "ventes": ["V1", "V2", "V3"], "conditionnement": None},
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


# ---------------------------------------------------------------------------
# Export Excel + chargement de fichiers
# ---------------------------------------------------------------------------

class TestExportEtChargement:
    def test_export_excel_trois_onglets(self):
        cad, gpnc, uni = _jeu_de_donnees()
        resultat = analyser(cad, gpnc, uni, _mapping(), DATE_ANALYSE)
        contenu = exporter_excel(resultat)
        relu = pd.read_excel(pd.io.common.BytesIO(contenu), sheet_name=None)
        assert set(relu) == {"À commander UNIPHARMA", "Rupture GPNC+UNIPHARMA",
                             "Analyse complète"}

    def test_nom_fichier(self):
        assert nom_fichier_sortie(DATE_ANALYSE) == "commande_ruptures_2026-05-13.xlsx"

    def test_charger_csv_point_virgule(self):
        contenu = "Produit;Stock\nOZEMPIC 1MG;5\n".encode("utf-8")
        df = charger_fichier(contenu, "cadencier.csv")
        assert list(df.columns) == ["Produit", "Stock"]
        assert len(df) == 1

    def test_charger_xlsx(self, tmp_path):
        chemin = tmp_path / "test.xlsx"
        pd.DataFrame({"A": [1]}).to_excel(chemin, index=False)
        df = charger_fichier(str(chemin), "test.xlsx")
        assert list(df.columns) == ["A"]

    def test_format_inconnu_message_clair(self):
        with pytest.raises(ValueError, match="Format non géré"):
            charger_fichier(b"", "fichier.pdf")
