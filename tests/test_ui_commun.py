# -*- coding: utf-8 -*-
"""Tests des règles de l'interface (ui_commun.py).

Ces fonctions décident de ce que le pharmacien voit et de ce qui part à
l'export : elles méritent le même filet que les moteurs de calcul. Elles ont
été sorties d'``app.py`` précisément pour être exécutables ici, sans
Streamlit.
"""

from datetime import date

import pandas as pd
import pytest

from ui_commun import (COLONNES_HISTORIQUE, COLONNES_STOCK_SIMPLES,
                       colonnes_stock_affichees, filtrer_stock,
                       fusionner_historique, lignes_historique_analyse,
                       signature_colonnes, signature_tableau)

JOUR = date(2026, 7, 31)


def _stock():
    return pd.DataFrame([
        {"Alerte": "🔴 Action requise", "Code CIP": "3400930000012",
         "Nom du produit": "DOLIPRANE 1000", "Stock min (calculé)": 3,
         "Stock max (calculé)": 9, "Stock min conseillé (variabilité)": 4,
         "Stock actuel": 1, "Qté à commander": 8, "_stock_jours": 2.0},
        {"Alerte": "🟢 OK", "Code CIP": "3400930000029",
         "Nom du produit": "VITAMINE D3 (30)", "Stock min (calculé)": 2,
         "Stock max (calculé)": 5, "Stock min conseillé (variabilité)": 2,
         "Stock actuel": 6, "Qté à commander": 0, "_stock_jours": 40.0},
        {"Alerte": "🟢 OK", "Code CIP": "3400930000036",
         "Nom du produit": "AMOXICILLINE", "Stock min (calculé)": 1,
         "Stock max (calculé)": 4, "Stock min conseillé (variabilité)": 1,
         "Stock actuel": 3, "Qté à commander": 0, "_stock_jours": 20.0},
    ])


# ---------------------------------------------------------------------------
# Empreintes
# ---------------------------------------------------------------------------

class TestSignatureColonnes:
    def test_stable_pour_les_memes_colonnes(self):
        assert signature_colonnes(["A", "B"]) == signature_colonnes(["A", "B"])

    def test_change_si_les_colonnes_changent(self):
        assert signature_colonnes(["A", "B"]) != signature_colonnes(["A", "C"])

    def test_sensible_a_l_ordre(self):
        assert signature_colonnes(["A", "B"]) != signature_colonnes(["B", "A"])

    def test_courte_et_lisible(self):
        assert len(signature_colonnes(["A"])) == 8


class TestSignatureTableau:
    """Cette empreinte protège la commande : elle doit changer dès que
    l'analyse change, et JAMAIS entre deux rendus de la même analyse."""

    def test_stable_entre_deux_rendus(self):
        assert signature_tableau(_stock()) == signature_tableau(_stock())

    def test_change_si_une_valeur_change(self):
        autre = _stock()
        autre.loc[0, "Qté à commander"] = 99
        assert signature_tableau(_stock()) != signature_tableau(autre)

    def test_change_si_un_produit_change(self):
        autre = _stock()
        autre.loc[0, "Nom du produit"] = "AUTRE PRODUIT"
        assert signature_tableau(_stock()) != signature_tableau(autre)

    def test_change_si_une_ligne_disparait(self):
        assert signature_tableau(_stock()) != signature_tableau(_stock().iloc[1:])

    def test_ignore_l_index(self):
        """Un tableau refiltré garde des index d'origine : l'empreinte ne
        doit pas dépendre de cet artefact."""
        decale = _stock().iloc[[0, 1, 2]].copy()
        decale.index = [10, 11, 12]
        assert signature_tableau(_stock()) == signature_tableau(decale)

    def test_tableau_vide(self):
        assert signature_tableau(pd.DataFrame()) == "vide"
        assert signature_tableau(None) == "vide"


# ---------------------------------------------------------------------------
# Filtrage du tableau du stock
# ---------------------------------------------------------------------------

class TestFiltrerStock:
    def test_recherche_par_nom_insensible_a_la_casse(self):
        trouve = filtrer_stock(_stock(), recherche="doliprane")
        assert list(trouve["Nom du produit"]) == ["DOLIPRANE 1000"]

    def test_recherche_par_code_cip(self):
        trouve = filtrer_stock(_stock(), recherche="3400930000029")
        assert list(trouve["Nom du produit"]) == ["VITAMINE D3 (30)"]

    def test_recherche_partielle(self):
        assert len(filtrer_stock(_stock(), recherche="34009300000")) == 3

    def test_terme_non_interprete_comme_expression_reguliere(self):
        """« (30) » est une recherche littérale, pas un groupe de capture —
        sinon la parenthèse ferait planter la page."""
        trouve = filtrer_stock(_stock(), recherche="(30)")
        assert list(trouve["Nom du produit"]) == ["VITAMINE D3 (30)"]

    def test_recherche_sans_resultat(self):
        assert filtrer_stock(_stock(), recherche="INEXISTANT").empty

    def test_espaces_autour_du_terme_ignores(self):
        assert len(filtrer_stock(_stock(), recherche="  DOLIPRANE  ")) == 1

    def test_filtre_par_alerte(self):
        trouve = filtrer_stock(_stock(), filtre_alerte="🟢 OK")
        assert len(trouve) == 2

    def test_filtre_toutes_ne_filtre_rien(self):
        assert len(filtrer_stock(_stock(), filtre_alerte="Toutes")) == 3

    def test_recherche_et_filtre_se_cumulent(self):
        trouve = filtrer_stock(_stock(), recherche="34009300000",
                               filtre_alerte="🔴 Action requise")
        assert list(trouve["Nom du produit"]) == ["DOLIPRANE 1000"]

    def test_tableau_vide(self):
        vide = pd.DataFrame(columns=["Alerte", "Code CIP", "Nom du produit"])
        assert filtrer_stock(vide, recherche="X").empty


class TestColonnesAffichees:
    def test_vue_simple_centree_sur_le_stock_min_max(self):
        colonnes = colonnes_stock_affichees(_stock(), detail_complet=False)
        assert colonnes == COLONNES_STOCK_SIMPLES
        # Stock actuel et Qté à commander relèvent des colonnes d'analyse.
        assert "Stock actuel" not in colonnes
        assert "Qté à commander" not in colonnes

    def test_vue_detaillee_ajoute_les_colonnes_d_analyse(self):
        colonnes = colonnes_stock_affichees(_stock(), detail_complet=True)
        assert "Stock actuel" in colonnes and "Qté à commander" in colonnes

    def test_colonnes_techniques_jamais_affichees(self):
        for detail in (True, False):
            assert "_stock_jours" not in colonnes_stock_affichees(_stock(),
                                                                  detail)

    def test_colonne_absente_ne_leve_pas_d_erreur(self):
        """Un résultat calculé par une version antérieure n'a pas les
        colonnes récentes : la sélection doit rester silencieuse."""
        ancien = _stock().drop(columns=["Stock min conseillé (variabilité)"])
        colonnes = colonnes_stock_affichees(ancien, detail_complet=False)
        assert "Stock min conseillé (variabilité)" not in colonnes
        assert ancien[colonnes] is not None  # la sélection passe


# ---------------------------------------------------------------------------
# Historique des analyses
# ---------------------------------------------------------------------------

class _Resultat:
    def __init__(self, onglet1=None, onglet2=None, justesse=None):
        vide = pd.DataFrame()
        self.onglet1 = onglet1 if onglet1 is not None else vide
        self.onglet2 = onglet2 if onglet2 is not None else vide
        self.ecartes_justesse = justesse if justesse is not None else vide


class TestHistorique:
    def test_les_trois_sources_sont_enregistrees(self):
        resultat = _Resultat(
            onglet1=pd.DataFrame([{"Produit": "A", "Urgence": "🔴 URGENT",
                                   "Qté à commander (Cmd)": 4,
                                   "Date réappro GPNC": "05/08/2026"}]),
            onglet2=pd.DataFrame([{"Produit": "B"}]),
            justesse=pd.DataFrame([{"Produit": "C",
                                    "Date réappro GPNC": "10/08/2026"}]))
        lignes = lignes_historique_analyse(resultat, JOUR)
        assert list(lignes.columns) == COLONNES_HISTORIQUE
        assert list(lignes["Produit"]) == ["A", "B", "C"]
        assert list(lignes["Type"]) == ["commande", "commande", "surveillance"]

    def test_urgence_par_defaut_des_sans_solution(self):
        resultat = _Resultat(onglet2=pd.DataFrame([{"Produit": "B"}]))
        assert (lignes_historique_analyse(resultat, JOUR)["Urgence"].iloc[0]
                == "❌ SANS SOLUTION")

    def test_date_de_reappro_conservee_pour_la_surveillance(self):
        """C'est elle qui permet de détecter une réappro repoussée AVANT
        que le produit ne bascule en commande."""
        resultat = _Resultat(justesse=pd.DataFrame(
            [{"Produit": "C", "Date réappro GPNC": "10/08/2026"}]))
        assert (lignes_historique_analyse(resultat, JOUR)["Date réappro"]
                .iloc[0] == "10/08/2026")

    def test_analyse_vide(self):
        lignes = lignes_historique_analyse(_Resultat(), JOUR)
        assert lignes.empty and list(lignes.columns) == COLONNES_HISTORIQUE

    def test_reanalyse_du_meme_jour_remplace(self):
        """Ré-analyser deux fois la même journée est courant : sans
        remplacement, « déjà signalé N fois » serait faussé."""
        ancien = pd.DataFrame([
            {"Date analyse": "2026-07-31", "Produit": "VIEUX",
             "Urgence": "", "Qté à commander (Cmd)": "", "Date réappro": "",
             "Type": "commande"},
            {"Date analyse": "2026-07-30", "Produit": "AVANT-HIER",
             "Urgence": "", "Qté à commander (Cmd)": "", "Date réappro": "",
             "Type": "commande"}])
        nouvelles = lignes_historique_analyse(
            _Resultat(onglet2=pd.DataFrame([{"Produit": "NOUVEAU"}])), JOUR)
        fusion = fusionner_historique(ancien, nouvelles, JOUR)
        assert list(fusion["Produit"]) == ["AVANT-HIER", "NOUVEAU"]

    def test_historique_vide_au_depart(self):
        nouvelles = lignes_historique_analyse(
            _Resultat(onglet2=pd.DataFrame([{"Produit": "A"}])), JOUR)
        fusion = fusionner_historique(pd.DataFrame(), nouvelles, JOUR)
        assert list(fusion["Produit"]) == ["A"]

    def test_analyse_vide_n_efface_que_le_jour(self):
        ancien = pd.DataFrame([
            {"Date analyse": "2026-07-30", "Produit": "HIER", "Urgence": "",
             "Qté à commander (Cmd)": "", "Date réappro": "",
             "Type": "commande"}])
        fusion = fusionner_historique(ancien, pd.DataFrame(), JOUR)
        assert list(fusion["Produit"]) == ["HIER"]


class TestIsolation:
    def test_aucune_dependance_a_streamlit(self):
        """C'est ce qui rend ces règles testables : le moindre import de
        streamlit ici et le fichier redevient du code d'affichage."""
        source = (pytest.importorskip("pathlib").Path(__file__).parent.parent
                  / "ui_commun.py").read_text(encoding="utf-8")
        assert "import streamlit" not in source
