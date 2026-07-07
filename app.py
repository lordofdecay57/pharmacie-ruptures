# -*- coding: utf-8 -*-
"""Interface Streamlit — Gestion des ruptures de stock (pharmacie).

Couche interface UNIQUEMENT : toute la logique métier vit dans
moteur_ruptures.py. Lancement : ``streamlit run app.py`` (ou double-clic sur
lancer.bat / lancer.command).

Parcours (suivi dans la barre latérale) :
  1. Déposer les 3 fichiers (cadencier, ruptures GPNC, ruptures UNIPHARMA)
     — ou cliquer « Essayer avec des données de démonstration ».
  2. Confirmer / corriger le mapping des colonnes (proposé automatiquement,
     mémorisé dans config.yaml pour les fois suivantes).
  3. Choisir la date d'analyse et la période de rotation (barre latérale),
     lancer l'analyse.
  4. Consulter les tuiles de synthèse + les 3 onglets, télécharger l'Excel.
"""

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

import moteur_ruptures as moteur

CONFIG_PATH = Path(__file__).parent / "config.yaml"
HISTORIQUE_PATH = Path(__file__).parent / "historique_commandes.csv"
COLONNES_HISTORIQUE = ["Date analyse", "Produit", "Urgence",
                       "Qté à commander (Cmd)"]

st.set_page_config(page_title="Ruptures pharmacie", page_icon="💊",
                   layout="wide", initial_sidebar_state="expanded")

# ---------------------------------------------------------------------------
# Habillage (bandeau, tuiles KPI) — l'urgence est TOUJOURS icône + libellé,
# la couleur n'est qu'un renfort (accessibilité daltonisme / impression N&B).
# ---------------------------------------------------------------------------

st.markdown("""
<style>
.hero {
  background: linear-gradient(120deg, #0f766e, #0d9488);
  border-radius: 14px; padding: 22px 26px; color: #ffffff;
}
.hero h1 { color: #ffffff; font-size: 1.55rem; margin: 0 0 6px 0; padding: 0; }
.hero p  { color: rgba(255,255,255,.88); margin: 0; font-size: .95rem; }
.hero .badge { display: inline-block; background: rgba(255,255,255,.16);
  border-radius: 999px; padding: 3px 14px; font-size: .8rem; margin-top: 12px; }

.kpi-row { display: flex; gap: 12px; flex-wrap: wrap; margin: 6px 0 12px 0; }
.kpi { flex: 1 1 160px; background: #ffffff; border: 1px solid rgba(11,11,11,.10);
  border-radius: 12px; padding: 12px 16px 10px; border-top: 3px solid #e1e0d9; }
.kpi .label { font-size: .78rem; color: #52514e; }
.kpi .value { font-size: 1.85rem; font-weight: 700; color: #0b0b0b; line-height: 1.2; }
.kpi .sub   { font-size: .74rem; color: #898781; }
.kpi.accent   { border-top-color: #0f766e; }
.kpi.critical { border-top-color: #d03b3b; }
.kpi.warning  { border-top-color: #fab219; }
.kpi.serious  { border-top-color: #ec835a; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero">
  <h1>💊 Gestion des ruptures de stock</h1>
  <p>Croise le cadencier avec les ruptures GPNC (fournisseur principal) et
  UNIPHARMA (dépannage) → fichier Excel de commande. Règle stricte : un
  produit dont le stock tient jusqu'à la réappro n'apparaît pas.</p>
  <span class="badge">🔒 Application 100 % locale — vos données ne quittent pas ce poste</span>
</div>
""", unsafe_allow_html=True)
st.write("")


def _tuile_kpi(label: str, valeur, variante: str = "", sous: str = "") -> str:
    """Tuile de synthèse : libellé discret, valeur en encre noire."""
    sous_html = f'<div class="sub">{sous}</div>' if sous else ""
    return (f'<div class="kpi {variante}"><div class="label">{label}</div>'
            f'<div class="value">{valeur}</div>{sous_html}</div>')


# ---------------------------------------------------------------------------
# Config (mémorisation du mapping des colonnes)
# ---------------------------------------------------------------------------


def charger_config() -> dict:
    """Mapping mémorisé lors d'une analyse précédente (ou vide)."""
    if CONFIG_PATH.exists():
        try:
            return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            st.warning("config.yaml illisible — mapping repart de zéro.")
    return {}


def sauver_config(mapping: dict) -> None:
    """Mémorise le mapping confirmé pour ne pas le refaire chaque semaine."""
    CONFIG_PATH.write_text(
        yaml.safe_dump(mapping, allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def _choix(label: str, colonnes: list, defaut, cle: str, optionnel=True):
    """Selectbox de mapping : propose ``defaut`` s'il existe encore."""
    options = (["(aucune)"] if optionnel else []) + list(colonnes)
    index = options.index(defaut) if defaut in options else 0
    valeur = st.selectbox(label, options, index=index, key=cle)
    return None if valeur == "(aucune)" else valeur


def charger_historique() -> pd.DataFrame:
    """Historique des analyses passées (comparaison semaine à semaine)."""
    if HISTORIQUE_PATH.exists():
        try:
            return pd.read_csv(HISTORIQUE_PATH)
        except (pd.errors.ParserError, pd.errors.EmptyDataError):
            return pd.DataFrame(columns=COLONNES_HISTORIQUE)
    return pd.DataFrame(columns=COLONNES_HISTORIQUE)


def sauver_historique_analyse(onglet1: pd.DataFrame, onglet2: pd.DataFrame,
                              date_analyse: date) -> pd.DataFrame:
    """Ajoute l'analyse du jour à l'historique local (remplace une éventuelle
    analyse déjà enregistrée à la même date, pour éviter les doublons en cas
    de ré-analyse). Renvoie l'historique mis à jour."""
    jour = date_analyse.strftime("%Y-%m-%d")
    lignes = []
    for df, urgence_defaut in ((onglet1, None), (onglet2, "❌ SANS SOLUTION")):
        if df.empty:
            continue
        sous = df[["Produit"]].copy()
        sous["Date analyse"] = jour
        sous["Urgence"] = df["Urgence"] if "Urgence" in df.columns else urgence_defaut
        sous["Qté à commander (Cmd)"] = (df["Qté à commander (Cmd)"]
                                         if "Qté à commander (Cmd)" in df.columns
                                         else "")
        lignes.append(sous[COLONNES_HISTORIQUE])
    historique = charger_historique()
    historique = historique[historique["Date analyse"] != jour]
    historique = pd.concat([historique] + lignes, ignore_index=True)
    historique.to_csv(HISTORIQUE_PATH, index=False)
    return historique


def _defaut(memo_valeur, colonnes: list, role: str):
    """Défaut d'un selectbox : le mémo s'il correspond encore au fichier,
    sinon la détection automatique (utile si le format du fichier change)."""
    if memo_valeur and memo_valeur in colonnes:
        return memo_valeur
    return moteur.detecter_colonne(colonnes, role)


# ---------------------------------------------------------------------------
# Données de démonstration (dates relatives à aujourd'hui → toujours valides)
# ---------------------------------------------------------------------------


def jeu_demonstration() -> dict:
    """Jeu fictif pour découvrir l'outil sans fichiers réels.

    Reprend les cas de référence (Titanoréine écartée, Ozempic modéré,
    Aranesp urgent) + rupture double, produit dormant, produit non vendu.
    """
    def dans(jours: int) -> str:
        return (date.today() + timedelta(days=jours)).strftime("%d/%m/%Y")

    cadencier = pd.DataFrame({
        "Produit": ["TITANOREINE SUPPO B/12", "OZEMPIC 1MG STYLO",
                    "ARANESP 150 SOL INJ", "DALACINE 300 GEL",
                    "PRODUIT DORMANT", "TAHOR 10MG CPR",
                    "DOLIPRANE 1000 CPR B/8", "VENTOLINE 100 SPRAY",
                    "KARDEGIC 75MG SACH", "AMOXICILLINE 1G CPR"],
        "CIP": ["1001", "1002", "1003", "1004", "1005",
                "1006", "1007", "1008", "1009", "1010"],
        "Stock": [3.6, 5, 0, 2, 4, 0, 30, 2, 50, 1],
        # Ventoline : un mois à 0 vente au milieu de mois actifs → indice de
        # rupture passée (rotation probablement sous-estimée).
        "Ventes avril": [6, 16, 4, 13, 0, 8, 60, 0, 40, 24],
        "Ventes mai":   [6, 17, 4, 13, 0, 8, 58, 9, 40, 26],
        "Ventes juin":  [6, 16.5, 4, 13, 0, 8, 62, 11, 40, 25],
        # Ventoline : 3 déjà en commande (à déduire, évite le doublon).
        "Commande en cours": [0, 0, 0, 0, 0, 0, 0, 3, 0, 0],
        # Kardegic : péremption proche (< 90 j) → alerte informative.
        "DLUO": ["", "", "", "", "", "", "", "", dans(70), ""],
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
            aide, type=["xlsx", "xls", "csv"], key=f"fichier_{cle}",
            label_visibility="collapsed")
        if fichiers[cle] is not None:
            try:
                dataframes[cle] = moteur.charger_fichier(
                    fichiers[cle].getvalue(), fichiers[cle].name)
                st.success(f"{len(dataframes[cle])} lignes · "
                           f"{len(dataframes[cle].columns)} colonnes")
            except ValueError as e:
                st.error(str(e))

# Mode démonstration : remplace les fichiers manquants par le jeu fictif.
mode_demo = st.session_state.get("mode_demo", False) and len(dataframes) < 3
if mode_demo:
    dataframes = jeu_demonstration()
    st.info("🧪 **Mode démonstration** — données fictives (les cas de "
            "référence : Titanoréine, Ozempic, Aranesp…). Déposez vos vrais "
            "fichiers ci-dessus pour repasser en mode normal.")

# ---------------------------------------------------------------------------
# Barre latérale — progression, paramètres, remise à zéro
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## 💊 Ruptures pharmacie")
    st.caption("Pilotage hebdomadaire des ruptures GPNC / UNIPHARMA.")

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
    st.markdown("#### ⚙️ Paramètres")
    date_analyse = st.date_input("📅 Date d'analyse", value=date.today(),
                                 format="DD/MM/YYYY")
    periode = st.radio(
        "Période de calcul de la rotation",
        ["annuelle", "3mois"],
        format_func=lambda p: ("Annuelle (moyenne 12 mois)" if p == "annuelle"
                               else "3 derniers mois"))

    st.divider()
    if st.button("🔄 Nouvelle analyse", use_container_width=True):
        for cle in ("resultat", "date_analyse", "mode_demo"):
            st.session_state.pop(cle, None)
        st.rerun()
    st.caption("🔒 100 % local : vos fichiers ne quittent pas ce poste. "
               "Le mapping des colonnes est mémorisé dans config.yaml.")

if len(dataframes) < 3:
    st.info("Déposez les **3 fichiers** ci-dessus pour continuer — ou "
            "découvrez l'outil avec des données fictives :")
    if st.button("🧪 Essayer avec des données de démonstration"):
        st.session_state["mode_demo"] = True
        st.rerun()
    st.stop()

# ---------------------------------------------------------------------------
# Étape 2 — validation du mapping des colonnes (aperçu + menus déroulants)
# ---------------------------------------------------------------------------

st.divider()
st.subheader("🧭 Vérification des colonnes")
st.caption("Les colonnes sont détectées automatiquement — confirmez ou "
           "corrigez, le choix est mémorisé pour les prochaines analyses.")

df_cad, df_gpnc, df_uni = (dataframes["cadencier"], dataframes["gpnc"],
                           dataframes["unipharma"])
memo = config if isinstance(config, dict) else {}
memo_cad = memo.get("cadencier", {})
memo_gpnc = memo.get("gpnc", {})
memo_uni = memo.get("unipharma", {})

with st.expander("📒 Cadencier — colonnes",
                 expanded=not memo_cad and not mode_demo):
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
            c for c in moteur.detecter_colonnes_ventes(cols) if c in cols]
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

with st.expander("🔴 Ruptures GPNC — colonnes",
                 expanded=not memo_gpnc and not mode_demo):
    st.dataframe(df_gpnc.head(5), use_container_width=True)
    cols = list(df_gpnc.columns)
    c1, c2, c3 = st.columns(3)
    with c1:
        gpnc_libelle = _choix("Libellé produit", cols,
                              _defaut(memo_gpnc.get("libelle"), cols, "libelle"),
                              "gpnc_libelle", optionnel=False)
    with c2:
        gpnc_cip = _choix("Code CIP (recommandé)", cols,
                          _defaut(memo_gpnc.get("cip"), cols, "cip"), "gpnc_cip")
    with c3:
        gpnc_date = _choix("Date de réappro", cols,
                           _defaut(memo_gpnc.get("date_reappro"), cols,
                                   "date_reappro"), "gpnc_date")

with st.expander("🟠 Ruptures UNIPHARMA — colonnes",
                 expanded=not memo_uni and not mode_demo):
    st.dataframe(df_uni.head(5), use_container_width=True)
    cols = list(df_uni.columns)
    c1, c2 = st.columns(2)
    with c1:
        uni_libelle = _choix("Libellé produit", cols,
                             _defaut(memo_uni.get("libelle"), cols, "libelle"),
                             "uni_libelle", optionnel=False)
    with c2:
        uni_cip = _choix("Code CIP (recommandé)", cols,
                         _defaut(memo_uni.get("cip"), cols, "cip"), "uni_cip")

# Contrôles bloquants AVANT de proposer l'analyse (messages clairs).
problemes = []
if not cad_ventes:
    problemes.append("Cadencier : sélectionnez au moins une colonne de ventes.")
if not gpnc_date:
    st.warning("Ruptures GPNC : aucune colonne de date de réappro choisie — "
               "tous les produits seront traités avec l'objectif 30 jours.")
for p in problemes:
    st.error(p)

# ---------------------------------------------------------------------------
# Étape 3 — lancement de l'analyse
# ---------------------------------------------------------------------------

st.divider()
if st.button("🔍 Lancer l'analyse", type="primary", disabled=bool(problemes),
             use_container_width=True):
    mapping = {
        "cadencier": {"libelle": cad_libelle, "cip": cad_cip,
                      "stock": cad_stock, "ventes": cad_ventes,
                      "conditionnement": cad_cond,
                      "commande_en_cours": cad_en_cours,
                      "peremption": cad_peremption},
        "gpnc": {"libelle": gpnc_libelle, "cip": gpnc_cip,
                 "date_reappro": gpnc_date},
        "unipharma": {"libelle": uni_libelle, "cip": uni_cip},
    }
    if not mode_demo:  # le mapping démo ne doit pas écraser le vrai mémo
        sauver_config(mapping)
    try:
        resultat = moteur.analyser(
            df_cad, df_gpnc, df_uni, mapping, date_analyse, periode)
        st.session_state["resultat"] = resultat
        st.session_state["date_analyse"] = date_analyse
        if not mode_demo:  # ne pas polluer l'historique avec les données fictives
            st.session_state["historique"] = sauver_historique_analyse(
                resultat.onglet1, resultat.onglet2, date_analyse)
        st.rerun()  # rafraîchit la coche « Analyse lancée » de la barre latérale
    except KeyError as e:
        st.error(f"Colonne introuvable : {e} — vérifiez le mapping ci-dessus.")
    except Exception as e:  # jamais de plantage brut à l'écran
        st.error(f"Erreur pendant l'analyse : {e}")

# ---------------------------------------------------------------------------
# Étape 4 — résultats (tuiles de synthèse + 3 onglets + export)
# ---------------------------------------------------------------------------

resultat = st.session_state.get("resultat")
if resultat is None:
    st.stop()

r = resultat.resume
st.divider()
st.subheader("📊 Résultats")
st.markdown('<div class="kpi-row">' + "".join([
    _tuile_kpi("Ruptures GPNC analysées", r["analyses"],
               sous=f'{r["vendus"]} vendus en pharmacie'),
    _tuile_kpi("À commander UNIPHARMA", r["a_commander"], "accent",
               sous=f'🟢 {r["anticiper"]} à anticiper'),
    _tuile_kpi("🔴 Urgents", r["urgents"], "critical",
               sous="stock épuisé ou ≤ 3 jours"),
    _tuile_kpi("🟡 Modérés", r["moderes"], "warning", sous="stock 4 à 15 jours"),
    _tuile_kpi("❌ Sans solution", r["sans_solution"], "serious",
               sous="rupture chez les deux fournisseurs"),
    _tuile_kpi("⚠️ Rotation à vérifier", r["rotation_douteuse"], "warning",
               sous="rupture passée possible"),
]) + "</div>", unsafe_allow_html=True)

for alerte in resultat.alertes:
    st.warning(alerte)
if resultat.matchs_incertains:
    with st.expander(f"⚠️ {len(resultat.matchs_incertains)} correspondances "
                     "incertaines à vérifier (fuzzy matching)"):
        st.dataframe(pd.DataFrame(resultat.matchs_incertains),
                     use_container_width=True)


def _teinter_urgence(ligne):
    """Code couleur des lignes de l'onglet 1 selon l'urgence."""
    couleurs = {moteur.URGENT: "#f8cbad", moteur.MODERE: "#ffe699",
                moteur.ANTICIPER: "#c6efce"}
    fond = couleurs.get(ligne.get("Urgence"))
    style = f"background-color: {fond}; color: #1a1a1a" if fond else ""
    return [style] * len(ligne)


onglet1, onglet2, onglet3 = st.tabs([
    f"🛒 À commander UNIPHARMA ({len(resultat.onglet1)})",
    f"❌ Rupture GPNC + UNIPHARMA ({len(resultat.onglet2)})",
    f"📋 Analyse complète ({len(resultat.onglet3)})",
])
with onglet1:
    if resultat.onglet1.empty:
        st.info("Aucun produit à commander — tous les stocks couvrent la réappro.")
    else:
        # Comparaison avec l'historique : ce produit était-il déjà signalé
        # lors de précédentes analyses (hors mode démonstration) ?
        historique = st.session_state.get("historique", charger_historique())
        affichage1 = resultat.onglet1.copy()
        affichage1["Déjà signalé"] = affichage1["Produit"].apply(
            lambda p: (lambda n: f"🔁 {n} fois" if n else "")(
                moteur.compter_occurrences_historique(
                    p, historique, st.session_state["date_analyse"])))
        # ``{:g}`` : pas de décimales inutiles (0 et non 0.000000, 9.1 reste 9.1).
        st.dataframe(affichage1.style.apply(_teinter_urgence, axis=1)
                     .format(lambda v: f"{v:g}" if isinstance(v, float) else v),
                     use_container_width=True, hide_index=True)
with onglet2:
    if resultat.onglet2.empty:
        st.info("Aucun produit en rupture chez les deux fournisseurs.")
    else:
        st.dataframe(resultat.onglet2, use_container_width=True, hide_index=True)
        st.caption("Pour ces produits : anticiper l'information patient et "
                   "contacter GPNC pour confirmer les dates de réappro.")
with onglet3:
    st.dataframe(resultat.onglet3, use_container_width=True, hide_index=True)
    st.caption("Traçabilité : tous les produits en rupture GPNC, avec le "
               "détail du calcul et le motif de la décision.")

st.download_button(
    "⬇️ Télécharger le fichier Excel",
    data=moteur.exporter_excel(resultat),
    file_name=moteur.nom_fichier_sortie(st.session_state["date_analyse"]),
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary", use_container_width=True)
