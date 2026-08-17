# -*- coding: utf-8 -*-
"""Propriétés qui doivent tenir QUELLES QUE SOIENT les données.

Les autres fichiers vérifient des cas choisis : « ce cadencier-là donne ce
résultat-là ». Celui-ci vérifie des **invariants** sur des données tirées au
hasard et sur des fichiers volontairement abîmés — le hasard trouve ce que
l'exemple oublie, et les fichiers d'officine ne sont jamais propres.

Ces contrôles sont nés d'un audit du code : ils y restent pour que ce qui a
été vérifié une fois le soit à chaque exécution.
"""

import ast
import itertools
import pathlib
import random
from datetime import date, timedelta

import pandas as pd
import pytest

import moteur_ruptures
import stock_ferme as sf
import stock_rotation

AUJOURDHUI = date(2026, 8, 10)
MOIS = [f"M{i}" for i in range(1, 13)]

MAPPING_ROTATION = {"cadencier": {
    "libelle": "Libellé", "cip": "Code", "stock": "Stock",
    "commande_en_cours": "Commande en cours", "ventes": MOIS}}


def _cadencier(nombre: int, graine: int) -> pd.DataFrame:
    """Cadencier plausible : stocks à zéro, ventes en dents de scie, gros
    volumes et produits dormants mélangés."""
    hasard = random.Random(graine)
    return pd.DataFrame([{
        "Code": f"34009{i:08d}", "Libellé": f"PRODUIT {i}",
        "Stock": hasard.choice([0, 0, 1, 3, 9, 25, 120]),
        "Commande en cours": hasard.choice([0, 0, 0, 5]),
        **{m: hasard.choice([0, 0, 1, 2, 5, 12, 40, 200]) for m in MOIS},
    } for i in range(nombre)])


class TestModuleStockRotation:
    """Ce qui ne doit JAMAIS sortir du calcul de stock min/max."""

    @pytest.mark.parametrize("graine", [1, 2, 3])
    @pytest.mark.parametrize("jour", [date(2026, 8, 7),    # vendredi
                                      date(2026, 8, 10),   # lundi
                                      None])
    def test_invariants(self, graine, jour):
        tableau = stock_rotation.analyser_stock_rotation(
            _cadencier(250, graine), MAPPING_ROTATION,
            date_analyse=jour).tableau
        assert not tableau.empty

        assert (tableau["Stock min (calculé)"]
                <= tableau["Stock max (calculé)"]).all(), \
            "un stock min au-dessus du max ferait commander en boucle"
        assert (tableau["Qté à commander"] >= 0).all(), \
            "une quantité négative se commanderait à l'envers"

        # Ce qu'on commande comble exactement le manque, ce qui est déjà en
        # route déduit — sans quoi on commande deux fois.
        a_commander = tableau[tableau["Qté à commander"] > 0]
        en_cours = pd.to_numeric(a_commander["Commande en cours"],
                                 errors="coerce").fillna(0)
        attendu = (a_commander["Cible réassort"] - a_commander["Stock actuel"]
                   - en_cours).clip(lower=0)
        assert (a_commander["Qté à commander"] == attendu).all()

        for colonne in ("Stock min (calculé)", "Stock max (calculé)",
                        "Qté à commander"):
            assert (tableau[colonne] == tableau[colonne].round()).all(), \
                f"{colonne} : une demi-boîte ne se commande pas"
            assert not tableau[colonne].isna().any()


def _jeu_ruptures():
    """Cadencier + les deux listes fournisseurs, cohérents entre eux."""
    cadencier = pd.DataFrame({
        "Produit": [f"PRODUIT {i}" for i in range(12)],
        "CIP": [f"{1000 + i}" for i in range(12)],
        "Stock": [0, 3, 50, 1, 0, 12, 7, 0, 2, 30, 4, 9],
        "Ventes avril": [6, 16, 4, 13, 0, 8, 60, 0, 40, 24, 28, 3],
        "Ventes mai": [6, 17, 4, 13, 0, 8, 58, 9, 40, 26, 30, 3],
        "Ventes juin": [6, 16, 4, 13, 0, 8, 62, 11, 40, 25, 32, 3],
        "Commande en cours": [0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0],
    })
    gpnc = pd.DataFrame({
        "Libellé": [f"PRODUIT {i}" for i in range(8)],
        "CIP": [f"{1000 + i}" for i in range(8)],
        "Date réappro": ["", "15/09/2026", "", "01/10/2026",
                         "", "", "20/09/2026", ""],
    })
    unipharma = pd.DataFrame({
        "Désignation": ["PRODUIT 3", "PRODUIT 5", "PRODUIT 7"],
        "CIP": ["1003", "1005", "1007"],
    })
    return cadencier, gpnc, unipharma


MAPPING_RUPTURES = {
    "cadencier": {"libelle": "Produit", "cip": "CIP", "stock": "Stock",
                  "ventes": ["Ventes avril", "Ventes mai", "Ventes juin"],
                  "commande_en_cours": "Commande en cours"},
    "gpnc": {"libelle": "Libellé", "cip": "CIP",
             "date_reappro": "Date réappro"},
    "unipharma": {"libelle": "Désignation", "cip": "CIP"},
}


def _produits(tableau) -> set:
    if not isinstance(tableau, pd.DataFrame) or tableau.empty:
        return set()
    colonne = next((c for c in ("Produit", "Nom du produit")
                    if c in tableau.columns), None)
    return set(tableau[colonne]) if colonne else set()


class TestModuleRuptures:
    """Ce qui ne doit JAMAIS sortir de la commande du jour."""

    def _verifier(self, resultat):
        # Commander chez UNIPHARMA un produit qu'on met AUSSI en vigilance,
        # c'est le commander deux fois dans la même journée.
        assert not (_produits(resultat.onglet1)
                    & _produits(resultat.vigilance))
        for nom in ("onglet1", "onglet2", "vigilance", "ecartes_justesse"):
            tableau = getattr(resultat, nom)
            if not isinstance(tableau, pd.DataFrame) or tableau.empty:
                continue
            produits = _produits(tableau)
            if produits:
                assert len(produits) == len(tableau), \
                    f"{nom} : un produit y figure deux fois"
            for colonne in tableau.columns:
                if "Cmd" in str(colonne):
                    quantites = pd.to_numeric(tableau[colonne],
                                              errors="coerce").fillna(0)
                    assert (quantites >= 0).all()
                    assert (quantites == quantites.round()).all()

    @pytest.mark.parametrize("periode", ["annuelle", "semestrielle",
                                         "trimestrielle", "mensuelle"])
    @pytest.mark.parametrize("prudente,abc", list(
        itertools.product((False, True), repeat=2)))
    def test_invariants_selon_les_reglages(self, periode, prudente, abc):
        cadencier, gpnc, unipharma = _jeu_ruptures()
        self._verifier(moteur_ruptures.analyser(
            cadencier, gpnc, unipharma, MAPPING_RUPTURES, AUJOURDHUI,
            periode=periode, rotation_prudente=prudente, politique_abc=abc))

    def test_fichiers_abimes(self):
        """Stock négatif, vente manquante, ligne en double, date impossible :
        un fichier d'officine n'est jamais propre, et l'analyse du jour ne
        peut pas s'arrêter pour autant."""
        cadencier, gpnc, unipharma = _jeu_ruptures()
        cadencier.loc[0, "Stock"] = -5
        cadencier.loc[1, "Ventes mai"] = None
        cadencier = pd.concat([cadencier, cadencier.iloc[[2]]],
                              ignore_index=True)
        gpnc.loc[0, "Date réappro"] = "32/13/2026"
        gpnc.loc[1, "Date réappro"] = "hier"
        self._verifier(moteur_ruptures.analyser(
            cadencier, gpnc, unipharma, MAPPING_RUPTURES, AUJOURDHUI))

    def test_fichiers_vides(self):
        cadencier, gpnc, unipharma = _jeu_ruptures()
        self._verifier(moteur_ruptures.analyser(
            cadencier.iloc[0:0], gpnc, unipharma, MAPPING_RUPTURES,
            AUJOURDHUI))
        self._verifier(moteur_ruptures.analyser(
            cadencier, gpnc.iloc[0:0], unipharma.iloc[0:0],
            MAPPING_RUPTURES, AUJOURDHUI))


class TestModuleStockFerme:
    """Ce qui ne doit JAMAIS arriver à un inventaire de stock fermé."""

    def _inventaire(self, graine=5, nombre=40):
        hasard = random.Random(graine)
        inventaire = sf.inventaire_vide()
        for i in range(nombre):
            inventaire = sf.ajouter_entree(inventaire, sf.EntreeStock(
                cip=hasard.choice([f"340093000{i:04d}", ""]),
                nom=f"PRODUIT {i}", dosage=hasard.choice(["", "10 mg"]),
                boites=hasard.randint(1, 9),
                unites_par_boite=hasard.choice([0, 8, 30]),
                unites_vrac=hasard.randint(0, 7),
                peremption=hasard.choice(
                    [None, AUJOURDHUI + timedelta(days=hasard.randint(-300,
                                                                      900))]),
                lot=f"L{i}"), AUJOURDHUI)
        return inventaire

    def test_le_total_d_unites_est_toujours_juste(self):
        vue = sf.inventaire_affichable(self._inventaire(), AUJOURDHUI)
        for _, ligne in vue.iterrows():
            assert int(ligne["Total unités"]) == sf.total_unites(
                ligne["Boîtes"], ligne["Unités par boîte"],
                ligne["Unités en vrac"])

    def test_le_resume_concorde_avec_le_tableau(self):
        """Les compteurs du bandeau et le tableau viennent du même
        inventaire : ils ne peuvent pas se contredire."""
        inventaire = self._inventaire()
        resume = sf.resume_inventaire(inventaire, AUJOURDHUI)
        vue = sf.inventaire_affichable(inventaire, AUJOURDHUI)
        statuts = vue["Statut"].value_counts()
        assert resume["lignes"] == len(vue)
        assert resume["boites"] == int(vue["Boîtes"].sum())
        assert resume["perimes"] == statuts.get(sf.STATUT_PERIME, 0)
        assert resume["imminents"] == statuts.get(sf.STATUT_IMMINENT, 0)

    @pytest.mark.parametrize("tri", sf.TRIS)
    def test_l_affichage_est_idempotent(self, tri):
        """Réafficher un tableau déjà affiché ne doit rien changer — sinon
        le dosage se recollerait au nom à chaque passage."""
        premier = sf.inventaire_affichable(self._inventaire(), AUJOURDHUI, tri)
        second = sf.inventaire_affichable(premier, AUJOURDHUI, tri)
        assert list(premier["Nom du produit"]) == list(second["Nom du produit"])

    @pytest.mark.parametrize("tri", sf.TRIS)
    def test_le_tri_ne_depend_pas_de_l_ordre_du_fichier(self, tri):
        inventaire = self._inventaire()
        attendu = list(sf.inventaire_affichable(
            inventaire, AUJOURDHUI, tri)["Nom du produit"])
        melange = list(sf.inventaire_affichable(
            inventaire.sample(frac=1, random_state=9),
            AUJOURDHUI, tri)["Nom du produit"])
        assert attendu == melange

    @pytest.mark.parametrize("cip", ["3400930000011", ""])
    def test_ce_qui_entre_peut_toujours_ressortir(self, cip):
        """Le tour complet, y compris pour un produit SANS code CIP — dont
        l'identité repose sur le seul nom."""
        inventaire = sf.ajouter_entree(sf.inventaire_vide(), sf.EntreeStock(
            cip=cip, nom="TEST", dosage="10 mg", boites=3,
            unites_par_boite=20, peremption=date(2027, 5, 31), lot="L1"),
            AUJOURDHUI)
        lot = sf.lots_sortables(inventaire, AUJOURDHUI)[0]
        apres = sf.retirer_entree(inventaire, lot["cip"], lot["nom"],
                                  lot["peremption"], lot["lot"], boites=3)
        assert len(apres) == 0

    def test_filtrer_conserve_ce_qu_il_ne_filtre_pas(self):
        inventaire = self._inventaire()
        for tri in sf.TRIS:
            tout = sf.filtrer_inventaire(inventaire, aujourdhui=AUJOURDHUI,
                                         tri=tri)
            assert len(tout) == len(inventaire)


class TestIsolationDesModules:
    """Les modules métier ne s'importent jamais l'un l'autre.

    C'est ce qui garantit qu'on peut faire évoluer la politique de stock
    sans risquer de casser les ruptures, et le stock fermé sans toucher aux
    commandes spéciales. Une dépendance ajoutée par commodité un jour de
    hâte se paie des mois plus tard, et rien ne la signale — sauf ce test.
    """

    #: Le seul module de service que les moteurs ont le droit d'importer.
    #: Il ne connaît aucun métier : verrou, écriture atomique, empreinte.
    SERVICES_AUTORISES = {"stockage_partage"}

    #: Modules du projet, tels qu'ils vivent à la racine.
    def _modules_du_projet(self) -> set:
        racine = pathlib.Path(__file__).resolve().parent.parent
        return {f.stem for f in racine.glob("*.py")}

    def _imports(self, nom: str) -> set:
        """Modules du projet importés par ce fichier, quel que soit le style
        (``import x``, ``import x as y``, ``from x import z``)."""
        racine = pathlib.Path(__file__).resolve().parent.parent
        arbre = ast.parse((racine / f"{nom}.py").read_text(encoding="utf-8"))
        projet = self._modules_du_projet()
        trouves = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                trouves |= {a.name.split(".")[0] for a in noeud.names}
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                trouves.add(noeud.module.split(".")[0])
        return trouves & projet

    @pytest.mark.parametrize("moteur", ["stock_ferme", "commandes_speciales"])
    def test_un_moteur_n_importe_que_le_service_de_stockage(self, moteur):
        interdits = self._imports(moteur) - self.SERVICES_AUTORISES
        assert not interdits, (
            f"{moteur}.py importe {sorted(interdits)} : la logique métier "
            "doit rester indépendante")

    def test_le_stock_ferme_et_les_commandes_s_ignorent(self):
        """Le rapprochement du module 4 lit le FICHIER du stock fermé, pas
        son code : c'est ce qui permet de faire évoluer l'un sans l'autre."""
        assert "stock_ferme" not in self._imports("commandes_speciales")
        assert "commandes_speciales" not in self._imports("stock_ferme")

    def test_les_deux_modules_du_cadencier_s_ignorent(self):
        """La mutualisation passe exclusivement par ``commun.py``."""
        assert "moteur_ruptures" not in self._imports("stock_rotation")
        assert "stock_rotation" not in self._imports("moteur_ruptures")

    def test_le_service_de_stockage_ne_connait_aucun_metier(self):
        """S'il importait un module métier, il ne serait plus partageable —
        et la mécanique du verrou finirait dupliquée."""
        assert self._imports("stockage_partage") == set()

    @pytest.mark.parametrize("moteur", ["stock_ferme", "commandes_speciales",
                                        "stock_rotation", "moteur_ruptures",
                                        "stockage_partage"])
    def test_aucun_moteur_n_importe_streamlit(self, moteur):
        """La logique métier doit être testable sans navigateur ni session :
        c'est ce qui rend possible les 700 tests qui tournent en 30 s."""
        racine = pathlib.Path(__file__).resolve().parent.parent
        source = (racine / f"{moteur}.py").read_text(encoding="utf-8")
        assert "import streamlit" not in source
