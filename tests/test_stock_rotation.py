# -*- coding: utf-8 -*-
"""Tests du Module 1 — Gestion des stocks en rotation (stock_rotation.py).

Couvre le calcul du stock min / max et, en priorité, la règle métier des
« 10 unités » : sous ce seuil ABSOLU, la cible de réassort passe
directement au stock max, sans recomplètement progressif jusqu'au seul
stock min.

Ce module est testé de façon totalement AUTONOME : aucun test ici n'a
besoin d'un fichier de ruptures GPNC/UNIPHARMA — seul le cadencier compte,
ce qui prouve l'isolation vis-à-vis de moteur_ruptures.py.
"""

import pandas as pd
import pytest

from stock_rotation import (ParametresStockRotation, analyser_stock_rotation,
                            calculer_stock_max, calculer_stock_min,
                            determiner_cible_reassort,
                            exporter_stock_rotation_excel)


# ---------------------------------------------------------------------------
# Calculs élémentaires : stock min / stock max
# ---------------------------------------------------------------------------

class TestCalculStockMin:
    def test_formule_de_base(self):
        # Conso 2/j, délai 5 j, sécurité 7 j → min = 2 × 12 = 24.
        assert calculer_stock_min(2, lead_time_jours=5,
                                  stock_securite_jours=7) == 24

    def test_consommation_nulle_min_nul(self):
        assert calculer_stock_min(0, lead_time_jours=5,
                                  stock_securite_jours=7) == 0

    def test_pas_de_stock_de_securite(self):
        assert calculer_stock_min(3, lead_time_jours=5,
                                  stock_securite_jours=0) == 15


class TestCalculStockMax:
    def test_formule_de_base(self):
        # Min 24, conso 2/j, réassort tous les 14 j → max = 24 + 28 = 52.
        assert calculer_stock_max(24, 2, frequence_reassort_jours=14) == 52

    def test_max_toujours_superieur_ou_egal_au_min(self):
        stock_min = calculer_stock_min(1.5, 5, 7)
        stock_max = calculer_stock_max(stock_min, 1.5, 14)
        assert stock_max >= stock_min


# ---------------------------------------------------------------------------
# LA règle métier : seuil absolu des 10 unités (priorité sur le stock min)
# ---------------------------------------------------------------------------

class TestReglesDixUnites:
    def test_sous_le_seuil_cible_directement_le_max(self):
        # Stock 8 < seuil 10 → cible = stock max DIRECTEMENT, quel que soit
        # le stock min (même si le stock min calculé serait plus élevé).
        cible, qte, motif = determiner_cible_reassort(
            stock_actuel=8, stock_min=15, stock_max=40,
            seuil_alerte_unites=10)
        assert cible == 40
        assert qte == 32
        assert "immédiate" in motif and "stock max" in motif

    def test_seuil_prioritaire_meme_si_stock_min_est_bas(self):
        # Le seuil absolu prime MÊME quand le stock min calculé (3) est
        # lui-même inférieur à 10 — c'est le cœur de la règle demandée :
        # pas de recomplètement progressif jusqu'au seul min dans ce cas.
        cible, qte, motif = determiner_cible_reassort(
            stock_actuel=8, stock_min=3, stock_max=12,
            seuil_alerte_unites=10)
        assert cible == 12  # stock max, pas stock min (3)
        assert qte == 4

    def test_egal_au_seuil_pas_dans_la_zone_critique(self):
        # stock_actuel == seuil : la comparaison est stricte (<), donc au
        # seuil exact on n'est PAS dans la zone d'action immédiate.
        cible, qte, motif = determiner_cible_reassort(
            stock_actuel=10, stock_min=15, stock_max=40,
            seuil_alerte_unites=10)
        assert cible == 15  # réassort progressif jusqu'au min, pas au max
        assert "progressif" in motif

    def test_au_dessus_du_seuil_mais_sous_le_min_reassort_progressif(self):
        # Entre le seuil et le stock min : réassort PROGRESSIF jusqu'au
        # stock min SEULEMENT (pas jusqu'au max) — situation pas critique.
        cible, qte, motif = determiner_cible_reassort(
            stock_actuel=12, stock_min=20, stock_max=50,
            seuil_alerte_unites=10)
        assert cible == 20
        assert qte == 8
        assert "progressif" in motif

    def test_stock_suffisant_aucune_commande(self):
        cible, qte, motif = determiner_cible_reassort(
            stock_actuel=25, stock_min=20, stock_max=50,
            seuil_alerte_unites=10)
        assert qte == 0
        assert "aucune commande" in motif.lower()

    def test_seuil_sous_le_max_deja_atteint_pas_de_commande_negative(self):
        # Produit à rotation très lente : stock max (6) < seuil absolu (10).
        # Stock à 8 (sous le seuil, mais déjà au-dessus du max) → la cible
        # « max » vaut moins que le stock actuel : Cmd = 0, jamais négative.
        cible, qte, motif = determiner_cible_reassort(
            stock_actuel=8, stock_min=3, stock_max=6,
            seuil_alerte_unites=10)
        assert cible == 6
        assert qte == 0  # max(0, ceil(6 - 8)) = 0, pas -2

    def test_seuil_reglable(self):
        # Avec un seuil à 5 (au lieu de 10 par défaut), un stock de 8 n'est
        # plus dans la zone d'action immédiate.
        cible, qte, motif = determiner_cible_reassort(
            stock_actuel=8, stock_min=15, stock_max=40,
            seuil_alerte_unites=5)
        assert cible == 15 and "progressif" in motif


# ---------------------------------------------------------------------------
# Analyse complète du cadencier (module autonome)
# ---------------------------------------------------------------------------

def _cadencier():
    return pd.DataFrame({
        "Produit": ["CRITIQUE B/12", "SOUS MIN", "STOCK OK", "DORMANT",
                    "SANS HISTORIQUE", "ARRETE PEU DE STOCK"],
        "CIP": ["4001", "4002", "4003", "4004", "4005", "4006"],
        # CRITIQUE : 8 unités < seuil 10 → action requise.
        # SOUS MIN : conso 30/mois → stock min 12 (défauts) ; stock 11 est
        #   au-dessus du seuil (10) mais sous ce stock min → palier moyen.
        # STOCK OK : largement au-dessus du stock min.
        # DORMANT : gros stock, faible rotation → couverture > 180 j.
        # SANS HISTORIQUE : aucune vente, stock 0.
        # ARRETE PEU DE STOCK : rotation nulle (non vendu) mais stock < 10 —
        #   ne doit PAS être « action requise » : rien à commander (qté 0).
        "Stock": [8, 11, 200, 500, 0, 4],
        "Ventes avril": [30, 30, 30, 2, 0, 0],
        "Ventes mai":   [32, 30, 32, 2, 0, 0],
        "Ventes juin":  [31, 30, 31, 2, 0, 0],
    })


def _mapping_cadencier():
    return {"cadencier": {"libelle": "Produit", "cip": "CIP", "stock": "Stock",
                          "ventes": ["Ventes avril", "Ventes mai",
                                     "Ventes juin"],
                          "conditionnement": None, "commande_en_cours": None,
                          "peremption": None}}


class TestAnalyseStockRotation:
    def test_produit_critique_signale(self):
        resultat = analyser_stock_rotation(_cadencier(), _mapping_cadencier())
        ligne = resultat.tableau[
            resultat.tableau["Nom du produit"] == "CRITIQUE B/12"]
        assert ligne["Alerte"].iloc[0] == "🔴 Action requise"
        assert ligne["Qté à commander"].iloc[0] > 0
        assert ligne["Stock max (calculé)"].iloc[0] > ligne[
            "Stock min (calculé)"].iloc[0]

    def test_colonnes_demandees_presentes(self):
        # Les 5 colonnes explicitement demandées + l'indicateur visuel.
        resultat = analyser_stock_rotation(_cadencier(), _mapping_cadencier())
        for colonne in ("Code CIP", "Nom du produit", "Stock actuel",
                        "Stock min (calculé)", "Stock max (calculé)", "Alerte"):
            assert colonne in resultat.tableau.columns

    def test_tri_action_requise_en_tete(self):
        resultat = analyser_stock_rotation(_cadencier(), _mapping_cadencier())
        assert resultat.tableau["Alerte"].iloc[0] == "🔴 Action requise"

    def test_sous_le_min_palier_intermediaire(self):
        # Stock 11, au-dessus du seuil (10) mais sous le stock min calculé
        # (12 avec les paramètres par défaut) → palier « Sous le min ».
        resultat = analyser_stock_rotation(_cadencier(), _mapping_cadencier())
        ligne = resultat.tableau[resultat.tableau["Nom du produit"] == "SOUS MIN"]
        assert ligne["Alerte"].iloc[0] == "🟡 Sous le min"
        assert ligne["Qté à commander"].iloc[0] > 0

    def test_stock_bas_mais_rotation_nulle_non_signale(self):
        # Produit arrêté (rotation 0) : même avec 4 unités en stock (< 10),
        # rien n'est à commander → pas d'alerte « action requise » trompeuse.
        resultat = analyser_stock_rotation(_cadencier(), _mapping_cadencier())
        ligne = resultat.tableau[
            resultat.tableau["Nom du produit"] == "ARRETE PEU DE STOCK"]
        assert ligne["Alerte"].iloc[0] == "🟢 OK"
        assert ligne["Qté à commander"].iloc[0] == 0

    def test_stock_dormant_detecte(self):
        resultat = analyser_stock_rotation(_cadencier(), _mapping_cadencier())
        assert "DORMANT" in " ".join(resultat.dormants["Nom du produit"])
        assert resultat.resume["dormants"] >= 1

    def test_classement_abc_integre(self):
        resultat = analyser_stock_rotation(_cadencier(), _mapping_cadencier())
        assert "Classe" in resultat.tableau.columns
        assert set(resultat.tableau["Classe"]) <= {"A", "B", "C"}

    def test_sans_historique_ni_stock_ignore(self):
        # Consommation par défaut désactivée (0) : produit sans aucune
        # vente ET sans stock → rien à piloter, n'apparaît pas.
        resultat = analyser_stock_rotation(_cadencier(), _mapping_cadencier())
        assert ("SANS HISTORIQUE"
                not in resultat.tableau["Nom du produit"].values)

    def test_isolation_aucun_fichier_rupture_necessaire(self):
        # Le module fonctionne avec le SEUL cadencier — preuve de
        # l'isolation vis-à-vis de moteur_ruptures.py (GPNC/UNIPHARMA).
        resultat = analyser_stock_rotation(_cadencier(), _mapping_cadencier())
        assert not resultat.tableau.empty
        assert resultat.resume["total_produits"] == 5  # sans historique exclu

    def test_parametres_configurables_changent_le_resultat(self):
        params_larges = ParametresStockRotation(
            lead_time_jours=1, stock_securite_jours=1,
            frequence_reassort_jours=3)
        params_serres = ParametresStockRotation(
            lead_time_jours=20, stock_securite_jours=20,
            frequence_reassort_jours=60)
        r_larges = analyser_stock_rotation(_cadencier(), _mapping_cadencier(),
                                           params_larges)
        r_serres = analyser_stock_rotation(_cadencier(), _mapping_cadencier(),
                                           params_serres)
        max_larges = r_larges.tableau.loc[
            r_larges.tableau["Nom du produit"] == "STOCK OK",
            "Stock max (calculé)"].iloc[0]
        max_serres = r_serres.tableau.loc[
            r_serres.tableau["Nom du produit"] == "STOCK OK",
            "Stock max (calculé)"].iloc[0]
        assert max_serres > max_larges

    def test_seuil_alerte_reglable_change_les_alertes(self):
        # Avec un seuil d'alerte relevé à 35, « SOUS MIN » (stock 30) bascule
        # aussi en action requise.
        params = ParametresStockRotation(seuil_alerte_unites=35)
        resultat = analyser_stock_rotation(_cadencier(), _mapping_cadencier(),
                                           params)
        ligne = resultat.tableau[
            resultat.tableau["Nom du produit"] == "SOUS MIN"]
        assert ligne["Alerte"].iloc[0] == "🔴 Action requise"


# ---------------------------------------------------------------------------
# Consommation par défaut (solution progressive sans historique)
# ---------------------------------------------------------------------------

class TestConsommationParDefaut:
    def test_active_pilote_le_produit_sans_historique(self):
        params = ParametresStockRotation(consommation_defaut_mensuelle=30)
        resultat = analyser_stock_rotation(_cadencier(), _mapping_cadencier(),
                                           params)
        assert ("SANS HISTORIQUE"
                in resultat.tableau["Nom du produit"].values)
        ligne = resultat.tableau[
            resultat.tableau["Nom du produit"] == "SANS HISTORIQUE"]
        assert "défaut" in ligne["Motif"].iloc[0]

    def test_historique_reel_prend_le_dessus(self):
        # Dès qu'il y a de VRAIES ventes, la valeur par défaut ne s'applique
        # plus — affinage automatique promis par la solution progressive.
        cad = _cadencier()
        cad.loc[cad["Produit"] == "SANS HISTORIQUE",
               ["Ventes avril", "Ventes mai", "Ventes juin"]] = [5, 5, 5]
        params = ParametresStockRotation(consommation_defaut_mensuelle=999)
        resultat = analyser_stock_rotation(cad, _mapping_cadencier(), params)
        ligne = resultat.tableau[
            resultat.tableau["Nom du produit"] == "SANS HISTORIQUE"]
        assert ligne["Consommation/mois"].iloc[0] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Export Excel dédié
# ---------------------------------------------------------------------------

class TestExportStockRotation:
    def test_deux_feuilles(self):
        resultat = analyser_stock_rotation(_cadencier(), _mapping_cadencier())
        contenu = exporter_stock_rotation_excel(resultat)
        relu = pd.read_excel(pd.io.common.BytesIO(contenu), sheet_name=None)
        assert set(relu) == {"Stock min-max", "Stock dormant"}

    def test_feuille_principale_contient_les_produits(self):
        resultat = analyser_stock_rotation(_cadencier(), _mapping_cadencier())
        contenu = exporter_stock_rotation_excel(resultat)
        relu = pd.read_excel(pd.io.common.BytesIO(contenu),
                             sheet_name="Stock min-max")
        assert "CRITIQUE B/12" in relu["Nom du produit"].values
