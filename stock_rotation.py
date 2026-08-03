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

from commun import (JOURS_PAR_MOIS, SEUILS_VARIABILITE,
                    calculer_rotation_mensuelle, calculer_stock_jours,
                    calculer_tendance, classer_abc, coefficient_variation,
                    corriger_faux_zeros, exporter_classeur, normaliser_libelle,
                    parser_nombre, variabilite_demande)

# ---------------------------------------------------------------------------
# Constantes / valeurs par défaut (toutes reconfigurables — voir
# ParametresStockRotation, exposé aux réglages de l'interface)
# ---------------------------------------------------------------------------

SEUIL_ALERTE_UNITES_DEFAUT = 10       # règle métier : sous ce seuil → cible = max
SEUIL_MAX_SANS_MIN_UNITES = 10        # stock max < ce seuil → pas de stock min
COUVERTURE_MIN_JOURS_DEFAUT = 14      # stock min = 14 jours de consommation
COUVERTURE_MAX_JOURS_DEFAUT = 30      # stock max = 30 jours de consommation
CONSOMMATION_DEFAUT_MENSUELLE = 0.0   # repli si aucun historique (0 = désactivé)
SEUIL_DORMANT_JOURS_DEFAUT = 180      # > 6 mois de couverture → stock dormant
ROTATION_MIN_COMMANDE_DEFAUT = 1.0    # rotation ≤ ce seuil → pas de réassort auto


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
    # Produits à rotation ≤ ce seuil (boîtes/mois) : écartés du réassort
    # automatique (classe C à rotation quasi nulle — commander 1 boîte de
    # chacun encombrerait la commande sans enjeu réel). 0 = ne rien écarter.
    rotation_min_commande_mensuelle: float = ROTATION_MIN_COMMANDE_DEFAUT


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

    - ``stock_actuel < seuil_alerte_unites`` **ET** ``stock_actuel <
      stock_min`` : urgence confirmée — cible = stock max directement,
      commande immédiate, pas de recomplètement partiel ;
    - ``stock_actuel < stock_min`` (sans être sous le seuil absolu, ou
      sous le seuil mais déjà au-dessus de son propre minimum) : réassort
      PROGRESSIF, cible = stock min seulement ;
    - ``stock_actuel >= stock_min`` : stock suffisant, aucune commande.

    Le seuil absolu ne suffit PLUS à lui seul à déclencher l'urgence : pour
    un produit à faible rotation, le stock min calculé (14 j de
    consommation) est souvent lui-même inférieur au seuil (10 unités par
    défaut). Sans la double condition, un produit dont le stock est déjà
    AU-DESSUS de son propre minimum (donc sans besoin réel de commande)
    déclenchait quand même une commande immédiate jusqu'au stock max —
    c'était le cas de 9 alertes rouges sur 10 en pratique, gonflant
    massivement les quantités proposées sans justification métier.
    """
    if stock_actuel < seuil_alerte_unites and stock_actuel < stock_min:
        cible = stock_max
        motif = (f"Stock < {seuil_alerte_unites:g} unités ET sous le stock "
                 "min — commande immédiate jusqu'au stock max")
    elif stock_actuel < stock_min:
        cible = stock_min
        motif = "Sous le stock min — réassort progressif jusqu'au stock min"
    else:
        cible = stock_actuel
        motif = "Stock suffisant — aucune commande"
    qte = max(0, math.ceil(cible - stock_actuel))
    return cible, qte, motif


def fusionner_doublons_cadencier(cadencier: pd.DataFrame, m: dict
                                 ) -> tuple[pd.DataFrame, int]:
    """Fusionne les lignes du cadencier qui décrivent le MÊME produit sous
    plusieurs codes CIP (changement de générique ou de fournisseur).

    Cas réel observé : l'ancien code reste dans le cadencier avec un stock 0
    et un historique de ventes qui s'arrête au mois du changement, pendant
    que le nouveau code porte le stock et les ventes récentes. Sans fusion,
    l'ancienne fiche déclenche une commande fantôme d'un produit déjà en
    rayon sous son nouveau code.

    Fusion par libellé normalisé strictement identique : stock et ventes
    mensuelles ADDITIONNÉS (les mois de transition se répartissent entre les
    deux codes, la série fusionnée redevient continue), code CIP de la ligne
    à l'activité la plus récente (à égalité : celle au stock le plus haut).
    Les libellés vides ne sont jamais fusionnés entre eux.

    Renvoie ``(cadencier_fusionne, nb_lignes_fusionnees)``.
    """
    libelles = cadencier[m["libelle"]].map(normaliser_libelle)
    en_double = libelles.duplicated(keep=False) & (libelles != "")
    if not en_double.any():
        return cadencier, 0
    colonnes_ventes = [c for c in m.get("ventes", []) if c in cadencier.columns]

    def _activite(ligne) -> tuple:
        """(index du dernier mois vendu, stock) — pour choisir la ligne
        « porteuse » du groupe, celle du code actuellement actif."""
        dernier = -1
        for i, c in enumerate(colonnes_ventes):
            if parser_nombre(ligne[c]) > 0:
                dernier = i
        return (dernier, parser_nombre(ligne[m["stock"]]))

    lignes, deja_fusionnes = [], set()
    for idx, ligne in cadencier.iterrows():
        if not en_double.loc[idx]:
            lignes.append(ligne)
            continue
        cle = libelles.loc[idx]
        if cle in deja_fusionnes:
            continue  # groupe déjà émis à sa première occurrence
        deja_fusionnes.add(cle)
        groupe = cadencier[libelles == cle]
        porteuse = max(groupe.index, key=lambda i: _activite(groupe.loc[i]))
        # astype(object) : la ligne d'un CSV est en dtype texte, les sommes
        # sont écrites en str pour rester relisibles par parser_nombre.
        fusion = groupe.loc[porteuse].copy().astype(object)
        fusion[m["stock"]] = f"{sum(parser_nombre(v) for v in groupe[m['stock']]):g}"
        for c in colonnes_ventes:
            fusion[c] = f"{sum(parser_nombre(v) for v in groupe[c]):g}"
        lignes.append(fusion)
    nb_fusionnees = len(cadencier) - len(lignes)
    return pd.DataFrame(lignes), nb_fusionnees


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
    "Commande en cours", "Consommation/mois", "Tendance", "Variabilité",
    "Stock min (calculé)", "Stock max (calculé)",
    "Stock min conseillé (variabilité)", "Cible réassort",
    "Qté à commander", "Motif",
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
    # Même produit sous deux codes CIP (changement de générique) : fusion,
    # sinon l'ancien code à stock 0 déclenche une commande fantôme.
    cadencier, doublons_fusionnes = fusionner_doublons_cadencier(cadencier, m)
    colonnes_ventes = [c for c in m["ventes"] if c in cadencier.columns]
    # Pas de réception le week-end : couverture min du JOUR ajustée.
    jours_weekend = jours_supplementaires_weekend(date_analyse)

    lignes = []
    for _, ligne in cadencier.iterrows():
        stock = parser_nombre(ligne[m["stock"]])
        en_cours = (parser_nombre(ligne[m["commande_en_cours"]])
                   if m.get("commande_en_cours") else 0.0)
        # Boîtes déjà commandées mais pas encore reçues : elles couvrent
        # aussi la consommation à venir. Sans cette déduction, l'outil
        # propose de commander comme si rien n'arrivait — double
        # commande systématique sur tout produit ayant un réassort en
        # cours, quel que soit son profil de rotation.
        stock_effectif = stock + en_cours
        brut_cip = ligne[m["cip"]] if m.get("cip") else ""
        cip = "" if pd.isna(brut_cip) else str(brut_cip).strip()
        brut_nom = ligne[m["libelle"]]
        nom = "" if pd.isna(brut_nom) else str(brut_nom).strip()
        ventes_brutes = [ligne[c] for c in colonnes_ventes]
        nb_corriges = 0
        ventes = ventes_brutes
        if params.corriger_ruptures_passees:
            ventes, nb_corriges = corriger_faux_zeros(ventes_brutes)

        rotation = calculer_rotation_mensuelle(ventes, params.periode_rotation)
        # Garde-fou des modes réactifs (mensuel, 3 mois, lissé) : si le calcul
        # récent tombe à 0 alors que le produit VEND sur l'année, c'est une
        # rupture/creux ponctuel — pas une fin de vie. On retombe sur la
        # moyenne annuelle pour ne pas faire DISPARAÎTRE du pilotage un
        # produit qui rote réellement (280 cas sur le cadencier réel).
        rotation_recente_nulle = False
        if rotation <= 0 and params.periode_rotation != "annuelle":
            rotation_annuelle = calculer_rotation_mensuelle(ventes, "annuelle")
            if rotation_annuelle > 0:
                rotation = rotation_annuelle
                rotation_recente_nulle = True

        sans_historique = all(parser_nombre(v) == 0 for v in ventes_brutes)
        if rotation <= 0 and sans_historique and params.consommation_defaut_mensuelle > 0:
            rotation = params.consommation_defaut_mensuelle

        if rotation <= 0 and stock <= 0:
            continue  # ni vente ni stock : rien à piloter

        conso_jour = rotation / JOURS_PAR_MOIS
        stock_min = calculer_stock_min(conso_jour, params.couverture_min_jours,
                                       jours_weekend)
        stock_max = calculer_stock_max(conso_jour, params.couverture_max_jours)
        # Bornes en BOÎTES ENTIÈRES : une borne de 4,2 boîtes se tient en
        # rayon avec 5 — arrondi à l'entier supérieur (round(…, 6) neutralise
        # les artefacts de virgule flottante avant le ceil). Le max ne passe
        # jamais sous le min (ajustement week-end compris).
        stock_min = math.ceil(round(stock_min, 6)) if stock_min > 0 else 0
        stock_max = math.ceil(round(stock_max, 6)) if stock_max > 0 else 0
        stock_max = max(stock_max, stock_min)
        # Règle officine : pour les lignes dont le stock max est < 10 boîtes,
        # on SUPPRIME le stock min (pas de point de commande automatique) —
        # ces petits produits ne sont pas pilotés par un minimum.
        min_supprime = False
        if 0 < stock_max < SEUIL_MAX_SANS_MIN_UNITES:
            stock_min = 0
            min_supprime = True

        # Produits à rotation quasi nulle (≤ seuil boîtes/mois) : écartés du
        # réassort automatique. Commander 1 boîte de centaines de références
        # vendues moins d'1 fois/mois encombre la commande sans enjeu réel.
        # Le produit reste visible (traçabilité) mais ne génère aucune Cmd.
        rotation_faible = (params.rotation_min_commande_mensuelle > 0
                           and 0 < rotation <= params.rotation_min_commande_mensuelle)

        # Colonne CONSEILLÉE (purement indicative, ne pilote pas la commande) :
        # stock min majoré d'une marge de sécurité pour les produits à ventes
        # IRRÉGULIÈRES. La marge ne s'ajoute qu'AU-DELÀ du seuil de stabilité
        # (SEUILS_VARIABILITE[0], soit CV 0,3) : un produit régulier garde
        # son min de base (cohérent avec le libellé « 🟢 stable »). Facteur
        # plafonné : CV 1,5 → +120 % au maximum. Le pharmacien peut s'y
        # référer pour sécuriser les produits à demande instable.
        cv = coefficient_variation(ventes)
        marge = max(0.0, min(cv, 1.5) - SEUILS_VARIABILITE[0]) if cv else 0.0
        if marge <= 0:
            stock_min_conseille = stock_min
        else:
            base = conso_jour * (params.couverture_min_jours + jours_weekend)
            stock_min_conseille = math.ceil(round(base * (1 + marge), 6))
            stock_min_conseille = max(stock_min_conseille, stock_min)
        # Cible et urgence évaluées sur le stock EFFECTIF (rayon + en cours) :
        # ce qui arrive déjà compte comme couverture.
        cible, qte, motif = determiner_cible_reassort(
            stock_effectif, stock_min, stock_max, params.seuil_alerte_unites)
        stock_jours = calculer_stock_jours(stock_effectif, rotation)

        # L'alerte suit la quantité RÉELLEMENT à commander : un produit à
        # rotation nulle avec peu de stock (ex. arrêté, non vendu) n'a pas
        # à être signalé « action requise » si rien n'est à commander.
        if rotation_faible:
            cible, qte = stock, 0
            alerte = "⚪ Rotation faible"
            motif = (f"Rotation ≤ {params.rotation_min_commande_mensuelle:g}/mois "
                     "— écarté du réassort automatique")
        elif qte <= 0:
            alerte = "🟢 OK"
        elif stock_effectif < params.seuil_alerte_unites:
            alerte = "🔴 Action requise"
        else:
            alerte = "🟡 Sous le min"
        if not rotation_faible and sans_historique and rotation > 0:
            motif += " (consommation par défaut — pas d'historique)"
        if not rotation_faible and rotation_recente_nulle:
            motif += (" · ventes récentes nulles (rupture/creux) — repli sur "
                      "la moyenne annuelle")
        if en_cours:
            motif += f" · {en_cours:g} déjà en commande (déduit du calcul)"
        if min_supprime and not rotation_faible:
            motif += (f" · stock min supprimé (stock max < "
                      f"{SEUIL_MAX_SANS_MIN_UNITES})")

        lignes.append({
            "Alerte": alerte,
            "Code CIP": cip,
            "Nom du produit": nom,
            "Stock actuel": int(round(stock)),
            "Commande en cours": int(round(en_cours)) if en_cours else "",
            "Consommation/mois": round(rotation, 1),
            "Tendance": calculer_tendance(ventes),
            "Variabilité": variabilite_demande(ventes),
            "Stock min (calculé)": int(stock_min),
            "Stock max (calculé)": int(stock_max),
            "Stock min conseillé (variabilité)": int(stock_min_conseille),
            "Cible réassort": int(round(cible)),
            "Qté à commander": qte,
            "Motif": motif,
            "_stock_jours": stock_jours,
            # Consommation NON arrondie : le classement ABC se fait dessus.
            # Classer sur la valeur affichée (arrondie au dixième) ferait
            # basculer de classe deux produits séparés par 0,04 boîte/mois,
            # au seul gré de l'arrondi.
            "_consommation_exacte": rotation,
        })

    df = pd.DataFrame(lignes)
    if df.empty:
        return ResultatStockRotation(
            df.reindex(columns=COLONNES_STOCK_ROTATION),
            df.reindex(columns=COLONNES_DORMANTS_ROTATION), {})

    df["Classe"] = classer_abc(list(df["_consommation_exacte"]))

    dormants = df[(df["Stock actuel"] > 0)
                  & (df["_stock_jours"] > params.seuil_dormant_jours)].copy()
    dormants["Stock (jours)"] = dormants["_stock_jours"].map(
        lambda v: "∞ (aucune vente)" if math.isinf(v) else round(v, 1))
    dormants["Commentaire"] = (
        f"Plus de {params.seuil_dormant_jours:.0f} j de couverture, bien "
        "au-delà du stock max — trésorerie immobilisée, envisager retour "
        "fournisseur ou arrêt de réassort.")
    dormants = (dormants.sort_values("Stock actuel", ascending=False)
                .reindex(columns=COLONNES_DORMANTS_ROTATION))

    # Priorité d'affichage : action requise, sous le min, OK, puis rotation
    # faible (écartée du réassort) en dernier.
    ordre_alerte = {"🔴 Action requise": 0, "🟡 Sous le min": 1, "🟢 OK": 2,
                    "⚪ Rotation faible": 3}
    df["_ordre"] = df["Alerte"].map(ordre_alerte)
    tableau = (df.sort_values(["_ordre", "Qté à commander"],
                              ascending=[True, False])
               .reindex(columns=COLONNES_STOCK_ROTATION))

    resume = {
        "total_produits": len(df),
        "action_requise": int((df["Alerte"] == "🔴 Action requise").sum()),
        "sous_le_min": int((df["Alerte"] == "🟡 Sous le min").sum()),
        "rotation_faible": int((df["Alerte"] == "⚪ Rotation faible").sum()),
        "nb_a": int((df["Classe"] == "A").sum()),
        "nb_b": int((df["Classe"] == "B").sum()),
        "nb_c": int((df["Classe"] == "C").sum()),
        "dormants": len(dormants),
        "dormants_boites": (float(dormants["Stock actuel"].sum())
                            if not dormants.empty else 0.0),
        "qte_totale_a_commander": int(df["Qté à commander"].sum()),
        "jours_weekend": jours_weekend,  # ajustement appliqué au stock min
        "doublons_fusionnes": doublons_fusionnes,  # anciens codes CIP absorbés
    }
    return ResultatStockRotation(tableau, dormants, resume)


# ---------------------------------------------------------------------------
# Comparaison à l'analyse précédente (cadencier n+1 : ne ressortir que les
# lignes dont le stock min/max a changé d'au moins 10 %)
# ---------------------------------------------------------------------------

SEUIL_VARIATION_AFFICHAGE = 0.10  # variation min/max ≥ 10 % → ligne ré-affichée
COLONNES_ETAT_STOCK = ["Code CIP", "Nom du produit", "Stock min (calculé)",
                       "Stock max (calculé)"]


def _cle_produit(cip, nom) -> str:
    """Clé d'appariement stable entre deux analyses : CIP + libellé
    normalisé. Combiner les deux évite les collisions quand plusieurs
    produits DIFFÉRENTS partagent le même CIP (cas réel dans le cadencier) —
    le CIP seul les confondrait et ferait ressortir des lignes à tort."""
    cip = "" if cip is None else str(cip).strip()
    return f"{cip}|{normaliser_libelle(nom)}"


def comparer_a_etat_precedent(tableau: pd.DataFrame,
                              etat_precedent: Optional[pd.DataFrame],
                              seuil_pct: float = SEUIL_VARIATION_AFFICHAGE):
    """Marque les lignes dont le stock min OU max a varié depuis la dernière
    analyse. Ajoute une colonne booléenne ``_modifie``.

    Une ligne est « modifiée » si elle est NOUVELLE (absente de l'analyse
    précédente) ou si son stock min ou son stock max a bougé d'au moins
    ``seuil_pct`` (10 % par défaut) en relatif. Permet de ne ré-afficher, au
    cadencier suivant, que les lignes réellement modifiées.

    ``etat_precedent`` vide ou None → tout est considéré modifié (première
    analyse). Renvoie ``(tableau_annoté, nb_modifiees, nb_nouvelles)``.
    """
    df = tableau.copy()
    if df.empty:
        df["_modifie"] = pd.Series(dtype=bool)
        return df, 0, 0
    if etat_precedent is None or etat_precedent.empty:
        df["_modifie"] = True
        return df, len(df), len(df)

    precedent = {}
    for _, r in etat_precedent.iterrows():
        precedent[_cle_produit(r.get("Code CIP", ""), r.get("Nom du produit", ""))] = (
            parser_nombre(r.get("Stock min (calculé)")),
            parser_nombre(r.get("Stock max (calculé)")))

    modifies, nb_nouvelles = [], 0
    for _, r in df.iterrows():
        cle = _cle_produit(r["Code CIP"], r["Nom du produit"])
        if cle not in precedent:
            modifies.append(True)
            nb_nouvelles += 1
            continue
        old_min, old_max = precedent[cle]
        var_min = abs(r["Stock min (calculé)"] - old_min) / max(abs(old_min), 1)
        var_max = abs(r["Stock max (calculé)"] - old_max) / max(abs(old_max), 1)
        modifies.append(var_min >= seuil_pct or var_max >= seuil_pct)

    df["_modifie"] = modifies
    return df, int(sum(modifies)), nb_nouvelles


def etat_stock_a_enregistrer(tableau: pd.DataFrame) -> pd.DataFrame:
    """Extrait de quoi mémoriser l'analyse courante (référence pour la
    prochaine comparaison) : code, nom, stock min et max."""
    if tableau.empty:
        return pd.DataFrame(columns=COLONNES_ETAT_STOCK)
    return tableau.reindex(columns=COLONNES_ETAT_STOCK).copy()


# ---------------------------------------------------------------------------
# Export Excel dédié
# ---------------------------------------------------------------------------

_COULEURS_ALERTE = {"🔴 Action requise": "F8CBAD", "🟡 Sous le min": "FFE699",
                    "🟢 OK": "C6EFCE", "⚪ Rotation faible": "E7E6E1"}


def exporter_stock_rotation_excel(resultat: ResultatStockRotation) -> bytes:
    """Classeur de gestion du stock en rotation : min/max + dormants.

    Le fichier étant le bon de commande, les produits « ⚪ Rotation faible »
    (écartés du réassort automatique) n'y figurent pas — ils restent
    consultables dans l'application."""
    tableau = resultat.tableau
    if not tableau.empty and "Alerte" in tableau.columns:
        tableau = tableau[tableau["Alerte"] != "⚪ Rotation faible"]
    # Retire les colonnes techniques internes (préfixe _) du document.
    tableau = tableau[[c for c in tableau.columns if not str(c).startswith("_")]]
    return exporter_classeur(
        [("Stock min-max", tableau),
         ("Stock dormant", resultat.dormants)],
        couleurs_par_colonne={"Alerte": _COULEURS_ALERTE})
