# -*- coding: utf-8 -*-
"""Icône de lancement sur le Bureau (Windows).

Le même travail que ``creer-raccourci.bat``, mais appelable **depuis
l'application**. Raison d'être : demander à quelqu'un d'aller chercher un
fichier dans un dossier, puis de le double-cliquer, c'est déjà trop —
d'autant que Windows masque par défaut l'extension « .bat » et qu'un poste
d'officine peut en interdire l'exécution. Un bouton dans l'écran déjà
ouvert ne demande rien de tout cela.

Écrit en bibliothèque standard uniquement, et **sans Streamlit** : tout est
testable hors interface, y compris sur une machine qui n'est pas Windows.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional, Sequence

#: Nom de l'icône telle qu'elle apparaît sur le Bureau. Le MÊME nom et
#: la MÊME image partout : `creer-raccourci.bat` sur un poste autonome,
#: `creer-raccourci-poste.bat` sur un poste relié au serveur, et ce
#: module depuis l'application. Trois chemins pour un seul geste — s'ils
#: divergent, un poste finit avec deux icônes et personne ne sait
#: laquelle ouvre quoi.
NOM_RACCOURCI = "Pilotage pharmacie.lnk"
#: Repli lorsque PowerShell est indisponible : un raccourci Internet, qui
#: n'est que du texte et se laisse écrire sans le moindre outil.
NOM_REPLI = "Pilotage pharmacie.url"

#: Les noms d'avant le renommage. On les efface en posant la nouvelle
#: icône : les laisser, c'est deux icônes côte à côte sur le Bureau,
#: dont une qui pointe peut-être sur une installation supprimée.
ANCIENS_NOMS = ("Pharmacie.lnk", "Pharmacie.url")

NOM_LANCEUR = "lancer.bat"
NOM_ICONE = "pharmacie.ico"

DESCRIPTION = "Pilotage pharmacie - stock, ruptures et stock ferme"

_DELAI_S = 20


def sur_windows(nom_systeme: str = os.name) -> bool:
    """Le raccourci du Bureau n'a de sens que sous Windows.

    Ailleurs, mieux vaut ne rien proposer du tout qu'un bouton qui échoue :
    l'application tourne aussi sur Mac pour la mise au point.
    """
    return nom_systeme == "nt"


def dossiers_bureau(accueil: Optional[Path] = None,
                    environnement: Optional[dict] = None) -> list:
    """Emplacements possibles du Bureau, du plus probable au moins probable.

    Le Bureau est souvent **redirigé** vers OneDrive sur les postes
    d'entreprise : le chemin en dur ``…/Desktop`` pointe alors sur un
    dossier vide que personne ne regarde jamais. On garde les deux, et on
    retient celui qui existe.
    """
    accueil = Path(accueil) if accueil else Path.home()
    environnement = os.environ if environnement is None else environnement
    pistes = []
    for racine in (environnement.get("OneDrive"),
                   environnement.get("OneDriveCommercial")):
        if racine:
            pistes.append(Path(racine) / "Desktop")
    pistes += [accueil / "Desktop", accueil / "Bureau"]
    # Sans doublon, en gardant l'ordre : deux variables d'environnement
    # pointent parfois sur le même dossier.
    vus, uniques = set(), []
    for piste in pistes:
        if str(piste) not in vus:
            vus.add(str(piste))
            uniques.append(piste)
    return uniques


def bureau(accueil: Optional[Path] = None,
           environnement: Optional[dict] = None) -> Optional[Path]:
    """Premier dossier Bureau qui existe réellement, ou ``None``."""
    for piste in dossiers_bureau(accueil, environnement):
        if piste.is_dir():
            return piste
    return None


def raccourci_existant(accueil: Optional[Path] = None,
                       environnement: Optional[dict] = None) -> Optional[Path]:
    """Chemin de l'icône déjà posée sur le Bureau, ou ``None``.

    C'est ce qui permet de ne proposer le bouton **que** lorsqu'il sert :
    une proposition qui reste affichée après avoir été suivie n'est plus
    une aide, c'est du bruit.
    """
    for dossier in dossiers_bureau(accueil, environnement):
        # Les anciens noms comptent : quelqu'un qui a déjà son icône ne
        # doit pas se voir proposer d'en poser une seconde.
        for nom in (NOM_RACCOURCI, NOM_REPLI) + ANCIENS_NOMS:
            if (dossier / nom).is_file():
                return dossier / nom
    return None


def effacer_anciens(bureau_choisi: Path) -> int:
    """Retire les icônes portant l'ancien nom. Ne lève jamais.

    Appelé juste après avoir posé la nouvelle : deux icônes côte à côte,
    dont une qui pointe peut-être sur une installation supprimée, c'est
    la garantie qu'on cliquera un jour la mauvaise.
    """
    efface = 0
    for nom in ANCIENS_NOMS:
        try:
            (Path(bureau_choisi) / nom).unlink()
            efface += 1
        except OSError:
            continue
    return efface


def commande_powershell(dossier: Path, cible_bureau: Path) -> list:
    """Commande créant le vrai raccourci Windows (.lnk).

    Les chemins passent par l'environnement du processus fils plutôt que
    par la ligne de commande : un dossier contenant une apostrophe ou un
    accent casse le meilleur des échappements.
    """
    return [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        "$lien = (New-Object -ComObject WScript.Shell)"
        ".CreateShortcut($env:PHARMA_LIEN); "
        "$lien.TargetPath = $env:PHARMA_CIBLE; "
        "$lien.WorkingDirectory = $env:PHARMA_DOSSIER; "
        "$lien.Description = $env:PHARMA_DESCRIPTION; "
        "if (Test-Path $env:PHARMA_ICONE) "
        "{ $lien.IconLocation = $env:PHARMA_ICONE }; "
        "$lien.Save()",
    ]


def environnement_powershell(dossier: Path, cible_bureau: Path,
                             environnement: Optional[dict] = None) -> dict:
    """Variables lues par la commande ci-dessus."""
    dossier = Path(dossier)
    base = dict(os.environ if environnement is None else environnement)
    base.update({
        "PHARMA_LIEN": str(cible_bureau),
        "PHARMA_CIBLE": str(dossier / NOM_LANCEUR),
        "PHARMA_DOSSIER": str(dossier),
        "PHARMA_ICONE": str(dossier / NOM_ICONE),
        "PHARMA_DESCRIPTION": DESCRIPTION,
    })
    return base


def contenu_url(dossier: Path) -> str:
    """Raccourci Internet de repli, en texte brut.

    ``file:///`` veut des barres obliques : un chemin Windows recopié tel
    quel donnerait un lien mort.
    """
    dossier = Path(dossier)
    cible = str(dossier / NOM_LANCEUR).replace("\\", "/")
    return ("[InternetShortcut]\n"
            f"URL=file:///{cible}\n"
            f"IconFile={dossier / NOM_ICONE}\n"
            "IconIndex=0\n")


def creer(dossier: Path, accueil: Optional[Path] = None,
          environnement: Optional[dict] = None,
          executer=subprocess.run) -> tuple:
    """Pose l'icône sur le Bureau. Renvoie ``(succes, message)``.

    Aucun appel ne lève : un bouton d'aide qui fait tomber l'application
    serait pire que pas de bouton du tout. Chaque échec est rendu en
    français, avec la marche à suivre à la main.
    """
    dossier = Path(dossier)
    if not (dossier / NOM_LANCEUR).is_file():
        return False, (f"« {NOM_LANCEUR} » est introuvable dans "
                       f"{dossier} — l'icône n'aurait rien à ouvrir.")

    destination = bureau(accueil, environnement)
    if destination is None:
        return False, ("Dossier Bureau introuvable. Créez l'icône à la main : "
                       f"clic droit sur « {NOM_LANCEUR} », puis "
                       "« Envoyer vers » ▸ « Bureau (créer un raccourci) ».")

    lien = destination / NOM_RACCOURCI
    try:
        executer(commande_powershell(dossier, lien),
                 env=environnement_powershell(dossier, lien, environnement),
                 timeout=_DELAI_S, capture_output=True)
    except Exception:                       # PowerShell absent ou interdit
        pass
    if lien.is_file():
        effacer_anciens(destination)
        return True, (f"Icône « {NOM_RACCOURCI[:-4]} » créée sur le Bureau "
                      f"({lien}).")

    # Repli : certains postes d'officine interdisent PowerShell par
    # stratégie de groupe. Le .url ne demande rien d'autre qu'écrire un
    # fichier texte.
    replacement = destination / NOM_REPLI
    try:
        replacement.write_text(contenu_url(dossier), encoding="utf-8")
    except OSError as e:
        return False, (f"Écriture impossible sur le Bureau ({e}). Créez "
                       f"l'icône à la main : clic droit sur « {NOM_LANCEUR} », "
                       "puis « Envoyer vers » ▸ « Bureau (créer un "
                       "raccourci) ».")
    effacer_anciens(destination)
    return True, (f"Icône « {NOM_REPLI[:-4]} » créée sur le Bureau "
                  f"({replacement}).")
