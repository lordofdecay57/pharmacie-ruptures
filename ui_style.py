"""Habillage commun et tableaux de lecture, sans modifier les données métier."""

from html import escape as _escape

import pandas as pd
import streamlit as st


def escape(valeur: str) -> str:
    # Une ligne vide saisie dans un nom ne doit pas interrompre le bloc
    # HTML de Markdown et transformer la suite en nouveau balisage.
    return _escape(valeur).replace("\r", "&#13;").replace("\n", "&#10;")


CSS = """
<style>
:root { --ph-encre: #243a30; --ph-vert: #255e48; --ph-ligne: #dce5dc; }
[data-testid="stMainBlockContainer"] {
  max-width: 1520px; padding: 1.8rem 2.5rem 3rem;
}
[data-testid="stSidebar"] { background: #edf2e9; }
.hero { display:flex; align-items:center; gap:12px; padding:0 0 8px; flex-wrap:wrap; }
.hero h1 { color:var(--ph-encre); font-size:1.12rem; font-weight:650; padding:0; margin:0; }
.hero .marque { background:var(--ph-vert); color:white; border-radius:10px;
  width:34px; height:34px; display:grid; place-items:center; font-size:26px; }
.hero .version { color:#526657; background:#e6ede3; border-radius:6px;
  padding:3px 8px; font-size:.74rem; font-weight:600; }
.hero .maj { background:#fff1dc; color:#855015; border:1px solid #e7cb9e;
  font-size:.8rem; border-radius:7px; padding:5px 10px; }
.st-key-espace_travail { margin:0 0 14px; }
.st-key-espace_travail [data-testid="stButtonGroup"] { gap:6px; align-items:stretch; }
.st-key-espace_travail button { min-height:52px; padding:12px 16px !important;
  border-radius:10px !important; border:1px solid var(--ph-ligne) !important;
  background:#fff !important; box-shadow:none !important; }
.st-key-espace_travail button p { font-size:.96rem !important; font-weight:600;
  color:#526657 !important; }
.st-key-espace_travail button:nth-child(1) { border-color:#0d9488 !important; }
.st-key-espace_travail button[aria-checked="true"],
.st-key-espace_travail button[kind="segmented_controlActive"] {
  background:var(--ph-vert) !important; border-color:var(--ph-vert) !important; }
.st-key-espace_travail button[aria-checked="true"] p,
.st-key-espace_travail button[kind="segmented_controlActive"] p { color:#fff !important; }
.ph-entete { padding:4px 0 12px; }
.ph-entete h2 { margin:0; padding:0; font-size:2rem; line-height:1.25;
  letter-spacing:-.8px; font-weight:600; color:var(--ph-encre); }
.ph-entete p { color:#65766a; font-size:.93rem; margin:7px 0 0; }
.ph-section { display:flex; align-items:center; justify-content:space-between;
  gap:12px; margin:0 0 4px; }
.ph-section h3 { font-size:1.15rem; font-weight:600; padding:0; margin:0; color:var(--ph-encre); }
.ph-section span { color:#65766a; font-size:.8rem; }
.st-key-sf_saisie, .st-key-sf_inventaire, .st-key-cs_liste,
.st-key-cs_actions, .st-key-cs_ajout {
  background:#fff; border:1px solid var(--ph-ligne) !important;
  border-radius:16px !important; padding:22px !important;
  box-shadow:0 3px 14px #243a3004;
}
.st-key-sf_zone_scan { background:#e1f1e9; border:1px solid #bddaca;
  padding:12px; border-radius:12px; }
.st-key-sf_zone_scan [role="group"] {
  border:2px solid #0d9488 !important; background:#fff !important;
  border-radius:8px !important; min-height:64px !important; height:auto !important;
  padding:0 12px !important; display:flex; align-items:center;
}
.st-key-sf_zone_scan input { font-size:1.4rem !important; font-weight:600 !important;
  color:var(--ph-encre) !important; background:transparent !important; }
.st-key-sf_zone_scan input::placeholder { font-size:1rem !important;
  font-weight:400 !important; color:#526c5e !important; }
.st-key-sf_zone_scan [role="group"]:focus-within {
  box-shadow:0 0 0 3px #0d94882e !important; }
.st-key-sf_bulles { background:#f4f8f3; border:1px solid #bddaca !important;
  border-radius:12px !important; }
.st-key-sf_bulles h3 { font-size:1.25rem; color:var(--ph-encre); }
.st-key-sf_bulle_entree button, .st-key-sf_bulle_sortie button {
  min-height:54px; border-radius:10px; border:1px solid var(--ph-vert);
  background:var(--ph-vert); }
.st-key-sf_bulle_entree button p, .st-key-sf_bulle_sortie button p {
  color:#fff; font-size:1.1rem; font-weight:600; }
.st-key-sf_bulle_sortie button { background:#9c5d24; border-color:#9c5d24; }
.st-key-sf_bulle_annuler button { min-height:44px; border:2px solid #b9c7be;
  border-radius:10px; background:#fff; }
.st-key-sf_bulle_annuler button p { font-size:.96rem; color:#526657; }
.st-key-sf_gestes button { min-height:42px; border-radius:8px; }
.st-key-cs_priorite [data-testid="stButtonGroup"] { gap:6px; }
.st-key-cs_priorite button { border-radius:8px; min-height:42px; }
.st-key-cs_actions button { min-height:44px; border-radius:9px; }
.ph-table-scroll { width:100%; overflow:auto; max-height:480px;
  border:1px solid var(--ph-ligne); border-radius:10px; }
.ph-table-scroll:focus-visible { outline:3px solid #0d9488; outline-offset:2px; }
.ph-table { width:100%; border-collapse:collapse; font-size:.9rem;
  color:var(--ph-encre); margin:0 !important; }
.ph-table th { position:sticky; top:0; z-index:1; background:#f2f6f0;
  color:#5c6d60; font-size:.76rem; font-weight:600; text-align:left;
  padding:12px 16px; border:0 !important; border-bottom:1px solid var(--ph-ligne) !important; }
.ph-table td { padding:15px 16px; vertical-align:middle;
  border:0 !important; border-bottom:1px solid #edf1ea !important; }
.ph-table tbody tr:last-child td { border-bottom:0 !important; }
.ph-table tbody tr:hover { background:#f8faf6; }
.ph-table td:first-child { font-weight:600; }
.ph-table small { display:block; margin-top:5px; color:#6b7a70; font-size:.76rem; }
.ph-badge { display:inline-block; border-radius:6px; padding:4px 8px;
  font-size:.77rem; font-weight:550; white-space:nowrap; color:#526657; background:#eef2ed; }
.ph-badge.vert { color:#235c43; background:#e5f2e7; }
.ph-badge.ambre { color:#82531f; background:#fcf0d9; }
.ph-badge.rouge { color:#a14136; background:#fae9e4; }
.ph-badge.bleu { color:#32617a; background:#e7f1f7; }
.ph-vide { text-align:center; padding:32px 18px; background:#f7f9f5;
  border:1px dashed #d4dfd1; border-radius:10px; }
.ph-vide strong { display:block; font-size:1.05rem; margin-bottom:7px; color:var(--ph-encre); }
.ph-vide p { font-size:.9rem; margin:0; color:#65766a; }
.ph-selection { border-left:3px solid var(--ph-vert); padding:2px 0 2px 12px; margin:4px 0 12px; }
.ph-selection strong { font-size:1.05rem; }
.ph-selection p { margin:4px 0 0; color:#65766a; font-size:.88rem; }
.ph-sr-only { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0,0,0,0); }
.espace { border-left:3px solid var(--ph-vert); padding:2px 0 2px 14px; margin:4px 0 16px; }
.espace .titre { font-size:1.3rem; font-weight:600; color:var(--ph-encre); }
.espace .sous, .step small { font-size:.88rem; color:#65766a; }
.kpi-row { display:flex; gap:14px; flex-wrap:wrap; margin:8px 0 14px; }
.kpi { flex:1 1 180px; max-width:340px; background:white; border:1px solid var(--ph-ligne);
  border-radius:12px; padding:14px 18px; border-top:3px solid #dce5dc; }
.kpi .label { font-size:.82rem; color:#526657; }
.kpi .value { font-size:2rem; font-weight:650; }
.kpi .sub { font-size:.76rem; color:#65766a; }
.kpi.accent { border-top-color:#255e48; } .kpi.critical { border-top-color:#a14136; }
.kpi.warning { border-top-color:#d5b35c; } .kpi.serious { border-top-color:#b6783c; }
.step { display:flex; align-items:center; gap:12px; margin:6px 0 2px; }
.step .num { background:var(--ph-vert); color:white; border-radius:50%; width:32px;
  height:32px; display:grid; place-items:center; flex-shrink:0; }
.step .txt { font-size:1.2rem; font-weight:600; } .step small { display:block; font-weight:400; }
@media (max-width: 760px) {
  [data-testid="stMainBlockContainer"] { padding:1rem 1rem 2rem; }
  .ph-entete h2 { font-size:1.65rem; }
  .st-key-espace_travail button { padding:8px 10px !important; }
  .st-key-espace_travail button p { font-size:.86rem !important; }
  .st-key-sf_saisie, .st-key-sf_inventaire, .st-key-cs_liste,
  .st-key-cs_actions, .st-key-cs_ajout { padding:14px !important; }
  .ph-table th, .ph-table td { padding:12px; }
}
</style>
"""


def appliquer() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def entete(titre: str, sous_titre: str) -> None:
    st.markdown(f'<header class="ph-entete"><h2>{escape(titre)}</h2>'
                f'<p>{escape(sous_titre)}</p></header>', unsafe_allow_html=True)


def section(titre: str, detail: str = "") -> None:
    st.markdown(f'<div class="ph-section"><h3>{escape(titre)}</h3>'
                f'<span>{escape(detail)}</span></div>', unsafe_allow_html=True)


def vide(titre: str, aide: str) -> None:
    st.markdown(f'<div class="ph-vide"><strong>{escape(titre)}</strong>'
                f'<p>{escape(aide)}</p></div>', unsafe_allow_html=True)


def texte(valeur) -> str:
    return "" if pd.isna(valeur) else str(valeur)


def tableau_html(tableau: pd.DataFrame, titre: str, *,
                  libelles: dict | None = None, badges: dict | None = None,
                  secondaires: dict | None = None) -> str:
    """Table accessible de lecture. Toute valeur, y compris les noms, est échappée.

    ``badges`` associe une valeur métier à (libellé, couleur) ; une valeur
    inconnue reste lisible. Les colonnes secondaires s'affichent dans la
    même cellule, et ne créent pas une nouvelle colonne.
    """
    libelles, badges, secondaires = libelles or {}, badges or {}, secondaires or {}
    colonnes = [c for c in tableau.columns if c not in secondaires.values()]
    entetes = "".join(f'<th scope="col">{escape(libelles.get(c, c))}</th>' for c in colonnes)
    lignes = []
    for _, ligne in tableau.iterrows():
        cellules = []
        for c in colonnes:
            valeur = texte(ligne[c])
            if c in badges:
                label, couleur = badges[c].get(valeur, (valeur, ""))
                couleur = couleur if couleur in {"vert", "ambre", "rouge", "bleu"} else ""
                contenu = f'<span class="ph-badge {couleur}">{escape(label)}</span>'
            else:
                contenu = escape(valeur)
            if c in secondaires:
                detail = texte(ligne[secondaires[c]])
                if detail:
                    contenu += f'<small>{escape(detail)}</small>'
            cellules.append(f'<td>{contenu}</td>')
        lignes.append('<tr>' + ''.join(cellules) + '</tr>')
    return (f'<div class="ph-table-scroll" role="region" tabindex="0" '
            f'aria-label="{escape(titre)}"><table class="ph-table">'
            f'<caption class="ph-sr-only">{escape(titre)}</caption>'
            f'<thead><tr>{entetes}</tr></thead><tbody>{"".join(lignes)}</tbody>'
            '</table></div>')


def tableau(tableau: pd.DataFrame, titre: str, **options) -> None:
    st.markdown(tableau_html(tableau, titre, **options), unsafe_allow_html=True)
