# -*- coding: utf-8 -*-
"""Tests des règles de l'interface (ui_commun.py).

Ces fonctions décident de ce que le pharmacien voit et de ce qui part à
l'export : elles méritent le même filet que les moteurs de calcul. Elles ont
été sorties d'``app.py`` précisément pour être exécutables ici, sans
Streamlit.
"""

import pathlib
from datetime import date

import pandas as pd
import pytest

from ui_commun import (COLONNES_HISTORIQUE, COLONNES_STOCK_SIMPLES,
                       colonnes_stock_affichees, dossier_donnees,
                       filtrer_stock,
                       fusionner_historique, lignes_historique_analyse,
                       mise_a_jour_disponible,
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


class TestMiseAJourDisponible:
    """Une mise à jour peut échouer sans bruit ; comparer les numéros est
    ce qui rend la situation visible."""

    @pytest.mark.parametrize("locale,distante,attendu", [
        ("3.2", "3.3", True),
        ("3.3", "3.3", False),
        ("3.4", "3.3", False),      # version de développement, en avance
        ("3.9", "3.10", True),      # 3.10 vient APRÈS 3.9…
        ("3.10", "3.9", False),     # …ce qu'un tri alphabétique inverserait
        ("3.3", "4.0", True),
    ])
    def test_comparaison_numerique(self, locale, distante, attendu):
        assert mise_a_jour_disponible(locale, distante) is attendu

    def test_version_distante_indisponible(self):
        """Poste hors ligne : on ne signale rien plutôt que d'alarmer."""
        assert mise_a_jour_disponible("3.3", None) is False
        assert mise_a_jour_disponible("3.3", "") is False

    def test_numero_inattendu_ne_leve_pas(self):
        assert mise_a_jour_disponible("3.3", "inconnue") is False


class TestDossierDonnees:
    """Où l'application range config, historique et inventaire.

    Ce n'est pas un détail : ces chemins ne dépendent PAS du répertoire de
    lancement. Sans possibilité de les déplacer, la suite de tests lirait —
    et écraserait — les données réelles de la pharmacie.
    """

    def test_par_defaut_a_cote_du_programme(self, monkeypatch):
        monkeypatch.delenv("PHARMACIE_DONNEES", raising=False)
        attendu = pathlib.Path(__file__).resolve().parent.parent
        assert dossier_donnees() == attendu

    def test_deplacable_par_variable_d_environnement(self, monkeypatch,
                                                     tmp_path):
        monkeypatch.setenv("PHARMACIE_DONNEES", str(tmp_path))
        assert dossier_donnees() == tmp_path

    def test_dossier_cree_s_il_manque(self, monkeypatch, tmp_path):
        cible = tmp_path / "pas" / "encore" / "la"
        monkeypatch.setenv("PHARMACIE_DONNEES", str(cible))
        assert dossier_donnees().is_dir()

    def test_variable_vide_ignoree(self, monkeypatch):
        monkeypatch.setenv("PHARMACIE_DONNEES", "")
        attendu = pathlib.Path(__file__).resolve().parent.parent
        assert dossier_donnees() == attendu


class TestIsolation:
    def test_aucune_dependance_a_streamlit(self):
        """C'est ce qui rend ces règles testables : le moindre import de
        streamlit ici et le fichier redevient du code d'affichage."""
        source = (pytest.importorskip("pathlib").Path(__file__).parent.parent
                  / "ui_commun.py").read_text(encoding="utf-8")
        assert "import streamlit" not in source


class TestColonnePeremption:
    """La péremption s'affiche en MOIS/ANNÉE.

    C'est ce qui est imprimé sur les cartons, et le jour prenait une place
    que la colonne n'a pas. Le point à vérifier : la date **complète** reste
    enregistrée — seul l'affichage est raccourci.
    """

    def _colonne(self):
        pytest.importorskip("streamlit")
        import ui_stock_ferme
        return ui_stock_ferme._COLONNE_PEREMPTION

    def test_format_sans_le_jour(self):
        configuration = self._colonne()["type_config"]
        assert configuration["format"] == "MM/YYYY"
        assert configuration["type"] == "date"

    def test_tous_les_tableaux_partagent_la_meme_fabrique(self):
        """Vue essentielle, vue filtrée détaillée, tableau modifiable : les
        trois doivent s'afficher pareil. Des réglages séparés finiraient
        par diverger, et la même péremption s'écrirait de deux façons d'un
        tableau à l'autre."""
        source = (pathlib.Path(__file__).parent.parent
                  / "ui_stock_ferme.py").read_text(encoding="utf-8")
        tableaux = source.count("st.dataframe(") + source.count(
            "st.data_editor(")
        partagees = source.count("column_config=_colonnes_inventaire()")
        assert partagees == tableaux, (
            f"{tableaux} tableaux mais {partagees} passent par la fabrique")

    def test_l_ecran_montre_la_vue_essentielle(self):
        """Une fonction qui existe mais que personne n'appelle ne simplifie
        aucun écran."""
        source = (pathlib.Path(__file__).parent.parent
                  / "ui_stock_ferme.py").read_text(encoding="utf-8")
        assert "stock_ferme.vue_essentielle(" in source

    def test_le_detail_est_replie_sous_le_tableau(self):
        """Quantités, lot, péremption exacte : on en a besoin pour
        corriger, jamais pour lire l'inventaire devant l'armoire."""
        source = (pathlib.Path(__file__).parent.parent
                  / "ui_stock_ferme.py").read_text(encoding="utf-8")
        assert 'st.expander("🔧 Voir le détail' in source
        # Le tableau essentiel vient AVANT le dépliant : c'est lui qu'on
        # regarde, l'autre est l'exception.
        assert source.index("stock_ferme.vue_essentielle(") \
            < source.index('st.expander("🔧 Voir le détail')

    def test_l_impression_garde_tout(self):
        """Réduire l'ÉCRAN n'est pas réduire la liste papier : sur le
        papier on coche des quantités, et il n'y a pas de dépliant."""
        source = (pathlib.Path(__file__).parent.parent
                  / "stock_ferme.py").read_text(encoding="utf-8")
        exports = source[source.index("def exporter_csv"):]
        assert "COLONNES_ESSENTIELLES" not in exports, (
            "le CSV et le PDF doivent rester complets")

    def test_l_impression_garde_la_date_complete(self):
        """Sur le papier, il n'y a pas de colonne « Jours restants » pour
        rattraper un jour masqué : la liste de contrôle reste précise."""
        source = (pathlib.Path(__file__).parent.parent
                  / "stock_ferme.py").read_text(encoding="utf-8")
        assert "%d/%m/%Y" in source


class TestColonnesCentrees:
    """Tout le contenu du tableau est centré.

    Par défaut, Streamlit colle les nombres au bord droit de leur colonne :
    sur une colonne large, le « 1 » des boîtes se retrouvait à des
    centimètres de son en-tête, et l'œil ne savait plus à quelle colonne il
    appartenait.
    """

    def _colonnes(self):
        pytest.importorskip("streamlit")
        import ui_stock_ferme
        return ui_stock_ferme._colonnes_inventaire()

    def test_toutes_les_colonnes_sont_centrees(self):
        for nom, config in self._colonnes().items():
            assert config.get("alignment") == "center", nom

    def test_toutes_les_colonnes_affichees_sont_couvertes(self):
        """Une colonne oubliée retomberait sur l'alignement par défaut et
        trancherait avec les autres."""
        import stock_ferme
        attendues = set(["Statut"] + stock_ferme.COLONNES_AFFICHEES
                        + ["Jours restants"])
        assert set(self._colonnes()) == attendues

    def test_la_date_d_enregistrement_est_en_francais(self):
        """Elle s'affichait en 2026-08-10, seule note anglo-saxonne d'un
        écran entièrement en français."""
        config = self._colonnes()["Enregistré le"]["type_config"]
        assert config["format"] == "DD/MM/YYYY"
