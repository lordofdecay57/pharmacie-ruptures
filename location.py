# -*- coding: utf-8 -*-
"""Module 5 — Location ET achat de matériel, ententes préalables CAFAT.

Fournir un lit médicalisé, un fauteuil roulant ou un concentrateur
d'oxygène à un patient suppose l'accord préalable de la caisse. Cet
accord — l'**entente préalable** — a une date et une durée, et il
**expire**. Passée l'échéance, la fourniture n'est plus prise en charge :
le matériel reste chez le patient et plus personne ne la paie.

Le matériel se **loue** ou s'**achète**, et le même patient peut faire les
deux. Les deux passent par une entente préalable ; ce qui les sépare vient
après :

======================  ========================  =======================
                        🛏️ Location                🛒 Achat
======================  ========================  =======================
Entente préalable       oui, et renouvelable      oui, une fois
Facturation             tous les mois             une seule fois
Une fois réglé          recommence le mois suivant   terminé, plus rien
======================  ========================  =======================

Les deux vivent dans le MÊME dossier, avec le même vocabulaire de
statuts : deux fichiers séparés auraient coupé chaque patient en deux, et
il aurait fallu le chercher deux fois pour répondre à « où en suis-je ? ».

Quatre questions se posent donc en permanence, et ce sont les quatre vues
du module :

1. **où en sont les ententes ?** — laquelle est accordée, depuis quand,
   jusqu'à quand ;
2. **qu'y a-t-il à facturer ?** — la location se facture tous les mois,
   et une facturation oubliée ne se rattrape pas toute seule ;
3. **que faut-il renouveler ?** — monter un dossier prend du temps :
   ordonnance, accord du médecin, envoi à la caisse. Une échéance vue le
   jour où elle tombe est une échéance manquée ;
4. **où en sont les achats ?** — ni mensuels ni renouvelables, ils se
   perdraient dans des listes faites pour des échéances qui reviennent.

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
    "Patient", "Matériel", "Mode", "Régime", "Début de location",
    "Demande le", "Demandée par", "Entente préalable", "Validité (mois)",
    "Dernière facturation", "Caution (F)", "Caution rendue le",
    "Commentaire entente", "Notes",
]

#: LOUER OU ACHETER. Le même patient peut faire les deux, et la caisse
#: demande une entente préalable dans les deux cas — c'est ce qui permet de
#: les tenir dans UN SEUL dossier, avec le même vocabulaire de statuts.
#: Ce qui change est la suite : une location se facture tous les mois et
#: son entente se renouvelle ; un achat se facture UNE FOIS et, une fois
#: réglé, il n'expire plus. Les séparer en deux fichiers aurait coupé
#: chaque patient en deux, et c'est justement ce qu'il ne faut pas.
MODE_LOCATION = "🛏️ Location"
MODE_ACHAT = "🛒 Achat"
MODES = (MODE_LOCATION, MODE_ACHAT)

#: SOUMIS À ENTENTE, OU NON. Tout le matériel ne passe pas par la caisse :
#: un tensiomètre n'est pas remboursé, un aérosol l'est sous conditions —
#: ni l'un ni l'autre ne demande d'entente préalable, mais tous deux
#: demandent une CAUTION. Les mêler aux dossiers soumis à entente les
#: ferait apparaître « sans entente » en permanence, c'est-à-dire comme
#: un manquement : ils n'en sont pas un.
REGIME_ENTENTE = "📋 Soumis à entente"
REGIME_LIBRE = "🆓 Sans entente requise"
REGIMES = (REGIME_ENTENTE, REGIME_LIBRE)

#: Le matériel qui se loue SANS passer par la caisse, et ce qu'il engage.
#: Les montants sont ceux pratiqués à l'officine ; ils sont proposés à la
#: saisie et restent modifiables ligne à ligne — un tarif qui change ne
#: doit pas demander une nouvelle version du programme.
#: La clé est cherchée dans le nom du matériel, sans accent ni casse.
CATALOGUE_SANS_ENTENTE = {
    "TENSIOMETRE": {"caution": 3000,
                    "remboursement": "Non remboursé"},
    "AEROSOL": {"caution": 5000,
                "remboursement": "Remboursé sous conditions"},
}

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

STATUT_SANS_ENTENTE = "⚪ Rien de fait"
STATUT_DEMANDE_ENVOYEE = "📨 Demande envoyée"
STATUT_ENTENTE_VALIDE = "🟢 Valide"
STATUT_A_RENOUVELER = "🟠 À renouveler"
STATUT_DERNIER_MOIS = "🔔 Dernier mois couvert"
STATUT_EXPIREE = "⛔ Expirée"

#: Le matériel qui n'a jamais eu besoin d'accord. Ce n'est pas un
#: manquement : c'est un régime différent, et il doit se lire comme tel.
STATUT_ENTENTE_NON_REQUISE = "🆓 Non requise"

#: Ceux qui appellent un geste. Le reste peut attendre.
#: « Dernier mois couvert » en fait partie : c'est le moment où le
#: renouvellement doit partir, pas celui où l'on constate qu'il aurait
#: dû partir.
STATUTS_A_TRAITER = (STATUT_A_RENOUVELER, STATUT_DERNIER_MOIS,
                     STATUT_EXPIREE)

STATUT_A_FACTURER = "🟢 À facturer"
STATUT_FACTURATION_A_JOUR = "🟡 À jour"
STATUT_JAMAIS_FACTUREE = "⚪ Jamais facturée"

#: L'achat réglé : rien ne reviendra, ni facturation ni renouvellement.
#: Un « 🟡 À jour » laisserait croire qu'une échéance approche.
STATUT_ACHAT_REGLE = "✅ Réglé"

#: Les deux statuts qui appellent une facturation, quel que soit le mode.
STATUTS_A_FACTURER = (STATUT_A_FACTURER, STATUT_JAMAIS_FACTUREE)

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


def parser_mode(valeur) -> str:
    """Loué ou acheté. Tout ce qui n'est pas un achat est une location.

    Le défaut penche du côté de la location parce que c'est le cas le plus
    fréquent, et surtout parce qu'il est le plus SURVEILLÉ : une location
    prise pour un achat cesserait d'être facturée tous les mois et
    disparaîtrait des renouvellements, sans que rien ne le signale.
    L'inverse ne fait qu'ajouter un dossier dans une liste.
    """
    texte = cle_patient(valeur)
    return MODE_ACHAT if "ACHAT" in texte or "ACHET" in texte else MODE_LOCATION


def parser_regime(valeur) -> str:
    """Soumis à entente, ou non. Le défaut est le régime SURVEILLÉ.

    Un dossier classé « sans entente requise » par erreur sortirait des
    renouvellements sans que rien ne le signale, et l'entente expirerait
    en silence. L'inverse n'ajoute qu'une ligne dans une liste.
    """
    texte = cle_patient(valeur)
    return REGIME_LIBRE if "SANS" in texte or "LIBRE" in texte else REGIME_ENTENTE


def fiche_sans_entente(materiel) -> Optional[dict]:
    """Ce que l'officine sait de ce matériel-là, ou ``None``.

    Cherché DANS le nom : « Aérosol Pari Boy » et « aerosol » doivent
    tomber sur la même fiche, sans quoi il faudrait écrire le libellé au
    caractère près pour que la caution se propose.
    """
    nom = cle_patient(materiel)
    for cle, fiche in CATALOGUE_SANS_ENTENTE.items():
        if cle in nom:
            return dict(fiche, matiere=cle)
    return None


def regime_propose(materiel) -> str:
    """Le régime que le nom du matériel laisse attendre.

    Une proposition, jamais une contrainte : elle évite de reclasser à la
    main chaque tensiomètre, et reste modifiable si un cas sort de
    l'ordinaire.
    """
    return REGIME_LIBRE if fiche_sans_entente(materiel) else REGIME_ENTENTE


def caution_proposee(materiel) -> int:
    """La caution d'usage pour ce matériel, 0 s'il n'en demande pas."""
    fiche = fiche_sans_entente(materiel)
    return int(fiche["caution"]) if fiche else 0


def remboursement(materiel) -> str:
    """Ce que la caisse fait de ce matériel-là, en clair.

    Tensiomètre et aérosol se ressemblent — ni l'un ni l'autre ne demande
    d'entente — mais l'un n'est jamais remboursé et l'autre l'est sous
    conditions. Les afficher côte à côte sans le dire ferait répondre au
    hasard au patient qui le demande.
    """
    fiche = fiche_sans_entente(materiel)
    return fiche["remboursement"] if fiche else ""


def parser_montant(valeur) -> int:
    """Un montant en francs. Vide, illisible ou négatif → 0.

    Jamais de négatif : une caution négative, c'est de l'argent que la
    pharmacie devrait au patient sans l'avoir encaissé.
    """
    nombre = pd.to_numeric(pd.Series([_texte(valeur).replace(" ", "")]),
                           errors="coerce").fillna(0)
    return max(0, int(nombre.iloc[0]))


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


def jours_depuis_demande(demande_le, aujourdhui: Optional[date] = None):
    """Depuis combien de jours la demande attend une réponse.

    ``None`` si aucune demande n'a été envoyée. C'est ce nombre qui dit
    quand relancer la caisse : une demande partie et jamais rappelée peut
    dormir des mois sans que rien ne la réveille.
    """
    partie = parser_date(demande_le)
    if partie is None:
        return None
    return ((aujourdhui or date.today()) - partie).days


def statut_entente(entente, validite_mois, aujourdhui: Optional[date] = None,
                   alerte_j: int = ALERTE_RENOUVELLEMENT_J,
                   defaut: int = VALIDITE_DEFAUT_MOIS,
                   regime: str = REGIME_ENTENTE, demande_le=None,
                   derniere_facturation=None, mode: str = MODE_LOCATION,
                   periode_mois: int = PERIODE_FACTURATION_MOIS) -> str:
    """Feu de circulation d'une entente préalable.

    Quatre étapes, et non deux : rien de fait, demande envoyée, accord
    reçu, échéance qui approche. L'étape « demande envoyée » manquait — un
    dossier parti à la caisse se lisait comme un dossier oublié, et on le
    refaisait.

    Le matériel qui n'a jamais eu besoin d'accord — tensiomètre, aérosol —
    n'entre pas dans ce feu-là : l'y faire entrer l'afficherait « rien de
    fait » à vie, c'est-à-dire comme un manquement.
    """
    if parser_regime(regime) == REGIME_LIBRE:
        return STATUT_ENTENTE_NON_REQUISE
    jours = jours_avant_echeance(entente, validite_mois, aujourdhui, defaut)
    if jours is None:
        return (STATUT_DEMANDE_ENVOYEE if parser_date(demande_le) is not None
                else STATUT_SANS_ENTENTE)
    if jours < 0:
        return STATUT_EXPIREE
    # Le dernier mois couvert passe DEVANT le compte à rebours : c'est un
    # signal de facturation, et il tombe parfois avant que le délai
    # d'alerte, réglable, ne se déclenche.
    if au_dernier_mois(entente, validite_mois, derniere_facturation, mode,
                       periode_mois, defaut):
        return STATUT_DERNIER_MOIS
    if jours <= max(0, int(alerte_j)):
        return STATUT_A_RENOUVELER
    return STATUT_ENTENTE_VALIDE


def au_dernier_mois(entente, validite_mois, derniere_facturation,
                    mode: str = MODE_LOCATION,
                    periode_mois: int = PERIODE_FACTURATION_MOIS,
                    defaut: int = VALIDITE_DEFAUT_MOIS) -> bool:
    """Le mois qui vient d'être facturé est-il le dernier que l'entente couvre ?

    « Au moment de la facturation du dernier mois, une proposition de
    renouvellement. » C'est LE moment utile : la facturation est le seul
    geste mensuel certain sur un dossier de location. Attendre l'échéance
    elle-même, c'est la découvrir une fois passée ; prévenir plus tôt,
    c'est prévenir tous les mois pour rien.

    Vrai quand la facturation SUIVANTE tomberait après l'échéance : il n'y
    aura donc pas de mois d'après à facturer sous cet accord.

    Un achat n'a pas de mois suivant : la question ne se pose pas.
    """
    if parser_mode(mode) == MODE_ACHAT:
        return False
    fin = echeance(entente, validite_mois, defaut)
    suivante = prochaine_facturation(derniere_facturation, periode_mois,
                                     MODE_LOCATION)
    if fin is None or suivante is None:
        return False
    return suivante > fin


# ---------------------------------------------------------------------------
# La facturation : mensuelle, et une oubliée ne se rattrape pas seule
# ---------------------------------------------------------------------------

def prochaine_facturation(derniere_facturation,
                          periode_mois: int = PERIODE_FACTURATION_MOIS,
                          mode: str = MODE_LOCATION):
    """Date à laquelle la prochaine facturation est due.

    ``None`` si le dossier n'a jamais été facturé : elle est due
    **maintenant**, et il n'y a pas de date à attendre.

    ``None`` aussi pour un ACHAT déjà réglé : il ne reviendra pas. Lui
    calculer une date le ferait remonter tous les mois dans « à facturer »,
    et on finirait par facturer deux fois le même fauteuil.
    """
    precedente = parser_date(derniere_facturation)
    if precedente is None or mode == MODE_ACHAT:
        return None
    return ajouter_mois(precedente, max(1, int(periode_mois)))


def jours_avant_facturation(derniere_facturation,
                            aujourdhui: Optional[date] = None,
                            periode_mois: int = PERIODE_FACTURATION_MOIS,
                            mode: str = MODE_LOCATION) -> int:
    """Jours restants avant la prochaine facturation. 0 si elle est due.

    Jamais négatif : « facturable depuis 40 jours » et « facturable » ne
    demandent pas deux gestes différents, et un nombre négatif dans une
    colonne se lit mal.
    """
    prochaine = prochaine_facturation(derniere_facturation, periode_mois, mode)
    if prochaine is None:
        return 0
    return max(0, (prochaine - (aujourdhui or date.today())).days)


def statut_facturation(derniere_facturation, aujourdhui: Optional[date] = None,
                       periode_mois: int = PERIODE_FACTURATION_MOIS,
                       mode: str = MODE_LOCATION) -> str:
    """Où en est la facturation — et elle ne se lit pas pareil selon le mode.

    Une LOCATION revient tous les mois. Un ACHAT se facture une fois : une
    fois réglé il est « ✅ Réglé », pas « à jour » — « à jour » laisserait
    croire qu'une échéance approche.
    """
    if parser_date(derniere_facturation) is None:
        return STATUT_JAMAIS_FACTUREE
    if mode == MODE_ACHAT:
        return STATUT_ACHAT_REGLE
    if jours_avant_facturation(derniere_facturation, aujourdhui,
                               periode_mois) == 0:
        return STATUT_A_FACTURER
    return STATUT_FACTURATION_A_JOUR


def mois_de_retard(derniere_facturation, aujourdhui: Optional[date] = None,
                   periode_mois: int = PERIODE_FACTURATION_MOIS,
                   mode: str = MODE_LOCATION) -> int:
    """Combien de facturations mensuelles ont été sautées.

    Une location facturée en janvier et oubliée jusqu'en avril, ce sont
    **trois** mois dus, pas un. Afficher « à facturer » sans dire combien
    ferait encaisser un mois et croire le dossier à jour.
    """
    precedente = parser_date(derniere_facturation)
    if precedente is None or mode == MODE_ACHAT:
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
    "Entente", "Patient", "Matériel", "Mode", "Régime",
    "Demande le", "Demandée par", "Attente (j)",
    "Entente préalable", "Validité (mois)", "Échéance",
    "Jours avant échéance", "Facturation", "Dernière facturation",
    "Prochaine facturation", "Mois dus", "Caution (F)",
    "Caution rendue le", "Début de location", "Commentaire entente",
    "Notes",
]

#: Ce qu'on LIT dans chaque sous-onglet. Le détail reste disponible — il
#: change simplement de vue.
#:
#: « Mode » figure dans TOUTES : une liste où l'on ne voit pas si la ligne
#: est louée ou achetée oblige à retourner au tableau complet pour chaque
#: patient — et c'est exactement le va-et-vient que ces vues évitent.
#: La DEMANDE figure dans la vue des ententes, avec son auteur : c'est la
#: traçabilité demandée — savoir qui a envoyé quoi, et quand, sans avoir à
#: appeler la caisse pour le lui demander.
#: Sans « Attente (j) » : le compte à rebours ne dit quelque chose que
#: d'une demande SANS réponse, et celles-là ont leur propre liste juste
#: au-dessus. Ici il serait vide neuf fois sur dix, et une colonne vide
#: coûte la place d'une colonne pleine.
COLONNES_ENTENTES = ["Entente", "Patient", "Matériel", "Mode",
                     "Demande le", "Demandée par",
                     "Entente préalable", "Échéance", "Commentaire entente"]

#: Ce qui attend une réponse de la caisse : sans accord, mais la demande
#: est partie. C'est la liste des relances.
COLONNES_DEMANDES = ["Patient", "Matériel", "Mode", "Demande le",
                     "Demandée par", "Attente (j)", "Commentaire entente"]

COLONNES_FACTURATION = ["Facturation", "Patient", "Matériel", "Mode",
                        "Dernière facturation", "Prochaine facturation",
                        "Mois dus", "Entente", "Échéance"]
COLONNES_RENOUVELLEMENT = ["Entente", "Patient", "Matériel", "Mode",
                           "Échéance", "Jours avant échéance",
                           "Demande le", "Demandée par"]

#: Le matériel loué hors caisse. Ni échéance ni mois dus : ce qui compte
#: est la CAUTION — de l'argent encaissé qui appartient au patient tant
#: qu'il n'a pas rendu l'appareil — et ce que la caisse en fait.
COLONNES_SANS_ENTENTE = ["Patient", "Matériel", "Remboursement",
                         "Début de location", "Caution (F)",
                         "Caution rendue le", "Dernière facturation",
                         "Notes"]

#: L'achat : ni « prochaine facturation » ni « mois dus » — il n'y en a
#: pas. Montrer deux colonnes vides ferait douter d'une panne.
COLONNES_ACHATS = ["Entente", "Patient", "Matériel", "Entente préalable",
                   "Échéance", "Facturation", "Dernière facturation"]

#: Le récapitulatif par patient : une ligne par personne, tous modes
#: confondus. C'est la vue qu'on ouvre quand le patient est au téléphone.
COLONNES_PATIENT = ["Patient", "Locations", "Achats", "Entente",
                    "À renouveler", "À facturer", "Mois dus",
                    "Caution détenue (F)"]

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
        mode = parser_mode(ligne.get("Mode"))
        materiel = _texte(ligne.get("Matériel"))
        # Un régime jamais renseigné — un dossier ouvert avant que ce
        # champ n'existe — se déduit du nom du matériel plutôt que de
        # verser d'office dans « soumis à entente » : un tensiomètre
        # d'avant la mise à jour se lirait sinon comme un manquement.
        regime = (parser_regime(ligne.get("Régime"))
                  if _texte(ligne.get("Régime")) else regime_propose(materiel))
        demande = parser_date(ligne.get("Demande le"))
        lignes.append({
            "Entente": statut_entente(entente, validite, aujourdhui, alerte_j,
                                      validite_defaut, regime, demande,
                                      derniere, mode, periode_mois),
            "Patient": _texte(ligne.get("Patient")),
            "Matériel": materiel,
            "Mode": mode,
            "Régime": regime,
            "Demande le": demande,
            "Demandée par": _texte(ligne.get("Demandée par")),
            "Attente (j)": (jours_depuis_demande(demande, aujourdhui)
                            if entente is None else None),
            "Remboursement": remboursement(materiel),
            "Entente préalable": entente,
            "Validité (mois)": validite,
            "Échéance": fin,
            "Jours avant échéance": jours_avant_echeance(
                entente, validite, aujourdhui, validite_defaut),
            "Facturation": statut_facturation(derniere, aujourdhui,
                                              periode_mois, mode),
            "Dernière facturation": derniere,
            "Prochaine facturation": prochaine_facturation(derniere,
                                                           periode_mois, mode),
            "Mois dus": mois_de_retard(derniere, aujourdhui, periode_mois,
                                       mode),
            "Caution (F)": parser_montant(ligne.get("Caution (F)")),
            "Caution rendue le": parser_date(ligne.get("Caution rendue le")),
            "Début de location": parser_date(ligne.get("Début de location")),
            "Commentaire entente": _texte(ligne.get("Commentaire entente")),
            "Notes": _texte(ligne.get("Notes")),
        })
    # « Remboursement » se déduit du matériel : il n'est pas saisi, donc
    # pas dans COLONNES_VUE, mais la vue des locations hors caisse en a
    # besoin — d'où la colonne ajoutée ici et non là.
    vue = pd.DataFrame(lignes, columns=COLONNES_VUE + ["Remboursement"])
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
                    "Prochaine facturation", "Début de location",
                    "Demande le", "Caution rendue le"):
        if colonne in propre.columns:
            propre[colonne] = [
                f"{jour:%d/%m/%Y}" if jour is not None and not pd.isna(jour)
                else "" for jour in propre[colonne]]
    for colonne in ("Jours avant échéance", "Mois dus", "Validité (mois)",
                    "Attente (j)"):
        if colonne in propre.columns:
            propre[colonne] = ["" if v is None or pd.isna(v) else str(int(v))
                               for v in propre[colonne]]
    # Les montants portent leur unité et une espace de millier : « 3 000 F »
    # se lit d'un coup d'œil là où « 3000 » se compte. Zéro s'efface :
    # une colonne de zéros se lit comme une panne, pas comme « rien à
    # encaisser ».
    for colonne in ("Caution (F)", "Caution détenue (F)"):
        if colonne in propre.columns:
            propre[colonne] = [
                "" if v is None or pd.isna(v) or int(v) == 0
                else f"{int(v):,} F".replace(",", " ")
                for v in propre[colonne]]
    return propre


# ---------------------------------------------------------------------------
# Les questions, chacune sa liste
# ---------------------------------------------------------------------------

def du_mode(vue: pd.DataFrame, mode: str) -> pd.DataFrame:
    """Les lignes d'un seul mode, dans une vue DÉJÀ calculée.

    Filtrer la vue plutôt que le dossier : le classement, les statuts et
    les comptes à rebours sont alors calculés une seule fois, et les deux
    modes restent rigoureusement d'accord entre eux — c'est ce qui permet
    de les lire côte à côte sans se demander lequel dit vrai.
    """
    if vue is None or vue.empty:
        return pd.DataFrame(columns=COLONNES_VUE)
    return vue[vue["Mode"] == mode].reset_index(drop=True)


def du_regime(vue: pd.DataFrame, regime: str) -> pd.DataFrame:
    """Les lignes d'un seul régime, dans une vue DÉJÀ calculée.

    Même raison que ``du_mode`` : filtrer la vue plutôt que le dossier
    garde les statuts et les classements rigoureusement d'accord entre
    les listes.
    """
    if vue is None or vue.empty:
        return pd.DataFrame(columns=COLONNES_VUE + ["Remboursement"])
    return vue[vue["Régime"] == regime].reset_index(drop=True)


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
    # Le matériel hors caisse en est absent SANS filtre supplémentaire :
    # `statut_entente` lui rend « 🆓 Non requise », qui n'est pas un statut
    # à traiter. Un second garde-fou ici serait du code qu'aucun test ne
    # peut atteindre — et une protection intestable ment sur ce qu'elle
    # protège. C'est donc `statut_entente` qui décide, et lui seul.
    a_traiter = vue["Entente"].isin(STATUTS_A_TRAITER)
    # Un achat RÉGLÉ ne se renouvelle pas : le fauteuil est payé, il est au
    # patient. Son entente a servi, elle peut expirer sans que personne
    # n'ait rien à faire — l'y laisser noierait les vraies échéances sous
    # des dossiers clos.
    a_traiter &= ~((vue["Mode"] == MODE_ACHAT)
                   & (vue["Facturation"] == STATUT_ACHAT_REGLE))
    return vue[a_traiter].reset_index(drop=True)


def en_attente_de_reponse(dossier: pd.DataFrame,
                          aujourdhui: Optional[date] = None,
                          alerte_j: int = ALERTE_RENOUVELLEMENT_J,
                          validite_defaut: int = VALIDITE_DEFAUT_MOIS
                          ) -> pd.DataFrame:
    """Les demandes parties à la caisse et restées sans réponse.

    Les plus anciennes d'abord : une demande qui dort depuis six semaines
    est une location que personne ne paie, et rien d'autre ne la rappelle.
    C'est aussi ce qui permet de dire au patient qui appelle depuis quand
    son dossier est parti, et par qui.
    """
    vue = vue_affichable(dossier, aujourdhui, TRI_ECHEANCE, alerte_j,
                         validite_defaut)
    if vue.empty:
        return vue
    attente = vue[vue["Entente"] == STATUT_DEMANDE_ENVOYEE].copy()
    if attente.empty:
        return attente
    attente["_attente"] = [-(j or 0) for j in attente["Attente (j)"]]
    return attente.sort_values("_attente", kind="stable").drop(
        columns=["_attente"]).reset_index(drop=True)


def sans_entente_requise(dossier: pd.DataFrame,
                         aujourdhui: Optional[date] = None,
                         alerte_j: int = ALERTE_RENOUVELLEMENT_J,
                         validite_defaut: int = VALIDITE_DEFAUT_MOIS
                         ) -> pd.DataFrame:
    """Le matériel loué hors caisse : aérosols et tensiomètres.

    Ils n'ont pas d'entente, pas d'échéance, pas de renouvellement — mais
    ils ont une CAUTION, et une caution est de l'argent encaissé qui
    appartient au patient tant qu'il n'a pas rendu l'appareil. C'est la
    seule chose à suivre, et elle n'a sa place dans aucune des autres
    listes.
    """
    vue = vue_affichable(dossier, aujourdhui, TRI_PATIENT, alerte_j,
                         validite_defaut)
    if vue.empty:
        return pd.DataFrame(columns=COLONNES_VUE + ["Remboursement"])
    return vue[vue["Régime"] == REGIME_LIBRE].reset_index(drop=True)


def cautions_detenues(vue: pd.DataFrame) -> int:
    """Le total des cautions encaissées et pas encore rendues.

    Cet argent n'est pas à la pharmacie : il est chez elle. Le compter
    évite qu'un appareil rendu il y a six mois laisse 5 000 F dans la
    caisse de quelqu'un d'autre.
    """
    if vue is None or vue.empty:
        return 0
    encore = [m for m, rendue in zip(vue["Caution (F)"],
                                     vue["Caution rendue le"])
              if rendue is None or pd.isna(rendue)]
    return int(sum(parser_montant(m) for m in encore))


def a_facturer(dossier: pd.DataFrame, aujourdhui: Optional[date] = None,
               periode_mois: int = PERIODE_FACTURATION_MOIS,
               alerte_j: int = ALERTE_RENOUVELLEMENT_J,
               validite_defaut: int = VALIDITE_DEFAUT_MOIS) -> pd.DataFrame:
    """Ce qui est dû : le mois des locations, et les achats jamais réglés.

    Jamais facturés compris : c'est le cas le plus facile à oublier,
    puisqu'aucune date ne vient le rappeler. Un achat livré et jamais
    facturé y reste jusqu'à ce qu'il soit réglé — puis il en sort pour de
    bon, contrairement à une location qui y revient chaque mois.
    """
    vue = vue_affichable(dossier, aujourdhui, TRI_ECHEANCE, alerte_j,
                         validite_defaut, periode_mois)
    if vue.empty:
        return vue
    return vue[vue["Facturation"].isin(STATUTS_A_FACTURER)].reset_index(
        drop=True)


def resume(dossier: pd.DataFrame, aujourdhui: Optional[date] = None,
           alerte_j: int = ALERTE_RENOUVELLEMENT_J,
           validite_defaut: int = VALIDITE_DEFAUT_MOIS,
           periode_mois: int = PERIODE_FACTURATION_MOIS) -> dict:
    """Les quelques nombres qui disent l'état du module d'un coup d'œil."""
    vue = vue_affichable(dossier, aujourdhui, TRI_ECHEANCE, alerte_j,
                         validite_defaut, periode_mois)
    if vue.empty:
        return {"dossiers": 0, "patients": 0, "locations": 0, "achats": 0,
                "a_renouveler": 0, "expirees": 0, "a_facturer": 0,
                "mois_dus": 0, "demandes_en_attente": 0, "dernier_mois": 0,
                "hors_caisse": 0, "cautions": 0}
    # « À renouveler » compte ce que la LISTE affiche, achats réglés exclus :
    # deux nombres qui prétendent dire la même chose et n'y arrivent pas
    # font douter des deux.
    renouvellements = a_renouveler(dossier, aujourdhui, alerte_j,
                                   validite_defaut)
    return {
        "dossiers": len(vue),
        "patients": len({cle_patient(p) for p in vue["Patient"]}),
        "locations": int((vue["Mode"] == MODE_LOCATION).sum()),
        "achats": int((vue["Mode"] == MODE_ACHAT).sum()),
        "a_renouveler": int((renouvellements["Entente"]
                             == STATUT_A_RENOUVELER).sum())
        if not renouvellements.empty else 0,
        "expirees": int((renouvellements["Entente"] == STATUT_EXPIREE).sum())
        if not renouvellements.empty else 0,
        "a_facturer": int(vue["Facturation"].isin(STATUTS_A_FACTURER).sum()),
        "mois_dus": int(pd.to_numeric(vue["Mois dus"],
                                      errors="coerce").fillna(0).sum()),
        "demandes_en_attente": int(
            (vue["Entente"] == STATUT_DEMANDE_ENVOYEE).sum()),
        "dernier_mois": int((vue["Entente"] == STATUT_DERNIER_MOIS).sum()),
        "hors_caisse": int((vue["Régime"] == REGIME_LIBRE).sum()),
        "cautions": cautions_detenues(vue),
    }


#: L'ordre de gravité des statuts d'entente. Le récapitulatif par patient
#: retient le PIRE de ses dossiers : si l'un de ses appareils n'est plus
#: pris en charge, c'est ce qu'il faut voir en ouvrant sa ligne — une
#: moyenne, ou le premier venu, cacherait exactement ce qui presse.
_GRAVITE = {STATUT_EXPIREE: 3, STATUT_A_RENOUVELER: 2,
            STATUT_SANS_ENTENTE: 1, STATUT_ENTENTE_VALIDE: 0}


def par_patient(dossier: pd.DataFrame, aujourdhui: Optional[date] = None,
                alerte_j: int = ALERTE_RENOUVELLEMENT_J,
                validite_defaut: int = VALIDITE_DEFAUT_MOIS,
                periode_mois: int = PERIODE_FACTURATION_MOIS) -> pd.DataFrame:
    """Une ligne par patient, locations ET achats confondus.

    C'est la vue qu'on ouvre quand le patient est au téléphone : il ne
    demande pas « où en est ma location de lit », il demande où il en est.
    Éclaté en deux listes, il fallait le chercher deux fois et recoller les
    réponses de tête — et c'est là qu'on oublie le second appareil.

    Le classement met en tête ceux dont une entente est tombée : à quinze
    patients la liste tient sur un écran, à soixante non.
    """
    vue = vue_affichable(dossier, aujourdhui, TRI_PATIENT, alerte_j,
                         validite_defaut, periode_mois)
    if vue.empty:
        return pd.DataFrame(columns=COLONNES_PATIENT)
    renouvellements = a_renouveler(dossier, aujourdhui, alerte_j,
                                   validite_defaut)
    a_renouveler_par_patient = (
        {} if renouvellements.empty
        else renouvellements.groupby(
            [cle_patient(p) for p in renouvellements["Patient"]]).size().to_dict())

    lignes = []
    for cle in dict.fromkeys(cle_patient(p) for p in vue["Patient"]):
        siens = vue[[cle_patient(p) == cle for p in vue["Patient"]]]
        pire = max(siens["Entente"], key=lambda st: _GRAVITE.get(st, 0))
        lignes.append({
            "Patient": siens.iloc[0]["Patient"],
            "Locations": int((siens["Mode"] == MODE_LOCATION).sum()),
            "Achats": int((siens["Mode"] == MODE_ACHAT).sum()),
            "Entente": pire,
            "À renouveler": int(a_renouveler_par_patient.get(cle, 0)),
            "À facturer": int(siens["Facturation"].isin(
                STATUTS_A_FACTURER).sum()),
            "Mois dus": int(pd.to_numeric(siens["Mois dus"],
                                          errors="coerce").fillna(0).sum()),
            "Caution détenue (F)": cautions_detenues(siens),
        })
    recap = pd.DataFrame(lignes, columns=COLONNES_PATIENT)
    recap["_gravite"] = [-_GRAVITE.get(st, 0) for st in recap["Entente"]]
    recap["_nom"] = [cle_patient(p) for p in recap["Patient"]]
    return recap.sort_values(["_gravite", "_nom"], kind="stable").drop(
        columns=["_gravite", "_nom"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Mouvements sur les dossiers
# ---------------------------------------------------------------------------

def _index_dossier(dossier: pd.DataFrame, patient: str, materiel: str,
                   mode: Optional[str] = None):
    """Ligne de ce patient pour ce matériel, ou ``None``.

    Un patient peut louer deux appareils différents : c'est le COUPLE qui
    identifie le dossier, pas le seul nom.

    Le MODE en fait partie dès qu'il est précisé : on loue un fauteuil
    quelques mois, puis on l'achète. Ce sont deux dossiers — deux ententes,
    deux facturations — et les confondre écraserait l'historique de la
    location le jour de l'achat. Sans mode précisé, la première ligne du
    couple gagne : c'est ce qui permet aux gestes du comptoir de viser un
    dossier sans avoir à répéter son mode.
    """
    if dossier is None or dossier.empty:
        return None
    cible = (cle_patient(patient), cle_patient(materiel))
    for i, ligne in dossier.iterrows():
        if (cle_patient(ligne.get("Patient")),
                cle_patient(ligne.get("Matériel"))) != cible:
            continue
        if mode is None or parser_mode(ligne.get("Mode")) == mode:
            return i
    return None


def ajouter_dossier(dossier: pd.DataFrame, patient: str, materiel: str,
                    debut=None, entente=None,
                    validite_mois: int = VALIDITE_DEFAUT_MOIS,
                    derniere_facturation=None, notes: str = "",
                    mode: str = MODE_LOCATION, regime=None,
                    demande_le=None, demandee_par: str = "",
                    caution=None, commentaire: str = "") -> pd.DataFrame:
    """Ouvre un dossier, ou complète celui qui existe déjà.

    Rouvrir un dossier existant plutôt que d'en créer un second : deux
    lignes pour le même patient et le même appareil, c'est un historique
    coupé en deux et une échéance suivie sur la mauvaise.

    « Le même » s'entend À MODE ÉGAL : un fauteuil loué puis acheté fait
    deux dossiers, et le second ne doit pas effacer le premier.
    """
    if dossier is None or dossier.empty:
        dossier = dossier_vide()
    dossier = dossier.reindex(columns=COLONNES_DOSSIER).copy()
    patient, materiel = _texte(patient), _texte(materiel)
    mode = parser_mode(mode)
    if not patient or not materiel:
        return dossier

    # Le nom du matériel décide du régime et de la caution quand on ne les
    # précise pas : taper « Tensiomètre » suffit pour que le dossier parte
    # hors caisse avec ses 3 000 F. Ressaisir l'un et l'autre à chaque
    # appareil, c'est la ligne qu'on finit par oublier.
    regime = (parser_regime(regime) if regime is not None
              else regime_propose(materiel))
    caution = (parser_montant(caution) if caution is not None
               else caution_proposee(materiel))
    existant = _index_dossier(dossier, patient, materiel, mode)
    valeurs = {
        "Patient": patient, "Matériel": materiel, "Mode": mode,
        "Régime": regime,
        "Début de location": _iso(debut),
        "Demande le": _iso(demande_le),
        "Demandée par": _texte(demandee_par),
        "Entente préalable": _iso(entente),
        "Validité (mois)": _mois_texte(validite_mois),
        "Dernière facturation": _iso(derniere_facturation),
        "Caution (F)": str(caution) if caution else "",
        "Caution rendue le": "",
        "Commentaire entente": _texte(commentaire),
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
              colonne: str, valeur, mode: Optional[str] = None) -> pd.DataFrame:
    if dossier is None or dossier.empty:
        return dossier_vide()
    dossier = dossier.reindex(columns=COLONNES_DOSSIER).copy()
    indice = _index_dossier(dossier, patient, materiel, mode)
    if indice is not None:
        dossier.at[indice, colonne] = valeur
    return dossier


def enregistrer_demande(dossier: pd.DataFrame, patient: str, materiel: str,
                        envoyee_le=None, par: str = "",
                        mode: Optional[str] = None) -> pd.DataFrame:
    """La demande d'entente est partie : sa date, et QUI l'a envoyée.

    Le prénom n'est pas une formalité. Trois semaines plus tard, quand la
    caisse n'a toujours pas répondu, c'est la seule façon de savoir à qui
    demander ce qui a été envoyé — et si ça l'a vraiment été.
    """
    dossier = _modifier(dossier, patient, materiel, "Demande le",
                        _iso(envoyee_le or date.today()), mode)
    return _modifier(dossier, patient, materiel, "Demandée par",
                     _texte(par), mode)


def enregistrer_commentaire(dossier: pd.DataFrame, patient: str,
                            materiel: str, texte: str,
                            mode: Optional[str] = None) -> pd.DataFrame:
    """Une note sur le suivi de l'entente : relance, pièce manquante, refus.

    Séparée des notes du dossier : celles-ci décrivent la location,
    celui-là raconte le dossier CAFAT. Mélangés, on ne retrouve ni l'un ni
    l'autre trois mois plus tard.
    """
    return _modifier(dossier, patient, materiel, "Commentaire entente",
                     _texte(texte), mode)


def enregistrer_caution_rendue(dossier: pd.DataFrame, patient: str,
                               materiel: str, le=None,
                               mode: Optional[str] = None) -> pd.DataFrame:
    """L'appareil est revenu, la caution est rendue.

    Tant que cette date est vide, l'argent est encore à la pharmacie sans
    lui appartenir. C'est ce qui permet de dire, à tout moment, combien
    elle détient et pour qui.
    """
    return _modifier(dossier, patient, materiel, "Caution rendue le",
                     _iso(le or date.today()), mode)


def enregistrer_entente(dossier: pd.DataFrame, patient: str, materiel: str,
                        accordee_le, validite_mois: int = VALIDITE_DEFAUT_MOIS,
                        mode: Optional[str] = None) -> pd.DataFrame:
    """L'accord de la caisse est arrivé : sa date, et sa durée.

    Vaut pour un achat comme pour une location : la caisse donne son accord
    AVANT, dans les deux cas. Ce qui change est ce qui suit l'accord.
    """
    dossier = _modifier(dossier, patient, materiel, "Entente préalable",
                        _iso(accordee_le), mode)
    return _modifier(dossier, patient, materiel, "Validité (mois)",
                     _mois_texte(validite_mois), mode)


def enregistrer_facturation(dossier: pd.DataFrame, patient: str,
                            materiel: str, le=None,
                            mode: Optional[str] = None) -> pd.DataFrame:
    """Le mois vient d'être facturé : l'horloge repart de cette date.

    Pour un achat, cette date ne relance rien — elle CLÔT la facturation.
    C'est la même saisie, et c'est voulu : un seul geste au comptoir, la
    différence se lit dans le statut qui en résulte.
    """
    return _modifier(dossier, patient, materiel, "Dernière facturation",
                     _iso(le or date.today()), mode)


def supprimer_dossier(dossier: pd.DataFrame, patient: str, materiel: str,
                      mode: Optional[str] = None) -> pd.DataFrame:
    """La location est terminée, le matériel est revenu."""
    if dossier is None or dossier.empty:
        return dossier_vide()
    dossier = dossier.reindex(columns=COLONNES_DOSSIER).copy()
    indice = _index_dossier(dossier, patient, materiel, mode)
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
    for colonne in ("Patient", "Matériel", "Notes", "Demandée par",
                    "Commentaire entente"):
        propre[colonne] = [_texte(v) for v in propre[colonne]]
    # Une case « Régime » vide suit le nom du matériel, comme à la saisie :
    # une ligne ajoutée avec le « + » pour un tensiomètre ne doit pas
    # réclamer une entente que personne ne demandera.
    propre["Régime"] = [
        parser_regime(r) if _texte(r) else regime_propose(m)
        for r, m in zip(propre["Régime"], propre["Matériel"])]
    propre["Caution (F)"] = [str(parser_montant(v)) if parser_montant(v)
                             else "" for v in propre["Caution (F)"]]
    # Une case « Mode » vide — celle d'une ligne ajoutée avec le « + » —
    # devient une location : c'est le mode surveillé, et donc le défaut
    # sans danger.
    propre["Mode"] = [parser_mode(v) for v in propre["Mode"]]
    for colonne in ("Début de location", "Entente préalable",
                    "Dernière facturation", "Demande le",
                    "Caution rendue le"):
        propre[colonne] = [_iso(v) for v in propre[colonne]]
    propre["Validité (mois)"] = [_mois_texte(v)
                                 for v in propre["Validité (mois)"]]
    garder = (propre["Patient"] != "") & (propre["Matériel"] != "")
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
                    "Dernière facturation", "Demande le",
                    "Caution rendue le"):
        tableau[colonne] = [_iso(v) for v in tableau[colonne]]
    # Le mode est normalisé À L'ÉCRITURE : un fichier relu ne doit jamais
    # contenir de troisième valeur, sans quoi ces lignes disparaîtraient
    # du sous-onglet des achats comme de celui des locations.
    if not tableau.empty:
        tableau["Mode"] = [parser_mode(v) for v in tableau["Mode"]]
        tableau["Régime"] = [
            parser_regime(r) if _texte(r) else regime_propose(m)
            for r, m in zip(tableau["Régime"], tableau["Matériel"])]
        tableau["Caution (F)"] = [str(parser_montant(v)) if parser_montant(v)
                                  else "" for v in tableau["Caution (F)"]]
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
    for colonne in ("Patient", "Matériel", "Notes", "Demandée par",
                    "Commentaire entente"):
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
