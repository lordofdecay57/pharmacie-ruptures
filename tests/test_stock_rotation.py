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

from datetime import date

import pandas as pd
import pytest

from stock_rotation import (ParametresStockRotation, analyser_stock_rotation,
                            calculer_stock_max, calculer_stock_min,
                            comparer_a_etat_precedent, determiner_cible_reassort,
                            etat_stock_a_enregistrer,
                            exporter_stock_rotation_excel,
                            jours_supplementaires_weekend)


# ---------------------------------------------------------------------------
# Calculs élémentaires : stock min / stock max (couvertures 14 j / 30 j)
# ---------------------------------------------------------------------------

class TestCalculStockMin:
    def test_formule_de_base(self):
        # Conso 2/j, couverture 14 j → min = 28.
        assert calculer_stock_min(2, couverture_min_jours=14) == 28

    def test_consommation_nulle_min_nul(self):
        assert calculer_stock_min(0, couverture_min_jours=14) == 0

    def test_ajout_jours_weekend(self):
        # Vendredi : +2 j → min = 2 × 16 = 32 au lieu de 28.
        assert calculer_stock_min(2, couverture_min_jours=14,
                                  jours_supplementaires=2) == 32


class TestCalculStockMax:
    def test_formule_de_base(self):
        # Conso 2/j, couverture 30 j → max = 60.
        assert calculer_stock_max(2, couverture_max_jours=30) == 60

    def test_max_superieur_au_min_avec_defauts(self):
        # 30 j > 14 j : le max domine toujours le min à paramètres par défaut.
        assert (calculer_stock_max(1.5, 30)
                > calculer_stock_min(1.5, 14))


# ---------------------------------------------------------------------------
# Week-end : pas de réception de commandes samedi / dimanche
# ---------------------------------------------------------------------------

class TestJoursWeekend:
    def test_vendredi_plus_deux_jours(self):
        # Vendredi 15/05/2026 : commande reçue lundi au lieu de samedi.
        assert jours_supplementaires_weekend(date(2026, 5, 15)) == 2

    def test_samedi_plus_un_jour(self):
        assert jours_supplementaires_weekend(date(2026, 5, 16)) == 1

    def test_jours_de_semaine_sans_ajustement(self):
        # Dimanche à jeudi : réception le lendemain, rien à ajouter.
        for jour in (10, 11, 12, 13, 14, 17):  # dim 10 → jeu 14, puis dim 17
            assert jours_supplementaires_weekend(date(2026, 5, jour)) == 0

    def test_sans_date_pas_d_ajustement(self):
        assert jours_supplementaires_weekend(None) == 0

    def test_stock_min_gonfle_le_vendredi(self):
        # Conso 30/mois = 1/j : min 14 en semaine, 16 le vendredi.
        cadencier = pd.DataFrame({
            "Produit": ["PRODUIT REGULIER"], "CIP": ["5001"], "Stock": [15],
            "Ventes avril": [30], "Ventes mai": [30], "Ventes juin": [30],
        })
        mapping = {"cadencier": {"libelle": "Produit", "cip": "CIP",
                                 "stock": "Stock",
                                 "ventes": ["Ventes avril", "Ventes mai",
                                            "Ventes juin"]}}
        mardi = analyser_stock_rotation(cadencier, mapping,
                                        date_analyse=date(2026, 5, 12))
        vendredi = analyser_stock_rotation(cadencier, mapping,
                                           date_analyse=date(2026, 5, 15))
        min_mardi = mardi.tableau["Stock min (calculé)"].iloc[0]
        min_vendredi = vendredi.tableau["Stock min (calculé)"].iloc[0]
        assert min_mardi == pytest.approx(14.0)
        assert min_vendredi == pytest.approx(16.0)
        # Stock 15 : suffisant le mardi (15 ≥ 14), SOUS le min le vendredi.
        assert mardi.tableau["Alerte"].iloc[0] == "🟢 OK"
        assert vendredi.tableau["Alerte"].iloc[0] == "🟡 Sous le min"
        assert vendredi.resume["jours_weekend"] == 2


# ---------------------------------------------------------------------------
# Plancher métier : stock max jamais < 10 pour un produit piloté
# ---------------------------------------------------------------------------

class TestStockMinSupprimePetitMax:
    """Règle officine : pour les lignes dont le stock max < 10, le stock min
    est SUPPRIMÉ (pas de point de commande automatique)."""

    def _mapping(self):
        return {"cadencier": {"libelle": "Produit", "cip": "CIP",
                              "stock": "Stock",
                              "ventes": ["Ventes avril", "Ventes mai",
                                         "Ventes juin"]}}

    def test_min_supprime_si_max_inferieur_10(self):
        # ~5/mois → max de base 5 (< 10) → min supprimé.
        cad = pd.DataFrame({
            "Produit": ["PETIT MAX"], "CIP": ["9300"], "Stock": [1],
            "Ventes avril": [5], "Ventes mai": [5], "Ventes juin": [5]})
        ligne = analyser_stock_rotation(cad, self._mapping()).tableau.iloc[0]
        assert ligne["Stock max (calculé)"] < 10
        assert ligne["Stock min (calculé)"] == 0
        assert "stock min supprimé" in ligne["Motif"]
        assert ligne["Qté à commander"] == 0  # sans min, pas de commande auto

    def test_min_conserve_si_max_10_ou_plus(self):
        # ~40/mois → max ≥ 10 → min conservé.
        cad = pd.DataFrame({
            "Produit": ["GROS VENDEUR"], "CIP": ["9302"], "Stock": [0],
            "Ventes avril": [40], "Ventes mai": [40], "Ventes juin": [40]})
        ligne = analyser_stock_rotation(cad, self._mapping()).tableau.iloc[0]
        assert ligne["Stock max (calculé)"] >= 10
        assert ligne["Stock min (calculé)"] > 0
        assert "stock min supprimé" not in ligne["Motif"]


# ---------------------------------------------------------------------------
# Garde-fou du mode réactif (mensuel/lissé) : ventes récentes nulles
# ---------------------------------------------------------------------------

class TestGardeFouModeReactif:
    """En mode mensuel, un produit qui vend sur l'année mais a eu 0 vente le
    dernier mois (rupture/creux) ne doit PAS disparaître du pilotage."""

    def _cadencier(self):
        # Vend 10/mois toute l'année SAUF le dernier mois à 0 (rupture).
        return pd.DataFrame({
            "Produit": ["EN RUPTURE CE MOIS"], "CIP": ["9100"], "Stock": [3],
            **{f"Ventes m{i}": [10] for i in range(11)},
            "Ventes m11": [0],  # dernier mois : rupture
        })

    def _mapping(self):
        return {"cadencier": {"libelle": "Produit", "cip": "CIP",
                              "stock": "Stock",
                              "ventes": [f"Ventes m{i}" for i in range(12)]}}

    def test_mensuel_ne_masque_pas_le_produit(self):
        params = ParametresStockRotation(periode_rotation="1mois")
        resultat = analyser_stock_rotation(self._cadencier(), self._mapping(),
                                           params)
        assert len(resultat.tableau) == 1  # présent, pas disparu
        ligne = resultat.tableau.iloc[0]
        # Repli sur la moyenne annuelle (~9,2/mois) au lieu de 0.
        assert ligne["Consommation/mois"] > 5
        assert "repli sur la moyenne annuelle" in ligne["Motif"]
        assert ligne["Qté à commander"] > 0

    def test_mode_annuel_inchange(self):
        # En annuel, pas de mention de repli (le calcul est déjà annuel).
        resultat = analyser_stock_rotation(self._cadencier(), self._mapping())
        ligne = resultat.tableau.iloc[0]
        assert "repli" not in ligne["Motif"]


# ---------------------------------------------------------------------------
# LA règle métier : seuil absolu des 10 unités — urgence CONFIRMÉE
# (sous le seuil ET sous le stock min), pas seuil seul
# ---------------------------------------------------------------------------

class TestReglesDixUnites:
    def test_sous_le_seuil_et_sous_le_min_cible_directement_le_max(self):
        # Stock 8 < seuil 10 ET < stock min 15 → urgence CONFIRMÉE, cible =
        # stock max directement.
        cible, qte, motif = determiner_cible_reassort(
            stock_actuel=8, stock_min=15, stock_max=40,
            seuil_alerte_unites=10)
        assert cible == 40
        assert qte == 32
        assert "immédiate" in motif and "stock max" in motif

    def test_sous_le_seuil_mais_deja_au_dessus_du_min_aucune_commande(self):
        # Cœur du correctif : un produit à faible rotation a souvent un
        # stock min calculé (3) déjà inférieur au seuil absolu (10). Le
        # seuil SEUL ne doit plus déclencher l'urgence si le stock (8) est
        # déjà au-dessus de son propre minimum — sinon 9 alertes rouges sur
        # 10 se sont révélées être ce faux positif sur le cadencier réel,
        # gonflant les quantités proposées sans besoin métier.
        cible, qte, motif = determiner_cible_reassort(
            stock_actuel=8, stock_min=3, stock_max=12,
            seuil_alerte_unites=10)
        assert cible == 8  # stock actuel : rien à commander
        assert qte == 0
        assert "suffisant" in motif.lower()

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
        # Stock à 8, déjà au-dessus du min (3) ET du max (6) → aucune
        # commande, jamais négative.
        cible, qte, motif = determiner_cible_reassort(
            stock_actuel=8, stock_min=3, stock_max=6,
            seuil_alerte_unites=10)
        assert cible == 8
        assert qte == 0  # max(0, ceil(8 - 8)) = 0, pas -2

    def test_seuil_reglable(self):
        # Avec un seuil à 5 (au lieu de 10 par défaut), un stock de 8 n'est
        # plus dans la zone d'action immédiate.
        cible, qte, motif = determiner_cible_reassort(
            stock_actuel=8, stock_min=15, stock_max=40,
            seuil_alerte_unites=5)
        assert cible == 15 and "progressif" in motif

    def test_stock_egal_a_son_propre_min_pas_de_fausse_urgence(self):
        # Cas réel (cadencier) : KETOCONAZOLE CREME — stock 9, stock min
        # calculé 9 (déjà atteint), sous le seuil absolu (10). Avant le
        # correctif : commande immédiate jusqu'au stock max malgré un
        # stock déjà à son minimum. Après : aucune commande.
        cible, qte, motif = determiner_cible_reassort(
            stock_actuel=9, stock_min=9, stock_max=18,
            seuil_alerte_unites=10)
        assert cible == 9
        assert qte == 0

    def test_urgence_confirmee_meme_pour_petite_rotation(self):
        # Le filet de sécurité reste actif quand c'est justifié : stock (5)
        # sous le seuil (10) ET sous son propre min (7) → urgence réelle,
        # cible = max.
        cible, qte, motif = determiner_cible_reassort(
            stock_actuel=5, stock_min=7, stock_max=15,
            seuil_alerte_unites=10)
        assert cible == 15
        assert qte == 10
        assert "immédiate" in motif


# ---------------------------------------------------------------------------
# Analyse complète du cadencier (module autonome)
# ---------------------------------------------------------------------------

def _cadencier():
    return pd.DataFrame({
        "Produit": ["CRITIQUE B/12", "SOUS MIN", "STOCK OK", "DORMANT",
                    "SANS HISTORIQUE", "ARRETE PEU DE STOCK"],
        "CIP": ["4001", "4002", "4003", "4004", "4005", "4006"],
        # CRITIQUE : 8 unités < seuil 10 → action requise.
        # SOUS MIN : conso 30/mois = 1/j → stock min 14 (couverture 14 j) ;
        #   stock 11 est au-dessus du seuil (10) mais sous ce min → palier moyen.
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
        # (14 avec la couverture par défaut) → palier « Sous le min ».
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

    def test_classement_abc_sur_la_consommation_exacte(self):
        """Le classement porte sur la rotation RÉELLE, pas sur la valeur
        arrondie au dixième pour l'affichage : deux produits séparés par
        quelques centièmes de boîte ne doivent pas être départagés par
        l'arrondi."""
        # 10 et 9 ventes sur l'année donnent 0,833 et 0,75 boîte/mois :
        # deux valeurs DIFFÉRENTES qui s'affichent toutes deux « 0,8 ».
        mois = [f"Ventes M{i}" for i in range(1, 13)]
        lignes = []
        for nom, total in (("GROS", 120), ("MOYEN", 10), ("PETIT", 9)):
            ligne = {"Produit": nom, "CIP": nom, "Stock": 0}
            for i, colonne in enumerate(mois):
                ligne[colonne] = total if i == 0 else 0
            lignes.append(ligne)
        resultat = analyser_stock_rotation(
            pd.DataFrame(lignes),
            {"cadencier": {"libelle": "Produit", "cip": "CIP",
                           "stock": "Stock", "ventes": mois}})
        affichees = dict(zip(resultat.tableau["Nom du produit"],
                             resultat.tableau["Consommation/mois"]))
        # Le cas n'est pas trivial : à l'écran, les deux sont indiscernables.
        assert affichees["MOYEN"] == affichees["PETIT"]

        # Invariant : vendre plus ne peut jamais valoir une classe moins
        # bonne. Classer sur la valeur arrondie créerait des ex æquo
        # artificiels, départagés par le seul ordre des lignes.
        rang = {"A": 0, "B": 1, "C": 2}
        ventes_exactes = {"GROS": 10.0, "MOYEN": 10 / 12, "PETIT": 9 / 12}
        classes = dict(zip(resultat.tableau["Nom du produit"],
                           resultat.tableau["Classe"]))
        for a in classes:
            for b in classes:
                if ventes_exactes[a] > ventes_exactes[b]:
                    assert rang[classes[a]] <= rang[classes[b]], (
                        f"{a} vend plus que {b} mais est moins bien classé")
        assert classes["GROS"] == "A"

    def test_colonnes_techniques_absentes_du_resultat(self):
        """Les colonnes de travail (préfixe _) ne doivent pas fuiter dans le
        tableau rendu à l'utilisateur ni dans les exports."""
        resultat = analyser_stock_rotation(_cadencier(), _mapping_cadencier())
        assert [c for c in resultat.tableau.columns
                if str(c).startswith("_")] == []

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
            couverture_min_jours=3, couverture_max_jours=7)
        params_serres = ParametresStockRotation(
            couverture_min_jours=30, couverture_max_jours=90)
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

    def test_cip_et_nom_manquants_affiches_vides(self):
        # Un CIP absent (NaN dans un export Excel) ne doit pas s'afficher
        # « nan » dans le tableau.
        cadencier = _cadencier()
        cadencier.loc[0, "CIP"] = float("nan")
        resultat = analyser_stock_rotation(cadencier, _mapping_cadencier())
        ligne = resultat.tableau[
            resultat.tableau["Nom du produit"] == "CRITIQUE B/12"]
        assert ligne["Code CIP"].iloc[0] == ""

    def test_dormant_jamais_vendu_couverture_infinie_lisible(self):
        # Stock sans aucune vente : couverture infinie → affichage explicite,
        # pas « inf ».
        cadencier = _cadencier()
        cadencier.loc[4, "Stock"] = 40  # SANS HISTORIQUE : stock mais 0 vente
        resultat = analyser_stock_rotation(cadencier, _mapping_cadencier())
        dormant = resultat.dormants[
            resultat.dormants["Nom du produit"] == "SANS HISTORIQUE"]
        assert len(dormant) == 1
        assert "∞" in str(dormant["Stock (jours)"].iloc[0])

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
# Fusion des doublons (même produit sous deux codes CIP)
# ---------------------------------------------------------------------------

class TestFusionDoublons:
    """Cas réel : changement de générique — l'ancien code reste dans le
    cadencier avec stock 0 et un historique qui s'arrête, le nouveau code
    porte le stock et les ventes récentes. Sans fusion, l'ancienne fiche
    déclenche une commande fantôme d'un produit déjà en rayon."""

    def _cadencier_doublon(self):
        return pd.DataFrame({
            "Produit": ["BISOPROLOL 2,5 B/ 30", "BISOPROLOL 2,5 B/ 30",
                        "AUTRE PRODUIT"],
            "CIP": ["3400935295637", "3400930227336", "4009"],
            "Stock": [0, 79, 50],
            # Ancien code : ventes jusqu'en janvier puis plus rien.
            # Nouveau code : prend le relais dès janvier.
            "Ventes dec":  [90, 0, 5],
            "Ventes jan":  [87, 10, 5],
            "Ventes fev":  [0, 109, 5],
            "Ventes mar":  [0, 119, 5],
        })

    def _mapping(self):
        return {"cadencier": {"libelle": "Produit", "cip": "CIP",
                              "stock": "Stock",
                              "ventes": ["Ventes dec", "Ventes jan",
                                         "Ventes fev", "Ventes mar"]}}

    def test_une_seule_ligne_par_produit(self):
        resultat = analyser_stock_rotation(self._cadencier_doublon(),
                                           self._mapping())
        lignes = resultat.tableau[
            resultat.tableau["Nom du produit"] == "BISOPROLOL 2,5 B/ 30"]
        assert len(lignes) == 1
        assert resultat.resume["doublons_fusionnes"] == 1

    def test_pas_de_commande_fantome_sur_l_ancien_code(self):
        # Fusionné : stock 79, série continue 90/97/109/119 (~104/mois) →
        # stock au-dessus du min (14 j ≈ 48), rien à commander.
        resultat = analyser_stock_rotation(self._cadencier_doublon(),
                                           self._mapping())
        ligne = resultat.tableau[
            resultat.tableau["Nom du produit"] == "BISOPROLOL 2,5 B/ 30"].iloc[0]
        assert ligne["Stock actuel"] == 79
        assert ligne["Qté à commander"] == 0
        assert ligne["Alerte"] == "🟢 OK"

    def test_cip_du_code_actif_conserve(self):
        resultat = analyser_stock_rotation(self._cadencier_doublon(),
                                           self._mapping())
        ligne = resultat.tableau[
            resultat.tableau["Nom du produit"] == "BISOPROLOL 2,5 B/ 30"].iloc[0]
        assert ligne["Code CIP"] == "3400930227336"  # le nouveau code

    def test_ventes_additionnees_mois_par_mois(self):
        resultat = analyser_stock_rotation(self._cadencier_doublon(),
                                           self._mapping())
        ligne = resultat.tableau[
            resultat.tableau["Nom du produit"] == "BISOPROLOL 2,5 B/ 30"].iloc[0]
        # (90 + 97 + 109 + 119) / 4 = 103,75 → série redevenue continue.
        assert ligne["Consommation/mois"] == pytest.approx(103.8)

    def test_produits_sans_doublon_intacts(self):
        resultat = analyser_stock_rotation(self._cadencier_doublon(),
                                           self._mapping())
        autre = resultat.tableau[
            resultat.tableau["Nom du produit"] == "AUTRE PRODUIT"]
        assert len(autre) == 1
        assert autre["Stock actuel"].iloc[0] == 50

    def test_libelles_vides_jamais_fusionnes(self):
        cadencier = pd.DataFrame({
            "Produit": ["", "", "NOMMÉ"],
            "CIP": ["111111", "222222", "333333"],
            "Stock": [5, 6, 7],
            "Ventes mai": [10, 20, 30],
            "Ventes juin": [10, 20, 30],
        })
        mapping = {"cadencier": {"libelle": "Produit", "cip": "CIP",
                                 "stock": "Stock",
                                 "ventes": ["Ventes mai", "Ventes juin"]}}
        resultat = analyser_stock_rotation(cadencier, mapping)
        assert resultat.resume["total_produits"] == 3
        assert resultat.resume.get("doublons_fusionnes", 0) == 0


# ---------------------------------------------------------------------------
# Consommation par défaut (solution progressive sans historique)
# ---------------------------------------------------------------------------

class TestCommandeEnCours:
    """Les boîtes déjà commandées mais pas encore reçues couvrent aussi la
    consommation à venir : sans déduction, l'outil recommande de commander
    comme si rien n'arrivait — double commande systématique."""

    def _cadencier(self):
        return pd.DataFrame({
            "Produit": ["AVEC COMMANDE EN COURS", "SANS COMMANDE EN COURS"],
            "CIP": ["7001", "7002"],
            "Stock": [2, 2],
            "En cours": [30, 0],
            "Ventes avril": [30, 30], "Ventes mai": [30, 30],
            "Ventes juin": [30, 30],
        })

    def _mapping(self):
        return {"cadencier": {"libelle": "Produit", "cip": "CIP",
                              "stock": "Stock",
                              "commande_en_cours": "En cours",
                              "ventes": ["Ventes avril", "Ventes mai",
                                         "Ventes juin"]}}

    def test_commande_en_cours_deduite_de_la_quantite(self):
        resultat = analyser_stock_rotation(self._cadencier(), self._mapping())
        avec = resultat.tableau[
            resultat.tableau["Nom du produit"] == "AVEC COMMANDE EN COURS"].iloc[0]
        sans = resultat.tableau[
            resultat.tableau["Nom du produit"] == "SANS COMMANDE EN COURS"].iloc[0]
        # Stock physique identique (2), mais 30 déjà en commande pour l'un :
        # stock effectif 32 (au-dessus du max) → aucune commande. L'autre
        # (stock effectif 2, sous le seuil ET sous le min) → urgence.
        assert avec["Qté à commander"] == 0
        assert sans["Qté à commander"] > 0
        assert avec["Stock actuel"] == 2  # le stock AFFICHÉ reste le stock physique
        assert avec["Alerte"] == "🟢 OK"
        assert sans["Alerte"] == "🔴 Action requise"

    def test_motif_mentionne_la_deduction(self):
        resultat = analyser_stock_rotation(self._cadencier(), self._mapping())
        avec = resultat.tableau[
            resultat.tableau["Nom du produit"] == "AVEC COMMANDE EN COURS"].iloc[0]
        assert "déjà en commande" in avec["Motif"]

    def test_sans_mapping_commande_en_cours_comportement_inchange(self):
        # Colonne non mappée : équivaut à 0 partout, aucune régression.
        mapping_sans = {"cadencier": {"libelle": "Produit", "cip": "CIP",
                                      "stock": "Stock",
                                      "ventes": ["Ventes avril", "Ventes mai",
                                                 "Ventes juin"]}}
        resultat = analyser_stock_rotation(self._cadencier(), mapping_sans)
        avec = resultat.tableau[
            resultat.tableau["Nom du produit"] == "AVEC COMMANDE EN COURS"].iloc[0]
        assert avec["Qté à commander"] > 0  # la déduction n'a pas lieu


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
# Écarter les produits à rotation trop faible du réassort automatique
# ---------------------------------------------------------------------------

class TestRotationFaibleEcartee:
    """Les produits vendus ≤ seuil boîtes/mois n'encombrent pas la commande :
    écartés du réassort auto, mais conservés (traçabilité)."""

    def _cadencier(self):
        return pd.DataFrame({
            "Produit": ["ROTATION LENTE", "ROTATION NORMALE"],
            "CIP": ["8001", "8002"],
            "Stock": [0, 0],
            # ROTATION LENTE : ~1 boîte/mois (3 sur 3 mois). ROTATION NORMALE
            # : ~20/mois. Les deux à stock 0.
            "Ventes avril": [1, 20], "Ventes mai": [1, 20],
            "Ventes juin": [1, 20],
        })

    def _mapping(self):
        return {"cadencier": {"libelle": "Produit", "cip": "CIP",
                              "stock": "Stock",
                              "ventes": ["Ventes avril", "Ventes mai",
                                         "Ventes juin"]}}

    def test_produit_lent_ecarte_par_defaut(self):
        # Défaut = 1/mois : ROTATION LENTE (1/mois) est écartée.
        resultat = analyser_stock_rotation(self._cadencier(), self._mapping())
        lent = resultat.tableau[
            resultat.tableau["Nom du produit"] == "ROTATION LENTE"].iloc[0]
        assert lent["Alerte"] == "⚪ Rotation faible"
        assert lent["Qté à commander"] == 0
        assert "écarté" in lent["Motif"]

    def test_produit_normal_toujours_commande(self):
        resultat = analyser_stock_rotation(self._cadencier(), self._mapping())
        normal = resultat.tableau[
            resultat.tableau["Nom du produit"] == "ROTATION NORMALE"].iloc[0]
        assert normal["Alerte"] == "🔴 Action requise"
        assert normal["Qté à commander"] > 0

    def test_seuil_reglable(self):
        # Seuil relevé à 25 : même ROTATION NORMALE (20/mois) est écartée.
        params = ParametresStockRotation(rotation_min_commande_mensuelle=25)
        resultat = analyser_stock_rotation(self._cadencier(), self._mapping(),
                                           params)
        assert set(resultat.tableau["Alerte"]) == {"⚪ Rotation faible"}
        assert resultat.resume["qte_totale_a_commander"] == 0
        assert resultat.resume["rotation_faible"] == 2

    def test_desactivable_avec_zero(self):
        # Seuil 0 : plus aucun produit n'est marqué « rotation faible ».
        params = ParametresStockRotation(rotation_min_commande_mensuelle=0)
        resultat = analyser_stock_rotation(self._cadencier(), self._mapping(),
                                           params)
        assert "⚪ Rotation faible" not in set(resultat.tableau["Alerte"])
        # ROTATION NORMALE (max ≥ 10) garde son min et se commande.
        # (ROTATION LENTE a un max < 10 → min supprimé par la règle dédiée,
        # indépendamment du filtre rotation faible.)
        normal = resultat.tableau[
            resultat.tableau["Nom du produit"] == "ROTATION NORMALE"].iloc[0]
        assert normal["Qté à commander"] > 0

    def test_absent_de_l_export_excel(self):
        # Le fichier de commande ne contient pas les produits écartés.
        resultat = analyser_stock_rotation(self._cadencier(), self._mapping())
        contenu = exporter_stock_rotation_excel(resultat)
        relu = pd.read_excel(pd.io.common.BytesIO(contenu),
                             sheet_name="Stock min-max")
        assert "ROTATION LENTE" not in relu["Nom du produit"].values
        assert "ROTATION NORMALE" in relu["Nom du produit"].values

    def test_rotation_nulle_non_concernee(self):
        # Rotation strictement nulle (produit arrêté) : reste 🟢 OK / ignoré,
        # PAS classé « rotation faible » (le filtre vise les ventes rares,
        # pas les produits sans aucune vente).
        cad = self._cadencier()
        cad.loc[cad["Produit"] == "ROTATION LENTE",
                ["Ventes avril", "Ventes mai", "Ventes juin"]] = [0, 0, 0]
        cad.loc[cad["Produit"] == "ROTATION LENTE", "Stock"] = 3
        resultat = analyser_stock_rotation(cad, self._mapping())
        lent = resultat.tableau[
            resultat.tableau["Nom du produit"] == "ROTATION LENTE"].iloc[0]
        assert lent["Alerte"] != "⚪ Rotation faible"


# ---------------------------------------------------------------------------
# Colonne conseillée : stock min majoré selon la variabilité (indicatif)
# ---------------------------------------------------------------------------

class TestStockMinConseille:
    """La colonne « Stock min conseillé (variabilité) » majore le min pour
    les produits erratiques, SANS changer la quantité à commander."""

    def _cadencier(self):
        return pd.DataFrame({
            "Produit": ["REGULIER", "ERRATIQUE"],
            "CIP": ["9200", "9201"],
            "Stock": [20, 20],
            # Régulier vs en dents de scie. Valeurs NON nulles pour l'erratique
            # (des 0 intérieurs seraient lissés par la correction des ruptures
            # passées, ce qui effacerait justement la variabilité).
            "Ventes avril": [10, 2], "Ventes mai": [10, 28], "Ventes juin": [10, 3],
            "Ventes juil": [10, 27], "Ventes aout": [10, 2], "Ventes sept": [10, 28],
        })

    def _mapping(self):
        return {"cadencier": {"libelle": "Produit", "cip": "CIP",
                              "stock": "Stock",
                              "ventes": ["Ventes avril", "Ventes mai",
                                         "Ventes juin", "Ventes juil",
                                         "Ventes aout", "Ventes sept"]}}

    def test_colonne_presente(self):
        resultat = analyser_stock_rotation(self._cadencier(), self._mapping())
        assert "Stock min conseillé (variabilité)" in resultat.tableau.columns

    def test_erratique_conseille_plus_que_regulier(self):
        resultat = analyser_stock_rotation(self._cadencier(), self._mapping())
        reg = resultat.tableau[
            resultat.tableau["Nom du produit"] == "REGULIER"].iloc[0]
        err = resultat.tableau[
            resultat.tableau["Nom du produit"] == "ERRATIQUE"].iloc[0]
        # Même conso → même stock min de base, mais conseillé plus élevé pour
        # l'erratique.
        assert reg["Stock min conseillé (variabilité)"] == reg["Stock min (calculé)"]
        assert (err["Stock min conseillé (variabilité)"]
                > err["Stock min (calculé)"])

    def test_conseille_ne_change_pas_la_commande(self):
        # La colonne est indicative : la quantité à commander reste pilotée
        # par le stock min/max de base.
        resultat = analyser_stock_rotation(self._cadencier(), self._mapping())
        err = resultat.tableau[
            resultat.tableau["Nom du produit"] == "ERRATIQUE"].iloc[0]
        # Stock 20 > min de base (5) → aucune commande, malgré un conseillé
        # plus élevé.
        assert err["Qté à commander"] == 0


# ---------------------------------------------------------------------------
# Cadencier n+1 : ne ressortir que les lignes modifiées (≥ 10 %)
# ---------------------------------------------------------------------------

class TestComparerEtatPrecedent:
    def _tableau(self, min_max):
        return pd.DataFrame({
            "Code CIP": [c for c, _, _ in min_max],
            "Nom du produit": [n for _, n, _ in min_max],
            "Stock min (calculé)": [mm[0] for *_, mm in min_max],
            "Stock max (calculé)": [mm[1] for *_, mm in min_max]})

    def test_premiere_analyse_tout_modifie(self):
        tab = self._tableau([("111", "A", (10, 20)), ("222", "B", (5, 12))])
        annote, nb_mod, nb_nouv = comparer_a_etat_precedent(tab, None)
        assert annote["_modifie"].all()
        assert nb_mod == 2 and nb_nouv == 2

    def test_ligne_inchangee_exclue(self):
        prec = self._tableau([("111", "A", (10, 20))])
        courant = self._tableau([("111", "A", (10, 20))])  # identique
        annote, nb_mod, _ = comparer_a_etat_precedent(courant, prec)
        assert not annote["_modifie"].iloc[0]
        assert nb_mod == 0

    def test_variation_sous_10pct_exclue(self):
        prec = self._tableau([("111", "A", (100, 200))])
        courant = self._tableau([("111", "A", (105, 209))])  # +5 %, +4,5 %
        annote, nb_mod, _ = comparer_a_etat_precedent(courant, prec)
        assert not annote["_modifie"].iloc[0]

    def test_variation_au_dessus_10pct_incluse(self):
        prec = self._tableau([("111", "A", (100, 200))])
        courant = self._tableau([("111", "A", (100, 230))])  # max +15 %
        annote, nb_mod, _ = comparer_a_etat_precedent(courant, prec)
        assert annote["_modifie"].iloc[0]
        assert nb_mod == 1

    def test_nouveau_produit_inclus(self):
        prec = self._tableau([("111", "A", (10, 20))])
        courant = self._tableau([("111", "A", (10, 20)),
                                 ("333", "C", (4, 9))])
        annote, nb_mod, nb_nouv = comparer_a_etat_precedent(courant, prec)
        c = annote[annote["Code CIP"] == "333"].iloc[0]
        assert c["_modifie"]
        assert nb_nouv == 1

    def test_etat_a_enregistrer_colonnes(self):
        res = analyser_stock_rotation(_cadencier(), _mapping_cadencier())
        etat = etat_stock_a_enregistrer(res.tableau)
        assert list(etat.columns) == ["Code CIP", "Nom du produit",
                                      "Stock min (calculé)", "Stock max (calculé)"]


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
