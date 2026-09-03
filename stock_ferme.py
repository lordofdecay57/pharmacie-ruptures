"""Module 3 — Gestion d'un stock interne (inventaire à lots et péremptions).

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
import unicodedata
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Sequence

import pandas as pd

import stockage_partage

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

#: Colonnes RÉELLEMENT affichées et imprimées. Le dosage n'y figure pas :
#: il fait partie de la dénomination (« DOLIPRANE 1000 mg, comprimé »), et
#: une colonne de plus pour le répéter ne dit rien de neuf tout en poussant
#: la péremption hors de l'écran. Il est fondu dans le nom à l'affichage —
#: rien n'est perdu, y compris pour les produits saisis à la main.
COLONNES_AFFICHEES = [c for c in COLONNES_STOCK_FERME if c != "Dosage"]

#: Les TROIS seules colonnes de l'écran de tous les jours : le nom, le
#: code CIP, et si la boîte est périmée. Demande de la pharmacie, mot
#: pour mot — « rien de plus ».
#:
#: Onze colonnes tenaient ici : boîtes, unités par boîte, vrac, total,
#: lot, date d'enregistrement, jours restants. Devant l'armoire on ne
#: cherche que deux choses — est-ce le bon produit, et est-il encore
#: bon. Le reste reste enregistré, s'ouvre dans le détail, et part
#: entier dans le CSV et le PDF : rien n'est perdu, tout est rangé.
COLONNES_ESSENTIELLES = ["Statut", "Nom du produit", "Code CIP"]

#: Péremption imminente : la boîte ne passera pas le mois. C'est le palier
#: qui déclenche une action immédiate — retrait, remplacement, ou emploi en
#: priorité absolue.
SEUIL_PEREMPTION_IMMINENTE_JOURS = 30
#: Sous ce seuil, le retrait est à préparer.
SEUIL_PEREMPTION_CRITIQUE_JOURS = 90
#: Sous ce seuil, la ligne est mise en vigilance (à écouler en priorité).
SEUIL_PEREMPTION_VIGILANCE_JOURS = 180

STATUT_PERIME = "⛔ Périmé"
STATUT_IMMINENT = "🔴 < 1 mois"
STATUT_CRITIQUE = "🟠 < 3 mois"
STATUT_VIGILANCE = "🟡 < 6 mois"
STATUT_OK = "🟢 OK"
STATUT_INCONNU = "⚪ Sans date"

#: Bornes d'une péremption plausible. Un stock interne contient des boîtes
#: périmées depuis longtemps (elles y sont pour être retirées) et des boîtes
#: qui périment loin — mais pas en l'an 9999. Sans ces bornes, une faute de
#: frappe sur l'année (« 31129999 », « 082207 ») passait sans un mot et la
#: boîte s'affichait « 🟢 OK » pour toujours, en bas de la liste, invisible.
#: Bornes ABSOLUES et non relatives au jour : la lecture d'un inventaire ne
#: doit pas dépendre de la date à laquelle on l'ouvre.
ANNEE_PEREMPTION_MIN = 1990
ANNEE_PEREMPTION_MAX = 2099

#: Ordres d'affichage de l'inventaire. Les deux répondent à deux gestes
#: différents : la péremption pour décider ce qu'on retire, le nom pour
#: retrouver un produit — sur l'écran comme sur la liste papier que l'on
#: parcourt devant l'armoire.
TRI_PEREMPTION = "Péremption (au plus proche)"
TRI_NOM = "Nom (A → Z)"
TRIS = (TRI_PEREMPTION, TRI_NOM)

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
#:
#: L'identifiant ``710`` (CIP français) est volontairement absent : quand la
#: douchette n'émet pas le FNC1, il est indissociable d'un chiffre suivi de
#: ``10`` (n° de lot), et il ferait alors couper les numéros de série d'un
#: caractère trop tôt. Les boîtes françaises portent de toute façon le CIP
#: dans le GTIN de l'identifiant ``01``.
_AI_VARIABLES = {"10": "lot", "21": "serie", "30": "quantite",
                 "240": "reference"}


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


def _suite_avec_champ_variable_final(texte: str) -> bool:
    """Comme ci-dessus, mais en tolérant UN champ variable en dernier.

    Cas courant : ``…10<lot>21<n° de série>`` sans séparateur. Le n° de
    série court jusqu'à la fin, donc aucune lecture « tout en champs fixes »
    n'existe.
    """
    while texte:
        for cle in (texte[:2], texte[:3]):
            # Un identifiant suivi de rien ne serait pas un champ mais la
            # fin du champ précédent, coupée au mauvais endroit.
            if cle in _AI_VARIABLES and len(texte) > len(cle):
                return True  # ce champ court jusqu'à la fin
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
    s'explique.

    Deux lectures, dans cet ordre : d'abord celle qui ne laisse que des
    champs de longueur fixe — non ambiguë, donc prioritaire ; à défaut,
    celle qui tolère un dernier champ variable (``21<n° de série>``).
    """
    coupe = reste.find(_FNC1)
    if coupe != -1:
        return coupe
    # La borne s'arrête AVANT la fin : un reste vide satisfait trivialement
    # les deux lectures et ferait toujours gagner « le champ va jusqu'au
    # bout », qui est justement le repli de dernier recours.
    for valide in (_suite_de_champs_fixes, _suite_avec_champ_variable_final):
        for i in range(1, len(reste)):
            if valide(reste[i:]):
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

    # Un code recopié à la main depuis la boîte est souvent espacé ou
    # ponctué (« 3400 912 345 678 ») : seuls les séparateurs sont tolérés,
    # pour ne pas confondre un libellé chiffré avec un code produit.
    if not re.fullmatch(r"[\d\s.\-]+", texte):
        return CodeScanne(brut=brut or "")
    chiffres = re.sub(r"\D", "", texte)
    if len(chiffres) == 13:
        return CodeScanne(cip=chiffres, format="cip13", brut=brut or "")
    if len(chiffres) == 14:
        return CodeScanne(cip=cip_depuis_gtin(chiffres), gtin=chiffres,
                          format="cip13", brut=brut or "")
    if len(chiffres) == 7:
        return CodeScanne(cip=chiffres, format="cip7", brut=brut or "")
    return CodeScanne(brut=brut or "")


def _peremption_chiffres_seuls(texte: str) -> Optional[tuple]:
    """« 082027 » → (2027, 8, 0). Les barres obliques deviennent inutiles.

    Taper les séparateurs coûte deux frappes par date, et il y en a une par
    boîte : sur un inventaire complet, cela fait des centaines de frappes
    pour rien. Les chiffres seuls suffisent — c'est d'ailleurs ce qui est
    imprimé sur les cartons.

    Six chiffres sont ambigus : ``082027`` est un mois suivi d'une année,
    ``310827`` un jour, un mois et une année courte. On tranche par le sens
    — un mois vaut au plus 12, une année tient entre 1900 et 2199.
    """
    if not texte.isdigit():
        return None
    if len(texte) == 8:                                   # JJMMAAAA
        return int(texte[4:]), int(texte[2:4]), int(texte[:2])
    if len(texte) == 6:
        mois, annee = int(texte[:2]), int(texte[2:])
        if 1 <= mois <= 12 and 1900 <= annee <= 2199:     # MMAAAA
            return annee, mois, 0
        return 2000 + int(texte[4:]), int(texte[2:4]), int(texte[:2])  # JJMMAA
    if len(texte) == 4:                                   # MMAA
        return 2000 + int(texte[2:]), int(texte[:2]), 0
    return None


def _date_plausible(annee: int, mois: int, jour: int) -> Optional[date]:
    """Date construite, ou ``None`` si elle n'a aucun sens pour une boîte.

    ``jour = 0`` signifie « fin de mois » — la convention des boîtes, qui ne
    portent qu'un mois et une année.
    """
    if not 1 <= mois <= 12:
        return None
    if not ANNEE_PEREMPTION_MIN <= annee <= ANNEE_PEREMPTION_MAX:
        return None
    try:
        return date(annee, mois, jour or monthrange(annee, mois)[1])
    except ValueError:
        return None


def parser_peremption_saisie(valeur) -> Optional[date]:
    """Péremption tapée au clavier : ``MM/AAAA``, ``JJ/MM/AAAA``, ``AAAA-MM``…

    Les séparateurs sont **facultatifs** : ``082027`` vaut ``08/2027``, et
    ``31082027`` vaut ``31/08/2027``.

    Sans jour, on retient le DERNIER jour du mois : une boîte marquée
    « 03/2027 » est utilisable jusqu'au 31 mars 2027.

    Une année hors des bornes plausibles est REFUSÉE plutôt que retenue :
    mieux vaut faire retaper une date que laisser une boîte se croire bonne
    jusqu'en l'an 9999.
    """
    if valeur in (None, ""):
        return None
    if isinstance(valeur, date) and not isinstance(valeur, datetime):
        return valeur
    if isinstance(valeur, datetime):
        return valeur.date()

    texte = str(valeur).strip()
    chiffres = _peremption_chiffres_seuls(texte)
    if chiffres:
        return _date_plausible(*chiffres)
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
        return _date_plausible(annee, mois, jour)
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


def _texte(valeur) -> str:
    """Cellule → texte propre. Les vides d'un fichier relu valent NaN, qu'il
    ne faut ni afficher (« nan ») ni traiter comme une valeur présente."""
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return ""
    return " ".join(str(valeur).split())


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
    # Le dosage est intégré au nom dès l'enregistrement : il n'a plus de
    # colonne à lui, et l'identité d'un lot sans code CIP repose sur le nom
    # — le stocker à part le ferait diverger de ce qui est affiché.
    return {
        "Nom du produit": _nom_avec_dosage(entree.nom, entree.dosage),
        "Dosage": "",
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

    # Le nom qui sert de clé est celui qui sera ÉCRIT — dosage compris. Le
    # comparer sous sa forme brute pendant que l'inventaire porte la forme
    # complète créerait un doublon à chaque second scan d'un produit sans
    # code CIP.
    nom_complet = _nom_avec_dosage(entree.nom, entree.dosage)
    cible = cle_lot(entree.cip, nom_complet, entree.peremption, entree.lot)
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
        if nom_complet:
            inventaire.at[i, "Nom du produit"] = nom_complet
        inventaire.at[i, "Total unités"] = total_unites(
            inventaire.at[i, "Boîtes"], inventaire.at[i, "Unités par boîte"],
            inventaire.at[i, "Unités en vrac"])
        inventaire.at[i, "Enregistré le"] = entree.enregistre_le or aujourdhui
        return inventaire

    ligne = pd.DataFrame([_ligne_en_dict(entree, aujourdhui)],
                         columns=COLONNES_STOCK_FERME)
    return pd.concat([inventaire, ligne], ignore_index=True)


def stock_du_lot(inventaire: pd.DataFrame, cip: str, nom: str,
                 peremption: Optional[date], lot: str) -> int:
    """Boîtes réellement en stock pour ce lot précis, 0 s'il a disparu.

    Sert à ne pas promettre une sortie que l'inventaire ne peut plus
    honorer : entre l'affichage d'une liste et le clic, un autre poste a pu
    retirer les dernières boîtes.
    """
    if inventaire is None or inventaire.empty:
        return 0
    cible = cle_lot(cip, nom, peremption, lot)
    for i, cle in zip(inventaire.index, _cles(inventaire)):
        if cle == cible:
            return int(inventaire.at[i, "Boîtes"] or 0)
    return 0


def retirer_entree(inventaire: pd.DataFrame, cip: str, nom: str,
                   peremption: Optional[date], lot: str, boites: int = 1,
                   unites_vrac: int = 0) -> pd.DataFrame:
    """Sortie de stock : décrémente le lot, et supprime la ligne à zéro.

    Une ligne dont il ne reste ni boîte ni unité disparaît de l'inventaire :
    un stock interne se contrôle boîte à boîte, une ligne à zéro n'est que du
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


def unites_disponibles(inventaire: pd.DataFrame, cip: str, nom: str,
                       peremption: Optional[date], lot: str) -> int:
    """Unités réellement sortables de ce lot : le vrac plus les boîtes.

    Sans conditionnement connu (``Unités par boîte = 0``), seules les unités
    déjà en vrac comptent : on ne sait pas combien de comprimés contient une
    boîte, et l'inventer donnerait un total faux.
    """
    if inventaire is None or inventaire.empty:
        return 0
    cible = cle_lot(cip, nom, peremption, lot)
    for i, cle in zip(inventaire.index, _cles(inventaire)):
        if cle == cible:
            return total_unites(inventaire.at[i, "Boîtes"],
                                inventaire.at[i, "Unités par boîte"],
                                inventaire.at[i, "Unités en vrac"])
    return 0


def vrac_sans_boite(inventaire: pd.DataFrame, cip: str = "",
                    nom: str = "") -> int:
    """Unités en vrac de ce produit dans les lots SANS boîte entière.

    Sert à dire la vérité quand un scan de sortie ne trouve rien à sortir :
    « ce produit n'est pas à l'inventaire » serait faux s'il reste sept
    comprimés d'une boîte entamée. Ce n'est pas la même réponse, et ce
    n'est pas le même geste — il faut passer par la sortie à l'unité.
    """
    if inventaire is None or inventaire.empty:
        return 0
    tableau = inventaire.reindex(columns=COLONNES_STOCK_FERME)
    cible_cip = re.sub(r"\D", "", str(cip or ""))
    cible_nom = _texte(nom).upper()
    total = 0
    for _, ligne in tableau.iterrows():
        if cible_cip:
            if re.sub(r"\D", "", _texte(ligne["Code CIP"])) != cible_cip:
                continue
        elif _texte(ligne["Nom du produit"]).upper() != cible_nom:
            continue
        boites = int(pd.to_numeric(ligne["Boîtes"], errors="coerce") or 0)
        if boites >= 1:
            continue
        total += int(pd.to_numeric(ligne["Unités en vrac"],
                                   errors="coerce") or 0)
    return total


def sortir_unites(inventaire: pd.DataFrame, cip: str, nom: str,
                  peremption: Optional[date], lot: str,
                  unites: int) -> tuple:
    """Sortie à l'UNITÉ : on entame une boîte quand le vrac ne suffit pas.

    C'est le geste réel du comptoir : dispenser dix comprimés d'une boîte de
    trente laisse vingt comprimés en vrac. Retirer une boîte entière pour
    dix comprimés fausserait l'inventaire des vingt autres.

    L'ordre suit la réalité : on prend d'abord ce qui est **déjà entamé** —
    une seconde boîte ouverte alors qu'un fond de boîte traîne, c'est du
    périmé annoncé.

    Renvoie ``(inventaire, unites_reellement_sorties)``. On ne sort jamais
    plus que ce qui existe : promettre une sortie que le stock ne peut pas
    honorer, c'est un inventaire faux le lendemain.
    """
    if inventaire is None or inventaire.empty or int(unites) <= 0:
        return (inventaire if inventaire is not None else inventaire_vide()), 0
    inventaire = inventaire.reindex(columns=COLONNES_STOCK_FERME).copy()
    cible = cle_lot(cip, nom, peremption, lot)

    for i, cle in zip(inventaire.index, _cles(inventaire)):
        if cle != cible:
            continue
        boites = int(inventaire.at[i, "Boîtes"] or 0)
        vrac = int(inventaire.at[i, "Unités en vrac"] or 0)
        par_boite = int(inventaire.at[i, "Unités par boîte"] or 0)

        reste = int(unites)
        pris = min(reste, vrac)
        vrac -= pris
        reste -= pris
        # Sans conditionnement connu, une boîte ne se convertit pas en
        # comprimés : on s'arrête au vrac plutôt que d'inventer un compte.
        while reste > 0 and boites > 0 and par_boite > 0:
            boites -= 1
            vrac += par_boite
            entame = min(reste, vrac)
            vrac -= entame
            reste -= entame
            pris += entame

        inventaire.at[i, "Boîtes"] = boites
        inventaire.at[i, "Unités en vrac"] = vrac
        inventaire.at[i, "Total unités"] = total_unites(boites, par_boite,
                                                        vrac)
        if boites == 0 and vrac == 0:
            inventaire = inventaire.drop(index=i)
        return inventaire.reset_index(drop=True), pris
    return inventaire.reset_index(drop=True), 0


def lots_sortables(inventaire: pd.DataFrame,
                   aujourdhui: Optional[date] = None,
                   tri: str = TRI_PEREMPTION) -> list:
    """Boîtes réellement sortables, décrites une par une.

    Sert la **sortie manuelle** : une douchette ne lit pas tout (étiquette
    abîmée, boîte reconditionnée, produit sans code), et il faut alors
    pouvoir désigner la boîte dans une liste. Chaque entrée porte de quoi
    appeler ``retirer_entree`` et de quoi se relire à l'écran.

    Les lignes à zéro boîte sont écartées : les proposer serait promettre
    une sortie impossible.
    """
    tableau = inventaire_affichable(inventaire, aujourdhui, tri)
    lots = []
    for _, ligne in tableau.iterrows():
        boites = int(pd.to_numeric(ligne["Boîtes"], errors="coerce") or 0)
        vrac = int(pd.to_numeric(ligne["Unités en vrac"],
                                 errors="coerce") or 0)
        par_boite = int(pd.to_numeric(ligne["Unités par boîte"],
                                      errors="coerce") or 0)
        # Une boîte entamée n'a plus de boîte pleine mais garde des unités :
        # l'écarter rendrait ses comprimés impossibles à sortir.
        if boites <= 0 and vrac <= 0:
            continue
        peremption = ligne["Péremption"]
        details = [f"{peremption:%d/%m/%Y}" if peremption else "sans date"]
        if _texte(ligne["Lot"]):
            details.append(f"lot {_texte(ligne['Lot'])}")
        details.append(f"{boites} boîte(s)"
                       + (f" + {vrac} unité(s)" if vrac else ""))
        # Le dosage fait déjà partie du nom affiché : rien à recoller ici.
        nom_complet = _texte(ligne["Nom du produit"])
        lots.append({
            "cip": _texte(ligne["Code CIP"]),
            "nom": nom_complet,
            "dosage": "",
            "peremption": peremption,
            "lot": _texte(ligne["Lot"]),
            "boites": boites,
            "unites_vrac": vrac,
            "unites_par_boite": par_boite,
            "unites": total_unites(boites, par_boite, vrac),
            "statut": ligne["Statut"],
            "libelle": f"{ligne['Statut']}  {nom_complet} — "
                       + " · ".join(details),
        })
    return lots


def lot_a_sortir(inventaire: pd.DataFrame, cip: str = "", nom: str = "",
                 peremption: Optional[date] = None,
                 lot: str = "") -> Optional[dict]:
    """Lot à décrémenter pour une sortie de stock, ou ``None`` si absent.

    Un Data Matrix désigne une boîte précise (CIP + péremption + n° de lot)
    et c'est elle qui sort. Un code-barres linéaire ne donne que le produit :
    on sort alors la boîte qui périme **le plus tôt** — c'est la règle de
    l'officine (FEFO), et la seule qui évite de laisser vieillir un lot au
    fond de l'armoire.

    Le drapeau ``exact`` distingue les deux cas : à ``False``, le scan
    désignait une boîte qui n'est pas sortable sous ce lot, et on propose
    la plus proche de la péremption. L'interface doit le dire — sortir un
    lot pour un autre en silence ruinerait la traçabilité.

    Seuls les lots ayant au moins **une boîte entière** sont proposés. Un
    lot entamé — plus de boîte, mais des comprimés en vrac — n'a rien à
    décrémenter : ``retirer_entree`` y retirerait « une boîte » de zéro,
    ce qui ne change rien, et l'écran annonçait pourtant une sortie
    réussie. Pire, la règle FEFO élisait ce lot entamé comme le plus
    proche de la péremption, et la douchette ne sortait alors plus rien
    du tout, même avec des boîtes pleines juste à côté.
    """
    if inventaire is None or inventaire.empty:
        return None
    tableau = inventaire.reindex(columns=COLONNES_STOCK_FERME).copy()
    tableau["Péremption"] = tableau["Péremption"].map(parser_peremption_saisie)

    cip = re.sub(r"\D", "", str(cip or ""))
    if cip:
        candidats = tableau[tableau["Code CIP"].map(
            lambda v: re.sub(r"\D", "", _texte(v))) == cip]
    else:
        cible = _texte(nom).upper()
        candidats = tableau[tableau["Nom du produit"].map(
            lambda v: _texte(v).upper()) == cible]
    candidats = candidats[candidats["Boîtes"].map(
        lambda v: int(pd.to_numeric(v, errors="coerce") or 0)) >= 1]
    if candidats.empty:
        return None

    def _decrire(index, exact: bool) -> dict:
        ligne = candidats.loc[index]
        return {"index": index, "exact": exact,
                "cip": _texte(ligne["Code CIP"]),
                "nom": _texte(ligne["Nom du produit"]),
                "dosage": _texte(ligne["Dosage"]),
                "peremption": ligne["Péremption"],
                "lot": _texte(ligne["Lot"]),
                "boites": int(pd.to_numeric(ligne["Boîtes"],
                                            errors="coerce") or 0)}

    # Le scan désigne-t-il une boîte PRÉCISE ? Seul un Data Matrix le fait.
    if peremption is not None or lot:
        precis = candidats
        if peremption is not None:
            precis = precis[precis["Péremption"] == peremption]
        if lot:
            precis = precis[precis["Lot"].map(
                lambda v: _texte(v).upper()) == lot.strip().upper()]
        if not precis.empty:
            return _decrire(precis.index[0], exact=True)

    # Sinon (code linéaire), ou boîte introuvable sous ce lot : FEFO, la
    # plus proche de la péremption sort. Les lots sans date passent en
    # dernier — rien ne presse à leur sujet.
    ordre = candidats["Péremption"].map(lambda p: date.max if p is None else p)
    return _decrire(ordre.sort_values(kind="stable").index[0],
                    exact=(peremption is None and not lot))


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
    if jours <= SEUIL_PEREMPTION_IMMINENTE_JOURS:
        return STATUT_IMMINENT
    if jours <= SEUIL_PEREMPTION_CRITIQUE_JOURS:
        return STATUT_CRITIQUE
    if jours <= SEUIL_PEREMPTION_VIGILANCE_JOURS:
        return STATUT_VIGILANCE
    return STATUT_OK


def _cle_alphabetique(valeur) -> str:
    """Clé de tri d'un libellé : sans accent, sans casse, sans espaces doubles.

    Sans elle, « ÉLAVIL » se range après « ZOLPIDEM » et « doliprane » après
    « ZYRTEC » : un classement alphabétique qui ne suit pas l'ordre du
    dictionnaire ne sert à rien pour retrouver une boîte dans l'armoire.
    """
    texte = " ".join(_texte(valeur).split()).upper()
    return "".join(c for c in unicodedata.normalize("NFKD", texte)
                   if not unicodedata.combining(c))


def _nom_avec_dosage(nom, dosage) -> str:
    """« DOLIPRANE » + « 1000 mg » → « DOLIPRANE 1000 mg ».

    **Idempotent** : un dosage déjà contenu dans le nom n'est pas répété.
    Sans cette garde, une ligne corrigée dans le tableau puis réaffichée
    finirait par « DOLIPRANE 1000 mg 1000 mg » — et les noms venus de la
    base publique portent tous leur dosage.
    """
    nom, dosage = _texte(nom).strip(), _texte(dosage).strip()
    if not dosage or dosage.upper() in nom.upper():
        return nom
    return f"{nom} {dosage}".strip()


def inventaire_affichable(inventaire: pd.DataFrame,
                          aujourdhui: Optional[date] = None,
                          tri: str = TRI_PEREMPTION) -> pd.DataFrame:
    """Inventaire prêt à lire : statut, jours restants, et ordre au choix.

    Par défaut les lots qui expirent le plus tôt remontent en tête — c'est
    l'ordre dans lequel on veut les traiter. ``TRI_NOM`` range plutôt par
    libellé, pour parcourir l'inventaire produit par produit devant
    l'armoire ; à nom égal, la boîte qui périme la première reste en tête,
    car c'est celle qu'on prend.

    Le **dosage est fondu dans le nom** et sa colonne disparaît : il fait
    déjà partie de la dénomination officielle, et le répéter poussait la
    péremption — la seule colonne qui compte vraiment ici — hors de l'écran.
    L'opération est sans perte et se refait à l'identique : un dosage déjà
    intégré ne l'est pas deux fois.
    """
    aujourdhui = aujourdhui or date.today()
    if inventaire is None or inventaire.empty:
        return (inventaire_vide().reindex(columns=COLONNES_AFFICHEES)
                .assign(**{"Statut": [], "Jours restants": []})
                .reindex(columns=["Statut"] + COLONNES_AFFICHEES
                         + ["Jours restants"]))

    tableau = inventaire.reindex(columns=COLONNES_STOCK_FERME).copy()
    # Une cellule vide relue d'un fichier vaut NaN : sans ce nettoyage, elle
    # s'afficherait « nan » dans le tableau et « None » dans le PDF.
    for colonne in ("Nom du produit", "Dosage", "Code CIP", "Lot"):
        tableau[colonne] = tableau[colonne].map(_texte)
    tableau["Nom du produit"] = [
        _nom_avec_dosage(nom, dosage)
        for nom, dosage in zip(tableau["Nom du produit"], tableau["Dosage"])]
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
    tableau["_nom"] = tableau["Nom du produit"].map(_cle_alphabetique)
    cles = (["_nom", "_ordre"] if tri == TRI_NOM else ["_ordre", "_nom"])
    tableau = (tableau.sort_values(cles)
               .drop(columns=["_ordre", "_nom"])
               .reset_index(drop=True))
    return tableau.reindex(
        columns=["Statut"] + COLONNES_AFFICHEES + ["Jours restants"])


def vue_essentielle(inventaire: pd.DataFrame,
                    aujourdhui: Optional[date] = None,
                    tri: str = TRI_PEREMPTION) -> pd.DataFrame:
    """L'inventaire réduit à ce qu'on lit debout devant l'armoire.

    Le nom, le code CIP, et si la boîte est périmée. Le même ordre et les
    mêmes lignes que la vue complète — on n'en retire que des colonnes,
    jamais un lot : un inventaire qui cache des lignes ne serait plus un
    inventaire.
    """
    return inventaire_affichable(inventaire, aujourdhui, tri).reindex(
        columns=COLONNES_ESSENTIELLES)


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
    # Le tableau modifiable n'affiche plus de colonne « Dosage » : elle
    # revient donc vide. Le nom, lui, porte déjà le dosage — cette ligne ne
    # sert qu'aux appels qui fourniraient encore les deux séparément.
    tableau["Nom du produit"] = [
        _nom_avec_dosage(nom, dosage)
        for nom, dosage in zip(tableau["Nom du produit"], tableau["Dosage"])]
    tableau["Dosage"] = ""
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
                "perimes": 0, "imminents": 0, "critiques": 0, "vigilance": 0,
                "sans_date": 0}
    # Une référence = un CIP ; les produits sans code (préparations,
    # dispositifs) comptent par leur libellé. On passe par `_texte` car une
    # cellule vide relue d'un fichier vaut NaN — qui est *vrai* en Python et
    # ferait donc échouer un simple `a or b`.
    codes = tableau.apply(
        lambda l: (_texte(l["Code CIP"])
                   or _texte(l["Nom du produit"]).upper()), axis=1)
    statuts = tableau["Statut"]
    return {
        "lignes": len(tableau),
        "references": int(codes.nunique()),
        "boites": int(pd.to_numeric(tableau["Boîtes"], errors="coerce")
                      .fillna(0).sum()),
        "unites": int(pd.to_numeric(tableau["Total unités"], errors="coerce")
                      .fillna(0).sum()),
        "perimes": int((statuts == STATUT_PERIME).sum()),
        "imminents": int((statuts == STATUT_IMMINENT).sum()),
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


#: L'écriture atomique et le verrou vivent dans ``stockage_partage`` :
#: cette mécanique est partagée avec les autres modules qui écrivent des
#: fichiers, et la dupliquer serait la voir diverger.
_ecrire_atomiquement = stockage_partage.ecrire_atomiquement


def sauver_inventaire(inventaire: pd.DataFrame, chemin: Path) -> None:
    """Écrit l'inventaire sur disque (dates en ISO, séparateur ``;``)."""
    tableau = (inventaire_vide() if inventaire is None or inventaire.empty
               else inventaire.reindex(columns=COLONNES_STOCK_FERME).copy())
    for colonne in ("Péremption", "Enregistré le"):
        tableau[colonne] = tableau[colonne].map(_date_iso)
    _ecrire_atomiquement(tableau, chemin)


# ---------------------------------------------------------------------------
# Écriture partagée entre plusieurs postes
# ---------------------------------------------------------------------------
#
# La mécanique est dans ``stockage_partage`` — verrou de fichier, écriture
# atomique, empreinte relevée sous le verrou. Ces noms restent exposés ici
# parce que c'est par ce module que l'interface du stock interne y accède.

DELAI_VERROU_S = stockage_partage.DELAI_VERROU_S
AGE_VERROU_ABANDONNE_S = stockage_partage.AGE_VERROU_ABANDONNE_S
VerrouIndisponible = stockage_partage.VerrouIndisponible
verrou_fichier = stockage_partage.verrou_fichier
empreinte_fichier = stockage_partage.empreinte_fichier
Ecriture = stockage_partage.Ecriture


def appliquer_a_l_inventaire(chemin: Path, mouvement,
                             delai_s: float = DELAI_VERROU_S) -> Ecriture:
    """Relit l'inventaire, applique ``mouvement``, réécrit — sous verrou.

    ``mouvement`` reçoit l'inventaire **tel qu'il est sur le disque à cet
    instant** et rend celui à enregistrer, ou ``None`` pour ne rien écrire.
    C'est la seule façon d'ajouter une boîte sans effacer celle qu'un autre
    poste vient d'ajouter : on n'écrase pas, on ajoute à ce qui est là.
    """
    return stockage_partage.appliquer(
        chemin, charger_inventaire, sauver_inventaire, mouvement, delai_s)


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
        _journal.warning("Inventaire du stock interne illisible : %s", chemin)
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
    # Inventaires écrits avant la disparition de la colonne « Dosage » : on
    # le replie dans le nom une fois pour toutes. Sans cette reprise, un lot
    # SANS code CIP serait affiché sous un nom et retrouvé sous un autre —
    # sa sortie ne décrémenterait rien.
    tableau["Nom du produit"] = [
        _nom_avec_dosage(nom, dosage)
        for nom, dosage in zip(tableau["Nom du produit"], tableau["Dosage"])]
    tableau["Dosage"] = ""
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


def importer_repertoire(repertoire: pd.DataFrame, lignes) -> tuple:
    """Charge en bloc des identités produit dans le répertoire.

    Un code-barres ne transporte PAS le nom du médicament : aucun
    identifiant GS1 ne le prévoit. Le nom doit donc venir d'une table
    « code CIP → libellé » — typiquement le catalogue de la pharmacie. Cette
    fonction l'avale d'un coup, pour que les scans suivants n'aient plus
    rien à demander.

    ``lignes`` : itérable de dictionnaires ``{"cip", "nom", "dosage",
    "unites_par_boite"}`` — la fonction ignore d'où ils viennent, ce qui la
    laisse indépendante de tout format de fichier.

    Renvoie ``(repertoire, nb_ajoutes, nb_ignores)``. Une ligne sans code ou
    sans nom est ignorée : elle n'apprendrait rien.
    """
    if repertoire is None or repertoire.empty:
        repertoire = repertoire_vide()
    repertoire = repertoire.reindex(columns=COLONNES_REPERTOIRE).copy()
    repertoire["Code CIP"] = repertoire["Code CIP"].map(
        lambda v: re.sub(r"\D", "", _texte(v)))

    existants = {c: i for i, c in zip(repertoire.index, repertoire["Code CIP"])}
    nouvelles: dict = {}   # cip -> ligne, pour ne pas dupliquer un CIP répété
    ignores = 0
    for ligne in lignes or []:
        cip = re.sub(r"\D", "", _texte(ligne.get("cip")))
        nom = _texte(ligne.get("nom"))
        if not cip or not nom:
            ignores += 1
            continue
        dosage = _texte(ligne.get("dosage"))
        unites = int(pd.to_numeric(pd.Series([ligne.get("unites_par_boite", 0)]),
                                   errors="coerce").fillna(0).astype(int).iloc[0])
        if cip in existants:  # déjà connu : le fichier met à jour l'existant
            i = existants[cip]
            repertoire.at[i, "Nom du produit"] = nom
            if dosage:
                repertoire.at[i, "Dosage"] = dosage
            if unites:
                repertoire.at[i, "Unités par boîte"] = unites
            continue
        # Un même CIP peut revenir plusieurs fois dans un catalogue : la
        # dernière ligne lue fait foi, sans créer de doublon.
        precedente = nouvelles.get(cip, {})
        nouvelles[cip] = {
            "Code CIP": cip, "Nom du produit": nom,
            "Dosage": dosage or precedente.get("Dosage", ""),
            "Unités par boîte": unites or precedente.get("Unités par boîte", 0)}

    if nouvelles:
        repertoire = pd.concat(
            [repertoire, pd.DataFrame(list(nouvelles.values()),
                                      columns=COLONNES_REPERTOIRE)],
            ignore_index=True)
    return repertoire.reset_index(drop=True), len(nouvelles), ignores


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
    _ecrire_atomiquement(tableau, Path(chemin))


def appliquer_au_repertoire(chemin: Path, mouvement,
                            delai_s: float = DELAI_VERROU_S) -> Ecriture:
    """Même précaution que pour l'inventaire, pour les produits mémorisés.

    Deux postes qui découvrent chacun un produit inconnu au même moment
    doivent en garder DEUX : sans cela le second réenregistre le répertoire
    qu'il avait en mémoire, et le produit du premier n'est plus reconnu.
    """
    return stockage_partage.appliquer(
        chemin, charger_repertoire, sauver_repertoire, mouvement, delai_s)


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
COLONNES_IMPRESSION = ["Statut", "Nom du produit", "Code CIP",
                       "Boîtes", "Unités", "Péremption", "Lot"]

#: Statuts retenus par le filtre « à traiter » : ce qui exige une action.
STATUTS_A_TRAITER = (STATUT_PERIME, STATUT_IMMINENT)


def filtrer_inventaire(inventaire: pd.DataFrame, recherche: str = "",
                       statuts: Optional[Sequence[str]] = None,
                       aujourdhui: Optional[date] = None,
                       tri: str = TRI_PEREMPTION) -> pd.DataFrame:
    """Vue filtrée de l'inventaire : recherche libre et paliers retenus.

    La recherche porte sur le nom, le dosage, le code CIP et le n° de lot —
    au comptoir on cherche indifféremment par l'un ou l'autre. Elle
    n'interprète PAS son terme comme une expression régulière : « (30) » est
    un texte, pas un groupe de capture.

    ``statuts`` restreint aux paliers de péremption voulus ; c'est ce qui
    permet d'imprimer la seule liste de retrait plutôt que tout le stock.

    Le résultat a la forme d'un INVENTAIRE (mêmes colonnes qu'en entrée) :
    il se réinjecte donc aussi bien dans l'affichage que dans les exports.
    L'ordre demandé est conservé — un filtre ne doit pas rebattre les
    lignes sous les yeux de qui vient de choisir son classement.
    """
    tableau = inventaire_affichable(inventaire, aujourdhui, tri)
    if tableau.empty:
        return inventaire_vide()
    terme = " ".join(str(recherche or "").split()).upper()
    if terme:
        # Le dosage est fondu dans le nom : le chercher séparément
        # n'apporterait rien, il est déjà couvert.
        colonnes = ("Nom du produit", "Code CIP", "Lot")
        garde = None
        for colonne in colonnes:
            trouve = tableau[colonne].map(
                lambda v: terme in _texte(v).upper())
            garde = trouve if garde is None else (garde | trouve)
        tableau = tableau[garde]
    if statuts:
        tableau = tableau[tableau["Statut"].isin(list(statuts))]
    return tableau.reindex(columns=COLONNES_STOCK_FERME).reset_index(drop=True)


def _tableau_impression(inventaire: pd.DataFrame,
                        aujourdhui: Optional[date] = None,
                        tri: str = TRI_PEREMPTION) -> pd.DataFrame:
    tableau = inventaire_affichable(inventaire, aujourdhui, tri)
    if tableau.empty:
        return pd.DataFrame(columns=COLONNES_IMPRESSION)
    sortie = pd.DataFrame({
        "Statut": tableau["Statut"],
        "Nom du produit": tableau["Nom du produit"],
        "Code CIP": tableau["Code CIP"],
        "Boîtes": tableau["Boîtes"],
        "Unités": tableau["Total unités"],
        "Péremption": tableau["Péremption"].map(
            lambda p: f"{p:%d/%m/%Y}" if p else ""),
        "Lot": tableau["Lot"],
    })
    return sortie.reindex(columns=COLONNES_IMPRESSION)


def exporter_csv(inventaire: pd.DataFrame,
                 aujourdhui: Optional[date] = None,
                 tri: str = TRI_PEREMPTION) -> bytes:
    """Liste de stock en CSV (``;`` et BOM : Excel l'ouvre sans réglage)."""
    tampon = io.StringIO()
    _tableau_impression(inventaire, aujourdhui, tri).to_csv(
        tampon, index=False, sep=";", quoting=csv.QUOTE_MINIMAL)
    return tampon.getvalue().encode("utf-8-sig")


#: Teintes de fond des lignes imprimées, par statut de péremption.
_COULEURS_PDF = {
    STATUT_PERIME: (0.94, 0.72, 0.72),
    STATUT_IMMINENT: (0.97, 0.80, 0.76),
    STATUT_CRITIQUE: (0.99, 0.88, 0.76),
    STATUT_VIGILANCE: (1.00, 0.94, 0.75),
}

#: Les polices PDF standard n'ont pas de glyphe pour les émojis — à
#: l'impression, le statut est donc écrit en toutes lettres. La couleur de
#: fond n'est qu'un renfort : la liste reste lisible imprimée en noir et
#: blanc.
_STATUT_PDF = {
    STATUT_PERIME: "PÉRIMÉ",
    STATUT_IMMINENT: "< 1 mois",
    STATUT_CRITIQUE: "< 3 mois",
    STATUT_VIGILANCE: "< 6 mois",
    STATUT_OK: "OK",
    STATUT_INCONNU: "sans date",
}

#: Même raison pour le classement : la flèche « → » de ``TRI_NOM`` n'existe
#: pas dans les polices PDF standard et s'imprimerait en pavé noir.
_TRI_PDF = {TRI_PEREMPTION: "péremption la plus proche",
            TRI_NOM: "nom du produit (A-Z)"}


def exporter_pdf(inventaire: pd.DataFrame, titre: str = "Stock interne",
                 aujourdhui: Optional[date] = None,
                 tri: str = TRI_PEREMPTION) -> bytes:
    """Liste de stock en PDF, prête à imprimer pour le contrôle physique.

    Format paysage, en-tête répété à chaque page, lignes teintées selon
    l'urgence de la péremption. Lève ``ValueError`` avec un message clair si
    ReportLab n'est pas installé — l'export CSV, lui, reste disponible.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer,
                                        Table, TableStyle)
        from xml.sax.saxutils import escape
    except ImportError:
        raise ValueError("Impression PDF indisponible : lancez "
                         "« pip install reportlab » puis réessayez.")

    aujourdhui = aujourdhui or date.today()
    tableau = _tableau_impression(inventaire, aujourdhui, tri)
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
            f"moins d'un mois : {resume['imminents']} · "
            f"moins de 3 mois : {resume['critiques']}<br/>"
            # La liste papier se parcourt devant l'armoire : savoir dans
            # quel ordre elle est rangée évite de la relire en entier.
            f"Classement : {_TRI_PDF.get(tri, _TRI_PDF[TRI_PEREMPTION])}",
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

    # Les libellés de médicaments dépassent souvent la largeur de colonne
    # (« PARACETAMOL BIOGARAN CONSEIL 1000 mg comprimé pelliculé sécable »).
    # Une chaîne brute déborderait sur les colonnes voisines et rendrait la
    # ligne illisible : les colonnes de texte libre passent en paragraphes,
    # qui se replient sur plusieurs lignes.
    style_cellule = ParagraphStyle("cellule", fontName="Helvetica",
                                   fontSize=7.5, leading=9)
    repliees = ("Nom du produit", "Lot")
    for colonne in repliees:
        imprime[colonne] = imprime[colonne].map(
            lambda v: Paragraph(escape(v), style_cellule))
    donnees = [list(imprime.columns)] + imprime.values.tolist()
    # La colonne du nom récupère la place du dosage, qui y est désormais
    # inclus : les dénominations officielles sont longues.
    largeurs = [22 * mm, 96 * mm, 30 * mm, 18 * mm, 18 * mm, 26 * mm,
                32 * mm]
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
