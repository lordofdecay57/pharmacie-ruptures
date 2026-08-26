# -*- coding: utf-8 -*-
"""Interface Streamlit — pilotage pharmacie d'officine.

Couche interface UNIQUEMENT : toute la logique métier vit dans les modules
de calcul (commun.py, moteur_ruptures.py, stock_rotation.py). Lancement :
``streamlit run app.py`` (ou double-clic sur lancer.bat / lancer.command).

Deux modules fonctionnels INDÉPENDANTS, chacun son onglet principal :
  📦 Gestion des stocks en rotation (stock_rotation.py) — stock min / max
     par produit à partir du seul cadencier, règle des 10 unités.
  🚨 Gestion des ruptures (moteur_ruptures.py) — croise le cadencier avec
     les listes de ruptures GPNC / UNIPHARMA, urgence en 3 paliers.

Parcours (suivi dans la barre latérale) :
  1. Déposer les 3 fichiers (cadencier, ruptures GPNC, ruptures UNIPHARMA)
     — ou cliquer « Essayer avec des données de démonstration ».
  2. Confirmer / corriger le mapping des colonnes (proposé automatiquement,
     mémorisé dans config.yaml pour les fois suivantes).
  3. Régler les paramètres de chaque module (barre latérale), lancer
     l'analyse.
  4. Consulter les deux onglets principaux, télécharger les Excel dédiés.
"""

import dataclasses
import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

import commun
import mise_a_jour
import moteur_ruptures as moteur
import raccourci
import stock_rotation
import ui_commun

# ---------------------------------------------------------------------------
# Garde-fou de lancement : « python app.py » au lieu de « streamlit run
# app.py ». Dans ce mode, AUCUNE protection Streamlit ne fonctionne —
# st.stop() est inopérant sans contexte d'exécution, les widgets renvoient
# None — et le script planterait plus bas (KeyError: 'cadencier'). On
# relance alors le script correctement, de façon transparente.
# ---------------------------------------------------------------------------
from streamlit import runtime

if __name__ == "__main__" and not runtime.exists():
    import sys
    from streamlit.web import cli as _stcli
    print("Lancement de l'interface Streamlit… "
          "(équivalent : python -m streamlit run app.py)")
    sys.argv = ["streamlit", "run", str(Path(__file__).resolve())]
    sys.exit(_stcli.main())

_journal = logging.getLogger("pharmacie.app")

# Version affichée dans le bandeau : permet de vérifier d'un coup d'œil que
# la bonne version tourne (utile après une mise à jour du dossier local).
VERSION_APP = "6.9"

# Dossier des données de la pharmacie : celui du programme par défaut,
# déplaçable par la variable d'environnement PHARMACIE_DONNEES (cf.
# ui_commun). Les tests s'en servent pour ne JAMAIS toucher aux vraies
# données — ces chemins ne dépendent pas du répertoire de lancement.
_DONNEES = ui_commun.dossier_donnees()
CONFIG_PATH = _DONNEES / "config.yaml"
HISTORIQUE_PATH = _DONNEES / "historique_commandes.csv"
# État du stock min/max de la dernière analyse — sert à ne ressortir, au
# cadencier suivant, que les lignes dont le stock a changé (≥ 10 %).
ETAT_STOCK_PATH = _DONNEES / "etat_stock_precedent.csv"
# Signature des colonnes du cadencier de la dernière analyse : la règle
# « ne pas ressortir les stocks inchangés » ne s'applique que si le document
# de base n'a pas changé de structure (mêmes colonnes de ventes, même format).
ETAT_STOCK_SIG_PATH = _DONNEES / "etat_stock_precedent.sig"
COLONNES_HISTORIQUE = ui_commun.COLONNES_HISTORIQUE
# Type « commande » : produit signalé (onglets 1-2) — compte dans le
# comparatif quotidien. Type « surveillance » : écarté de justesse — sert
# uniquement au suivi des dates de réappro repoussées. Historique du Module
# « Gestion des ruptures » exclusivement — le Module « Stock en rotation »
# ne lit ni n'écrit ce fichier (isolation fonctionnelle des deux modules).

st.set_page_config(page_title="Pharmacie — stock & ruptures", page_icon="💊",
                   layout="wide", initial_sidebar_state="expanded")

# ---------------------------------------------------------------------------
# Habillage (bandeau, tuiles KPI) — l'urgence/alerte est TOUJOURS icône +
# libellé, la couleur n'est qu'un renfort (accessibilité, impression N&B).
# ---------------------------------------------------------------------------

st.markdown("""
<style>
/* Bandeau volontairement DISCRET : il rappelle où l'on est et quelle
   version tourne, rien de plus. La place revient au choix de l'espace de
   travail, juste en dessous, qui est la vraie décision de l'écran. */
.hero {
  background: linear-gradient(120deg, #0f766e, #0d9488);
  border-radius: 10px; padding: 10px 18px; color: #ffffff;
  display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap;
}
.hero h1 { color: #ffffff; font-size: 1.12rem; margin: 0; padding: 0;
  font-weight: 700; }
.hero .version { font-size: .74rem; font-weight: 600;
  background: rgba(255,255,255,.22); border-radius: 999px; padding: 1px 9px;
  letter-spacing: .3px; }
/* Version périmée : signalé en ambre, impossible à confondre avec le reste
   du bandeau — c'est la seule information du bandeau qui appelle une action. */
.hero .maj { background: #b45309; color: #fff; font-size: .78rem;
  font-weight: 600; border-radius: 999px; padding: 3px 12px; }

/* Choix de l'espace de travail : deux grands onglets, impossibles à
   manquer. Ciblé par la clé du widget (st-key-espace_travail) pour ne pas
   déformer les autres groupes de boutons de l'application. */
.st-key-espace_travail { margin: 12px 0 4px 0; }
.st-key-espace_travail [data-testid="stButtonGroup"] { gap: 10px; }
.st-key-espace_travail button {
  padding: 15px 20px !important; border-radius: 10px !important;
  border: 1px solid rgba(11,11,11,.14) !important;
}
.st-key-espace_travail button p {
  font-size: 1.05rem !important; font-weight: 600 !important;
}
/* L'onglet ACTIF est plein : la couleur seule ne suffirait pas à le
   distinguer d'un survol, un fond franc le rend évident.
   DEUX sélecteurs : « aria-checked » est l'attribut standard, stable d'une
   version de Streamlit à l'autre ; « kind » était l'attribut interne des
   versions ≤ 1.58, disparu depuis. S'appuyer sur le seul attribut interne
   faisait perdre le remplissage — et les onglets redevenaient indistincts —
   au premier Streamlit un peu récent. */
.st-key-espace_travail button[aria-checked="true"],
.st-key-espace_travail button[kind="segmented_controlActive"] {
  background: #0f766e !important; border-color: #0f766e !important;
  box-shadow: 0 2px 6px rgba(15,118,110,.30) !important;
}
.st-key-espace_travail button[aria-checked="true"] p,
.st-key-espace_travail button[kind="segmented_controlActive"] p {
  color: #ffffff !important;
}

/* Entrée / Sortie du stock fermé : les DEUX boutons les plus cliqués de
   toute l'application — chaque boîte scannée passe par l'un ou l'autre.
   Ils sont donc traités en grand, et chacun garde sa couleur MÊME éteint :
   savoir dans quel sens on travaille ne doit pas demander à lire. */
.st-key-sf_mode { margin: 6px 0 12px 0; }
.st-key-sf_mode [data-testid="stButtonGroup"] { gap: 14px; }
.st-key-sf_mode button {
  padding: 18px 46px !important; border-radius: 12px !important;
  border: 2px solid #0f766e !important; background: #ecfdf5 !important;
}
.st-key-sf_mode button p { font-size: 1.25rem !important;
  font-weight: 700 !important; color: #0f766e !important; }
/* La SORTIE retire du stock : ambre, pour qu'on ne scanne pas une entrée en
   croyant faire une sortie, ou l'inverse. */
.st-key-sf_mode button:last-child { border-color: #b45309 !important;
  background: #fff7ed !important; }
.st-key-sf_mode button:last-child p { color: #b45309 !important; }
/* Le bouton ACTIF est plein : un simple contour se confondrait avec le
   survol du bouton voisin.
   DEUX sélecteurs : « aria-checked » est l'attribut standard, stable d'une
   version de Streamlit à l'autre ; « kind » était l'attribut interne des
   versions ≤ 1.58, disparu depuis. */
.st-key-sf_mode button[aria-checked="true"],
.st-key-sf_mode button[kind="segmented_controlActive"] {
  background: #0f766e !important;
  box-shadow: 0 3px 10px rgba(15,118,110,.35) !important;
}
.st-key-sf_mode button:last-child[aria-checked="true"],
.st-key-sf_mode button:last-child[kind="segmented_controlActive"] {
  background: #b45309 !important;
  box-shadow: 0 3px 10px rgba(180,83,9,.35) !important;
}
.st-key-sf_mode button[aria-checked="true"] p,
.st-key-sf_mode button[kind="segmented_controlActive"] p,
.st-key-sf_mode button:last-child[aria-checked="true"] p,
.st-key-sf_mode button:last-child[kind="segmented_controlActive"] p {
  color: #ffffff !important;
}

/* Séparateur d'espace : une barre de couleur propre à chaque module, pour
   qu'on sache d'un coup d'œil dans lequel on travaille. */
.espace { border-left: 5px solid #0f766e; padding: 2px 0 2px 14px;
  margin: 4px 0 16px 0; }
.espace.ferme { border-left-color: #7c3aed; }
.espace.speciales { border-left-color: #b45309; }
.espace .titre { font-size: 1.3rem; font-weight: 700; color: #0b0b0b; }
.espace .sous  { font-size: .88rem; color: #6b6a66; margin-top: 2px; }

.kpi-row { display: flex; gap: 14px; flex-wrap: wrap; margin: 8px 0 14px 0; }
.kpi { flex: 1 1 180px; max-width: 340px; background: #ffffff;
  border: 1px solid rgba(11,11,11,.10); border-radius: 12px;
  padding: 14px 18px 12px; border-top: 4px solid #e1e0d9; }
.kpi .label { font-size: .82rem; color: #52514e; }
.kpi .value { font-size: 2.05rem; font-weight: 700; color: #0b0b0b; line-height: 1.2; }
.kpi .sub   { font-size: .76rem; color: #898781; margin-top: 2px; }
.kpi.accent   { border-top-color: #0f766e; }
.kpi.critical { border-top-color: #d03b3b; }
.kpi.warning  { border-top-color: #fab219; }
.kpi.serious  { border-top-color: #ec835a; }

/* En-tête d'étape numérotée — rend le parcours linéaire et évident. */
.step { display: flex; align-items: center; gap: 12px; margin: 6px 0 2px; }
.step .num { flex: 0 0 auto; width: 34px; height: 34px; border-radius: 50%;
  background: #0f766e; color: #fff; font-weight: 700; font-size: 1.05rem;
  display: flex; align-items: center; justify-content: center; }
.step .txt { font-size: 1.25rem; font-weight: 700; color: #0b0b0b; }
.step .txt small { display: block; font-size: .82rem; font-weight: 400;
  color: #6b6a66; margin-top: 1px; }

/* Lisibilité générale : tableaux un peu plus aérés et lisibles. */
[data-testid="stDataFrame"] { font-size: .95rem; }
section.main .block-container { padding-top: 2.2rem; }
</style>
""", unsafe_allow_html=True)


def _etape(numero: str, titre: str, sous_titre: str = "") -> None:
    """Affiche un en-tête d'étape numéroté (parcours guidé ①②③)."""
    sous = f"<small>{sous_titre}</small>" if sous_titre else ""
    st.markdown(f'<div class="step"><span class="num">{numero}</span>'
                f'<span class="txt">{titre}{sous}</span></div>',
                unsafe_allow_html=True)

def _entete_espace(titre: str, sous_titre: str = "", variante: str = "") -> None:
    """Bandeau d'espace : dit en clair dans quel module on travaille.

    Le sous-titre est facultatif : quand l'écran explique déjà de quoi il
    s'agit, le répéter ici ne fait qu'ajouter une ligne à lire.
    """
    sous = f'<div class="sous">{sous_titre}</div>' if sous_titre else ""
    st.markdown(f'<div class="espace {variante}">'
                f'<div class="titre">{titre}</div>{sous}</div>',
                unsafe_allow_html=True)


# Une mise à jour peut échouer sans bruit (ancienne instance encore ouverte
# sur le port, nouvelle version démarrée ailleurs) : on tournait alors sur
# une version périmée sans le savoir. Le bandeau le dit. Vérifié au plus une
# fois par heure, sans jamais bloquer si le poste est hors ligne.
@st.cache_data(ttl=3600, show_spinner=False)
def _version_publiee_cache() -> str:
    return ui_commun.version_publiee() or ""


_maj = ""
if st.session_state.get("verifier_version", True):
    if ui_commun.mise_a_jour_disponible(VERSION_APP, _version_publiee_cache()):
        # Le bandeau renvoie vers le BOUTON, pas vers un fichier à retrouver
        # dans un dossier : nommer un « .bat » n'aide personne — Windows en
        # masque l'extension, certains postes en interdisent l'exécution, et
        # depuis un poste sans installation locale ce fichier n'existe même
        # pas. Le bouton, lui, est dans l'écran déjà ouvert.
        _maj = (f'<span class="maj">⬆️ v{_version_publiee_cache()} disponible '
                "— bouton d'installation dans la barre latérale ◀</span>")

st.markdown(f"""
<div class="hero">
  <h1>💊 Pilotage pharmacie</h1>
  <span class="version">v{VERSION_APP}</span>
  {_maj}
</div>
""", unsafe_allow_html=True)
st.write("")


def _tuile_kpi(label: str, valeur, variante: str = "", sous: str = "") -> str:
    """Tuile de synthèse : libellé discret, valeur en encre noire."""
    sous_html = f'<div class="sub">{sous}</div>' if sous else ""
    return (f'<div class="kpi {variante}"><div class="label">{label}</div>'
            f'<div class="value">{valeur}</div>{sous_html}</div>')


def _onglet_simple(df: pd.DataFrame, message_vide: str, legende: str) -> None:
    """Affichage commun des tableaux simples : tableau ou message vide."""
    if df.empty:
        st.info(message_vide)
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(legende)


# ---------------------------------------------------------------------------
# Choix de l'espace de travail
#
# Le stock fermé (Module 3) ne travaille sur AUCUN fichier déposé : il a son
# propre inventaire et ses propres exports. Le brancher ici, avant l'étape 1,
# lui évite d'être bloqué par les garde-fous « déposez d'abord le cadencier »
# du parcours principal — et matérialise son indépendance.
# ---------------------------------------------------------------------------

ESPACE_CADENCIER = "📈  Cadencier — stock & ruptures"
ESPACE_STOCK_FERME = "🔒  Stock fermé — inventaire scanné"
ESPACE_COMMANDES = "💠  Commandes spéciales"

DOSSIER_APP = Path(__file__).resolve().parent


def _proposer_raccourci() -> None:
    """Propose de poser l'icône du Bureau — seulement si elle manque.

    Un fichier à retrouver dans un dossier, c'est déjà trop demander :
    Windows masque l'extension « .bat », et certains postes en interdisent
    l'exécution. Le bouton est ici, dans l'écran déjà ouvert.

    Il s'efface de lui-même une fois l'icône posée : une proposition qui
    reste affichée après avoir été suivie n'est plus une aide, c'est du
    bruit. Rien ne s'affiche non plus hors Windows.
    """
    with st.sidebar:
        message = st.session_state.pop("raccourci_message", None)
        if message:
            niveau, texte = message
            (st.success if niveau == "ok" else st.warning)(texte)
        if not raccourci.sur_windows() or raccourci.raccourci_existant():
            return
        with st.container(border=True):
            st.markdown("**🖥️ Icône du Bureau**")
            st.caption("Aucune icône « Pharmacie » sur votre Bureau. Elle "
                       "ouvre l'utilitaire en un double-clic, sans avoir à "
                       "revenir dans ce dossier.")
            if st.button("📌 Créer l'icône maintenant",
                         use_container_width=True):
                succes, texte = raccourci.creer(DOSSIER_APP)
                st.session_state["raccourci_message"] = (
                    "ok" if succes else "attention", texte)
                st.rerun()

def _mode_serveur() -> bool:
    """Cette instance sert-elle toute la pharmacie, ou ce poste seulement ?

    On lit le drapeau avec lequel le processus a RÉELLEMENT démarré :
    ``lancer-serveur.bat`` passe ``--server.address 0.0.0.0``, pas
    ``lancer.bat``. Un fichier témoin, lui, survivrait à un changement de
    mode — et se tromper coûte cher : relancer un poste isolé en mode
    serveur n'ouvrirait plus aucune fenêtre devant quelqu'un qui attend.
    """
    try:
        return st.get_option("server.address") == "0.0.0.0"
    except Exception:                        # option absente d'une version
        return False


def _proposer_mise_a_jour() -> None:
    """Installe la nouvelle version en un clic, quand il y en a une.

    Le bandeau annonçait « ⬆️ vX disponible » sans donner le moyen de la
    prendre : il constatait le retard sans permettre de le combler. Et le
    geste le plus courant — double-cliquer sur l'icône du Bureau — ne met
    JAMAIS à jour, puisque la mise à jour automatique se reporte tant que
    l'application répond, et que personne ne la ferme d'abord.

    L'encadré n'apparaît que lorsqu'il sert : à jour, il n'y a rien à dire.
    """
    with st.sidebar:
        message = st.session_state.pop("maj_message", None)
        if message:
            niveau, texte = message
            (st.success if niveau == "ok" else st.warning)(texte)
        # Même interrupteur que le bandeau : qui coupe la vérification de
        # version ne doit pas se voir proposer d'installer quand même.
        if not mise_a_jour.sur_windows():
            return
        if not st.session_state.get("verifier_version", True):
            return
        publiee = _version_publiee_cache()
        if not ui_commun.mise_a_jour_disponible(VERSION_APP, publiee):
            return

        serveur = _mode_serveur()
        with st.container(border=True):
            st.markdown(f"**⬆️ Version v{publiee} disponible**")
            if serveur:
                # Un clic depuis un comptoir arrête l'application de TOUTE
                # la pharmacie : cela se dit avant, pas après.
                st.caption("Cette application sert tous les postes. La mettre "
                           "à jour la redémarre : chaque poste perdra sa page "
                           "une trentaine de secondes, et une fiche en cours "
                           "de saisie sera perdue.")
                pret = st.checkbox("J'ai prévenu les autres postes",
                                   key="maj_confirme_serveur")
            else:
                st.caption("L'application va redémarrer et cette page se "
                           "rechargera toute seule. Vous ne perdez rien de "
                           "ce qui est enregistré.")
                pret = True
            if st.button(f"⬆️ Installer la v{publiee}", type="primary",
                         use_container_width=True, disabled=not pret):
                succes, texte = mise_a_jour.lancer(DOSSIER_APP,
                                                   mode_serveur=serveur)
                st.session_state["maj_message"] = (
                    "ok" if succes else "attention", texte)
                st.rerun()


# Deux grands onglets plutôt qu'un choix discret : les deux espaces ne
# partagent NI fichiers, NI données, NI exports. Savoir dans lequel on se
# trouve est la première chose à voir en arrivant sur l'écran.
def _garder_espace() -> None:
    """Empêche la déselection : recliquer l'onglet actif le laisse actif.

    Sans cela, un second clic sur l'onglet courant le déselectionne et
    PLUS AUCUN onglet n'apparaît choisi — il faut alors cliquer sur l'autre
    pour s'en sortir. Un onglet n'est pas une case à cocher : il y a
    toujours un espace de travail affiché, donc toujours un onglet actif.
    """
    if st.session_state.get("espace_travail") is None:
        st.session_state["espace_travail"] = st.session_state.get(
            "espace_retenu", ESPACE_CADENCIER)
    st.session_state["espace_retenu"] = st.session_state["espace_travail"]


# Avant l'aiguillage : la barre latérale des deux espaces est construite
# plus bas, chacune de son côté, et l'espace « stock fermé » s'arrête sur un
# st.stop(). Poser la proposition ici est le seul endroit d'où elle est
# visible dans les deux.
_proposer_mise_a_jour()
_proposer_raccourci()

espace = st.segmented_control(
    "Espace de travail",
    [ESPACE_CADENCIER, ESPACE_STOCK_FERME, ESPACE_COMMANDES],
    default=ESPACE_CADENCIER, label_visibility="collapsed",
    key="espace_travail", width="stretch", on_change=_garder_espace)
if espace is None:  # premier rendu suivant une déselection
    espace = st.session_state.get("espace_retenu", ESPACE_CADENCIER)

if espace == ESPACE_COMMANDES:
    import ui_commandes_speciales
    _entete_espace("💠 Commandes spéciales", variante="speciales")
    ui_commandes_speciales.rendre(_etape, _tuile_kpi)
    st.stop()  # le parcours « cadencier » ci-dessous ne concerne pas ce module

if espace == ESPACE_STOCK_FERME:
    import ui_stock_ferme
    # Sans sous-titre : la barre latérale décrit déjà ce qu'est ce stock, et
    # l'étape 1 dit quoi faire. Le répéter ici n'ajoutait qu'une ligne.
    _entete_espace("🔒 Stock fermé", variante="ferme")
    ui_stock_ferme.rendre(_etape, _tuile_kpi)
    st.stop()  # le parcours « cadencier » ci-dessous ne concerne pas ce module

_entete_espace(
    "📈 Cadencier — stock en rotation & ruptures",
    "Deux modules à partir des mêmes fichiers : le stock min/max par produit, "
    "et la commande de dépannage face aux ruptures fournisseurs.")

# ---------------------------------------------------------------------------
# Config (mémorisation du mapping des colonnes + des réglages des 2 modules)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _charger_fichier_cache(data: bytes, nom: str) -> pd.DataFrame:
    """Cache du parsing : un cadencier PDF de ~200 pages prend ~1 min à
    lire — sans cache, Streamlit le relirait à CHAQUE clic dans la page."""
    return commun.charger_fichier(data, nom)


# Les classeurs Excel sont construits à CHAQUE exécution du script, donc à
# chaque frappe dans la recherche et à chaque case cochée — alors qu'on ne
# les télécharge qu'une fois. Sur le cadencier réel (3 528 produits), la
# mise en forme openpyxl coûte près de 4 secondes : sans cache, l'interface
# est inutilisable. La clé de cache est le CONTENU des tableaux, donc le
# fichier n'est reconstruit que s'il a réellement changé.

@st.cache_data(show_spinner=False, max_entries=4)
def _excel_stock_cache(tableau: pd.DataFrame, dormants: pd.DataFrame) -> bytes:
    return stock_rotation.exporter_stock_rotation_excel(
        stock_rotation.ResultatStockRotation(tableau, dormants, {}))


@st.cache_data(show_spinner=False, max_entries=4)
def _excel_ruptures_cache(onglet1: pd.DataFrame, onglet2: pd.DataFrame,
                          onglet3: pd.DataFrame, vigilance: pd.DataFrame,
                          justesse: pd.DataFrame) -> bytes:
    return moteur.exporter_excel(moteur.ResultatAnalyse(
        onglet1, onglet2, onglet3, {}, [], [],
        vigilance=vigilance, ecartes_justesse=justesse))


def charger_config() -> dict:
    """Mapping + réglages mémorisés lors d'une analyse précédente (ou vide)."""
    if CONFIG_PATH.exists():
        try:
            return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            st.warning("config.yaml illisible — mapping repart de zéro.")
    return {}


def sauver_config(mapping: dict) -> None:
    """Mémorise le mapping confirmé pour ne pas le refaire chaque jour."""
    CONFIG_PATH.write_text(
        yaml.safe_dump(mapping, allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def _choix(label: str, colonnes: list, defaut, cle: str, optionnel=True):
    """Selectbox de mapping : propose ``defaut`` s'il existe encore."""
    options = (["(aucune)"] if optionnel else []) + list(colonnes)
    index = options.index(defaut) if defaut in options else 0
    valeur = st.selectbox(label, options, index=index, key=cle)
    return None if valeur == "(aucune)" else valeur


def _defaut(memo_valeur, colonnes: list, role: str):
    """Défaut d'un selectbox : le mémo s'il correspond encore au fichier,
    sinon la détection automatique (utile si le format du fichier change)."""
    if memo_valeur and memo_valeur in colonnes:
        return memo_valeur
    return commun.detecter_colonne(colonnes, role)


#: Voir ui_commun : empreinte des colonnes d'un fichier, pour repartir de
#: widgets neufs quand un cadencier de structure différente est déposé.
_signature_colonnes = ui_commun.signature_colonnes


def charger_etat_stock() -> tuple:
    """(stock min/max de la dernière analyse, signature du cadencier alors
    utilisé). Vide / None si première analyse."""
    signature = None
    if ETAT_STOCK_SIG_PATH.exists():
        try:
            signature = ETAT_STOCK_SIG_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            signature = None
    if ETAT_STOCK_PATH.exists():
        try:
            return (pd.read_csv(ETAT_STOCK_PATH, dtype={"Code CIP": str}),
                    signature)
        except (pd.errors.ParserError, pd.errors.EmptyDataError):
            pass
    return (pd.DataFrame(columns=stock_rotation.COLONNES_ETAT_STOCK), signature)


def sauver_etat_stock(tableau: pd.DataFrame, signature: str) -> None:
    """Mémorise le stock min/max courant ET la signature des colonnes du
    cadencier, comme référence pour la prochaine analyse."""
    stock_rotation.etat_stock_a_enregistrer(tableau).to_csv(
        ETAT_STOCK_PATH, index=False, encoding="utf-8")
    ETAT_STOCK_SIG_PATH.write_text(signature or "", encoding="utf-8")


def charger_historique() -> pd.DataFrame:
    """Historique des analyses de RUPTURES passées (suivi quotidien du
    Module « Gestion des ruptures » — sans lien avec le Module stock)."""
    if HISTORIQUE_PATH.exists():
        try:
            return pd.read_csv(HISTORIQUE_PATH)
        except (pd.errors.ParserError, pd.errors.EmptyDataError):
            return pd.DataFrame(columns=COLONNES_HISTORIQUE)
    return pd.DataFrame(columns=COLONNES_HISTORIQUE)


def sauver_historique_analyse(resultat, date_analyse: date) -> pd.DataFrame:
    """Ajoute l'analyse du jour à l'historique local (remplace une éventuelle
    analyse déjà enregistrée à la même date, pour éviter les doublons en cas
    de ré-analyse). Renvoie l'historique mis à jour."""
    historique = ui_commun.fusionner_historique(
        charger_historique(),
        ui_commun.lignes_historique_analyse(resultat, date_analyse),
        date_analyse)
    historique.to_csv(HISTORIQUE_PATH, index=False)
    return historique


# ---------------------------------------------------------------------------
# Données de démonstration (dates relatives à aujourd'hui → toujours valides)
# ---------------------------------------------------------------------------

def jeu_demonstration() -> dict:
    """Jeu fictif pour découvrir l'outil sans fichiers réels.

    Reprend les cas de référence (Titanoréine écartée, Ozempic modéré,
    Aranesp urgent) + rupture double, produit dormant, produit non vendu,
    et un produit à stock critique (< 10 unités, règle du Module stock).
    """
    def dans(jours: int) -> str:
        return (date.today() + timedelta(days=jours)).strftime("%d/%m/%Y")

    cadencier = pd.DataFrame({
        "Produit": ["TITANOREINE SUPPO B/12", "OZEMPIC 1MG STYLO",
                    "ARANESP 150 SOL INJ", "DALACINE 300 GEL",
                    "PRODUIT DORMANT", "TAHOR 10MG CPR",
                    "DOLIPRANE 1000 CPR B/8", "VENTOLINE 100 SPRAY",
                    "KARDEGIC 75MG SACH", "AMOXICILLINE 1G CPR",
                    "ELIQUIS 5MG CPR B/60"],
        "CIP": ["1001", "1002", "1003", "1004", "1005",
                "1006", "1007", "1008", "1009", "1010", "1011"],
        "Stock": [3.6, 5, 0, 2, 4, 0, 30, 2, 50, 1, 3],
        # Ventoline : un mois à 0 vente au milieu de mois actifs → indice de
        # rupture passée. Eliquis : HORS rupture GPNC mais 3 j de stock →
        # onglet Vigilance (rupture en rayon à venir).
        "Ventes avril": [6, 16, 4, 13, 0, 8, 60, 0, 40, 24, 28],
        "Ventes mai":   [6, 17, 4, 13, 0, 8, 58, 9, 40, 26, 30],
        "Ventes juin":  [6, 16.5, 4, 13, 0, 8, 62, 11, 40, 25, 32],
        # Ventoline : 3 déjà en commande (à déduire, évite le doublon).
        "Commande en cours": [0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0],
        # Kardegic : péremption proche (< 90 j) → alerte informative.
        "DLUO": ["", "", "", "", "", "", "", "", dans(70), "", ""],
    })
    ruptures_gpnc = pd.DataFrame({
        "Libellé": ["TITANOREINE SUPPO B/12", "OZEMPIC 1MG STYLO",
                    "ARANESP 150 SOL INJ", "DALACINE 300 GEL",
                    "PRODUIT DORMANT", "TAHOR 10MG CPR",
                    "DOLIPRANE 1000 CPR B/8", "VENTOLINE 100 SPRAY",
                    "KARDEGIC 75MG SACH", "AMOXICILLINE 1G CPR",
                    "PRODUIT NON VENDU"],
        "CIP": ["1001", "1002", "1003", "1004", "1005", "1006",
                "1007", "1008", "1009", "1010", "9999"],
        "Date réappro": [dans(16), "", dans(2), "", "", dans(22),
                         dans(20), "", "", dans(10), ""],
    })
    ruptures_unipharma = pd.DataFrame({
        "Désignation": ["DALACINE 300 GEL", "TAHOR 10MG CPR"],
        "CIP": ["1004", "1006"],
    })
    return {"cadencier": cadencier, "gpnc": ruptures_gpnc,
            "unipharma": ruptures_unipharma}


# ---------------------------------------------------------------------------
# Étape 1 — dépôt des fichiers (ou mode démonstration)
# ---------------------------------------------------------------------------

config = charger_config()

_etape("1", "Déposez vos fichiers",
       "Le cadencier suffit pour le stock. Ajoutez GPNC + UNIPHARMA pour les ruptures.")

col_fichiers = st.columns(3)
libelles_zones = [
    ("cadencier", "📒 Cadencier", "Historique des ventes + stock actuel"),
    ("gpnc", "🔴 Ruptures GPNC", "Fournisseur principal (ruptgpnc_ia)"),
    ("unipharma", "🟠 Ruptures UNIPHARMA", "Fournisseur de dépannage (ruptocdp_ia)"),
]
fichiers, dataframes = {}, {}
for colonne, (cle, titre, aide) in zip(col_fichiers, libelles_zones):
    with colonne, st.container(border=True):
        st.markdown(f"**{titre}**")
        st.caption(aide)
        fichiers[cle] = st.file_uploader(
            aide, type=["xlsx", "xls", "csv", "pdf"], key=f"fichier_{cle}",
            label_visibility="collapsed")
        if fichiers[cle] is not None:
            try:
                with st.spinner("Lecture du fichier…"):
                    dataframes[cle] = _charger_fichier_cache(
                        fichiers[cle].getvalue(), fichiers[cle].name)
                st.success(f"{len(dataframes[cle])} lignes · "
                           f"{len(dataframes[cle].columns)} colonnes")
            except ValueError as e:
                st.error(str(e))

# Mode démonstration : actif tant qu'aucun VRAI cadencier n'est déposé (le
# cadencier est le seul fichier indispensable — dès qu'il arrive, on repasse
# en mode normal, même sans les fichiers de ruptures).
mode_demo = (st.session_state.get("mode_demo", False)
             and "cadencier" not in dataframes)
if mode_demo:
    dataframes = jeu_demonstration()
    st.info("🧪 **Mode démonstration** — données fictives (les cas de "
            "référence : Titanoréine, Ozempic, Aranesp…). Déposez votre "
            "vrai cadencier ci-dessus pour repasser en mode normal.")
_journal.info("Pilotage pharmacie v%s — fichiers disponibles : %s%s",
              VERSION_APP, sorted(dataframes) or "aucun",
              " (démo)" if mode_demo else "")

# ---------------------------------------------------------------------------
# Barre latérale — épurée : progression + date + réglages avancés repliés
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## 💊 Pilotage pharmacie")

    st.markdown("#### Progression")
    for cle, nom, _ in [(c, t.split(" ", 1)[1], a) for c, t, a in libelles_zones]:
        if cle in dataframes:
            detail = "démo" if mode_demo else f"{len(dataframes[cle])} lignes"
            st.markdown(f"✅ {nom} — {detail}")
        else:
            st.markdown(f"⬜ {nom}")
    analyse_faite = st.session_state.get("resultat") is not None
    st.markdown("✅ Analyse lancée" if analyse_faite else "⬜ Analyse lancée")

    st.divider()
    date_analyse = st.date_input("📅 Date d'analyse", value=date.today(),
                                 format="DD/MM/YYYY")

    memo_rotation = (config if isinstance(config, dict) else {}).get(
        "stock_rotation", {})

    # Réglages fins regroupés dans un panneau REPLIÉ : les valeurs par
    # défaut conviennent au quotidien, et déplié il occupait tout l'écran
    # gauche au détriment de la progression et de la date d'analyse.
    with st.expander("⚙️ Réglages avancés", expanded=False):
        st.caption("Les valeurs par défaut conviennent dans la plupart des "
                   "cas — n'y touchez que si besoin.")

        st.markdown("**📦 Stock en rotation**")
        _options_periode = ["annuelle", "6mois", "3mois", "1mois", "lissee"]
        _libelle_periode = {
            "annuelle": "Annuelle (moyenne 12 mois)",
            "6mois": "Semestrielle (6 derniers mois)",
            "3mois": "Trimestrielle (3 derniers mois)",
            "1mois": "Mensuelle (dernier mois seul)",
            "lissee": "Lissée (réactive aux tendances)"}
        _memo_p = memo_rotation.get("periode", "annuelle")
        periode_rotation = st.radio(
            "Calcul de la consommation", _options_periode,
            index=_options_periode.index(_memo_p if _memo_p in _options_periode
                                         else "annuelle"),
            format_func=lambda p: _libelle_periode[p],
            key="periode_rotation")
        couverture_min = st.number_input(
            "Stock min (jours de couverture)", 1, 90,
            value=int(memo_rotation.get(
                "couverture_min", stock_rotation.COUVERTURE_MIN_JOURS_DEFAUT)),
            help="Point de commande : passer sous ce niveau de couverture "
                 "déclenche un réassort. Ajusté automatiquement les "
                 "vendredis (+2 j) et samedis (+1 j) : pas de réception de "
                 "commandes le week-end.")
        couverture_max = st.number_input(
            "Stock max (jours de couverture)", 1, 180,
            value=int(memo_rotation.get(
                "couverture_max", stock_rotation.COUVERTURE_MAX_JOURS_DEFAUT)),
            help="Plafond de réassort : au-delà, trésorerie immobilisée et "
                 "risque de péremption.")
        seuil_alerte_unites = st.number_input(
            "Seuil d'action immédiate (unités)", 0, 100,
            value=int(memo_rotation.get(
                "seuil_alerte", stock_rotation.SEUIL_ALERTE_UNITES_DEFAUT)),
            help="Règle métier : sous ce seuil ABSOLU, la cible de commande "
                 "passe directement au stock max (pas de recomplètement "
                 "progressif jusqu'au seul stock min).")
        corriger_zeros_stock = st.checkbox(
            "Corriger les mois à 0 des ruptures passées", value=True,
            key="corriger_zeros_stock",
            help="Un mois à 0 vente ENTRE deux mois actifs = produit en "
                 "rupture, pas absence de demande.")
        rotation_min_commande = st.number_input(
            "Écarter les produits vendus au maximum de (boîtes/mois)", 0.0, 20.0,
            value=float(memo_rotation.get(
                "rotation_min_commande",
                stock_rotation.ROTATION_MIN_COMMANDE_DEFAUT)),
            step=1.0,
            help="Les produits à rotation ≤ cette valeur sont écartés du "
                 "réassort automatique (pas de commande) — évite d'encombrer "
                 "la commande d'une boîte de chaque produit vendu très "
                 "rarement. Ils restent consultables via le filtre "
                 "« ⚪ Rotation faible ». 0 = tout garder.")
        conso_defaut = st.number_input(
            "Consommation par défaut si pas d'historique (unités/mois)", 0, 500,
            value=int(memo_rotation.get("conso_defaut", 0)),
            help="Produit sans aucune vente enregistrée (nouveau, ou "
                 "cadencier trop court) : consommation de repli utilisée le "
                 "temps que l'historique s'accumule. 0 = désactivé (le "
                 "produit n'est pas piloté tant qu'il n'a pas d'historique).")
        seuil_dormant = st.number_input(
            "Seuil de stock dormant (jours de couverture)", 30, 720,
            value=int(memo_rotation.get(
                "seuil_dormant", stock_rotation.SEUIL_DORMANT_JOURS_DEFAUT)),
            help="Au-delà, le stock est considéré dormant (trésorerie "
                 "immobilisée).")

        st.divider()
        st.markdown("**🚨 Gestion des ruptures**")
        periode = st.radio(
            "Calcul de la rotation", _options_periode,
            format_func=lambda p: _libelle_periode[p],
            key="periode_ruptures",
            help="« Mensuelle » : le dernier mois seul, le plus réactif mais "
                 "sensible à un mois atypique. « Lissée » : lissage "
                 "exponentiel — suit les hausses ET les baisses récentes sans "
                 "sur-réagir à un mois isolé. Attention : un produit en rupture "
                 "EN COURS (derniers mois à 0) voit sa rotation mensuelle ou "
                 "lissée chuter — « Annuelle » reste plus robuste pour ces cas, "
                 "signalés « ⚠️ rupture passée possible ».")
        seuil_vigilance = st.number_input(
            "Seuil de vigilance stock (jours)", 1, 30,
            value=int(moteur.SEUIL_VIGILANCE_JOURS),
            help="Produits HORS rupture GPNC dont la couverture passe sous "
                 "ce seuil → onglet Vigilance (rupture en rayon à venir).")
        rotation_min_vigilance = st.number_input(
            "Rotation minimale vigilance (ventes/mois)", 0, 100,
            value=int(moteur.ROTATION_MIN_VIGILANCE),
            help="En dessous de ce volume de ventes, un stock bas n'est pas "
                 "signalé — évite le bruit des produits à rotation très lente.")
        seuil_marge = st.number_input(
            "Marge « écarté de justesse » (jours)", 0, 15,
            value=int(moteur.SEUIL_MARGE_JUSTESSE_JOURS),
            help="Produit écarté par la règle stricte avec moins de cette "
                 "marge → listé à part : si la réappro glisse, rupture sèche.")
        delai_livraison = st.number_input(
            "Délai de livraison UNIPHARMA (jours)", 0, 10, value=0,
            help="Ajouté à la couverture cible du calcul de Cmd : les boîtes "
                 "commandées aujourd'hui n'arrivent pas aujourd'hui. À 0, "
                 "les quantités restent identiques aux références validées.")
        rotation_prudente = st.checkbox(
            "Rotation prudente (max annuelle / 3 mois)", value=False,
            help="Retient la plus élevée des deux moyennes par produit — "
                 "un produit en croissance n'est jamais sous-couvert.")
        corriger_zeros = st.checkbox(
            "Corriger les mois à 0 des ruptures passées", value=True,
            key="corriger_zeros_ruptures",
            help="Un mois à 0 vente ENTRE deux mois actifs = produit en "
                 "rupture, pas absence de demande. Le corriger évite de "
                 "sous-commander les produits qui ont déjà manqué.")
        politique_abc = st.checkbox(
            "Politique de couverture par classe ABC", value=False,
            help="Sans date de réappro : cible A 21 j (réassort fréquent, "
                 "petites quantités) · B 30 j · C 14 j (éviter le surstock) "
                 "au lieu de 30 j pour tous. Modifie les quantités Cmd.")

    st.divider()
    if st.button("🔄 Nouvelle analyse", use_container_width=True):
        for cle in ("resultat", "resultat_stock", "date_analyse", "mode_demo"):
            st.session_state.pop(cle, None)
        st.rerun()

if "cadencier" not in dataframes:
    _journal.info("Cadencier absent — attente d'un dépôt de fichier.")
    st.info("Déposez au moins le **cadencier** pour continuer — ou "
            "découvrez l'outil avec des données fictives :")
    if st.button("🧪 Essayer avec des données de démonstration"):
        st.session_state["mode_demo"] = True
        st.rerun()
    st.stop()  # efficace : le garde-fou de lancement garantit le runtime

# ---------------------------------------------------------------------------
# Étape 2 — validation du mapping des colonnes (aperçu + menus déroulants)
# ---------------------------------------------------------------------------

st.divider()

df_cad = dataframes["cadencier"]
df_gpnc = dataframes.get("gpnc")
df_uni = dataframes.get("unipharma")
ruptures_disponibles = df_gpnc is not None and df_uni is not None

memo = config if isinstance(config, dict) else {}
memo_cad = memo.get("cadencier", {})
memo_gpnc = memo.get("gpnc", {})
memo_uni = memo.get("unipharma", {})

# Ouvert d'office UNIQUEMENT au premier usage (aucun mapping mémorisé) :
# ensuite, l'utilisateur passe directement des fichiers au bouton d'analyse.
premier_usage = not memo_cad and not mode_demo
_etape("2", "Vérifiez les colonnes détectées",
       "Repérées automatiquement. À confirmer une seule fois — mémorisé ensuite."
       if premier_usage else
       "Repérées automatiquement — ouvrez le panneau seulement si une colonne est mal placée.")

etiquette_colonnes = ("📋 Colonnes des fichiers — à confirmer" if premier_usage
                      else "📋 Colonnes des fichiers ✓ détectées (cliquer pour ajuster)")
with st.expander(etiquette_colonnes, expanded=premier_usage):
    st.markdown("**📒 Cadencier**")
    st.dataframe(df_cad.head(5), use_container_width=True)
    cols = list(df_cad.columns)
    # Suffixe de clé propre à CE fichier : changer de cadencier (structure
    # de colonnes différente) réinitialise tous les menus ci-dessous au
    # lieu d'hériter d'une sélection faite pour un autre fichier.
    sig_cad = _signature_colonnes(cols)

    c1, c2 = st.columns(2)
    with c1:
        cad_libelle = _choix("Libellé produit", cols,
                             _defaut(memo_cad.get("libelle"), cols, "libelle"),
                             f"cad_libelle_{sig_cad}", optionnel=False)
        cad_cip = _choix("Code CIP (recommandé)", cols,
                         _defaut(memo_cad.get("cip"), cols, "cip"),
                         f"cad_cip_{sig_cad}")
    with c2:
        cad_stock = _choix("Stock actuel", cols,
                           _defaut(memo_cad.get("stock"), cols, "stock"),
                           f"cad_stock_{sig_cad}", optionnel=False)
        cad_cond = _choix("Conditionnement (facultatif)", cols,
                          _defaut(memo_cad.get("conditionnement"), cols,
                                  "conditionnement"), f"cad_cond_{sig_cad}")

    st.markdown("**Période de ventes prise en compte**")
    # Le choix ne porte QUE sur des colonnes reconnues comme des ventes —
    # jamais le libellé produit ou une autre colonne par erreur (ancien bug :
    # une sélection mémorisée pour un autre fichier pouvait laisser une
    # colonne texte comme « Produit » cochée parmi les ventes).
    candidats_ventes = [c for c in commun.detecter_colonnes_ventes(cols) if c in cols]
    memo_ventes = [c for c in (memo_cad.get("ventes") or []) if c in candidats_ventes]
    MODE_TOUT = "Tout l'historique détecté (recommandé)"
    MODE_PERIODE = "Choisir une période précise"
    index_mode = 1 if (memo_ventes and memo_ventes != candidats_ventes) else 0
    mode_ventes = st.radio(
        "Mois à inclure dans le calcul de consommation", [MODE_TOUT, MODE_PERIODE],
        index=index_mode, horizontal=True, key=f"mode_ventes_{sig_cad}",
        help="« Tout l'historique » utilise les mois détectés automatiquement "
             "(recommandé — plus de recul, calcul plus fiable). « Choisir une "
             "période » restreint le calcul à une plage de mois consécutifs, "
             "par exemple pour ignorer une période non représentative.")
    if not candidats_ventes:
        cad_ventes = []
        st.warning("Aucune colonne de ventes mensuelles détectée "
                   "automatiquement dans ce fichier.")
    elif mode_ventes == MODE_TOUT:
        cad_ventes = candidats_ventes
        st.caption(f"✓ {len(candidats_ventes)} mois détectés, de "
                   f"« {candidats_ventes[0]} » à « {candidats_ventes[-1]} ».")
    else:
        depart = (memo_ventes[0] if memo_ventes and memo_ventes[0] in candidats_ventes
                 else candidats_ventes[0])
        fin = (memo_ventes[-1] if memo_ventes and memo_ventes[-1] in candidats_ventes
              else candidats_ventes[-1])
        cd1, cd2 = st.columns(2)
        with cd1:
            debut = st.selectbox("Du mois", candidats_ventes,
                                 index=candidats_ventes.index(depart),
                                 key=f"cad_ventes_debut_{sig_cad}")
        with cd2:
            fin = st.selectbox("Au mois", candidats_ventes,
                               index=candidats_ventes.index(fin),
                               key=f"cad_ventes_fin_{sig_cad}")
        i_debut, i_fin = sorted([candidats_ventes.index(debut),
                                 candidats_ventes.index(fin)])
        cad_ventes = candidats_ventes[i_debut:i_fin + 1]
        st.caption(f"{len(cad_ventes)} mois retenus, de « {cad_ventes[0]} » "
                   f"à « {cad_ventes[-1]} ».")

    c4, c5 = st.columns(2)
    with c4:
        cad_en_cours = _choix(
            "Commande en cours (facultatif)", cols,
            _defaut(memo_cad.get("commande_en_cours"), cols, "commande_en_cours"),
            f"cad_en_cours_{sig_cad}")
        st.caption("Colonne indiquant les boîtes déjà commandées au "
                   "fournisseur mais pas encore livrées — déduite du calcul "
                   "pour éviter de recommander ce qui arrive déjà. Un export "
                   "WinPharma standard ne contient généralement PAS cette "
                   "information : laisser sur « (aucune) » est normal, le "
                   "calcul fonctionne très bien sans.")
    with c5:
        cad_peremption = _choix(
            "Péremption / DLUO (facultatif)", cols,
            _defaut(memo_cad.get("peremption"), cols, "peremption"),
            f"cad_peremption_{sig_cad}")
        st.caption("Alerte si péremption dans moins de 90 jours — "
                   "n'écarte pas le produit, informatif seulement.")

    gpnc_date = None
    if ruptures_disponibles:
        st.divider()
        st.markdown("**🔴 Ruptures GPNC**")
        st.dataframe(df_gpnc.head(5), use_container_width=True)
        cols = list(df_gpnc.columns)
        sig_gpnc = _signature_colonnes(cols)
        c1, c2, c3 = st.columns(3)
        with c1:
            gpnc_libelle = _choix("Libellé produit", cols,
                                  _defaut(memo_gpnc.get("libelle"), cols,
                                          "libelle"),
                                  f"gpnc_libelle_{sig_gpnc}", optionnel=False)
        with c2:
            gpnc_cip = _choix("Code CIP (recommandé)", cols,
                              _defaut(memo_gpnc.get("cip"), cols, "cip"),
                              f"gpnc_cip_{sig_gpnc}")
        with c3:
            gpnc_date = _choix("Date de réappro", cols,
                               _defaut(memo_gpnc.get("date_reappro"), cols,
                                       "date_reappro"), f"gpnc_date_{sig_gpnc}")

        st.divider()
        st.markdown("**🟠 Ruptures UNIPHARMA**")
        st.dataframe(df_uni.head(5), use_container_width=True)
        cols = list(df_uni.columns)
        sig_uni = _signature_colonnes(cols)
        c1, c2 = st.columns(2)
        with c1:
            uni_libelle = _choix("Libellé produit", cols,
                                 _defaut(memo_uni.get("libelle"), cols,
                                         "libelle"),
                                 f"uni_libelle_{sig_uni}", optionnel=False)
        with c2:
            uni_cip = _choix("Code CIP (recommandé)", cols,
                             _defaut(memo_uni.get("cip"), cols, "cip"),
                             f"uni_cip_{sig_uni}")

mapping_cadencier = {"libelle": cad_libelle, "cip": cad_cip,
                     "stock": cad_stock, "ventes": cad_ventes,
                     "conditionnement": cad_cond,
                     "commande_en_cours": cad_en_cours,
                     "peremption": cad_peremption}

problemes_stock = []
if not cad_ventes:
    problemes_stock.append(
        "Cadencier : sélectionnez au moins une colonne de ventes pour "
        "calculer la consommation.")

mapping_gpnc = mapping_uni = None
if ruptures_disponibles:
    mapping_gpnc = {"libelle": gpnc_libelle, "cip": gpnc_cip,
                    "date_reappro": gpnc_date}
    mapping_uni = {"libelle": uni_libelle, "cip": uni_cip}
    if not gpnc_date:
        st.warning("Ruptures GPNC : aucune colonne de date de réappro "
                   "choisie — tous les produits seront traités avec "
                   "l'objectif 30 jours.")
else:
    st.caption("💡 Ajoutez les fichiers **Ruptures GPNC** et **UNIPHARMA** "
               "pour activer aussi la Gestion des ruptures.")

for p in problemes_stock:
    st.error(p)

# ---------------------------------------------------------------------------
# Étape 3 — lancement des analyses (2 modules INDÉPENDANTS)
# ---------------------------------------------------------------------------

st.divider()
_etape("3", "Lancez l'analyse",
       "Un clic → les résultats et le fichier Excel de commande s'affichent en dessous.")
if st.button("🔍 Lancer l'analyse", type="primary",
             disabled=bool(problemes_stock), use_container_width=True):
    config_a_sauver = {
        "cadencier": mapping_cadencier,
        "stock_rotation": {"periode": periode_rotation,
                           "couverture_min": couverture_min,
                           "couverture_max": couverture_max,
                           "seuil_alerte": seuil_alerte_unites,
                           "rotation_min_commande": rotation_min_commande,
                           "conso_defaut": conso_defaut,
                           "seuil_dormant": seuil_dormant},
    }
    if mapping_gpnc:
        config_a_sauver["gpnc"] = mapping_gpnc
        config_a_sauver["unipharma"] = mapping_uni
    if not mode_demo:  # le mapping démo ne doit pas écraser le vrai mémo
        sauver_config(config_a_sauver)

    # --- Module 1 : Gestion des stocks en rotation (toujours calculable) ---
    try:
        params_stock = stock_rotation.ParametresStockRotation(
            couverture_min_jours=couverture_min,
            couverture_max_jours=couverture_max,
            seuil_alerte_unites=seuil_alerte_unites,
            periode_rotation=periode_rotation,
            corriger_ruptures_passees=corriger_zeros_stock,
            consommation_defaut_mensuelle=conso_defaut,
            seuil_dormant_jours=seuil_dormant,
            rotation_min_commande_mensuelle=rotation_min_commande)
        resultat_stock_obj = stock_rotation.analyser_stock_rotation(
            df_cad, {"cadencier": mapping_cadencier}, params_stock,
            date_analyse=date_analyse)
        # Cadencier n+1 : marque les lignes dont le stock min/max a bougé de
        # ≥ 10 % depuis la dernière analyse, puis mémorise l'état courant.
        # (Pas en démo : ne pas polluer la référence réelle.)
        if not mode_demo:
            etat_precedent, signature_prec = charger_etat_stock()
            signature_cadencier = _signature_colonnes(df_cad.columns)
            # La règle « ne pas ressortir les stocks inchangés » ne vaut que
            # si le DOCUMENT DE BASE est le même : si le cadencier a changé de
            # structure (colonnes différentes), la comparaison n'a pas de sens
            # → on repart de zéro (toutes les lignes ressortent).
            document_different = (not etat_precedent.empty
                                  and signature_prec != signature_cadencier)
            reference = (pd.DataFrame(columns=stock_rotation.COLONNES_ETAT_STOCK)
                         if document_different else etat_precedent)
            tab, nb_mod, nb_nouv = stock_rotation.comparer_a_etat_precedent(
                resultat_stock_obj.tableau, reference)
            resultat_stock_obj.tableau = tab
            resultat_stock_obj.resume["nb_modifiees"] = nb_mod
            resultat_stock_obj.resume["nb_nouvelles"] = nb_nouv
            resultat_stock_obj.resume["etat_precedent_existant"] = (
                not reference.empty)
            resultat_stock_obj.resume["document_different"] = document_different
            sauver_etat_stock(tab, signature_cadencier)
        st.session_state["resultat_stock"] = resultat_stock_obj
    except Exception as e:  # jamais de plantage brut à l'écran
        st.error(f"Erreur — Gestion des stocks en rotation : {e}")

    # --- Module 2 : Gestion des ruptures (si les 2 fichiers fournisseurs) --
    if mapping_gpnc:
        try:
            mapping = {"cadencier": mapping_cadencier, "gpnc": mapping_gpnc,
                      "unipharma": mapping_uni}
            resultat = moteur.analyser(
                df_cad, df_gpnc, df_uni, mapping, date_analyse, periode,
                historique=None if mode_demo else charger_historique(),
                seuil_vigilance_jours=seuil_vigilance,
                rotation_min_vigilance=rotation_min_vigilance,
                seuil_marge_jours=seuil_marge,
                delai_livraison_jours=delai_livraison,
                rotation_prudente=rotation_prudente,
                corriger_ruptures_passees=corriger_zeros,
                politique_abc=politique_abc)
            st.session_state["resultat"] = resultat
            if not mode_demo:  # ne pas polluer l'historique avec la démo
                st.session_state["historique"] = sauver_historique_analyse(
                    resultat, date_analyse)
        except KeyError as e:
            st.error(f"Colonne introuvable : {e} — vérifiez le mapping.")
        except Exception as e:
            st.error(f"Erreur — Gestion des ruptures : {e}")
    st.session_state["date_analyse"] = date_analyse
    st.session_state["version_resultats"] = VERSION_APP  # cf. garde anti-stale
    st.rerun()  # rafraîchit la coche « Analyse lancée » de la barre latérale

# ---------------------------------------------------------------------------
# Étape 4 — résultats, un onglet principal par module fonctionnel
# ---------------------------------------------------------------------------

# Écarte un résultat calculé par une version ANTÉRIEURE resté en mémoire de
# session après une mise à jour (structure de colonnes différente → plantages
# type KeyError). On invite alors simplement à relancer l'analyse.
if st.session_state.get("version_resultats") not in (None, VERSION_APP):
    for _cle in ("resultat", "resultat_stock", "historique"):
        st.session_state.pop(_cle, None)
    st.session_state.pop("version_resultats", None)
    st.info("🔄 L'application a été mise à jour — relancez l'analyse pour "
            "afficher les résultats à jour.")
    st.stop()

resultat_stock = st.session_state.get("resultat_stock")
resultat = st.session_state.get("resultat")
if resultat_stock is None and resultat is None:
    st.stop()

historique = st.session_state.get("historique", charger_historique())
# Toujours présente après une analyse ; repli sur la date de la barre
# latérale si la session a été restaurée partiellement.
date_analyse_resultats = st.session_state.get("date_analyse", date_analyse)

st.divider()
st.subheader("📊 Résultats")

_MIME_XLSX = ("application/vnd.openxmlformats-officedocument."
              "spreadsheetml.sheet")
_MIME_CSV = "text/csv"
# Accès direct aux fichiers Excel sans fouiller les onglets. Conteneur
# rempli EN FIN de script : l'export des ruptures doit refléter les cases
# cochées dans l'éditeur de commande, connu seulement après son rendu.
zone_exports = st.container()
excel_stock = excel_ruptures = None

module_stock, module_ruptures = st.tabs([
    "📦 Gestion des stocks en rotation",
    "🚨 Gestion des ruptures",
])

# ===========================================================================
# MODULE 1 — GESTION DES STOCKS EN ROTATION (stock_rotation.py)
# ===========================================================================
with module_stock:
    if resultat_stock is None:
        st.info("Relancez l'analyse pour calculer le stock min / max.")
    else:
        rs = resultat_stock.resume
        st.markdown('<div class="kpi-row">' + "".join([
            _tuile_kpi("Produits pilotés", rs.get("total_produits", 0),
                       sous=f'A : {rs.get("nb_a", 0)} · B : {rs.get("nb_b", 0)} '
                            f'· C : {rs.get("nb_c", 0)}'),
            _tuile_kpi("🔴 Action requise (< seuil)",
                       rs.get("action_requise", 0), "critical",
                       sous=f"stock sous {seuil_alerte_unites:g} unités"),
            _tuile_kpi("🟡 Sous le stock min", rs.get("sous_le_min", 0),
                       "warning", sous="réassort progressif conseillé"),
            _tuile_kpi("Qté totale à commander",
                       rs.get("qte_totale_a_commander", 0), "accent",
                       sous="hors rotation faible écartée"),
            _tuile_kpi("⚪ Rotation faible", rs.get("rotation_faible", 0),
                       sous="écartés du réassort auto"),
            _tuile_kpi("💤 Stock dormant", rs.get("dormants", 0), "warning",
                       sous=f'{rs.get("dormants_boites", 0):g} unités '
                            "immobilisées"),
        ]) + "</div>", unsafe_allow_html=True)

        doublons = rs.get("doublons_fusionnes", 0)
        if doublons:
            st.caption(f"🔁 {doublons} ligne(s) en double fusionnée(s) : même "
                       "produit sous deux codes CIP (changement de générique "
                       "ou de fournisseur) — stock et ventes additionnés, "
                       "code le plus récent conservé.")
        jours_we = rs.get("jours_weekend", 0)
        if jours_we:
            st.info(f"📅 **Ajustement week-end actif** : analyse d'un "
                    f"{'vendredi' if jours_we == 2 else 'samedi'} — pas de "
                    "réception de commandes samedi/dimanche, le stock min "
                    f"du jour couvre **+{jours_we} jour(s)** de consommation.")
        st.markdown("**Stock min / max par produit** — calculé uniquement à "
                    "partir du cadencier (aucun lien avec les fichiers de "
                    "ruptures fournisseurs).")

        # Cadencier n+1 : par défaut, on ne ressort que les lignes dont le
        # stock min/max a changé de ≥ 10 % depuis la dernière analyse (évite
        # de relire les mêmes lignes). Case pour tout réafficher.
        base_stock = resultat_stock.tableau
        seulement_modifiees = False
        if rs.get("document_different"):
            st.warning("📄 Le cadencier déposé a une **structure différente** "
                       "de la dernière analyse (colonnes de ventes changées) — "
                       "toutes les lignes sont affichées, la comparaison aux "
                       "stocks précédents ne s'applique pas.")
        if ("_modifie" in base_stock.columns
                and rs.get("etat_precedent_existant")):
            nb_mod = int(rs.get("nb_modifiees", 0))
            nb_nouv = int(rs.get("nb_nouvelles", 0))
            st.info(f"🔁 **{nb_mod} ligne(s) modifiée(s)** depuis la dernière "
                    f"analyse (dont {nb_nouv} nouvelle(s)) — variation du "
                    "stock min/max ≥ 10 %. Les lignes inchangées sont "
                    "masquées pour ne pas relire les mêmes produits.")
            voir_tout = st.checkbox(
                "Afficher aussi les lignes inchangées", value=False,
                key="voir_tout_stock")
            seulement_modifiees = not voir_tout
        if seulement_modifiees:
            base_stock = base_stock[base_stock["_modifie"]]

        # Recherche + filtre : trouver un produit sans faire défiler 3 500
        # lignes. Les colonnes d'analyse ne s'affichent qu'à la demande.
        c_rech, c_alerte, c_detail = st.columns([3, 2, 2])
        with c_rech:
            recherche = st.text_input(
                "🔎 Rechercher (nom ou code CIP)", key="recherche_stock",
                placeholder="ex. DOLIPRANE ou 3400930…")
        with c_alerte:
            filtre_alerte = st.selectbox(
                "Filtrer par alerte",
                ["Toutes", "🔴 Action requise", "🟡 Sous le min", "🟢 OK",
                 "⚪ Rotation faible"],
                key="filtre_alerte_stock")
        with c_detail:
            st.write("")
            st.write("")
            detail_complet = st.checkbox(
                "＋ Colonnes d'analyse", key="detail_stock",
                help="Ajoute Stock actuel, Qté à commander, classe ABC, "
                     "consommation, tendance, variabilité, cible de réassort "
                     "et motif.")

        tableau_stock = base_stock
        tableau_stock = ui_commun.filtrer_stock(tableau_stock, recherche,
                                                filtre_alerte)
        tableau_stock = tableau_stock[
            ui_commun.colonnes_stock_affichees(tableau_stock, detail_complet)]
        st.caption(f"{len(tableau_stock)} produit(s) affiché(s) — les "
                   "stocks sont en boîtes entières. Document de base centré "
                   "sur le stock min/max ; **Stock actuel** et **Qté à "
                   "commander** apparaissent via « ＋ Colonnes d'analyse ». "
                   "« Stock min conseillé (variabilité) » est indicative "
                   "(marge pour les ventes irrégulières).")
        st.dataframe(tableau_stock, use_container_width=True,
                     hide_index=True, height=560)
        st.caption(
            f"Méthode : Stock min = consommation/j × {couverture_min:g} j "
            "(point de commande, +2 j le vendredi / +1 j le samedi car pas "
            "de réception le week-end) ; Stock max = consommation/j × "
            f"{couverture_max:g} j (plafond). **Règle des "
            f"{seuil_alerte_unites:g} unités** : sous ce seuil, la cible "
            "passe directement au stock max (commande immédiate), sans "
            "recomplètement progressif jusqu'au seul stock min.")

        st.markdown(f"**💤 Stock dormant ({len(resultat_stock.dormants)})**")
        _onglet_simple(
            resultat_stock.dormants,
            "Aucun stock dormant : toutes les couvertures sont raisonnables.",
            "Couverture très supérieure au stock max — trésorerie "
            "immobilisée. Envisager retour fournisseur ou arrêt de réassort.")

        # L'export reflète le mode d'affichage : en cadencier n+1, le
        # document ne contient que les lignes modifiées (≥ 10 %).
        resultat_pour_export = resultat_stock
        if seulement_modifiees:
            resultat_pour_export = dataclasses.replace(
                resultat_stock,
                tableau=resultat_stock.tableau[resultat_stock.tableau["_modifie"]])
        excel_stock = _excel_stock_cache(resultat_pour_export.tableau,
                                         resultat_pour_export.dormants)
        nom_excel_stock = commun.nom_fichier_export(
            "stock_rotation", date_analyse_resultats)
        c_xlsx, c_csv = st.columns([3, 1])
        c_xlsx.download_button(
            "⬇️ Télécharger l'Excel du stock en rotation",
            data=excel_stock, file_name=nom_excel_stock, mime=_MIME_XLSX,
            type="primary", use_container_width=True, key="dl_stock_onglet")
        c_csv.download_button(
            "📄 CSV",
            data=ui_commun.exporter_csv(resultat_pour_export.tableau),
            file_name=nom_excel_stock.replace(".xlsx", ".csv"), mime=_MIME_CSV,
            use_container_width=True, key="dl_stock_csv",
            help="Même tableau, format d'échange (s'ouvre partout).")

# ===========================================================================
# MODULE 2 — GESTION DES RUPTURES (moteur_ruptures.py)
# ===========================================================================
with module_ruptures:
    if resultat is None:
        st.info("Déposez aussi les fichiers **Ruptures GPNC** et "
                "**Ruptures UNIPHARMA**, puis relancez l'analyse pour "
                "activer ce module.")
    else:
        r = resultat.resume
        # Accès défensifs : un résultat resté en session pendant une mise à
        # jour du code peut dater d'une version sans ces champs.
        df_vigilance = getattr(resultat, "vigilance", pd.DataFrame())
        df_justesse = getattr(resultat, "ecartes_justesse", pd.DataFrame())

        st.markdown('<div class="kpi-row">' + "".join([
            _tuile_kpi("Ruptures GPNC analysées", r["analyses"],
                       sous=f'{r["vendus"]} vendus en pharmacie'),
            _tuile_kpi("À commander UNIPHARMA", r["a_commander"], "accent",
                       sous=f'🟢 {r["anticiper"]} à anticiper'),
            _tuile_kpi("🔴 Urgents", r["urgents"], "critical",
                       sous="stock épuisé ou ≤ 3 jours"),
            _tuile_kpi("🟡 Modérés", r["moderes"], "warning",
                       sous="stock 4 à 15 jours"),
            _tuile_kpi("❌ Sans solution", r["sans_solution"], "serious",
                       sous="rupture chez les deux fournisseurs"),
            _tuile_kpi("⚠️ Rotation à vérifier", r.get("rotation_douteuse", 0),
                       "warning", sous="rupture passée possible"),
            _tuile_kpi("🔭 Vigilance stock", r.get("vigilance", len(df_vigilance)),
                       "warning", sous="rupture en rayon à venir (hors GPNC)"),
        ]) + "</div>", unsafe_allow_html=True)

        # --- Suivi quotidien : quoi de neuf depuis l'analyse précédente ? --
        if not mode_demo:
            produits_jour = (list(resultat.onglet1["Produit"])
                             + list(resultat.onglet2["Produit"]))
            date_prec, nouveaux, resolus = moteur.comparer_a_analyse_precedente(
                produits_jour, historique, date_analyse_resultats)
            if date_prec is None:
                st.caption("📅 Première analyse enregistrée — le comparatif "
                           "quotidien (nouvelles ruptures / résolues) "
                           "démarrera dès la prochaine.")
            else:
                st.markdown(
                    f"**📅 Depuis l'analyse du {date_prec:%d/%m/%Y}** : "
                    f"🆕 {len(nouveaux)} nouvelle(s) rupture(s) à traiter · "
                    f"✅ {len(resolus)} sortie(s) de la liste")
                c_nouv, c_res = st.columns(2)
                if nouveaux:
                    with c_nouv, st.expander(
                            f"🆕 Nouvelles ruptures ({len(nouveaux)})"):
                        st.write("\n".join(f"- {p}" for p in nouveaux))
                if resolus:
                    with c_res, st.expander(
                            f"✅ Résolues / sorties ({len(resolus)})"):
                        st.write("\n".join(f"- {p}" for p in resolus))

        for alerte in resultat.alertes:
            st.warning(alerte)
        if resultat.matchs_incertains:
            with st.expander(f"⚠️ {len(resultat.matchs_incertains)} "
                             "correspondances incertaines à vérifier "
                             "(fuzzy matching)"):
                st.dataframe(pd.DataFrame(resultat.matchs_incertains),
                             use_container_width=True)

        onglet1, onglet2, onglet_vigilance, onglet_justesse, onglet3 = st.tabs([
            f"🛒 À commander UNIPHARMA ({len(resultat.onglet1)})",
            f"❌ Rupture GPNC + UNIPHARMA ({len(resultat.onglet2)})",
            f"🔭 Vigilance stock ({len(df_vigilance)})",
            f"⚠️ Écartés de justesse ({len(df_justesse)})",
            f"📋 Analyse complète ({len(resultat.onglet3)})",
        ])
        with onglet1:
            if resultat.onglet1.empty:
                st.info("Aucun produit à commander — tous les stocks "
                        "couvrent la réappro.")
                st.session_state["onglet1_valide"] = resultat.onglet1
            else:
                # Comparaison avec l'historique : ce produit était-il déjà
                # signalé ? (sans objet en mode démonstration)
                affichage1 = resultat.onglet1.copy()
                if not mode_demo:
                    affichage1["Déjà signalé"] = affichage1["Produit"].apply(
                        lambda p: (lambda n: f"🔁 {n} fois" if n else "🆕 nouveau")(
                            moteur.compter_occurrences_historique(
                                p, historique, date_analyse_resultats)))
                # Validation de commande DANS l'outil : cocher/décocher,
                # ajuster la quantité — l'export Excel reflète les ajustements.
                affichage1.insert(0, "✔", True)
                edite = st.data_editor(
                    affichage1,
                    column_config={
                        "✔": st.column_config.CheckboxColumn(
                            "✔", help="Décochez pour exclure de la commande"),
                        "Qté à commander (Cmd)": st.column_config.NumberColumn(
                            "Qté à commander (Cmd)", min_value=0, step=1,
                            help="Ajustable avant export"),
                    },
                    disabled=[c for c in affichage1.columns
                              if c not in ("✔", "Qté à commander (Cmd)")],
                    use_container_width=True, hide_index=True,
                    # Clé indexée sur le CONTENU : une nouvelle analyse
                    # repart d'un éditeur neuf. Avec une clé fixe, les
                    # cases décochées hier se rejouent par POSITION sur
                    # les produits d'aujourd'hui, et la commande part
                    # amputée sans que rien ne le signale.
                    key=f"editeur_onglet1_"
                        f"{ui_commun.signature_tableau(resultat.onglet1)}")
                st.caption("Trié par **score de priorité** (risque à 7 j × "
                           "poids A/B/C × fiabilité de la réappro). "
                           "Cochez/décochez et ajustez les quantités : "
                           "l'export Excel reprend vos choix.")
                st.session_state["onglet1_valide"] = (
                    edite[edite["✔"]].drop(columns=["✔"]))

            # Fiche produit : historique complet avant de valider.
            if not mode_demo and not historique.empty:
                with st.expander("🔎 Historique d'un produit (avant validation)"):
                    produit_choisi = st.selectbox(
                        "Produit", sorted(historique["Produit"].unique()),
                        key="fiche_produit")
                    fiche = (historique[historique["Produit"] == produit_choisi]
                             .sort_values("Date analyse", ascending=False))
                    st.dataframe(fiche, use_container_width=True,
                                 hide_index=True)
                    st.caption("Signalements passés, quantités commandées et "
                               "dates de réappro successivement annoncées "
                               "(type « surveillance » = écarté de justesse).")
        with onglet2:
            _onglet_simple(
                resultat.onglet2,
                "Aucun produit en rupture chez les deux fournisseurs.",
                "Pour ces produits : anticiper l'information patient et "
                "contacter GPNC pour confirmer les dates de réappro.")
        with onglet_vigilance:
            _onglet_simple(
                df_vigilance,
                "Aucune rupture en rayon à anticiper : tous les produits "
                "hors rupture GPNC ont une couverture suffisante.",
                "Produits que vous vendez, HORS liste de ruptures GPNC, "
                "dont le stock s'épuise : commander chez GPNC (circuit "
                "normal) avant la rupture en rayon.")
        with onglet_justesse:
            _onglet_simple(
                df_justesse,
                "Aucun produit écarté de justesse : les produits écartés "
                "ont tous une marge confortable.",
                "Écartés par la règle stricte (le stock couvre la réappro) "
                "mais avec très peu de marge : si la date de réappro "
                "glisse, c'est la rupture sèche. À surveiller.")
        with onglet3:
            _onglet_simple(
                resultat.onglet3,
                "Aucune rupture GPNC analysée.",
                "Traçabilité : tous les produits en rupture GPNC, avec le "
                "détail du calcul et le motif de la décision.")

        # L'export reflète les validations/ajustements faits dans l'onglet 1.
        onglet1_valide = st.session_state.get("onglet1_valide", resultat.onglet1)
        if "Déjà signalé" in getattr(onglet1_valide, "columns", []):
            onglet1_valide = onglet1_valide.drop(columns=["Déjà signalé"])
        nb_exclus = len(resultat.onglet1) - len(onglet1_valide)
        excel_ruptures = _excel_ruptures_cache(
            onglet1_valide, resultat.onglet2, resultat.onglet3,
            df_vigilance, df_justesse)
        nom_excel_ruptures = moteur.nom_fichier_sortie(date_analyse_resultats)
        libelle_ruptures = ("⬇️ Télécharger le fichier Excel des ruptures"
                            + (f" ({nb_exclus} produit(s) décoché(s))"
                               if nb_exclus else ""))
        c_xlsx_r, c_csv_r = st.columns([3, 1])
        c_xlsx_r.download_button(
            libelle_ruptures, data=excel_ruptures,
            file_name=nom_excel_ruptures, mime=_MIME_XLSX,
            type="primary", use_container_width=True, key="dl_ruptures_onglet")
        c_csv_r.download_button(
            "📄 CSV", data=ui_commun.exporter_csv(onglet1_valide),
            file_name=nom_excel_ruptures.replace(".xlsx", ".csv"),
            mime=_MIME_CSV, use_container_width=True, key="dl_ruptures_csv",
            help="La commande UNIPHARMA seule, en format d'échange.")

# ---------------------------------------------------------------------------
# Accès direct aux exports, affiché SOUS l'en-tête Résultats (conteneur
# réservé plus haut) — le fichier de commande en un clic, sans chercher.
# ---------------------------------------------------------------------------
with zone_exports:
    if excel_stock is not None or excel_ruptures is not None:
        c1, c2 = st.columns(2)
        if excel_stock is not None:
            with c1:
                st.download_button(
                    "⬇️ 📦 Excel — stock en rotation", data=excel_stock,
                    file_name=nom_excel_stock, mime=_MIME_XLSX,
                    use_container_width=True, key="dl_stock_haut")
        if excel_ruptures is not None:
            with c2:
                st.download_button(
                    "⬇️ 🚨 Excel — commande ruptures", data=excel_ruptures,
                    file_name=nom_excel_ruptures, mime=_MIME_XLSX,
                    use_container_width=True, key="dl_ruptures_haut")
        st.write("")
