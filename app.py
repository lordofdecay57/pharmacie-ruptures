# -*- coding: utf-8 -*-
"""Interface Streamlit — Gestion des ruptures de stock (pharmacie).

Couche interface UNIQUEMENT : toute la logique métier vit dans
moteur_ruptures.py. Lancement : ``streamlit run app.py`` (ou double-clic sur
lancer.bat / lancer.command).

Parcours :
  1. Déposer les 3 fichiers (cadencier, ruptures GPNC, ruptures UNIPHARMA).
  2. Confirmer / corriger le mapping des colonnes (proposé automatiquement,
     mémorisé dans config.yaml pour les fois suivantes).
  3. Choisir la date d'analyse et la période de rotation, lancer l'analyse.
  4. Consulter les 3 onglets à l'écran, télécharger l'Excel de commande.
"""

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

import moteur_ruptures as moteur

CONFIG_PATH = Path(__file__).parent / "config.yaml"

st.set_page_config(page_title="Ruptures pharmacie", page_icon="💊",
                   layout="wide")

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


# ---------------------------------------------------------------------------
# En-tête + zone d'import
# ---------------------------------------------------------------------------

st.title("💊 Gestion des ruptures de stock")
st.caption("Croise le cadencier avec les ruptures GPNC (fournisseur principal) "
           "et UNIPHARMA (dépannage) → fichier Excel de commande. "
           "Règle stricte : un produit dont le stock tient jusqu'à la réappro "
           "n'apparaît pas.")

config = charger_config()

col_fichiers = st.columns(3)
libelles_zones = [
    ("cadencier", "📒 Cadencier", "Historique des ventes + stock actuel"),
    ("gpnc", "🔴 Ruptures GPNC", "Fournisseur principal (ruptgpnc_ia)"),
    ("unipharma", "🟠 Ruptures UNIPHARMA", "Fournisseur de dépannage (ruptocdp_ia)"),
]
fichiers, dataframes, erreurs = {}, {}, []
for colonne, (cle, titre, aide) in zip(col_fichiers, libelles_zones):
    with colonne:
        st.subheader(titre)
        fichiers[cle] = st.file_uploader(
            aide, type=["xlsx", "xls", "csv"], key=f"fichier_{cle}")
        if fichiers[cle] is not None:
            try:
                dataframes[cle] = moteur.charger_fichier(
                    fichiers[cle].getvalue(), fichiers[cle].name)
                st.success(f"{len(dataframes[cle])} lignes · "
                           f"{len(dataframes[cle].columns)} colonnes")
            except ValueError as e:
                erreurs.append(f"{titre} : {e}")
                st.error(str(e))

for message in erreurs:
    st.error(message)

if len(dataframes) < 3:
    st.info("Déposez les **3 fichiers** ci-dessus pour continuer.")
    st.stop()

# ---------------------------------------------------------------------------
# Paramètres d'analyse
# ---------------------------------------------------------------------------

st.divider()
col_date, col_periode = st.columns(2)
with col_date:
    date_analyse = st.date_input("📅 Date d'analyse", value=date.today(),
                                 format="DD/MM/YYYY")
with col_periode:
    periode = st.radio(
        "Période de calcul de la rotation",
        ["annuelle", "3mois"], horizontal=True,
        format_func=lambda p: ("Annuelle (moyenne 12 mois)" if p == "annuelle"
                               else "3 derniers mois"))

# ---------------------------------------------------------------------------
# Validation du mapping des colonnes (aperçu + menus déroulants)
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

with st.expander("📒 Cadencier — colonnes", expanded=not memo_cad):
    st.dataframe(df_cad.head(5), use_container_width=True)
    cols = list(df_cad.columns)
    c1, c2, c3 = st.columns(3)
    with c1:
        cad_libelle = _choix("Libellé produit", cols,
                             memo_cad.get("libelle")
                             or moteur.detecter_colonne(cols, "libelle"),
                             "cad_libelle", optionnel=False)
        cad_cip = _choix("Code CIP (recommandé)", cols,
                         memo_cad.get("cip") or moteur.detecter_colonne(cols, "cip"),
                         "cad_cip")
    with c2:
        cad_stock = _choix("Stock actuel", cols,
                           memo_cad.get("stock")
                           or moteur.detecter_colonne(cols, "stock"),
                           "cad_stock", optionnel=False)
        cad_cond = _choix("Conditionnement (facultatif)", cols,
                          memo_cad.get("conditionnement")
                          or moteur.detecter_colonne(cols, "conditionnement"),
                          "cad_cond")
    with c3:
        defaut_ventes = [c for c in (memo_cad.get("ventes")
                                     or moteur.detecter_colonnes_ventes(cols))
                         if c in cols]
        cad_ventes = st.multiselect(
            "Colonnes de ventes mensuelles — ordre chronologique, "
            "la plus récente en DERNIER",
            cols, default=defaut_ventes, key="cad_ventes")

with st.expander("🔴 Ruptures GPNC — colonnes", expanded=not memo_gpnc):
    st.dataframe(df_gpnc.head(5), use_container_width=True)
    cols = list(df_gpnc.columns)
    c1, c2, c3 = st.columns(3)
    with c1:
        gpnc_libelle = _choix("Libellé produit", cols,
                              memo_gpnc.get("libelle")
                              or moteur.detecter_colonne(cols, "libelle"),
                              "gpnc_libelle", optionnel=False)
    with c2:
        gpnc_cip = _choix("Code CIP (recommandé)", cols,
                          memo_gpnc.get("cip")
                          or moteur.detecter_colonne(cols, "cip"), "gpnc_cip")
    with c3:
        gpnc_date = _choix("Date de réappro", cols,
                           memo_gpnc.get("date_reappro")
                           or moteur.detecter_colonne(cols, "date_reappro"),
                           "gpnc_date")

with st.expander("🟠 Ruptures UNIPHARMA — colonnes", expanded=not memo_uni):
    st.dataframe(df_uni.head(5), use_container_width=True)
    cols = list(df_uni.columns)
    c1, c2 = st.columns(2)
    with c1:
        uni_libelle = _choix("Libellé produit", cols,
                             memo_uni.get("libelle")
                             or moteur.detecter_colonne(cols, "libelle"),
                             "uni_libelle", optionnel=False)
    with c2:
        uni_cip = _choix("Code CIP (recommandé)", cols,
                         memo_uni.get("cip")
                         or moteur.detecter_colonne(cols, "cip"), "uni_cip")

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
# Lancement de l'analyse
# ---------------------------------------------------------------------------

st.divider()
if st.button("🔍 Lancer l'analyse", type="primary", disabled=bool(problemes),
             use_container_width=True):
    mapping = {
        "cadencier": {"libelle": cad_libelle, "cip": cad_cip,
                      "stock": cad_stock, "ventes": cad_ventes,
                      "conditionnement": cad_cond},
        "gpnc": {"libelle": gpnc_libelle, "cip": gpnc_cip,
                 "date_reappro": gpnc_date},
        "unipharma": {"libelle": uni_libelle, "cip": uni_cip},
    }
    sauver_config(mapping)  # mémorisé pour la semaine prochaine
    try:
        st.session_state["resultat"] = moteur.analyser(
            df_cad, df_gpnc, df_uni, mapping, date_analyse, periode)
        st.session_state["date_analyse"] = date_analyse
    except KeyError as e:
        st.error(f"Colonne introuvable : {e} — vérifiez le mapping ci-dessus.")
    except Exception as e:  # jamais de plantage brut à l'écran
        st.error(f"Erreur pendant l'analyse : {e}")

# ---------------------------------------------------------------------------
# Résultats
# ---------------------------------------------------------------------------

resultat = st.session_state.get("resultat")
if resultat is None:
    st.stop()

r = resultat.resume
st.divider()
st.subheader("📊 Résultats")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Ruptures GPNC analysées", r["analyses"])
m2.metric("Vendus en pharmacie", r["vendus"])
m3.metric("À commander UNIPHARMA", r["a_commander"])
m4.metric("Sans solution", r["sans_solution"])
m5.metric("🔴 Urgents", r["urgents"])
st.caption(f"Répartition onglet 1 : 🔴 {r['urgents']} urgents · "
           f"🟡 {r['moderes']} modérés · 🟢 {r['anticiper']} à anticiper")

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
        st.dataframe(resultat.onglet1.style.apply(_teinter_urgence, axis=1),
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
