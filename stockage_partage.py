# -*- coding: utf-8 -*-
"""Écrire un fichier partagé entre plusieurs postes, sans rien perdre.

Plusieurs comptoirs peuvent travailler en même temps sur la même
application, installée sur un serveur. Sans précaution, chacun réécrit le
fichier entier depuis la version qu'il avait en mémoire à l'ouverture de sa
page : la ligne enregistrée par le poste d'à côté disparaît, sans message.
Le remède tient en deux règles — on ne réécrit JAMAIS une photo, on relit
puis on applique le mouvement ; et on le fait sous verrou, pour que deux
postes ne se croisent pas.

Ce module ne connaît rien au métier : ni inventaire, ni patients. Il est
partagé par les modules qui écrivent des fichiers, précisément pour que
cette mécanique délicate n'existe qu'à un seul endroit. La dupliquer serait
la voir diverger, et une divergence ici perd des données.

Bibliothèque standard et pandas seulement : aucun module du projet.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

import pandas as pd

_journal = logging.getLogger("pharmacie.stockage")

#: Attente maximale du verrou. Au-delà on renonce plutôt que de bloquer le
#: comptoir : une erreur visible vaut mieux qu'un écran figé.
DELAI_VERROU_S = 10.0
#: Un verrou plus vieux que cela vient d'un poste qui a planté ou a été
#: éteint pendant l'écriture : on le reprend.
AGE_VERROU_ABANDONNE_S = 30.0
_ATTENTE_VERROU_S = 0.05


class VerrouIndisponible(RuntimeError):
    """Un autre poste écrit depuis trop longtemps."""


def ecrire_atomiquement(tableau: pd.DataFrame, chemin: Path) -> None:
    """Écrit à côté, puis remplace d'un bloc.

    Une écriture directe laisse le fichier à moitié rempli si le poste
    s'éteint au mauvais moment — et ces fichiers n'ont pas de seconde
    copie. ``os.replace`` est atomique : le fichier passe d'une version
    complète à l'autre, jamais par un entre-deux.
    """
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    # Nom unique par PROCESSUS **et par fil** : le serveur traite chaque
    # poste dans son propre fil, et deux fichiers de travail homonymes se
    # voleraient mutuellement leur contenu à mi-écriture.
    provisoire = chemin.with_name(
        f"{chemin.name}.{os.getpid()}-{threading.get_ident()}.tmp")
    try:
        tableau.to_csv(provisoire, index=False, sep=";",
                       encoding="utf-8-sig")
        os.replace(provisoire, chemin)
    finally:
        if provisoire.exists():
            try:
                provisoire.unlink()
            except OSError:                       # pragma: no cover
                pass


@contextmanager
def verrou_fichier(chemin: Path, delai_s: float = DELAI_VERROU_S):
    """Empêche deux postes d'écrire le même fichier en même temps.

    Le verrou est un fichier créé en mode « exclusif » : sa création est
    atomique, y compris sur un dossier partagé en réseau — c'est ce qui la
    rend préférable aux verrous du système, dont le comportement sur un
    partage Windows n'est pas garanti.
    """
    verrou = Path(chemin).with_name(Path(chemin).name + ".verrou")
    verrou.parent.mkdir(parents=True, exist_ok=True)
    fin = time.monotonic() + delai_s
    descripteur = None
    while descripteur is None:
        try:
            descripteur = os.open(verrou, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                abandonne = (time.time() - verrou.stat().st_mtime
                             > AGE_VERROU_ABANDONNE_S)
            except OSError:                       # il vient de disparaître
                abandonne = False
            if abandonne:
                _journal.warning("Verrou abandonné repris : %s", verrou)
                try:
                    verrou.unlink()
                except OSError:                   # pragma: no cover
                    pass
                continue
            if time.monotonic() > fin:
                raise VerrouIndisponible(
                    f"Un autre poste écrit encore dans {Path(chemin).name}.")
            time.sleep(_ATTENTE_VERROU_S)
    try:
        os.write(descripteur, str(os.getpid()).encode())
        yield
    finally:
        os.close(descripteur)
        try:
            verrou.unlink()
        except OSError:                           # pragma: no cover
            pass


def empreinte_fichier(chemin: Path) -> tuple:
    """Signature bon marché d'un fichier : (date de modification, taille).

    Sert à savoir si un AUTRE poste a écrit depuis notre dernière lecture,
    sans relire le fichier à chaque interaction.
    """
    try:
        etat = Path(chemin).stat()
    except OSError:
        return (0, 0)
    return (etat.st_mtime_ns, etat.st_size)


class Ecriture(NamedTuple):
    """Ce qui a été écrit, et l'empreinte du fichier au même instant.

    Les deux voyagent ensemble parce qu'ils doivent être relevés **sous le
    même verrou**. Prendre l'empreinte après coup ouvre une fenêtre : un
    autre poste écrit entre-temps, on retient SON empreinte avec NOTRE
    tableau, et le poste se croit à jour alors qu'il ne l'est pas — l'écran
    reste en retard, et une correction du tableau effacerait le travail du
    voisin sans que rien ne le signale.
    """
    tableau: pd.DataFrame
    empreinte: tuple


def appliquer(chemin: Path, charger, sauver, mouvement,
              delai_s: float = DELAI_VERROU_S) -> Ecriture:
    """Relit le fichier, applique ``mouvement``, réécrit — sous verrou.

    ``mouvement`` reçoit le tableau **tel qu'il est sur le disque à cet
    instant** et rend celui à enregistrer, ou ``None`` pour ne rien écrire.
    C'est la seule façon d'ajouter une ligne sans effacer celle qu'un autre
    poste vient d'ajouter : on n'écrase pas, on ajoute à ce qui est là.

    ``charger`` et ``sauver`` sont fournis par le module métier : ce module
    ne sait pas ce que contient le fichier, et n'a pas à le savoir.
    """
    chemin = Path(chemin)
    with verrou_fichier(chemin, delai_s):
        tableau = charger(chemin)
        nouveau = mouvement(tableau)
        if nouveau is None:
            return Ecriture(tableau, empreinte_fichier(chemin))
        sauver(nouveau, chemin)
        return Ecriture(nouveau, empreinte_fichier(chemin))
