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
from pathlib import Path

import pandas as pd
import streamlit as st

import stock_ferme

_journal = logging.getLogger("pharmacie.stock_ferme.ui")

INVENTAIRE_PATH = Path(__file__).parent / "stock_ferme.csv"
REPERTOIRE_PATH = Path(__file__).parent / "stock_ferme_produits.csv"

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


def _enregistrer(inventaire=None, repertoire=None) -> None:
    """Écrit sur le disque : c'est la « mémoire » entre deux ouvertures."""
    if inventaire is not None:
        st.session_state["sf_inventaire"] = inventaire
        stock_ferme.sauver_inventaire(inventaire, INVENTAIRE_PATH)
    if repertoire is not None:
        st.session_state["sf_repertoire"] = repertoire
        stock_ferme.sauver_repertoire(repertoire, REPERTOIRE_PATH)


# ---------------------------------------------------------------------------
# Saisie
# ---------------------------------------------------------------------------

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
    connu = stock_ferme.produit_connu(repertoire, code.cip)

    # Boîte entièrement identifiée (Data Matrix d'un produit déjà nommé) :
    # elle entre au stock sans confirmation — c'est le geste du comptoir.
    if (code.reconnu and code.peremption is not None and connu
            and st.session_state.get("sf_ajout_direct", True)):
        entree = stock_ferme.EntreeStock(
            cip=code.cip, nom=connu["nom"], dosage=connu["dosage"],
            boites=1, unites_par_boite=connu["unites_par_boite"],
            peremption=code.peremption, lot=code.lot)
        _enregistrer(inventaire=stock_ferme.ajouter_entree(inventaire, entree))
        st.session_state["sf_message"] = (
            "ok", f"➕ {connu['nom']} {connu['dosage']} — 1 boîte "
                  f"(péremption {code.peremption:%d/%m/%Y}"
                  + (f", lot {code.lot}" if code.lot else "") + ")")
        st.session_state.pop("sf_en_attente", None)
        return

    # Sinon : formulaire de complément, pré-rempli avec ce qu'on sait déjà.
    st.session_state["sf_en_attente"] = {
        "cip": code.cip,
        "nom": (connu or {}).get("nom", ""),
        "dosage": (connu or {}).get("dosage", ""),
        "unites_par_boite": (connu or {}).get("unites_par_boite", 0),
        "peremption": code.peremption,
        "lot": code.lot,
        "brut": code.brut,
        "reconnu": code.reconnu,
    }
    if not code.reconnu:
        st.session_state["sf_message"] = (
            "avertissement",
            f"Code non reconnu : « {code.brut} ». Complétez la fiche "
            "ci-dessous — elle sera mémorisée pour les prochains scans.")
    else:
        st.session_state["sf_message"] = None


def _saisie_manuelle_vierge() -> None:
    st.session_state["sf_en_attente"] = {
        "cip": "", "nom": "", "dosage": "", "unites_par_boite": 0,
        "peremption": None, "lot": "", "brut": "", "reconnu": True}
    st.session_state["sf_message"] = None


def _formulaire_complement(inventaire: pd.DataFrame,
                           repertoire: pd.DataFrame) -> None:
    """Fiche d'ajout : ce que le code ne dit pas, l'opérateur le complète."""
    attente = st.session_state["sf_en_attente"]
    with st.form("sf_form_ajout", clear_on_submit=False):
        st.markdown("**Fiche du produit à enregistrer**")

        col1, col2, col3 = st.columns([3, 2, 2])
        nom = col1.text_input("Nom du médicament *", value=attente["nom"],
                              placeholder="DOLIPRANE")
        dosage = col2.text_input("Dosage", value=attente["dosage"],
                                 placeholder="1000 mg")
        cip = col3.text_input("Code CIP", value=attente["cip"],
                              placeholder="3400912345678")

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
        st.error("Le nom du médicament est obligatoire.")
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
        tuile("🔴 Moins de 3 mois", resume["critiques"],
              "serious" if resume["critiques"] else "",
              sous=f'{resume["vigilance"]} autre(s) sous 6 mois'),
    ]) + "</div>", unsafe_allow_html=True)


def _tableau_editable(inventaire: pd.DataFrame,
                      aujourdhui: date) -> pd.DataFrame | None:
    """Inventaire modifiable ; renvoie le tableau corrigé s'il a changé."""
    vue = stock_ferme.inventaire_affichable(inventaire, aujourdhui)
    if vue.empty:
        st.info("Inventaire vide — scannez une première boîte ci-dessus.")
        return None

    edite = st.data_editor(
        vue, hide_index=True, use_container_width=True, num_rows="dynamic",
        key="sf_editeur",
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


def _zone_impression(inventaire: pd.DataFrame, aujourdhui: date) -> None:
    st.markdown("**Imprimer la liste de stock**")
    st.caption("Nom du médicament, dosage, code CIP, nombre de boîtes et "
               "d'unités, et date de péremption de chaque lot.")

    col_csv, col_pdf = st.columns(2)
    col_csv.download_button(
        "📄 Télécharger en CSV",
        data=stock_ferme.exporter_csv(inventaire, aujourdhui),
        file_name=stock_ferme.nom_fichier_stock_ferme("csv", aujourdhui),
        mime=_MIME_CSV, use_container_width=True)
    try:
        pdf = stock_ferme.exporter_pdf(inventaire, "Stock fermé", aujourdhui)
        col_pdf.download_button(
            "🖨️ Télécharger en PDF",
            data=pdf,
            file_name=stock_ferme.nom_fichier_stock_ferme("pdf", aujourdhui),
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
        st.caption("🔒 100 % local : l'inventaire ne quitte pas ce poste.")
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
    etape("1", "Scannez ou saisissez le produit",
          "Douchette (code CIP ou Data Matrix) — ou saisie au clavier.")
    col_scan, col_manuel = st.columns([3, 1])
    col_scan.text_input(
        "Code scanné", key="sf_scan", on_change=_traiter_scan,
        placeholder="Douchez la boîte ici (le champ se vide tout seul)",
        label_visibility="collapsed")
    col_manuel.button("⌨️ Saisie manuelle", use_container_width=True,
                      on_click=_saisie_manuelle_vierge)
    st.caption("Le Data Matrix des boîtes récentes fournit d'un coup le code "
               "CIP, la date de péremption et le n° de lot. Un code-barres "
               "linéaire ne donne que le CIP : la péremption reste à saisir.")

    if "sf_en_attente" in st.session_state:
        _formulaire_complement(inventaire, repertoire)
        inventaire, repertoire = _etat()

    # --- Inventaire --------------------------------------------------------
    st.divider()
    etape("2", "Inventaire", "Une ligne par lot : la péremption appartient "
                             "à la boîte, pas au produit.")
    _bandeau_kpi(stock_ferme.resume_inventaire(inventaire, aujourdhui),
                 tuile_kpi)
    corrige = _tableau_editable(inventaire, aujourdhui)
    if corrige is not None:
        _enregistrer(inventaire=corrige)
        st.rerun()

    # --- Impression --------------------------------------------------------
    st.divider()
    etape("3", "Imprimez ou exportez", "Liste de contrôle du stock physique.")
    _zone_impression(inventaire, aujourdhui)
