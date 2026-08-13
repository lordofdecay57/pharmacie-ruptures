# -*- coding: utf-8 -*-
"""Installer la nouvelle version depuis l'application elle-même.

Raison d'être : le geste le plus courant — double-cliquer sur l'icône du
Bureau — est précisément celui qui **ne peut jamais** mettre à jour.
``lancer.bat`` appelle bien ``maj_auto``, mais celui-ci se reporte tant que
l'application répond sur le port 8501… et personne ne ferme l'application
avant de cliquer sur son icône. Le bandeau annonçait donc une nouvelle
version sans donner le moyen de la prendre.

Ce module lance le script de mise à jour **détaché**, dans sa propre
fenêtre. C'est indispensable : ce script commence par arrêter le processus
qui écoute sur 8501 — c'est-à-dire nous. Un enfant ordinaire mourrait avec
nous avant d'avoir rien copié.

Écrit en bibliothèque standard uniquement, et **sans Streamlit** : tout est
testable hors interface, y compris sur une machine qui n'est pas Windows.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

#: Sur un poste isolé : relance l'application pour ce poste.
NOM_SCRIPT_POSTE = "mettre-a-jour.bat"
#: Sur un serveur : relance en annonçant explicitement qu'on écoute le
#: réseau, journalise, et sait rendre la main à la tâche de nuit.
#: `mettre-a-jour.bat` marcherait aussi — Streamlit écoute par défaut sur
#: toutes les cartes — mais il relance avec les réglages d'un poste isolé :
#: navigateur ouvert sur l'écran du serveur, icône du mauvais lanceur posée
#: sur son Bureau, et rien dans le journal.
NOM_SCRIPT_SERVEUR = "mettre-a-jour-serveur.bat"

#: Combien de temps l'application met à revenir, à annoncer avant le clic.
#: Sans cet avertissement, la perte de connexion du navigateur passe pour
#: une panne — et quelqu'un rappelle la pharmacie.
DELAI_RETOUR = "une minute"


def sur_windows(nom_systeme: str = os.name) -> bool:
    """Les scripts de mise à jour sont des ``.bat``.

    Ailleurs, mieux vaut ne rien proposer du tout qu'un bouton qui échoue :
    l'application tourne aussi sur Mac pour la mise au point.
    """
    return nom_systeme == "nt"


def script_a_lancer(dossier: Path, mode_serveur: bool = False) -> Optional[Path]:
    """Le script de mise à jour qui convient à cette installation.

    ``None`` s'il manque : sur une installation ancienne, le script serveur
    peut ne jamais avoir été livré (les scripts de mise à jour ne sont
    jamais remplacés par une mise à jour — ils sont en cours d'exécution
    pendant la copie).
    """
    dossier = Path(dossier)
    nom = NOM_SCRIPT_SERVEUR if mode_serveur else NOM_SCRIPT_POSTE
    chemin = dossier / nom
    return chemin if chemin.is_file() else None


def _drapeaux_detachement() -> int:
    """Nouvelle console, nouveau groupe de processus.

    Les deux comptent. La console propre rend la mise à jour **visible** —
    on voit défiler ce qui se passe au lieu de fixer une page morte. Le
    groupe séparé évite qu'un Ctrl+C dans la fenêtre de l'application
    n'interrompe la mise à jour en pleine copie de fichiers.

    Les constantes n'existent que sous Windows : ailleurs, zéro, et les
    tests tournent quand même.
    """
    return (getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))


def lancer(dossier: Path, mode_serveur: bool = False,
           demarrer=subprocess.Popen) -> tuple:
    """Démarre la mise à jour. Renvoie ``(succes, message)``.

    Aucun appel ne lève : un bouton d'aide qui fait tomber l'application
    serait pire que pas de bouton du tout. Chaque échec est rendu en
    français, avec la marche à suivre à la main.
    """
    dossier = Path(dossier)
    script = script_a_lancer(dossier, mode_serveur)
    if script is None:
        nom = NOM_SCRIPT_SERVEUR if mode_serveur else NOM_SCRIPT_POSTE
        return False, (
            f"« {nom} » est introuvable dans {dossier}. Mettez à jour à la "
            "main : ouvrez ce dossier et double-cliquez sur le script de "
            "mise à jour.")

    try:
        demarrer([str(script)], cwd=str(dossier),
                 creationflags=_drapeaux_detachement(), close_fds=True)
    except Exception as erreur:              # script interdit, droits, etc.
        return False, (
            f"Le lancement a échoué ({erreur}). Mettez à jour à la main : "
            f"ouvrez le dossier de l'application et double-cliquez sur "
            f"« {script.name} ».")

    quoi = "Le serveur redémarre" if mode_serveur else "L'application redémarre"
    return True, (
        f"Mise à jour démarrée dans une nouvelle fenêtre. {quoi} : cette "
        f"page va se recharger toute seule d'ici {DELAI_RETOUR}. Ne fermez "
        "pas la fenêtre noire qui vient de s'ouvrir.")
