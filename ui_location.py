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
_COLONNES_EDITABLES = ("Patient", "Matériel", "Mode", "Régime",
                       "Début de location", "Demande le", "Demandée par",
                       "Entente préalable", "Validité (mois)",
                       "Dernière facturation", "Caution (F)",
                       "Caution rendue le", "Commentaire entente", "Notes")

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
        # Le régime et la demande : une liste fermée pour l'un, du texte
        # pour l'autre. Le prénom est libre — c'est celui de l'équipe, pas
        # une liste à tenir à jour.
        "Régime": st.column_config.SelectboxColumn(
            "Régime", options=list(loc.REGIMES), width="medium",
            required=True),
        "Demande le": st.column_config.TextColumn("Demandé le", **jour),
        "Demandée par": st.column_config.TextColumn(
            "Par", width="small", alignment="center"),
        "Attente (j)": st.column_config.TextColumn(
            "Attente (j)", width="small", alignment="center"),
        "Remboursement": st.column_config.TextColumn(
            "Remboursement", alignment="center"),
        "Caution (F)": st.column_config.TextColumn(
            "Caution", width="small", alignment="center"),
        "Caution détenue (F)": st.column_config.TextColumn(
            "Caution détenue", width="small", alignment="center"),
        "Caution rendue le": st.column_config.TextColumn(
            "Caution rendue", **jour),
        "Commentaire entente": st.column_config.TextColumn(
            "Commentaire entente", width="large", alignment="center"),
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
    """Liste déroulante des dossiers ; renvoie la ligne choisie."""
    libelles = _libelles(vue)
    if not libelles:
        return None
    rang = st.selectbox("Dossier", range(len(libelles)),
                        format_func=lambda i: libelles[i], key=cle,
                        label_visibility="collapsed")
    return vue.iloc[rang]


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
                   "deux dossiers — deux ententes, deux facturations.\n\n"
                   "**Tensiomètre** ou **aérosol** : tapez simplement le "
                   "nom, le régime hors caisse et la caution se remplissent "
                   "seuls.")
        _formulaire_nouveau(dossiers)


def _formulaire_nouveau(dossiers: pd.DataFrame) -> None:
    """Ouvrir un dossier : un patient, un matériel, et les dates connues.

    Le formulaire ne demande QUE ce qui n'est pas déductible. Le régime et
    la caution se proposent d'après le nom du matériel — taper
    « Tensiomètre » suffit pour partir hors caisse avec ses 3 000 F. Les
    ressaisir à chaque appareil, c'est la ligne qu'on finit par oublier.
    """
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
        demande = c4.text_input(
            "Demande d'entente envoyée le", key="lo_nouveau_demande",
            placeholder="jj/mm/aaaa",
            help="La date d'ENVOI à la caisse. Laissez vide si la demande "
                 "n'est pas encore partie — ou si le matériel n'en demande "
                 "pas (tensiomètre, aérosol).")
        par = c5.selectbox(
            "Demande faite par", _prenoms_connus(dossiers), index=None,
            accept_new_options=True, key="lo_nouveau_par",
            placeholder="Prénom",
            help="Pour la traçabilité : c'est à cette personne qu'on "
                 "demandera ce qui a été envoyé, si la caisse tarde.")
        validite = c6.number_input(
            "Validité (mois)", min_value=1, max_value=60,
            value=loc.VALIDITE_DEFAUT_MOIS, step=1, key="lo_nouveau_validite",
            help="La durée accordée par la caisse pour CE dossier. Elle "
                 "varie selon le matériel — d'où la saisie au cas par cas.")
        c7, c8, c9 = st.columns([2, 2, 3])
        entente = c7.text_input("Entente accordée le",
                                key="lo_nouveau_entente",
                                placeholder="jj/mm/aaaa")
        facturation = c8.text_input("Dernière facturation",
                                    key="lo_nouveau_facturation",
                                    placeholder="jj/mm/aaaa")
        caution = c9.text_input(
            "Caution encaissée (F)", key="lo_nouveau_caution",
            placeholder="Proposée d'après le matériel — laissez vide",
            help="Laissée vide, elle se déduit du matériel : 3 000 F pour "
                 "un tensiomètre, 5 000 F pour un aérosol, rien pour le "
                 "reste.")
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

    # Caution laissée vide → celle du catalogue ; saisie → la sienne.
    montant = (loc.parser_montant(caution) if loc._texte(caution) else None)
    resultat = _appliquer(lambda courant: loc.ajouter_dossier(
        courant, patient, materiel, debut=debut, entente=entente,
        validite_mois=int(validite), derniere_facturation=facturation,
        notes=notes, mode=mode, demande_le=demande, demandee_par=par or "",
        caution=montant))
    if resultat is None:
        return
    st.session_state["lo_ajout_ouvert"] = True
    regime = loc.regime_propose(materiel)
    retenue = (montant if montant is not None
               else loc.caution_proposee(materiel))
    suite = ""
    if regime == loc.REGIME_LIBRE:
        suite = (f" Classé **hors caisse** ({loc.remboursement(materiel)})"
                 + (f", caution de {retenue:,} F.".replace(",", " ")
                    if retenue else "."))
    st.session_state["lo_message"] = (
        "ok", f"📁 {patient} — {materiel} ({mode}) : dossier "
              f"enregistré.{suite} {len(resultat)} dossier(s) suivi(s) — le "
              "formulaire est vide, vous pouvez enchaîner avec le patient "
              "suivant.")
    st.rerun()


# ---------------------------------------------------------------------------
# Sous-onglet 1 — Ententes préalables
# ---------------------------------------------------------------------------

def _prenoms_connus(dossiers: pd.DataFrame) -> list:
    """Les prénoms déjà saisis dans le fichier.

    La liste se remplit toute seule : personne n'a à tenir à jour un
    annuaire de l'équipe, et au bout de trois demandes on choisit au lieu
    de taper. Elle reste ouverte — un remplaçant d'un après-midi ne doit
    pas être un obstacle.
    """
    if dossiers is None or dossiers.empty:
        return []
    vus = [loc._texte(v) for v in dossiers.get("Demandée par", [])]
    return sorted({v for v in vus if v})


def _onglet_ententes(dossiers: pd.DataFrame, vue: pd.DataFrame,
                     aujourdhui: date) -> None:
    """Le parcours complet d'une entente : demande → accord → suivi.

    Quatre étapes, et non deux. L'étape « demande envoyée » manquait : un
    dossier parti à la caisse se lisait comme un dossier oublié, et on le
    refaisait. Elle porte une date ET un prénom — trois semaines plus
    tard, c'est la seule façon de savoir à qui demander ce qui a été
    envoyé.
    """
    if vue.empty:
        st.info("Aucun dossier — ouvrez-en un tout en haut de l'écran.")
        return
    # Le matériel hors caisse n'a pas sa place ici : il a son propre
    # sous-onglet, et l'afficher sous un tableau d'ententes reviendrait à
    # lui reprocher une démarche que personne ne lui demande.
    soumis = vue[vue["Régime"] != loc.REGIME_LIBRE]
    if soumis.empty:
        st.info("Aucun dossier soumis à entente préalable. Les aérosols et "
                "tensiomètres se suivent dans « 🆓 Sans entente ».")
        return

    attente = soumis[soumis["Entente"] == loc.STATUT_DEMANDE_ENVOYEE]
    rien = soumis[soumis["Entente"] == loc.STATUT_SANS_ENTENTE]
    if not rien.empty:
        st.warning(f"**{len(rien)} dossier(s) sans démarche engagée.** Tant "
                   "que la demande n'est pas partie, la location n'est "
                   "prise en charge par personne.")
    if not attente.empty:
        vieille = max(int(j or 0) for j in attente["Attente (j)"])
        st.info(f"📨 **{len(attente)} demande(s) en attente de réponse** — "
                f"la plus ancienne depuis {vieille} jour(s). "
                "Relancez la caisse : une demande qui dort est une location "
                "que personne ne paie.")
        st.dataframe(loc.pour_affichage(attente[loc.COLONNES_DEMANDES]),
                     use_container_width=True, hide_index=True,
                     column_config=_colonnes_vue())

    st.markdown("**Toutes les ententes**")
    st.caption("« Demandé le » est la date d'ENVOI à la caisse ; « Entente "
               "faite le » est celle de son **accord** — c'est de cette "
               "dernière que court la validité, et c'est elle que la caisse "
               "contrôlera.")
    st.dataframe(loc.pour_affichage(soumis[loc.COLONNES_ENTENTES]),
                 use_container_width=True, hide_index=True,
                 column_config=_colonnes_vue())

    with st.container(border=True):
        st.markdown("**Enregistrer une démarche**")
        ligne = _choisir_un_dossier(soumis, "lo_entente_dossier")
        if ligne is None:
            return
        patient, materiel, mode = (ligne["Patient"], ligne["Matériel"],
                                   ligne["Mode"])

        etape_demande, etape_accord, etape_suivi = st.tabs(
            ["📨 Demande envoyée", "✅ Accord reçu", "💬 Commentaire"])

        with etape_demande:
            st.caption("Le prénom n'est pas une formalité : c'est à lui "
                       "qu'on demandera ce qui a été envoyé, si la caisse "
                       "ne répond pas.")
            c1, c2 = st.columns([2, 3])
            envoyee = c1.date_input("Envoyée le", value=aujourdhui,
                                    format="DD/MM/YYYY",
                                    key="lo_demande_date")
            par = c2.selectbox(
                "Prénom de qui a fait la demande",
                _prenoms_connus(dossiers), index=None,
                accept_new_options=True, key="lo_demande_par",
                placeholder="Tapez un prénom — il sera proposé la "
                            "prochaine fois")
            if st.button("📨 Demande envoyée à la caisse", type="primary",
                         use_container_width=True, key="lo_demande_valider"):
                if not loc._texte(par):
                    st.error("**Le prénom est indispensable.** Sans lui, la "
                             "demande n'est traçable par personne.")
                else:
                    if _appliquer(lambda courant: loc.enregistrer_demande(
                            courant, patient, materiel, envoyee,
                            par, mode)) is not None:
                        st.session_state["lo_message"] = (
                            "ok", f"📨 {patient} — {materiel} : demande "
                                  f"envoyée le {envoyee:%d/%m/%Y} par "
                                  f"{par}. Elle apparaîtra dans les "
                                  "relances tant que la caisse n'aura pas "
                                  "répondu.")
                    st.rerun()

        with etape_accord:
            partie = ligne["Demande le"]
            if partie is not None and not pd.isna(partie):
                st.caption(f"Demande partie le {partie:%d/%m/%Y}"
                           + (f" par {ligne['Demandée par']}."
                              if ligne["Demandée par"] else "."))
            c1, c2 = st.columns([3, 2])
            accordee = c1.date_input("Accordée le", value=aujourdhui,
                                     format="DD/MM/YYYY",
                                     key="lo_entente_date")
            validite = c2.number_input(
                "Validité (mois)", min_value=1, max_value=60,
                value=int(ligne["Validité (mois)"]
                          or loc.VALIDITE_DEFAUT_MOIS),
                step=1, key="lo_entente_validite")
            if st.button("✅ Entente préalable faite", type="primary",
                         use_container_width=True, key="lo_entente_valider"):
                if _appliquer(lambda courant: loc.enregistrer_entente(
                        courant, patient, materiel, accordee,
                        int(validite), mode)) is not None:
                    fin = loc.ajouter_mois(accordee, int(validite))
                    st.session_state["lo_message"] = (
                        "ok", f"✅ {patient} — {materiel} : entente accordée "
                              f"le {accordee:%d/%m/%Y}, valable jusqu'au "
                              f"{fin:%d/%m/%Y}.")
                st.rerun()

        with etape_suivi:
            st.caption("Relance, pièce manquante, refus, numéro de "
                       "dossier : ce qui se passe entre la demande et "
                       "l'accord. Séparé des notes de la location — "
                       "mélangés, on ne retrouve ni l'un ni l'autre trois "
                       "mois plus tard.")
            texte = st.text_area(
                "Commentaire sur l'entente",
                value=ligne["Commentaire entente"], height=100,
                key="lo_commentaire_texte",
                placeholder="Ex. : relancé la caisse le 12/09, dossier "
                            "incomplet — manque l'ordonnance du Dr X")
            if st.button("💬 Enregistrer le commentaire",
                         use_container_width=True,
                         key="lo_commentaire_valider"):
                if _appliquer(lambda courant: loc.enregistrer_commentaire(
                        courant, patient, materiel, texte,
                        mode)) is not None:
                    st.session_state["lo_message"] = (
                        "ok", f"💬 {patient} — {materiel} : commentaire "
                              "enregistré.")
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
                # « Au moment de la facturation du dernier mois, une
                # proposition de renouvellement. » C'est ici, et nulle part
                # ailleurs : on tient le dossier en main, et il n'y aura
                # pas de mois suivant pour y revenir.
                if loc.au_dernier_mois(ligne["Entente préalable"],
                                       ligne["Validité (mois)"], jour, mode,
                                       loc.PERIODE_FACTURATION_MOIS):
                    st.session_state["lo_renouveler"] = (patient, materiel,
                                                         mode)
            st.rerun()


def _proposition_de_renouvellement(vue: pd.DataFrame, aujourdhui: date) -> None:
    """« C'était le dernier mois couvert » — et la demande part d'ici.

    Affichée juste après la facturation qui l'a déclenchée : c'est le seul
    instant où le dossier est ouvert, le patient identifié et la question
    encore fraîche. Renvoyée à une liste du lendemain, elle se lit comme
    une tâche de plus ; ici, c'est la suite du geste qu'on vient de faire.
    """
    cible = st.session_state.get("lo_renouveler")
    if not cible:
        return
    patient, materiel, mode = cible
    with st.container(border=True, key="lo_bulle_renouvellement"):
        st.markdown(f"### 🔔 Dernier mois couvert — {patient}")
        st.markdown(
            f"L'entente de **{materiel}** ne couvre pas le mois prochain. "
            "Si la location continue, la demande de renouvellement doit "
            "partir **maintenant** : le temps de revoir le médecin et "
            "d'attendre la réponse de la caisse.")
        c1, c2, c3 = st.columns([2, 3, 2])
        envoyee = c1.date_input("Envoyée le", value=aujourdhui,
                                format="DD/MM/YYYY", key="lo_renouv_date")
        par = c2.selectbox(
            "Prénom", _prenoms_connus(st.session_state.get("lo_dossiers")),
            index=None, accept_new_options=True, key="lo_renouv_par",
            placeholder="Qui fait la demande ?")
        c3.write("")
        if st.button("📨 Demande de renouvellement envoyée", type="primary",
                     use_container_width=True, key="lo_renouv_valider"):
            if not loc._texte(par):
                st.error("**Le prénom est indispensable.** Sans lui, la "
                         "demande n'est traçable par personne.")
            else:
                if _appliquer(lambda courant: loc.enregistrer_demande(
                        courant, patient, materiel, envoyee, par,
                        mode)) is not None:
                    st.session_state.pop("lo_renouveler", None)
                    st.session_state["lo_message"] = (
                        "ok", f"📨 {patient} — {materiel} : renouvellement "
                              f"demandé le {envoyee:%d/%m/%Y} par {par}.")
                st.rerun()
        if st.button("Plus tard — la location s'arrête là",
                     use_container_width=True, key="lo_renouv_plus_tard"):
            st.session_state.pop("lo_renouveler", None)
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
# Sous-onglet 5 — Loué hors caisse : aérosols et tensiomètres
# ---------------------------------------------------------------------------

def _onglet_sans_entente(vue: pd.DataFrame, aujourdhui: date) -> None:
    """Ce qui se loue sans passer par la caisse, et ce que ça engage.

    Tensiomètre et aérosol n'ont pas d'entente préalable, pas d'échéance,
    pas de renouvellement. Mêlés aux autres, ils s'affichaient « rien de
    fait » à vie, c'est-à-dire comme un manquement — ils n'en sont pas un.

    Ce qu'ils ont, c'est une CAUTION : de l'argent encaissé qui appartient
    au patient tant qu'il n'a pas rendu l'appareil. C'est la seule chose à
    suivre, et elle n'a sa place dans aucune autre liste.
    """
    libres = loc.du_regime(vue, loc.REGIME_LIBRE)
    st.caption(
        f"**Tensiomètre** — non remboursé, caution "
        f"{loc.CATALOGUE_SANS_ENTENTE['TENSIOMETRE']['caution']:,} F. "
        f"**Aérosol** — remboursé sous conditions, caution "
        f"{loc.CATALOGUE_SANS_ENTENTE['AEROSOL']['caution']:,} F. "
        "Aucun des deux ne demande d'entente préalable : taper le nom de "
        "l'appareil suffit, le régime et la caution se proposent seuls."
        .replace(",", " "))
    if libres.empty:
        st.info("Aucune location hors caisse. Ouvrez un dossier tout en "
                "haut de l'écran en tapant « Tensiomètre » ou « Aérosol » "
                "comme matériel : le reste se remplit tout seul.")
        return

    detenues = loc.cautions_detenues(libres)
    en_cours = libres[[r is None or pd.isna(r)
                       for r in libres["Caution rendue le"]]]
    if detenues:
        st.markdown(
            f"**💰 {detenues:,} F de cautions détenues** pour "
            f"{len(en_cours)} appareil(s) encore chez des patients. Cet "
            "argent n'est pas à la pharmacie : il est chez elle."
            .replace(",", " "))
    else:
        st.success("✅ Aucune caution en cours : tous les appareils sont "
                   "revenus.")

    st.dataframe(loc.pour_affichage(libres[loc.COLONNES_SANS_ENTENTE]),
                 use_container_width=True, hide_index=True,
                 column_config=_colonnes_vue())

    if en_cours.empty:
        return
    with st.container(border=True):
        st.markdown("**↩️ L'appareil est revenu, la caution est rendue**")
        ligne = _choisir_un_dossier(en_cours, "lo_caution_dossier")
        if ligne is None:
            return
        jour = st.date_input("Rendue le", value=aujourdhui,
                             format="DD/MM/YYYY", key="lo_caution_date")
        montant = loc.parser_montant(ligne["Caution (F)"])
        if st.button(f"↩️ Caution de {montant:,} F rendue".replace(",", " "),
                     type="primary", use_container_width=True,
                     key="lo_caution_valider"):
            patient, materiel = ligne["Patient"], ligne["Matériel"]
            mode = ligne["Mode"]
            if _appliquer(lambda courant: loc.enregistrer_caution_rendue(
                    courant, patient, materiel, jour, mode)) is not None:
                st.session_state["lo_message"] = (
                    "ok", f"↩️ {patient} — {materiel} : caution de "
                          f"{montant:,} F rendue le {jour:%d/%m/%Y}."
                          .replace(",", " "))
            st.rerun()


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

def _bandeau(resume: dict, tuile) -> None:
    st.markdown('<div class="kpi-row">' + "".join([
        tuile("Dossiers suivis", resume["dossiers"], "accent",
              sous=f'{resume["locations"]} loué(s) · '
                   f'{resume["achats"]} acheté(s)'),
        tuile("📨 Demandes en attente", resume["demandes_en_attente"],
              "accent" if resume["demandes_en_attente"] else "",
              sous="parties, sans réponse"),
        tuile("🔁 À renouveler", resume["a_renouveler"] + resume["dernier_mois"],
              "accent" if resume["a_renouveler"] + resume["dernier_mois"]
              else "",
              sous=f'dont {resume["dernier_mois"]} au dernier mois'),
        tuile("⛔ Ententes expirées", resume["expirees"],
              "critical" if resume["expirees"] else "",
              sous="plus prises en charge"),
        tuile("💰 À facturer", resume["a_facturer"],
              "critical" if resume["a_facturer"] else "",
              sous=f'{resume["mois_dus"]} mois dus'),
        tuile("🆓 Hors caisse", resume["hors_caisse"], "",
              sous=f'{resume["cautions"]:,} F de cautions'.replace(",", " ")),
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
    """Affiche l'écran complet du module.

    ``etape`` et ``tuile_kpi`` sont les fonctions d'habillage de ``app.py``,
    passées en paramètre pour garder ce module indépendant de l'application.
    """
    dossiers = _etat()
    aujourdhui, alerte = _barre_laterale(dossiers, date.today())

    message = st.session_state.pop("lo_message", None)
    if message:
        niveau, texte = message
        (st.success if niveau == "ok" else st.warning)(texte)

    vue_courante = loc.vue_affichable(dossiers, aujourdhui, loc.TRI_ECHEANCE,
                                      alerte)

    _bandeau(loc.resume(dossiers, aujourdhui, alerte), tuile_kpi)

    # La proposition de renouvellement passe AVANT tout le reste : elle
    # naît d'un geste qu'on vient de faire, et enfouie sous l'écran elle
    # se lirait comme une tâche de plus au lieu de sa suite immédiate.
    _proposition_de_renouvellement(vue_courante, aujourdhui)

    _panneau_ajout(dossiers)

    etape("1", "Les trois questions de la location",
          "L'entente est-elle faite, qu'y a-t-il à facturer, et qu'est-ce "
          "qui expire bientôt.")

    vue = vue_courante
    onglets = st.tabs(["✅ Ententes préalables", "💰 Facturations",
                       "🔁 À renouveler", "🛒 Achats", "🆓 Sans entente"])
    with onglets[0]:
        _onglet_ententes(dossiers, vue, aujourdhui)
    with onglets[1]:
        _onglet_facturations(dossiers, vue, aujourdhui)
    with onglets[2]:
        _onglet_renouvellement(dossiers, aujourdhui, alerte)
    with onglets[3]:
        _onglet_achats(vue)
    with onglets[4]:
        _onglet_sans_entente(vue, aujourdhui)

    st.divider()
    etape("2", "Chaque patient d'un coup d'œil",
          "Ce qu'il loue, ce qu'il a acheté, et ce qui presse — sur une "
          "seule ligne.")
    _recapitulatif_par_patient(dossiers, aujourdhui, alerte)

    st.divider()
    etape("3", "Tous les dossiers", "La référence, corrigeable à la main.")
    colonne_recherche, colonne_tri = st.columns([3, 2])
    recherche = colonne_recherche.text_input(
        "🔍 Rechercher", key="lo_recherche",
        placeholder="Nom du patient ou matériel loué")
    tri = colonne_tri.selectbox("↕️ Classer par", loc.TRIS, key="lo_tri")

    # Recalculée avec le tri demandé : les sous-onglets ci-dessus sont
    # toujours classés par échéance — ce qui expire en premier doit sauter
    # aux yeux — tandis que la référence se classe comme on veut la lire.
    classee = loc.vue_affichable(dossiers, aujourdhui, tri, alerte)
    if dossiers.empty:
        st.info("Aucun dossier — ouvrez-en un tout en haut de l'écran.")
    elif recherche.strip():
        # Le tableau ne devient modifiable que sur la liste ENTIÈRE :
        # corriger une vue filtrée réécrirait les dossiers en perdant les
        # lignes masquées.
        motif = recherche.strip().lower()
        garde = classee.apply(
            lambda l: motif in f"{l['Patient']} {l['Matériel']} "
                               f"{l['Mode']}".lower(),
            axis=1)
        filtree = classee[garde]
        st.dataframe(loc.pour_affichage(filtree[loc.COLONNES_VUE]),
                     use_container_width=True, hide_index=True,
                     column_config=_colonnes_vue())
        st.caption(f"{len(filtree)} dossier(s) trouvé(s). Videz la recherche "
                   "pour corriger le tableau.")
    else:
        corrige = _tableau(classee)
        if corrige is not None:
            _enregistrer_corrections(corrige)
            st.rerun()

    st.divider()
    etape("4", "Imprimez ou exportez",
          "La liste des ententes, à poser à côté du téléphone.")
    st.download_button(
        "📄 Exporter en CSV",
        loc.exporter_csv(dossiers, aujourdhui, tri, alerte),
        file_name=loc.nom_fichier("csv", aujourdhui), mime=_MIME_CSV,
        use_container_width=True)
