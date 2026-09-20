# -*- coding: utf-8 -*-
"""Interface du Module 5 — Location, achat, et ententes préalables CAFAT.

Écran autonome, comme les commandes spéciales : il ne dépend d'aucun
fichier déposé, et toute la logique vit dans ``location.py``. Ce fichier
ne fait que l'habillage Streamlit.

Ergonomie visée : **quatre questions, quatre sous-onglets**, dans l'ordre
où elles se posent au comptoir —

1. l'entente préalable est-elle faite, et jusqu'à quand ;
2. qu'est-ce qui reste à facturer, et depuis combien de mois ;
3. quels dossiers faut-il renouveler avant qu'ils n'expirent ;
4. où en sont les achats — ni mensuels ni renouvelables, ils se
   perdraient dans des listes faites pour des échéances qui reviennent.

HARMONISATION PAR PATIENT. Louer et acheter partagent ici tout ce qui peut
l'être : le même dossier, les mêmes statuts, les mêmes couleurs, les mêmes
gestes. La colonne « Mode » figure dans chaque liste, et un
récapitulatif **par patient** ouvre le tableau de référence — parce que le
patient au téléphone ne demande pas « où en est ma location de lit », il
demande où il en est.

Le tableau complet vient après : c'est la référence, pas le geste du
matin. Aucune règle CAFAT n'est inventée ici — la durée de validité est
**saisie par dossier**, la caisse l'accordant au cas par cas.
"""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd
import streamlit as st

import location as loc
import ui_commun

_journal = logging.getLogger("pharmacie.location.ui")

DOSSIERS_PATH = ui_commun.dossier_donnees() / "location.csv"

_MIME_CSV = "text/csv"

#: Colonnes que l'on peut corriger directement dans le tableau. Les statuts,
#: les échéances et les mois dus n'en font pas partie : ils se déduisent.
_COLONNES_EDITABLES = ("Patient", "Matériel", "Mode", "Début de location",
                       "Entente préalable", "Validité (mois)",
                       "Dernière facturation", "Notes")

MESSAGE_VERROU = (
    "Un autre poste enregistre au même instant — rien n'a été modifié. "
    "Refaites le geste dans un instant.")
MESSAGE_FICHIER_BLOQUE = (
    "Impossible d'enregistrer : le fichier `{fichier}` est ouvert dans un "
    "autre programme (Excel, le plus souvent). Fermez-le, puis refaites le "
    "geste — rien n'a été perdu.")


def _colonnes_vue() -> dict:
    """Mise en forme du tableau, partagée par toutes ses apparitions.

    Tout est centré, comme dans les autres modules : sur des colonnes
    larges, un nombre collé au bord droit finit loin de son en-tête.

    Les dates et les nombres pouvant être vides sont déclarés en TEXTE :
    Streamlit affiche « None » pour une date absente comme pour un entier
    absent, et seule une chaîne vide s'affiche vide. Les valeurs sont mises
    en forme par ``loc.pour_affichage``, et ``parser_date`` sait relire
    « 24/08/2026 » si on les corrige à la main.
    """
    jour = dict(width="small", alignment="center")
    return {
        "Entente": st.column_config.TextColumn(
            "Entente", width="small", alignment="center"),
        "Facturation": st.column_config.TextColumn(
            "Facturation", width="small", alignment="center"),
        "Patient": st.column_config.TextColumn("Patient", alignment="center"),
        "Matériel": st.column_config.TextColumn(
            "Matériel", alignment="center"),
        # Une liste fermée, et non du texte libre : « loc. », « LOCATION »
        # et « louée » sortiraient le dossier de son sous-onglet sans que
        # rien ne le signale.
        # Sans `alignment` : `SelectboxColumn` ne l'accepte pas, et le
        # passer faisait tomber l'écran entier au premier affichage.
        "Mode": st.column_config.SelectboxColumn(
            "Mode", options=list(loc.MODES), width="small", required=True),
        "Locations": st.column_config.NumberColumn(
            "🛏️ Loué", width="small", alignment="center"),
        "Achats": st.column_config.NumberColumn(
            "🛒 Acheté", width="small", alignment="center"),
        "À renouveler": st.column_config.NumberColumn(
            "🔁 À renouveler", width="small", alignment="center"),
        "À facturer": st.column_config.NumberColumn(
            "💰 À facturer", width="small", alignment="center"),
        "Début de location": st.column_config.TextColumn("Loué depuis", **jour),
        "Entente préalable": st.column_config.TextColumn(
            "Entente faite le", **jour),
        "Validité (mois)": st.column_config.TextColumn(
            "Validité (mois)", width="small", alignment="center"),
        "Échéance": st.column_config.TextColumn("Expire le", **jour),
        "Jours avant échéance": st.column_config.TextColumn(
            "J avant échéance", width="small", alignment="center"),
        "Dernière facturation": st.column_config.TextColumn(
            "Dern. facturation", **jour),
        "Prochaine facturation": st.column_config.TextColumn(
            "Prochaine fact.", **jour),
        "Mois dus": st.column_config.TextColumn(
            "Mois dus", width="small", alignment="center"),
        "Notes": st.column_config.TextColumn("Notes", alignment="center"),
    }


# ---------------------------------------------------------------------------
# Mémoire de session
# ---------------------------------------------------------------------------

def _etat() -> pd.DataFrame:
    """Les dossiers, relus dès qu'un autre poste écrit.

    Même précaution que partout ailleurs : sur un serveur partagé, garder
    la photo prise à l'ouverture ferait réenregistrer plus tard une version
    qui ignore la facturation saisie au comptoir d'à côté.
    """
    empreinte = loc.empreinte_fichier(DOSSIERS_PATH)
    if ("lo_dossiers" not in st.session_state
            or st.session_state.get("lo_empreinte") != empreinte):
        premiere = "lo_dossiers" not in st.session_state
        st.session_state["lo_dossiers"] = loc.charger(DOSSIERS_PATH)
        st.session_state["lo_empreinte"] = empreinte
        if not premiere:
            st.session_state["lo_generation"] = (
                st.session_state.get("lo_generation", 0) + 1)
        _journal.info("Location — %d dossier(s) relus depuis %s",
                      len(st.session_state["lo_dossiers"]), DOSSIERS_PATH)
    return st.session_state["lo_dossiers"]


def _memoriser(dossiers, empreinte=None) -> None:
    st.session_state["lo_dossiers"] = dossiers
    st.session_state["lo_empreinte"] = (
        empreinte if empreinte is not None
        else loc.empreinte_fichier(DOSSIERS_PATH))
    st.session_state["lo_generation"] = (
        st.session_state.get("lo_generation", 0) + 1)


def _appliquer(mouvement):
    """Applique un mouvement aux dossiers **du disque**, sous verrou.

    Deux comptoirs peuvent enregistrer une facturation au même instant :
    sans cela, la seconde effacerait la première et l'échéance de l'entente
    repartirait de la mauvaise date — donc un refus de la caisse.
    """
    try:
        ecriture = loc.appliquer_aux_dossiers(DOSSIERS_PATH, mouvement)
    except loc.VerrouIndisponible:
        st.session_state["lo_message"] = ("avertissement", MESSAGE_VERROU)
        return None
    except OSError as erreur:
        _journal.error("Dossiers de location non enregistrés : %s", erreur)
        st.session_state["lo_message"] = (
            "avertissement",
            MESSAGE_FICHIER_BLOQUE.format(fichier=DOSSIERS_PATH.name))
        return None
    _memoriser(ecriture.tableau, ecriture.empreinte)
    return ecriture.tableau


def _libelles(vue: pd.DataFrame) -> list:
    """« Patient — matériel (mode) » : ce qui identifie un dossier.

    Le mode fait partie du libellé parce qu'il fait partie de l'identité :
    un fauteuil loué puis acheté donne deux dossiers, et deux lignes
    identiques dans la liste ne laisseraient aucun moyen de viser la bonne.
    """
    return [f"{ligne['Patient']} — {ligne['Matériel']} ({ligne['Mode']})"
            for _, ligne in vue.iterrows()]


def _choisir_un_dossier(vue: pd.DataFrame, cle: str):
    """Conserve le dossier choisi même si les échéances le reclassent."""
    libelles = _libelles(vue)
    if not libelles:
        return None
    identites = [_identite_dossier(ligne) for _, ligne in vue.iterrows()]
    positions = {identite: i for i, identite in enumerate(identites)}
    if cle in st.session_state and st.session_state[cle] not in positions:
        # Le dossier a disparu ou son identité a changé sur un autre poste.
        # Ne pas proposer silencieusement un autre patient à sa place.
        st.session_state[cle] = None
    choix = st.selectbox("Dossier", identites,
                         format_func=lambda identite: libelles[positions[identite]],
                         key=cle, label_visibility="collapsed",
                         placeholder="Choisissez un dossier")
    return None if choix is None else vue.iloc[positions[choix]]


def _identite_dossier(ligne) -> tuple:
    """La même identité patient / matériel / mode que le moteur."""
    return (loc.cle_patient(ligne["Patient"]),
            loc.cle_patient(ligne["Matériel"]),
            loc.parser_mode(ligne["Mode"]))


# ---------------------------------------------------------------------------
# Ouvrir un dossier
# ---------------------------------------------------------------------------

def _panneau_ajout(dossiers: pd.DataFrame) -> None:
    """L'ouverture d'un dossier, en haut de l'écran et prête à enchaîner.

    Ouvert d'office tant qu'aucun dossier n'existe — un module vide n'a que
    cette action-là — et il **reste ouvert** après un ajout, pour qu'on
    enchaîne les saisies sans le rouvrir à chaque patient.
    """
    vide = dossiers is None or dossiers.empty
    ouvert = vide or st.session_state.get("lo_ajout_ouvert", False)
    nombre = 0 if vide else len(dossiers)
    titre = ("➕ Ouvrez un premier dossier de location" if vide else
             f"➕ Ouvrir un dossier — {nombre} location"
             f"{'s' if nombre > 1 else ''} suivie"
             f"{'s' if nombre > 1 else ''}")
    with st.expander(titre, expanded=ouvert):
        st.caption("Un dossier par patient, par matériel ET par mode : le "
                   "même patient peut louer un lit et acheter un "
                   "déambulateur, chacun avec sa propre entente préalable. "
                   "Un fauteuil d'abord loué puis acheté fait lui aussi "
                   "deux dossiers — deux ententes, deux facturations.")
        _formulaire_nouveau()


def _formulaire_nouveau() -> None:
    """Ouvrir un dossier : un patient, un matériel, et les dates connues."""
    with st.form("lo_nouveau", clear_on_submit=True):
        c1, c2, c0 = st.columns([3, 3, 2])
        patient = c1.text_input("Patient", key="lo_nouveau_patient",
                                placeholder="Nom du patient")
        materiel = c2.text_input("Matériel", key="lo_nouveau_materiel",
                                 placeholder="Lit médicalisé, VNI, "
                                             "concentrateur…")
        mode = c0.selectbox(
            "Mode", loc.MODES, key="lo_nouveau_mode",
            help="Louer ou acheter. Les deux passent par une entente "
                 "préalable ; seule la suite diffère — la location se "
                 "facture tous les mois et se renouvelle, l'achat se "
                 "facture une fois et se termine.")
        c3, c4, c5, c6 = st.columns(4)
        debut = c3.text_input("Début de location", key="lo_nouveau_debut",
                              placeholder="jj/mm/aaaa")
        entente = c4.text_input("Entente préalable faite le",
                                key="lo_nouveau_entente",
                                placeholder="jj/mm/aaaa")
        validite = c5.number_input(
            "Validité (mois)", min_value=1, max_value=60,
            value=loc.VALIDITE_DEFAUT_MOIS, step=1, key="lo_nouveau_validite",
            help="La durée accordée par la caisse pour CE dossier. Elle "
                 "varie selon le matériel — d'où la saisie au cas par cas.")
        facturation = c6.text_input("Dernière facturation",
                                    key="lo_nouveau_facturation",
                                    placeholder="jj/mm/aaaa")
        notes = st.text_input("Notes", key="lo_nouveau_notes",
                              placeholder="Facultatif — prescripteur, "
                                          "n° de dossier CAFAT…")
        valide = st.form_submit_button("➕ Ouvrir le dossier", type="primary",
                                       use_container_width=True)

    if not valide:
        return
    if not patient.strip() or not materiel.strip():
        st.error("**Patient et matériel sont indispensables.** C'est le "
                 "couple qui identifie un dossier — et c'est lui qui porte "
                 "l'échéance de l'entente préalable.")
        return

    resultat = _appliquer(lambda courant: loc.ajouter_dossier(
        courant, patient, materiel, debut=debut, entente=entente,
        validite_mois=int(validite), derniere_facturation=facturation,
        notes=notes, mode=mode))
    if resultat is None:
        return
    st.session_state["lo_ajout_ouvert"] = True
    st.session_state["lo_message"] = (
        "ok", f"📁 {patient} — {materiel} ({mode}) : dossier enregistré. "
              f"{len(resultat)} dossier(s) suivi(s) — le formulaire est "
              "vide, vous pouvez enchaîner avec le patient suivant.")
    st.rerun()


# ---------------------------------------------------------------------------
# Sous-onglet 1 — Ententes préalables
# ---------------------------------------------------------------------------

def _onglet_ententes(dossiers: pd.DataFrame, vue: pd.DataFrame,
                     aujourdhui: date) -> None:
    """Où en est chaque entente, et le geste « l'accord est arrivé ».

    La date affichée est celle de l'ACCORD, pas celle de la demande : c'est
    d'elle que court la validité, et c'est elle que la caisse contrôlera.
    """
    st.caption("La date affichée est celle où la caisse a **accordé** "
               "l'entente : c'est de là que court la validité.")
    if vue.empty:
        st.info("Aucun dossier de location — ouvrez-en un tout en haut de "
                "l'écran.")
        return

    st.dataframe(loc.pour_affichage(vue[loc.COLONNES_ENTENTES]),
                 use_container_width=True, hide_index=True,
                 column_config=_colonnes_vue())

    sans = vue[vue["Entente"] == loc.STATUT_SANS_ENTENTE]
    if not sans.empty:
        st.warning(f"**{len(sans)} dossier(s) sans entente préalable.** "
                   "Tant que l'accord n'est pas saisi, la location n'est "
                   "prise en charge par personne.")

    with st.container(border=True):
        st.markdown("**✅ Enregistrer une entente accordée**")
        ligne = _choisir_un_dossier(vue, "lo_entente_dossier")
        if ligne is None:
            return
        duree = int(ligne["Validité (mois)"] or loc.VALIDITE_DEFAUT_MOIS)
        reference = (_identite_dossier(ligne), duree)
        if st.session_state.get("lo_entente_reference") != reference:
            # Une clé de widget fixe garde sinon la durée du patient précédent.
            st.session_state["lo_entente_validite"] = duree
            st.session_state["lo_entente_date"] = aujourdhui
            st.session_state["lo_entente_reference"] = reference
        c1, c2 = st.columns([3, 2])
        accordee = c1.date_input("Accordée le", value=aujourdhui,
                                 format="DD/MM/YYYY", key="lo_entente_date")
        validite = c2.number_input(
            "Validité (mois)", min_value=1, max_value=60,
            value=duree,
            step=1, key="lo_entente_validite")
        if st.button("✅ Entente préalable faite", type="primary",
                     use_container_width=True, key="lo_entente_valider"):
            patient, materiel = ligne["Patient"], ligne["Matériel"]
            mode = ligne["Mode"]
            if _appliquer(lambda courant: loc.enregistrer_entente(
                    courant, patient, materiel, accordee,
                    int(validite), mode)) is not None:
                fin = loc.ajouter_mois(accordee, int(validite))
                st.session_state["lo_message"] = (
                    "ok", f"✅ {patient} — {materiel} : entente accordée le "
                          f"{accordee:%d/%m/%Y}, valable jusqu'au "
                          f"{fin:%d/%m/%Y}.")
            st.rerun()


# ---------------------------------------------------------------------------
# Sous-onglet 2 — Facturations
# ---------------------------------------------------------------------------

def _onglet_facturations(dossiers: pd.DataFrame, vue: pd.DataFrame,
                         aujourdhui: date) -> None:
    """Ce qu'il reste à facturer, et depuis combien de mois.

    Le nombre de mois dus est affiché sans détour : une location oubliée
    depuis janvier, ce sont trois mois à facturer en avril, pas un. Afficher
    « à facturer » tout court ferait encaisser un mois et croire le dossier
    à jour.
    """
    st.caption(f"La location se facture tous les "
               f"{loc.PERIODE_FACTURATION_MOIS} mois. Les dossiers jamais "
               "facturés sont comptés : c'est le cas le plus facile à "
               "oublier, puisqu'aucune date ne vient le rappeler.")
    if vue.empty:
        st.info("Aucun dossier de location — ouvrez-en un tout en haut de "
                "l'écran.")
        return

    dues = loc.a_facturer(dossiers, aujourdhui)
    if dues.empty:
        st.success("💰 Rien à facturer aujourd'hui : toutes les locations "
                   "sont à jour.")
    else:
        retard = int(pd.to_numeric(dues["Mois dus"],
                                   errors="coerce").fillna(0).sum())
        st.markdown(f"**💰 {len(dues)} location(s) à facturer** — "
                    f"{retard} mois dus au total.")
        st.dataframe(loc.pour_affichage(dues[loc.COLONNES_FACTURATION]),
                     use_container_width=True, hide_index=True,
                     column_config=_colonnes_vue())

    with st.expander("Toutes les locations et leur facturation"):
        st.dataframe(loc.pour_affichage(vue[loc.COLONNES_FACTURATION]),
                     use_container_width=True, hide_index=True,
                     column_config=_colonnes_vue())

    with st.container(border=True):
        st.markdown("**💰 Enregistrer une facturation**")
        ligne = _choisir_un_dossier(vue, "lo_facture_dossier")
        if ligne is None:
            return
        identite = _identite_dossier(ligne)
        if st.session_state.get("lo_facture_reference") != identite:
            st.session_state["lo_facture_date"] = aujourdhui
            st.session_state["lo_facture_reference"] = identite
        jour = st.date_input("Facturé le", value=aujourdhui,
                             format="DD/MM/YYYY", key="lo_facture_date")
        if st.button("💰 Facturé", type="primary",
                     use_container_width=True, key="lo_facture_valider"):
            patient, materiel = ligne["Patient"], ligne["Matériel"]
            mode = ligne["Mode"]
            if _appliquer(lambda courant: loc.enregistrer_facturation(
                    courant, patient, materiel, jour, mode)) is not None:
                suivante = loc.prochaine_facturation(jour, mode=mode)
                # L'achat n'a pas de suite : le dire, plutôt que de laisser
                # la phrase s'arrêter sur un blanc.
                suite = (f" Prochaine facturation le {suivante:%d/%m/%Y}."
                         if suivante is not None
                         else " Achat réglé : il ne reviendra plus dans les "
                              "facturations.")
                st.session_state["lo_message"] = (
                    "ok", f"💰 {patient} — {materiel} ({mode}) : facturé le "
                          f"{jour:%d/%m/%Y}.{suite}")
            st.rerun()


# ---------------------------------------------------------------------------
# Sous-onglet 3 — À renouveler
# ---------------------------------------------------------------------------

def _onglet_renouvellement(dossiers: pd.DataFrame, aujourdhui: date,
                           alerte_j: int) -> None:
    """Les ententes qui expirent bientôt — ou qui ont déjà expiré.

    Les expirées passent en tête : elles ne sont plus prises en charge, et
    chaque jour compte double. Le délai d'alerte se règle dans la barre
    latérale, parce qu'une demande de renouvellement met un temps variable
    à revenir de la caisse.
    """
    st.caption(f"Alerte {alerte_j} jours avant l'échéance : le temps de "
               "revoir le médecin, d'envoyer la demande, et d'attendre la "
               "réponse de la caisse.")
    a_traiter = loc.a_renouveler(dossiers, aujourdhui, alerte_j)
    if a_traiter.empty:
        st.success("🔁 Aucun dossier à renouveler : toutes les ententes "
                   f"tiennent au-delà de {alerte_j} jours.")
        return

    expirees = a_traiter[a_traiter["Entente"] == loc.STATUT_EXPIREE]
    if not expirees.empty:
        st.error(f"⛔ **{len(expirees)} entente(s) déjà expirée(s).** Ces "
                 "locations ne sont plus prises en charge : la demande de "
                 "renouvellement est à faire aujourd'hui.")
    st.dataframe(loc.pour_affichage(a_traiter[loc.COLONNES_RENOUVELLEMENT]),
                 use_container_width=True, hide_index=True,
                 column_config=_colonnes_vue())
    st.caption("Quand l'accord revient de la caisse, enregistrez-le dans le "
               "sous-onglet « ✅ Ententes préalables » : l'échéance repart "
               "de la date d'accord.")


# ---------------------------------------------------------------------------
# Sous-onglet 4 — Achats
# ---------------------------------------------------------------------------

def _onglet_achats(vue: pd.DataFrame) -> None:
    """Ce qui est acheté plutôt que loué : une entente, une facturation.

    Sa propre liste parce qu'il ne se lit pas comme une location : ni
    « prochaine facturation » ni « mois dus » — montrer deux colonnes vides
    ferait douter d'une panne — et une fois réglé, il ne revient plus.
    """
    achats = loc.du_mode(vue, loc.MODE_ACHAT)
    st.caption("L'achat passe par la même entente préalable qu'une location, "
               "mais il se facture **une seule fois** : une fois réglé, il "
               "ne revient ni dans les facturations ni dans les "
               "renouvellements.")
    if achats.empty:
        st.info("Aucun achat enregistré. Ouvrez un dossier tout en haut de "
                "l'écran en choisissant le mode « 🛒 Achat ».")
        return

    a_regler = achats[achats["Facturation"].isin(loc.STATUTS_A_FACTURER)]
    if a_regler.empty:
        st.success(f"✅ Les {len(achats)} achat(s) sont réglés.")
    else:
        st.markdown(f"**💰 {len(a_regler)} achat(s) à facturer** — livrés, "
                    "jamais réglés. Aucune date ne viendra le rappeler.")
        st.dataframe(loc.pour_affichage(a_regler[loc.COLONNES_ACHATS]),
                     use_container_width=True, hide_index=True,
                     column_config=_colonnes_vue())

    st.markdown("**Tous les achats**")
    st.dataframe(loc.pour_affichage(achats[loc.COLONNES_ACHATS]),
                 use_container_width=True, hide_index=True,
                 column_config=_colonnes_vue())
    st.caption("Enregistrez le règlement dans le sous-onglet "
               "« 💰 Facturations » : c'est le même geste que pour une "
               "location, et c'est le mode du dossier qui décide de la "
               "suite.")


# ---------------------------------------------------------------------------
# Le patient d'abord
# ---------------------------------------------------------------------------

def _recapitulatif_par_patient(dossiers: pd.DataFrame, aujourdhui: date,
                               alerte: int) -> None:
    """Une ligne par patient, locations ET achats confondus.

    Le patient au téléphone ne demande pas « où en est ma location de
    lit » : il demande où il en est. Éclaté en deux listes, il fallait le
    chercher deux fois et recoller les réponses de tête — et c'est là qu'on
    oublie le second appareil.
    """
    recap = loc.par_patient(dossiers, aujourdhui, alerte)
    if recap.empty:
        return
    with st.expander(f"👤 Vue par patient — {len(recap)} personne(s) suivie(s)",
                     expanded=True):
        st.caption("Ceux dont une entente est tombée passent en tête. Un "
                   "patient = une ligne, qu'il loue, qu'il achète, ou les "
                   "deux.")
        st.dataframe(recap, use_container_width=True, hide_index=True,
                     column_config=_colonnes_vue())


# ---------------------------------------------------------------------------
# Tableau complet
# ---------------------------------------------------------------------------

def _tableau(vue: pd.DataFrame):
    """La référence, corrigeable à la main. Renvoie le corrigé, ou ``None``.

    La clé porte la génération ET l'ordre affiché : l'éditeur repère ses
    corrections par POSITION de ligne, et les rejouer sur un tableau
    reclassé recopierait une date sur le mauvais patient.
    """
    if vue.empty:
        return None
    affiche = loc.pour_affichage(vue[loc.COLONNES_CORRECTION])
    edite = st.data_editor(
        affiche, hide_index=True, use_container_width=True,
        num_rows="dynamic", column_config=_colonnes_vue(),
        key=f"lo_editeur_{st.session_state.get('lo_generation', 0)}")
    st.caption("Corrigez une date ou une durée directement dans le tableau, "
               "**ajoutez un dossier** avec le « + » de la dernière ligne, "
               "ou supprimez-en un (sélection puis touche Suppr) — la "
               "location est terminée, le matériel est revenu. Tout est "
               "enregistré automatiquement.")

    colonnes = [c for c in _COLONNES_EDITABLES if c in edite.columns]
    # La comparaison se fait sur le tableau TEL QU'AFFICHÉ : comparer du
    # texte à des valeurs typées signalerait une correction à chaque
    # affichage, et l'écran bouclerait.
    if len(edite) == len(affiche) and edite[colonnes].equals(affiche[colonnes]):
        return None
    return loc.normaliser_tableau_edite(edite)


def _enregistrer_corrections(corrige: pd.DataFrame) -> None:
    """Le tableau remplace tout : refuser plutôt qu'écraser un voisin."""
    attendu = st.session_state.get("lo_empreinte")
    conflit = []

    def mouvement(courant):
        if loc.empreinte_fichier(DOSSIERS_PATH) != attendu:
            conflit.append(True)
            return None
        return corrige

    if _appliquer(mouvement) is None or not conflit:
        return
    st.session_state["lo_message"] = (
        "avertissement",
        "Un autre poste a modifié les dossiers pendant votre correction : "
        "elle n'a pas été enregistrée, pour ne pas effacer son travail. Le "
        "tableau est à jour — refaites la correction.")


# ---------------------------------------------------------------------------
# Écran
# ---------------------------------------------------------------------------

def _bandeau(resume: dict, tuile,
             alerte_j: int = loc.ALERTE_RENOUVELLEMENT_J) -> None:
    st.markdown('<div class="kpi-row">' + "".join([
        tuile("Dossiers suivis", resume["dossiers"], "accent",
              sous=f'{resume["locations"]} loué(s) · '
                   f'{resume["achats"]} acheté(s)'),
        tuile("🔁 À renouveler", resume["a_renouveler"],
              "accent" if resume["a_renouveler"] else "",
              sous=f'échéance sous {alerte_j} jours'),
        tuile("⛔ Ententes expirées", resume["expirees"],
              "critical" if resume["expirees"] else "",
              sous="plus prises en charge"),
        tuile("💰 À facturer", resume["a_facturer"],
              "critical" if resume["a_facturer"] else "",
              sous=f'{resume["mois_dus"]} mois dus'),
    ]) + "</div>", unsafe_allow_html=True)


def _barre_laterale(dossiers: pd.DataFrame, aujourdhui: date) -> tuple:
    with st.sidebar:
        st.markdown("### 🛏️ Location")
        st.caption("Matériel au patient et ententes préalables CAFAT : "
                   "deux horloges par dossier — la validité de l'entente, et "
                   "la facturation mensuelle.")
        aujourdhui = st.date_input("Date du jour", value=aujourdhui,
                                   format="DD/MM/YYYY", key="lo_date")
        alerte = st.number_input(
            "Alerte renouvellement (jours)", min_value=1, max_value=180,
            value=loc.ALERTE_RENOUVELLEMENT_J, step=5, key="lo_alerte",
            help="Combien de jours avant l'échéance un dossier passe dans "
                 "« à renouveler ». Le temps de revoir le médecin et "
                 "d'attendre la réponse de la caisse.")
        st.divider()
        st.markdown("#### Mémoire")
        st.caption(f"{len(dossiers)} dossier(s)\n\n`{DOSSIERS_PATH.name}`")
        with st.expander("🗑️ Vider les dossiers"):
            st.warning("Supprime tous les dossiers de location.")
            if st.button("Confirmer la remise à zéro",
                         use_container_width=True, key="lo_vider"):
                if _appliquer(lambda _: loc.dossier_vide()) is not None:
                    st.session_state["lo_message"] = (
                        "ok", "Dossiers de location remis à zéro.")
                st.rerun()
    return aujourdhui, int(alerte)


def rendre(etape, tuile_kpi) -> None:
    """Le parcours de travail réel ; les aides historiques restent testées."""
    from ui_locations_suivi import rendre as rendre_suivi
    rendre_suivi(DOSSIERS_PATH)
