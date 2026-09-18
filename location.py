# -*- coding: utf-8 -*-
"""Module 5 — Location de matériel médical, et ententes préalables CAFAT.

Louer un lit médicalisé, un fauteuil roulant ou un concentrateur
d'oxygène à un patient suppose l'accord préalable de la caisse. Cet
accord — l'**entente préalable** — a une date et une durée, et il
**expire**. Passée l'échéance, la location n'est plus prise en charge :
le matériel reste chez le patient et plus personne ne la paie.

Trois questions se posent donc en permanence, et ce sont les trois vues
du module :

1. **où en sont les ententes ?** — laquelle est accordée, depuis quand,
   jusqu'à quand ;
2. **qu'y a-t-il à facturer ?** — la location se facture tous les mois,
   et une facturation oubliée ne se rattrape pas toute seule ;
3. **que faut-il renouveler ?** — monter un dossier prend du temps :
   ordonnance, accord du médecin, envoi à la caisse. Une échéance vue le
   jour où elle tombe est une échéance manquée.

**La durée de validité est saisie par dossier**, et non déduite d'une
règle : la caisse l'accorde au cas par cas selon le matériel, et inventer
une règle unique ferait expirer des dossiers sans prévenir — ou les
ferait renouveler pour rien. Une valeur par défaut est proposée, elle est
modifiable ligne à ligne.

ISOLATION : ce module ne lit ni le cadencier, ni les ruptures, ni
l'inventaire du stock interne, ni les commandes spéciales. Il ne connaît
que ses propres dossiers.
"""

from __future__ import annotations

import calendar
import logging
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

import stockage_partage

_journal = logging.getLogger("pharmacie.location")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

#: Ce qui est SAISI. Tout le reste — échéance, statuts, comptes à rebours —
#: se déduit, et n'a donc pas sa place dans le fichier : une valeur
#: enregistrée qui se déduit finit par contredire ce dont elle est déduite.
COLONNES_DOSSIER = [
    "Patient", "Matériel loué", "Début de location",
    "Entente préalable", "Validité (mois)", "Dernière facturation", "Notes",
]

#: Durée proposée quand on crée un dossier, en mois. Modifiable ligne à
#: ligne : la caisse accorde au cas par cas, et ce nombre n'est qu'un
#: point de départ pour éviter de tout ressaisir.
VALIDITE_DEFAUT_MOIS = 6

#: La location se facture tous les mois.
PERIODE_FACTURATION_MOIS = 1

#: Combien de temps à l'avance un dossier rejoint « à renouveler ».
#: Un mois : le temps de revoir le médecin, de refaire la demande et
#: d'attendre la réponse de la caisse.
ALERTE_RENOUVELLEMENT_J = 30

STATUT_SANS_ENTENTE = "⚪ Sans entente"
STATUT_ENTENTE_VALIDE = "🟢 Valide"
STATUT_A_RENOUVELER = "🟠 À renouveler"
STATUT_EXPIREE = "⛔ Expirée"

#: Les deux qui appellent un geste. Le reste peut attendre.
STATUTS_A_TRAITER = (STATUT_A_RENOUVELER, STATUT_EXPIREE)

STATUT_A_FACTURER = "🟢 À facturer"
STATUT_FACTURATION_A_JOUR = "🟡 À jour"
STATUT_JAMAIS_FACTUREE = "⚪ Jamais facturée"

TRI_ECHEANCE = "Échéance (au plus proche)"
TRI_PATIENT = "Patient (A → Z)"
TRIS = (TRI_ECHEANCE, TRI_PATIENT)


# ---------------------------------------------------------------------------
# Lecture des valeurs saisies
# ---------------------------------------------------------------------------

def dossier_vide() -> pd.DataFrame:
    """Dossier neuf, colonnes déjà en place (évite les tests d'existence)."""
    return pd.DataFrame(columns=COLONNES_DOSSIER)


def _texte(valeur) -> str:
    """Cellule → texte propre. Les vides d'un fichier relu valent NaN, qu'il
    ne faut ni afficher (« nan ») ni traiter comme une valeur présente."""
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return ""
    return " ".join(str(valeur).split())


def cle_patient(valeur) -> str:
    """Nom de patient réduit à ce qui l'identifie : sans accent ni casse.

    « Mme DUPONT », « mme dupont » et « Mme Dupont » désignent la même
    personne. Sans cette réduction, le même patient reviendrait en trois
    dossiers, chacun avec sa moitié d'historique.
    """
    sans_accent = unicodedata.normalize("NFKD", _texte(valeur))
    sans_accent = "".join(c for c in sans_accent if not unicodedata.combining(c))
    return " ".join(sans_accent.upper().split())


#: Formats acceptés à la saisie. Le premier qui tombe juste gagne.
_FORMATS_DATE = ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y")


def parser_date(valeur) -> Optional[date]:
    """Texte ou date → ``date``, ou ``None`` si rien d'exploitable.

    Une date illisible ne doit JAMAIS lever : ces dossiers sont saisis à
    la main, et une faute de frappe ne peut pas faire tomber l'écran de
    toute une pharmacie.
    """
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return None
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    texte = _texte(valeur)
    if not texte:
        return None
    for format_essaye in _FORMATS_DATE:
        try:
            return datetime.strptime(texte, format_essaye).date()
        except ValueError:
            continue
    try:                                    # pandas rattrape le reste
        lue = pd.to_datetime(texte, dayfirst=True, errors="coerce")
    except (ValueError, TypeError):         # pragma: no cover
        return None
    return None if pd.isna(lue) else lue.date()


def parser_mois(valeur, defaut: int = VALIDITE_DEFAUT_MOIS) -> int:
    """Nombre de mois saisi. Zéro ou vide → le défaut, jamais de négatif.

    Zéro mois voudrait dire « expire le jour même », ce que la caisse
    n'accorde pas : c'est donc une case non remplie, pas une durée.
    """
    nombre = pd.to_numeric(pd.Series([valeur]), errors="coerce").fillna(0)
    mois = int(nombre.iloc[0])
    return defaut if mois <= 0 else mois


def _mois_texte(valeur, defaut: int = VALIDITE_DEFAUT_MOIS) -> str:
    """La durée, telle qu'elle s'ÉCRIT dans le dossier : en texte.

    Le dossier est un tableau de texte de bout en bout — relu du CSV en
    ``dtype=str``, réécrit tel quel. Y glisser un entier fait éclater
    pandas dès que la colonne est adossée à Arrow (« Scalar must be NA or
    str »), et l'écran tombe en exception au moment précis où l'on
    enregistre une entente. La conversion en nombre appartient à la vue,
    pas au stockage.
    """
    return str(parser_mois(valeur, defaut))


def ajouter_mois(depart: Optional[date], mois: int) -> Optional[date]:
    """``depart`` + ``mois``, en restant dans le calendrier.

    Le 31 janvier plus un mois n'est pas le 31 février : c'est le 28 (ou
    le 29). Ajouter 30 jours donnerait le 2 mars, et les échéances
    dériveraient d'un mois sur l'autre — une entente de six mois finirait
    par expirer cinq jours trop tôt.
    """
    if depart is None:
        return None
    total = depart.month - 1 + int(mois)
    annee = depart.year + total // 12
    mois_final = total % 12 + 1
    jour = min(depart.day, calendar.monthrange(annee, mois_final)[1])
    return date(annee, mois_final, jour)


# ---------------------------------------------------------------------------
# L'entente préalable : accordée, valable jusqu'à quand
# ---------------------------------------------------------------------------

def echeance(entente, validite_mois, defaut: int = VALIDITE_DEFAUT_MOIS):
    """Dernier jour couvert par l'entente, ou ``None`` s'il n'y en a pas.

    Sans entente accordée, il n'y a pas d'échéance à calculer — et surtout
    pas d'échéance à inventer : un dossier sans accord n'est pas un
    dossier qui expire, c'est un dossier qui n'a jamais commencé.
    """
    accordee = parser_date(entente)
    if accordee is None:
        return None
    return ajouter_mois(accordee, parser_mois(validite_mois, defaut))


def jours_avant_echeance(entente, validite_mois,
                         aujourdhui: Optional[date] = None,
                         defaut: int = VALIDITE_DEFAUT_MOIS):
    """Jours restants avant expiration. Négatif si l'entente est dépassée.

    Le signe compte : « expirée depuis 12 jours » et « expire dans
    12 jours » n'appellent pas le même geste.
    """
    fin = echeance(entente, validite_mois, defaut)
    if fin is None:
        return None
    return (fin - (aujourdhui or date.today())).days


def statut_entente(entente, validite_mois, aujourdhui: Optional[date] = None,
                   alerte_j: int = ALERTE_RENOUVELLEMENT_J,
                   defaut: int = VALIDITE_DEFAUT_MOIS) -> str:
    """Feu de circulation d'une entente préalable."""
    jours = jours_avant_echeance(entente, validite_mois, aujourdhui, defaut)
    if jours is None:
        return STATUT_SANS_ENTENTE
    if jours < 0:
        return STATUT_EXPIREE
    if jours <= max(0, int(alerte_j)):
        return STATUT_A_RENOUVELER
    return STATUT_ENTENTE_VALIDE


# ---------------------------------------------------------------------------
# La facturation : mensuelle, et une oubliée ne se rattrape pas seule
# ---------------------------------------------------------------------------

def prochaine_facturation(derniere_facturation,
                          periode_mois: int = PERIODE_FACTURATION_MOIS):
    """Date à laquelle la prochaine facturation est due.

    ``None`` si le dossier n'a jamais été facturé : elle est due
    **maintenant**, et il n'y a pas de date à attendre.
    """
    precedente = parser_date(derniere_facturation)
    if precedente is None:
        return None
    return ajouter_mois(precedente, max(1, int(periode_mois)))


def jours_avant_facturation(derniere_facturation,
                            aujourdhui: Optional[date] = None,
                            periode_mois: int = PERIODE_FACTURATION_MOIS) -> int:
    """Jours restants avant la prochaine facturation. 0 si elle est due.

    Jamais négatif : « facturable depuis 40 jours » et « facturable » ne
    demandent pas deux gestes différents, et un nombre négatif dans une
    colonne se lit mal.
    """
    prochaine = prochaine_facturation(derniere_facturation, periode_mois)
    if prochaine is None:
        return 0
    return max(0, (prochaine - (aujourdhui or date.today())).days)


def statut_facturation(derniere_facturation, aujourdhui: Optional[date] = None,
                       periode_mois: int = PERIODE_FACTURATION_MOIS) -> str:
    if parser_date(derniere_facturation) is None:
        return STATUT_JAMAIS_FACTUREE
    if jours_avant_facturation(derniere_facturation, aujourdhui,
                               periode_mois) == 0:
        return STATUT_A_FACTURER
    return STATUT_FACTURATION_A_JOUR


def mois_de_retard(derniere_facturation, aujourdhui: Optional[date] = None,
                   periode_mois: int = PERIODE_FACTURATION_MOIS) -> int:
    """Combien de facturations mensuelles ont été sautées.

    Une location facturée en janvier et oubliée jusqu'en avril, ce sont
    **trois** mois dus, pas un. Afficher « à facturer » sans dire combien
    ferait encaisser un mois et croire le dossier à jour.
    """
    precedente = parser_date(derniere_facturation)
    if precedente is None:
        return 0
    aujourdhui = aujourdhui or date.today()
    periode = max(1, int(periode_mois))
    retard, echue = 0, ajouter_mois(precedente, periode)
    while echue is not None and echue <= aujourdhui and retard < 240:
        retard += 1
        echue = ajouter_mois(precedente, periode * (retard + 1))
    return retard


# ---------------------------------------------------------------------------
# Vue calculée
# ---------------------------------------------------------------------------

COLONNES_VUE = [
    "Entente", "Patient", "Matériel loué", "Entente préalable",
    "Validité (mois)", "Échéance", "Jours avant échéance",
    "Facturation", "Dernière facturation", "Prochaine facturation",
    "Mois dus", "Début de location", "Notes",
]

#: Ce qu'on LIT dans chaque sous-onglet. Le détail reste disponible — il
#: change simplement de vue.
COLONNES_ENTENTES = ["Entente", "Patient", "Matériel loué",
                     "Entente préalable", "Échéance"]
COLONNES_FACTURATION = ["Facturation", "Patient", "Matériel loué",
                        "Dernière facturation", "Prochaine facturation",
                        "Mois dus"]
COLONNES_RENOUVELLEMENT = ["Entente", "Patient", "Matériel loué",
                           "Échéance", "Jours avant échéance"]

#: Ce qu'on CORRIGE : uniquement ce qui a été saisi à la main. Les statuts
#: et les échéances se déduisent — les afficher dans un tableau modifiable
#: laisserait croire qu'on peut les changer.
COLONNES_CORRECTION = list(COLONNES_DOSSIER)


def vue_affichable(dossier: pd.DataFrame, aujourdhui: Optional[date] = None,
                   tri: str = TRI_ECHEANCE,
                   alerte_j: int = ALERTE_RENOUVELLEMENT_J,
                   validite_defaut: int = VALIDITE_DEFAUT_MOIS,
                   periode_mois: int = PERIODE_FACTURATION_MOIS) -> pd.DataFrame:
    """Le dossier, enrichi de tout ce qui se déduit des dates."""
    aujourdhui = aujourdhui or date.today()
    if dossier is None or dossier.empty:
        return pd.DataFrame(columns=COLONNES_VUE)

    tableau = dossier.reindex(columns=COLONNES_DOSSIER).copy()
    lignes = []
    for _, ligne in tableau.iterrows():
        entente = parser_date(ligne.get("Entente préalable"))
        validite = parser_mois(ligne.get("Validité (mois)"), validite_defaut)
        fin = echeance(entente, validite, validite_defaut)
        derniere = parser_date(ligne.get("Dernière facturation"))
        lignes.append({
            "Entente": statut_entente(entente, validite, aujourdhui, alerte_j,
                                      validite_defaut),
            "Patient": _texte(ligne.get("Patient")),
            "Matériel loué": _texte(ligne.get("Matériel loué")),
            "Entente préalable": entente,
            "Validité (mois)": validite,
            "Échéance": fin,
            "Jours avant échéance": jours_avant_echeance(
                entente, validite, aujourdhui, validite_defaut),
            "Facturation": statut_facturation(derniere, aujourdhui,
                                              periode_mois),
            "Dernière facturation": derniere,
            "Prochaine facturation": prochaine_facturation(derniere,
                                                           periode_mois),
            "Mois dus": mois_de_retard(derniere, aujourdhui, periode_mois),
            "Début de location": parser_date(ligne.get("Début de location")),
            "Notes": _texte(ligne.get("Notes")),
        })
    vue = pd.DataFrame(lignes, columns=COLONNES_VUE)
    return _classer(vue, tri)


def _classer(vue: pd.DataFrame, tri: str) -> pd.DataFrame:
    """Trie la vue, puis retire les colonnes de service.

    L'échéance par défaut : ce qui expire en premier doit sauter aux yeux.
    Les dossiers sans entente passent en queue — rien ne presse à leur
    sujet tant qu'aucun accord n'a été demandé.
    """
    if vue.empty:
        return vue
    travail = vue.copy()
    travail["_echeance"] = [date.max if d is None or pd.isna(d) else d
                            for d in travail["Échéance"]]
    travail["_patient"] = [cle_patient(p) for p in travail["Patient"]]
    cles = (["_patient", "_echeance"] if tri == TRI_PATIENT
            else ["_echeance", "_patient"])
    travail = travail.sort_values(cles, kind="stable")
    return travail.drop(columns=["_echeance", "_patient"]).reset_index(
        drop=True)


def pour_affichage(vue: pd.DataFrame) -> pd.DataFrame:
    """La vue en TEXTE, pour que les cases vides soient vraiment vides.

    Streamlit affiche « None » pour une date absente comme pour un entier
    absent. Seule une chaîne vide s'affiche vide — et une colonne pleine
    de « None » se lit comme une panne.
    """
    if vue is None or vue.empty:
        return vue if vue is not None else pd.DataFrame(columns=COLONNES_VUE)
    propre = vue.copy()
    for colonne in ("Entente préalable", "Échéance", "Dernière facturation",
                    "Prochaine facturation", "Début de location"):
        if colonne in propre.columns:
            propre[colonne] = [
                f"{jour:%d/%m/%Y}" if jour is not None and not pd.isna(jour)
                else "" for jour in propre[colonne]]
    for colonne in ("Jours avant échéance", "Mois dus", "Validité (mois)"):
        if colonne in propre.columns:
            propre[colonne] = ["" if v is None or pd.isna(v) else str(int(v))
                               for v in propre[colonne]]
    return propre


# ---------------------------------------------------------------------------
# Les trois questions, chacune sa liste
# ---------------------------------------------------------------------------

def a_renouveler(dossier: pd.DataFrame, aujourdhui: Optional[date] = None,
                 alerte_j: int = ALERTE_RENOUVELLEMENT_J,
                 validite_defaut: int = VALIDITE_DEFAUT_MOIS) -> pd.DataFrame:
    """Les ententes qui expirent bientôt — ou qui ont déjà expiré.

    Les expirées d'abord, par ordre d'ancienneté : elles ne sont plus
    prises en charge, chaque jour compte double.
    """
    vue = vue_affichable(dossier, aujourdhui, TRI_ECHEANCE, alerte_j,
                         validite_defaut)
    if vue.empty:
        return vue
    return vue[vue["Entente"].isin(STATUTS_A_TRAITER)].reset_index(drop=True)


def a_facturer(dossier: pd.DataFrame, aujourdhui: Optional[date] = None,
               periode_mois: int = PERIODE_FACTURATION_MOIS,
               alerte_j: int = ALERTE_RENOUVELLEMENT_J,
               validite_defaut: int = VALIDITE_DEFAUT_MOIS) -> pd.DataFrame:
    """Les locations dont la facturation du mois est due.

    Jamais facturées comprises : c'est le cas le plus facile à oublier,
    puisqu'aucune date ne vient le rappeler.
    """
    vue = vue_affichable(dossier, aujourdhui, TRI_ECHEANCE, alerte_j,
                         validite_defaut, periode_mois)
    if vue.empty:
        return vue
    dues = vue["Facturation"].isin((STATUT_A_FACTURER, STATUT_JAMAIS_FACTUREE))
    return vue[dues].reset_index(drop=True)


def resume(dossier: pd.DataFrame, aujourdhui: Optional[date] = None,
           alerte_j: int = ALERTE_RENOUVELLEMENT_J,
           validite_defaut: int = VALIDITE_DEFAUT_MOIS,
           periode_mois: int = PERIODE_FACTURATION_MOIS) -> dict:
    """Les quelques nombres qui disent l'état du module d'un coup d'œil."""
    vue = vue_affichable(dossier, aujourdhui, TRI_ECHEANCE, alerte_j,
                         validite_defaut, periode_mois)
    if vue.empty:
        return {"dossiers": 0, "a_renouveler": 0, "expirees": 0,
                "a_facturer": 0, "mois_dus": 0}
    return {
        "dossiers": len(vue),
        "a_renouveler": int((vue["Entente"] == STATUT_A_RENOUVELER).sum()),
        "expirees": int((vue["Entente"] == STATUT_EXPIREE).sum()),
        "a_facturer": int(vue["Facturation"].isin(
            (STATUT_A_FACTURER, STATUT_JAMAIS_FACTUREE)).sum()),
        "mois_dus": int(pd.to_numeric(vue["Mois dus"],
                                      errors="coerce").fillna(0).sum()),
    }


# ---------------------------------------------------------------------------
# Mouvements sur les dossiers
# ---------------------------------------------------------------------------

def _index_dossier(dossier: pd.DataFrame, patient: str, materiel: str):
    """Ligne de ce patient pour ce matériel, ou ``None``.

    Un patient peut louer deux appareils différents : c'est le COUPLE qui
    identifie le dossier, pas le seul nom.
    """
    if dossier is None or dossier.empty:
        return None
    cible = (cle_patient(patient), cle_patient(materiel))
    for i, ligne in dossier.iterrows():
        if (cle_patient(ligne.get("Patient")),
                cle_patient(ligne.get("Matériel loué"))) == cible:
            return i
    return None


def ajouter_dossier(dossier: pd.DataFrame, patient: str, materiel: str,
                    debut=None, entente=None,
                    validite_mois: int = VALIDITE_DEFAUT_MOIS,
                    derniere_facturation=None, notes: str = "") -> pd.DataFrame:
    """Ouvre un dossier, ou complète celui qui existe déjà.

    Rouvrir un dossier existant plutôt que d'en créer un second : deux
    lignes pour le même patient et le même appareil, c'est un historique
    coupé en deux et une échéance suivie sur la mauvaise.
    """
    if dossier is None or dossier.empty:
        dossier = dossier_vide()
    dossier = dossier.reindex(columns=COLONNES_DOSSIER).copy()
    patient, materiel = _texte(patient), _texte(materiel)
    if not patient or not materiel:
        return dossier

    existant = _index_dossier(dossier, patient, materiel)
    valeurs = {
        "Patient": patient, "Matériel loué": materiel,
        "Début de location": _iso(debut),
        "Entente préalable": _iso(entente),
        "Validité (mois)": _mois_texte(validite_mois),
        "Dernière facturation": _iso(derniere_facturation),
        "Notes": _texte(notes),
    }
    if existant is not None:
        # On complète, on n'efface pas : une case laissée vide au
        # formulaire ne doit pas effacer une date déjà connue.
        for colonne, valeur in valeurs.items():
            if valeur not in ("", 0, None):
                dossier.at[existant, colonne] = valeur
        return dossier
    ligne = pd.DataFrame([valeurs], columns=COLONNES_DOSSIER)
    return pd.concat([dossier, ligne], ignore_index=True)


def _iso(valeur) -> str:
    jour = parser_date(valeur)
    return jour.isoformat() if jour else ""


def _modifier(dossier: pd.DataFrame, patient: str, materiel: str,
              colonne: str, valeur) -> pd.DataFrame:
    if dossier is None or dossier.empty:
        return dossier_vide()
    dossier = dossier.reindex(columns=COLONNES_DOSSIER).copy()
    indice = _index_dossier(dossier, patient, materiel)
    if indice is not None:
        dossier.at[indice, colonne] = valeur
    return dossier


def enregistrer_entente(dossier: pd.DataFrame, patient: str, materiel: str,
                        accordee_le, validite_mois: int = VALIDITE_DEFAUT_MOIS
                        ) -> pd.DataFrame:
    """L'accord de la caisse est arrivé : sa date, et sa durée."""
    dossier = _modifier(dossier, patient, materiel, "Entente préalable",
                        _iso(accordee_le))
    return _modifier(dossier, patient, materiel, "Validité (mois)",
                     _mois_texte(validite_mois))


def enregistrer_facturation(dossier: pd.DataFrame, patient: str,
                            materiel: str, le=None) -> pd.DataFrame:
    """Le mois vient d'être facturé : l'horloge repart de cette date."""
    return _modifier(dossier, patient, materiel, "Dernière facturation",
                     _iso(le or date.today()))


def supprimer_dossier(dossier: pd.DataFrame, patient: str,
                      materiel: str) -> pd.DataFrame:
    """La location est terminée, le matériel est revenu."""
    if dossier is None or dossier.empty:
        return dossier_vide()
    dossier = dossier.reindex(columns=COLONNES_DOSSIER).copy()
    indice = _index_dossier(dossier, patient, materiel)
    if indice is None:
        return dossier
    return dossier.drop(index=indice).reset_index(drop=True)


def normaliser_tableau_edite(tableau: pd.DataFrame) -> pd.DataFrame:
    """Remet en forme un dossier corrigé à la main dans le tableau.

    Une ligne sans patient OU sans matériel est abandonnée : ces deux-là
    font l'identité du dossier, et une ligne qui n'en a qu'un ne peut ni
    se retrouver ni se décrémenter.
    """
    if tableau is None or tableau.empty:
        return dossier_vide()
    propre = tableau.reindex(columns=COLONNES_DOSSIER).copy()
    for colonne in ("Patient", "Matériel loué", "Notes"):
        propre[colonne] = [_texte(v) for v in propre[colonne]]
    for colonne in ("Début de location", "Entente préalable",
                    "Dernière facturation"):
        propre[colonne] = [_iso(v) for v in propre[colonne]]
    propre["Validité (mois)"] = [_mois_texte(v)
                                 for v in propre["Validité (mois)"]]
    garder = (propre["Patient"] != "") & (propre["Matériel loué"] != "")
    return propre[garder].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Persistance — partagée entre postes, comme le reste
# ---------------------------------------------------------------------------

VerrouIndisponible = stockage_partage.VerrouIndisponible
empreinte_fichier = stockage_partage.empreinte_fichier


def sauver(dossier: pd.DataFrame, chemin: Path) -> None:
    """Écrit les dossiers sur disque (dates en ISO, séparateur ``;``)."""
    tableau = (dossier_vide() if dossier is None or dossier.empty
               else dossier.reindex(columns=COLONNES_DOSSIER).copy())
    for colonne in ("Début de location", "Entente préalable",
                    "Dernière facturation"):
        tableau[colonne] = [_iso(v) for v in tableau[colonne]]
    stockage_partage.ecrire_atomiquement(tableau, chemin)


def charger(chemin: Path) -> pd.DataFrame:
    """Relit les dossiers ; dossier vide si le fichier manque.

    Un fichier illisible ne doit pas empêcher l'ouverture du module : on
    repart d'un dossier vide en le signalant au journal, et l'ancien
    fichier reste sur le disque.
    """
    chemin = Path(chemin)
    if not chemin.exists():
        return dossier_vide()
    try:
        tableau = pd.read_csv(chemin, sep=";", dtype=str,
                              encoding="utf-8-sig").fillna("")
    except Exception:
        _journal.warning("Dossiers de location illisibles : %s", chemin)
        return dossier_vide()
    tableau = tableau.reindex(columns=COLONNES_DOSSIER).fillna("")
    for colonne in ("Patient", "Matériel loué", "Notes"):
        tableau[colonne] = tableau[colonne].astype(str)
    return tableau


def appliquer_aux_dossiers(chemin: Path, mouvement,
                           delai_s: float = stockage_partage.DELAI_VERROU_S):
    """Relit, applique ``mouvement``, réécrit — sous verrou.

    Plusieurs comptoirs travaillent sur les mêmes fichiers : on n'écrase
    jamais une photo prise à l'ouverture de la page, on relit et on
    applique le mouvement sur ce qui est là.
    """
    return stockage_partage.appliquer(chemin, charger, sauver, mouvement,
                                      delai_s)


def exporter_csv(dossier: pd.DataFrame, aujourdhui: Optional[date] = None,
                 tri: str = TRI_ECHEANCE,
                 alerte_j: int = ALERTE_RENOUVELLEMENT_J,
                 validite_defaut: int = VALIDITE_DEFAUT_MOIS) -> bytes:
    """La vue complète, telle qu'affichée, pour l'imprimer ou l'archiver."""
    vue = pour_affichage(vue_affichable(dossier, aujourdhui, tri, alerte_j,
                                        validite_defaut))
    return vue.to_csv(index=False, sep=";").encode("utf-8-sig")


def nom_fichier(extension: str, aujourdhui: Optional[date] = None,
                prefixe: str = "location") -> str:
    """Nom daté : deux exports du même jour ne doivent pas se recouvrir."""
    return f"{prefixe}_{(aujourdhui or date.today()):%Y-%m-%d}.{extension}"
