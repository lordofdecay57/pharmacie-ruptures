# -*- coding: utf-8 -*-
"""Module 1 — Gestion des stocks en rotation.

Logique métier PURE, sans interface : détermine pour chaque produit du
cadencier un **stock min** et un **stock max**, afin d'éviter le
sous-stockage (rupture) et le sur-stockage (trésorerie immobilisée,
péremption).

Méthode retenue — point de commande à recomplètement périodique (méthode
standard de gestion de stock) :

    Stock min = consommation/jour × (délai de réappro + stock de sécurité)
    Stock max = Stock min + consommation/jour × fréquence de réassort visée

Le délai de réappro et le stock de sécurité sont exprimés en JOURS de
consommation (plus intuitif à régler pour un pharmacien que des unités
absolues, et cohérent avec le fait que les deux se traduisent en jours).

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
LEAD_TIME_JOURS_DEFAUT = 5            # délai de réappro fournisseur
STOCK_SECURITE_JOURS_DEFAUT = 7       # marge de sécurité, en jours de conso
FREQUENCE_REASSORT_JOURS_DEFAUT = 14  # fréquence de commande visée
CONSOMMATION_DEFAUT_MENSUELLE = 0.0   # repli si aucun historique (0 = désactivé)
SEUIL_DORMANT_JOURS_DEFAUT = 180      # > 6 mois de couverture → stock dormant


@dataclass
class ParametresStockRotation:
    """Paramètres configurables du calcul min/max — aucun n'est codé en dur
    dans la logique de calcul, tous sont pilotables depuis l'interface."""
    lead_time_jours: float = LEAD_TIME_JOURS_DEFAUT
    stock_securite_jours: float = STOCK_SECURITE_JOURS_DEFAUT
    frequence_reassort_jours: float = FREQUENCE_REASSORT_JOURS_DEFAUT
    seuil_alerte_unites: float = SEUIL_ALERTE_UNITES_DEFAUT
    periode_rotation: str = "annuelle"     # "annuelle" | "3mois" | "lissee"
    corriger_ruptures_passees: bool = True
    consommation_defaut_mensuelle: float = CONSOMMATION_DEFAUT_MENSUELLE
    seuil_dormant_jours: float = SEUIL_DORMANT_JOURS_DEFAUT


# ---------------------------------------------------------------------------
# Calculs élémentaires — unitairement testables
# ---------------------------------------------------------------------------

def calculer_stock_min(consommation_jour: float, lead_time_jours: float,
                       stock_securite_jours: float) -> float:
    """Stock min = conso/jour × (délai de réappro + stock de sécurité).

    C'est le point de commande classique (reorder point) : le stock minimal
    qui doit encore couvrir la consommation pendant tout le délai de
    livraison, plus une marge de sécurité contre les aléas de vente.
    """
    return consommation_jour * (lead_time_jours + stock_securite_jours)


def calculer_stock_max(stock_min: float, consommation_jour: float,
                       frequence_reassort_jours: float) -> float:
    """Stock max = stock min + conso/jour × fréquence de réassort visée.

    La quantité de réassort optimale est ici approximée par la consommation
    prévue jusqu'à la prochaine commande (modèle de recomplètement
    périodique) : plus la fréquence de commande visée est faible (on
    commande rarement), plus le stock max grimpe.
    """
    return stock_min + consommation_jour * frequence_reassort_jours


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
                            params: Optional[ParametresStockRotation] = None
                            ) -> ResultatStockRotation:
    """Calcule stock min/max et la quantité de réassort pour chaque produit
    du cadencier. Module AUTONOME : ne lit ni GPNC ni UNIPHARMA.

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
        stock_min = calculer_stock_min(conso_jour, params.lead_time_jours,
                                       params.stock_securite_jours)
        stock_max = calculer_stock_max(stock_min, conso_jour,
                                       params.frequence_reassort_jours)
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
