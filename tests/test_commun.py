# -*- coding: utf-8 -*-
"""Tests des fonctions PURES partagées (commun.py) — parsing, chargement de
fichiers, statistiques de consommation. Ni ruptures fournisseurs, ni stock
min/max : ces briques sont mutualisées par les deux modules métier.
"""

import math
from datetime import date

import pandas as pd
import pytest

from commun import (calculer_rotation_mensuelle, calculer_stock_jours,
                    calculer_tendance, charger_fichier, classer_abc,
                    corriger_faux_zeros, detecter_colonne,
                    detecter_colonnes_ventes, normaliser_cip,
                    normaliser_libelle, parser_date, parser_nombre,
                    pic_saisonnier, variabilite_demande, variantes_cip)


# ---------------------------------------------------------------------------
# Stock en jours
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
# Rotation annuelle / 3 mois / lissée
# ---------------------------------------------------------------------------

class TestRotation:
    VENTES = [10, 10, 10, 10, 10, 10, 10, 10, 10, 20, 20, 20]  # récent en dernier

    def test_annuelle(self):
        assert calculer_rotation_mensuelle(self.VENTES, "annuelle") == pytest.approx(12.5)

    def test_trois_mois(self):
        assert calculer_rotation_mensuelle(self.VENTES, "3mois") == pytest.approx(20)

    def test_un_mois(self):
        # Dernier mois seul : le plus réactif.
        assert calculer_rotation_mensuelle(self.VENTES, "1mois") == pytest.approx(20)
        assert calculer_rotation_mensuelle([5, 8, 30], "1mois") == pytest.approx(30)

    def test_virgule_francaise(self):
        assert calculer_rotation_mensuelle(["16,5"], "annuelle") == pytest.approx(16.5)

    def test_vide(self):
        assert calculer_rotation_mensuelle([], "annuelle") == 0.0


class TestRotationProduitRecent:
    """Les mois à 0 AVANT la première vente (produit pas encore référencé)
    ne comptent pas : sinon un générique lancé il y a 4 mois voit sa
    rotation divisée par 3 et son stock min sous-dimensionné d'autant."""

    LANCE_RECEMMENT = [0, 0, 0, 0, 0, 0, 0, 0, 90, 100, 95, 99]

    def test_moyenne_depuis_la_premiere_vente(self):
        rotation = calculer_rotation_mensuelle(self.LANCE_RECEMMENT, "annuelle")
        assert rotation == pytest.approx(96)  # et non 384/12 = 32

    def test_lissage_depuis_la_premiere_vente(self):
        lissee = calculer_rotation_mensuelle(self.LANCE_RECEMMENT, "lissee")
        assert lissee > 90  # sans la correction : ~64, très sous-estimé

    def test_zeros_de_fin_conserves(self):
        # Un arrêt de vente (zéros RÉCENTS) reste de la vraie demande nulle.
        rotation = calculer_rotation_mensuelle([12, 12, 0, 0], "annuelle")
        assert rotation == pytest.approx(6)

    def test_serie_toute_nulle_inchangee(self):
        assert calculer_rotation_mensuelle([0, 0, 0], "annuelle") == 0.0

    def test_variabilite_depuis_la_premiere_vente(self):
        # Demande parfaitement stable depuis le lancement → CV nul, pas
        # « forte variabilité » à cause des mois d'avant référencement.
        assert "stable" in variabilite_demande([0, 0, 0, 0, 10, 10, 10, 10])

    def test_pas_de_faux_pic_saisonnier(self):
        ventes = [0, 0, 0, 0, 0, 0, 10, 10, 10, 10, 12, 10]
        noms = [f"Ventes M{i}" for i in range(12)]
        assert pic_saisonnier(ventes, noms) == ""  # 12 < 2× moyenne réelle


class TestRotationLissee:
    def test_lissage_exponentiel(self):
        # SES α=0,4 sur [10, 10, 20] : 10 → 10 → 0,4×20+0,6×10 = 14.
        assert calculer_rotation_mensuelle([10, 10, 20], "lissee") == pytest.approx(14)

    def test_reagit_a_la_baisse(self):
        # Contrairement à une moyenne « prudente » (max), la baisse est
        # bien suivie par le lissage exponentiel.
        lissee = calculer_rotation_mensuelle([20, 20, 20, 5, 5, 5], "lissee")
        assert lissee < 10  # bien en dessous de la moyenne plate (12,5)


# ---------------------------------------------------------------------------
# Normalisation / parsing
# ---------------------------------------------------------------------------

class TestParsing:
    def test_normaliser_libelle(self):
        assert (normaliser_libelle("  Titanoréine® suppo. B/12 ")
                == "TITANOREINE SUPPO B 12")

    def test_normaliser_cip_float_excel(self):
        assert normaliser_cip("3400930123456.0") == "3400930123456"

    def test_normaliser_cip_zero_traite_comme_absent(self):
        # Placeholder « 0 » des exports : ne doit jamais servir au matching.
        assert normaliser_cip("0") == ""
        assert normaliser_cip("000") == ""

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
# CIP13 ↔ CIP7 (formats réels des exports pharmacie)
# ---------------------------------------------------------------------------

class TestVariantesCip:
    def test_cip13_matche_cip7(self):
        # Titanoréine : 3400932300778 (CIP13) ↔ 3230077 (CIP7).
        assert "3230077" in variantes_cip("3400932300778")

    def test_ean_parapharmacie_non_transforme(self):
        assert variantes_cip("7322540796742") == ["7322540796742"]


# ---------------------------------------------------------------------------
# Tendance de la demande
# ---------------------------------------------------------------------------

class TestTendance:
    def test_hausse(self):
        # Moyenne globale 12,5 ; 3 derniers mois 20 → +60 % → hausse.
        assert calculer_tendance([10, 10, 10, 20, 20, 20]) == "↗ hausse"

    def test_baisse(self):
        assert calculer_tendance([20, 20, 20, 10, 10, 10]) == "↘ baisse"

    def test_stable(self):
        assert calculer_tendance([10, 11, 10, 9, 10, 10]) == "→ stable"

    def test_cadencier_court_dernier_mois_vs_precedents(self):
        # 2-3 mois de recul : dernier mois (20) vs moyenne des précédents
        # (12,5) → +60 % → hausse. Un seul mois : rien à comparer.
        assert calculer_tendance([5, 20, 20]) == "↗ hausse"
        assert calculer_tendance([20]) == "→ stable"

    def test_demande_nulle(self):
        assert calculer_tendance([0, 0, 0, 0]) == "→ stable"


# ---------------------------------------------------------------------------
# Correction des faux zéros (rupture passée dans l'historique de ventes)
# ---------------------------------------------------------------------------

class TestCorrectionFauxZeros:
    def test_zero_interieur_interpole(self):
        corrigees, nb = corriger_faux_zeros([10, 0, 12])
        assert corrigees == [10, 11, 12] and nb == 1

    def test_serie_de_zeros_interpolee(self):
        corrigees, nb = corriger_faux_zeros([9, 0, 0, 12])
        assert corrigees == [9, 10, 11, 12] and nb == 2

    def test_zeros_de_bord_conserves(self):
        # Début (lancement) et fin (rupture EN COURS) : ne pas inventer.
        corrigees, nb = corriger_faux_zeros([0, 10, 10, 0])
        assert corrigees == [0, 10, 10, 0] and nb == 0

    def test_tout_a_zero_conserve(self):
        corrigees, nb = corriger_faux_zeros([0, 0, 0])
        assert corrigees == [0, 0, 0] and nb == 0


# ---------------------------------------------------------------------------
# Classement ABC (Pareto)
# ---------------------------------------------------------------------------

class TestClassementAbc:
    def test_pareto_80_15_5(self):
        # 80 fait 80 % du total (100) → A ; 15 → B ; 4 et 1 → C.
        assert classer_abc([80, 15, 4, 1]) == ["A", "B", "C", "C"]

    def test_plus_gros_vendeur_toujours_a(self):
        # Même s'il dépasse 80 % à lui seul, le n°1 est classé A.
        assert classer_abc([90, 10]) == ["A", "B"]

    def test_volumes_nuls_en_c(self):
        assert classer_abc([0, 0]) == ["C", "C"]
        assert classer_abc([10, 0]) == ["A", "C"]


# ---------------------------------------------------------------------------
# Variabilité de la demande / saisonnalité
# ---------------------------------------------------------------------------

class TestVariabiliteEtSaisonnalite:
    def test_demande_stable(self):
        assert "stable" in variabilite_demande([10, 10, 11, 9, 10, 10])

    def test_demande_tres_variable(self):
        assert "forte" in variabilite_demande([0, 30, 0, 30, 0, 30])

    def test_pas_assez_de_recul(self):
        assert variabilite_demande([10, 10]) == ""

    def test_pic_saisonnier_nomme(self):
        mois = [f"Ventes {m}" for m in
                ["Jul", "Aou", "Sep", "Oct", "Nov", "Dec"]]
        # Décembre à 30 pour une moyenne < 15 → pic Dec.
        assert pic_saisonnier([5, 5, 5, 5, 10, 30], mois) == "📈 pic Dec"

    def test_pas_de_pic_sur_demande_reguliere(self):
        assert pic_saisonnier([10, 10, 10, 10, 10, 12], []) == ""


# ---------------------------------------------------------------------------
# Chargement des fichiers (.xlsx / .xls / .csv / .pdf)
# ---------------------------------------------------------------------------

class TestChargementFichiers:
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
        # .pdf est géré — .docx reste un format inconnu.
        with pytest.raises(ValueError, match="Format non géré"):
            charger_fichier(b"", "fichier.docx")

    def test_chargement_format_reel_unipharma(self):
        # Reproduit l'en-tête et 2 lignes du vrai ruptocdp_ia.csv (CRLF).
        contenu = ("CIP13;CIP;Libelle;Réappro;Rembt;TGC;Situation\r\n"
                   "3400933937218;3393721;PYOSTACINE 250MG CP B/16      ;"
                   "03/06/26;OUI;;1\r\n"
                   "3400930571187;3057118;LARGACTIL CPR  25MG BT50      ;"
                   ";OUI;3,0%  ;2\r\n").encode("utf-8")
        df = charger_fichier(contenu, "ruptocdp_ia.csv")
        assert len(df) == 2
        assert detecter_colonne(df.columns, "libelle") == "Libelle"
        assert detecter_colonne(df.columns, "date_reappro") == "Réappro"
        assert parser_date(df["Réappro"].iloc[0]) == date(2026, 6, 3)


class TestCadencierWinPharmaCsv:
    """Export CSV du cadencier WinPharma : bandeau, achats (A) / ventes (V)
    anti-chronologiques, Code13Réf, ligne de totaux finale."""

    CONTENU = (
        '"PHARMACIE DE LA FOA M. Lauret Claude Alexandre"\r\n'
        '"92 Route Territoriale 1 BP 214"\r\n'
        '"Date :  10/07/2026 13:05"\r\n'
        '"du 01/07/2025 au 30/06/2026"\r\n'
        "\r\n"
        'CIP;Code13Réf;Nom;"Formes & presentations";Stock;'
        '"Jun (A)";"Mai (A)";"Jun (V)";"Mai (V)";"Total (A)";"Total (V)"\r\n'
        '3352892;3400933528928;"ABUFENE  400   B/ 30";"60  COMPRIMÉ";'
        "1;0;2;5;3;2;8\r\n"
        '3525720004499;3525722032742;"3 CHENES CARBOLINE B/30";;'
        "17;12;0;3;1;12;4\r\n"
        ';;"BO COEUR WHITE BRONZE";;2;0;0;1;0;0;1\r\n'
        ';;"Qte : 3621";"Manque : -8";20;12;2;9;4;14;13\r\n'
    ).encode("latin-1")

    def _charge(self):
        return charger_fichier(self.CONTENU, "Cadencier.csv")

    def test_bandeau_ignore_et_totaux_elimines(self):
        df = self._charge()
        assert len(df) == 3  # 2 produits codés + 1 sans code, totaux éliminés
        assert not df["Produit"].str.contains("Qte").any()

    def test_format_normalise_identique_au_pdf(self):
        df = self._charge()
        assert list(df.columns) == ["Produit", "CIP", "Stock",
                                    "Ventes Mai", "Ventes Jun"]

    def test_ventes_remises_en_ordre_chronologique_sans_achats(self):
        df = self._charge()
        abufene = df[df["Produit"].str.startswith("ABUFENE")].iloc[0]
        # Ligne source : Jun (V) = 5, Mai (V) = 3 — et surtout PAS les achats.
        assert abufene["Ventes Mai"] == "3"
        assert abufene["Ventes Jun"] == "5"

    def test_code13ref_prefere_au_cip_court(self):
        df = self._charge()
        abufene = df[df["Produit"].str.startswith("ABUFENE")].iloc[0]
        assert abufene["CIP"] == "3400933528928"

    def test_produit_sans_code_conserve(self):
        df = self._charge()
        sans_code = df[df["Produit"].str.startswith("BO COEUR")]
        assert len(sans_code) == 1
        assert sans_code.iloc[0]["CIP"] == ""

    def test_colonnes_auto_detectees(self):
        df = self._charge()
        assert detecter_colonne(df.columns, "libelle") == "Produit"
        assert detecter_colonne(df.columns, "cip") == "CIP"
        assert detecter_colonne(df.columns, "stock") == "Stock"
        assert detecter_colonnes_ventes(df.columns) == ["Ventes Mai",
                                                        "Ventes Jun"]

    def test_csv_ordinaire_non_intercepte(self):
        contenu = "CIP;Stock\n3352892;4\n".encode("utf-8")
        df = charger_fichier(contenu, "autre.csv")
        assert list(df.columns) == ["CIP", "Stock"]  # chemin générique


class TestPdf:
    def test_cadencier_pdf_multipages(self, tmp_path):
        pytest.importorskip("pdfplumber")
        pytest.importorskip("reportlab")
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

        chemin = tmp_path / "cadencier.pdf"
        en_tete = ["Produit", "CIP", "Stock", "Ventes mai", "Ventes juin"]
        lignes = [[f"PRODUIT {i:03d} CPR B30", f"3{i:06d}", "4", "10", "12"]
                  for i in range(60)]  # 60 lignes → plusieurs pages
        tableau = Table([en_tete] + lignes, repeatRows=1)  # en-tête répété
        tableau.setStyle(TableStyle(
            [("GRID", (0, 0), (-1, -1), 0.5, colors.grey)]))
        SimpleDocTemplate(str(chemin), pagesize=landscape(A4)).build([tableau])

        df = charger_fichier(str(chemin), "cadencier.pdf")
        assert list(df.columns) == en_tete
        assert len(df) == 60  # en-têtes répétés éliminés, aucune ligne perdue

    def test_pdf_illisible_message_clair(self):
        pytest.importorskip("pdfplumber")
        with pytest.raises(ValueError, match="PDF"):
            charger_fichier(b"%PDF-1.4 contenu corrompu", "scan.pdf")


class TestCadencierWinpharma:
    BRUTES = [
        ["PHARMACIE DE TEST 13/05/2026\nCADENCIER DE STOCK du 01/06/2025 "
         "au 31/05/2026 Page: 1", "", "", ""],
        ["Codes produit", "Nom / Formes & presentations", "Stock",
         "Mai Avr Mar Fev Jan Dec Nov Oct Sep Aou Jul Jun Total"],
        ["3230077\n3400932300778", "TITANOREINE SUPPO B/ 12\n182 SOLUTION",
         "3", "A 0 0 0 0 15 0 0 0 18 0 12 12 57\nV 2 4 6 4 5 4 5 6 6 7 7 9 65"],
        ["Manque: -9\nQte: 3652\nStock: 26368", "", "",
         "A 9792 21254 23157 18629 18514 23269 18404 21661 19402 24100 1 2 3"],
    ]

    def test_extraction_produit(self):
        from commun import _parser_cadencier_winpharma
        df = _parser_cadencier_winpharma(self.BRUTES)
        assert len(df) == 1  # bandeau, en-tête et ligne de totaux éliminés
        assert df["CIP"].iloc[0] == "3400932300778"  # CIP13 préféré au CIP7
        assert df["Produit"].iloc[0] == "TITANOREINE SUPPO B/ 12 182 SOLUTION"
        assert df["Stock"].iloc[0] == "3"

    def test_ventes_remises_en_ordre_chronologique(self):
        from commun import _parser_cadencier_winpharma
        df = _parser_cadencier_winpharma(self.BRUTES)
        # Ligne V : Mai=2 (récent) … Jun=9 (ancien) → chronologique Jun→Mai.
        assert list(df.columns[3:5]) == ["Ventes Jun", "Ventes Jul"]
        assert df["Ventes Jun"].iloc[0] == "9"
        assert df["Ventes Mai"].iloc[0] == "2"
        # La rotation utilise bien la ligne V (65/12 ≈ 5,4), pas la ligne A.
        ventes = [df[c].iloc[0] for c in df.columns if c.startswith("Ventes")]
        assert (calculer_rotation_mensuelle(ventes, "annuelle")
                == pytest.approx(65 / 12))


class TestSeparationMoisTotal:
    def test_cas_reel_doliprane(self):
        # Ligne V réelle du cadencier : dernier mois (1572) collé au total
        # (18268 = somme des 12 mois) faute de place dans le PDF.
        from commun import _separer_mois_et_total
        nombres = ["706", "1739", "1576", "1327", "1433", "1733", "1530",
                   "1591", "1621", "1772", "1668", "157218268"]
        assert _separer_mois_et_total(nombres)[-1] == "1572"

    def test_sans_fusion_inchange(self):
        from commun import _separer_mois_et_total
        nombres = [str(n) for n in [5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5]]
        assert _separer_mois_et_total(nombres) == nombres
