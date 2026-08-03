# -*- coding: utf-8 -*-
"""Module 2 — Gestion des ruptures de stock (pharmacie).

Module Python PUR, sans interface : toute la logique de calcul vit ici et est
testable indépendamment (voir tests/test_moteur.py). L'interface Streamlit
(app.py) ne fait qu'appeler ce module.

Logique métier (STRICTE, sans buffer — corrigée avec l'utilisateur) :
  1. Périmètre : produits en rupture GPNC ET vendus (rotation > 0 au cadencier).
  2. stock_jours = stock_actuel / (rotation_mensuelle / 30) ; stock 0 → 0 jour.
  3. Apparition :
       - avec date de réappro : stock_jours < jours_avant_reappro (STRICT) ;
       - sans date : stock_jours < 30 (objectif 30 jours de couverture).
     Ex. Titanoréine : réappro 16 j, stock 18 j → 18 ≥ 16 → n'apparaît PAS.
  4. Dépannage : absent des ruptures UNIPHARMA → Onglet 1 (commander) ;
     présent → Onglet 2 (aucune solution).
  5. Cmd = arrondi_sup(rotation_journaliere × couverture_cible − stock), min 1,
     arrondi au conditionnement si l'info existe.
  6. Urgence : URGENT (stock 0 ou ≤ 3 j) · MODÉRÉ (≤ 15 j) · À ANTICIPER (> 15 j).

ISOLATION : ce module croise le cadencier avec DEUX listes fournisseurs
(GPNC, UNIPHARMA) — c'est sa seule raison d'être. La politique de stock
min/max (Module 1) vit entièrement dans stock_rotation.py, que ce module
n'importe jamais. Les calculs de consommation partagés (rotation, tendance,
variabilité, classement ABC, correction des ruptures passées) viennent de
commun.py : mutualisation des calculs, aucun couplage fonctionnel entre les
deux modules métier.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from commun import (JOURS_PAR_MOIS, calculer_rotation_mensuelle,
                    calculer_stock_jours, calculer_tendance, classer_abc,
                    corriger_faux_zeros, normaliser_cip, normaliser_libelle,
                    parser_date, parser_nombre, variantes_cip)
# Ré-exportés pour compatibilité : app.py et les tests historiques importent
# ces fonctions génériques directement depuis moteur_ruptures.
from commun import (charger_fichier, detecter_colonne,  # noqa: F401
                    detecter_colonnes_ventes, exporter_classeur)

try:  # rapidfuzz est optionnel : sans lui, seul le matching exact/CIP marche.
    from rapidfuzz import fuzz

    _RAPIDFUZZ = True
except ImportError:  # pragma: no cover - environnement sans rapidfuzz
    _RAPIDFUZZ = False

# ---------------------------------------------------------------------------
# Constantes métier — spécifiques aux ruptures fournisseurs
# ---------------------------------------------------------------------------

COUVERTURE_SANS_DATE_JOURS = 30   # objectif de couverture quand pas de réappro
#: DLUO à moins de ~3 mois → alerte informative avant de commander plus.
#: Même seuil que le palier « < 3 mois » du Module 3 (stock fermé), pour que
#: « péremption proche » désigne la même chose d'un module à l'autre. Les
#: deux modules restent indépendants : c'est une cohérence de vocabulaire,
#: pas un couplage de code.
SEUIL_ALERTE_PEREMPTION_JOURS = 90
SEUIL_VIGILANCE_JOURS = 7         # couverture < 7 j hors rupture → vigilance
ROTATION_MIN_VIGILANCE = 5        # < 5 ventes/mois → pas de vigilance (bruit)
SEUIL_MARGE_JUSTESSE_JOURS = 3    # écarté avec < 3 j de marge → à surveiller

URGENT = "🔴 URGENT"
MODERE = "🟡 MODÉRÉ"
ANTICIPER = "🟢 À ANTICIPER"
_ORDRE_URGENCE = {URGENT: 0, MODERE: 1, ANTICIPER: 2}

SEUIL_MATCH = 80      # score fuzzy minimal pour accepter une correspondance
SEUIL_CERTAIN = 92    # en dessous → correspondance « incertaine », à vérifier

COUVERTURE_ABC = {"A": 21, "B": 30, "C": 14}  # cible sans date, si politique ABC
POIDS_CLASSE = {"A": 1.0, "B": 0.5, "C": 0.2}  # poids volume du score priorité


# ---------------------------------------------------------------------------
# Matching produit (CIP prioritaire, sinon libellé normalisé + fuzzy)
# — spécifique aux ruptures : rapproche le cadencier de 2 listes fournisseurs.
# ---------------------------------------------------------------------------

@dataclass
class Correspondance:
    """Résultat du rapprochement d'un produit avec une autre liste."""
    index: Optional[int]          # index de la ligne appariée (None = aucun)
    methode: str                  # "cip" | "exact" | "fuzzy" | "aucune"
    score: float = 100.0          # score fuzzy (100 pour cip/exact)
    incertain: bool = False       # True si score < SEUIL_CERTAIN → à vérifier


def apparier(libelle: str, cip: str, index_cip: dict, index_libelle: dict,
             libelles_norm: list) -> Correspondance:
    """Rapproche un produit d'une liste indexée (CIP > exact > fuzzy)."""
    for forme in variantes_cip(cip):  # CIP13 et CIP7 équivalents
        if forme in index_cip:
            return Correspondance(index_cip[forme], "cip")
    norme = normaliser_libelle(libelle)
    if not norme:
        return Correspondance(None, "aucune", 0.0)
    if norme in index_libelle:
        return Correspondance(index_libelle[norme], "exact")
    if _RAPIDFUZZ and libelles_norm:
        meilleur, meilleur_score = None, 0.0
        for autre_norme, idx in libelles_norm:
            s = fuzz.token_sort_ratio(norme, autre_norme)
            if s > meilleur_score:
                meilleur, meilleur_score = idx, s
        if meilleur is not None and meilleur_score >= SEUIL_MATCH:
            return Correspondance(meilleur, "fuzzy", meilleur_score,
                                  incertain=meilleur_score < SEUIL_CERTAIN)
    return Correspondance(None, "aucune", 0.0)


def _indexer(df: pd.DataFrame, col_libelle: str, col_cip: Optional[str]):
    """Construit les index (CIP → ligne, libellé normalisé → ligne)."""
    index_cip, index_libelle, libelles_norm = {}, {}, []
    for idx, row in df.iterrows():
        if col_cip and col_cip in df.columns:
            for forme in variantes_cip(normaliser_cip(row[col_cip])):
                if forme not in index_cip:  # CIP13 ET CIP7 indexés
                    index_cip[forme] = idx
        norme = normaliser_libelle(row[col_libelle])
        if norme:
            if norme not in index_libelle:
                index_libelle[norme] = idx
            libelles_norm.append((norme, idx))
    return index_cip, index_libelle, libelles_norm


# ---------------------------------------------------------------------------
# Calculs élémentaires (étapes 2, 3, 5, 6) — spécifiques aux ruptures
# ---------------------------------------------------------------------------

def probabilite_rupture(stock_effectif: float, rotation_mensuelle: float,
                        ventes: list, horizon_jours: float = 7) -> float:
    """Probabilité d'être en rupture d'ici ``horizon_jours``.

    La demande sur l'horizon est modélisée en Normale(μ_h, σ_h) à partir de
    la moyenne et de l'écart-type MENSUELS observés (σ_h = σ_mois ×
    √(horizon/30)). Sans variabilité mesurable (moins de 3 mois, σ = 0),
    repli déterministe : 1 si la demande moyenne épuise le stock, sinon 0.
    """
    if rotation_mensuelle <= 0:
        return 0.0
    demande_horizon = rotation_mensuelle / JOURS_PAR_MOIS * horizon_jours
    valeurs = [parser_nombre(v) for v in ventes]
    sigma_mois = 0.0
    if len(valeurs) >= 3:
        moyenne = sum(valeurs) / len(valeurs)
        sigma_mois = (sum((v - moyenne) ** 2 for v in valeurs)
                      / len(valeurs)) ** 0.5
    sigma_horizon = sigma_mois * math.sqrt(horizon_jours / JOURS_PAR_MOIS)
    if sigma_horizon <= 0:
        return 1.0 if demande_horizon >= stock_effectif else 0.0
    z = (stock_effectif - demande_horizon) / sigma_horizon
    return 0.5 * (1 - math.erf(z / math.sqrt(2)))


def score_priorite(risque_rupture: float, classe: str, reports: int = 0,
                   sans_date: bool = False) -> int:
    """Score de priorité de commande 0-100, pour trier la liste du matin.

    - 50 pts : risque de rupture imminent (probabilité à 7 jours, 0-1) ;
    - 30 pts : poids du produit dans les ventes (classe A/B/C) ;
    - 20 pts : fiabilité de la réappro (déjà repoussée → 1 ; pas de date
      annoncée → 0,5 ; date jamais démentie → 0).
    """
    risque = min(1.0, max(0.0, risque_rupture))
    fiabilite = 1.0 if reports else (0.5 if sans_date else 0.0)
    return int(round(50 * risque + 30 * POIDS_CLASSE.get(classe, 0.2)
                     + 20 * fiabilite))


def doit_apparaitre(stock_jours: float,
                    jours_avant_reappro: Optional[float]) -> bool:
    """Étape 3 — règle d'apparition STRICTE, sans buffer.

    - Avec date de réappro : apparaît ssi stock_jours < jours_avant_reappro.
    - Sans date : apparaît ssi stock_jours < 30.
    """
    if jours_avant_reappro is not None:
        return stock_jours < jours_avant_reappro
    return stock_jours < COUVERTURE_SANS_DATE_JOURS


def classer_urgence(stock_actuel: float, stock_jours: float) -> str:
    """Étape 6 — URGENT (stock 0 ou ≤ 3 j) · MODÉRÉ (≤ 15 j) · À ANTICIPER."""
    if stock_actuel <= 0 or stock_jours <= 3:
        return URGENT
    if stock_jours <= 15:
        return MODERE
    return ANTICIPER


def quantite_a_commander(rotation_mensuelle: float,
                         couverture_cible_jours: float,
                         stock_actuel: float,
                         conditionnement: Optional[float] = None) -> int:
    """Étape 5 — Cmd = arrondi_sup(rot_j × couverture − stock), minimum 1.

    Arrondi au multiple du conditionnement si fourni (> 1).
    """
    rotation_journaliere = rotation_mensuelle / JOURS_PAR_MOIS
    qte_cible = rotation_journaliere * couverture_cible_jours
    cmd = max(1, math.ceil(qte_cible - stock_actuel))
    if conditionnement and conditionnement > 1:
        cmd = int(math.ceil(cmd / conditionnement) * conditionnement)
    return cmd


def compter_reports_reappro(produit: str, historique,
                            date_reappro_jour: Optional[date] = None) -> int:
    """Nombre de fois où la date de réappro annoncée pour ``produit`` a été
    REPOUSSÉE d'une analyse à l'autre (fournisseur peu fiable sur ce produit).

    ``date_reappro_jour`` : date annoncée AUJOURD'HUI, comparée en dernier —
    un glissement entre hier et aujourd'hui compte donc dès aujourd'hui.
    L'historique doit contenir les colonnes 'Date analyse', 'Produit' et
    'Date réappro' (les anciens historiques sans cette colonne renvoient 0).
    """
    annonces: list = []
    if (historique is not None and not historique.empty
            and "Date réappro" in historique.columns):
        sous = historique[historique["Produit"] == produit].copy()
        if not sous.empty:
            sous["_date"] = pd.to_datetime(sous["Date analyse"], errors="coerce")
            sous = sous.sort_values("_date")
            annonces = [parser_date(v) for v in sous["Date réappro"]]
    return _compter_reports(annonces, date_reappro_jour)


def _compter_reports(annonces: list, date_reappro_jour: Optional[date]) -> int:
    """Compte les glissements dans une suite chronologique de dates annoncées
    (None = pas de date ce jour-là, ignoré), la date du jour en dernier."""
    reports, derniere = 0, None
    for d in list(annonces) + [date_reappro_jour]:
        if d is None:
            continue
        if derniere is not None and d > derniere:
            reports += 1
        derniere = d
    return reports


def rotation_possiblement_sous_estimee(ventes: list) -> bool:
    """Indice de rupture passée : au moins un mois à 0 vente alors que
    d'autres mois montrent des ventes — la rotation calculée est alors
    probablement sous-estimée (le produit était en rupture, pas sans
    demande). Toutes les valeurs à 0 = pas de demande réelle → non signalé.
    """
    valeurs = [parser_nombre(v) for v in ventes]
    if not valeurs or all(v <= 0 for v in valeurs):
        return False
    return any(v <= 0 for v in valeurs)


def _lignes_signalees(historique: pd.DataFrame) -> pd.DataFrame:
    """Restreint l'historique aux produits réellement SIGNALÉS (onglets 1-2).

    Les lignes de type « surveillance » (écartés de justesse) n'existent que
    pour suivre les dates de réappro annoncées : elles ne comptent ni dans
    « déjà signalé N fois » ni dans le comparatif quotidien.
    """
    if historique is None or historique.empty or "Type" not in historique.columns:
        return historique
    return historique[historique["Type"].fillna("commande") != "surveillance"]


def compter_occurrences_historique(produit: str, historique: pd.DataFrame,
                                   avant_date: date) -> int:
    """Nombre d'analyses antérieures à ``avant_date`` où ``produit`` était
    déjà signalé dans l'historique (colonnes 'Date analyse' / 'Produit',
    persisté par l'interface — voir app.py). Module pur : aucune I/O ici.
    """
    historique = _lignes_signalees(historique)
    if historique is None or historique.empty:
        return 0
    sous = historique[historique["Produit"] == produit]
    dates = pd.to_datetime(sous["Date analyse"], errors="coerce").dt.date
    return int((dates < avant_date).sum())


def comparer_a_analyse_precedente(produits_jour, historique: pd.DataFrame,
                                  date_analyse: date):
    """Suivi quotidien : compare les produits signalés aujourd'hui à la
    DERNIÈRE analyse antérieure à ``date_analyse``.

    Renvoie ``(date_precedente, nouveaux, resolus)`` :
      - date_precedente : date de l'analyse de référence (None si aucune —
        première analyse, tout est « nouveau ») ;
      - nouveaux : produits du jour absents de l'analyse précédente ;
      - resolus  : produits de l'analyse précédente absents aujourd'hui.
    """
    produits_jour = list(produits_jour)
    historique = _lignes_signalees(historique)
    if historique is None or historique.empty:
        return None, produits_jour, []
    dates = pd.to_datetime(historique["Date analyse"], errors="coerce").dt.date
    anterieures = {d for d in dates if pd.notna(d) and d < date_analyse}
    if not anterieures:
        return None, produits_jour, []
    precedente = max(anterieures)
    produits_precedents = set(historique.loc[dates == precedente, "Produit"])
    nouveaux = [p for p in produits_jour if p not in produits_precedents]
    resolus = sorted(produits_precedents - set(produits_jour))
    return precedente, nouveaux, resolus


def taux_de_service(produits_a: list, historique: pd.DataFrame,
                    date_analyse: date, fenetre_jours: int = 30):
    """Taux de service des produits A : part des couples produit×jour SANS
    rupture signalée sur la fenêtre glissante. Renvoie (taux, jours_analyses)
    — (None, 0) si l'historique ne couvre pas encore la fenêtre.

    Métrique de RUPTURES (dépend de l'historique des signalements de ce
    module), pas de gestion de stock — ``produits_a`` peut être calculée
    avec ``commun.classer_abc`` sans dépendre de stock_rotation.py.
    """
    historique = _lignes_signalees(historique)
    if historique is None or historique.empty or not produits_a:
        return None, 0
    h = historique.copy()
    h["_date"] = pd.to_datetime(h["Date analyse"], errors="coerce").dt.date
    debut = date_analyse - timedelta(days=fenetre_jours)
    h = h[(h["_date"] >= debut) & (h["_date"] < date_analyse)]
    jours = sorted({d for d in h["_date"] if pd.notna(d)})
    if not jours:
        return None, 0
    ensemble_a = set(produits_a)
    ruptures = h[h["Produit"].isin(ensemble_a)]
    produit_jours = len(ruptures[["_date", "Produit"]].drop_duplicates())
    total = len(jours) * len(ensemble_a)
    return 1 - produit_jours / total, len(jours)


# ---------------------------------------------------------------------------
# Analyse complète
# ---------------------------------------------------------------------------

@dataclass
class ResultatAnalyse:
    """Sortie de l'analyse : les onglets de décision + résumé + alertes."""
    onglet1: pd.DataFrame           # à commander chez UNIPHARMA
    onglet2: pd.DataFrame           # rupture chez les deux → pas de solution
    onglet3: pd.DataFrame           # traçabilité complète
    resume: dict = field(default_factory=dict)
    alertes: list = field(default_factory=list)          # messages pour l'UI
    matchs_incertains: list = field(default_factory=list)  # à vérifier à la main
    vigilance: pd.DataFrame = field(default_factory=pd.DataFrame)
    # ^ anticipation : produits hors rupture GPNC dont le stock s'épuise
    ecartes_justesse: pd.DataFrame = field(default_factory=pd.DataFrame)
    # ^ écartés par la règle stricte mais avec très peu de marge


COLONNES_ONGLET1 = ["Priorité", "Urgence", "Classe", "Produit", "Stock actuel",
                    "Commande en cours", "Rotation/mois", "Tendance",
                    "Fiabilité rotation", "Stock (jours)", "P(rupture 7 j)",
                    "Date réappro GPNC", "Jours avant réappro",
                    "Péremption", "Qté à commander (Cmd)", "Commentaire"]
COLONNES_VIGILANCE = ["Priorité", "Classe", "Produit", "Stock actuel",
                      "Commande en cours", "Rotation/mois", "Tendance",
                      "Stock (jours)", "P(rupture 7 j)", "Conseil"]
COLONNES_JUSTESSE = ["Produit", "Stock actuel", "Rotation/mois",
                     "Stock (jours)", "Date réappro GPNC",
                     "Jours avant réappro", "Marge (jours)", "Commentaire"]
COLONNES_ONGLET2 = ["Produit", "Stock actuel", "Rotation/mois", "Stock (jours)",
                    "Date réappro GPNC", "Péremption", "Commentaire"]
COLONNES_ONGLET3 = ["Produit", "Vendu (O/N)", "Stock actuel", "Commande en cours",
                    "Rotation/mois", "Fiabilité rotation", "Stock (jours)",
                    "Date réappro", "Jours avant réappro", "Péremption",
                    "Dispo UNIPHARMA (O/N)", "Décision", "Onglet", "Motif"]


def _precalculer_cadencier(cadencier: pd.DataFrame, m_cad: dict,
                           rotation, corriger_ruptures_passees: bool
                           ) -> tuple:
    """UNE passe sur le cadencier pour tout le monde.

    La boucle GPNC, l'onglet Vigilance et le classement ABC ont besoin des
    mêmes valeurs : stock, commande en cours, ventes corrigées des faux
    zéros, rotation. Les recalculer à chaque usage coûterait trois passes
    sur 3 500 lignes et risquerait de les faire diverger.

    Renvoie ``(infos_par_index, classe_par_index)``.
    """
    colonnes_ventes = [c for c in m_cad["ventes"] if c in cadencier.columns]
    infos: dict = {}
    for idx, ligne in cadencier.iterrows():
        stock = parser_nombre(ligne[m_cad["stock"]])
        en_cours = (parser_nombre(ligne[m_cad["commande_en_cours"]])
                    if m_cad.get("commande_en_cours") else 0.0)
        ventes = [ligne[c] for c in colonnes_ventes]
        nb_corriges = 0
        if corriger_ruptures_passees:
            ventes, nb_corriges = corriger_faux_zeros(ventes)
        infos[idx] = (stock, en_cours, ventes, rotation(ventes), nb_corriges)
    indices = list(infos)
    classes = classer_abc([infos[i][3] for i in indices])
    return infos, dict(zip(indices, classes))


def _annonces_reappro(historique: Optional[pd.DataFrame],
                      date_analyse: date) -> dict:
    """Dates de réappro annoncées par le passé, groupées par produit.

    Pré-groupées en une passe plutôt qu'un filtre du DataFrame par produit
    signalé. Seules les analyses STRICTEMENT antérieures comptent : une
    ré-analyse antidatée ne doit pas se comparer à des annonces « du futur ».
    """
    if (historique is None or historique.empty
            or "Date réappro" not in historique.columns):
        return {}
    h = historique.copy()
    h["_date"] = pd.to_datetime(h["Date analyse"], errors="coerce")
    h = h[h["_date"].dt.date < date_analyse]
    return {produit: [parser_date(v) for v in groupe["Date réappro"]]
            for produit, groupe in h.sort_values("_date").groupby("Produit",
                                                                  sort=False)}


def _date_reappro_annoncee(ligne_gpnc, m_gpnc: dict, date_analyse: date,
                           produit: str, alertes: list) -> tuple:
    """Date de réappro GPNC et jours restants.

    Une date DÉPASSÉE est traitée comme une absence de date : le fournisseur
    ne l'a pas tenue, s'appuyer dessus reviendrait à considérer le produit
    comme couvert alors qu'il ne l'est pas.
    """
    if not m_gpnc.get("date_reappro"):
        return None, None
    date_reappro = parser_date(ligne_gpnc[m_gpnc["date_reappro"]])
    if date_reappro is None:
        return None, None
    jours_avant = (date_reappro - date_analyse).days
    if jours_avant < 0:
        alertes.append(f"{produit} : date de réappro dépassée "
                       f"({date_reappro:%d/%m/%Y}) — traité comme sans date.")
        return None, None
    return date_reappro, jours_avant


def _fiabilite_rotation(nb_corriges: int, ventes: list) -> str:
    """Ce qu'on peut croire de la rotation calculée."""
    if nb_corriges:  # faux zéros interpolés → rotation redressée
        return f"🔧 corrigée ({nb_corriges} mois de rupture)"
    if rotation_possiblement_sous_estimee(ventes):  # zéros en bord de période
        return "⚠️ rupture passée possible"
    return "OK"


def _peremption_produit(ligne_cad, m_cad: dict, date_analyse: date,
                        produit: str, alertes: list) -> str:
    """Affichage de la DLUO, et alerte si elle approche.

    Informatif : une péremption proche n'écarte PAS le produit de la
    commande, elle invite à vérifier le stock avant d'en commander plus.
    """
    if not m_cad.get("peremption"):
        return ""
    date_peremption = parser_date(ligne_cad[m_cad["peremption"]])
    if date_peremption is None:
        return ""
    affichage = f"{date_peremption:%d/%m/%Y}"
    jours = (date_peremption - date_analyse).days
    if 0 <= jours <= SEUIL_ALERTE_PEREMPTION_JOURS:
        alertes.append(
            f"{produit} : péremption proche — moins de "
            f"{SEUIL_ALERTE_PEREMPTION_JOURS} j ({affichage}, dans "
            f"{jours} j). Vérifier le stock avant de commander davantage.")
    return affichage


def _quantite_et_commentaire(rotation: float, stock_effectif: float,
                             en_cours: float, jours_avant: Optional[int],
                             classe: str, politique_abc: bool,
                             delai_livraison_jours: float, ligne_cad,
                             m_cad: dict, avert_reports: str) -> tuple:
    """Quantité à commander chez UNIPHARMA, et son explication.

    Le délai de livraison s'ajoute à la couverture cible : les boîtes
    commandées aujourd'hui n'arrivent pas aujourd'hui. Sans date de réappro,
    la cible est de 30 j pour tous — ou différenciée par classe si la
    politique ABC est activée. La règle d'APPARITION, elle, ne bouge pas :
    seule la quantité change.
    """
    cible_sans_date = (COUVERTURE_ABC.get(classe, COUVERTURE_SANS_DATE_JOURS)
                       if politique_abc else COUVERTURE_SANS_DATE_JOURS)
    couverture_cible = (jours_avant if jours_avant is not None
                        else cible_sans_date) + delai_livraison_jours
    conditionnement = None
    if m_cad.get("conditionnement"):
        c = parser_nombre(ligne_cad[m_cad["conditionnement"]])
        conditionnement = c if c > 1 else None
    cmd = quantite_a_commander(rotation, couverture_cible, stock_effectif,
                               conditionnement)

    commentaire = ("Dépannage jusqu'à la réappro GPNC"
                   if jours_avant is not None else
                   f"Pas de date de réappro → objectif "
                   f"{cible_sans_date:.0f} j de couverture")
    if en_cours:
        commentaire += f" · {en_cours:g} déjà en commande (déduit du calcul)"
    return cmd, commentaire + avert_reports


def _decider_rotation_nulle(produit: str, historique, date_analyse: date,
                            alertes: list) -> tuple:
    """Que faire d'un produit sans aucune vente sur la période ?

    Rupture LONGUE : les ventes sont écrasées à 0 parce que le produit a
    manqué, pas parce qu'il ne se vend pas. S'il était déjà signalé les
    jours précédents, l'écarter en silence reviendrait à le laisser
    disparaître de la liste au moment où il manque le plus.
    """
    deja_signale = compter_occurrences_historique(produit, historique,
                                                  date_analyse)
    if deja_signale <= 0:
        return "Écarté", "Rotation nulle (produit non vendu)"
    alertes.append(
        f"{produit} : ventes à 0 sur toute la période mais déjà signalé "
        f"{deja_signale} fois — rupture longue probable, rotation "
        "incalculable ; vérifier manuellement (dépannage UNIPHARMA possible).")
    return "À vérifier", (f"Rotation nulle mais déjà signalé {deja_signale} "
                          "fois (rupture longue probable)")


def _motif_ecarte(stock_jours: float, jours_avant: Optional[int]) -> str:
    """Pourquoi la règle stricte écarte ce produit."""
    if jours_avant is not None:
        return (f"Stock ({stock_jours:.0f} j) couvre jusqu'à la réappro "
                f"({jours_avant} j)")
    return (f"Stock ({stock_jours:.0f} j) ≥ {COUVERTURE_SANS_DATE_JOURS:.0f} j "
            "de couverture")


def _examiner_justesse(produit: str, stock: float, rotation: float,
                       stock_jours: float, jours_avant: Optional[int],
                       date_reappro_affichee: str, reports: int,
                       avert_reports: str, seuil_marge_jours: float,
                       alertes: list) -> tuple:
    """Écarté de JUSTESSE ? La règle stricte tient, mais de si peu qu'un
    glissement de réappro suffirait à créer la rupture sèche.

    Renvoie ``(ligne, complément_de_motif)``, ou ``(None, "")`` si la marge
    est confortable.
    """
    marge = stock_jours - (jours_avant if jours_avant is not None
                           else COUVERTURE_SANS_DATE_JOURS)
    if marge >= seuil_marge_jours:
        return None, ""

    commentaire = (
        "Écarté par la règle stricte mais marge faible — si la réappro "
        "glisse, rupture sèche. Surveiller / dépanner au besoin."
        if jours_avant is not None else
        f"Sans date de réappro, à peine au-dessus des "
        f"{COUVERTURE_SANS_DATE_JOURS:.0f} j de couverture — surveiller la "
        "rotation.") + avert_reports
    if reports:
        alertes.append(f"{produit} : écarté de justesse ALORS QUE la réappro "
                       f"a déjà été repoussée {reports} fois — risque fort de "
                       "rupture sèche.")
    ligne = {
        "Produit": produit, "Stock actuel": stock,
        "Rotation/mois": round(rotation, 1),
        "Stock (jours)": round(stock_jours, 1),
        "Date réappro GPNC": date_reappro_affichee,
        "Jours avant réappro": (jours_avant if jours_avant is not None else ""),
        "Marge (jours)": round(marge, 1),
        "Commentaire": commentaire,
    }
    return ligne, f" — de justesse ({marge:.1f} j de marge)"


def _calculer_vigilance(indices: list, deja_traites: set, infos: dict,
                        classe_par_index: dict, cadencier: pd.DataFrame,
                        m_cad: dict, rotation_min: float,
                        seuil_jours: float) -> list:
    """Produits du cadencier HORS ruptures GPNC dont le stock s'épuise.

    La rupture en rayon arrive : autant commander chez GPNC (circuit normal)
    avant qu'elle se produise. Les rotations trop faibles sont écartées —
    c'est du bruit, il n'y a rien à anticiper.
    """
    lignes = []
    for idx in indices:
        if idx in deja_traites:
            continue  # déjà couvert par l'analyse des ruptures GPNC
        stock, en_cours, ventes, rotation, _ = infos[idx]
        if rotation < rotation_min or rotation <= 0:
            continue
        stock_jours = calculer_stock_jours(stock + en_cours, rotation)
        if stock_jours >= seuil_jours:
            continue
        classe = classe_par_index.get(idx, "C")
        proba7 = probabilite_rupture(stock + en_cours, rotation, ventes, 7)
        lignes.append({
            "Priorité": score_priorite(proba7, classe),
            "Classe": classe,
            "Produit": str(cadencier.loc[idx, m_cad["libelle"]]).strip(),
            "Stock actuel": stock,
            "Commande en cours": (en_cours if m_cad.get("commande_en_cours")
                                  else ""),
            "Rotation/mois": round(rotation, 1),
            "Tendance": calculer_tendance(ventes),
            "Stock (jours)": round(stock_jours, 1),
            "P(rupture 7 j)": f"{proba7:.0%}",
            "Conseil": ("Hors ruptures GPNC identifiées — commander avant "
                        "la rupture en rayon."),
            "_stock_jours": stock_jours,
        })
    return lignes


def _assembler_resultat(lignes1: list, lignes2: list, lignes3: list,
                        lignes_vigilance: list, lignes_justesse: list,
                        nb_ruptures_gpnc: int, alertes: list,
                        matchs_incertains: list) -> ResultatAnalyse:
    """Tris, mise en forme des onglets et compteurs du bandeau."""
    # Onglet 1 : le score de priorité trie la liste du matin — un produit A
    # à fort risque passe devant un produit C déjà à sec.
    df1 = pd.DataFrame(lignes1)
    if not df1.empty:
        df1 = (df1.sort_values(["Priorité", "_stock_jours"],
                               ascending=[False, True])
                  .drop(columns=["_stock_jours"]))
    df1 = df1.reindex(columns=COLONNES_ONGLET1)

    df2 = pd.DataFrame(lignes2)
    if not df2.empty:  # criticité : stock 0 d'abord, puis fort volume
        df2["_stock0"] = (df2["_stock"] <= 0).astype(int)
        df2 = (df2.sort_values(["_stock0", "_rotation"],
                               ascending=[False, False])
                  .drop(columns=["_stock0", "_rotation", "_stock"]))
    df2 = df2.reindex(columns=COLONNES_ONGLET2)

    df3 = pd.DataFrame(lignes3).reindex(columns=COLONNES_ONGLET3)

    df_vigilance = pd.DataFrame(lignes_vigilance)
    if not df_vigilance.empty:  # priorité (risque × volume) puis couverture
        df_vigilance = (df_vigilance
                        .sort_values(["Priorité", "_stock_jours"],
                                     ascending=[False, True])
                        .drop(columns=["_stock_jours"]))
    df_vigilance = df_vigilance.reindex(columns=COLONNES_VIGILANCE)

    df_justesse = pd.DataFrame(lignes_justesse)
    if not df_justesse.empty:  # la marge la plus faible en premier
        df_justesse = df_justesse.sort_values("Marge (jours)")
    df_justesse = df_justesse.reindex(columns=COLONNES_JUSTESSE)

    def _compter(colonne: str, valeur) -> int:
        return int((df1[colonne] == valeur).sum()) if not df1.empty else 0

    resume = {
        "ruptures_gpnc": nb_ruptures_gpnc,
        "analyses": len(df3),
        "vendus": int((df3["Vendu (O/N)"] == "O").sum()) if not df3.empty else 0,
        "a_commander": len(df1),
        "sans_solution": len(df2),
        "urgents": _compter("Urgence", URGENT),
        "moderes": _compter("Urgence", MODERE),
        "anticiper": _compter("Urgence", ANTICIPER),
        "rotation_douteuse": _compter("Fiabilité rotation",
                                      "⚠️ rupture passée possible"),
        "peremption_proche": len([a for a in alertes
                                  if "péremption proche" in a]),
        "vigilance": len(df_vigilance),
        "justesse": len(df_justesse),
    }
    return ResultatAnalyse(df1, df2, df3, resume, alertes, matchs_incertains,
                           vigilance=df_vigilance,
                           ecartes_justesse=df_justesse)


def analyser(cadencier: pd.DataFrame,
             ruptures_gpnc: pd.DataFrame,
             ruptures_unipharma: pd.DataFrame,
             mapping: dict,
             date_analyse: date,
             periode: str = "annuelle",
             historique: Optional[pd.DataFrame] = None,
             seuil_vigilance_jours: float = SEUIL_VIGILANCE_JOURS,
             rotation_min_vigilance: float = ROTATION_MIN_VIGILANCE,
             seuil_marge_jours: float = SEUIL_MARGE_JUSTESSE_JOURS,
             delai_livraison_jours: float = 0,
             rotation_prudente: bool = False,
             corriger_ruptures_passees: bool = True,
             politique_abc: bool = False) -> ResultatAnalyse:
    """Croise les 3 fichiers et produit les onglets de décision.

    Paramètres d'anticipation (tous facultatifs, comportement historique
    par défaut) :
      - historique : analyses passées (suivi des réappros repoussées et des
        ruptures longues aux ventes écrasées à 0) ;
      - seuil_vigilance_jours : produits du cadencier HORS rupture GPNC dont
        la couverture passe sous ce seuil → onglet Vigilance ;
      - rotation_min_vigilance : plancher de ventes/mois pour la vigilance
        (écarte le bruit des produits à très faible rotation) ;
      - seuil_marge_jours : produits écartés par la règle stricte avec moins
        de cette marge → onglet Écartés de justesse ;
      - delai_livraison_jours : délai de livraison UNIPHARMA ajouté à la
        couverture cible du calcul de Cmd (pas à la règle d'apparition) ;
      - rotation_prudente : retient max(annuelle, 3 mois) par produit ;
      - corriger_ruptures_passees : les mois à 0 vente encadrés de mois
        actifs (= rupture passée) sont interpolés avant le calcul de
        rotation — corrige le biais de SOUS-commande sur les produits qui
        ont déjà manqué (actif par défaut) ;
      - politique_abc : couverture cible SANS date différenciée par classe
        (A 21 j · B 30 j · C 14 j) au lieu de 30 j pour tous — la règle
        d'APPARITION reste la règle stricte, seule la Cmd change (opt-in,
        car elle modifie les quantités de référence).

    ``mapping`` décrit les colonnes de chaque fichier :
      {
        "cadencier":  {"libelle": str, "cip": str|None, "stock": str,
                        "ventes": [str, ...],  # ordre chrono, récent en dernier
                        "conditionnement": str|None,
                        "commande_en_cours": str|None,  # qté déjà commandée
                        "peremption": str|None},        # DLUO la plus proche
        "gpnc":       {"libelle": str, "cip": str|None, "date_reappro": str|None},
        "unipharma":  {"libelle": str, "cip": str|None},
      }
    """
    m_cad, m_gpnc, m_uni = mapping["cadencier"], mapping["gpnc"], mapping["unipharma"]
    alertes: list = []
    matchs_incertains: list = []

    # Index du cadencier et des ruptures UNIPHARMA pour le rapprochement.
    idx_cip_cad, idx_lib_cad, libs_cad = _indexer(
        cadencier, m_cad["libelle"], m_cad.get("cip"))
    idx_cip_uni, idx_lib_uni, libs_uni = _indexer(
        ruptures_unipharma, m_uni["libelle"], m_uni.get("cip"))

    if not _RAPIDFUZZ:
        alertes.append("rapidfuzz non installé : matching exact/CIP uniquement "
                       "(pip install rapidfuzz recommandé).")

    def _rotation(ventes: list) -> float:
        """Rotation retenue : période choisie, ou la plus élevée des deux
        moyennes (annuelle / 3 mois) en mode prudent — un produit en
        croissance n'est alors jamais sous-couvert."""
        if rotation_prudente:
            return max(calculer_rotation_mensuelle(ventes, "annuelle"),
                       calculer_rotation_mensuelle(ventes, "3mois"))
        return calculer_rotation_mensuelle(ventes, periode)

    infos_cadencier, classe_par_index = _precalculer_cadencier(
        cadencier, m_cad, _rotation, corriger_ruptures_passees)
    indices = list(infos_cadencier)
    annonces_reappro = _annonces_reappro(historique, date_analyse)

    lignes1, lignes2, lignes3 = [], [], []
    lignes_justesse: list = []
    indices_cadencier_traites: set = set()  # pour l'onglet Vigilance

    for _, ligne_gpnc in ruptures_gpnc.iterrows():
        produit_gpnc = str(ligne_gpnc[m_gpnc["libelle"]]).strip()
        if not produit_gpnc or produit_gpnc.lower() == "nan":
            continue
        cip_gpnc = normaliser_cip(ligne_gpnc[m_gpnc["cip"]]) if m_gpnc.get("cip") else ""

        # --- Rapprochement avec le cadencier -------------------------------
        corr = apparier(produit_gpnc, cip_gpnc, idx_cip_cad, idx_lib_cad, libs_cad)
        if corr.incertain:
            matchs_incertains.append({
                "Produit (ruptures GPNC)": produit_gpnc,
                "Rapproché de (cadencier)":
                    str(cadencier.loc[corr.index, m_cad["libelle"]]),
                "Score": round(corr.score, 1), "Fichier": "cadencier",
            })

        # --- Date de réappro ------------------------------------------------
        date_reappro, jours_avant = _date_reappro_annoncee(
            ligne_gpnc, m_gpnc, date_analyse, produit_gpnc, alertes)

        base3 = {
            "Produit": produit_gpnc,
            "Date réappro": f"{date_reappro:%d/%m/%Y}" if date_reappro else "",
            "Jours avant réappro": jours_avant if jours_avant is not None else "",
        }

        # Fiabilité de la date annoncée : déjà repoussée par le passé ?
        # Calculée ici pour servir aux onglets 1 ET 2 ET « justesse ».
        reports = _compter_reports(annonces_reappro.get(produit_gpnc, []),
                                   date_reappro)
        avert_reports = (f" · ⚠️ réappro déjà repoussée {reports} fois "
                         "(date peu fiable)") if reports else ""

        # --- Étape 1 : périmètre (vendu, rotation > 0) ----------------------
        if corr.index is None:
            lignes3.append({**base3, "Vendu (O/N)": "N", "Stock actuel": "",
                            "Commande en cours": "", "Rotation/mois": "",
                            "Fiabilité rotation": "", "Stock (jours)": "",
                            "Péremption": "", "Dispo UNIPHARMA (O/N)": "",
                            "Décision": "Écarté", "Onglet": "—",
                            "Motif": "Absent du cadencier (non vendu)"})
            continue

        ligne_cad = cadencier.loc[corr.index]
        indices_cadencier_traites.add(corr.index)
        stock, en_cours, ventes, rotation, nb_corriges = \
            infos_cadencier[corr.index]
        classe = classe_par_index.get(corr.index, "C")

        # Commande en cours : évite de recommander ce qui arrive déjà.
        stock_effectif = stock + en_cours
        affiche_en_cours = en_cours if m_cad.get("commande_en_cours") else ""

        # --- Péremption (DLUO) : alerte informative, n'écarte pas le produit
        affiche_peremption = _peremption_produit(
            ligne_cad, m_cad, date_analyse, produit_gpnc, alertes)

        tendance = calculer_tendance(ventes)
        affiche_fiabilite = _fiabilite_rotation(nb_corriges, ventes)
        if rotation <= 0:
            decision, motif = _decider_rotation_nulle(
                produit_gpnc, historique, date_analyse, alertes)
            lignes3.append({**base3, "Vendu (O/N)": "N", "Stock actuel": stock,
                            "Commande en cours": affiche_en_cours,
                            "Rotation/mois": 0, "Fiabilité rotation": "",
                            "Stock (jours)": "", "Péremption": affiche_peremption,
                            "Dispo UNIPHARMA (O/N)": "", "Décision": decision,
                            "Onglet": "—", "Motif": motif})
            continue

        # --- Étapes 2-3 : stock en jours + règle d'apparition ---------------
        # Le stock EFFECTIF (physique + commandes en cours) sert de base au
        # calcul : une commande déjà partie ne doit pas être recommandée.
        stock_jours = calculer_stock_jours(stock_effectif, rotation)
        base3.update({"Vendu (O/N)": "O", "Stock actuel": stock,
                      "Commande en cours": affiche_en_cours,
                      "Rotation/mois": round(rotation, 1),
                      "Fiabilité rotation": affiche_fiabilite,
                      "Stock (jours)": round(stock_jours, 1),
                      "Péremption": affiche_peremption})

        if not doit_apparaitre(stock_jours, jours_avant):
            motif = _motif_ecarte(stock_jours, jours_avant)
            ligne_justesse, complement = _examiner_justesse(
                produit_gpnc, stock, rotation, stock_jours, jours_avant,
                base3["Date réappro"], reports, avert_reports,
                seuil_marge_jours, alertes)
            if ligne_justesse is not None:
                lignes_justesse.append(ligne_justesse)
                motif += complement
            lignes3.append({**base3, "Dispo UNIPHARMA (O/N)": "",
                            "Décision": "Écarté", "Onglet": "—", "Motif": motif})
            continue

        # --- Étape 4 : dépannage UNIPHARMA ----------------------------------
        corr_uni = apparier(produit_gpnc, cip_gpnc, idx_cip_uni, idx_lib_uni, libs_uni)
        if corr_uni.incertain:
            matchs_incertains.append({
                "Produit (ruptures GPNC)": produit_gpnc,
                "Rapproché de (cadencier)":
                    str(ruptures_unipharma.loc[corr_uni.index, m_uni["libelle"]]),
                "Score": round(corr_uni.score, 1), "Fichier": "ruptures UNIPHARMA",
            })
        rupture_uni = corr_uni.index is not None
        urgence = classer_urgence(stock_effectif, stock_jours)

        if rupture_uni:  # rupture chez les DEUX → pas de solution
            lignes2.append({
                "Produit": produit_gpnc, "Stock actuel": stock,
                "Rotation/mois": round(rotation, 1),
                "Stock (jours)": round(stock_jours, 1),
                "Date réappro GPNC": base3["Date réappro"],
                "Péremption": affiche_peremption,
                "Commentaire": ("Anticiper l'information patient ; contacter "
                                "GPNC pour confirmer la date de réappro."
                                + avert_reports),
                "_rotation": rotation, "_stock": stock,
            })
            if reports:
                alertes.append(f"{produit_gpnc} : rupture chez les deux ET "
                               f"réappro déjà repoussée {reports} fois — "
                               "confirmer la date avec GPNC.")
            lignes3.append({**base3, "Dispo UNIPHARMA (O/N)": "N",
                            "Décision": "Retenu", "Onglet": "Onglet 2",
                            "Motif": "Rupture GPNC + UNIPHARMA (pas de solution)"})
            continue

        # --- Étape 5 : quantité à commander ---------------------------------
        # Le délai de livraison UNIPHARMA s'ajoute à la couverture cible :
        # les boîtes commandées aujourd'hui n'arrivent pas aujourd'hui.
        # Sans date de réappro : cible 30 j pour tous, ou différenciée par
        # classe (politique ABC, opt-in) — la règle d'apparition ne bouge pas.
        cmd, commentaire = _quantite_et_commentaire(
            rotation, stock_effectif, en_cours, jours_avant, classe,
            politique_abc, delai_livraison_jours, ligne_cad, m_cad,
            avert_reports)
        if reports:
            alertes.append(f"{produit_gpnc} : la date de réappro GPNC a déjà "
                           f"été repoussée {reports} fois — ne pas compter "
                           "dessus, privilégier le dépannage.")
        proba7 = probabilite_rupture(stock_effectif, rotation, ventes, 7)
        lignes1.append({
            "Priorité": score_priorite(proba7, classe, reports,
                                       sans_date=jours_avant is None),
            "Urgence": urgence, "Classe": classe, "Produit": produit_gpnc,
            "Stock actuel": stock,
            "Commande en cours": affiche_en_cours,
            "Rotation/mois": round(rotation, 1),
            "Tendance": tendance,
            "Fiabilité rotation": affiche_fiabilite,
            "Stock (jours)": round(stock_jours, 1),
            "P(rupture 7 j)": f"{proba7:.0%}",
            "Date réappro GPNC": base3["Date réappro"],
            "Jours avant réappro": jours_avant if jours_avant is not None else "",
            "Péremption": affiche_peremption,
            "Qté à commander (Cmd)": cmd, "Commentaire": commentaire,
            "_stock_jours": stock_jours,
        })
        lignes3.append({**base3, "Dispo UNIPHARMA (O/N)": "O",
                        "Décision": "Retenu", "Onglet": "Onglet 1",
                        "Motif": f"À commander chez UNIPHARMA ({urgence})"})

    # --- Vigilance : anticiper les ruptures de VOTRE stock ---------------
    lignes_vigilance = _calculer_vigilance(
        indices, indices_cadencier_traites, infos_cadencier,
        classe_par_index, cadencier, m_cad, rotation_min_vigilance,
        seuil_vigilance_jours)

    return _assembler_resultat(lignes1, lignes2, lignes3, lignes_vigilance,
                               lignes_justesse, len(ruptures_gpnc),
                               alertes, matchs_incertains)


# ---------------------------------------------------------------------------
# Export Excel (5 onglets : commandes, sans solution, vigilance, justesse,
# analyse complète — mise en forme)
# ---------------------------------------------------------------------------

_COULEURS_URGENCE = {URGENT: "F8CBAD", MODERE: "FFE699", ANTICIPER: "C6EFCE"}


def exporter_excel(resultat: ResultatAnalyse) -> bytes:
    """Classeur de décision : les 5 onglets de l'analyse des ruptures."""
    return exporter_classeur(
        [("À commander UNIPHARMA", resultat.onglet1),
         ("Rupture GPNC+UNIPHARMA", resultat.onglet2),
         ("Vigilance stock", resultat.vigilance),
         ("Écartés de justesse", resultat.ecartes_justesse),
         ("Analyse complète", resultat.onglet3)],
        couleurs_par_colonne={"Urgence": _COULEURS_URGENCE})


def nom_fichier_sortie(date_analyse: date) -> str:
    """Nom conventionnel du fichier généré."""
    return f"commande_ruptures_{date_analyse:%Y-%m-%d}.xlsx"
