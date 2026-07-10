# -*- coding: utf-8 -*-
"""Module 1 — Gestion des stocks en rotation.

Logique métier PURE, sans interface : détermine pour chaque produit du
cadencier un **stock min** et un **stock max**, afin d'éviter le
sous-stockage (rupture) et le sur-stockage (trésorerie immobilisée,
péremption).

Méthode retenue — bornes de couverture directes (validées avec le
pharmacien) :

    Stock min = consommation/jour × 14 jours   (point de commande)
    Stock max = consommation/jour × 30 jours   (plafond de réassort)

Les deux bornes sont réglables. Le stock min du jour est AJUSTÉ au
calendrier de réception : les commandes ne sont PAS reçues le samedi ni le
dimanche, donc une commande passée le vendredi n'arrive que le lundi
(+2 jours de couverture nécessaires ce jour-là), le samedi +1 jour — voir
``jours_supplementaires_weekend``.

Règle métier spécifique de l'officine (priorité sur la logique générale) :
si le stock actuel passe sous un seuil ABSOLU (10 unités par défaut,
indépendant du stock min calculé), la cible de réassort devient
DIRECTEMENT le stock max — pas de recomplètement progressif jusqu'au seul
stock min. Voir ``determiner_cible_reassort``.

ISOLATION : ce module ne lit QUE le cadencier de la pharmacie. Il ignore
tout des ruptures fournisseurs (GPNC, UNIPHARMA), de l'urgence ou du
dépannage — ces notions appartiennent exclusivement à moteur_ruptures.py.
Les deux modules mutualisent leurs calculs de consommation via commun.py,
mais aucun des deux n'importe l'autre : zéro couplage fonctionnel.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import pandas as pd

from commun import (JOURS_PAR_MOIS, calculer_rotation_mensuelle,
                    calculer_stock_jours, calculer_tendance, classer_abc,
                    corriger_faux_zeros, exporter_classeur, parser_nombre,
                    variabilite_demande)

# ---------------------------------------------------------------------------
# Constantes / valeurs par défaut (toutes reconfigurables — voir
# ParametresStockRotation, exposé aux réglages de l'interface)
# ---------------------------------------------------------------------------

SEUIL_ALERTE_UNITES_DEFAUT = 10       # règle métier : sous ce seuil → cible = max
COUVERTURE_MIN_JOURS_DEFAUT = 14      # stock min = 14 jours de consommation
COUVERTURE_MAX_JOURS_DEFAUT = 30      # stock max = 30 jours de consommation
CONSOMMATION_DEFAUT_MENSUELLE = 0.0   # repli si aucun historique (0 = désactivé)
SEUIL_DORMANT_JOURS_DEFAUT = 180      # > 6 mois de couverture → stock dormant


@dataclass
class ParametresStockRotation:
    """Paramètres configurables du calcul min/max — aucun n'est codé en dur
    dans la logique de calcul, tous sont pilotables depuis l'interface."""
    couverture_min_jours: float = COUVERTURE_MIN_JOURS_DEFAUT
    couverture_max_jours: float = COUVERTURE_MAX_JOURS_DEFAUT
    seuil_alerte_unites: float = SEUIL_ALERTE_UNITES_DEFAUT
    periode_rotation: str = "annuelle"     # "annuelle" | "3mois" | "lissee"
    corriger_ruptures_passees: bool = True
    consommation_defaut_mensuelle: float = CONSOMMATION_DEFAUT_MENSUELLE
    seuil_dormant_jours: float = SEUIL_DORMANT_JOURS_DEFAUT


# ---------------------------------------------------------------------------
# Calculs élémentaires — unitairement testables
# ---------------------------------------------------------------------------

def jours_supplementaires_weekend(date_commande: Optional[date]) -> int:
    """Jours de couverture à AJOUTER au stock min du jour, parce que les
    commandes ne sont pas réceptionnées le samedi ni le dimanche.

    Convention : une commande passée un jour ouvré est reçue le prochain
    jour de réception (lundi-vendredi). Le lendemain sert de référence :
      - vendredi → réception lundi au lieu de samedi : +2 jours ;
      - samedi   → réception lundi au lieu de dimanche : +1 jour ;
      - dimanche-jeudi → réception le lendemain : +0.
    ``None`` (date inconnue, ex. tests unitaires) → 0.
    """
    if date_commande is None:
        return 0
    jour_semaine = date_commande.weekday()  # lundi = 0 … dimanche = 6
    if jour_semaine == 4:   # vendredi
        return 2
    if jour_semaine == 5:   # samedi
        return 1
    return 0


def calculer_stock_min(consommation_jour: float, couverture_min_jours: float,
                       jours_supplementaires: float = 0) -> float:
    """Stock min = conso/jour × (couverture min + jours week-end éventuels).

    C'est le point de commande : passer sous ce niveau déclenche un
    réassort. ``jours_supplementaires`` encaisse l'absence de réception le
    week-end (voir ``jours_supplementaires_weekend``) : le vendredi, le
    stock doit tenir 2 jours de plus qu'un jour de semaine ordinaire.
    """
    return consommation_jour * (couverture_min_jours + jours_supplementaires)


def calculer_stock_max(consommation_jour: float,
                       couverture_max_jours: float) -> float:
    """Stock max = conso/jour × couverture max (plafond de réassort).

    Au-delà, le stock immobilise de la trésorerie et augmente le risque de
    péremption sans améliorer le service.
    """
    return consommation_jour * couverture_max_jours


def determiner_cible_reassort(stock_actuel: float, stock_min: float,
                              stock_max: float, seuil_alerte_unites: float):
    """Politique de réassort à 3 paliers. Renvoie ``(cible, qte, motif)``.

    - ``stock_actuel < seuil_alerte_unites`` (règle ABSOLUE, prioritaire) :
      cible = stock max directement — commande immédiate, pas de
      recomplètement partiel, quel que soit le stock min calculé ;
    - ``seuil_alerte_unites <= stock_actuel < stock_min`` : réassort
      PROGRESSIF, cible = stock min seulement (situation pas encore
      critique, pas besoin de monter jusqu'au max) ;
    - ``stock_actuel >= stock_min`` : stock suffisant, aucune commande.
    """
    if stock_actuel < seuil_alerte_unites:
        cible = stock_max
        motif = (f"Stock < {seuil_alerte_unites:g} unités — commande "
                 "immédiate jusqu'au stock max")
    elif stock_actuel < stock_min:
        cible = stock_min
        motif = "Sous le stock min — réassort progressif jusqu'au stock min"
    else:
        cible = stock_actuel
        motif = "Stock suffisant — aucune commande"
    qte = max(0, math.ceil(cible - stock_actuel))
    return cible, qte, motif


# ---------------------------------------------------------------------------
# Analyse complète du cadencier
# ---------------------------------------------------------------------------

@dataclass
class ResultatStockRotation:
    """Sortie du Module 1 : tableau min/max + produits dormants + résumé."""
    tableau: pd.DataFrame
    dormants: pd.DataFrame = field(default_factory=pd.DataFrame)
    resume: dict = field(default_factory=dict)


COLONNES_STOCK_ROTATION = [
    "Alerte", "Classe", "Code CIP", "Nom du produit", "Stock actuel",
    "Consommation/mois", "Tendance", "Variabilité", "Stock min (calculé)",
    "Stock max (calculé)", "Cible réassort", "Qté à commander", "Motif",
]
COLONNES_DORMANTS_ROTATION = ["Code CIP", "Nom du produit", "Stock actuel",
                              "Consommation/mois", "Stock (jours)",
                              "Stock max (calculé)", "Commentaire"]


def analyser_stock_rotation(cadencier: pd.DataFrame, mapping: dict,
                            params: Optional[ParametresStockRotation] = None,
                            date_analyse: Optional[date] = None
                            ) -> ResultatStockRotation:
    """Calcule stock min/max et la quantité de réassort pour chaque produit
    du cadencier. Module AUTONOME : ne lit ni GPNC ni UNIPHARMA.

    ``date_analyse`` sert UNIQUEMENT à l'ajustement week-end du stock min
    (pas de réception samedi/dimanche : le vendredi, le stock min du jour
    couvre +2 jours ; le samedi +1). Sans date : aucun ajustement.

    ``mapping`` : uniquement la clé "cadencier" du mapping habituel —
    {"libelle": str, "cip": str|None, "stock": str, "ventes": [str, ...]}.

    Si un produit n'a AUCUN historique de vente exploitable (toutes les
    colonnes de ventes à 0 ou absentes), la consommation par défaut
    ``params.consommation_defaut_mensuelle`` est utilisée à sa place — solution
    progressive : dès qu'une seule vente réelle est enregistrée, le calcul
    réel prend automatiquement le dessus (valeur par défaut désactivée en
    mettant le paramètre à 0).
    """
    params = params or ParametresStockRotation()
    m = mapping["cadencier"]
    colonnes_ventes = [c for c in m["ventes"] if c in cadencier.columns]
    # Pas de réception le week-end : couverture min du JOUR ajustée.
    jours_weekend = jours_supplementaires_weekend(date_analyse)

    lignes = []
    for _, ligne in cadencier.iterrows():
        stock = parser_nombre(ligne[m["stock"]])
        cip = (str(ligne[m["cip"]]).strip() if m.get("cip") else "")
        ventes_brutes = [ligne[c] for c in colonnes_ventes]
        nb_corriges = 0
        ventes = ventes_brutes
        if params.corriger_ruptures_passees:
            ventes, nb_corriges = corriger_faux_zeros(ventes_brutes)

        rotation = calculer_rotation_mensuelle(ventes, params.periode_rotation)
        sans_historique = all(parser_nombre(v) == 0 for v in ventes_brutes)
        if rotation <= 0 and sans_historique and params.consommation_defaut_mensuelle > 0:
            rotation = params.consommation_defaut_mensuelle

        if rotation <= 0 and stock <= 0:
            continue  # ni vente ni stock : rien à piloter

        conso_jour = rotation / JOURS_PAR_MOIS
        stock_min = calculer_stock_min(conso_jour, params.couverture_min_jours,
                                       jours_weekend)
        stock_max = calculer_stock_max(conso_jour, params.couverture_max_jours)
        # Cohérence : l'ajustement week-end ne doit jamais inverser les bornes.
        stock_max = max(stock_max, stock_min)
        cible, qte, motif = determiner_cible_reassort(
            stock, stock_min, stock_max, params.seuil_alerte_unites)
        stock_jours = calculer_stock_jours(stock, rotation)

        # L'alerte suit la quantité RÉELLEMENT à commander : un produit à
        # rotation nulle avec peu de stock (ex. arrêté, non vendu) n'a pas
        # à être signalé « action requise » si rien n'est à commander.
        if qte <= 0:
            alerte = "🟢 OK"
        elif stock < params.seuil_alerte_unites:
            alerte = "🔴 Action requise"
        else:
            alerte = "🟡 Sous le min"
        if sans_historique and rotation > 0:
            motif += " (consommation par défaut — pas d'historique)"

        lignes.append({
            "Alerte": alerte,
            "Code CIP": cip,
            "Nom du produit": str(ligne[m["libelle"]]).strip(),
            "Stock actuel": stock,
            "Consommation/mois": round(rotation, 1),
            "Tendance": calculer_tendance(ventes),
            "Variabilité": variabilite_demande(ventes),
            "Stock min (calculé)": round(stock_min, 1),
            "Stock max (calculé)": round(stock_max, 1),
            "Cible réassort": round(cible, 1),
            "Qté à commander": qte,
            "Motif": motif,
            "_stock_jours": stock_jours,
        })

    df = pd.DataFrame(lignes)
    if df.empty:
        return ResultatStockRotation(
            df.reindex(columns=COLONNES_STOCK_ROTATION),
            df.reindex(columns=COLONNES_DORMANTS_ROTATION), {})

    df["Classe"] = classer_abc(list(df["Consommation/mois"]))

    dormants = df[(df["Stock actuel"] > 0)
                  & (df["_stock_jours"] > params.seuil_dormant_jours)].copy()
    dormants["Stock (jours)"] = dormants["_stock_jours"].round(1)
    dormants["Commentaire"] = (
        f"Plus de {params.seuil_dormant_jours:.0f} j de couverture, bien "
        "au-delà du stock max — trésorerie immobilisée, envisager retour "
        "fournisseur ou arrêt de réassort.")
    dormants = (dormants.sort_values("Stock actuel", ascending=False)
                .reindex(columns=COLONNES_DORMANTS_ROTATION))

    # Priorité d'affichage : action requise d'abord, puis sous le min.
    ordre_alerte = {"🔴 Action requise": 0, "🟡 Sous le min": 1, "🟢 OK": 2}
    df["_ordre"] = df["Alerte"].map(ordre_alerte)
    tableau = (df.sort_values(["_ordre", "Qté à commander"],
                              ascending=[True, False])
               .reindex(columns=COLONNES_STOCK_ROTATION))

    resume = {
        "total_produits": len(df),
        "action_requise": int((df["Alerte"] == "🔴 Action requise").sum()),
        "sous_le_min": int((df["Alerte"] == "🟡 Sous le min").sum()),
        "nb_a": int((df["Classe"] == "A").sum()),
        "nb_b": int((df["Classe"] == "B").sum()),
        "nb_c": int((df["Classe"] == "C").sum()),
        "dormants": len(dormants),
        "dormants_boites": (float(dormants["Stock actuel"].sum())
                            if not dormants.empty else 0.0),
        "qte_totale_a_commander": int(df["Qté à commander"].sum()),
        "jours_weekend": jours_weekend,  # ajustement appliqué au stock min
    }
    return ResultatStockRotation(tableau, dormants, resume)


# ---------------------------------------------------------------------------
# Export Excel dédié
# ---------------------------------------------------------------------------

_COULEURS_ALERTE = {"🔴 Action requise": "F8CBAD", "🟡 Sous le min": "FFE699",
                    "🟢 OK": "C6EFCE"}


def exporter_stock_rotation_excel(resultat: ResultatStockRotation) -> bytes:
    """Classeur de gestion du stock en rotation : min/max + dormants."""
    return exporter_classeur(
        [("Stock min-max", resultat.tableau),
         ("Stock dormant", resultat.dormants)],
        couleurs_par_colonne={"Alerte": _COULEURS_ALERTE})
