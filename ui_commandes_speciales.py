# -*- coding: utf-8 -*-
"""Interface du Module 4 — Commandes spéciales.

Écran autonome : il ne dépend d'aucun fichier déposé. Toute la logique est
dans ``commandes_speciales.py`` ; ce fichier ne fait que l'habillage
Streamlit.

Ergonomie visée : **répondre à trois questions avant tout le reste** — qui
puis-je facturer aujourd'hui, pour qui faut-il commander, quelle commande
est en retard. Le tableau complet vient après : c'est la référence, pas le
geste du matin.
"""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd
import streamlit as st

import base_medicaments
import commandes_speciales as cs
import commun
import ui_commun

_journal = logging.getLogger("pharmacie.commandes_speciales.ui")

DOSSIERS_PATH = ui_commun.dossier_donnees() / "commandes_speciales.csv"
INVENTAIRE_PATH = ui_commun.dossier_donnees() / "stock_ferme.csv"
BASE_MEDICAMENTS_PATH = ui_commun.dossier_donnees() / "base_medicaments.csv"

_MIME_CSV = "text/csv"
_MIME_PDF = "application/pdf"

#: Colonnes que l'on peut corriger directement dans le tableau. Les statuts
#: et les comptes à rebours n'en font pas partie : ils se déduisent.
_COLONNES_EDITABLES = ("Patient", "Nom du produit", "Boîtes en main",
                       "Envoi du mail", "Réception", "Dernière facturation",
                       "Notes")

MESSAGE_VERROU = (
    "Un autre poste enregistre au même instant — rien n'a été modifié. "
    "Refaites le geste dans un instant.")
MESSAGE_FICHIER_BLOQUE = (
    "Impossible d'enregistrer : le fichier `{fichier}` est ouvert dans un "
    "autre programme (Excel, le plus souvent). Fermez-le, puis refaites le "
    "geste — rien n'a été perdu.")


def _colonnes_vue() -> dict:
    """Mise en forme du tableau, partagée par toutes ses apparitions.

    Tout est centré, comme dans le stock interne : sur des colonnes larges,
    un nombre collé au bord droit finit loin de son en-tête.
    """
    # Colonnes de DATE et de nombre pouvant être vides : déclarées en
    # texte, parce que Streamlit affiche « None » pour une date absente
    # comme pour un entier absent — seule une chaîne vide s'affiche vide.
    # Les valeurs sont mises en forme par ``cs.pour_affichage``, et
    # ``parser_date`` sait relire « 24/08/2026 » comme « 24082026 » si on
    # les corrige à la main.
    jour = dict(width="small", alignment="center")
    nombre = dict(min_value=0, step=1, width="small", alignment="center")
    return {
        "Facturation": st.column_config.TextColumn(
            "Facturation", width="small", alignment="center"),
        "Patient": st.column_config.TextColumn("Patient", alignment="center"),
        "Nom du produit": st.column_config.TextColumn(
            "Produit", alignment="center"),
        "Code CIP": st.column_config.TextColumn(
            "Code CIP", alignment="center", disabled=True),
        "Boîtes en main": st.column_config.NumberColumn("En main", **nombre),
        "Facturable le": st.column_config.TextColumn("Facturable le", **jour),
        "Jours avant facturation": st.column_config.TextColumn(
            "J avant fact.", width="small", alignment="center"),
        "Commande": st.column_config.TextColumn(
            "Commande", width="small", alignment="center"),
        "Envoi du mail": st.column_config.TextColumn("Mail envoyé", **jour),
        "Réception": st.column_config.TextColumn("Reçu le", **jour),
        "Attente (j)": st.column_config.TextColumn(
            "Attente (j)", width="small", alignment="center"),
        "Délai observé (j)": st.column_config.TextColumn(
            "Délai réel (j)", width="small", alignment="center"),
        "À commander": st.column_config.TextColumn(
            "À commander", width="small", alignment="center"),
        "Dernière facturation": st.column_config.TextColumn(
            "Dern. facturation", **jour),
        "Notes": st.column_config.TextColumn("Notes", alignment="center"),
    }


# ---------------------------------------------------------------------------
# Mémoire de session
# ---------------------------------------------------------------------------

def _etat() -> pd.DataFrame:
    """Les dossiers, relus dès qu'un autre poste écrit.

    Même précaution que le stock interne : sur un serveur partagé, garder la
    photo prise à l'ouverture ferait réenregistrer plus tard une version qui
    ignore la facturation saisie au comptoir d'à côté.
    """
    empreinte = cs.empreinte_fichier(DOSSIERS_PATH)
    if ("cs_dossiers" not in st.session_state
            or st.session_state.get("cs_empreinte") != empreinte):
        premiere = "cs_dossiers" not in st.session_state
        st.session_state["cs_dossiers"] = cs.charger(DOSSIERS_PATH)
        st.session_state["cs_empreinte"] = empreinte
        if not premiere:
            st.session_state["cs_generation"] = (
                st.session_state.get("cs_generation", 0) + 1)
        _journal.info("Commandes spéciales — %d dossier(s) relus depuis %s",
                      len(st.session_state["cs_dossiers"]), DOSSIERS_PATH)
    return st.session_state["cs_dossiers"]


def _memoriser(dossiers, empreinte=None) -> None:
    st.session_state["cs_dossiers"] = dossiers
    st.session_state["cs_empreinte"] = (
        empreinte if empreinte is not None
        else cs.empreinte_fichier(DOSSIERS_PATH))
    st.session_state["cs_generation"] = (
        st.session_state.get("cs_generation", 0) + 1)


def _appliquer(mouvement):
    """Applique un mouvement aux dossiers **du disque**, sous verrou.

    Deux comptoirs peuvent enregistrer une facturation au même instant :
    sans cela, la seconde effacerait la première et les 22 jours
    repartiraient de la mauvaise date — donc un refus de la caisse.
    """
    try:
        ecriture = cs.appliquer_aux_dossiers(DOSSIERS_PATH, mouvement)
    except cs.VerrouIndisponible:
        st.session_state["cs_message"] = ("avertissement", MESSAGE_VERROU)
        return None
    except OSError as erreur:
        _journal.error("Dossiers non enregistrés : %s", erreur)
        st.session_state["cs_message"] = (
            "avertissement",
            MESSAGE_FICHIER_BLOQUE.format(fichier=DOSSIERS_PATH.name))
        return None
    _memoriser(ecriture.tableau, ecriture.empreinte)
    return ecriture.tableau


def _catalogue() -> list:
    """Le catalogue des boîtes de la base publique, figé par session.

    Recalculé à chaque interaction, il repartirait en entier dans le
    navigateur au lieu d'une simple référence.
    """
    empreinte = (BASE_MEDICAMENTS_PATH.stat().st_mtime
                 if BASE_MEDICAMENTS_PATH.exists() else 0)
    if st.session_state.get("cs_base_empreinte") != empreinte:
        table = base_medicaments.charger_table(BASE_MEDICAMENTS_PATH)
        catalogue = base_medicaments.catalogue(
            base_medicaments.index_par_nom(table))
        st.session_state["cs_base_catalogue"] = catalogue
        st.session_state["cs_base_par_libelle"] = {
            m["libelle"]: m for m in catalogue}
        st.session_state["cs_base_empreinte"] = empreinte
    return st.session_state["cs_base_catalogue"]


def _inventaire_stock_ferme() -> pd.DataFrame:
    """L'inventaire du stock interne, lu SANS importer son module.

    Le rapprochement a besoin des boîtes physiques, mais ce module n'a pas à
    dépendre du stock interne : on lit son fichier, colonnes utiles seulement.
    S'il n'existe pas, le rapprochement dira simplement « 0 au stock ».
    """
    if not INVENTAIRE_PATH.exists():
        return pd.DataFrame(columns=["Code CIP", "Boîtes"])
    try:
        tableau = pd.read_csv(INVENTAIRE_PATH, sep=";", dtype=str,
                              encoding="utf-8-sig").fillna("")
    except Exception:
        _journal.warning("Inventaire du stock interne illisible : %s",
                         INVENTAIRE_PATH)
        return pd.DataFrame(columns=["Code CIP", "Boîtes"])
    return tableau.reindex(columns=["Code CIP", "Boîtes"]).fillna("")


# ---------------------------------------------------------------------------
# Saisie
# ---------------------------------------------------------------------------

def _medicament_choisi() -> None:
    """Une boîte vient d'être choisie : nom et CIP sont renseignés."""
    libelle = st.session_state.get("cs_auto_nom")
    st.session_state["cs_auto_nom"] = None
    medicament = st.session_state.get("cs_base_par_libelle", {}).get(libelle)
    if medicament:
        st.session_state["cs_nouveau_produit"] = medicament["nom"]
        st.session_state["cs_nouveau_cip"] = medicament["cip"]


def _panneau_ajout(dossiers: pd.DataFrame) -> None:
    """L'ajout d'un dossier, en haut de l'écran et prêt à enchaîner.

    Trois décisions, chacune née d'un défaut constaté :

    - **en haut**, avant les listes du matin. Placé en troisième position,
      on ne le voyait pas sans faire défiler, et l'écran donnait
      l'impression de ne gérer qu'un seul patient — celui de la liste
      déroulante des gestes ;
    - **ouvert d'office** tant qu'aucun dossier n'existe : un module vide
      n'a que cette action-là. Et il **reste ouvert** après un ajout, pour
      qu'on enchaîne les saisies sans le rouvrir à chaque fois ;
    - **replié** ensuite, pour ne pas manger l'écran de l'usage quotidien.
    """
    vide = dossiers is None or dossiers.empty
    ouvert = vide or st.session_state.get("cs_ajout_ouvert", False)
    nombre = 0 if vide else len(dossiers)
    titre = ("➕ Ouvrez un premier dossier" if vide else
             f"➕ Ouvrir un dossier — {nombre} dossier"
             f"{'s' if nombre > 1 else ''} déjà suivi"
             f"{'s' if nombre > 1 else ''}")
    with st.expander(titre, expanded=ouvert):
        st.caption("Un dossier par patient ET par médicament. Le même "
                   "patient peut en avoir plusieurs, et il n'y a pas de "
                   "limite au nombre de dossiers.")
        _formulaire_nouveau()


#: Ce qu'on cherche dans le fichier importé, et les mots qui le trahissent.
#: L'ordre compte : le premier en-tête contenant l'un de ces mots gagne.
_ROLES_IMPORT = [
    ("patient", "Patient", True,
     ("patient", "nom du patient", "beneficiaire", "assure", "client")),
    ("produit", "Médicament", True,
     ("produit", "medicament", "specialite", "libelle", "designation",
      "article", "denomination")),
    ("cip", "Code CIP", False, ("cip", "code", "ean", "acl")),
    ("boites", "Boîtes en main", False,
     ("boite", "quantite", "qte", "stock", "en main", "nombre")),
    ("envoi", "Envoi du mail", False, ("envoi", "mail", "commande le",
                                       "commande")),
    ("reception", "Réception", False, ("reception", "recu", "livraison",
                                       "livre")),
    ("facturation", "Dernière facturation", False,
     ("facturation", "facture", "delivrance", "delivre")),
    ("notes", "Notes", False, ("note", "remarque", "commentaire",
                               "observation")),
]

_AUCUNE = "— aucune —"


def _colonne_probable(colonnes, mots) -> str:
    """La colonne du fichier qui correspond le mieux à ce rôle.

    Deviner évite de faire choisir huit colonnes à la main quand les
    en-têtes sont clairs. Deviner **mal** est sans gravité : la
    proposition reste modifiable avant l'import.
    """
    for mot in mots:
        for colonne in colonnes:
            if mot in commun.sans_accents(str(colonne)):
                return colonne
    return _AUCUNE


def _import_fichier(dossiers: pd.DataFrame) -> None:
    """Charger des dossiers depuis un fichier Excel, CSV ou PDF.

    Retaper trente patients qui existent déjà dans un tableur, c'est une
    demi-journée et des fautes de frappe sur des noms.

    La LECTURE du fichier est faite ici, dans l'interface : le moteur ne
    reçoit que des lignes, et reste ainsi indépendant de tout format —
    c'est ce qui permet de le tester sans ouvrir un seul fichier.
    """
    with st.expander("📂 Importer depuis un fichier (Excel, CSV, PDF)"):
        st.caption(
            "Vos dossiers existants sont **complétés**, jamais remplacés : "
            "un patient déjà suivi garde ses dates et son avance si le "
            "fichier ne les porte pas. Rien n'est écrit tant que vous n'avez "
            "pas cliqué sur le bouton d'import.")
        depot = st.file_uploader(
            "Fichier", type=["xlsx", "xlsm", "xls", "csv", "txt", "pdf"],
            key="cs_import_fichier", label_visibility="collapsed")
        if depot is None:
            return
        try:
            tableau = commun.charger_fichier(depot, depot.name)
        except Exception as erreur:
            st.error(f"**Fichier illisible.** {erreur}")
            return
        if tableau is None or tableau.empty:
            st.warning("Ce fichier ne contient aucune ligne exploitable. "
                       "Pour un PDF, vérifiez qu'il contient du texte et non "
                       "une simple image scannée.")
            return

        st.caption(f"{len(tableau)} ligne(s) lue(s). Vérifiez les colonnes "
                   "ci-dessous, puis importez.")
        st.dataframe(tableau.head(5), use_container_width=True,
                     hide_index=True)

        colonnes = list(tableau.columns)
        choix = {}
        rangees = [_ROLES_IMPORT[i:i + 4] for i in range(0, len(_ROLES_IMPORT),
                                                         4)]
        for rangee in rangees:
            for cellule, (role, libelle, requis, mots) in zip(
                    st.columns(len(rangee)), rangee):
                options = ([_AUCUNE] + colonnes if not requis else colonnes)
                propose = _colonne_probable(colonnes, mots)
                if requis and propose == _AUCUNE:
                    propose = colonnes[0]
                choix[role] = cellule.selectbox(
                    libelle + (" *" if requis else ""), options,
                    index=options.index(propose) if propose in options else 0,
                    key=f"cs_import_{role}")

        if not st.button("📥 Importer ces dossiers", type="primary",
                         use_container_width=True, key="cs_import_valider"):
            return

        lignes = []
        for _, ligne in tableau.iterrows():
            # Une colonne non désignée est ABSENTE du dictionnaire, elle
            # n'est pas mise à vide : c'est ce qui évite qu'un fichier sans
            # quantités remette toutes les avances à zéro.
            lignes.append({role: ligne[colonne]
                           for role, colonne in choix.items()
                           if colonne != _AUCUNE})

        resultat = {}

        def mouvement(courant):
            nouveau, ajoutes, completes, ignores = cs.importer_dossiers(
                courant, lignes)
            resultat.update(ajoutes=ajoutes, completes=completes,
                            ignores=ignores, total=len(nouveau))
            return nouveau

        if _appliquer(mouvement) is None:
            return
        st.session_state["cs_message"] = (
            "ok",
            f"📂 {resultat['ajoutes']} dossier(s) ouvert(s), "
            f"{resultat['completes']} complété(s)"
            + (f" · {resultat['ignores']} ligne(s) sans patient ou sans "
               "médicament ignorée(s)" if resultat["ignores"] else "")
            + f" · {resultat['total']} dossier(s) suivis désormais.")
        st.rerun()


def _formulaire_nouveau() -> None:
    """Ouvrir un dossier : un patient, un produit, et les dates connues."""
    catalogue = _catalogue()
    if catalogue:
        st.selectbox(
            "Médicament", [m["libelle"] for m in catalogue], index=None,
            key="cs_auto_nom", on_change=_medicament_choisi,
            label_visibility="collapsed",
            placeholder="🔎 Tapez le nom du médicament, puis le dosage pour "
                        f"affiner ({len(catalogue)} boîtes référencées)")
    else:
        st.caption("Base publique des médicaments absente : le nom et le "
                   "code CIP sont à taper à la main. Installez-la depuis "
                   "l'espace « Stock interne » pour les voir se remplir seuls.")

    with st.form("cs_nouveau", clear_on_submit=True):
        c1, c2, c3 = st.columns([2, 3, 2])
        patient = c1.text_input("Patient", key="cs_nouveau_patient",
                               placeholder="Nom du patient")
        produit = c2.text_input("Médicament", key="cs_nouveau_produit",
                                placeholder="Dénomination")
        cip = c3.text_input("Code CIP", key="cs_nouveau_cip",
                            placeholder="13 chiffres")
        c4, c5, c6, c7 = st.columns(4)
        boites = c4.number_input("Boîtes en main", min_value=0, step=1,
                                 value=0, key="cs_nouveau_boites")
        envoi = c5.text_input("Envoi du mail", key="cs_nouveau_envoi",
                              placeholder="jj/mm/aaaa")
        reception = c6.text_input("Réception", key="cs_nouveau_reception",
                                  placeholder="jj/mm/aaaa")
        facturation = c7.text_input("Dernière facturation",
                                    key="cs_nouveau_facturation",
                                    placeholder="jj/mm/aaaa")
        notes = st.text_input("Notes", key="cs_nouveau_notes",
                              placeholder="Facultatif")
        valide = st.form_submit_button("➕ Ouvrir le dossier", type="primary",
                                       use_container_width=True)

    if not valide:
        return
    if not patient.strip() or not produit.strip():
        st.error("**Patient et médicament sont indispensables.** C'est le "
                 "couple qui identifie un dossier — et c'est lui qui porte "
                 "les 22 jours entre deux facturations.")
        return

    resultat = _appliquer(lambda courant: cs.ajouter_dossier(
        courant, patient, produit, cip, boites=int(boites), envoi=envoi,
        reception=reception, facturation=facturation, notes=notes))
    if resultat is None:
        return
    # Le panneau reste ouvert : on saisit rarement un seul dossier. Devoir
    # le rouvrir entre chaque patient est ce qui donnait l'impression de ne
    # pas pouvoir en ajouter d'autres.
    st.session_state["cs_ajout_ouvert"] = True
    st.session_state["cs_message"] = (
        "ok", f"📁 {patient} — {produit} : dossier enregistré. "
              f"{len(resultat)} dossier(s) suivi(s) — le formulaire est vide, "
              "vous pouvez enchaîner avec le patient suivant.")
    st.rerun()


def _actions_rapides(dossiers: pd.DataFrame, aujourdhui: date) -> None:
    """Les trois gestes du comptoir, sans passer par le tableau.

    Facturer, recevoir, commander : chacun met à jour la bonne date ET le
    nombre de boîtes, parce que ce sont les mêmes gestes dans la réalité.
    Laisser corriger deux cases à la main serait laisser l'avance fausse.
    """
    if dossiers.empty:
        st.info("Aucun dossier pour l'instant — ouvrez-en un tout en haut "
                "de l'écran, dans « ➕ Ouvrez un premier dossier ».")
        return
    vue = cs.vue_affichable(dossiers, aujourdhui, cs.TRI_PATIENT)
    libelles = [f"{l['Patient']} — {l['Nom du produit']}"
                for _, l in vue.iterrows()]

    with st.container(border=True):
        st.markdown("**Enregistrer un geste**")
        choix = st.selectbox("Dossier", range(len(libelles)),
                             format_func=lambda i: libelles[i],
                             key="cs_geste_dossier",
                             label_visibility="collapsed")
        ligne = vue.iloc[choix]
        jour = st.date_input("Date du geste", value=aujourdhui,
                            format="DD/MM/YYYY", key="cs_geste_date")
        c1, c2, c3 = st.columns(3)
        patient, cip = ligne["Patient"], ligne["Code CIP"]
        produit = ligne["Nom du produit"]

        if c1.button("💰 Facturé et délivré", use_container_width=True,
                     type="primary"):
            if _appliquer(lambda courant: cs.enregistrer_facturation(
                    courant, patient, cip, produit, jour)) is not None:
                st.session_state["cs_message"] = (
                    "ok", f"💰 {patient} — facturé le {jour:%d/%m/%Y}, une "
                          "boîte sortie. Prochaine facturation possible le "
                          f"{cs.facturable_le(jour):%d/%m/%Y}.")
            st.rerun()

        if c2.button("📥 Boîte reçue", use_container_width=True):
            if _appliquer(lambda courant: cs.enregistrer_reception(
                    courant, patient, cip, produit, jour)) is not None:
                st.session_state["cs_message"] = (
                    "ok", f"📥 {patient} — boîte reçue le {jour:%d/%m/%Y}, "
                          "elle entre en avance.")
            st.rerun()

        if c3.button("📧 Mail de commande envoyé", use_container_width=True):
            if _appliquer(lambda courant: cs.enregistrer_envoi(
                    courant, patient, cip, produit, jour)) is not None:
                st.session_state["cs_message"] = (
                    "ok", f"📧 {patient} — commande partie le "
                          f"{jour:%d/%m/%Y}.")
            st.rerun()


# ---------------------------------------------------------------------------
# Les trois listes du matin
# ---------------------------------------------------------------------------

def _liste(titre: str, aide: str, tableau: pd.DataFrame,
           colonnes: list, vide: str) -> None:
    """Une des trois listes. Vide, elle le dit — et c'est une bonne
    nouvelle, pas une absence de données."""
    st.markdown(f"**{titre}**")
    if tableau.empty:
        st.caption(vide)
        return
    st.caption(aide)
    st.dataframe(cs.pour_affichage(tableau[colonnes]),
                 use_container_width=True, hide_index=True,
                 column_config=_colonnes_vue())


def _listes_du_matin(dossiers: pd.DataFrame, aujourdhui: date,
                     avance: int) -> None:
    facturer = cs.a_facturer_aujourdhui(dossiers, aujourdhui)
    commander = cs.a_commander_maintenant(dossiers, aujourdhui, avance)
    retard = cs.commandes_en_retard(dossiers, aujourdhui)

    colonne_gauche, colonne_droite = st.columns(2)
    with colonne_gauche:
        _liste("💰 À facturer aujourd'hui",
               "Les 22 jours sont écoulés : la caisse acceptera.",
               facturer,
               ["Patient", "Nom du produit", "Boîtes en main",
                "Dernière facturation"],
               "Personne à facturer aujourd'hui.")
    with colonne_droite:
        _liste("📦 À commander maintenant",
               "Sans quoi la boîte n'arrivera pas avant la facturation "
               "suivante.",
               commander,
               ["Patient", "Nom du produit", "Boîtes en main",
                "Jours avant facturation", "Délai observé (j)"],
               "Rien à commander : les avances tiennent.")

    if not retard.empty:
        _liste("⏰ Commandes en retard",
               "Mail parti, rien reçu, délai habituel dépassé : relancez.",
               retard,
               ["Patient", "Nom du produit", "Envoi du mail", "Attente (j)"],
               "")


# ---------------------------------------------------------------------------
# Tableau complet
# ---------------------------------------------------------------------------

def _tableau(dossiers: pd.DataFrame, aujourdhui: date, tri: str,
             avance: int, vue_choisie: str):
    """Le tableau de référence, dans l'une de ses deux vues.

    Quinze colonnes d'un bloc ne se lisent pas : trois disaient la
    facturation (statut, date, compte à rebours), cinq la commande. Sur
    deux dossiers cela passait ; avec vingt patients, plus rien ne ressort.

    Deux vues, donc, parce qu'il y a deux gestes distincts : **regarder où
    en est chaque patient**, et **corriger une date mal saisie**. La
    première n'a pas besoin des champs de saisie, la seconde n'a pas besoin
    des statuts — et les montrer dans un tableau modifiable laisse croire
    qu'on peut les changer.

    Renvoie le tableau corrigé, ou ``None``.
    """
    vue = cs.vue_affichable(dossiers, aujourdhui, tri, avance)
    if vue.empty:
        return None

    if vue_choisie == cs.VUE_LECTURE:
        st.dataframe(cs.pour_affichage(vue[cs.COLONNES_LECTURE]),
                     use_container_width=True, hide_index=True,
                     column_config=_colonnes_vue())
        st.caption(
            f"{len(vue)} dossier(s). Passez en **✏️ Correction** pour "
            "modifier une date, ajouter ou supprimer un dossier — et pour "
            "voir le détail des dates d'envoi et de réception.")
        return None

    # La clé porte la génération ET l'ordre affiché : l'éditeur repère ses
    # corrections par POSITION de ligne, et les rejouer sur un tableau
    # reclassé recopierait une date sur le mauvais patient.
    # La comparaison « a-t-on corrigé quelque chose ? » se fait sur le
    # tableau TEL QU'AFFICHÉ. Comparer du texte à des valeurs typées
    # signalerait une correction à chaque affichage, et l'écran bouclerait.
    affiche = cs.pour_affichage(vue[cs.COLONNES_CORRECTION])
    edite = st.data_editor(
        affiche, hide_index=True,
        use_container_width=True, num_rows="dynamic",
        key=f"cs_editeur_{st.session_state.get('cs_generation', 0)}"
            f"_{cs.TRIS.index(tri)}",
        disabled=["Code CIP"], column_config=_colonnes_vue())
    st.caption("Corrigez une date ou un nombre de boîtes directement dans le "
               "tableau, **ajoutez un dossier** avec le « + » de la dernière "
               "ligne, ou supprimez-en un (sélection puis touche Suppr). "
               "Tout est enregistré automatiquement.")

    colonnes = [c for c in _COLONNES_EDITABLES if c in edite.columns]
    if len(edite) == len(affiche) and edite[colonnes].equals(
            affiche[colonnes]):
        return None
    return cs.normaliser_tableau_edite(edite)


def _enregistrer_corrections(corrige: pd.DataFrame) -> None:
    """Le tableau remplace tout : refuser plutôt qu'écraser un voisin."""
    attendu = st.session_state.get("cs_empreinte")
    conflit = []

    def mouvement(courant):
        if cs.empreinte_fichier(DOSSIERS_PATH) != attendu:
            conflit.append(True)
            return None
        return corrige

    if _appliquer(mouvement) is None or not conflit:
        return
    st.session_state["cs_message"] = (
        "avertissement",
        "Un autre poste a modifié les dossiers pendant votre correction : "
        "elle n'a pas été enregistrée, pour ne pas effacer son travail. Le "
        "tableau est à jour — refaites la correction.")


def _rapprochement(dossiers: pd.DataFrame) -> None:
    """Ce que les dossiers annoncent, face aux boîtes réellement scannées."""
    rapprochement = cs.rapprochement_stock(dossiers,
                                           _inventaire_stock_ferme())
    if rapprochement.empty:
        return
    ecarts = cs.ecarts_a_verifier(rapprochement)
    titre = ("✅ Dossiers et stock interne d'accord" if ecarts.empty else
             f"⚠️ {len(ecarts)} écart(s) entre les dossiers et le stock interne")
    with st.expander(titre, expanded=not ecarts.empty):
        st.caption(
            "Le code CIP identifie un produit, pas une boîte : si deux "
            "patients suivent le même médicament, rien ne dit laquelle des "
            "boîtes est pour qui. On compare donc des totaux par produit — "
            "cela suffit à repérer une boîte reçue mais jamais scannée, ou "
            "scannée sans dossier.")
        st.dataframe(rapprochement if ecarts.empty else ecarts,
                     use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Écran
# ---------------------------------------------------------------------------

def _bandeau(resume: dict, tuile) -> None:
    st.markdown('<div class="kpi-row">' + "".join([
        tuile("Dossiers suivis", resume["dossiers"], "accent",
              sous=f'{resume["patients"]} patient(s)'),
        tuile("💰 À facturer", resume["a_facturer"],
              "accent" if resume["a_facturer"] else "",
              sous="les 22 jours sont écoulés"),
        tuile("📦 À commander", resume["a_commander"],
              "critical" if resume["a_commander"] else "",
              sous="sinon le patient attendra"),
        tuile("⏰ En retard", resume["en_retard"],
              "critical" if resume["en_retard"] else "",
              sous="à relancer"),
    ]) + "</div>", unsafe_allow_html=True)


def _barre_laterale(dossiers: pd.DataFrame, aujourdhui: date) -> tuple:
    with st.sidebar:
        st.markdown("### 💠 Commandes spéciales")
        st.caption("Produits chers importés du continent : deux horloges par "
                   "patient — l'import, et les "
                   f"{cs.DELAI_FACTURATION_J} jours de la caisse.")
        aujourdhui = st.date_input("Date du jour", value=aujourdhui,
                                   format="DD/MM/YYYY", key="cs_date")
        avance = st.number_input(
            "Boîtes d'avance visées", min_value=0, max_value=10,
            value=cs.AVANCE_CIBLE_DEFAUT, step=1, key="cs_avance",
            help="L'avance qui absorbe le délai d'import. En dessous, le "
                 "dossier passe dans « à commander ».")
        st.divider()
        st.markdown("#### Mémoire")
        st.caption(f"{len(dossiers)} dossier(s)\n\n`{DOSSIERS_PATH.name}`")
        with st.expander("🗑️ Vider les dossiers"):
            st.warning("Supprime tous les dossiers de commandes spéciales.")
            if st.button("Confirmer la remise à zéro",
                         use_container_width=True, key="cs_vider"):
                if _appliquer(lambda _: cs.dossier_vide()) is not None:
                    st.session_state["cs_message"] = (
                        "ok", "Dossiers remis à zéro.")
                st.rerun()
    return aujourdhui, int(avance)


def _zone_impression(dossiers: pd.DataFrame, aujourdhui: date,
                     tri: str) -> None:
    colonne_csv, colonne_pdf = st.columns(2)
    colonne_csv.download_button(
        "📄 Exporter en CSV", cs.exporter_csv(dossiers, aujourdhui, tri),
        file_name=f"commandes-speciales-{aujourdhui:%Y-%m-%d}.csv",
        mime=_MIME_CSV, use_container_width=True)
    try:
        pdf = cs.exporter_pdf(dossiers, aujourdhui=aujourdhui, tri=tri)
    except ValueError as erreur:
        colonne_pdf.button("🖨️ Imprimer (PDF)", disabled=True,
                           use_container_width=True, help=str(erreur))
        return
    colonne_pdf.download_button(
        "🖨️ Imprimer (PDF)", pdf,
        file_name=f"commandes-speciales-{aujourdhui:%Y-%m-%d}.pdf",
        mime=_MIME_PDF, use_container_width=True, type="primary")


def rendre(etape, tuile_kpi) -> None:
    """Affiche l'écran complet du module.

    ``etape`` et ``tuile_kpi`` sont les fonctions d'habillage de ``app.py``,
    passées en paramètre pour garder ce module indépendant de l'application.
    """
    dossiers = _etat()
    aujourdhui, avance = _barre_laterale(dossiers, date.today())

    message = st.session_state.pop("cs_message", None)
    if message:
        niveau, texte = message
        (st.success if niveau == "ok" else st.warning)(texte)

    _bandeau(cs.resume(dossiers, aujourdhui, avance), tuile_kpi)

    # --- Ajouter, tout en haut ---------------------------------------------
    # L'ajout était en troisième position, sous deux sections : on ne le
    # voyait pas sans faire défiler, et l'écran donnait l'impression de ne
    # gérer qu'un seul patient — celui de la liste déroulante des gestes.
    # C'est pourtant l'action de départ : un module vide n'a que celle-là.
    _panneau_ajout(dossiers)
    _import_fichier(dossiers)

    # --- Le matin ----------------------------------------------------------
    etape("1", "Ce qu'il y a à faire aujourd'hui",
          "Trois questions, trois listes — le reste peut attendre.")
    _listes_du_matin(dossiers, aujourdhui, avance)

    st.divider()
    etape("2", "Enregistrez un geste",
          "Facturer, recevoir, commander sur un dossier DÉJÀ ouvert : la "
          "date et les boîtes bougent ensemble.")
    _actions_rapides(dossiers, aujourdhui)

    # --- La référence ------------------------------------------------------
    st.divider()
    etape("3", "Tous les dossiers", "La référence, corrigeable à la main.")
    colonne_vue, colonne_recherche, colonne_tri = st.columns([2, 3, 2])
    vue_choisie = colonne_vue.selectbox("👓 Afficher", cs.VUES, key="cs_vue")
    recherche = colonne_recherche.text_input(
        "🔍 Rechercher", key="cs_recherche",
        placeholder="Nom du patient, médicament ou code CIP")
    tri = colonne_tri.selectbox("↕️ Classer par", cs.TRIS, key="cs_tri")

    if dossiers.empty:
        st.info("Aucun dossier — ouvrez-en un tout en haut de l'écran.")
    elif recherche.strip():
        # Le tableau ne devient modifiable que sur la liste ENTIÈRE :
        # corriger une vue filtrée réécrirait les dossiers en perdant les
        # lignes masquées.
        vue = cs.vue_affichable(dossiers, aujourdhui, tri, avance)
        motif = recherche.strip().lower()
        garde = vue.apply(
            lambda l: motif in f"{l['Patient']} {l['Nom du produit']} "
                               f"{l['Code CIP']}".lower(), axis=1)
        filtree = vue[garde]
        colonnes = (cs.COLONNES_LECTURE if vue_choisie == cs.VUE_LECTURE
                    else cs.COLONNES_CORRECTION)
        st.dataframe(cs.pour_affichage(filtree[colonnes]),
                     use_container_width=True, hide_index=True,
                     column_config=_colonnes_vue())
        st.caption(f"{len(filtree)} dossier(s) trouvé(s). Videz la "
                   "recherche pour corriger le tableau.")
    else:
        corrige = _tableau(dossiers, aujourdhui, tri, avance, vue_choisie)
        if corrige is not None:
            _enregistrer_corrections(corrige)
            st.rerun()

    _rapprochement(dossiers)

    st.divider()
    etape("4", "Imprimez ou exportez",
          "La liste du matin, à poser à côté du téléphone.")
    _zone_impression(dossiers, aujourdhui, tri)
