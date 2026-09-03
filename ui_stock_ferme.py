# -*- coding: utf-8 -*-
"""Interface du Module 3 — Gestion d'un stock interne.

Écran autonome : il ne dépend d'aucun fichier déposé (ni cadencier, ni
ruptures fournisseurs). Toute la logique métier est dans ``stock_ferme.py`` ;
ce fichier ne fait que l'habillage Streamlit.

Ergonomie visée : la douchette doit suffire. Un scan de Data Matrix qui
donne à la fois le CIP, la péremption et le lot d'un produit déjà connu
entre au stock **sans un clic** ; les autres cas ouvrent un formulaire de
complément pré-rempli.
"""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd
import streamlit as st

import base_medicaments
import commun
import stock_ferme
import ui_commun

_journal = logging.getLogger("pharmacie.stock_ferme.ui")

# Dossier des données de la pharmacie (déplaçable par PHARMACIE_DONNEES) :
# ces chemins ne dépendent PAS du répertoire de lancement, sinon la suite de
# tests écraserait l'inventaire réel.
INVENTAIRE_PATH = ui_commun.dossier_donnees() / "stock_ferme.csv"
REPERTOIRE_PATH = ui_commun.dossier_donnees() / "stock_ferme_produits.csv"
#: Table « code CIP → dénomination » issue de la base publique des
#: médicaments, conservée sur le poste pour fonctionner hors ligne.
BASE_MEDICAMENTS_PATH = ui_commun.dossier_donnees() / "base_medicaments.csv"

#: Au-delà, la base publique mérite d'être rafraîchie (nouvelles AMM,
#: arrêts de commercialisation).
ANCIENNETE_BASE_JOURS = 180

_MIME_CSV = "text/csv"
_MIME_PDF = "application/pdf"

#: La péremption s'affiche en MOIS/ANNÉE : c'est ce qui est imprimé sur les
#: cartons, et le jour prenait une place que la colonne n'a pas. Rien n'est
#: perdu — la date complète reste enregistrée, et « Jours restants », juste
#: à côté, donne le compte exact à la journée près.
_COLONNE_PEREMPTION = st.column_config.DateColumn(
    "Péremption", format="MM/YYYY", width="small", alignment="center")


def _colonnes_inventaire() -> dict:
    """Mise en forme des colonnes de l'inventaire, pour LES DEUX tableaux.

    Tout est **centré**. Par défaut, Streamlit colle les nombres au bord
    droit de leur colonne : sur des colonnes larges, le « 1 » des boîtes se
    retrouvait à des centimètres de son en-tête, et l'œil ne savait plus à
    quelle colonne il appartenait.

    Le tableau modifiable et la vue filtrée partagent cette déclaration :
    deux réglages séparés finiraient par diverger.
    """
    nombre = dict(min_value=0, step=1, width="small", alignment="center")
    return {
        "Statut": st.column_config.TextColumn(
            "Statut", width="small", alignment="center"),
        "Nom du produit": st.column_config.TextColumn(
            "Nom du produit", alignment="center"),
        # Pas de largeur imposée : un CIP tronqué (« 34009300000… ») ne
        # sert à rien, et c'est par lui qu'on identifie une boîte.
        "Code CIP": st.column_config.TextColumn(
            "Code CIP", alignment="center"),
        "Boîtes": st.column_config.NumberColumn("Boîtes", **nombre),
        "Unités par boîte": st.column_config.NumberColumn(
            "Unités/boîte", **nombre),
        "Unités en vrac": st.column_config.NumberColumn("Vrac", **nombre),
        "Total unités": st.column_config.NumberColumn(
            "Total unités", width="small", alignment="center"),
        "Péremption": _COLONNE_PEREMPTION,
        "Lot": st.column_config.TextColumn(
            "Lot", width="small", alignment="center"),
        # Date d'enregistrement : elle s'affichait en 2026-08-10, seule note
        # anglo-saxonne d'un écran entièrement en français.
        "Enregistré le": st.column_config.DateColumn(
            "Enregistré le", format="DD/MM/YYYY", width="small",
            alignment="center"),
        "Jours restants": st.column_config.NumberColumn(
            "Jours restants", width="small", alignment="center"),
    }

#: Colonnes modifiables directement dans le tableau.
_COLONNES_EDITABLES = ("Nom du produit", "Boîtes",
                       "Unités par boîte", "Unités en vrac", "Péremption",
                       "Lot")


# ---------------------------------------------------------------------------
# Mémoire de session (chargée une fois depuis le disque)
# ---------------------------------------------------------------------------

def _etat():
    """Inventaire et répertoire courants, relus dès qu'un autre poste écrit.

    Sur un serveur partagé, chaque poste a sa propre page et sa propre
    mémoire de session. Garder la photo prise à l'ouverture, c'est afficher
    un stock périmé et — bien pire — réenregistrer plus tard une version qui
    ignore les boîtes scannées ailleurs. On compare donc l'empreinte du
    fichier à chaque affichage : un simple ``stat``, et on relit seulement
    quand elle a bougé.
    """
    empreinte = stock_ferme.empreinte_fichier(INVENTAIRE_PATH)
    if ("sf_inventaire" not in st.session_state
            or st.session_state.get("sf_empreinte") != empreinte):
        premiere = "sf_inventaire" not in st.session_state
        st.session_state["sf_inventaire"] = stock_ferme.charger_inventaire(
            INVENTAIRE_PATH)
        st.session_state["sf_empreinte"] = empreinte
        if not premiere:
            # Les lignes ont changé de forme sous l'éditeur : ses corrections
            # en cours désignent des positions qui ne veulent plus rien dire.
            st.session_state["sf_generation"] = (
                st.session_state.get("sf_generation", 0) + 1)
        _journal.info("Stock interne — %d lot(s) relus depuis %s",
                      len(st.session_state["sf_inventaire"]), INVENTAIRE_PATH)

    empreinte_repertoire = stock_ferme.empreinte_fichier(REPERTOIRE_PATH)
    if ("sf_repertoire" not in st.session_state
            or st.session_state.get("sf_empreinte_repertoire")
            != empreinte_repertoire):
        st.session_state["sf_repertoire"] = stock_ferme.charger_repertoire(
            REPERTOIRE_PATH)
        st.session_state["sf_empreinte_repertoire"] = empreinte_repertoire
    return st.session_state["sf_inventaire"], st.session_state["sf_repertoire"]


def _base_chargee() -> tuple:
    """Les vues de la base publique : par code CIP, par nom, et le catalogue.

    Relues une seule fois par session, et à nouveau si le fichier a changé
    (mise à jour de la base) — 40 000 codes, inutile de les relire à chaque
    interaction. Toutes sont construites ensemble : elles viennent du même
    fichier, le lire trois fois serait payer trois fois.
    """
    empreinte = (BASE_MEDICAMENTS_PATH.stat().st_mtime
                 if BASE_MEDICAMENTS_PATH.exists() else 0)
    if st.session_state.get("sf_base_empreinte") != empreinte:
        table = base_medicaments.charger_table(BASE_MEDICAMENTS_PATH)
        index_noms = base_medicaments.index_par_nom(table)
        # Catalogue figé une fois pour toutes : c'est lui qui part dans le
        # navigateur pour la saisie assistée. Le recalculer à chaque
        # interaction le rendrait « nouveau » aux yeux de Streamlit, qui le
        # renverrait en entier au lieu d'une simple référence.
        catalogue = base_medicaments.catalogue(index_noms)
        st.session_state["sf_base_index"] = base_medicaments.index_par_cip(
            table)
        st.session_state["sf_base_noms"] = index_noms
        st.session_state["sf_base_catalogue"] = catalogue
        st.session_state["sf_base_par_libelle"] = {
            m["libelle"]: m for m in catalogue}
        st.session_state["sf_base_empreinte"] = empreinte
        _journal.info("Base des médicaments : %d code(s), %d présentation(s), "
                      "%d boîte(s) au catalogue",
                      len(st.session_state["sf_base_index"]),
                      len(index_noms), len(catalogue))
    return (st.session_state["sf_base_index"],
            st.session_state["sf_base_noms"])


def _index_base() -> dict:
    return _base_chargee()[0]


def _index_noms() -> list:
    return _base_chargee()[1]


def _catalogue() -> list:
    _base_chargee()
    return st.session_state["sf_base_catalogue"]


def _catalogue_par_libelle() -> dict:
    _base_chargee()
    return st.session_state["sf_base_par_libelle"]


def _memoriser(inventaire, empreinte=None) -> None:
    """Range en session l'inventaire qui vient d'être écrit, et son empreinte.

    Sans l'empreinte, le prochain affichage croirait qu'un autre poste a
    écrit et relirait pour rien ; pire, le tableau modifiable se croirait en
    conflit avec sa propre écriture.

    L'empreinte vient de l'écriture elle-même, relevée **sous le verrou** :
    la relire ici l'exposerait à un autre poste écrivant entre-temps, et le
    poste retiendrait le fichier de l'autre en croyant y voir le sien.
    """
    st.session_state["sf_inventaire"] = inventaire
    st.session_state["sf_empreinte"] = (
        empreinte if empreinte is not None
        else stock_ferme.empreinte_fichier(INVENTAIRE_PATH))
    # Change la clé de l'éditeur : ses corrections en cours ne doivent
    # pas être rejouées sur le tableau qui vient d'être réenregistré.
    st.session_state["sf_generation"] = (
        st.session_state.get("sf_generation", 0) + 1)


MESSAGE_VERROU = (
    "Un autre poste enregistre au même instant — rien n'a été modifié. "
    "Refaites le geste dans un instant.")

#: Le cas le plus fréquent, et de loin : le fichier est ouvert dans Excel.
#: Windows refuse alors de le remplacer, et sans ce message l'écran
#: afficherait une trace d'erreur en anglais au milieu du comptoir.
MESSAGE_FICHIER_BLOQUE = (
    "Impossible d'enregistrer : le fichier `{fichier}` est ouvert dans un "
    "autre programme (Excel, le plus souvent). Fermez-le, puis refaites le "
    "geste — rien n'a été perdu.")


def _memoriser_produit(**produit) -> None:
    """Ajoute un produit au répertoire du disque, sans écraser les autres."""
    try:
        ecriture = stock_ferme.appliquer_au_repertoire(
            REPERTOIRE_PATH,
            lambda courant: stock_ferme.memoriser_produit(courant, **produit))
    except stock_ferme.VerrouIndisponible:                   # pragma: no cover
        _journal.warning("Verrou du répertoire indisponible")
        return
    except OSError as erreur:
        # Le nom du produit n'est pas mémorisé, mais la boîte, elle, va
        # entrer au stock : on ne bloque pas le comptoir pour cela.
        _journal.error("Répertoire non enregistré : %s", erreur)
        return
    st.session_state["sf_repertoire"] = ecriture.tableau
    st.session_state["sf_empreinte_repertoire"] = ecriture.empreinte


def _appliquer(mouvement, produit=None):
    """Applique un mouvement à l'inventaire **du disque**, sous verrou.

    C'est le cœur du partage entre postes : on ne réenregistre pas la photo
    qu'on avait en mémoire (elle effacerait la boîte scannée à côté), on
    relit le fichier et on lui applique le geste — une boîte de plus, une de
    moins. Renvoie l'inventaire enregistré, ou ``None`` si le verrou n'a pas
    pu être pris (le message d'attente est alors déjà posé).
    """
    if produit is not None:
        _memoriser_produit(**produit)
    try:
        ecriture = stock_ferme.appliquer_a_l_inventaire(INVENTAIRE_PATH,
                                                        mouvement)
    except stock_ferme.VerrouIndisponible:
        _journal.warning("Verrou de l'inventaire indisponible")
        st.session_state["sf_message"] = ("avertissement", MESSAGE_VERROU)
        return None
    except OSError as erreur:
        _journal.error("Inventaire non enregistré : %s", erreur)
        st.session_state["sf_message"] = (
            "avertissement",
            MESSAGE_FICHIER_BLOQUE.format(fichier=INVENTAIRE_PATH.name))
        return None
    _memoriser(ecriture.tableau, ecriture.empreinte)
    return ecriture.tableau


def _enregistrer(inventaire=None, repertoire=None) -> None:
    """Écrit sur le disque : c'est la « mémoire » entre deux ouvertures.

    Réservé aux écritures qui remplacent délibérément le tout (remise à
    zéro, import du répertoire) ; un mouvement de stock passe par
    ``_appliquer``.
    """
    if inventaire is not None:
        try:
            # L'empreinte est relevée SOUS le verrou, comme partout ailleurs.
            with stock_ferme.verrou_fichier(INVENTAIRE_PATH):
                stock_ferme.sauver_inventaire(inventaire, INVENTAIRE_PATH)
                empreinte = stock_ferme.empreinte_fichier(INVENTAIRE_PATH)
        except stock_ferme.VerrouIndisponible:
            st.session_state["sf_message"] = ("avertissement", MESSAGE_VERROU)
            return
        except OSError as erreur:
            _journal.error("Inventaire non enregistré : %s", erreur)
            st.session_state["sf_message"] = (
                "avertissement",
                MESSAGE_FICHIER_BLOQUE.format(fichier=INVENTAIRE_PATH.name))
            return
        _memoriser(inventaire, empreinte)
    if repertoire is not None:
        st.session_state["sf_repertoire"] = repertoire
        try:
            with stock_ferme.verrou_fichier(REPERTOIRE_PATH):
                stock_ferme.sauver_repertoire(repertoire, REPERTOIRE_PATH)
                empreinte = stock_ferme.empreinte_fichier(REPERTOIRE_PATH)
        except stock_ferme.VerrouIndisponible:      # pragma: no cover
            _journal.warning("Verrou du répertoire indisponible")
            return
        except OSError as erreur:
            _journal.error("Répertoire non enregistré : %s", erreur)
            st.session_state["sf_message"] = (
                "avertissement",
                MESSAGE_FICHIER_BLOQUE.format(fichier=REPERTOIRE_PATH.name))
            return
        st.session_state["sf_empreinte_repertoire"] = empreinte


# ---------------------------------------------------------------------------
# Saisie
# ---------------------------------------------------------------------------

MODE_ENTREE = "➕ Entrée"
MODE_SORTIE = "➖ Sortie"

# Sortir une boîte entière ou quelques comprimés : ce n'est pas le même
# geste au comptoir, et l'inventaire ne se décrémente pas pareil.
UNITE_BOITE = "Boîtes entières"
UNITE_UNITE = "Unités (comprimés)"


def _garder_mode() -> None:
    """Empêche la déselection : recliquer le mode actif le laisse actif.

    Sans cela, un second clic sur « Entrée » (ou « Sortie ») le
    déselectionne et AUCUN des deux n'apparaît choisi — il faut cliquer sur
    l'autre pour s'en sortir, alors qu'un scan a toujours un sens.
    """
    if st.session_state.get("sf_mode") is None:
        st.session_state["sf_mode"] = st.session_state.get("sf_mode_choisi",
                                                           MODE_ENTREE)
    st.session_state["sf_mode_choisi"] = st.session_state["sf_mode"]


def _traiter_sortie(code) -> None:
    """Sortie de stock à la douchette : une boîte de moins, du bon lot.

    Un Data Matrix désigne la boîte précise ; un code-barres linéaire ne
    donne que le produit, et c'est alors le lot qui périme le plus tôt qui
    sort (FEFO).
    """
    # Le lot est choisi sur l'inventaire RELU sous verrou, pas sur celui
    # qu'affiche la page : entre l'affichage et le scan, un autre poste a pu
    # sortir la dernière boîte de ce lot.
    cible = {}

    def mouvement(courant):
        trouve = stock_ferme.lot_a_sortir(courant, cip=code.cip,
                                          peremption=code.peremption,
                                          lot=code.lot)
        if trouve is None:
            return None
        cible.update(trouve)
        return stock_ferme.retirer_entree(
            courant, trouve["cip"], trouve["nom"], trouve["peremption"],
            trouve["lot"], boites=1)

    if _appliquer(mouvement) is None:
        return
    if not cible:
        # Rien à sortir en BOÎTE ne veut pas dire rien à l'inventaire : il
        # peut rester les comprimés d'une boîte entamée. Le dire, plutôt
        # que d'envoyer chercher un produit qui est bien là.
        inventaire, _ = _etat()
        vrac = stock_ferme.vrac_sans_boite(inventaire, cip=code.cip)
        if vrac:
            st.session_state["sf_message"] = (
                "avertissement",
                f"Plus de boîte entière pour « {code.cip or code.brut} » — "
                f"il reste {vrac} unité(s) d'une boîte entamée. Passez par "
                "« ⌨️ Le code ne se lit pas ? Sortir à l'unité ? » pour les "
                "dispenser.")
            return
        st.session_state["sf_message"] = (
            "avertissement",
            f"Sortie impossible : « {code.cip or code.brut} » n'est pas à "
            "l'inventaire. Vérifiez le code, choisissez la boîte avec "
            "« ⌨️ Sortie manuelle », ou passez en mode Entrée pour "
            "l'enregistrer.")
        return

    reste = max(0, cible["boites"] - 1)
    peremption = (f"{cible['peremption']:%d/%m/%Y}" if cible["peremption"]
                  else "sans date")
    detail = (f"lot {cible['lot']}, " if cible["lot"] else "") + peremption
    avertissement = ("" if cible["exact"] else
                     " ⚠️ Le lot scanné n'était pas à l'inventaire — c'est la "
                     "boîte périmant le plus tôt qui a été sortie.")
    st.session_state["sf_message"] = (
        "ok" if cible["exact"] else "avertissement",
        f"➖ {cible['nom']} {cible['dosage']} — 1 boîte sortie ({detail}) · "
        f"reste {reste} boîte(s) sur ce lot." + avertissement)


def _traiter_scan() -> None:
    """Rappel de la douchette : elle tape le code puis valide (Entrée).

    Le champ est vidé immédiatement pour que le scan suivant puisse être
    saisi sans intervention de l'opérateur.
    """
    brut = st.session_state.get("sf_scan", "")
    st.session_state["sf_scan"] = ""
    if not str(brut).strip():
        return

    code = stock_ferme.parser_code_scanne(brut)
    # Seul le répertoire est lu ici : l'inventaire, lui, n'est jamais
    # manipulé de mémoire — chaque mouvement le relit sur le disque.
    _, repertoire = _etat()

    # On lit le mode RETENU, pas la valeur brute du widget : celui-ci vaut
    # None quand on reclique dessus pour le déselectionner, et un scan ne
    # doit pas basculer silencieusement en entrée dans ce cas.
    if st.session_state.get("sf_mode_choisi", MODE_ENTREE) == MODE_SORTIE:
        st.session_state.pop("sf_en_attente", None)
        if not code.reconnu:
            st.session_state["sf_message"] = (
                "avertissement",
                f"Code non reconnu : « {code.brut} ». Utilisez « ⌨️ Sortie "
                "manuelle » pour choisir la boîte dans la liste.")
            return
        _traiter_sortie(code)
        return

    # Qui est ce produit ? Le répertoire de la pharmacie d'abord — c'est sa
    # propre vérité, éventuellement corrigée à la main. À défaut, la base
    # publique des médicaments identifie le CIP : le nom arrive alors en même
    # temps que le scan, sans rien demander.
    connu = stock_ferme.produit_connu(repertoire, code.cip)
    depuis_base = False
    if connu is None:
        nom_officiel = base_medicaments.chercher(_index_base(), code.cip)
        if nom_officiel:
            connu = {"nom": nom_officiel, "dosage": "", "unites_par_boite": 0}
            depuis_base = True

    # Boîte entièrement identifiée : elle entre au stock sans confirmation —
    # c'est le geste du comptoir.
    if (code.reconnu and code.peremption is not None and connu
            and st.session_state.get("sf_ajout_direct", True)):
        entree = stock_ferme.EntreeStock(
            cip=code.cip, nom=connu["nom"], dosage=connu["dosage"],
            boites=1, unites_par_boite=connu["unites_par_boite"],
            peremption=code.peremption, lot=code.lot)
        produit = None
        if depuis_base:
            # Le nom devient celui de la pharmacie : elle peut le corriger,
            # et l'identification ne dépendra plus de la base ensuite.
            produit = {"cip": code.cip, "nom": connu["nom"]}
        if _appliquer(lambda courant: stock_ferme.ajouter_entree(
                courant, entree), produit=produit) is None:
            return
        st.session_state["sf_message"] = (
            "ok", f"➕ {connu['nom']} {connu['dosage']} — 1 boîte "
                  f"(péremption {code.peremption:%d/%m/%Y}"
                  + (f", lot {code.lot}" if code.lot else "") + ")"
                  + (" · nom repris de la base publique des médicaments"
                     if depuis_base else ""))
        st.session_state.pop("sf_en_attente", None)
        return

    # Sinon : formulaire de complément, pré-rempli avec ce qu'on sait déjà.
    # Une fiche déjà ouverte sur un AUTRE produit serait remplacée sans
    # bruit : on le signale, sinon la boîte précédente est oubliée.
    precedente = st.session_state.get("sf_en_attente")
    abandonnee = (precedente is not None
                  and (precedente.get("cip"), precedente.get("brut"))
                  != (code.cip, code.brut))

    # Ce n'est pas un code : c'est très probablement un NOM tapé au clavier.
    # Si la base ne connaît qu'UNE boîte portant ce nom, il n'y a rien à
    # choisir — on remplit. Sinon on renvoie vers la liste 🔎, qui montre
    # les dosages et les conditionnements côte à côte.
    index_noms = [] if code.reconnu else _index_noms()
    propositions = (base_medicaments.preselectionner(index_noms, brut)
                    ["resultats"] if index_noms else [])

    st.session_state["sf_en_attente"] = {
        "cip": code.cip,
        # Même quand la fiche s'ouvre (pas de péremption, ajout direct
        # désactivé…), le nom trouvé dans la base est déjà là : il n'y a
        # plus qu'à valider. Et ce qui a été tapé à la main sert de nom :
        # le retaper dans la fiche juste en dessous n'aurait aucun sens.
        "nom": ((connu or {}).get("nom", "")
                or ("" if code.reconnu else str(brut).strip())),
        "dosage": (connu or {}).get("dosage", ""),
        "unites_par_boite": (connu or {}).get("unites_par_boite", 0),
        "peremption": code.peremption,
        "lot": code.lot,
        "brut": code.brut,
        "reconnu": code.reconnu,
    }
    rappel = (" La fiche précédente, non validée, a été abandonnée."
              if abandonnee else "")
    if len(propositions) == 1:
        # Une seule boîte porte ce nom : faire choisir entre une seule
        # proposition n'aurait aucun sens.
        _choisir_medicament(propositions[0])
        if rappel:
            niveau, texte = st.session_state["sf_message"]
            st.session_state["sf_message"] = (niveau, texte + rappel)
    elif propositions:
        st.session_state["sf_message"] = (
            "ok", f"{len(propositions)} boîte(s) portent le nom "
                  f"« {str(brut).strip()} » — choisissez la vôtre dans la "
                  "liste 🔎 ci-dessous : le dosage et le conditionnement y "
                  "figurent." + rappel)
    elif not code.reconnu and not index_noms:
        # Rien à proposer parce qu'il n'y a rien à chercher DEDANS : le dire,
        # plutôt que de laisser croire que le nom tapé est en cause.
        st.session_state["sf_message"] = (
            "avertissement",
            f"« {code.brut} » n'est pas un code-barres, et la base publique "
            "des médicaments n'est pas installée sur ce poste — il n'y a donc "
            "rien à proposer. Installez-la (encadré ci-dessous) ou complétez "
            "la fiche à la main." + rappel)
    elif not code.reconnu:
        # La base est là et ne connaît pas ce nom : ne JAMAIS rester muet,
        # c'est ce qui fait croire que l'application ne réagit pas.
        st.session_state["sf_message"] = (
            "avertissement",
            f"Aucun médicament trouvé pour « {code.brut} » dans la base "
            "publique. Vérifiez l'orthographe, essayez le seul nom de marque "
            "— ou complétez la fiche ci-dessous, elle sera mémorisée pour les "
            "prochains scans." + rappel)
    elif abandonnee:
        st.session_state["sf_message"] = ("avertissement", rappel.strip())
    else:
        st.session_state["sf_message"] = None


def _saisie_manuelle_vierge() -> None:
    st.session_state["sf_en_attente"] = {
        "cip": "", "nom": "", "dosage": "", "unites_par_boite": 0,
        "peremption": None, "lot": "", "brut": "", "reconnu": True}
    st.session_state["sf_message"] = None


def _choisir_medicament(medicament: dict) -> None:
    """Reprend un médicament du catalogue dans la fiche d'ajout."""
    attente = dict(st.session_state.get("sf_en_attente") or {})
    attente.update({
        "cip": medicament["cip"],
        # La dénomination officielle porte déjà le dosage (« DOLIPRANE
        # 1000 mg, comprimé ») : la scinder en deux champs reviendrait à
        # deviner où couper.
        "nom": medicament["nom"],
        "unites_par_boite": medicament.get("unites_par_boite", 0),
    })
    for champ, defaut in (("dosage", ""), ("peremption", None), ("lot", ""),
                          ("brut", ""), ("reconnu", True)):
        attente.setdefault(champ, defaut)
    st.session_state["sf_en_attente"] = attente
    st.session_state["sf_message"] = (
        "ok", f"{medicament.get('libelle') or medicament['nom']} — il ne "
              "reste que la date de péremption à saisir.")


def _medicament_choisi_dans_la_liste() -> None:
    """Une boîte vient d'être choisie dans la liste : la fiche est remplie.

    En un seul geste — le nom, le dosage et le conditionnement sont dans la
    même ligne. C'est ce qui remplace l'ancien parcours en deux temps
    (choisir un nom, puis une présentation, puis valider).
    """
    libelle = st.session_state.get("sf_auto_nom")
    # Remis à zéro tout de suite : sans cela, rechoisir la MÊME boîte après
    # coup ne déclencherait rien, la valeur du menu n'ayant pas changé.
    st.session_state["sf_auto_nom"] = None
    medicament = _catalogue_par_libelle().get(libelle)
    if medicament:
        _choisir_medicament(medicament)


def _saisie_assistee() -> None:
    """Liste déroulante cherchable : les propositions viennent à la frappe.

    C'est le navigateur qui filtre, pas le serveur : le catalogue lui est
    envoyé une fois, et la liste se réduit **dès les premières lettres**,
    sans validation ni aller-retour. Un champ texte ordinaire ne peut pas le
    faire — Streamlit n'y réagit qu'à la validation, et l'écran semblait
    alors ne rien faire.

    Chaque ligne porte le nom, le dosage ET la taille de la boîte : taper
    « doliprane 1000 » puis choisir suffit à tout renseigner, sans second
    écran de confirmation.
    """
    catalogue = _catalogue()
    if not catalogue:
        return          # base absente : l'encadré ci-dessous le dit déjà
    st.selectbox(
        "Médicament", [m["libelle"] for m in catalogue], index=None,
        key="sf_auto_nom", on_change=_medicament_choisi_dans_la_liste,
        label_visibility="collapsed",
        placeholder=f"🔎 Tapez le nom du médicament, puis le dosage pour "
                    f"affiner ({len(catalogue)} boîtes référencées)")
def _basculer_sortie_manuelle() -> None:
    """Ouvre (ou referme) le choix de la boîte à sortir à la main."""
    st.session_state["sf_sortie_manuelle"] = not st.session_state.get(
        "sf_sortie_manuelle", False)
    st.session_state["sf_message"] = None


def _passer_en_entree() -> None:
    """Bascule en mode Entrée depuis un message d'aide.

    Les deux clés bougent ensemble : ``sf_mode`` est celle du sélecteur,
    ``sf_mode_choisi`` la mémoire qui survit à une déselection.
    """
    st.session_state["sf_mode"] = MODE_ENTREE
    st.session_state["sf_mode_choisi"] = MODE_ENTREE
    st.session_state["sf_sortie_manuelle"] = False


def _panneau_sortie_manuelle(inventaire: pd.DataFrame, aujourdhui: date,
                             tri: str) -> None:
    """Retirer une boîte — ou quelques unités — en la désignant dans la liste.

    Une étiquette abîmée, une boîte reconditionnée, un produit sans
    code-barres : la douchette ne lit pas tout, et il n'y avait alors
    aucune façon de sortir une boîte — le bouton de saisie manuelle était
    purement et simplement désactivé en mode Sortie.

    C'est aussi le seul chemin pour une sortie **à l'unité** : la douchette
    lit une boîte, pas dix comprimés. Dispenser à l'unité en retirant la
    boîte entière ferait disparaître de l'inventaire les comprimés qui
    restent réellement dans l'armoire.
    """
    lots = stock_ferme.lots_sortables(inventaire, aujourdhui, tri)
    if not lots:
        st.info("Aucune boîte à sortir : l'inventaire est vide.")
        return

    with st.container(border=True):
        st.markdown("**Choisissez la boîte à sortir**")
        choix = st.selectbox(
            "Boîte à sortir", range(len(lots)),
            format_func=lambda i: lots[i]["libelle"],
            key="sf_sortie_choix", label_visibility="collapsed")
        lot = lots[choix]

        # Ce que ce lot permet réellement. Une boîte entamée n'a plus de
        # boîte pleine mais garde des comprimés ; un produit sans
        # conditionnement connu a des boîtes mais aucune unité comptable.
        # Proposer les deux dans les deux cas mènerait à un maximum de zéro.
        possibles = ([UNITE_BOITE] if lot["boites"] > 0 else []) + (
            [UNITE_UNITE] if lot["unites"] > 0 else [])
        if len(possibles) > 1:
            unite = st.radio(
                "Retirer en", possibles, horizontal=True,
                key=f"sf_sortie_unite_{choix}",
                help="À l'unité, on entame une boîte : dispenser 10 "
                     "comprimés d'une boîte de 30 en laisse 20 en vrac.")
        else:
            unite = possibles[0]
            st.caption(
                f"Ce lot se sort {'à la boîte' if unite == UNITE_BOITE else 'à l’unité'}"
                + (" (il ne reste que des unités en vrac)."
                   if unite == UNITE_UNITE else
                   " (le conditionnement de ce produit n'est pas renseigné, "
                   "les unités ne peuvent pas être comptées)."))

        a_l_unite = unite == UNITE_UNITE
        maximum = lot["unites"] if a_l_unite else lot["boites"]
        colonne_nombre, colonne_bouton = st.columns([1, 2])
        # Le maximum est le stock du lot : proposer davantage, c'est
        # promettre une sortie que l'inventaire ne peut pas honorer. La clé
        # porte le lot ET l'unité : sans cela, « 12 » saisi sur un lot bien
        # fourni resterait affiché sur le lot suivant, au-dessus de son
        # propre maximum.
        combien = colonne_nombre.number_input(
            "Unités à retirer" if a_l_unite else "Boîtes à retirer",
            min_value=1, max_value=maximum, value=1, step=1,
            key=f"sf_sortie_combien_{choix}_{a_l_unite:d}")
        colonne_bouton.markdown("<div style='height:1.8rem'></div>",
                                unsafe_allow_html=True)
        if colonne_bouton.button("➖ Retirer du stock", type="primary",
                                 use_container_width=True):
            # Le stock réel est celui du disque : un autre poste a pu retirer
            # des boîtes depuis que cette liste s'est affichée. On retire ce
            # qu'on peut, et on annonce ce qui a été retiré — pas ce qui
            # avait été demandé.
            retire = {"nombre": 0, "reste": 0}

            def mouvement(courant, lot=lot, combien=int(combien),
                          a_l_unite=a_l_unite):
                if a_l_unite:
                    disponible = stock_ferme.unites_disponibles(
                        courant, lot["cip"], lot["nom"], lot["peremption"],
                        lot["lot"])
                    if disponible == 0:
                        retire.update(nombre=0, reste=0)
                        return None
                    apres, pris = stock_ferme.sortir_unites(
                        courant, lot["cip"], lot["nom"], lot["peremption"],
                        lot["lot"], min(combien, disponible))
                    retire.update(nombre=pris, reste=disponible - pris)
                    return apres if pris else None
                disponible = stock_ferme.stock_du_lot(
                    courant, lot["cip"], lot["nom"], lot["peremption"],
                    lot["lot"])
                nombre = min(combien, disponible)
                retire.update(nombre=nombre, reste=disponible - nombre)
                if nombre == 0:
                    return None
                return stock_ferme.retirer_entree(
                    courant, lot["cip"], lot["nom"], lot["peremption"],
                    lot["lot"], boites=nombre)

            if _appliquer(mouvement) is None:
                # Verrou indisponible : le panneau reste ouvert, avec le
                # même choix déjà fait — il n'y a qu'à recliquer.
                st.rerun()
            sorties = retire["nombre"]
            mot = "unité" if a_l_unite else "boîte"
            peremption = (f"{lot['peremption']:%d/%m/%Y}" if lot["peremption"]
                          else "sans date")
            if sorties == 0:
                st.session_state["sf_message"] = (
                    "avertissement",
                    f"{lot['nom']} — ce lot n'a plus de {mot} à sortir "
                    "(un autre poste vient de le vider).")
            else:
                st.session_state["sf_message"] = (
                    "ok", f"➖ {lot['nom']} {lot['dosage']} — {sorties} "
                          f"{mot}(s) sortie(s) ({peremption}) · reste "
                          f"{retire['reste']} {mot}(s) sur ce lot."
                          + ("" if sorties == int(combien) else
                             " ⚠️ Moins que demandé : le stock avait changé."))
            st.session_state["sf_sortie_manuelle"] = False
            st.rerun()


def _detail_code(brut: str) -> str:
    """Décomposition lisible du code scanné, champ GS1 par champ GS1."""
    code = stock_ferme.parser_code_scanne(brut)
    visible = brut.replace("\x1d", "⟨sép⟩")
    lignes = [f"Contenu transmis par la douchette ({len(brut)} caractères) :",
              f"  {visible}", ""]
    if code.format == "datamatrix":
        lignes.append("Décodage GS1 :")
        lignes.append(f"  01  GTIN / code produit ... {code.gtin} → CIP "
                      f"{code.cip}")
        lignes.append("  17  date de péremption .... "
                      + (f"{code.peremption:%d/%m/%Y}" if code.peremption
                         else "absente"))
        lignes.append(f"  10  n° de lot ............ {code.lot or 'absent'}")
        lignes.append(f"  21  n° de série .......... "
                      f"{code.serie or 'absent'}")
    elif code.reconnu:
        lignes.append(f"Code-barres linéaire : CIP {code.cip} — il ne porte "
                      "que l'identifiant du produit.")
    else:
        lignes.append("Contenu non reconnu comme un code produit.")
    lignes += ["", "Aucun identifiant GS1 ne transporte le NOM du "
                   "médicament : il n'est pas dans la boîte, il vient du "
                   "répertoire."]
    return "\n".join(lignes)


def _formulaire_complement() -> None:
    """Fiche d'ajout : ce que le code ne dit pas, l'opérateur le complète."""
    attente = st.session_state["sf_en_attente"]
    with st.form("sf_form_ajout", clear_on_submit=False):
        st.markdown("**Fiche du produit à enregistrer**")

        # Le code-barres donne le CIP, la péremption et le lot — JAMAIS le
        # nom du médicament, qui ne figure dans aucun standard GS1. Sans
        # cette explication, se voir réclamer le nom d'une boîte qu'on vient
        # de scanner passe pour un bug.
        if attente["cip"] and not attente["nom"]:
            st.info(
                f"Le code **{attente['cip']}** n'a jamais été enregistré ici. "
                "Un code-barres ne contient **pas** le nom du médicament : "
                "saisissez-le une fois, et les prochains scans de ce produit "
                "seront reconnus tout seuls. Pour éviter toute saisie, "
                "importez votre catalogue (encadré « Pré-remplir les noms » "
                "ci-dessus).")

        col1, col2 = st.columns([3, 2])
        # Placeholders rédigés comme des CONSIGNES : un exemple réaliste
        # (« DOLIPRANE » en gris) se confond avec une valeur déjà saisie, et
        # l'on valide sans comprendre pourquoi le champ est refusé.
        nom = col1.text_input("Nom du médicament *", value=attente["nom"],
                              placeholder="nom et dosage, comme sur la boîte")
        cip = col2.text_input("Code CIP", value=attente["cip"],
                              placeholder="facultatif")
        # Plus de champ « Dosage » : il fait partie du nom, partout. Celui
        # qui vient d'un catalogue importé continue d'être repris ici, sans
        # rien demander — il sera fondu dans le nom à l'enregistrement.
        dosage = attente["dosage"]

        col4, col5, col6 = st.columns(3)
        boites = col4.number_input("Nombre de boîtes", min_value=0,
                                   max_value=100000, value=1, step=1)
        unites_par_boite = col5.number_input(
            "Unités par boîte", min_value=0, max_value=100000,
            value=int(attente["unites_par_boite"] or 0), step=1,
            help="Comprimés, ampoules… Laissez 0 si le conditionnement "
                 "n'a pas d'importance ici.")
        unites_vrac = col6.number_input(
            "Unités en vrac", min_value=0, max_value=100000, value=0, step=1,
            help="Comprimés restants d'une boîte entamée.")

        col7, col8 = st.columns([2, 2])
        # Les barres obliques coûtent deux frappes par boîte, et il y a une
        # date par boîte : sur un inventaire complet, cela fait des
        # centaines de frappes pour rien. Les chiffres seuls suffisent —
        # c'est d'ailleurs ce qui est imprimé sur les cartons.
        peremption_texte = col7.text_input(
            "Date de péremption *",
            value=(f"{attente['peremption']:%d/%m/%Y}"
                   if attente["peremption"] else ""),
            placeholder="082027 pour 08/2027 — sans les barres",
            help="Tapez seulement les chiffres : « 082027 » pour une boîte "
                 "marquée 08/2027 (elle vaut alors jusqu'au 31 août), "
                 "« 31082027 » pour une date complète, « 0827 » en encore "
                 "plus court. Avec les barres, ça marche aussi.\n\n"
                 "Obligatoire : c'est elle qui distingue deux boîtes du "
                 "même médicament.")
        lot = col8.text_input("N° de lot", value=attente["lot"])

        # Vérifiable d'un coup d'œil : ce que la boîte a RÉELLEMENT transmis,
        # champ par champ. C'est la seule façon de constater soi-même
        # qu'aucun libellé n'y figure — et, si une douchette envoyait autre
        # chose, de le voir immédiatement.
        if attente["brut"]:
            with st.expander("🔎 Que contient exactement le code scanné ?"):
                st.code(_detail_code(attente["brut"]), language=None)

        col_ok, col_annule = st.columns([3, 1])
        valide = col_ok.form_submit_button("➕ Ajouter au stock",
                                           type="primary",
                                           use_container_width=True)
        annule = col_annule.form_submit_button("Annuler",
                                               use_container_width=True)

    if annule:
        st.session_state.pop("sf_en_attente", None)
        st.rerun()

    if not valide:
        return

    peremption = stock_ferme.parser_peremption_saisie(peremption_texte)
    if not nom.strip():
        st.error("**Nom du médicament manquant.** Le code-barres ne le "
                 "contient pas : recopiez-le depuis la boîte dans le premier "
                 "champ, puis validez. Une seule fois par produit — il sera "
                 "reconnu aux scans suivants.")
        return
    if peremption is None:
        st.error(
            "**Date de péremption illisible.** Tapez les chiffres du mois et "
            "de l'année : « 082027 » pour 08/2027, « 31082027 » pour une date "
            f"complète. L'année doit rester entre "
            f"{stock_ferme.ANNEE_PEREMPTION_MIN} et "
            f"{stock_ferme.ANNEE_PEREMPTION_MAX} — au-delà, c'est une faute "
            "de frappe, et une boîte qui périme en l'an 9999 ne se signale "
            "jamais.")
        return
    if boites == 0 and unites_vrac == 0:
        st.error("Indiquez au moins une boîte ou des unités en vrac.")
        return

    entree = stock_ferme.EntreeStock(
        cip=cip, nom=nom, dosage=dosage, boites=int(boites),
        unites_par_boite=int(unites_par_boite), unites_vrac=int(unites_vrac),
        peremption=peremption, lot=lot)
    if _appliquer(
            lambda courant: stock_ferme.ajouter_entree(courant, entree),
            produit={"cip": cip, "nom": nom, "dosage": dosage,
                     "unites_par_boite": int(unites_par_boite)}) is None:
        return
    st.session_state.pop("sf_en_attente", None)
    st.session_state["sf_message"] = (
        "ok", f"➕ {entree.nom} {entree.dosage} — {boites} boîte(s), "
              f"péremption {peremption:%d/%m/%Y}")
    st.rerun()


# ---------------------------------------------------------------------------
# Écran
# ---------------------------------------------------------------------------

def _base_publique() -> None:
    """Installation et mise à jour de la base publique des médicaments.

    C'est elle qui donne le nom au moment du scan, sans rien saisir. Le
    téléchargement est explicite : l'application reste locale, et on choisit
    quand la rafraîchir.
    """
    info = base_medicaments.info_base(BASE_MEDICAMENTS_PATH)
    age = base_medicaments.anciennete_jours(info,
                                            st.session_state.get("sf_date"))
    # Une base installée avant l'ajout du conditionnement n'a pas de
    # présentations : la recherche par nom marche, mais sans « 30
    # comprimés » ni unités par boîte. Autant le dire que de laisser
    # chercher pourquoi la colonne reste vide.
    incomplete = info["existe"] and not info.get("presentations")
    if not info["existe"]:
        etat, ouvert = "⚠️ non installée", True
    elif incomplete:
        etat, ouvert = f"🟡 {info['lignes']} codes · sans conditionnement", True
    elif age is not None and age > ANCIENNETE_BASE_JOURS:
        etat, ouvert = f"🟡 {info['lignes']} codes · {age} jours", False
    else:
        etat, ouvert = f"🟢 {info['lignes']} codes · à jour", False

    with st.expander(f"🌐 Base publique des médicaments — {etat}",
                     expanded=ouvert):
        st.caption(
            "Un code-barres ne contient pas le nom du médicament, seulement "
            "le code CIP. Cette base officielle (ANSM / ministère de la "
            "Santé) fait la correspondance : une fois installée, le nom "
            "s'affiche **au moment du scan**, sans rien taper. Elle est "
            "conservée sur ce poste et fonctionne ensuite hors ligne.")
        st.caption(
            "Elle sert aussi dans l'autre sens : **tapez un nom** dans le "
            "champ de scan et elle propose les présentations correspondantes, "
            "avec leur dosage, leur conditionnement et leur code CIP.")
        if info["existe"]:
            st.caption(f"Dernière mise à jour : {info['date']:%d/%m/%Y}.")
        if incomplete:
            st.warning("Cette base a été installée avant l'ajout du "
                       "conditionnement : elle identifie bien les codes, mais "
                       "ne connaît ni « plaquette de 30 comprimés » ni le "
                       "nombre d'unités par boîte. Retéléchargez-la pour en "
                       "profiter.")

        if not st.button("⬇️ Télécharger / mettre à jour la base",
                         use_container_width=True,
                         type="primary" if not info["existe"] else "secondary"):
            return
        try:
            with st.spinner("Téléchargement de la base officielle…"):
                table = base_medicaments.telecharger_table()
            base_medicaments.sauver_table(table, BASE_MEDICAMENTS_PATH)
        except ValueError as e:
            st.error(str(e))
            return
        st.session_state["sf_message"] = (
            "ok", f"🌐 Base des médicaments installée — {len(table)} codes. "
                  "Les prochains scans afficheront le nom tout seuls.")
        st.rerun()


def _import_repertoire() -> None:
    """Pré-remplissage du répertoire depuis un fichier de la pharmacie.

    Le nom du médicament ne peut PAS venir du code-barres. Il doit venir
    d'une table « code CIP → libellé » : le cadencier de l'officine en est
    une, et elle a l'avantage d'être déjà sur le poste et de ne contenir que
    des produits réellement détenus.

    Le fichier est lu ici, dans la couche d'affichage : `stock_ferme.py`
    n'en connaît rien, il ne reçoit que des couples déjà extraits.
    """
    with st.expander("📇 Pré-remplir les noms depuis un fichier "
                     "(cadencier, catalogue…)"):
        st.caption(
            "Un code-barres ne contient pas le nom du médicament. En "
            "important une fois votre catalogue, les boîtes scannées seront "
            "reconnues automatiquement, sans rien saisir.")
        fichier = st.file_uploader(
            "Fichier contenant au moins un code CIP et un libellé",
            type=["xlsx", "xls", "csv", "pdf"], key="sf_import_fichier")
        if fichier is None:
            return

        try:
            tableau = commun.charger_fichier(fichier.getvalue(), fichier.name)
        except ValueError as e:
            st.error(str(e))
            return
        colonnes = list(tableau.columns)
        st.success(f"{len(tableau)} ligne(s) lue(s).")

        def _defaut(role, secours=None):
            trouve = commun.detecter_colonne(colonnes, role)
            return colonnes.index(trouve) if trouve in colonnes else (
                colonnes.index(secours) if secours in colonnes else 0)

        c1, c2, c3 = st.columns(3)
        col_cip = c1.selectbox("Colonne du code CIP", colonnes,
                               index=_defaut("cip"), key="sf_import_cip")
        col_nom = c2.selectbox("Colonne du nom", colonnes,
                               index=_defaut("libelle"), key="sf_import_nom")
        col_dosage = c3.selectbox("Colonne du dosage (facultatif)",
                                  ["(aucune)"] + colonnes,
                                  key="sf_import_dosage")

        if not st.button("📥 Importer dans le répertoire",
                         use_container_width=True, type="primary"):
            return
        lignes = [{"cip": ligne[col_cip], "nom": ligne[col_nom],
                   "dosage": (ligne[col_dosage]
                              if col_dosage != "(aucune)" else "")}
                  for _, ligne in tableau.iterrows()]
        # L'import s'applique au répertoire RELU sous verrou : le faire sur
        # celui qu'on avait en mémoire effacerait les produits qu'un autre
        # poste a nommés pendant qu'on choisissait ses colonnes.
        compte = {}

        def mouvement(courant):
            nouveau, ajoutes, ignores = stock_ferme.importer_repertoire(
                courant, lignes)
            compte.update(ajoutes=ajoutes, ignores=ignores,
                          total=len(nouveau))
            return nouveau

        try:
            ecriture = stock_ferme.appliquer_au_repertoire(REPERTOIRE_PATH,
                                                           mouvement)
        except (stock_ferme.VerrouIndisponible, OSError) as erreur:
            _journal.error("Import du répertoire abandonné : %s", erreur)
            st.error(MESSAGE_FICHIER_BLOQUE.format(
                fichier=REPERTOIRE_PATH.name))
            return
        st.session_state["sf_repertoire"] = ecriture.tableau
        st.session_state["sf_empreinte_repertoire"] = ecriture.empreinte
        st.session_state["sf_message"] = (
            "ok", f"📇 {compte['ajoutes']} produit(s) ajouté(s) au répertoire"
                  + (f" · {compte['ignores']} ligne(s) sans code ou sans nom "
                     "ignorée(s)" if compte["ignores"] else "")
                  + f" · {compte['total']} produit(s) reconnus désormais.")
        st.rerun()


def _tableau_editable(inventaire: pd.DataFrame, aujourdhui: date,
                      tri: str) -> pd.DataFrame | None:
    """Inventaire modifiable ; renvoie le tableau corrigé s'il a changé."""
    vue = stock_ferme.inventaire_affichable(inventaire, aujourdhui, tri)
    if vue.empty:
        st.info("Inventaire vide — scannez une première boîte ci-dessus.")
        return None

    # L'éditeur mémorise ses corrections en cours dans l'état de session, sous
    # sa clé, et les repère par POSITION de ligne. Après un enregistrement,
    # l'inventaire a changé de forme (lignes supprimées, ordre revu par
    # échéance) ; changer de classement rebat les lignes tout autant.
    # Réutiliser la même clé réappliquerait les anciennes corrections aux
    # NOUVELLES lignes — un comptage recopié sur le mauvais médicament. La
    # clé porte donc à la fois la génération et l'ordre affiché.
    edite = st.data_editor(
        vue, hide_index=True, use_container_width=True, num_rows="dynamic",
        key=f"sf_editeur_{st.session_state.get('sf_generation', 0)}"
            f"_{stock_ferme.TRIS.index(tri)}",
        disabled=["Statut", "Code CIP", "Total unités", "Jours restants",
                  "Enregistré le"],
        column_config=_colonnes_inventaire())
    st.caption("Corrigez une quantité ou une date directement dans le "
               "tableau ; la ligne d'une boîte sortie peut être supprimée "
               "(sélection puis touche Suppr). Tout est enregistré "
               "automatiquement.")

    colonnes = [c for c in _COLONNES_EDITABLES if c in edite.columns]
    if len(edite) == len(vue) and edite[colonnes].equals(vue[colonnes]):
        return None
    # Le tableau affiché porte des colonnes de lecture (Statut, Jours
    # restants) qui ne font pas partie du stock : on ne renvoie que le stock.
    return stock_ferme.normaliser_tableau_edite(edite)


def _enregistrer_corrections(corrige: pd.DataFrame) -> None:
    """Enregistre le tableau corrigé — sauf si un autre poste a écrit depuis.

    Le tableau modifiable ne décrit pas un mouvement mais un état complet :
    l'écrire, c'est remplacer tout l'inventaire par celui qu'on avait sous
    les yeux. Si un autre poste a scanné entre-temps, sa boîte disparaîtrait
    sans un mot. On refuse donc, on réaffiche la version du disque, et on le
    dit : une correction à refaire vaut mieux qu'un stock faux.
    """
    attendu = st.session_state.get("sf_empreinte")
    conflit = []

    def mouvement(courant):
        if stock_ferme.empreinte_fichier(INVENTAIRE_PATH) != attendu:
            conflit.append(True)
            return None
        return corrige

    if _appliquer(mouvement) is None or not conflit:
        return
    st.session_state["sf_message"] = (
        "avertissement",
        "Un autre poste a modifié l'inventaire pendant votre correction : "
        "elle n'a pas été enregistrée, pour ne pas effacer son travail. Le "
        "tableau est à jour ci-dessous — refaites la correction.")


def _zone_impression(inventaire: pd.DataFrame, aujourdhui: date,
                     tri: str) -> None:
    st.markdown("**Imprimer la liste de stock**")
    st.caption("Nom du médicament, dosage, code CIP, nombre de boîtes et "
               "d'unités, et date de péremption de chaque lot. Le document "
               f"reprend le classement choisi ci-dessus ({tri.lower()}).")

    # Le besoin le plus fréquent n'est pas la liste complète mais la liste de
    # RETRAIT : ce qui est périmé ou ne passera pas le mois.
    retrait_seul = st.checkbox(
        "N'imprimer que les lots à retirer (périmés et moins d'un mois)",
        key="sf_impression_retrait")
    a_imprimer = (stock_ferme.filtrer_inventaire(
        inventaire, statuts=stock_ferme.STATUTS_A_TRAITER,
        aujourdhui=aujourdhui, tri=tri) if retrait_seul else inventaire)
    titre = "Stock interne — lots à retirer" if retrait_seul else "Stock interne"
    prefixe = "stock_ferme_retrait" if retrait_seul else "stock_ferme"
    nombre = len(stock_ferme.inventaire_affichable(a_imprimer, aujourdhui, tri))
    st.caption(f"{nombre} lot(s) dans le document.")

    col_csv, col_pdf = st.columns(2)
    col_csv.download_button(
        "📄 Télécharger en CSV",
        data=stock_ferme.exporter_csv(a_imprimer, aujourdhui, tri),
        file_name=f"{prefixe}_{aujourdhui:%Y-%m-%d}.csv",
        mime=_MIME_CSV, use_container_width=True)
    try:
        pdf = stock_ferme.exporter_pdf(a_imprimer, titre, aujourdhui, tri)
        col_pdf.download_button(
            "🖨️ Télécharger en PDF",
            data=pdf,
            file_name=f"{prefixe}_{aujourdhui:%Y-%m-%d}.pdf",
            mime=_MIME_PDF, type="primary", use_container_width=True)
    except ValueError as e:
        col_pdf.warning(str(e))


def _barre_laterale(inventaire: pd.DataFrame, repertoire: pd.DataFrame,
                    aujourdhui: date) -> date:
    with st.sidebar:
        st.markdown("## 🔒 Stock interne")
        st.caption("Inventaire tenu à part du stock officinal : armoire "
                   "sécurisée, dotation d'urgence, trousse, réserve de garde.")

        aujourdhui = st.date_input("Date du jour", value=aujourdhui,
                                   format="DD/MM/YYYY")
        st.checkbox("Ajout immédiat des boîtes reconnues", value=True,
                    key="sf_ajout_direct",
                    help="Un Data Matrix qui donne le CIP, la péremption et "
                         "un produit déjà connu entre au stock sans "
                         "confirmation.")

        st.divider()
        # Réglages qu'on fait UNE FOIS, pas des gestes de comptoir. Au
        # milieu de l'écran, entre le scan et l'inventaire, ils occupaient
        # la place de ce qu'on regarde tous les jours — et il fallait les
        # dépasser du regard à chaque boîte scannée.
        _base_publique()
        _import_repertoire()

        st.divider()
        st.markdown("#### Mémoire")
        st.caption(f"{len(inventaire)} lot(s) · {len(repertoire)} produit(s) "
                   f"mémorisé(s)\n\n`{INVENTAIRE_PATH.name}`")
        with st.expander("🗑️ Vider l'inventaire"):
            st.warning("Supprime tous les lots enregistrés. Les produits "
                       "mémorisés (noms, dosages) sont conservés.")
            if st.button("Confirmer la remise à zéro",
                         use_container_width=True):
                _enregistrer(inventaire=stock_ferme.inventaire_vide())
                st.session_state.pop("sf_en_attente", None)
                st.rerun()
    return aujourdhui


def rendre(etape) -> None:
    """Affiche l'écran complet du module.

    ``etape`` est la fonction d'habillage de ``app.py``, passée en
    paramètre pour garder ce module indépendant de l'application.

    Les compteurs du haut — lots, boîtes, périmés, moins d'un mois,
    moins de trois mois — ont été retirés : le tableau dit la même chose
    ligne par ligne, et ils repoussaient l'inventaire hors de l'écran.
    """
    inventaire, repertoire = _etat()
    aujourdhui = _barre_laterale(inventaire, repertoire,
                                 st.session_state.get("sf_date", date.today()))
    st.session_state["sf_date"] = aujourdhui
    # La barre latérale porte l'import du répertoire : il peut avoir ajouté
    # des produits à l'instant, et l'écran doit les voir tout de suite.
    inventaire, repertoire = _etat()

    message = st.session_state.pop("sf_message", None)
    if message:
        niveau, texte = message
        (st.success if niveau == "ok" else st.warning)(texte)

    # --- Saisie ------------------------------------------------------------
    # Deux lignes, et rien d'autre. C'est la demande de la pharmacie, et
    # elle a raison : au comptoir on bipe, puis on dit dans quel sens.
    # L'écran portait auparavant deux dispositions différentes selon le
    # mode — trois boutons en Entrée, deux encadrés en Sortie — et il
    # fallait relire l'écran à chaque bascule pour retrouver le champ.
    etape("1", "Scannez le produit",
          "Douchette ou clavier, puis le sens du mouvement.")

    # LIGNE 1 — le champ, et rien d'autre. Un bouton « Chercher » l'a
    # accompagné : il ne faisait que ce que fait la touche Entrée, et
    # faisait donc douter qu'Entrée suffise. L'invite le dit maintenant
    # en toutes lettres, et la douchette valide de toute façon seule.
    st.text_input(
        "Code scanné", key="sf_scan", on_change=_traiter_scan,
        placeholder="🔦 Douchez la boîte — ou tapez le nom du médicament "
                    "et appuyez sur Entrée",
        label_visibility="collapsed")

    # LIGNE 2 — le sens. Sous le champ et non au-dessus : on bipe d'abord,
    # on regarde le sens ensuite. Il reste choisi d'un scan à l'autre, donc
    # on le règle une fois le matin.
    mode = st.segmented_control(
        "Sens du mouvement", [MODE_ENTREE, MODE_SORTIE],
        default=st.session_state.get("sf_mode_choisi", MODE_ENTREE),
        label_visibility="collapsed", key="sf_mode", on_change=_garder_mode,
        width="stretch")
    if mode is None:  # premier rendu suivant une déselection
        mode = st.session_state.get("sf_mode_choisi", MODE_ENTREE)
    st.session_state["sf_mode_choisi"] = mode

    # Tout le reste est replié. Ce sont des exceptions — étiquette abîmée,
    # boîte sans code-barres, dispensation à l'unité — et une exception
    # affichée en permanence encombre le geste de tous les jours. Le titre
    # les nomme : replié ne veut pas dire caché.
    with st.expander("⌨️ Le code ne se lit pas ? Sortir à l'unité ?"):
        if mode == MODE_ENTREE:
            st.button(
                "⌨️ Saisie manuelle", use_container_width=True,
                key="sf_bouton_saisie_manuelle",
                on_click=_saisie_manuelle_vierge,
                help="Enregistrer une boîte dont le code ne se lit pas.")
            st.caption("Ou cherchez le médicament par son nom :")
            _saisie_assistee()
        else:
            st.button(
                "⌨️ Sortie manuelle", use_container_width=True,
                key="sf_bouton_sortie_manuelle",
                on_click=_basculer_sortie_manuelle,
                help="Sans douchette : on désigne le lot, puis le "
                     "nombre de boîtes ou d'unités.")
            st.caption(
                "Pour une étiquette abîmée, une boîte sans code-barres — et "
                "pour sortir **quelques unités** plutôt qu'une boîte entière "
                "(le reste part en vrac, il reste à l'inventaire).")

    if mode == MODE_SORTIE:
        tri_courant = st.session_state.get("sf_tri", stock_ferme.TRI_PEREMPTION)
        if inventaire is None or inventaire.empty:
            # Sortir d'un inventaire vide ne peut que rater : chaque scan
            # répondait « ce produit n'est pas à l'inventaire », et le seul
            # autre bouton était grisé. Impasse complète.
            st.info("L'inventaire est vide : il n'y a rien à sortir. "
                    "Enregistrez d'abord vos boîtes en mode Entrée.")
            st.button("➕ Passer en Entrée", on_click=_passer_en_entree)
        elif st.session_state.get("sf_sortie_manuelle"):
            _panneau_sortie_manuelle(inventaire, aujourdhui, tri_courant)

    if "sf_en_attente" in st.session_state and mode == MODE_ENTREE:
        _formulaire_complement()
        inventaire, repertoire = _etat()

    # --- Inventaire --------------------------------------------------------
    st.divider()
    # Ni tuiles ni explication : cinq compteurs tenaient ici — lots,
    # boîtes, périmés, moins d'un mois, moins de trois mois — au-dessus
    # d'un tableau qui dit déjà tout cela, ligne par ligne, avec le
    # statut en tête. Ils repoussaient l'inventaire lui-même sous la
    # ligne de flottaison, et c'est lui qu'on vient voir.
    etape("2", "Inventaire", "")

    col_rech, col_tri, col_filtre = st.columns([3, 2, 2])
    recherche = col_rech.text_input(
        "🔎 Rechercher (nom, dosage, code CIP ou n° de lot)",
        key="sf_recherche", placeholder="ex. MORPHINE, 3400937… ou LOT-A")
    # Deux gestes distincts : décider ce qu'on retire (péremption) et
    # retrouver un produit dans l'armoire (nom). Le classement suit jusqu'au
    # CSV et au PDF — sinon la liste papier contredirait l'écran.
    tri = col_tri.selectbox("↕️ Classer par", stock_ferme.TRIS, key="sf_tri")
    a_traiter = col_filtre.checkbox(
        "⚠️ N'afficher que les lots à traiter", key="sf_filtre_traiter",
        help="Périmés et lots de moins d'un mois.")
    vue_filtree = stock_ferme.filtrer_inventaire(
        inventaire, recherche,
        stock_ferme.STATUTS_A_TRAITER if a_traiter else None, aujourdhui, tri)
    filtre_actif = bool(recherche) or a_traiter
    if filtre_actif and vue_filtree.empty:
        st.info("Aucun lot ne correspond à ce filtre.")

    # TROIS colonnes : le nom, le code CIP, et si la boîte est périmée.
    # Demande de la pharmacie, mot pour mot — « rien de plus ». Onze
    # colonnes tenaient ici ; devant l'armoire on ne cherche que deux
    # choses : est-ce le bon produit, et est-il encore bon.
    st.dataframe(
        stock_ferme.vue_essentielle(
            vue_filtree if filtre_actif else inventaire, aujourdhui, tri),
        use_container_width=True, hide_index=True,
        column_config=_colonnes_inventaire())
    if filtre_actif:
        st.caption(f"{len(vue_filtree)} lot(s) sur {len(inventaire)}.")

    # Le détail — quantités, lot, péremption exacte — reste à une clic. Il
    # ne se corrige que sur l'inventaire ENTIER : rectifier une vue filtrée
    # réécrirait le stock en perdant les lignes masquées.
    corrige = None
    with st.expander("🔧 Voir le détail et corriger les quantités"):
        if filtre_actif:
            st.dataframe(
                stock_ferme.inventaire_affichable(vue_filtree, aujourdhui,
                                                  tri),
                use_container_width=True, hide_index=True,
                column_config=_colonnes_inventaire())
            st.caption("Videz la recherche et décochez le filtre pour "
                       "corriger l'inventaire.")
        else:
            corrige = _tableau_editable(inventaire, aujourdhui, tri)
    if corrige is not None:
        _enregistrer_corrections(corrige)
        st.rerun()

    # --- Impression --------------------------------------------------------
    st.divider()
    etape("3", "Imprimez ou exportez", "Liste de contrôle du stock physique.")
    _zone_impression(inventaire, aujourdhui, tri)
