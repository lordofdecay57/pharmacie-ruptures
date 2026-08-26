# -*- coding: utf-8 -*-
"""Qui se sert du dossier en ce moment ?

Quand le dossier de l'application est posé sur un partage, chaque poste
lance **son propre** Streamlit sur les **mêmes** fichiers. La mise à jour
automatique vérifiait qu'aucune application ne tournait — mais sur
``127.0.0.1``, c'est-à-dire chez elle seule. Un poste qui démarrait à
08h05 pouvait donc remplacer le code sous la session du comptoir voisin,
en pleine dispensation : Streamlit y recharge ses fichiers à chaud, et
l'écran part en erreur au milieu d'un scan.

Le principe tient en deux gestes : chaque lancement dépose un marqueur à
son nom dans le dossier partagé, et le retire en partant. La mise à jour
ne touche à rien tant qu'il en reste un.

Un poste éteint brutalement laisse son marqueur derrière lui. C'est
pourquoi il **périme** : passé une journée de travail, il ne bloque plus
rien. Sans cela, une seule coupure de courant suffirait à figer la
pharmacie sur sa version pour toujours — et personne ne saurait pourquoi.

Rien ici ne lève : ce module tourne au démarrage d'un poste, avant que
quiconque puisse lire un message d'erreur. Un marqueur qu'on n'arrive pas
à écrire ne doit pas empêcher l'application de s'ouvrir.

Bibliothèque standard uniquement, aucun module du projet : il est appelé
aussi bien par ``maj_auto.py`` que par les scripts de lancement.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import socket
import sys
import time
from pathlib import Path
from typing import List, Optional

#: Sous-dossier des marqueurs. Le point le range hors de vue dans
#: l'Explorateur, à côté des autres fichiers de service.
DOSSIER_MARQUEURS = ".postes-actifs"

#: Au-delà, un marqueur est réputé abandonné. Une journée de travail :
#: assez long pour couvrir une session ouverte de 8 h à 19 h sans jamais
#: gêner, assez court pour qu'un poste débranché ne bloque pas le
#: lendemain matin.
DUREE_MAX_H = 16.0


def nom_du_poste() -> str:
    """Nom de cette machine, tel qu'il apparaîtra dans les messages.

    Trois sources par ordre de fiabilité sous Windows, puis un repli :
    le message « utilisé par POSTE-COMPTOIR-2 » ne vaut que si le nom
    désigne vraiment quelqu'un.
    """
    for brut in (os.environ.get("COMPUTERNAME"), platform.node(),
                 socket.gethostname()):
        propre = _assainir(brut or "")
        if propre:
            return propre
    return "poste"


def _assainir(nom: str) -> str:
    """Un nom de machine devient un nom de fichier sûr.

    Le nom vient de l'environnement : il sert à fabriquer un chemin, et
    un « .. » ou un séparateur y écrirait ailleurs que dans le dossier
    prévu.
    """
    propre = re.sub(r"[^A-Za-z0-9._-]", "-", str(nom).strip())
    return propre.strip(".-")[:60]


def dossier_marqueurs(dossier: Path) -> Path:
    return Path(dossier) / DOSSIER_MARQUEURS


def marqueur(dossier: Path, poste: Optional[str] = None) -> Path:
    return dossier_marqueurs(dossier) / f"{_assainir(poste or nom_du_poste())}"


def entrer(dossier: Path, poste: Optional[str] = None) -> bool:
    """Signale que ce poste ouvre l'application. Ne lève jamais."""
    cible = marqueur(dossier, poste)
    try:
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
        return True
    except OSError:
        # Partage en lecture seule, disque plein, réseau coupé : tant pis
        # pour la protection, mais l'application doit s'ouvrir.
        return False


def sortir(dossier: Path, poste: Optional[str] = None) -> bool:
    """Signale que ce poste a refermé l'application. Ne lève jamais."""
    try:
        marqueur(dossier, poste).unlink()
        return True
    except OSError:
        return False


def postes_actifs(dossier: Path, maintenant: Optional[float] = None,
                  duree_max_h: float = DUREE_MAX_H) -> List[str]:
    """Noms des postes dont le marqueur est encore valide, triés.

    On lit la **date du fichier**, pas son contenu : elle est posée par le
    système au moment de l'écriture, et ne peut pas mentir sur l'heure
    d'un poste mal réglé.
    """
    limite = (time.time() if maintenant is None else maintenant) \
        - duree_max_h * 3600
    trouves = []
    try:
        fichiers = list(dossier_marqueurs(dossier).iterdir())
    except OSError:
        return []
    for fichier in fichiers:
        try:
            if fichier.is_file() and fichier.stat().st_mtime >= limite:
                trouves.append(fichier.name)
        except OSError:
            continue
    return sorted(trouves)


def purger(dossier: Path, maintenant: Optional[float] = None,
           duree_max_h: float = DUREE_MAX_H) -> int:
    """Efface les marqueurs périmés. Renvoie le nombre effacé.

    Un poste débranché laisse le sien : sans ce ménage, le dossier
    accumulerait des noms de machines qui n'existent plus, et le jour où
    quelqu'un l'ouvrirait il n'y comprendrait rien.
    """
    limite = (time.time() if maintenant is None else maintenant) \
        - duree_max_h * 3600
    efface = 0
    try:
        fichiers = list(dossier_marqueurs(dossier).iterdir())
    except OSError:
        return 0
    for fichier in fichiers:
        try:
            if fichier.is_file() and fichier.stat().st_mtime < limite:
                fichier.unlink()
                efface += 1
        except OSError:
            continue
    return efface


def main(argv=None) -> int:
    """Appelé par les scripts de lancement, autour de Streamlit."""
    analyseur = argparse.ArgumentParser(
        description="Marque ce poste comme utilisant le dossier partagé.")
    analyseur.add_argument("--dossier", default=str(Path(__file__).parent))
    groupe = analyseur.add_mutually_exclusive_group(required=True)
    groupe.add_argument("--entrer", action="store_true")
    groupe.add_argument("--sortir", action="store_true")
    groupe.add_argument("--lister", action="store_true")
    arguments = analyseur.parse_args(argv)

    dossier = Path(arguments.dossier)
    if arguments.entrer:
        purger(dossier)
        entrer(dossier)
    elif arguments.sortir:
        sortir(dossier)
    else:
        for nom in postes_actifs(dossier):
            print(nom)
    # Toujours 0 : un marqueur manqué ne doit pas faire echouer le
    # lancement du script qui l'appelle.
    return 0


if __name__ == "__main__":          # pragma: no cover
    sys.exit(main())
