# -*- coding: utf-8 -*-
"""Interface du Module 3 — Gestion d'un stock fermé.

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

#: Colonnes modifiables directement dans le tableau.
_COLONNES_EDITABLES = ("Nom du produit", "Dosage", "Boîtes",
                       "Unités par boîte", "Unités en vrac", "Péremption",
                       "Lot")


# ---------------------------------------------------------------------------
# Mémoire de session (chargée une fois depuis le disque)
# ---------------------------------------------------------------------------

def _etat():
    """Inventaire et répertoire courants, relus du disque au premier appel."""
    if "sf_inventaire" not in st.session_state:
        st.session_state["sf_inventaire"] = stock_ferme.charger_inventaire(
            INVENTAIRE_PATH)
        _journal.info("Stock fermé — %d lot(s) relus depuis %s",
                      len(st.session_state["sf_inventaire"]), INVENTAIRE_PATH)
    if "sf_repertoire" not in st.session_state:
        st.session_state["sf_repertoire"] = stock_ferme.charger_repertoire(
            REPERTOIRE_PATH)
    return st.session_state["sf_inventaire"], st.session_state["sf_repertoire"]


def _base_chargee() -> tuple:
    """Les deux index de la base publique : par code CIP, et par nom.

    Relus une seule fois par session, et à nouveau si le fichier a changé
    (mise à jour de la base) — 40 000 codes, inutile de les relire à chaque
    interaction. Les deux sont construits ensemble : ils viennent du même
    fichier, le lire deux fois serait payer deux fois.
    """
    empreinte = (BASE_MEDICAMENTS_PATH.stat().st_mtime
                 if BASE_MEDICAMENTS_PATH.exists() else 0)
    if st.session_state.get("sf_base_empreinte") != empreinte:
        table = base_medicaments.charger_table(BASE_MEDICAMENTS_PATH)
        st.session_state["sf_base_index"] = base_medicaments.index_par_cip(
            table)
        st.session_state["sf_base_noms"] = base_medicaments.index_par_nom(
            table)
        st.session_state["sf_base_empreinte"] = empreinte
        _journal.info("Base des médicaments : %d code(s), %d présentation(s)",
                      len(st.session_state["sf_base_index"]),
                      len(st.session_state["sf_base_noms"]))
    return (st.session_state["sf_base_index"],
            st.session_state["sf_base_noms"])


def _index_base() -> dict:
    return _base_chargee()[0]


def _index_noms() -> list:
    return _base_chargee()[1]


def _enregistrer(inventaire=None, repertoire=None) -> None:
    """Écrit sur le disque : c'est la « mémoire » entre deux ouvertures."""
    if inventaire is not None:
        st.session_state["sf_inventaire"] = inventaire
        stock_ferme.sauver_inventaire(inventaire, INVENTAIRE_PATH)
        # Change la clé de l'éditeur : ses corrections en cours ne doivent
        # pas être rejouées sur le tableau qui vient d'être réenregistré.
        st.session_state["sf_generation"] = (
            st.session_state.get("sf_generation", 0) + 1)
    if repertoire is not None:
        st.session_state["sf_repertoire"] = repertoire
        stock_ferme.sauver_repertoire(repertoire, REPERTOIRE_PATH)


# ---------------------------------------------------------------------------
# Saisie
# ---------------------------------------------------------------------------

MODE_ENTREE = "➕ Entrée"
MODE_SORTIE = "➖ Sortie"


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


def _traiter_sortie(code, inventaire) -> None:
    """Sortie de stock à la douchette : une boîte de moins, du bon lot.

    Un Data Matrix désigne la boîte précise ; un code-barres linéaire ne
    donne que le produit, et c'est alors le lot qui périme le plus tôt qui
    sort (FEFO).
    """
    cible = stock_ferme.lot_a_sortir(inventaire, cip=code.cip,
                                     peremption=code.peremption, lot=code.lot)
    if cible is None:
        st.session_state["sf_message"] = (
            "avertissement",
            f"Sortie impossible : « {code.cip or code.brut} » n'est pas à "
            "l'inventaire. Vérifiez le code, choisissez la boîte avec "
            "« ⌨️ Sortie manuelle », ou passez en mode Entrée pour "
            "l'enregistrer.")
        return

    _enregistrer(inventaire=stock_ferme.retirer_entree(
        inventaire, cible["cip"], cible["nom"], cible["peremption"],
        cible["lot"], boites=1))
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
    inventaire, repertoire = _etat()

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
        _traiter_sortie(code, inventaire)
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
        nouveau_repertoire = None
        if depuis_base:
            # Le nom devient celui de la pharmacie : elle peut le corriger,
            # et l'identification ne dépendra plus de la base ensuite.
            nouveau_repertoire = stock_ferme.memoriser_produit(
                repertoire, code.cip, connu["nom"])
        _enregistrer(inventaire=stock_ferme.ajouter_entree(inventaire, entree),
                     repertoire=nouveau_repertoire)
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
    # La base publique sait alors proposer les présentations correspondantes
    # — avec leur dosage, leur conditionnement et leur code CIP, qu'il n'y a
    # plus qu'à choisir plutôt qu'à ressaisir.
    index_noms = [] if code.reconnu else _index_noms()
    trouvaille = (base_medicaments.preselectionner(index_noms, brut)
                  if index_noms else
                  {"resultats": [], "terme": "", "elargi": False})
    propositions = trouvaille["resultats"]
    if propositions:
        st.session_state["sf_propositions"] = {
            "saisi": str(brut).strip(), "terme": trouvaille["terme"],
            "elargi": trouvaille["elargi"], "resultats": propositions}
    else:
        st.session_state.pop("sf_propositions", None)

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
    if propositions:
        st.session_state["sf_message"] = (
            "ok", f"{len(propositions)} médicament(s) trouvé(s) pour "
                  f"« {str(brut).strip()} » — choisissez la présentation "
                  "ci-dessous." + rappel)
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
    st.session_state.pop("sf_propositions", None)
    st.session_state["sf_message"] = None


def libelle_proposition(medicament: dict) -> str:
    """Une ligne de la présélection : dénomination, conditionnement, unités.

    Deux boîtes du même médicament au même dosage ne se distinguent que par
    leur conditionnement — 8 comprimés ou 100. L'omettre rendrait le choix
    aveugle, et c'est justement ce nombre qui remplit « unités par boîte ».
    """
    ligne = medicament["nom"]
    if medicament.get("presentation"):
        ligne += f" — {medicament['presentation']}"
    if medicament.get("unites_par_boite"):
        ligne += f" · {medicament['unites_par_boite']} unités/boîte"
    return ligne


def _choisir_proposition(medicament: dict) -> None:
    """Reprend un médicament de la présélection dans la fiche d'ajout."""
    attente = dict(st.session_state.get("sf_en_attente") or {})
    attente.update({
        "cip": medicament["cip"],
        # La dénomination officielle porte déjà le dosage (« DOLIPRANE
        # 1000 mg, comprimé ») : le scinder en deux champs reviendrait à
        # deviner où couper.
        "nom": medicament["nom"],
        "unites_par_boite": medicament.get("unites_par_boite", 0),
    })
    attente.setdefault("dosage", "")
    attente.setdefault("peremption", None)
    attente.setdefault("lot", "")
    attente.setdefault("brut", "")
    attente.setdefault("reconnu", True)
    st.session_state["sf_en_attente"] = attente
    st.session_state.pop("sf_propositions", None)
    st.session_state["sf_message"] = (
        "ok", f"{medicament['nom']} — il ne reste que la date de péremption "
              "à saisir.")


def _preselection_par_nom() -> None:
    """Liste des médicaments correspondant au nom tapé au clavier."""
    proposition = st.session_state.get("sf_propositions")
    if not proposition:
        return
    resultats = proposition["resultats"]
    saisi = proposition.get("saisi", "")
    with st.container(border=True):
        st.markdown(f"**Médicaments trouvés pour « {saisi} »**")
        if proposition.get("elargi"):
            # Dire ce qui a réellement servi : sinon la liste paraît hors
            # sujet, alors qu'elle répond à une recherche volontairement
            # élargie faute de correspondance exacte.
            st.caption(f"Aucune correspondance exacte : recherche élargie à "
                       f"« {proposition['terme']} ».")
        st.caption("Choisissez la présentation exacte : c'est elle qui donne "
                   "le code CIP et le nombre d'unités par boîte. La date de "
                   "péremption reste à saisir — elle n'appartient qu'à la "
                   "boîte que vous avez en main.")
        choix = st.selectbox(
            "Médicament", range(len(resultats)),
            format_func=lambda i: libelle_proposition(resultats[i]),
            key="sf_proposition_choix", label_visibility="collapsed")
        colonne_ok, colonne_non = st.columns([3, 1])
        colonne_ok.button("✅ Utiliser ce médicament", type="primary",
                          use_container_width=True,
                          on_click=_choisir_proposition,
                          args=(resultats[choix],))
        colonne_non.button("Aucun", use_container_width=True,
                           help="Saisir le produit à la main.",
                           on_click=lambda: st.session_state.pop(
                               "sf_propositions", None))


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
    """Retirer une boîte en la désignant dans la liste, sans douchette.

    Une étiquette abîmée, une boîte reconditionnée, un produit sans
    code-barres : la douchette ne lit pas tout, et il n'y avait alors
    aucune façon de sortir une boîte — le bouton de saisie manuelle était
    purement et simplement désactivé en mode Sortie.
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
        colonne_nombre, colonne_bouton = st.columns([1, 2])
        # Le maximum est le stock du lot : proposer davantage, c'est
        # promettre une sortie que l'inventaire ne peut pas honorer.
        combien = colonne_nombre.number_input(
            "Boîtes à retirer", min_value=1, max_value=lot["boites"],
            value=1, step=1, key="sf_sortie_combien")
        colonne_bouton.markdown("<div style='height:1.8rem'></div>",
                                unsafe_allow_html=True)
        if colonne_bouton.button("➖ Retirer du stock", type="primary",
                                 use_container_width=True):
            _enregistrer(inventaire=stock_ferme.retirer_entree(
                inventaire, lot["cip"], lot["nom"], lot["peremption"],
                lot["lot"], boites=int(combien)))
            reste = lot["boites"] - int(combien)
            peremption = (f"{lot['peremption']:%d/%m/%Y}" if lot["peremption"]
                          else "sans date")
            st.session_state["sf_message"] = (
                "ok", f"➖ {lot['nom']} {lot['dosage']} — {int(combien)} "
                      f"boîte(s) sortie(s) ({peremption}) · reste {reste} "
                      "boîte(s) sur ce lot.")
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


def _formulaire_complement(inventaire: pd.DataFrame,
                           repertoire: pd.DataFrame) -> None:
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

        col1, col2, col3 = st.columns([3, 2, 2])
        # Placeholders rédigés comme des CONSIGNES : un exemple réaliste
        # (« DOLIPRANE » en gris) se confond avec une valeur déjà saisie, et
        # l'on valide sans comprendre pourquoi le champ est refusé.
        nom = col1.text_input("Nom du médicament *", value=attente["nom"],
                              placeholder="à recopier sur la boîte")
        dosage = col2.text_input("Dosage", value=attente["dosage"],
                                 placeholder="facultatif")
        cip = col3.text_input("Code CIP", value=attente["cip"],
                              placeholder="facultatif")

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
        peremption_texte = col7.text_input(
            "Date de péremption *",
            value=(f"{attente['peremption']:%d/%m/%Y}"
                   if attente["peremption"] else ""),
            placeholder="JJ/MM/AAAA ou MM/AAAA",
            help="Obligatoire : c'est elle qui distingue deux boîtes du "
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
        st.error("Date de péremption obligatoire et lisible "
                 "(JJ/MM/AAAA ou MM/AAAA).")
        return
    if boites == 0 and unites_vrac == 0:
        st.error("Indiquez au moins une boîte ou des unités en vrac.")
        return

    entree = stock_ferme.EntreeStock(
        cip=cip, nom=nom, dosage=dosage, boites=int(boites),
        unites_par_boite=int(unites_par_boite), unites_vrac=int(unites_vrac),
        peremption=peremption, lot=lot)
    _enregistrer(
        inventaire=stock_ferme.ajouter_entree(inventaire, entree),
        repertoire=stock_ferme.memoriser_produit(
            repertoire, cip, nom, dosage, int(unites_par_boite)))
    st.session_state.pop("sf_en_attente", None)
    st.session_state["sf_message"] = (
        "ok", f"➕ {entree.nom} {entree.dosage} — {boites} boîte(s), "
              f"péremption {peremption:%d/%m/%Y}")
    st.rerun()


# ---------------------------------------------------------------------------
# Écran
# ---------------------------------------------------------------------------

def _bandeau_kpi(resume: dict, tuile) -> None:
    st.markdown('<div class="kpi-row">' + "".join([
        tuile("Lots enregistrés", resume["lignes"], "accent",
              sous=f'{resume["references"]} référence(s)'),
        tuile("Boîtes", resume["boites"], "accent",
              sous=(f'{resume["unites"]} unité(s) au total'
                    if resume["unites"] else "conditionnement non renseigné")),
        tuile("⛔ Périmés", resume["perimes"],
              "critical" if resume["perimes"] else "",
              sous="à retirer du stock"),
        tuile("🔴 Moins d'un mois", resume["imminents"],
              "critical" if resume["imminents"] else "",
              sous="ne passeront pas le mois"),
        tuile("🟠 Moins de 3 mois", resume["critiques"],
              "serious" if resume["critiques"] else "",
              sous=f'{resume["vigilance"]} autre(s) sous 6 mois'),
    ]) + "</div>", unsafe_allow_html=True)


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


def _import_repertoire(repertoire: pd.DataFrame) -> None:
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
        nouveau, ajoutes, ignores = stock_ferme.importer_repertoire(
            repertoire, lignes)
        _enregistrer(repertoire=nouveau)
        st.session_state["sf_message"] = (
            "ok", f"📇 {ajoutes} produit(s) ajouté(s) au répertoire"
                  + (f" · {ignores} ligne(s) sans code ou sans nom ignorée(s)"
                     if ignores else "")
                  + f" · {len(nouveau)} produit(s) reconnus désormais.")
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
        column_config={
            "Statut": st.column_config.TextColumn("Statut", width="small"),
            "Péremption": st.column_config.DateColumn(
                "Péremption", format="DD/MM/YYYY", width="small"),
            "Boîtes": st.column_config.NumberColumn(
                "Boîtes", min_value=0, step=1, width="small"),
            "Unités par boîte": st.column_config.NumberColumn(
                "Unités/boîte", min_value=0, step=1, width="small"),
            "Unités en vrac": st.column_config.NumberColumn(
                "Vrac", min_value=0, step=1, width="small"),
            "Total unités": st.column_config.NumberColumn(
                "Total unités", width="small"),
            "Jours restants": st.column_config.NumberColumn(
                "Jours restants", width="small"),
        })
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
    titre = "Stock fermé — lots à retirer" if retrait_seul else "Stock fermé"
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
        st.markdown("## 🔒 Stock fermé")
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


def rendre(etape, tuile_kpi) -> None:
    """Affiche l'écran complet du module.

    ``etape`` et ``tuile_kpi`` sont les fonctions d'habillage de ``app.py``,
    passées en paramètre pour garder ce module indépendant de l'application.
    """
    inventaire, repertoire = _etat()
    aujourdhui = _barre_laterale(inventaire, repertoire,
                                 st.session_state.get("sf_date", date.today()))
    st.session_state["sf_date"] = aujourdhui

    message = st.session_state.pop("sf_message", None)
    if message:
        niveau, texte = message
        (st.success if niveau == "ok" else st.warning)(texte)

    # --- Saisie ------------------------------------------------------------
    etape("1", "Scannez le produit",
          "Douchette (code CIP ou Data Matrix) — ou saisie au clavier.")
    # Entrée ou sortie : c'est la question la plus lourde de conséquences de
    # l'écran (ajouter ou retirer du stock). Elle mérite deux boutons francs,
    # pas deux puces — et un code couleur pour qu'une erreur saute aux yeux.
    mode = st.segmented_control(
        "Sens du mouvement", [MODE_ENTREE, MODE_SORTIE],
        default=st.session_state.get("sf_mode_choisi", MODE_ENTREE),
        label_visibility="collapsed", key="sf_mode", on_change=_garder_mode)
    if mode is None:  # premier rendu suivant une déselection
        mode = st.session_state.get("sf_mode_choisi", MODE_ENTREE)
    st.session_state["sf_mode_choisi"] = mode
    # Un bouton « Chercher » à côté du champ, en plus de la touche Entrée.
    # La douchette valide toute seule ; un nom tapé au clavier, non — et le
    # champ restait alors plein sans que rien ne se passe. C'est exactement
    # ce qui s'est produit en officine : « DOLIPRA » écrit, aucune réaction.
    if mode == MODE_ENTREE:
        col_scan, col_valider, col_manuel = st.columns([4, 1.3, 1.7])
    else:
        col_scan, col_manuel = st.columns([3, 1])
        col_valider = None
    col_scan.text_input(
        "Code scanné", key="sf_scan", on_change=_traiter_scan,
        placeholder=("Douchez la boîte à ajouter — ou tapez un nom de "
                     "médicament puis Entrée" if mode == MODE_ENTREE
                     else "Douchez la boîte à sortir"
                          " (le champ se vide tout seul)"),
        label_visibility="collapsed")
    if col_valider is not None:
        col_valider.button("🔎 Chercher", use_container_width=True,
                           on_click=_traiter_scan,
                           help="Valide ce qui est écrit dans le champ — "
                                "même chose que la touche Entrée.")
    # Le bouton de droite sert dans LES DEUX sens. Il était désactivé en
    # mode Sortie : une étiquette illisible, et il n'existait plus aucune
    # façon de retirer une boîte.
    if mode == MODE_ENTREE:
        col_manuel.button(
            "⌨️ Saisie manuelle", use_container_width=True,
            on_click=_saisie_manuelle_vierge,
            help="Enregistrer une boîte dont le code ne se lit pas.")
        st.caption("Sans code lisible, **tapez le nom du médicament, puis "
                   "appuyez sur Entrée** (ou cliquez sur « 🔎 Chercher ») : "
                   "la base publique propose les présentations "
                   "correspondantes. Rien ne se déclenche tant que la saisie "
                   "n'est pas validée — la douchette, elle, valide toute "
                   "seule.")
        st.caption("Le Data Matrix des boîtes récentes fournit d'un coup le "
                   "code CIP, la date de péremption et le n° de lot. Un "
                   "code-barres linéaire ne donne que le CIP : la péremption "
                   "reste à saisir.")
    else:
        col_manuel.button(
            "⌨️ Sortie manuelle", use_container_width=True,
            on_click=_basculer_sortie_manuelle,
            help="Choisir la boîte à retirer dans la liste, sans douchette.")
        st.caption("Chaque scan retire **une boîte**. Le Data Matrix désigne "
                   "la boîte exacte ; un code-barres linéaire ne donne que le "
                   "produit, et c'est alors le lot qui **périme le plus tôt** "
                   "qui sort.")

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

    if mode == MODE_ENTREE:
        # Juste sous le champ : la présélection répond à ce qui vient d'être
        # tapé, la reléguer sous les panneaux repliés la ferait manquer.
        _preselection_par_nom()
        _base_publique()
        _import_repertoire(repertoire)
        inventaire, repertoire = _etat()

    if "sf_en_attente" in st.session_state and mode == MODE_ENTREE:
        _formulaire_complement(inventaire, repertoire)
        inventaire, repertoire = _etat()

    # --- Inventaire --------------------------------------------------------
    st.divider()
    etape("2", "Inventaire", "Une ligne par lot : la péremption appartient "
                             "à la boîte, pas au produit.")
    _bandeau_kpi(stock_ferme.resume_inventaire(inventaire, aujourdhui),
                 tuile_kpi)

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

    # Le tableau ne devient modifiable que sur l'inventaire ENTIER : corriger
    # une vue filtrée réécrirait le stock en perdant les lignes masquées.
    if filtre_actif:
        st.dataframe(
            stock_ferme.inventaire_affichable(vue_filtree, aujourdhui, tri),
            use_container_width=True, hide_index=True)
        st.caption(f"{len(vue_filtree)} lot(s) affiché(s). Videz la recherche "
                   "et décochez le filtre pour corriger l'inventaire.")
        corrige = None
    else:
        corrige = _tableau_editable(inventaire, aujourdhui, tri)
    if corrige is not None:
        _enregistrer(inventaire=corrige)
        st.rerun()

    # --- Impression --------------------------------------------------------
    st.divider()
    etape("3", "Imprimez ou exportez", "Liste de contrôle du stock physique.")
    _zone_impression(inventaire, aujourdhui, tri)
