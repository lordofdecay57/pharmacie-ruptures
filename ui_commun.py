# -*- coding: utf-8 -*-
"""Fonctions PURES de l'interface — sans Streamlit, donc testables.

`app.py` mélangeait décisions et rendu : ce qui part à l'export, ce que le
filtre laisse passer, ce qui distingue deux analyses. Ces règles se testent
comme n'importe quelle règle métier ; seul l'affichage reste dans `app.py`.

Aucune de ces fonctions n'importe `streamlit` : c'est ce qui les rend
exécutables dans la suite de tests.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Optional, Sequence

import pandas as pd

#: Colonnes de l'historique des analyses de ruptures.
COLONNES_HISTORIQUE = ["Date analyse", "Produit", "Urgence",
                       "Qté à commander (Cmd)", "Date réappro", "Type"]

#: Vue « simple » du stock en rotation : le document de base, centré sur le
#: stock min/max. Stock actuel et quantité à commander sont réservés à la
#: vue détaillée (« ＋ Colonnes d'analyse »).
COLONNES_STOCK_SIMPLES = ["Alerte", "Code CIP", "Nom du produit",
                          "Stock min (calculé)", "Stock max (calculé)",
                          "Stock min conseillé (variabilité)"]


# ---------------------------------------------------------------------------
# Empreintes : distinguer deux fichiers, deux analyses
# ---------------------------------------------------------------------------

def exporter_csv(tableau: pd.DataFrame) -> bytes:
    """Tableau → CSV français (« ; » + BOM : Excel l'ouvre sans réglage).

    Complète l'export Excel : un CSV s'ouvre partout, se relit sans macro et
    s'importe dans un autre logiciel — l'Excel mis en forme reste le
    document de travail, le CSV le format d'échange.
    """
    if tableau is None:
        tableau = pd.DataFrame()
    propre = tableau[[c for c in tableau.columns if not str(c).startswith("_")]]
    return propre.to_csv(index=False, sep=";").encode("utf-8-sig")


def signature_colonnes(colonnes: Sequence) -> str:
    """Empreinte courte de la liste de colonnes d'un fichier.

    Suffixe les clés des widgets de mapping : dès qu'un fichier de structure
    DIFFÉRENTE est chargé, les widgets repartent à zéro au lieu d'hériter
    d'une sélection mémorisée pour un AUTRE fichier — sinon une colonne
    correcte pour l'ancien cadencier mais fausse pour le nouveau reste
    cochée silencieusement.
    """
    empreinte = "|".join(str(c) for c in colonnes)
    return hashlib.md5(empreinte.encode("utf-8")).hexdigest()[:8]


def signature_tableau(tableau: Optional[pd.DataFrame]) -> str:
    """Empreinte du CONTENU d'un tableau, pour indexer une clé de widget.

    `st.data_editor` mémorise les cases cochées et les cellules modifiées
    sous sa clé, **par position de ligne**. Une clé fixe fait donc rejouer
    les corrections d'hier sur les lignes d'aujourd'hui : après une nouvelle
    analyse, un produit peut arriver décoché parce qu'un AUTRE produit
    l'était à la même place — et la commande part incomplète sans que rien
    ne le signale. Indexer la clé sur le contenu règle le problème sans
    avoir à penser à réinitialiser quoi que ce soit.
    """
    if tableau is None or tableau.empty:
        return "vide"
    try:
        empreinte = int(pd.util.hash_pandas_object(tableau, index=False).sum())
    except TypeError:  # colonnes non hachables (objets) : repli sur le texte
        empreinte = hash(tableau.to_csv(index=False))
    return f"{empreinte & 0xFFFFFFFF:08x}"


# ---------------------------------------------------------------------------
# Filtrage du tableau du stock en rotation
# ---------------------------------------------------------------------------

def filtrer_stock(tableau: pd.DataFrame, recherche: str = "",
                  filtre_alerte: str = "Toutes") -> pd.DataFrame:
    """Recherche libre (nom ou code CIP) + filtre par alerte.

    La recherche est insensible à la casse et n'interprète PAS son terme
    comme une expression régulière : un pharmacien qui tape « VITAMINE D3 »
    ou « (30) » cherche ce texte, pas un motif.
    """
    if tableau is None or tableau.empty:
        return tableau
    resultat = tableau
    terme = str(recherche or "").strip().upper()
    if terme:
        noms = resultat["Nom du produit"].astype(str).str.upper()
        codes = resultat["Code CIP"].astype(str)
        resultat = resultat[noms.str.contains(terme, regex=False)
                            | codes.str.contains(terme, regex=False)]
    if filtre_alerte and filtre_alerte != "Toutes":
        resultat = resultat[resultat["Alerte"] == filtre_alerte]
    return resultat


def colonnes_stock_affichees(tableau: pd.DataFrame,
                             detail_complet: bool) -> list:
    """Colonnes à montrer, selon que les colonnes d'analyse sont demandées.

    Sélection DÉFENSIVE : on ne garde que les colonnes réellement présentes.
    Un résultat calculé par une version antérieure et resté en mémoire de
    session après une mise à jour n'a pas les colonnes récentes — une
    sélection naïve lèverait un KeyError en plein écran.
    """
    if tableau is None:
        return []
    if detail_complet:  # tout sauf les colonnes de travail internes
        return [c for c in tableau.columns if not str(c).startswith("_")]
    return [c for c in COLONNES_STOCK_SIMPLES if c in tableau.columns]


# ---------------------------------------------------------------------------
# Historique des analyses de ruptures
# ---------------------------------------------------------------------------

def lignes_historique_analyse(resultat, date_analyse: date) -> pd.DataFrame:
    """Lignes d'historique produites par une analyse de ruptures.

    Trois sources : les produits à commander, ceux sans solution, et les
    écartés de justesse. Ces derniers sont enregistrés en « surveillance »
    pour que leurs dates de réappro annoncées permettent de détecter un
    glissement AVANT que le produit ne bascule en commande.
    """
    jour = date_analyse.strftime("%Y-%m-%d")
    sources = ((getattr(resultat, "onglet1", None), None, "commande"),
               (getattr(resultat, "onglet2", None), "❌ SANS SOLUTION",
                "commande"),
               (getattr(resultat, "ecartes_justesse", None),
                "⚠️ SURVEILLANCE", "surveillance"))
    lignes = []
    for tableau, urgence_defaut, type_ligne in sources:
        if tableau is None or tableau.empty:
            continue
        sous = tableau[["Produit"]].copy()
        sous["Date analyse"] = jour
        sous["Urgence"] = (tableau["Urgence"] if "Urgence" in tableau.columns
                           else urgence_defaut)
        sous["Qté à commander (Cmd)"] = (
            tableau["Qté à commander (Cmd)"]
            if "Qté à commander (Cmd)" in tableau.columns else "")
        # Date de réappro annoncée : mémorisée pour détecter les glissements.
        sous["Date réappro"] = (tableau["Date réappro GPNC"]
                                if "Date réappro GPNC" in tableau.columns
                                else "")
        sous["Type"] = type_ligne
        lignes.append(sous[COLONNES_HISTORIQUE])
    if not lignes:
        return pd.DataFrame(columns=COLONNES_HISTORIQUE)
    return pd.concat(lignes, ignore_index=True)


def fusionner_historique(historique: pd.DataFrame, nouvelles: pd.DataFrame,
                         date_analyse: date) -> pd.DataFrame:
    """Historique mis à jour : l'analyse du jour REMPLACE celle du même jour.

    Ré-analyser deux fois la même journée est courant (on corrige un
    mapping, on redépose un fichier) : sans ce remplacement, le produit
    apparaîtrait deux fois et le comptage « déjà signalé N fois » serait
    faussé.
    """
    jour = date_analyse.strftime("%Y-%m-%d")
    if historique is None or historique.empty:
        base = pd.DataFrame(columns=COLONNES_HISTORIQUE)
    else:
        base = historique[historique["Date analyse"].astype(str) != jour]
    if nouvelles is None or nouvelles.empty:
        return base.reset_index(drop=True)
    return pd.concat([base, nouvelles], ignore_index=True)
