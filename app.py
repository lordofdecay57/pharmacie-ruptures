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
import moteur_ruptures as moteur
import stock_rotation

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
VERSION_APP = "2.2"

CONFIG_PATH = Path(__file__).parent / "config.yaml"
HISTORIQUE_PATH = Path(__file__).parent / "historique_commandes.csv"
COLONNES_HISTORIQUE = ["Date analyse", "Produit", "Urgence",
                       "Qté à commander (Cmd)", "Date réappro", "Type"]
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
.hero {
  background: linear-gradient(120deg, #0f766e, #0d9488);
  border-radius: 14px; padding: 22px 26px; color: #ffffff;
}
.hero h1 { color: #ffffff; font-size: 1.55rem; margin: 0 0 6px 0; padding: 0; }
.hero .version { font-size: .82rem; font-weight: 600; vertical-align: middle;
  background: rgba(255,255,255,.22); border-radius: 999px; padding: 2px 10px;
  margin-left: 8px; letter-spacing: .3px; }
.hero p  { color: rgba(255,255,255,.88); margin: 0; font-size: .95rem; }
.hero .badge { display: inline-block; background: rgba(255,255,255,.16);
  border-radius: 999px; padding: 3px 14px; font-size: .8rem; margin-top: 12px; }

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

st.markdown(f"""
<div class="hero">
  <h1>💊 Pilotage pharmacie — stock &amp; ruptures
    <span class="version">v{VERSION_APP}</span></h1>
  <p>Deux modules indépendants à partir des mêmes fichiers : le <b>stock en
  rotation</b> (stock min/max par produit) et les <b>ruptures fournisseurs</b>
  (GPNC/UNIPHARMA → fichier Excel de commande).</p>
  <span class="badge">🔒 Application 100 % locale — vos données ne quittent pas ce poste</span>
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
# Config (mémorisation du mapping des colonnes + des réglages des 2 modules)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _charger_fichier_cache(data: bytes, nom: str) -> pd.DataFrame:
    """Cache du parsing : un cadencier PDF de ~200 pages prend ~1 min à
    lire — sans cache, Streamlit le relirait à CHAQUE clic dans la page."""
    return commun.charger_fichier(data, nom)


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
    jour = date_analyse.strftime("%Y-%m-%d")
    lignes = []
    sources = ((resultat.onglet1, None, "commande"),
               (resultat.onglet2, "❌ SANS SOLUTION", "commande"),
               # Écartés de justesse : leurs dates annoncées sont mémorisées
               # pour détecter les réappros repoussées AVANT que le produit
               # ne bascule en commande.
               (resultat.ecartes_justesse, "⚠️ SURVEILLANCE", "surveillance"))
    for df, urgence_defaut, type_ligne in sources:
        if df.empty:
            continue
        sous = df[["Produit"]].copy()
        sous["Date analyse"] = jour
        sous["Urgence"] = df["Urgence"] if "Urgence" in df.columns else urgence_defaut
        sous["Qté à commander (Cmd)"] = (df["Qté à commander (Cmd)"]
                                         if "Qté à commander (Cmd)" in df.columns
                                         else "")
        # Date de réappro annoncée : mémorisée pour détecter les glissements.
        sous["Date réappro"] = (df["Date réappro GPNC"]
                                if "Date réappro GPNC" in df.columns else "")
        sous["Type"] = type_ligne
        lignes.append(sous[COLONNES_HISTORIQUE])
    historique = charger_historique()
    historique = historique[historique["Date analyse"] != jour]
    historique = pd.concat([historique] + lignes, ignore_index=True)
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

    # Tous les réglages fins tiennent dans UN panneau replié : l'écran reste
    # épuré, les valeurs par défaut conviennent à la quasi-totalité des cas.
    with st.expander("⚙️ Réglages avancés (facultatif)"):
        st.caption("Les valeurs par défaut conviennent dans la plupart des "
                   "cas — n'y touchez que si besoin.")

        st.markdown("**📦 Stock en rotation**")
        periode_rotation = st.radio(
            "Calcul de la consommation", ["annuelle", "3mois", "lissee"],
            index=["annuelle", "3mois", "lissee"].index(
                memo_rotation.get("periode", "annuelle")),
            format_func=lambda p: {
                "annuelle": "Annuelle (moyenne 12 mois)",
                "3mois": "3 derniers mois",
                "lissee": "Lissée (réactive aux tendances)"}[p],
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
            "Calcul de la rotation", ["annuelle", "3mois", "lissee"],
            format_func=lambda p: {
                "annuelle": "Annuelle (moyenne 12 mois)",
                "3mois": "3 derniers mois",
                "lissee": "Lissée (réactive aux tendances)"}[p],
            key="periode_ruptures",
            help="« Lissée » : lissage exponentiel — suit les hausses ET les "
                 "baisses récentes sans sur-réagir à un mois isolé. Attention : "
                 "un produit en rupture EN COURS (derniers mois à 0) voit sa "
                 "rotation lissée chuter — « Annuelle » reste plus robuste pour "
                 "ces cas, signalés « ⚠️ rupture passée possible ».")
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
    st.caption("🔒 100 % local : vos fichiers ne quittent pas ce poste.")

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
    c1, c2, c3 = st.columns(3)
    with c1:
        cad_libelle = _choix("Libellé produit", cols,
                             _defaut(memo_cad.get("libelle"), cols, "libelle"),
                             "cad_libelle", optionnel=False)
        cad_cip = _choix("Code CIP (recommandé)", cols,
                         _defaut(memo_cad.get("cip"), cols, "cip"), "cad_cip")
    with c2:
        cad_stock = _choix("Stock actuel", cols,
                           _defaut(memo_cad.get("stock"), cols, "stock"),
                           "cad_stock", optionnel=False)
        cad_cond = _choix("Conditionnement (facultatif)", cols,
                          _defaut(memo_cad.get("conditionnement"), cols,
                                  "conditionnement"), "cad_cond")
    with c3:
        memo_ventes = [c for c in (memo_cad.get("ventes") or []) if c in cols]
        defaut_ventes = memo_ventes or [
            c for c in commun.detecter_colonnes_ventes(cols) if c in cols]
        cad_ventes = st.multiselect(
            "Colonnes de ventes mensuelles — ordre chronologique, "
            "la plus récente en DERNIER",
            cols, default=defaut_ventes, key="cad_ventes")
    c4, c5 = st.columns(2)
    with c4:
        cad_en_cours = _choix(
            "Commande en cours (facultatif)", cols,
            _defaut(memo_cad.get("commande_en_cours"), cols, "commande_en_cours"),
            "cad_en_cours")
        st.caption("Qté déjà commandée mais pas reçue — déduite du calcul "
                   "pour éviter de recommander ce qui arrive déjà.")
    with c5:
        cad_peremption = _choix(
            "Péremption / DLUO (facultatif)", cols,
            _defaut(memo_cad.get("peremption"), cols, "peremption"),
            "cad_peremption")
        st.caption("Alerte si péremption dans moins de 90 jours — "
                   "n'écarte pas le produit, informatif seulement.")

    gpnc_date = None
    if ruptures_disponibles:
        st.divider()
        st.markdown("**🔴 Ruptures GPNC**")
        st.dataframe(df_gpnc.head(5), use_container_width=True)
        cols = list(df_gpnc.columns)
        c1, c2, c3 = st.columns(3)
        with c1:
            gpnc_libelle = _choix("Libellé produit", cols,
                                  _defaut(memo_gpnc.get("libelle"), cols,
                                          "libelle"),
                                  "gpnc_libelle", optionnel=False)
        with c2:
            gpnc_cip = _choix("Code CIP (recommandé)", cols,
                              _defaut(memo_gpnc.get("cip"), cols, "cip"),
                              "gpnc_cip")
        with c3:
            gpnc_date = _choix("Date de réappro", cols,
                               _defaut(memo_gpnc.get("date_reappro"), cols,
                                       "date_reappro"), "gpnc_date")

        st.divider()
        st.markdown("**🟠 Ruptures UNIPHARMA**")
        st.dataframe(df_uni.head(5), use_container_width=True)
        cols = list(df_uni.columns)
        c1, c2 = st.columns(2)
        with c1:
            uni_libelle = _choix("Libellé produit", cols,
                                 _defaut(memo_uni.get("libelle"), cols,
                                         "libelle"),
                                 "uni_libelle", optionnel=False)
        with c2:
            uni_cip = _choix("Code CIP (recommandé)", cols,
                             _defaut(memo_uni.get("cip"), cols, "cip"),
                             "uni_cip")

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
            seuil_dormant_jours=seuil_dormant)
        st.session_state["resultat_stock"] = stock_rotation.analyser_stock_rotation(
            df_cad, {"cadencier": mapping_cadencier}, params_stock,
            date_analyse=date_analyse)
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
    st.rerun()  # rafraîchit la coche « Analyse lancée » de la barre latérale

# ---------------------------------------------------------------------------
# Étape 4 — résultats, un onglet principal par module fonctionnel
# ---------------------------------------------------------------------------

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
                       sous="toutes lignes confondues"),
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
                ["Toutes", "🔴 Action requise", "🟡 Sous le min", "🟢 OK"],
                key="filtre_alerte_stock")
        with c_detail:
            st.write("")
            st.write("")
            detail_complet = st.checkbox(
                "＋ Colonnes d'analyse", key="detail_stock",
                help="Ajoute classe ABC, consommation, tendance, "
                     "variabilité, cible de réassort et motif.")

        tableau_stock = resultat_stock.tableau
        if recherche:
            terme = recherche.strip().upper()
            tableau_stock = tableau_stock[
                tableau_stock["Nom du produit"].astype(str).str.upper()
                .str.contains(terme, regex=False)
                | tableau_stock["Code CIP"].astype(str)
                .str.contains(terme, regex=False)]
        if filtre_alerte != "Toutes":
            tableau_stock = tableau_stock[
                tableau_stock["Alerte"] == filtre_alerte]
        if not detail_complet:  # vue simple convenue : CIP / nom / stocks
            tableau_stock = tableau_stock[
                ["Alerte", "Code CIP", "Nom du produit", "Stock actuel",
                 "Stock min (calculé)", "Stock max (calculé)",
                 "Qté à commander"]]
        st.caption(f"{len(tableau_stock)} produit(s) affiché(s) — les "
                   "stocks sont en boîtes entières.")
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

        excel_stock = stock_rotation.exporter_stock_rotation_excel(
            resultat_stock)
        nom_excel_stock = commun.nom_fichier_export(
            "stock_rotation", date_analyse_resultats)
        st.download_button(
            "⬇️ Télécharger l'Excel du stock en rotation",
            data=excel_stock, file_name=nom_excel_stock, mime=_MIME_XLSX,
            type="primary", use_container_width=True, key="dl_stock_onglet")

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
                    key="editeur_onglet1")
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
        resultat_export = dataclasses.replace(resultat, onglet1=onglet1_valide)
        nb_exclus = len(resultat.onglet1) - len(onglet1_valide)
        excel_ruptures = moteur.exporter_excel(resultat_export)
        nom_excel_ruptures = moteur.nom_fichier_sortie(date_analyse_resultats)
        libelle_ruptures = ("⬇️ Télécharger le fichier Excel des ruptures"
                            + (f" ({nb_exclus} produit(s) décoché(s))"
                               if nb_exclus else ""))
        st.download_button(
            libelle_ruptures, data=excel_ruptures,
            file_name=nom_excel_ruptures, mime=_MIME_XLSX,
            type="primary", use_container_width=True, key="dl_ruptures_onglet")

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
