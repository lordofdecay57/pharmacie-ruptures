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
COLONNES_BASE = ["Code CIP", "Nom du produit"]

#: Position des champs utiles dans les fichiers officiels (séparés par des
#: tabulations, sans ligne d'en-tête).
_COL_CIS_DENOMINATION = 1      # dans CIS_bdpm.txt
_COL_CIP7 = 1                  # dans CIS_CIP_bdpm.txt
_COL_CIP13 = 6                 # idem

_DELAI_RESEAU_S = 60


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
        for position in (_COL_CIP13, _COL_CIP7):
            code = "".join(c for c in champs[position] if c.isdigit())
            if code and code not in vus:
                vus.add(code)
                lignes.append({"Code CIP": code, "Nom du produit": nom})
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
    return {"existe": True, "lignes": len(table),
            "date": horodatage.date()}


def anciennete_jours(info: dict, aujourdhui: Optional[date] = None
                     ) -> Optional[int]:
    """Âge de la base en jours (``None`` si elle n'est pas installée)."""
    if not info.get("existe") or info.get("date") is None:
        return None
    return ((aujourdhui or date.today()) - info["date"]).days
