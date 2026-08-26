# -*- coding: utf-8 -*-
"""Mise à jour automatique, en arrière-plan.

Se lance à l'ouverture de la session Windows et à chaque démarrage de
l'application. Compare la version installée à celle publiée, et n'agit que
s'il y a réellement quelque chose de nouveau.

Deux règles de prudence guident tout le module :

1. **ne jamais toucher aux fichiers pendant que l'application tourne** —
   remplacer un module sous un Streamlit en cours de route casserait la
   session en plein comptoir. Si le port de l'application répond, on ne
   fait rien et on ressort. Sur un dossier partagé, ce test ne suffit
   pas : il ne regarde que ``127.0.0.1``, alors que les comptoirs
   voisins lancent leur propre Streamlit sur les mêmes fichiers. Les
   marqueurs de ``presence.py`` disent qui d'autre est en train de
   travailler ;
2. **ne jamais bloquer** — poste hors ligne, réseau filtré, archive
   illisible : la mise à jour renonce en silence. Elle n'a pas le droit
   d'empêcher l'application de démarrer.

Écrit en bibliothèque standard uniquement (ni pandas, ni Streamlit) : au
démarrage du PC, ce script doit être immédiat et indépendant.
"""

from __future__ import annotations

import argparse
import io
import logging
import re
import shutil
import socket
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import presence

_journal = logging.getLogger("pharmacie.maj_auto")

URL_ARCHIVE = ("https://github.com/lordofdecay57/pharmacie-ruptures"
               "/archive/refs/heads/main.zip")
URL_VERSION = ("https://raw.githubusercontent.com/lordofdecay57/"
               "pharmacie-ruptures/main/app.py")
#: Dossier racine à l'intérieur de l'archive GitHub.
RACINE_ARCHIVE = "pharmacie-ruptures-main"

#: Ce qui ne descend PAS sur le poste de la pharmacie.
#:
#: Le dépôt contient le programme ET tout ce qui sert à le fabriquer :
#: la suite de tests, les outils de développement, une application web
#: sans rapport. Tout cela atterrissait dans le dossier de l'officine —
#: 3 Mo et une centaine de fichiers de plus, au milieu desquels il
#: fallait retrouver « lancer.bat ». Personne ne lance un utilitaire
#: dont il ne reconnaît aucun fichier.
DOSSIERS_DE_DEVELOPPEMENT = (
    "tests",        # la suite de tests : 2,3 Mo, inutile en officine
    "outils",       # génération de l'icône et du guide PDF
    "web",          # application Next.js, projet séparé
    ".github",      # intégration continue
    ".pytest_cache",
    "__pycache__",
)

#: Fichiers de la pharmacie : JAMAIS écrasés par une mise à jour.
#: Ce sont ses DONNÉES, rien d'autre.
#:
#: Les deux `mettre-a-jour*.bat` n'y figurent pas, et c'est délibéré.
#: Ils s'excluent eux-mêmes de leur propre `/XF` — cmd relit un .bat
#: au fil des lignes, le remplacer sous ses pieds lui ferait exécuter
#: n'importe quoi. Mais ici, c'est Python qui écrit et aucun des deux
#: n'est en train de tourner : les protéger revenait à interdire pour
#: toujours de corriger un bug dedans. Un défaut y est resté des mois,
#: réparé dans le dépôt et jamais chez la pharmacie.
#:
#: Reste une course étroite : quelqu'un lance `mettre-a-jour.bat`
#: pendant que `maj_auto` tourne sur un autre poste. Elle dure quelques
#: secondes, elle ne survient qu'un jour de publication, et elle coûte
#: une fenêtre à relancer. L'autre branche du choix coûtait un bug
#: définitif.
FICHIERS_PROTEGES = (
    "config.yaml",
    "historique_commandes.csv",
    "etat_stock_precedent.csv",
    "etat_stock_precedent.sig",
    "stock_ferme.csv",
    "stock_ferme_produits.csv",
    "commandes_speciales.csv",
    "base_medicaments.csv",
)

PORT_APPLICATION = 8501
_DELAI_RESEAU_S = 20

#: Résultats possibles, tels qu'inscrits au journal.
DEJA_A_JOUR = "deja_a_jour"
APPLICATION_EN_COURS = "application_en_cours"
INJOIGNABLE = "injoignable"
MISE_A_JOUR = "mise_a_jour"
ECHEC = "echec"

#: Code de sortie signalant au lanceur que l'application répond déjà — il
#: doit alors ouvrir le navigateur au lieu de démarrer un second serveur.
CODE_DEJA_OUVERTE = 10


def lire_version(chemin_app: Path) -> str:
    """Version inscrite dans un ``app.py`` (chaîne vide si introuvable)."""
    try:
        texte = Path(chemin_app).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    trouve = re.search(r'VERSION_APP\s*=\s*"([^"]+)"', texte)
    return trouve.group(1) if trouve else ""


def _numero(version: str) -> tuple:
    """« 3.10 » → (3, 10) : comparer des nombres, pas du texte."""
    return tuple(int(p) if p.isdigit() else 0
                 for p in str(version or "").split("."))


def plus_recente(publiee: str, installee: str) -> bool:
    """Vrai si ``publiee`` est strictement postérieure à ``installee``.

    Une version installée EN AVANCE (poste de développement) ne doit
    déclencher aucune mise à jour.
    """
    if not publiee or not installee:
        return False
    return _numero(publiee) > _numero(installee)


def application_en_cours(port: int = PORT_APPLICATION) -> bool:
    """L'application répond-elle déjà sur son port ?

    C'est le garde-fou principal : remplacer les fichiers sous un Streamlit
    en cours casserait la session ouverte au comptoir.
    """
    with socket.socket() as prise:
        prise.settimeout(0.6)
        return prise.connect_ex(("127.0.0.1", port)) == 0


def _telecharger(url: str, delai_s: float) -> Optional[bytes]:
    try:
        with urllib.request.urlopen(url, timeout=delai_s) as reponse:
            return reponse.read()
    except Exception as e:                      # réseau, DNS, proxy, 404…
        _journal.info("Téléchargement impossible (%s) : %s", url, e)
        return None


def version_publiee(delai_s: float = _DELAI_RESEAU_S) -> str:
    """Version publiée sur le dépôt, ou chaîne vide si injoignable.

    On lit le seul ``app.py`` (quelques dizaines de Ko) plutôt que
    l'archive complète : inutile de télécharger 300 Ko pour découvrir qu'on
    est déjà à jour.
    """
    donnees = _telecharger(URL_VERSION, delai_s)
    if donnees is None:
        return ""
    trouve = re.search(r'VERSION_APP\s*=\s*"([^"]+)"',
                       donnees.decode("utf-8", errors="replace"))
    return trouve.group(1) if trouve else ""


def installer_archive(archive: bytes, destination: Path) -> int:
    """Déploie l'archive sur le dossier de l'application.

    Les fichiers de la pharmacie sont préservés, et rien n'est supprimé :
    une mise à jour ajoute ou remplace, elle ne fait jamais le ménage.
    Renvoie le nombre de fichiers écrits.
    """
    destination = Path(destination)
    with zipfile.ZipFile(io.BytesIO(archive)) as zip_archive:
        noms = zip_archive.namelist()
        racine = noms[0].split("/")[0] if noms else RACINE_ARCHIVE
        with tempfile.TemporaryDirectory() as travail:
            zip_archive.extractall(travail)
            source = Path(travail) / racine
            if not source.is_dir():
                raise ValueError("archive inattendue : dossier racine absent")
            ecrits = 0
            for fichier in sorted(source.rglob("*")):
                if not fichier.is_file():
                    continue
                relatif = fichier.relative_to(source)
                if relatif.name in FICHIERS_PROTEGES:
                    continue
                # Le dossier de l'officine ne reçoit que le programme :
                # y déverser la suite de tests, c'est noyer lancer.bat
                # au milieu de cent fichiers que personne ne reconnaît.
                if set(relatif.parts[:-1]) & set(DOSSIERS_DE_DEVELOPPEMENT):
                    continue
                cible = destination / relatif
                cible.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(fichier, cible)
                ecrits += 1
    return ecrits


def executer(dossier: Path, forcer: bool = False,
             delai_s: float = _DELAI_RESEAU_S) -> tuple:
    """Vérifie et, si besoin, installe la nouvelle version.

    Renvoie ``(resultat, message)``. Aucun appel ne lève : ce script tourne
    au démarrage du poste, il doit échouer sans bruit.
    """
    dossier = Path(dossier)
    installee = lire_version(dossier / "app.py")

    if application_en_cours():
        return (APPLICATION_EN_COURS,
                "Application ouverte — mise à jour reportée pour ne pas "
                "interrompre la session en cours.")

    # Dossier partagé : les autres comptoirs lancent leur propre Streamlit
    # sur CES fichiers. Le test du port ci-dessus ne les voit pas — il
    # n'interroge que cette machine. Les nommer plutôt que dire « occupé »
    # : le lendemain, on saura quel poste était resté ouvert.
    occupes = presence.postes_actifs(dossier)
    if occupes:
        return (APPLICATION_EN_COURS,
                "Dossier en cours d'utilisation par : "
                + ", ".join(occupes)
                + " — mise à jour reportée pour ne pas interrompre leur "
                  "session.")

    publiee = version_publiee(delai_s)
    if not publiee:
        return INJOIGNABLE, "Dépôt injoignable — aucune mise à jour tentée."
    if not forcer and not plus_recente(publiee, installee):
        return DEJA_A_JOUR, f"Déjà à jour (v{installee})."

    archive = _telecharger(URL_ARCHIVE, delai_s)
    if archive is None:
        return INJOIGNABLE, "Archive non téléchargée — rien n'a été modifié."
    try:
        ecrits = installer_archive(archive, dossier)
    except Exception as e:
        return ECHEC, f"Installation impossible : {e}"
    return (MISE_A_JOUR,
            f"Mise à jour v{installee or '?'} → v{publiee} "
            f"({ecrits} fichiers).")


def _configurer_journal(dossier: Path, verbeux: bool) -> None:
    """Trace dans un fichier : une mise à jour silencieuse doit rester
    explicable après coup."""
    poignees = [logging.FileHandler(dossier / "maj_auto.log",
                                    encoding="utf-8")]
    if verbeux:
        poignees.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, handlers=poignees, force=True,
                        format="%(asctime)s %(message)s")


def main(argv=None) -> int:
    analyseur = argparse.ArgumentParser(
        description="Met à jour l'utilitaire si une version plus récente "
                    "est publiée. Ne fait rien si l'application tourne.")
    analyseur.add_argument("--dossier", default=str(Path(__file__).parent),
                           help="dossier de l'application")
    analyseur.add_argument("--forcer", action="store_true",
                           help="réinstaller même si la version est identique")
    analyseur.add_argument("--verbeux", action="store_true",
                           help="afficher le déroulement dans la console")
    options = analyseur.parse_args(argv)

    dossier = Path(options.dossier)
    try:
        _configurer_journal(dossier, options.verbeux)
    except OSError:                              # dossier en lecture seule
        logging.basicConfig(level=logging.INFO, force=True)

    resultat, message = executer(dossier, forcer=options.forcer)
    _journal.info("[%s] %s", resultat, message)
    if options.verbeux:
        print(f"{datetime.now():%d/%m/%Y %H:%M} — {message}")
    # L'application tourne déjà : le lanceur doit ouvrir le navigateur
    # plutôt que de tenter un second démarrage, qui echouerait sur un port
    # occupe et laisserait l'utilisateur devant une erreur.
    if resultat == APPLICATION_EN_COURS:
        return CODE_DEJA_OUVERTE
    # Sinon toujours 0, y compris en cas d'echec : une mise a jour ratee ne
    # doit pas empecher le lancement de l'application qui suit.
    return 0


if __name__ == "__main__":
    sys.exit(main())
