# -*- coding: utf-8 -*-
"""Base publique des médicaments — identification d'un produit par son CIP.

Un code-barres, Data Matrix compris, ne transporte **pas** le nom du
médicament : aucun identifiant GS1 ne le prévoit. Il ne donne que le code
CIP. Pour afficher un nom au moment du scan, il faut donc une table
« code CIP → dénomination ».

Ce module la construit à partir de la **Base de données publique des
médicaments** (ANSM / ministère de la Santé), en libre téléchargement :

- ``CIS_bdpm.txt``     : code CIS → dénomination du médicament ;
- ``CIS_CIP_bdpm.txt`` : code CIS → CIP7 et CIP13 de chaque présentation.

Les deux fichiers se recoupent sur le code CIS. Le résultat est enregistré
sur le poste : le téléchargement n'a lieu que lorsqu'on le demande, et
l'identification fonctionne ensuite **hors ligne**.

ISOLATION : ce module ne connaît ni le cadencier, ni les ruptures, ni le
stock fermé. Il ne sait faire qu'une chose — répondre « quel médicament
porte ce code ? ».
"""

from __future__ import annotations

import logging
import re
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

_journal = logging.getLogger("pharmacie.base_medicaments")

#: Fichiers officiels de la base publique des médicaments.
URL_DENOMINATIONS = ("https://base-donnees-publique.medicaments.gouv.fr"
                     "/download/file/CIS_bdpm.txt")
URL_PRESENTATIONS = ("https://base-donnees-publique.medicaments.gouv.fr"
                     "/download/file/CIS_CIP_bdpm.txt")

#: Colonnes de la table enregistrée sur le poste.
#:
#: « Présentation » est le libellé officiel du conditionnement — « plaquette
#: de 30 comprimé(s) », « flacon de 90 gélule(s) ». C'est ce qui distingue
#: deux boîtes du même médicament au même dosage, et ce qui donne le nombre
#: d'unités par boîte.
COLONNES_BASE = ["Code CIP", "Nom du produit", "Présentation"]

#: Position des champs utiles dans les fichiers officiels (séparés par des
#: tabulations, sans ligne d'en-tête).
_COL_CIS_DENOMINATION = 1      # dans CIS_bdpm.txt
_COL_CIP7 = 1                  # dans CIS_CIP_bdpm.txt
_COL_PRESENTATION = 2          # idem
_COL_CIP13 = 6                 # idem

_DELAI_RESEAU_S = 60

#: Formes **dénombrables** : celles dont on peut dire « il en reste 12 ».
#: Les millilitres, grammes et unités internationales en sont exclus — ils
#: mesurent un contenu, ils ne le comptent pas.
_FORMES_DENOMBRABLES = (
    "comprime", "gelule", "capsule", "sachet", "suppositoire", "ovule",
    "pastille", "gomme", "lyophilisat", "dose", "implant", "film",
    "emplatre", "anneau", "pilule", "granule", "unite",
)
_MOTIF_UNITES = re.compile(
    r"\bde\s+(\d+)\s*(?:" + "|".join(_FORMES_DENOMBRABLES) + r")s?\b")
#: « 3 pilulier(s) … de 30 comprimé(s) » : la boîte en contient 90. Sans ce
#: multiplicateur de tête, on lirait 30 — et « 100 plaquettes de 1 gélule »
#: donnerait 1 au lieu de 100.
_MOTIF_MULTIPLICATEUR = re.compile(r"^(\d+)\s+\D")
#: Garde-fou : au-delà, c'est que la lecture a dérapé.
_UNITES_MAX = 5000


def _aplatir(texte) -> str:
    """Minuscules sans accent : « ÉLAVIL » et « elavil » doivent se trouver."""
    plat = unicodedata.normalize("NFKD", str(texte or "").lower())
    return " ".join("".join(c for c in plat
                            if not unicodedata.combining(c)).split())


#: Toutes les doses ramenées au milligramme. La base officielle écrit
#: « DOLIPRANE 1000 mg » ; à l'officine on dit « Doliprane 1 g ». Sans cette
#: conversion, la recherche ne rend rien — et rien n'est plus déroutant
#: qu'un écran qui ne réagit pas à un nom parfaitement exact.
_UNITES_DOSE = {
    "g": 1000.0, "gramme": 1000.0, "grammes": 1000.0,
    "mg": 1.0, "milligramme": 1.0, "milligrammes": 1.0,
    "µg": 0.001, "μg": 0.001, "ug": 0.001, "mcg": 0.001,
    "microgramme": 0.001, "microgrammes": 0.001,
}
_MOTIF_DOSE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(microgrammes?|milligrammes?|grammes?|mcg|[µμ]g|ug|mg|g)\b")


def _en_milligrammes(trouve) -> str:
    valeur = float(trouve.group(1).replace(",", "."))
    return f"{valeur * _UNITES_DOSE[trouve.group(2)]:g}mg"


def _cle_recherche(texte) -> str:
    """Forme comparable d'un libellé : sans accent, sans casse, doses en mg.

    Appliquée des DEUX côtés — à la base comme à ce qui est tapé — pour que
    « 1 g » et « 1000 mg » se rencontrent. Idempotente : « 1000mg » repasse
    par la fonction sans changer.
    """
    return _MOTIF_DOSE.sub(_en_milligrammes, _aplatir(texte))


def unites_par_boite(presentation: str) -> int:
    """Nombre d'unités que contient une boîte, ou ``0`` si indécidable.

    Lu dans le libellé officiel du conditionnement. En cas de doute — deux
    nombres possibles, forme non dénombrable, libellé alambiqué — on rend
    ``0`` plutôt qu'une valeur inventée : une quantité fausse sur un stock
    fermé est pire qu'une case vide, elle ne se remarque pas.
    """
    texte = _aplatir(presentation)
    valeurs = {int(m.group(1)) for m in _MOTIF_UNITES.finditer(texte)}
    if len(valeurs) != 1:
        return 0
    total = valeurs.pop()
    debut = _MOTIF_MULTIPLICATEUR.match(texte)
    if debut:
        total *= int(debut.group(1))
    return total if 0 < total <= _UNITES_MAX else 0


def decoder(donnees: bytes) -> str:
    """Décode un fichier officiel.

    Les deux fichiers n'ont PAS le même encodage — ``CIS_bdpm.txt`` est en
    ISO-8859-1, ``CIS_CIP_bdpm.txt`` en UTF-8 — et rien ne garantit que cela
    ne changera pas. On essaie donc l'UTF-8 puis on se rabat.
    """
    try:
        return donnees.decode("utf-8")
    except UnicodeDecodeError:
        return donnees.decode("latin-1", errors="replace")


def construire_table(texte_denominations: str,
                     texte_presentations: str) -> pd.DataFrame:
    """Recoupe les deux fichiers officiels en une table CIP → dénomination.

    Les CIP13 **et** les CIP7 sont indexés : les boîtes anciennes ne portent
    parfois que l'ancien code à 7 chiffres.
    """
    noms: dict = {}
    for ligne in texte_denominations.splitlines():
        champs = ligne.split("\t")
        if len(champs) > _COL_CIS_DENOMINATION:
            cis = champs[0].strip()
            nom = " ".join(champs[_COL_CIS_DENOMINATION].split())
            if cis and nom:
                noms[cis] = nom

    lignes = []
    vus = set()
    for ligne in texte_presentations.splitlines():
        champs = ligne.split("\t")
        if len(champs) <= _COL_CIP13:
            continue
        nom = noms.get(champs[0].strip())
        if not nom:
            continue
        presentation = " ".join(champs[_COL_PRESENTATION].split())
        for position in (_COL_CIP13, _COL_CIP7):
            code = "".join(c for c in champs[position] if c.isdigit())
            if code and code not in vus:
                vus.add(code)
                lignes.append({"Code CIP": code, "Nom du produit": nom,
                               "Présentation": presentation})
    return pd.DataFrame(lignes, columns=COLONNES_BASE)


def telecharger_table(delai_s: float = _DELAI_RESEAU_S) -> pd.DataFrame:
    """Télécharge les deux fichiers officiels et en construit la table.

    Lève ``ValueError`` avec un message lisible si le réseau ne répond pas :
    l'identification par CIP est un confort, son indisponibilité ne doit
    jamais empêcher de tenir l'inventaire.
    """
    fichiers = []
    for url in (URL_DENOMINATIONS, URL_PRESENTATIONS):
        try:
            with urllib.request.urlopen(url, timeout=delai_s) as reponse:
                fichiers.append(decoder(reponse.read()))
        except (urllib.error.URLError, OSError) as e:
            raise ValueError(
                "Base des médicaments injoignable — vérifiez la connexion "
                f"Internet du poste. ({e})")
    table = construire_table(*fichiers)
    if table.empty:
        raise ValueError("Base des médicaments téléchargée mais illisible : "
                         "le format des fichiers officiels a peut-être "
                         "changé.")
    return table


# ---------------------------------------------------------------------------
# Conservation sur le poste
# ---------------------------------------------------------------------------

def sauver_table(table: pd.DataFrame, chemin: Path) -> None:
    """Enregistre la table pour que l'identification marche hors ligne."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    table.reindex(columns=COLONNES_BASE).to_csv(
        chemin, index=False, sep=";", encoding="utf-8-sig")


def charger_table(chemin: Path) -> pd.DataFrame:
    """Relit la table enregistrée ; table vide si elle n'existe pas encore.

    Un fichier abîmé ne doit pas empêcher l'ouverture du module : on repart
    d'une table vide, l'ancien fichier reste sur le disque.
    """
    chemin = Path(chemin)
    if not chemin.exists():
        return pd.DataFrame(columns=COLONNES_BASE)
    try:
        table = pd.read_csv(chemin, sep=";", dtype=str,
                            encoding="utf-8-sig").fillna("")
    except Exception:
        _journal.warning("Base des médicaments illisible : %s", chemin)
        return pd.DataFrame(columns=COLONNES_BASE)
    return table.reindex(columns=COLONNES_BASE).fillna("")


def index_par_cip(table: pd.DataFrame) -> dict:
    """Table → dictionnaire code CIP → nom, pour une recherche immédiate."""
    if table is None or table.empty:
        return {}
    return {str(c).strip(): str(n).strip()
            for c, n in zip(table["Code CIP"], table["Nom du produit"])
            if str(c).strip() and str(n).strip()}


def index_par_nom(table: pd.DataFrame) -> list:
    """Table → liste cherchable par nom, une entrée par présentation.

    Chaque médicament figure deux fois dans la table (son CIP13 et son
    ancien CIP7) : on n'en garde qu'une entrée, en préférant le code le plus
    long — c'est le CIP13, celui que portent les boîtes d'aujourd'hui.

    La clé de recherche est calculée une fois pour toutes : la refaire à
    chaque frappe sur 40 000 lignes se sentirait à l'écran.
    """
    if table is None or table.empty:
        return []
    table = table.reindex(columns=COLONNES_BASE).fillna("")
    retenus: dict = {}
    for cip, nom, presentation in zip(table["Code CIP"],
                                      table["Nom du produit"],
                                      table["Présentation"]):
        nom, presentation = str(nom).strip(), str(presentation).strip()
        code = str(cip).strip()
        if not nom or not code:
            continue
        cle = (nom, presentation)
        if cle in retenus and len(retenus[cle]["cip"]) >= len(code):
            continue
        retenus[cle] = {
            "cip": code, "nom": nom, "presentation": presentation,
            "unites_par_boite": unites_par_boite(presentation),
            "_recherche": _cle_recherche(nom),
        }
    return list(retenus.values())


def noms_distincts(index: list) -> list:
    """Dénominations, sans doublon, dans l'ordre alphabétique.

    Destinée à la **saisie assistée** : la liste part telle quelle dans le
    navigateur, qui la filtre à chaque frappe. Les présentations d'un même
    médicament portent la même dénomination — les envoyer toutes
    tripleraient la liste sans rien apprendre tant que le nom n'est pas
    choisi.
    """
    return sorted({e["nom"] for e in (index or []) if e.get("nom")})


def presentations_du_nom(index: list, nom: str) -> list:
    """Présentations d'une dénomination donnée, de la plus petite boîte à la
    plus grande — c'est l'ordre du rayon."""
    exactes = [e for e in (index or []) if e.get("nom") == nom]
    exactes.sort(key=lambda e: (e["unites_par_boite"] or 10 ** 6,
                                e["presentation"]))
    return exactes


#: En dessous, la recherche ramènerait la moitié de la base : on attend que
#: le terme soit assez discriminant pour valoir une liste.
LONGUEUR_RECHERCHE_MINIMALE = 3


def chercher_par_nom(index: list, terme: str, limite: int = 25) -> list:
    """Médicaments dont la dénomination contient TOUS les mots cherchés.

    « doliprane 1000 » doit trouver « DOLIPRANE 1000 mg, comprimé » sans
    exiger l'ordre ni la ponctuation exacts — on tape ce dont on se
    souvient, pas la dénomination officielle.

    Les correspondances qui **commencent** par le premier mot passent
    devant : qui tape « doli » cherche DOLIPRANE, pas un générique dont le
    nom le contient au milieu.
    """
    mots = _cle_recherche(terme).split()
    if not index or not mots:
        return []
    if len("".join(mots)) < LONGUEUR_RECHERCHE_MINIMALE:
        return []
    trouves = [e for e in index
               if all(mot in e["_recherche"] for mot in mots)]
    trouves.sort(key=lambda e: (not e["_recherche"].startswith(mots[0]),
                                e["nom"], e["presentation"]))
    return trouves[:limite]


def preselectionner(index: list, terme: str, limite: int = 25) -> dict:
    """Recherche par nom, en relâchant les mots tant que rien ne sort.

    « Doliprane 1 g effervescent » ne correspond à aucune dénomination
    officielle exacte ; « Doliprane 1 g » en donne quinze. Plutôt que de
    rendre une liste vide — ce qui, à l'écran, ressemble à une application
    qui ne réagit pas — on abandonne les mots par la fin jusqu'à trouver, et
    on dit ce qui a réellement servi.

    Renvoie ``{"resultats", "terme", "elargi"}``.
    """
    mots = _cle_recherche(terme).split()
    complet = list(mots)
    while mots:
        trouves = chercher_par_nom(index, " ".join(mots), limite)
        if trouves:
            return {"resultats": trouves, "terme": " ".join(mots),
                    "elargi": len(mots) < len(complet)}
        mots = mots[:-1]
    return {"resultats": [], "terme": "", "elargi": False}


def cip7_depuis_cip13(cip13: str) -> str:
    """CIP7 contenu dans un CIP13 français, ou ``""``.

    Structure vérifiée sur la base officielle : ``34009`` + CIP7 (7
    chiffres) + clé de contrôle.
    """
    code = "".join(c for c in str(cip13 or "") if c.isdigit())
    return code[5:12] if len(code) == 13 and code.startswith("34009") else ""


def chercher(index: dict, cip: str) -> Optional[str]:
    """Dénomination officielle d'un code CIP, ou ``None`` s'il est inconnu.

    Les deux formes sont indexées, donc la recherche directe suffit presque
    toujours. Le repli par le CIP7 couvre le cas d'une fiche officielle dont
    le CIP13 manquerait.
    """
    if not index:
        return None
    code = "".join(c for c in str(cip or "") if c.isdigit())
    if not code:
        return None
    if code in index:
        return index[code]
    cip7 = cip7_depuis_cip13(code)
    return index.get(cip7) if cip7 else None


def info_base(chemin: Path) -> dict:
    """Ce qu'on peut dire de la base présente sur le poste."""
    chemin = Path(chemin)
    if not chemin.exists():
        return {"existe": False, "lignes": 0, "date": None}
    table = charger_table(chemin)
    horodatage = datetime.fromtimestamp(chemin.stat().st_mtime)
    # Les bases installées avant l'ajout du conditionnement n'ont que deux
    # colonnes : la recherche par nom marche, mais sans présentation ni
    # nombre d'unités. Il faut pouvoir le dire et proposer de la refaire.
    presentations = int((table["Présentation"].astype(str).str.strip() != ""
                         ).sum()) if not table.empty else 0
    return {"existe": True, "lignes": len(table),
            "presentations": presentations, "date": horodatage.date()}


def anciennete_jours(info: dict, aujourdhui: Optional[date] = None
                     ) -> Optional[int]:
    """Âge de la base en jours (``None`` si elle n'est pas installée)."""
    if not info.get("existe") or info.get("date") is None:
        return None
    return ((aujourdhui or date.today()) - info["date"]).days
