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


def _index_base() -> dict:
    """Index « code CIP → dénomination » de la base publique.

    Relu une seule fois par session, et à nouveau si le fichier a changé
    (mise à jour de la base) — 40 000 codes, inutile de les relire à chaque
    interaction.
    """
    empreinte = (BASE_MEDICAMENTS_PATH.stat().st_mtime
                 if BASE_MEDICAMENTS_PATH.exists() else 0)
    if st.session_state.get("sf_base_empreinte") != empreinte:
        st.session_state["sf_base_index"] = base_medicaments.index_par_cip(
            base_medicaments.charger_table(BASE_MEDICAMENTS_PATH))
        st.session_state["sf_base_empreinte"] = empreinte
        _journal.info("Base des médicaments : %d code(s) chargé(s)",
                      len(st.session_state["sf_base_index"]))
    return st.session_state["sf_base_index"]


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
            "l'inventaire. Vérifiez le code, ou passez en mode Entrée.")
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
                f"Code non reconnu : « {code.brut} ». Une sortie se fait par "
                "scan ; pour un produit sans code, supprimez la ligne dans "
                "le tableau.")
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

    st.session_state["sf_en_attente"] = {
        "cip": code.cip,
        # Même quand la fiche s'ouvre (pas de péremption, ajout direct
        # désactivé…), le nom trouvé dans la base est déjà là : il n'y a
        # plus qu'à valider.
        "nom": (connu or {}).get("nom", ""),
        "dosage": (connu or {}).get("dosage", ""),
        "unites_par_boite": (connu or {}).get("unites_par_boite", 0),
        "peremption": code.peremption,
        "lot": code.lot,
        "brut": code.brut,
        "reconnu": code.reconnu,
    }
    rappel = (" La fiche précédente, non validée, a été abandonnée."
              if abandonnee else "")
    if not code.reconnu:
        st.session_state["sf_message"] = (
            "avertissement",
            f"Code non reconnu : « {code.brut} ». Complétez la fiche "
            "ci-dessous — elle sera mémorisée pour les prochains scans."
            + rappel)
    elif abandonnee:
        st.session_state["sf_message"] = ("avertissement", rappel.strip())
    else:
        st.session_state["sf_message"] = None


def _saisie_manuelle_vierge() -> None:
    st.session_state["sf_en_attente"] = {
        "cip": "", "nom": "", "dosage": "", "unites_par_boite": 0,
        "peremption": None, "lot": "", "brut": "", "reconnu": True}
    st.session_state["sf_message"] = None


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
    if not info["existe"]:
        etat, ouvert = "⚠️ non installée", True
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
        if info["existe"]:
            st.caption(f"Dernière mise à jour : {info['date']:%d/%m/%Y}.")

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


def _tableau_editable(inventaire: pd.DataFrame,
                      aujourdhui: date) -> pd.DataFrame | None:
    """Inventaire modifiable ; renvoie le tableau corrigé s'il a changé."""
    vue = stock_ferme.inventaire_affichable(inventaire, aujourdhui)
    if vue.empty:
        st.info("Inventaire vide — scannez une première boîte ci-dessus.")
        return None

    # L'éditeur mémorise ses corrections en cours dans l'état de session, sous
    # sa clé. Après un enregistrement, l'inventaire a changé de forme (lignes
    # supprimées, ordre revu par échéance) : réutiliser la même clé
    # réappliquerait les anciennes corrections aux NOUVELLES lignes. On repart
    # donc d'un éditeur neuf à chaque enregistrement.
    edite = st.data_editor(
        vue, hide_index=True, use_container_width=True, num_rows="dynamic",
        key=f"sf_editeur_{st.session_state.get('sf_generation', 0)}",
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

    # Le besoin le plus fréquent n'est pas la liste complète mais la liste de
    # RETRAIT : ce qui est périmé ou ne passera pas le mois.
    retrait_seul = st.checkbox(
        "N'imprimer que les lots à retirer (périmés et moins d'un mois)",
        key="sf_impression_retrait")
    a_imprimer = (stock_ferme.filtrer_inventaire(
        inventaire, statuts=stock_ferme.STATUTS_A_TRAITER,
        aujourdhui=aujourdhui) if retrait_seul else inventaire)
    titre = "Stock fermé — lots à retirer" if retrait_seul else "Stock fermé"
    prefixe = "stock_ferme_retrait" if retrait_seul else "stock_ferme"
    nombre = len(stock_ferme.inventaire_affichable(a_imprimer, aujourdhui))
    st.caption(f"{nombre} lot(s) dans le document.")

    col_csv, col_pdf = st.columns(2)
    col_csv.download_button(
        "📄 Télécharger en CSV",
        data=stock_ferme.exporter_csv(a_imprimer, aujourdhui),
        file_name=f"{prefixe}_{aujourdhui:%Y-%m-%d}.csv",
        mime=_MIME_CSV, use_container_width=True)
    try:
        pdf = stock_ferme.exporter_pdf(a_imprimer, titre, aujourdhui)
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
    col_scan, col_manuel = st.columns([3, 1])
    col_scan.text_input(
        "Code scanné", key="sf_scan", on_change=_traiter_scan,
        placeholder=("Douchez la boîte à ajouter" if mode == MODE_ENTREE
                     else "Douchez la boîte à sortir")
                    + " (le champ se vide tout seul)",
        label_visibility="collapsed")
    col_manuel.button("⌨️ Saisie manuelle", use_container_width=True,
                      disabled=mode == MODE_SORTIE,
                      on_click=_saisie_manuelle_vierge)
    if mode == MODE_ENTREE:
        st.caption("Le Data Matrix des boîtes récentes fournit d'un coup le "
                   "code CIP, la date de péremption et le n° de lot. Un "
                   "code-barres linéaire ne donne que le CIP : la péremption "
                   "reste à saisir.")
    else:
        st.caption("Chaque scan retire **une boîte**. Le Data Matrix désigne "
                   "la boîte exacte ; un code-barres linéaire ne donne que le "
                   "produit, et c'est alors le lot qui **périme le plus tôt** "
                   "qui sort.")

    if mode == MODE_ENTREE:
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

    col_rech, col_filtre = st.columns([3, 2])
    recherche = col_rech.text_input(
        "🔎 Rechercher (nom, dosage, code CIP ou n° de lot)",
        key="sf_recherche", placeholder="ex. MORPHINE, 3400937… ou LOT-A")
    a_traiter = col_filtre.checkbox(
        "⚠️ N'afficher que les lots à traiter", key="sf_filtre_traiter",
        help="Périmés et lots de moins d'un mois.")
    vue_filtree = stock_ferme.filtrer_inventaire(
        inventaire, recherche,
        stock_ferme.STATUTS_A_TRAITER if a_traiter else None, aujourdhui)
    filtre_actif = bool(recherche) or a_traiter
    if filtre_actif and vue_filtree.empty:
        st.info("Aucun lot ne correspond à ce filtre.")

    # Le tableau ne devient modifiable que sur l'inventaire ENTIER : corriger
    # une vue filtrée réécrirait le stock en perdant les lignes masquées.
    if filtre_actif:
        st.dataframe(stock_ferme.inventaire_affichable(vue_filtree, aujourdhui),
                     use_container_width=True, hide_index=True)
        st.caption(f"{len(vue_filtree)} lot(s) affiché(s). Videz la recherche "
                   "et décochez le filtre pour corriger l'inventaire.")
        corrige = None
    else:
        corrige = _tableau_editable(inventaire, aujourdhui)
    if corrige is not None:
        _enregistrer(inventaire=corrige)
        st.rerun()

    # --- Impression --------------------------------------------------------
    st.divider()
    etape("3", "Imprimez ou exportez", "Liste de contrôle du stock physique.")
    _zone_impression(inventaire, aujourdhui)
