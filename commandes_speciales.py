# -*- coding: utf-8 -*-
"""Module 4 — Commandes spéciales (produits chers importés du continent).

En Nouvelle-Calédonie, les médicaments très chers ne sont pas au stock : ils
sont commandés à l'unité, par mail, et importés. Le délai est de trois
semaines à un mois. Deux horloges tournent alors en parallèle pour chaque
patient, et c'est de leur décalage que vient tout l'intérêt du suivi :

1. **l'approvisionnement** part de l'envoi du mail et dure le délai
   d'import — c'est elle qui dit quand la boîte arrivera ;
2. **la facturation** part de la dernière facturation et dure 22 jours,
   minimum imposé par la caisse — c'est elle qui dit quand on peut
   encaisser.

Facturer tous les 22 jours va plus vite que la consommation réelle
(une boîte par mois environ). Ce décalage est ce qui permet à la fois
d'avancer la trésorerie — indispensable sur des produits à ce prix, payés
au grossiste avant d'être remboursés — et de constituer la **boîte
d'avance** qui absorbe le mois d'import. Sans cette avance, le patient
attend l'avion.

Un dossier = un patient + un médicament, suivi dans le temps. Les dates y
sont mises à jour au fil des commandes et des facturations.

ISOLATION : ce module ne lit ni le cadencier, ni les ruptures, ni
l'inventaire du stock fermé. Le rapprochement avec les boîtes physiques est
fait par l'appelant, qui lui passe l'inventaire — le module ne va rien
chercher tout seul.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

import stockage_partage

_journal = logging.getLogger("pharmacie.commandes_speciales")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

COLONNES_DOSSIER = [
    "Patient", "Nom du produit", "Code CIP", "Boîtes en main",
    "Envoi du mail", "Réception", "Dernière facturation", "Notes",
]

#: Intervalle minimum imposé par la caisse entre deux facturations d'un même
#: patient pour un même produit. C'est la contrainte autour de laquelle tout
#: le module est construit.
DELAI_FACTURATION_J = 22

#: Délai d'import retenu tant qu'aucune réception n'a encore été observée
#: pour ce produit. Volontairement pessimiste : trois semaines à un mois,
#: on retient le haut. Sous-estimer ferait commander trop tard, et le
#: patient attendrait l'avion.
DELAI_IMPORT_DEFAUT_J = 30

#: Nombre de boîtes qu'on veut avoir en main en permanence.
AVANCE_CIBLE_DEFAUT = 1

STATUT_FACTURABLE = "🟢 Facturable"
STATUT_ATTENTE_FACTURATION = "🟡 À attendre"
STATUT_JAMAIS_FACTURE = "⚪ Jamais facturé"

STATUT_RIEN_EN_COURS = "⚪ Rien en cours"
STATUT_EN_TRANSIT = "🔵 En transit"
STATUT_RETARD = "🔴 En retard"
STATUT_RECU = "🟢 Reçu"

#: Au-delà du délai habituel PLUS cette marge, la commande est dite en
#: retard. La marge évite de crier au loup pour deux jours d'écart : les
#: délais d'import ne sont pas réguliers.
MARGE_RETARD_J = 5

#: Ordres d'affichage. Chacun répond à un geste : encaisser, commander,
#: ou retrouver un patient dans la liste.
TRI_FACTURATION = "Facturation (au plus tôt)"
TRI_PATIENT = "Patient (A → Z)"
TRI_COMMANDE = "Commande (la plus urgente)"
TRIS = (TRI_FACTURATION, TRI_COMMANDE, TRI_PATIENT)


def dossier_vide() -> pd.DataFrame:
    """Tableau neuf, colonnes déjà en place."""
    tableau = pd.DataFrame(columns=COLONNES_DOSSIER)
    return tableau.astype({"Boîtes en main": "int64"}, errors="ignore")


# ---------------------------------------------------------------------------
# Lecture des saisies
# ---------------------------------------------------------------------------

def _texte(valeur) -> str:
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return ""
    return str(valeur).strip()


def normaliser_cip(valeur) -> str:
    """Ne garde que les chiffres : la douchette et le clavier convergent."""
    return re.sub(r"\D", "", _texte(valeur))


def cle_patient(valeur) -> str:
    """Forme comparable d'un nom de patient : sans accent, sans casse.

    « Mme Léa DUPONT » et « lea dupont » désignent la même personne. Sans
    cette normalisation, un dossier serait créé deux fois et les 22 jours
    seraient comptés depuis la mauvaise date — donc facturés trop tôt.
    """
    nu = unicodedata.normalize("NFKD", _texte(valeur))
    nu = "".join(c for c in nu if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", nu).strip().upper()


def parser_date(valeur) -> Optional[date]:
    """Date saisie à la main → date, ou ``None`` si illisible.

    Accepte les chiffres seuls (``12082026``), les formats français et
    l'ISO. Les mêmes tolérances que la péremption du stock fermé : sur un
    comptoir, taper les barres obliques est du temps perdu.
    """
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    texte = _texte(valeur)
    if not texte:
        return None
    chiffres = re.sub(r"\D", "", texte)
    if len(chiffres) == 8:
        for essai in ((chiffres[:2], chiffres[2:4], chiffres[4:]),
                      (chiffres[6:], chiffres[4:6], chiffres[:4])):
            try:
                return date(int(essai[2]), int(essai[1]), int(essai[0]))
            except ValueError:
                continue
    for format_ in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d",
                    "%d/%m/%y"):
        try:
            return datetime.strptime(texte, format_).date()
        except ValueError:
            continue
    return None


def _entier(valeur) -> int:
    nombre = pd.to_numeric(pd.Series([valeur]), errors="coerce").fillna(0)
    return max(0, int(nombre.iloc[0]))


# ---------------------------------------------------------------------------
# Les deux horloges
# ---------------------------------------------------------------------------

def facturable_le(derniere_facturation) -> Optional[date]:
    """Première date à laquelle la caisse acceptera la prochaine facture.

    ``None`` si le patient n'a jamais été facturé : il l'est alors dès
    aujourd'hui, sans attendre.
    """
    precedente = parser_date(derniere_facturation)
    if precedente is None:
        return None
    return precedente + timedelta(days=DELAI_FACTURATION_J)


def jours_avant_facturation(derniere_facturation,
                            aujourdhui: Optional[date] = None) -> int:
    """Jours restants avant de pouvoir facturer. 0 si c'est possible.

    Jamais négatif : « facturable depuis 40 jours » ne se distingue pas de
    « facturable » pour la décision à prendre, et un nombre négatif dans une
    colonne se lit mal.
    """
    aujourdhui = aujourdhui or date.today()
    prochaine = facturable_le(derniere_facturation)
    if prochaine is None:
        return 0
    return max(0, (prochaine - aujourdhui).days)


def statut_facturation(derniere_facturation,
                       aujourdhui: Optional[date] = None) -> str:
    if parser_date(derniere_facturation) is None:
        return STATUT_JAMAIS_FACTURE
    if jours_avant_facturation(derniere_facturation, aujourdhui) == 0:
        return STATUT_FACTURABLE
    return STATUT_ATTENTE_FACTURATION


def delai_observe(envoi, reception) -> Optional[int]:
    """Jours réellement écoulés entre le mail et la réception.

    C'est la mesure qui remplace « trois semaines à un mois » par un
    chiffre. ``None`` s'il manque une date, ou si la réception précède
    l'envoi (saisie inversée) — un délai négatif fausserait la moyenne
    plus sûrement qu'une donnée absente.
    """
    depart, arrivee = parser_date(envoi), parser_date(reception)
    if depart is None or arrivee is None or arrivee < depart:
        return None
    return (arrivee - depart).days


def delai_habituel(dossier: pd.DataFrame, cip: str = "",
                   defaut: int = DELAI_IMPORT_DEFAUT_J) -> int:
    """Délai d'import retenu pour ce produit, mesuré sur les dossiers.

    La **médiane** et non la moyenne : une commande oubliée trois mois dans
    un carton tirerait une moyenne vers le haut et ferait commander bien
    trop tôt pour tous les autres patients.

    À défaut de mesure pour ce produit précis, on prend celle de tous les
    produits ; à défaut de toute mesure, le défaut pessimiste.
    """
    if dossier is None or dossier.empty:
        return defaut
    mesures = []
    cible = normaliser_cip(cip)
    for _, ligne in dossier.iterrows():
        observe = delai_observe(ligne.get("Envoi du mail"),
                               ligne.get("Réception"))
        if observe is None:
            continue
        mesures.append((normaliser_cip(ligne.get("Code CIP")), observe))
    if cible:
        propres = [j for code, j in mesures if code == cible]
        if propres:
            return int(pd.Series(propres).median())
    tous = [j for _, j in mesures]
    return int(pd.Series(tous).median()) if tous else defaut


def commande_en_cours(envoi, reception) -> bool:
    """Un mail parti et rien de reçu depuis : une boîte est en route.

    La réception ANTÉRIEURE à l'envoi signifie qu'un nouveau cycle a
    commencé — la date de réception est celle de la boîte précédente.
    """
    depart, arrivee = parser_date(envoi), parser_date(reception)
    if depart is None:
        return False
    return arrivee is None or arrivee < depart


def statut_commande(envoi, reception, delai: int = DELAI_IMPORT_DEFAUT_J,
                    aujourdhui: Optional[date] = None) -> str:
    aujourdhui = aujourdhui or date.today()
    depart = parser_date(envoi)
    if depart is None:
        return STATUT_RIEN_EN_COURS
    if not commande_en_cours(envoi, reception):
        return STATUT_RECU
    attente = (aujourdhui - depart).days
    if attente > delai + MARGE_RETARD_J:
        return STATUT_RETARD
    return STATUT_EN_TRANSIT


def jours_d_attente(envoi, reception,
                    aujourdhui: Optional[date] = None) -> Optional[int]:
    """Depuis combien de jours on attend cette boîte, ou ``None``."""
    if not commande_en_cours(envoi, reception):
        return None
    aujourdhui = aujourdhui or date.today()
    return max(0, (aujourdhui - parser_date(envoi)).days)


# ---------------------------------------------------------------------------
# La décision : faut-il commander aujourd'hui ?
# ---------------------------------------------------------------------------

def a_commander(ligne, delai: int = DELAI_IMPORT_DEFAUT_J,
                avance_cible: int = AVANCE_CIBLE_DEFAUT,
                aujourdhui: Optional[date] = None) -> tuple:
    """Faut-il commander pour ce dossier ? Renvoie ``(oui, raison)``.

    Le raisonnement, dans l'ordre où on le tiendrait à voix haute :

    - une boîte est déjà en route → rien à faire, elle arrive ;
    - il ne reste pas l'avance voulue → commander, et le dire ;
    - sinon, la boîte en main partira à la prochaine facturation : la
      suivante doit être là avant. Si le temps qui reste d'ici là est plus
      court que le délai d'import, il est **déjà** trop tard pour attendre.

    C'est ce dernier point qui fait le travail. Personne ne peut le tenir
    de tête sur trente dossiers, chacun avec ses dates.
    """
    aujourdhui = aujourdhui or date.today()
    if commande_en_cours(ligne.get("Envoi du mail"), ligne.get("Réception")):
        return False, "Une boîte est déjà en route."

    en_main = _entier(ligne.get("Boîtes en main"))
    if en_main < avance_cible:
        manque = avance_cible - en_main
        return True, (f"{en_main} boîte(s) en main pour {avance_cible} "
                      f"voulue(s) — il en manque {manque}.")

    jours = jours_avant_facturation(ligne.get("Dernière facturation"),
                                    aujourdhui)
    # La boîte en main est délivrée à la prochaine facturation ; celle
    # d'après doit donc être arrivée pour la facturation SUIVANTE.
    avant_rupture = jours + DELAI_FACTURATION_J * max(1, en_main - avance_cible + 1)
    if avant_rupture <= delai:
        return True, (f"Prochaine boîte nécessaire dans {avant_rupture} j, "
                      f"or l'import prend {delai} j.")
    return False, (f"Rien à faire : {avant_rupture} j d'autonomie pour "
                   f"{delai} j d'import.")


# ---------------------------------------------------------------------------
# Vue calculée
# ---------------------------------------------------------------------------

COLONNES_VUE = [
    "Facturation", "Patient", "Nom du produit", "Code CIP", "Boîtes en main",
    "Facturable le", "Jours avant facturation", "Commande",
    "Envoi du mail", "Réception", "Attente (j)", "Délai observé (j)",
    "À commander", "Dernière facturation", "Notes",
]


def _cle_tri(tri: str) -> list:
    """Colonnes de tri, ajoutées puis retirées après le classement."""
    if tri == TRI_PATIENT:
        return ["_patient", "_produit"]
    if tri == TRI_COMMANDE:
        return ["_commander", "_jours", "_patient"]
    return ["_jours", "_patient"]


def vue_affichable(dossier: pd.DataFrame, aujourdhui: Optional[date] = None,
                   tri: str = TRI_FACTURATION,
                   avance_cible: int = AVANCE_CIBLE_DEFAUT) -> pd.DataFrame:
    """Le dossier, enrichi de tout ce qui se déduit des dates.

    C'est ici que le tableau devient un outil : les cinq dates saisies à la
    main deviennent un statut, un compte à rebours et une décision.
    """
    aujourdhui = aujourdhui or date.today()
    if dossier is None or dossier.empty:
        return pd.DataFrame(columns=COLONNES_VUE)

    lignes = []
    for _, ligne in dossier.iterrows():
        cip = normaliser_cip(ligne.get("Code CIP"))
        delai = delai_habituel(dossier, cip)
        oui, raison = a_commander(ligne, delai, avance_cible, aujourdhui)
        jours = jours_avant_facturation(ligne.get("Dernière facturation"),
                                        aujourdhui)
        prochaine = facturable_le(ligne.get("Dernière facturation"))
        lignes.append({
            "Facturation": statut_facturation(
                ligne.get("Dernière facturation"), aujourdhui),
            "Patient": _texte(ligne.get("Patient")),
            "Nom du produit": _texte(ligne.get("Nom du produit")),
            "Code CIP": cip,
            "Boîtes en main": _entier(ligne.get("Boîtes en main")),
            "Facturable le": prochaine,
            "Jours avant facturation": jours,
            "Commande": statut_commande(ligne.get("Envoi du mail"),
                                        ligne.get("Réception"), delai,
                                        aujourdhui),
            "Envoi du mail": parser_date(ligne.get("Envoi du mail")),
            "Réception": parser_date(ligne.get("Réception")),
            "Attente (j)": jours_d_attente(ligne.get("Envoi du mail"),
                                           ligne.get("Réception"),
                                           aujourdhui),
            "Délai observé (j)": delai_observe(ligne.get("Envoi du mail"),
                                               ligne.get("Réception")),
            "À commander": "📦 Oui" if oui else "",
            "Dernière facturation": parser_date(
                ligne.get("Dernière facturation")),
            "Notes": _texte(ligne.get("Notes")),
            "_patient": cle_patient(ligne.get("Patient")),
            "_produit": _texte(ligne.get("Nom du produit")).upper(),
            "_jours": jours,
            "_commander": 0 if oui else 1,
        })

    vue = pd.DataFrame(lignes)
    # Colonnes pouvant être VIDES. Sans un type qui connaît l'absence,
    # pandas garde des objets Python et la case affiche « None » en plein
    # tableau — seule note anglo-saxonne d'un écran entièrement en français.
    # Les dates comptent autant que les nombres : un patient jamais facturé
    # n'a pas de dernière facturation, et c'est le cas le plus courant à
    # l'ouverture d'un dossier.
    for colonne in ("Attente (j)", "Délai observé (j)"):
        vue[colonne] = pd.array(vue[colonne], dtype="Int64")
    for colonne in ("Facturable le", "Envoi du mail", "Réception",
                    "Dernière facturation"):
        vue[colonne] = pd.to_datetime(vue[colonne], errors="coerce")
    vue = vue.sort_values(_cle_tri(tri),
                          kind="stable").reset_index(drop=True)
    return vue[COLONNES_VUE]


# ---------------------------------------------------------------------------
# Les trois listes du matin
# ---------------------------------------------------------------------------

def a_facturer_aujourdhui(dossier: pd.DataFrame,
                          aujourdhui: Optional[date] = None) -> pd.DataFrame:
    """La liste qui rapporte, et donc la première de l'écran."""
    vue = vue_affichable(dossier, aujourdhui, TRI_FACTURATION)
    if vue.empty:
        return vue
    return vue[vue["Facturation"].isin(
        (STATUT_FACTURABLE, STATUT_JAMAIS_FACTURE))].reset_index(drop=True)


def a_commander_maintenant(dossier: pd.DataFrame,
                           aujourdhui: Optional[date] = None,
                           avance_cible: int = AVANCE_CIBLE_DEFAUT
                           ) -> pd.DataFrame:
    """Sans quoi le patient attendra l'avion."""
    vue = vue_affichable(dossier, aujourdhui, TRI_COMMANDE, avance_cible)
    if vue.empty:
        return vue
    return vue[vue["À commander"] != ""].reset_index(drop=True)


def commandes_en_retard(dossier: pd.DataFrame,
                        aujourdhui: Optional[date] = None) -> pd.DataFrame:
    """Mail parti, rien reçu, délai dépassé : il faut relancer."""
    vue = vue_affichable(dossier, aujourdhui, TRI_COMMANDE)
    if vue.empty:
        return vue
    return vue[vue["Commande"] == STATUT_RETARD].reset_index(drop=True)


def resume(dossier: pd.DataFrame,
           aujourdhui: Optional[date] = None,
           avance_cible: int = AVANCE_CIBLE_DEFAUT) -> dict:
    """Les quatre chiffres du bandeau."""
    aujourdhui = aujourdhui or date.today()
    return {
        "dossiers": 0 if dossier is None else len(dossier),
        "patients": 0 if dossier is None or dossier.empty else
                    dossier["Patient"].map(cle_patient).nunique(),
        "a_facturer": len(a_facturer_aujourdhui(dossier, aujourdhui)),
        "a_commander": len(a_commander_maintenant(dossier, aujourdhui,
                                                  avance_cible)),
        "en_retard": len(commandes_en_retard(dossier, aujourdhui)),
    }


# ---------------------------------------------------------------------------
# Rapprochement avec les boîtes physiques du stock fermé
# ---------------------------------------------------------------------------

def rapprochement_stock(dossier: pd.DataFrame,
                        inventaire: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Compare, par code CIP, ce que les dossiers annoncent et ce qui est là.

    **Ce que ce rapprochement peut dire, et ce qu'il ne peut pas.** Le code
    CIP identifie un produit, pas une boîte : si deux patients suivent le
    même médicament, rien dans l'inventaire ne dit laquelle des boîtes est
    pour qui. On compare donc des TOTAUX par produit — et c'est déjà le
    contrôle utile : il attrape la boîte reçue mais jamais scannée, et la
    boîte scannée qui n'a été rattachée à aucun dossier.

    Prétendre attribuer les boîtes une à une serait inventer une
    information que les données ne contiennent pas.
    """
    colonnes = ["Code CIP", "Nom du produit", "Annoncé par les dossiers",
                "Présent au stock fermé", "Écart"]
    if dossier is None or dossier.empty:
        return pd.DataFrame(columns=colonnes)

    annonce, noms = {}, {}
    for _, ligne in dossier.iterrows():
        cip = normaliser_cip(ligne.get("Code CIP"))
        if not cip:
            continue
        annonce[cip] = annonce.get(cip, 0) + _entier(ligne.get("Boîtes en main"))
        noms.setdefault(cip, _texte(ligne.get("Nom du produit")))

    present = {}
    if inventaire is not None and not inventaire.empty:
        for _, ligne in inventaire.iterrows():
            cip = normaliser_cip(ligne.get("Code CIP"))
            if not cip:
                continue
            present[cip] = present.get(cip, 0) + _entier(ligne.get("Boîtes"))

    lignes = []
    for cip in sorted(set(annonce) | set(present)):
        if cip not in annonce:
            continue            # produit du stock fermé sans dossier : normal
        attendu, reel = annonce.get(cip, 0), present.get(cip, 0)
        lignes.append({
            "Code CIP": cip,
            "Nom du produit": noms.get(cip, ""),
            "Annoncé par les dossiers": attendu,
            "Présent au stock fermé": reel,
            "Écart": reel - attendu,
        })
    return pd.DataFrame(lignes, columns=colonnes)


def ecarts_a_verifier(rapprochement: pd.DataFrame) -> pd.DataFrame:
    """Les seules lignes du rapprochement qui demandent un geste."""
    if rapprochement is None or rapprochement.empty:
        return rapprochement if rapprochement is not None else pd.DataFrame()
    return rapprochement[rapprochement["Écart"] != 0].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Mouvements
# ---------------------------------------------------------------------------

def _index_dossier(dossier: pd.DataFrame, patient: str, cip: str,
                   produit: str = "") -> Optional[int]:
    """Retrouve la ligne d'un patient pour un produit.

    Le CIP identifie le produit quand il est là ; à défaut — produit saisi
    à la main, sans code — c'est le nom qui sert. Sans ce repli, chaque
    saisie créerait un nouveau dossier et les 22 jours repartiraient de
    zéro : on facturerait trop tôt.
    """
    if dossier is None or dossier.empty:
        return None
    cible_patient = cle_patient(patient)
    cible_cip = normaliser_cip(cip)
    cible_produit = _texte(produit).upper()
    for i, ligne in zip(dossier.index, dossier.to_dict("records")):
        if cle_patient(ligne.get("Patient")) != cible_patient:
            continue
        code = normaliser_cip(ligne.get("Code CIP"))
        if cible_cip and code:
            if code == cible_cip:
                return i
            continue
        if _texte(ligne.get("Nom du produit")).upper() == cible_produit:
            return i
    return None


def ajouter_dossier(dossier: pd.DataFrame, patient: str, produit: str,
                    cip: str = "", boites: int = 0,
                    envoi=None, reception=None, facturation=None,
                    notes: str = "") -> pd.DataFrame:
    """Crée un dossier, ou complète celui qui existe déjà.

    Deux dossiers pour le même patient et le même produit feraient repartir
    les 22 jours à zéro : c'est une facturation refusée par la caisse, ou
    pire, acceptée à tort.
    """
    if not _texte(patient) or not _texte(produit):
        return dossier if dossier is not None else dossier_vide()
    if dossier is None or dossier.empty:
        dossier = dossier_vide()
    dossier = dossier.reindex(columns=COLONNES_DOSSIER).copy()

    existant = _index_dossier(dossier, patient, cip, produit)
    valeurs = {
        "Patient": _texte(patient),
        "Nom du produit": _texte(produit),
        "Code CIP": normaliser_cip(cip),
        "Boîtes en main": _entier(boites),
        "Envoi du mail": _iso(envoi),
        "Réception": _iso(reception),
        "Dernière facturation": _iso(facturation),
        "Notes": _texte(notes),
    }
    if existant is not None:
        for colonne, valeur in valeurs.items():
            # On ne VIDE pas une case déjà remplie avec un blanc : compléter
            # un dossier ne doit pas effacer ce qu'on n'a pas retapé.
            if valeur not in ("", 0) or colonne == "Boîtes en main":
                dossier.at[existant, colonne] = valeur
        return dossier.reset_index(drop=True)
    return pd.concat([dossier, pd.DataFrame([valeurs])], ignore_index=True)


def _iso(valeur) -> str:
    jour = parser_date(valeur)
    return jour.isoformat() if jour else ""


def enregistrer_envoi(dossier: pd.DataFrame, patient: str, cip: str,
                      produit: str = "", jour: Optional[date] = None
                      ) -> pd.DataFrame:
    """Le mail de commande vient de partir : l'horloge d'import démarre."""
    return _modifier(dossier, patient, cip, produit,
                     {"Envoi du mail": _iso(jour or date.today())})


def enregistrer_reception(dossier: pd.DataFrame, patient: str, cip: str,
                          produit: str = "", jour: Optional[date] = None,
                          boites: int = 1) -> pd.DataFrame:
    """La boîte est arrivée : elle entre en main, le délai est mesuré."""
    index = _index_dossier(dossier, patient, cip, produit)
    if index is None:
        return dossier
    en_main = _entier(dossier.at[index, "Boîtes en main"]) + max(1, int(boites))
    return _modifier(dossier, patient, cip, produit,
                     {"Réception": _iso(jour or date.today()),
                      "Boîtes en main": en_main})


def enregistrer_facturation(dossier: pd.DataFrame, patient: str, cip: str,
                            produit: str = "", jour: Optional[date] = None,
                            boites: int = 1) -> pd.DataFrame:
    """Facturé et délivré : les 22 jours repartent, une boîte sort.

    La boîte quitte le stock en même temps que la facture part : c'est le
    même geste au comptoir, et les séparer laisserait l'avance fausse.
    """
    index = _index_dossier(dossier, patient, cip, produit)
    if index is None:
        return dossier
    en_main = max(0, _entier(dossier.at[index, "Boîtes en main"])
                  - max(1, int(boites)))
    return _modifier(dossier, patient, cip, produit,
                     {"Dernière facturation": _iso(jour or date.today()),
                      "Boîtes en main": en_main})


def _modifier(dossier: pd.DataFrame, patient: str, cip: str, produit: str,
              valeurs: dict) -> pd.DataFrame:
    index = _index_dossier(dossier, patient, cip, produit)
    if index is None:
        return dossier if dossier is not None else dossier_vide()
    dossier = dossier.reindex(columns=COLONNES_DOSSIER).copy()
    for colonne, valeur in valeurs.items():
        dossier.at[index, colonne] = valeur
    return dossier.reset_index(drop=True)


def supprimer_dossier(dossier: pd.DataFrame, patient: str, cip: str,
                      produit: str = "") -> pd.DataFrame:
    index = _index_dossier(dossier, patient, cip, produit)
    if index is None:
        return dossier
    return dossier.drop(index=index).reset_index(drop=True)


def normaliser_tableau_edite(tableau: pd.DataFrame) -> pd.DataFrame:
    """Ramène un tableau corrigé à l'écran à la forme du fichier.

    L'éditeur rend des colonnes de lecture (statuts, comptes à rebours) qui
    ne font pas partie du dossier : on ne garde que ce qui est saisi.
    """
    if tableau is None or tableau.empty:
        return dossier_vide()
    propre = tableau.reindex(columns=COLONNES_DOSSIER).copy()
    for colonne in ("Envoi du mail", "Réception", "Dernière facturation"):
        propre[colonne] = propre[colonne].map(_iso)
    propre["Boîtes en main"] = propre["Boîtes en main"].map(_entier)
    for colonne in ("Patient", "Nom du produit", "Notes"):
        propre[colonne] = propre[colonne].map(_texte)
    propre["Code CIP"] = propre["Code CIP"].map(normaliser_cip)
    # Une ligne sans patient NI produit est une ligne ajoutée puis
    # abandonnée dans l'éditeur : la garder polluerait le fichier.
    garde = (propre["Patient"] != "") | (propre["Nom du produit"] != "")
    return propre[garde].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Fichier
# ---------------------------------------------------------------------------

def sauver(dossier: pd.DataFrame, chemin: Path) -> None:
    tableau = (dossier_vide() if dossier is None or dossier.empty
               else dossier.reindex(columns=COLONNES_DOSSIER).copy())
    for colonne in ("Envoi du mail", "Réception", "Dernière facturation"):
        tableau[colonne] = tableau[colonne].map(_iso)
    stockage_partage.ecrire_atomiquement(tableau, Path(chemin))


def charger(chemin: Path) -> pd.DataFrame:
    """Relit les dossiers ; tableau vide si le fichier manque.

    Un fichier illisible n'empêche pas le module de s'ouvrir : mieux vaut
    un écran vide et un avertissement au journal qu'une application qui
    refuse de démarrer au comptoir.
    """
    chemin = Path(chemin)
    if not chemin.exists():
        return dossier_vide()
    try:
        tableau = pd.read_csv(chemin, sep=";", dtype=str,
                              encoding="utf-8-sig").fillna("")
    except Exception:
        _journal.warning("Commandes spéciales illisibles : %s", chemin)
        return dossier_vide()
    tableau = tableau.reindex(columns=COLONNES_DOSSIER).fillna("")
    tableau["Boîtes en main"] = tableau["Boîtes en main"].map(_entier)
    return tableau.reset_index(drop=True)


def appliquer_aux_dossiers(chemin: Path, mouvement,
                           delai_s: float = stockage_partage.DELAI_VERROU_S
                           ) -> stockage_partage.Ecriture:
    """Relit le fichier, applique le mouvement, réécrit — sous verrou.

    Plusieurs comptoirs peuvent enregistrer une facturation au même
    instant : sans cela, la seconde effacerait la première et les 22 jours
    repartiraient de la mauvaise date.
    """
    return stockage_partage.appliquer(chemin, charger, sauver, mouvement,
                                      delai_s)


def empreinte_fichier(chemin: Path) -> tuple:
    return stockage_partage.empreinte_fichier(chemin)


VerrouIndisponible = stockage_partage.VerrouIndisponible


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

def exporter_csv(dossier: pd.DataFrame, aujourdhui: Optional[date] = None,
                 tri: str = TRI_FACTURATION) -> bytes:
    """CSV français (« ; » + BOM) : Excel l'ouvre sans réglage."""
    vue = vue_affichable(dossier, aujourdhui, tri)
    return vue.to_csv(index=False, sep=";").encode("utf-8-sig")


def exporter_pdf(dossier: pd.DataFrame, titre: str = "Commandes spéciales",
                 aujourdhui: Optional[date] = None,
                 tri: str = TRI_FACTURATION) -> bytes:
    """Liste du matin en PDF, à poser à côté du téléphone.

    Lève ``ValueError`` avec un message clair si ReportLab manque — l'export
    CSV, lui, reste disponible.
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
                         "« pip install reportlab » dans le dossier de "
                         "l'application, ou utilisez l'export CSV.")

    import io as _io

    aujourdhui = aujourdhui or date.today()
    vue = vue_affichable(dossier, aujourdhui, tri)
    colonnes = ["Facturation", "Patient", "Nom du produit", "Boîtes en main",
                "Facturable le", "Commande", "À commander"]
    entetes = ["Statut", "Patient", "Produit", "En main", "Facturable le",
               "Commande", "À cmder"]

    styles = getSampleStyleSheet()
    cellule = ParagraphStyle("cellule", parent=styles["BodyText"],
                             fontSize=7.5, leading=9)
    tampon = _io.BytesIO()
    document = SimpleDocTemplate(
        tampon, pagesize=landscape(A4), topMargin=12 * mm,
        bottomMargin=12 * mm, leftMargin=10 * mm, rightMargin=10 * mm,
        title=titre)

    def texte_cellule(valeur) -> str:
        if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
            return ""
        if isinstance(valeur, date):
            return f"{valeur:%d/%m/%Y}"
        return str(valeur)

    donnees = [[Paragraph(f"<b>{escape(e)}</b>", cellule) for e in entetes]]
    for _, ligne in vue.iterrows():
        donnees.append([Paragraph(escape(texte_cellule(ligne[c])), cellule)
                        for c in colonnes])

    tableau = Table(donnees, repeatRows=1, hAlign="LEFT")
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d6d3")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f766e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]
    for i, (_, ligne) in enumerate(vue.iterrows(), start=1):
        if ligne["À commander"]:
            style.append(("BACKGROUND", (0, i), (-1, i),
                          colors.HexColor("#fff4e5")))
        elif ligne["Facturation"] == STATUT_FACTURABLE:
            style.append(("BACKGROUND", (0, i), (-1, i),
                          colors.HexColor("#eaf7f0")))
    tableau.setStyle(TableStyle(style))

    document.build([
        Paragraph(f"<b>{escape(titre)}</b>", styles["Title"]),
        Paragraph(f"Édité le {aujourdhui:%d/%m/%Y} — {len(vue)} dossier(s) · "
                  f"facturation possible tous les {DELAI_FACTURATION_J} jours",
                  styles["Normal"]),
        Spacer(1, 6 * mm), tableau])
    return tampon.getvalue()
