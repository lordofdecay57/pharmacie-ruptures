"""Module 3 — Gestion d'un stock fermé (inventaire à lots et péremptions).

Destiné aux stocks tenus à part du stock officinal courant : armoire de
stupéfiants, dotation d'urgence, trousse, réserve de garde, rétrocessions…
La saisie se fait à la douchette (code-barres CIP13 ou Data Matrix GS1) ou
au clavier (nom + dosage, ou code CIP).

Trois particularités de ce stock, qui justifient un module dédié :

1. **la péremption est portée par la boîte, pas par le produit** — deux
   boîtes du même médicament peuvent expirer à six mois d'écart. L'unité
   d'enregistrement est donc le *lot* : (CIP, péremption, n° de lot) ;
2. **le comptage se fait en boîtes ET à l'unité** — une boîte entamée laisse
   des comprimés en vrac, qui comptent dans le total ;
3. **le stock doit pouvoir être imprimé** (CSV ou PDF) pour le contrôle
   physique et la traçabilité.

ISOLATION : ce module ne lit NI le cadencier, NI les fichiers de ruptures
fournisseurs, et n'écrit dans aucun de leurs fichiers. Il est autonome : ses
seules données sont son inventaire et son répertoire de produits.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

_journal = logging.getLogger("pharmacie.stock_ferme")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

COLONNES_STOCK_FERME = [
    "Nom du produit", "Dosage", "Code CIP", "Boîtes", "Unités par boîte",
    "Unités en vrac", "Total unités", "Péremption", "Lot", "Enregistré le",
]
COLONNES_REPERTOIRE = ["Code CIP", "Nom du produit", "Dosage",
                       "Unités par boîte"]

#: Une péremption sous ce seuil est signalée en rouge (retrait à préparer).
SEUIL_PEREMPTION_CRITIQUE_JOURS = 90
#: Sous ce seuil, la ligne est mise en vigilance (à écouler en priorité).
SEUIL_PEREMPTION_VIGILANCE_JOURS = 180

STATUT_PERIME = "⛔ Périmé"
STATUT_CRITIQUE = "🔴 < 3 mois"
STATUT_VIGILANCE = "🟡 < 6 mois"
STATUT_OK = "🟢 OK"
STATUT_INCONNU = "⚪ Sans date"

#: Préfixes de symbologie ajoutés par certaines douchettes avant le contenu
#: réel : ``]d2`` (Data Matrix GS1), ``]C1`` (GS1-128), ``]e0`` (GS1 DataBar),
#: ``]Q3`` (QR GS1).
_PREFIXES_SYMBOLOGIE = ("]d2", "]C1", "]e0", "]Q3")

#: Séparateur de champ GS1 (FNC1). Les douchettes le transmettent en GS
#: (ASCII 29) ; certaines le remplacent par un caractère imprimable.
_FNC1 = "\x1d"
_SUBSTITUTS_FNC1 = ("\x1d", "␝", "<GS>", "{GS}")

#: Identifiants de données GS1 de longueur FIXE (hors le « 01 » du GTIN).
_AI_FIXES = {
    "00": 18, "01": 14, "02": 14, "11": 6, "12": 6, "13": 6, "15": 6,
    "16": 6, "17": 6, "20": 2,
}
#: Identifiants de longueur VARIABLE, terminés par FNC1.
_AI_VARIABLES = {"10": "lot", "21": "serie", "30": "quantite",
                 "240": "reference", "710": "cip_fr"}


# ---------------------------------------------------------------------------
# Lecture des codes scannés
# ---------------------------------------------------------------------------

@dataclass
class CodeScanne:
    """Résultat de la lecture d'un code-barres ou d'un Data Matrix."""

    cip: str = ""
    peremption: Optional[date] = None
    lot: str = ""
    serie: str = ""
    gtin: str = ""
    #: ``datamatrix`` (GS1), ``cip13`` / ``cip7`` (code-barres linéaire),
    #: ``inconnu`` si le contenu n'a pas pu être interprété.
    format: str = "inconnu"
    brut: str = ""

    @property
    def reconnu(self) -> bool:
        return self.format != "inconnu"


def cip_depuis_gtin(gtin: str) -> str:
    """CIP13 à partir du GTIN-14 du Data Matrix (zéro de tête à retirer).

    Les CIP français sont des GTIN-13 : le Data Matrix les code sur 14
    chiffres en ajoutant un zéro devant. On ne retire ce zéro que s'il est
    bien là, pour ne pas mutiler un GTIN étranger réellement sur 14 chiffres.
    """
    chiffres = re.sub(r"\D", "", gtin or "")
    if len(chiffres) == 14 and chiffres.startswith("0"):
        return chiffres[1:]
    return chiffres


def _date_gs1(valeur: str) -> Optional[date]:
    """Date GS1 ``AAMMJJ`` → date. ``JJ = 00`` signifie « fin de mois ».

    Le siècle suit la règle GS1 : un millésime à plus de 50 ans dans le
    futur appartient au siècle précédent (aucune boîte ne périme en 2075).
    """
    chiffres = re.sub(r"\D", "", valeur or "")
    if len(chiffres) != 6:
        return None
    annee, mois, jour = (int(chiffres[:2]), int(chiffres[2:4]),
                         int(chiffres[4:]))
    if not 1 <= mois <= 12:
        return None
    siecle = 2000 + annee
    if siecle - date.today().year > 50:
        siecle -= 100
    dernier = monthrange(siecle, mois)[1]
    # ``JJ = 00`` est la convention GS1 pour « fin de mois ». Un jour hors
    # calendrier (31/02, vu sur des codes mal générés) est ramené au dernier
    # jour du mois plutôt que rejeté : perdre la péremption d'une boîte
    # coûterait bien plus cher que ce jour d'écart.
    if jour == 0 or jour > dernier:
        jour = dernier
    return date(siecle, mois, jour)


def _nettoyer_scan(brut: str) -> str:
    """Retire le préfixe de symbologie et normalise les séparateurs FNC1."""
    texte = (brut or "").strip()
    for prefixe in _PREFIXES_SYMBOLOGIE:
        if texte.startswith(prefixe):
            texte = texte[len(prefixe):]
            break
    for substitut in _SUBSTITUTS_FNC1:
        texte = texte.replace(substitut, _FNC1)
    return texte


def _suite_de_champs_fixes(texte: str) -> bool:
    """Vrai si ``texte`` s'interprète INTÉGRALEMENT en champs GS1 fixes."""
    while texte:
        longueur = _AI_FIXES.get(texte[:2])
        if longueur is None or len(texte) < 2 + longueur:
            return False
        texte = texte[2 + longueur:]
    return True


def _fin_champ_variable(reste: str) -> int:
    """Longueur d'un champ variable quand le séparateur FNC1 est absent.

    Certaines douchettes n'émettent pas le FNC1. Couper au premier
    identifiant GS1 qui *ressemble* à un en-tête tronquerait le numéro de
    lot dès qu'il contient « 21 » ou « 17 » (« LOT42 » suivi de « 17… » se
    lirait « LOT4 »). On ne coupe donc qu'à un endroit où **tout le reste**
    s'interprète en champs de longueur fixe : c'est la seule lecture qui ne
    laisse aucun caractère inexpliqué.
    """
    coupe = reste.find(_FNC1)
    if coupe != -1:
        return coupe
    for i in range(1, len(reste) + 1):
        if _suite_de_champs_fixes(reste[i:]):
            return i
    return len(reste)


def parser_datamatrix(brut: str) -> Optional[CodeScanne]:
    """Data Matrix GS1 → GTIN, péremption, lot, n° de série.

    Renvoie ``None`` si le contenu n'est pas un flux GS1 exploitable (il
    sera alors traité comme un code-barres linéaire).
    """
    texte = _nettoyer_scan(brut)
    if len(texte) < 4 or not texte[:2].isdigit():
        return None

    code = CodeScanne(format="datamatrix", brut=brut or "")
    position, reconnu_un_ai = 0, False
    while position < len(texte):
        if texte[position] == _FNC1:
            position += 1
            continue
        ai = texte[position:position + 2]
        ai3 = texte[position:position + 3]
        if ai in _AI_FIXES:
            longueur = _AI_FIXES[ai]
            valeur = texte[position + 2:position + 2 + longueur]
            if len(valeur) < longueur:
                break
            position += 2 + longueur
            reconnu_un_ai = True
            if ai == "01":
                code.gtin = valeur
                code.cip = cip_depuis_gtin(valeur)
            elif ai == "17":
                code.peremption = _date_gs1(valeur)
        elif ai in _AI_VARIABLES or ai3 in _AI_VARIABLES:
            cle = ai3 if ai3 in _AI_VARIABLES else ai
            debut = position + len(cle)
            longueur = _fin_champ_variable(texte[debut:])
            valeur = texte[debut:debut + longueur]
            position = debut + longueur
            reconnu_un_ai = True
            champ = _AI_VARIABLES[cle]
            if champ == "lot":
                code.lot = valeur.strip()
            elif champ == "serie":
                code.serie = valeur.strip()
            elif champ == "cip_fr" and not code.cip:
                code.cip = re.sub(r"\D", "", valeur)
        else:
            break

    if not reconnu_un_ai or not (code.cip or code.peremption):
        return None
    return code


def parser_code_scanne(brut: str) -> CodeScanne:
    """Lit ce que la douchette a envoyé, quel que soit le type de code.

    Trois cas, dans cet ordre :

    - **Data Matrix GS1** (boîtes récentes) : CIP + péremption + lot d'un
      seul geste — c'est le cas nominal, rien d'autre à saisir ;
    - **code-barres linéaire CIP13** (EAN-13, boîtes anciennes) : le code
      seul, la péremption doit être saisie à la main ;
    - **CIP7** : ancien code à 7 chiffres, conservé tel quel.

    Un contenu non reconnu est renvoyé avec ``format = "inconnu"`` et son
    texte brut, afin que l'interface propose une saisie manuelle plutôt que
    de perdre l'information.
    """
    texte = _nettoyer_scan(brut).strip()
    if not texte:
        return CodeScanne(brut=brut or "")

    code = parser_datamatrix(brut)
    if code is not None:
        return code

    chiffres = re.sub(r"\D", "", texte)
    if len(chiffres) == 13 and chiffres == texte:
        return CodeScanne(cip=chiffres, format="cip13", brut=brut or "")
    if len(chiffres) == 14 and chiffres == texte:
        return CodeScanne(cip=cip_depuis_gtin(chiffres), gtin=chiffres,
                          format="cip13", brut=brut or "")
    if len(chiffres) == 7 and chiffres == texte:
        return CodeScanne(cip=chiffres, format="cip7", brut=brut or "")
    return CodeScanne(brut=brut or "")


def parser_peremption_saisie(valeur) -> Optional[date]:
    """Péremption tapée au clavier : ``MM/AAAA``, ``JJ/MM/AAAA``, ``AAAA-MM``…

    Sans jour, on retient le DERNIER jour du mois : une boîte marquée
    « 03/2027 » est utilisable jusqu'au 31 mars 2027.
    """
    if valeur in (None, ""):
        return None
    if isinstance(valeur, date) and not isinstance(valeur, datetime):
        return valeur
    if isinstance(valeur, datetime):
        return valeur.date()

    texte = str(valeur).strip()
    for motif, ordre in (
        (r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$", "jma"),
        (r"^(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})$", "amj"),
        (r"^(\d{1,2})[/\-.](\d{4})$", "ma"),
        (r"^(\d{4})[/\-.](\d{1,2})$", "am"),
        (r"^(\d{1,2})[/\-.](\d{2})$", "ma2"),
    ):
        trouve = re.match(motif, texte)
        if not trouve:
            continue
        g = trouve.groups()
        if ordre == "jma":
            jour, mois, annee = int(g[0]), int(g[1]), int(g[2])
        elif ordre == "amj":
            annee, mois, jour = int(g[0]), int(g[1]), int(g[2])
        elif ordre == "ma":
            mois, annee, jour = int(g[0]), int(g[1]), 0
        elif ordre == "am":
            annee, mois, jour = int(g[0]), int(g[1]), 0
        else:  # MM/AA
            mois, annee, jour = int(g[0]), 2000 + int(g[1]), 0
        if not 1 <= mois <= 12:
            return None
        try:
            return date(annee, mois, jour or monthrange(annee, mois)[1])
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Inventaire
# ---------------------------------------------------------------------------

@dataclass
class EntreeStock:
    """Une ligne d'inventaire : un lot d'un produit, à une péremption."""

    cip: str = ""
    nom: str = ""
    dosage: str = ""
    boites: int = 0
    unites_par_boite: int = 0
    unites_vrac: int = 0
    peremption: Optional[date] = None
    lot: str = ""
    enregistre_le: Optional[date] = None

    def __post_init__(self):
        self.cip = re.sub(r"\D", "", str(self.cip or ""))
        self.nom = " ".join(str(self.nom or "").split())
        self.dosage = " ".join(str(self.dosage or "").split())
        self.lot = str(self.lot or "").strip()


def total_unites(boites: int, unites_par_boite: int, unites_vrac: int) -> int:
    """Comptage à l'unité : boîtes pleines + comprimés de la boîte entamée.

    Sans conditionnement connu (``unites_par_boite = 0``), on ne convertit
    pas les boîtes : seul le vrac est compté, pour ne pas inventer un total.
    """
    return int(max(0, boites)) * int(max(0, unites_par_boite)) + int(
        max(0, unites_vrac))


def cle_lot(cip: str, nom: str, peremption: Optional[date], lot: str) -> tuple:
    """Identité d'une ligne d'inventaire.

    La péremption ET le n° de lot font partie de la clé : deux boîtes du même
    médicament qui n'expirent pas le même jour restent deux lignes — c'est
    tout l'objet du module. Le nom complète la clé pour les produits sans
    code CIP (préparations, dispositifs).
    """
    return (re.sub(r"\D", "", str(cip or "")),
            "" if cip else " ".join(str(nom or "").upper().split()),
            peremption.isoformat() if peremption else "",
            str(lot or "").strip().upper())


def inventaire_vide() -> pd.DataFrame:
    """Inventaire neuf, colonnes déjà en place (évite les tests d'existence)."""
    return pd.DataFrame(columns=COLONNES_STOCK_FERME)


def _ligne_en_dict(entree: EntreeStock, aujourdhui: date) -> dict:
    return {
        "Nom du produit": entree.nom,
        "Dosage": entree.dosage,
        "Code CIP": entree.cip,
        "Boîtes": int(entree.boites),
        "Unités par boîte": int(entree.unites_par_boite),
        "Unités en vrac": int(entree.unites_vrac),
        "Total unités": total_unites(entree.boites, entree.unites_par_boite,
                                     entree.unites_vrac),
        "Péremption": entree.peremption,
        "Lot": entree.lot,
        "Enregistré le": entree.enregistre_le or aujourdhui,
    }


def _cles(inventaire: pd.DataFrame) -> list:
    return [cle_lot(l.get("Code CIP", ""), l.get("Nom du produit", ""),
                    l.get("Péremption"), l.get("Lot", ""))
            for _, l in inventaire.iterrows()]


def ajouter_entree(inventaire: pd.DataFrame, entree: EntreeStock,
                   aujourdhui: Optional[date] = None) -> pd.DataFrame:
    """Ajoute un lot, ou l'incrémente s'il est déjà à l'inventaire.

    Scanner deux fois la même boîte n'a pas de sens : un second scan du même
    (produit, péremption, lot) ajoute une boîte à la ligne existante plutôt
    que de créer un doublon. Le nom et le conditionnement déjà connus sont
    conservés si le nouveau scan ne les renseigne pas.
    """
    aujourdhui = aujourdhui or date.today()
    if inventaire is None or inventaire.empty:
        inventaire = inventaire_vide()
    inventaire = inventaire.reindex(columns=COLONNES_STOCK_FERME).copy()

    cible = cle_lot(entree.cip, entree.nom, entree.peremption, entree.lot)
    for i, cle in zip(inventaire.index, _cles(inventaire)):
        if cle != cible:
            continue
        inventaire.at[i, "Boîtes"] = (int(inventaire.at[i, "Boîtes"] or 0)
                                      + int(entree.boites))
        inventaire.at[i, "Unités en vrac"] = (
            int(inventaire.at[i, "Unités en vrac"] or 0)
            + int(entree.unites_vrac))
        if entree.unites_par_boite:
            inventaire.at[i, "Unités par boîte"] = int(entree.unites_par_boite)
        if entree.nom:
            inventaire.at[i, "Nom du produit"] = entree.nom
        if entree.dosage:
            inventaire.at[i, "Dosage"] = entree.dosage
        inventaire.at[i, "Total unités"] = total_unites(
            inventaire.at[i, "Boîtes"], inventaire.at[i, "Unités par boîte"],
            inventaire.at[i, "Unités en vrac"])
        inventaire.at[i, "Enregistré le"] = entree.enregistre_le or aujourdhui
        return inventaire

    ligne = pd.DataFrame([_ligne_en_dict(entree, aujourdhui)],
                         columns=COLONNES_STOCK_FERME)
    return pd.concat([inventaire, ligne], ignore_index=True)


def retirer_entree(inventaire: pd.DataFrame, cip: str, nom: str,
                   peremption: Optional[date], lot: str, boites: int = 1,
                   unites_vrac: int = 0) -> pd.DataFrame:
    """Sortie de stock : décrémente le lot, et supprime la ligne à zéro.

    Une ligne dont il ne reste ni boîte ni unité disparaît de l'inventaire :
    un stock fermé se contrôle boîte à boîte, une ligne à zéro n'est que du
    bruit sur la liste imprimée.
    """
    if inventaire is None or inventaire.empty:
        return inventaire_vide()
    inventaire = inventaire.reindex(columns=COLONNES_STOCK_FERME).copy()
    cible = cle_lot(cip, nom, peremption, lot)

    for i, cle in zip(inventaire.index, _cles(inventaire)):
        if cle != cible:
            continue
        inventaire.at[i, "Boîtes"] = max(
            0, int(inventaire.at[i, "Boîtes"] or 0) - int(boites))
        inventaire.at[i, "Unités en vrac"] = max(
            0, int(inventaire.at[i, "Unités en vrac"] or 0) - int(unites_vrac))
        inventaire.at[i, "Total unités"] = total_unites(
            inventaire.at[i, "Boîtes"], inventaire.at[i, "Unités par boîte"],
            inventaire.at[i, "Unités en vrac"])
        if (int(inventaire.at[i, "Boîtes"]) == 0
                and int(inventaire.at[i, "Unités en vrac"]) == 0):
            inventaire = inventaire.drop(index=i)
        break
    return inventaire.reset_index(drop=True)


def jours_avant_peremption(peremption, aujourdhui: date) -> Optional[int]:
    """Jours restants avant expiration (négatif si la boîte est périmée)."""
    peremption = parser_peremption_saisie(peremption)
    return None if peremption is None else (peremption - aujourdhui).days


def statut_peremption(peremption, aujourdhui: Optional[date] = None) -> str:
    """Feu de circulation de la péremption d'un lot."""
    aujourdhui = aujourdhui or date.today()
    jours = jours_avant_peremption(peremption, aujourdhui)
    if jours is None:
        return STATUT_INCONNU
    if jours < 0:
        return STATUT_PERIME
    if jours <= SEUIL_PEREMPTION_CRITIQUE_JOURS:
        return STATUT_CRITIQUE
    if jours <= SEUIL_PEREMPTION_VIGILANCE_JOURS:
        return STATUT_VIGILANCE
    return STATUT_OK


def inventaire_affichable(inventaire: pd.DataFrame,
                          aujourdhui: Optional[date] = None) -> pd.DataFrame:
    """Inventaire prêt à lire : statut, jours restants, tri par urgence.

    Les lots qui expirent le plus tôt remontent en tête — c'est l'ordre dans
    lequel on veut les traiter, et celui de la liste imprimée.
    """
    aujourdhui = aujourdhui or date.today()
    if inventaire is None or inventaire.empty:
        return inventaire_vide().assign(**{"Statut": [], "Jours restants": []})

    tableau = inventaire.reindex(columns=COLONNES_STOCK_FERME).copy()
    tableau["Péremption"] = tableau["Péremption"].map(parser_peremption_saisie)
    tableau["Statut"] = tableau["Péremption"].map(
        lambda p: statut_peremption(p, aujourdhui))
    tableau["Jours restants"] = tableau["Péremption"].map(
        lambda p: jours_avant_peremption(p, aujourdhui))
    tableau["Total unités"] = [
        total_unites(l["Boîtes"], l["Unités par boîte"], l["Unités en vrac"])
        for _, l in tableau.iterrows()]
    # Les lots sans date passent en dernier : rien ne presse à leur sujet.
    tableau["_ordre"] = tableau["Jours restants"].map(
        lambda j: 10 ** 6 if j is None else j)
    tableau = (tableau.sort_values(["_ordre", "Nom du produit"])
               .drop(columns=["_ordre"]).reset_index(drop=True))
    return tableau.reindex(
        columns=["Statut"] + COLONNES_STOCK_FERME + ["Jours restants"])


def normaliser_tableau_edite(edite: pd.DataFrame) -> pd.DataFrame:
    """Remet en forme un inventaire corrigé à la main dans le tableau.

    L'édition directe est le moyen le plus rapide de rectifier un comptage,
    mais elle laisse le tableau dans un état approximatif : colonnes de
    lecture (statut, jours restants) mélangées au stock, quantités saisies en
    texte, lignes ajoutées puis laissées vides, total d'unités périmé. On
    reconstruit ici un inventaire propre.

    Une ligne sans nom de produit est abandonnée : la création d'une
    référence passe par la fiche de saisie, qui, elle, exige une péremption.
    """
    if edite is None or edite.empty:
        return inventaire_vide()
    tableau = edite.reindex(columns=COLONNES_STOCK_FERME).copy()

    for colonne in ("Nom du produit", "Dosage", "Code CIP", "Lot"):
        tableau[colonne] = (tableau[colonne].fillna("").astype(str)
                            .map(lambda v: " ".join(v.split())))
    tableau["Code CIP"] = tableau["Code CIP"].map(
        lambda v: re.sub(r"\D", "", v))
    for colonne in ("Boîtes", "Unités par boîte", "Unités en vrac"):
        tableau[colonne] = (pd.to_numeric(tableau[colonne], errors="coerce")
                            .fillna(0).clip(lower=0).astype(int))
    for colonne in ("Péremption", "Enregistré le"):
        tableau[colonne] = tableau[colonne].map(parser_peremption_saisie)

    tableau = tableau[tableau["Nom du produit"] != ""]
    tableau["Total unités"] = [
        total_unites(l["Boîtes"], l["Unités par boîte"], l["Unités en vrac"])
        for _, l in tableau.iterrows()]
    return tableau.reset_index(drop=True)


def resume_inventaire(inventaire: pd.DataFrame,
                      aujourdhui: Optional[date] = None) -> dict:
    """Compteurs du bandeau : références, boîtes, unités, péremptions."""
    aujourdhui = aujourdhui or date.today()
    tableau = inventaire_affichable(inventaire, aujourdhui)
    if tableau.empty:
        return {"lignes": 0, "references": 0, "boites": 0, "unites": 0,
                "perimes": 0, "critiques": 0, "vigilance": 0, "sans_date": 0}
    codes = tableau.apply(
        lambda l: l["Code CIP"] or l["Nom du produit"].upper(), axis=1)
    statuts = tableau["Statut"]
    return {
        "lignes": len(tableau),
        "references": int(codes.nunique()),
        "boites": int(pd.to_numeric(tableau["Boîtes"], errors="coerce")
                      .fillna(0).sum()),
        "unites": int(pd.to_numeric(tableau["Total unités"], errors="coerce")
                      .fillna(0).sum()),
        "perimes": int((statuts == STATUT_PERIME).sum()),
        "critiques": int((statuts == STATUT_CRITIQUE).sum()),
        "vigilance": int((statuts == STATUT_VIGILANCE).sum()),
        "sans_date": int((statuts == STATUT_INCONNU).sum()),
    }


# ---------------------------------------------------------------------------
# Mémoire : inventaire et répertoire des produits déjà scannés
# ---------------------------------------------------------------------------

def _date_iso(valeur) -> str:
    peremption = parser_peremption_saisie(valeur)
    return peremption.isoformat() if peremption else ""


def sauver_inventaire(inventaire: pd.DataFrame, chemin: Path) -> None:
    """Écrit l'inventaire sur disque (dates en ISO, séparateur ``;``)."""
    tableau = (inventaire_vide() if inventaire is None or inventaire.empty
               else inventaire.reindex(columns=COLONNES_STOCK_FERME).copy())
    for colonne in ("Péremption", "Enregistré le"):
        tableau[colonne] = tableau[colonne].map(_date_iso)
    Path(chemin).parent.mkdir(parents=True, exist_ok=True)
    tableau.to_csv(chemin, index=False, sep=";", encoding="utf-8-sig")


def charger_inventaire(chemin: Path) -> pd.DataFrame:
    """Relit l'inventaire enregistré ; inventaire vide si le fichier manque.

    Un fichier illisible (édité à la main, tronqué) ne doit pas empêcher
    l'ouverture du module : on repart d'un inventaire vide en le signalant
    dans le journal, l'ancien fichier reste sur le disque.
    """
    chemin = Path(chemin)
    if not chemin.exists():
        return inventaire_vide()
    try:
        tableau = pd.read_csv(chemin, sep=";", dtype=str,
                              encoding="utf-8-sig").fillna("")
    except Exception:
        _journal.warning("Inventaire du stock fermé illisible : %s", chemin)
        return inventaire_vide()
    tableau = tableau.reindex(columns=COLONNES_STOCK_FERME)
    for colonne in ("Boîtes", "Unités par boîte", "Unités en vrac",
                    "Total unités"):
        tableau[colonne] = (pd.to_numeric(tableau[colonne], errors="coerce")
                            .fillna(0).astype(int))
    for colonne in ("Péremption", "Enregistré le"):
        tableau[colonne] = tableau[colonne].map(parser_peremption_saisie)
    for colonne in ("Nom du produit", "Dosage", "Code CIP", "Lot"):
        tableau[colonne] = tableau[colonne].fillna("").astype(str)
    return tableau


def repertoire_vide() -> pd.DataFrame:
    return pd.DataFrame(columns=COLONNES_REPERTOIRE)


def memoriser_produit(repertoire: pd.DataFrame, cip: str, nom: str,
                      dosage: str = "",
                      unites_par_boite: int = 0) -> pd.DataFrame:
    """Retient l'identité d'un CIP pour les scans suivants.

    C'est la « mémoire » du module : un produit nommé une fois n'a plus à
    l'être — au prochain scan, la douchette suffit.
    """
    cip = re.sub(r"\D", "", str(cip or ""))
    if not cip or not str(nom or "").strip():
        return repertoire if repertoire is not None else repertoire_vide()
    if repertoire is None or repertoire.empty:
        repertoire = repertoire_vide()
    repertoire = repertoire.reindex(columns=COLONNES_REPERTOIRE).copy()

    nom = " ".join(str(nom).split())
    dosage = " ".join(str(dosage or "").split())
    existant = repertoire.index[repertoire["Code CIP"].astype(str) == cip]
    if len(existant):
        i = existant[0]
        repertoire.at[i, "Nom du produit"] = nom
        if dosage:
            repertoire.at[i, "Dosage"] = dosage
        if unites_par_boite:
            repertoire.at[i, "Unités par boîte"] = int(unites_par_boite)
        return repertoire
    ligne = pd.DataFrame([{"Code CIP": cip, "Nom du produit": nom,
                           "Dosage": dosage,
                           "Unités par boîte": int(unites_par_boite or 0)}],
                         columns=COLONNES_REPERTOIRE)
    return pd.concat([repertoire, ligne], ignore_index=True)


def produit_connu(repertoire: pd.DataFrame, cip: str) -> Optional[dict]:
    """Identité mémorisée d'un CIP, ou ``None`` s'il est encore inconnu."""
    cip = re.sub(r"\D", "", str(cip or ""))
    if not cip or repertoire is None or repertoire.empty:
        return None
    trouve = repertoire[repertoire["Code CIP"].astype(str) == cip]
    if trouve.empty:
        return None
    ligne = trouve.iloc[0]
    unites = pd.to_numeric(pd.Series([ligne.get("Unités par boîte", 0)]),
                           errors="coerce").fillna(0).astype(int).iloc[0]
    return {"nom": str(ligne.get("Nom du produit", "") or ""),
            "dosage": str(ligne.get("Dosage", "") or ""),
            "unites_par_boite": int(unites)}


def sauver_repertoire(repertoire: pd.DataFrame, chemin: Path) -> None:
    tableau = (repertoire_vide() if repertoire is None or repertoire.empty
               else repertoire.reindex(columns=COLONNES_REPERTOIRE))
    Path(chemin).parent.mkdir(parents=True, exist_ok=True)
    tableau.to_csv(chemin, index=False, sep=";", encoding="utf-8-sig")


def charger_repertoire(chemin: Path) -> pd.DataFrame:
    chemin = Path(chemin)
    if not chemin.exists():
        return repertoire_vide()
    try:
        tableau = pd.read_csv(chemin, sep=";", dtype=str,
                              encoding="utf-8-sig").fillna("")
    except Exception:
        _journal.warning("Répertoire produits illisible : %s", chemin)
        return repertoire_vide()
    tableau = tableau.reindex(columns=COLONNES_REPERTOIRE).fillna("")
    tableau["Unités par boîte"] = (
        pd.to_numeric(tableau["Unités par boîte"], errors="coerce")
        .fillna(0).astype(int))
    return tableau


# ---------------------------------------------------------------------------
# Impression de la liste de stock (CSV et PDF)
# ---------------------------------------------------------------------------

#: Colonnes de la liste imprimée, dans l'ordre demandé au comptoir.
COLONNES_IMPRESSION = ["Statut", "Nom du produit", "Dosage", "Code CIP",
                       "Boîtes", "Unités", "Péremption", "Lot"]


def _tableau_impression(inventaire: pd.DataFrame,
                        aujourdhui: Optional[date] = None) -> pd.DataFrame:
    tableau = inventaire_affichable(inventaire, aujourdhui)
    if tableau.empty:
        return pd.DataFrame(columns=COLONNES_IMPRESSION)
    sortie = pd.DataFrame({
        "Statut": tableau["Statut"],
        "Nom du produit": tableau["Nom du produit"],
        "Dosage": tableau["Dosage"],
        "Code CIP": tableau["Code CIP"],
        "Boîtes": tableau["Boîtes"],
        "Unités": tableau["Total unités"],
        "Péremption": tableau["Péremption"].map(
            lambda p: f"{p:%d/%m/%Y}" if p else ""),
        "Lot": tableau["Lot"],
    })
    return sortie.reindex(columns=COLONNES_IMPRESSION)


def exporter_csv(inventaire: pd.DataFrame,
                 aujourdhui: Optional[date] = None) -> bytes:
    """Liste de stock en CSV (``;`` et BOM : Excel l'ouvre sans réglage)."""
    tampon = io.StringIO()
    _tableau_impression(inventaire, aujourdhui).to_csv(
        tampon, index=False, sep=";", quoting=csv.QUOTE_MINIMAL)
    return tampon.getvalue().encode("utf-8-sig")


#: Teintes de fond des lignes imprimées, par statut de péremption.
_COULEURS_PDF = {
    STATUT_PERIME: (0.96, 0.80, 0.80),
    STATUT_CRITIQUE: (0.97, 0.85, 0.72),
    STATUT_VIGILANCE: (1.00, 0.94, 0.75),
}

#: Les polices PDF standard n'ont pas de glyphe pour les émojis — à
#: l'impression, le statut est donc écrit en toutes lettres. La couleur de
#: fond n'est qu'un renfort : la liste reste lisible imprimée en noir et
#: blanc.
_STATUT_PDF = {
    STATUT_PERIME: "PÉRIMÉ",
    STATUT_CRITIQUE: "< 3 mois",
    STATUT_VIGILANCE: "< 6 mois",
    STATUT_OK: "OK",
    STATUT_INCONNU: "sans date",
}


def exporter_pdf(inventaire: pd.DataFrame, titre: str = "Stock fermé",
                 aujourdhui: Optional[date] = None) -> bytes:
    """Liste de stock en PDF, prête à imprimer pour le contrôle physique.

    Format paysage, en-tête répété à chaque page, lignes teintées selon
    l'urgence de la péremption. Lève ``ValueError`` avec un message clair si
    ReportLab n'est pas installé — l'export CSV, lui, reste disponible.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer,
                                        Table, TableStyle)
    except ImportError:
        raise ValueError("Impression PDF indisponible : lancez "
                         "« pip install reportlab » puis réessayez.")

    aujourdhui = aujourdhui or date.today()
    tableau = _tableau_impression(inventaire, aujourdhui)
    resume = resume_inventaire(inventaire, aujourdhui)

    tampon = io.BytesIO()
    document = SimpleDocTemplate(
        tampon, pagesize=landscape(A4), title=titre,
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm)
    styles = getSampleStyleSheet()
    elements = [
        Paragraph(f"<b>{titre}</b>", styles["Title"]),
        Paragraph(
            f"Édité le {aujourdhui:%d/%m/%Y} — {resume['lignes']} lot(s), "
            f"{resume['references']} référence(s), {resume['boites']} boîte(s), "
            f"{resume['unites']} unité(s) · périmés : {resume['perimes']} · "
            f"moins de 3 mois : {resume['critiques']}",
            styles["Normal"]),
        Spacer(1, 6 * mm),
    ]

    if tableau.empty:
        elements.append(Paragraph("Inventaire vide.", styles["Normal"]))
        document.build(elements)
        return tampon.getvalue()

    imprime = tableau.astype(str).copy()
    imprime["Statut"] = tableau["Statut"].map(
        lambda s: _STATUT_PDF.get(s, str(s)))
    donnees = [list(imprime.columns)] + imprime.values.tolist()
    largeurs = [22 * mm, 68 * mm, 30 * mm, 30 * mm, 18 * mm, 18 * mm,
                26 * mm, 30 * mm]
    grille = Table(donnees, colWidths=largeurs, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9D9D9")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (4, 1), (5, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#9E9E9E")),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    for i, statut in enumerate(tableau["Statut"], start=1):
        teinte = _COULEURS_PDF.get(statut)
        if teinte:
            style.append(("BACKGROUND", (0, i), (-1, i), colors.Color(*teinte)))
    grille.setStyle(TableStyle(style))
    elements.append(grille)
    document.build(elements)
    return tampon.getvalue()


def nom_fichier_stock_ferme(extension: str,
                            aujourdhui: Optional[date] = None) -> str:
    """Nom conventionnel du fichier imprimé : ``stock_ferme_AAAA-MM-JJ.ext``."""
    aujourdhui = aujourdhui or date.today()
    return f"stock_ferme_{aujourdhui:%Y-%m-%d}.{extension.lstrip('.')}"
