"""Interface de travail Location, branchée sur les dossiers réels depuis 6.36."""
from __future__ import annotations

import json
from datetime import date, timedelta
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

import locations_suivi as suivi
import rappels_location as rappels
from stockage_partage import VerrouIndisponible


STYLE = """<style>
.st-key-locations_suivi { --vert:#214d3d; color:#223d33; }
.loc-intro {display:flex;justify-content:space-between;align-items:center;gap:20px;
padding:26px 28px;background:linear-gradient(115deg,#eaf2e9,#f7f8f3);
border:1px solid #dce7d9;border-radius:20px;margin:10px 0 22px}
.loc-intro h2 {color:#214d3d;font-size:1.9rem;letter-spacing:-.7px;margin:0;padding:0}
.loc-intro p {color:#53695e;margin:8px 0 0;font-size:.95rem}
.loc-eyebrow {font-size:.7rem;letter-spacing:1.8px;text-transform:uppercase;color:#657f6a;font-weight:700}
.loc-pill {background:#214d3d;color:white;border-radius:40px;padding:9px 15px;white-space:nowrap;font-size:.8rem}
.loc-kpis {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-bottom:22px}
.loc-kpi {background:white;border:1px solid #e0e6df;border-radius:16px;padding:18px 22px}
.loc-kpi strong {display:block;font-size:2rem;line-height:1.3;color:#214d3d;font-weight:650}
.loc-kpi span {font-size:.83rem;color:#5e7064}.loc-kpi small {display:block;font-size:.75rem;color:#76877b}
.st-key-locations_suivi [data-testid="stForm"] {border-color:#dce5db;border-radius:16px;background:#fff}
.st-key-locations_suivi button[kind="primary"] {background:#214d3d;border-color:#214d3d;border-radius:9px}
.st-key-locations_suivi [data-baseweb="tab-list"] {gap:12px}
.st-key-locations_suivi [aria-selected="true"][role="tab"] {color:#214d3d;font-weight:700}
@media(max-width:700px){.loc-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.loc-intro{padding:20px}.loc-pill{display:none}}
</style>"""


def _date(value):
    return suivi.jour(value).strftime("%d/%m/%Y") if value else "—"


def _table(rows):
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def _agir(path, action, acteur, d=None, **params):
    try:
        suivi.appliquer(path, action, acteur=acteur,
                        identifiant=d["id"] if d else "", revision=d["revision"] if d else None, **params)
    except (ValueError, OSError, VerrouIndisponible) as error:
        st.error(str(error) if isinstance(error, ValueError) else "Enregistrement indisponible. Rechargez le dossier puis réessayez.")
        return
    st.session_state["ls_message"] = "Enregistrement effectué."
    st.rerun()


def _choisir(state, key, recherche=""):
    choix = [d for d in state["dossiers"] if suivi.cle_patient(recherche) in suivi.cle_patient(d["patient"] + " " + d["materiel"])]
    ids = [d["id"] for d in choix]
    if not ids:
        st.info("Aucun dossier à afficher.")
        return None
    par_id = {d["id"]: d for d in choix}
    if key in st.session_state and st.session_state[key] not in ids:
        st.session_state[key] = None
    selected = st.selectbox("Dossier patient", ids,
        format_func=lambda i: f'{par_id[i]["patient"]} · {par_id[i]["materiel"]} · {par_id[i]["mode"]}',
        key=key, placeholder="Choisissez un dossier")
    return par_id.get(selected)


def _nouveau(state, path, acteur, today):
    with st.expander("＋ Nouveau dossier", expanded=not state["dossiers"]):
        categorie = st.selectbox("Matériel", suivi.CATEGORIES, key="ls_creation_categorie")
        with st.form("ls_creation", clear_on_submit=True):
            c1, c2 = st.columns([3, 2])
            patient = c1.text_input("Patient", placeholder="Nom et prénom")
            modes = ["Achat", "Location"] if categorie == "Fauteuil roulant" else ["Location", "Achat"]
            mode = c2.selectbox("Fourniture", modes, key="ls_creation_mode_" + categorie)
            if categorie == "Fauteuil roulant":
                st.caption("Achat proposé en priorité. Choisissez Location si la prescription prévoit une location temporaire.")
            c1, c2 = st.columns(2)
            debut = c1.date_input("Début réel / délivrance", value=today, format="DD/MM/YYYY")
            fin = c2.date_input("Fin prévue (facultative)", value=None, format="DD/MM/YYYY")
            prise = st.selectbox("Prise en charge", suivi.PRISES)
            with st.expander("Conditions de facturation et détails de l'appareil"):
                c1, c2 = st.columns(2)
                cycle = c1.selectbox("Rythme de préparation des factures", suivi.CYCLES)
                terme = c2.selectbox("Facturation à préparer", ["Début de période", "Fin de période"])
                st.caption("Le rythme choisi organise le suivi. Il ne détermine ni l'unité tarifaire ni le montant CAFAT. Un achat génère une seule période.")
                c1, c2 = st.columns(2)
                appareil = c1.text_input("N° de l'appareil (facultatif)")
                detail = c2.text_input("Désignation / modèle (facultatif)")
                notes = st.text_area("Notes", height=70)
            if categorie in suivi.CAUTIONS:
                st.info(f"Caution proposée pour une location : {suivi.CAUTIONS[categorie]:,} F CFP. Sa réception sera enregistrée séparément.".replace(",", " "))
            if st.form_submit_button("Créer le dossier", type="primary", use_container_width=True):
                _agir(path, "creer", acteur, patient=patient, categorie=categorie, debut=debut,
                      fin_prevue=fin, cycle=cycle, terme=terme, mode=mode, prise=prise,
                      appareil=appareil, materiel=detail, notes=notes)


def _a_faire(state, path, acteur, today):
    tasks = suivi.taches(state, today)
    dossiers = {d["id"]: d for d in state["dossiers"]}
    st.subheader("Votre prochaine action")
    if tasks["facturer"]:
        _table([{"Patient": dossiers[p["dossier"]]["patient"], "Matériel": dossiers[p["dossier"]]["materiel"],
                 "Du": _date(p["du"]), "Au": _date(p["au"]),
                 "À faire": "Dernier mois · renouvellement" if p["dernier"] else "Préparer la facture"}
                for p in tasks["facturer"]])
    else:
        st.success("Aucune facturation prête à préparer aujourd'hui.")
    if tasks["facturer"]:
        st.caption("Ouvrez Facturation pour vérifier la demande d'entente puis enregistrer la facture.")
    if tasks["renouveler"]:
        st.subheader("Renouvellements")
        _table([{"Patient": dossiers[t["dossier"]]["patient"], "Matériel": dossiers[t["dossier"]]["materiel"],
                 "Fin de couverture": _date(t["fin"]),
                 "À faire": "Accord attendu" if t["demande_en_cours"] else "Préparer l'entente préalable"}
                for t in tasks["renouveler"]])
    if tasks["completer"]:
        st.subheader("Dossiers à compléter")
        _table([{"Patient": dossiers[t["dossier"]]["patient"], "Matériel": dossiers[t["dossier"]]["materiel"],
                 "À vérifier": " · ".join(t["motifs"])} for t in tasks["completer"]])
    if tasks["cautions"] or tasks["retours"]:
        st.subheader("Retours et cautions")
        _table([{"Patient": dossiers[i]["patient"], "Matériel": dossiers[i]["materiel"], "À faire": action}
                for key, action in (("cautions", "Restituer la caution"), ("retours", "Récupérer le matériel")) for i in tasks[key]])
    if tasks["regulariser"]:
        st.warning("Des factures couvrent une période après le retour du matériel. Vérifiez leur régularisation dans le logiciel métier.")
        _table([{"Patient": dossiers[f["dossier"]]["patient"], "Facture": f["reference"], "Retour": _date(dossiers[f["dossier"]]["retour"]), "Facturée au": _date(f["au"])}
                for f in state["factures"] if f["id"] in tasks["regulariser"]])
    a_preparer = [ref for ref, m in state["materiels"].items() if m["etat"] == "À préparer"]
    if a_preparer:
        with st.expander(f"{len(a_preparer)} appareil(s) à contrôler après retour"):
            with st.form("ls_disponible"):
                ref = st.selectbox("Appareil contrôlé", a_preparer)
                confirme = st.checkbox("Nettoyage et contrôle terminés, appareil prêt à être remis")
                if st.form_submit_button("Remettre à disposition"):
                    if confirme:
                        _agir(path, "disponible", acteur, appareil=ref, date=today)
                    else:
                        st.error("Confirmez le contrôle de l'appareil.")


def _facturer(state, path, acteur, today, pretes):
    if not pretes:
        return
    with st.container(border=True):
        st.markdown("**Enregistrer une facture émise**")
        par_id = {p["id"]: p for p in pretes}
        if st.session_state.get("ls_periode") not in par_id:
            st.session_state["ls_periode"] = None
        ident = st.selectbox("Période à facturer", list(par_id), index=None, key="ls_periode",
            format_func=lambda i: f'{suivi.dossier(state, par_id[i]["dossier"])["patient"]} · {_date(par_id[i]["du"])} → {_date(par_id[i]["au"])}')
        if ident is None:
            return
        p = par_id[ident]
        d = suivi.dossier(state, p["dossier"])
        if d["prise"] != "Non remboursable":
            st.markdown("**Entente liée à cette période**")
            _table(_lignes_ententes([
                a for a in d["accords"] if a["statut"] == "Accordée"
                and a["du"] <= p["au"] and a["au"] >= p["du"]]))
        if p["dernier"]:
            st.warning("Dernière période de prise en charge : préparez le renouvellement de l'entente. L'alerte restera affichée jusqu'à l'accord suivant.")
        if p["partielle"]:
            st.warning("Période écourtée : vérifiez le montant et les unités dans le logiciel métier. Aucun prorata n'est calculé ici.")
        with st.form("ls_facturer_" + ident):
            c1, c2, c3 = st.columns(3)
            reference = c1.text_input("Référence de facture")
            emission = c2.date_input("Date d'émission", value=today, format="DD/MM/YYYY")
            somme = c3.number_input("Montant F CFP", min_value=0, value=0, step=1)
            st.caption("Recopiez la facture de votre logiciel métier. La caution reste séparée du montant facturé.")
            confirme = st.checkbox("J'ai vérifié le montant et l'action de renouvellement") if p["partielle"] or p["dernier"] else True
            if st.form_submit_button("Enregistrer la facture", type="primary"):
                _agir(path, "facturer", acteur, d, periode=ident, reference=reference,
                      date=emission, montant=somme, confirme=confirme)


def _fiche(state, path, acteur, today):
    recherche = st.text_input("Rechercher un patient ou un matériel", key="ls_recherche")
    d = _choisir(state, "ls_dossier", recherche)
    if not d:
        return
    key = f'{d["id"]}_{d["revision"]}'
    st.markdown(f'### {escape(d["patient"])}')
    st.caption(f'{d["materiel"]} · {d["mode"]} · Début {_date(d["debut"])} · {d["prise"]}')
    if d["retour"]:
        st.info(f'Matériel rendu le {_date(d["retour"])} · {d["etat_retour"]}')
    if d["notes"]:
        st.write(d["notes"])
    if d["reprise_a_verifier"]:
        st.warning("Dossier conservé depuis l'ancienne version. Vérifiez sa dernière période facturée avant d'activer le nouveau suivi.")
        with st.expander("Voir les valeurs d'origine"):
            st.json(d["source_ancienne"])
        with st.form("ls_reprise_" + key):
            c1, c2 = st.columns(2)
            debut = c1.date_input("Début réel du dossier", value=suivi.jour(d["debut"]) if d["debut"] else today, format="DD/MM/YYYY")
            suite = c2.date_input("Début de la première période non facturée", value=None, format="DD/MM/YYYY")
            preuve = st.text_input("Dernière période vérifiée et référence (ou « aucune facture »)")
            deja_facture = st.checkbox("Cet achat est déjà facturé : conserver l'historique sans nouvelle facture") if d["mode"] == "Achat" else False
            if st.form_submit_button("Valider la reprise"):
                if suite or deja_facture:
                    _agir(path, "reprendre", acteur, d, debut=debut, debut_suivi=suite or debut, justification=preuve, achat_deja_facture=deja_facture)
                else:
                    st.error("Indiquez la première période non facturée.")
    sections = st.tabs(["Prise en charge", "Caution & retour", "Échéancier & historique"])
    with sections[0]:
        with st.expander("Conditions de prise en charge", expanded=d["prise"] == "À vérifier" or not d["motif"]):
            if d["categorie"] == "Aérosol":
                st.info("Aérosol : vérifiez les conditions propres au patient. Le matériel seul ne suffit pas à conclure à un remboursement.")
            with st.form("ls_prise_" + key):
                prise = st.selectbox("Prise en charge", suivi.PRISES, index=suivi.PRISES.index(d["prise"]))
                motif = st.text_area("Conditions vérifiées, motif et référence", value=d["motif"])
                prescription = st.text_input("Référence de prescription", value=d["prescription"])
                date_verif = st.date_input("Vérifié le", value=today, format="DD/MM/YYYY")
                if st.form_submit_button("Enregistrer la vérification", type="primary"):
                    _agir(path, "qualifier", acteur, d, prise=prise, motif=motif, prescription=prescription, date=date_verif)
            if d["verifie_par"]:
                st.caption(f'Vérifié par {d["verifie_par"]}, le {_date(d["verifie_le"])}')
        if d["prise"] != "Non remboursable":
            st.caption("La date de demande d'entente, son initiateur et la réponse de la caisse se renseignent dans Facturation.")
        else:
            st.caption("Location privée : pas d'entente exigée par ce suivi. Le contrat, la facture et la caution sont suivis dans le même dossier.")
    with sections[1]:
        _caution(d, path, acteur, today, key)
    with sections[2]:
        ps = suivi.periodes(state, d, today, toutes=True)
        _table([{"Période": p["numero"], "Du": _date(p["du"]), "Au": _date(p["au"]),
                 "Facturation": "Enregistrée" if p["facture"] else "À vérifier" if p["blocages"] else "À préparer" if p["echeance"] <= today.isoformat() else "À venir",
                 "Attention": "Dernier mois · renouvellement" if p["dernier"] else "Période partielle" if p["partielle"] else ""} for p in ps])
        if d.get("achat_historique"):
            st.success("Achat historique déjà facturé : aucune nouvelle échéance. Le règlement reste à consulter dans le logiciel métier d'origine.")
        elif not ps:
            st.info("L'échéancier apparaîtra après vérification du dossier et des dates de couverture.")
        _table([{"Date": e["date"][:16].replace("T", " "), "Action": e["action"], "Équipe": e["auteur"]}
                for e in reversed(state["journal"]) if e["dossier"] == d["id"]])


def _lignes_ententes(accords):
    return [{"Date de demande d'entente préalable": _date(a["envoyee"]),
             "Membre de l'équipe": a["initiateur"], "État": a["statut"],
             "Reçue le": _date(a["reception"]), "Du": _date(a["du"]), "Au": _date(a["au"]), "Référence": a["reference"] or a["reference_demande"]}
            for a in accords]


def _ententes(d, path, acteur, today, key):
    _table(_lignes_ententes(d["accords"]))
    with st.expander("Enregistrer une demande d'entente préalable", expanded=not d["accords"]):
        st.caption("Renseignez la date réelle d'envoi et le membre de l'équipe à l'origine de la demande. Cet enregistrement n'envoie pas de mail à la CAFAT.")
        with st.form("ls_demande_" + key):
            c1, c2 = st.columns([2, 3])
            date_envoi = c1.date_input("Date de demande d'entente préalable", value=None,
                                       max_value=today, format="DD/MM/YYYY")
            initiateur = c2.text_input("Membre de l'équipe ayant initié la demande", value=acteur,
                                       help="La personne qui a initié la demande, même si un collègue l'enregistre aujourd'hui.")
            c1, c2 = st.columns([1, 2])
            canal = c1.selectbox("Mode d'envoi", ["Mail", "Courrier", "Autre"])
            reference = c2.text_input("Référence de la demande / du mail")
            if st.form_submit_button("Enregistrer la demande", type="primary"):
                if date_envoi is None:
                    st.error("Renseignez la date de demande d'entente préalable.")
                elif not initiateur.strip():
                    st.error("Renseignez le membre de l'équipe ayant initié la demande.")
                else:
                    _agir(path, "demander", acteur, d, date=date_envoi, canal=canal, reference=reference, initiateur=initiateur)
    demandes = suivi.accords_en_attente(d)
    if demandes:
        with st.expander("Enregistrer la réponse de la caisse", expanded=True):
            with st.form("ls_accord_" + key):
                demande = st.selectbox("Demande concernée", [a["id"] for a in demandes],
                    format_func=lambda i: next(f'{a["reference_demande"]} · {a["initiateur"]}' for a in demandes if a["id"] == i))
                reponse = st.selectbox("Réponse", ["Accordée", "Refusée"])
                recu = st.date_input("Réponse reçue le", value=today, format="DD/MM/YYYY")
                c1, c2 = st.columns(2)
                du = c1.date_input("Couverture du", value=None, format="DD/MM/YYYY")
                au = c2.date_input("Couverture au (inclus)", value=None, format="DD/MM/YYYY")
                reference = st.text_input("Référence de l'accord / motif du refus")
                st.caption("Recopiez les dates de couverture de l'accord. La réception du mail ne fixe pas automatiquement le début de prise en charge.")
                if st.form_submit_button("Enregistrer la réponse", type="primary"):
                    if reponse == "Refusée":
                        _agir(path, "refuser", acteur, d, demande=demande, date=recu, motif=reference)
                    elif du and au:
                        _agir(path, "accorder", acteur, d, demande=demande, reception=recu, du=du, au=au, reference=reference)
                    else:
                        st.error("Renseignez les dates de couverture indiquées sur l'accord.")
    with st.expander("Accord existant ou couverture sans réponse individuelle"):
        st.caption("Pour une reprise ou un accord réputé acquis : documentez la règle applicable au patient et les dates vérifiées.")
        with st.form("ls_couverture_" + key):
            c1, c2 = st.columns(2)
            du = c1.date_input("Début de couverture", value=None, format="DD/MM/YYYY")
            au = c2.date_input("Fin de couverture incluse", value=None, format="DD/MM/YYYY")
            ref = st.text_input("Fondement de couverture et justificatif")
            if st.form_submit_button("Enregistrer cette couverture"):
                if du and au:
                    _agir(path, "couverture", acteur, d, du=du, au=au, date=today, reference=ref)
                else:
                    st.error("Renseignez les deux dates de couverture.")


def _caution(d, path, acteur, today, key):
    c = d["caution"]
    statut = ("Chèque conservé, non encaissé" if c["mode"] == "Chèque" else "Espèces reçues") if c["etat"] == "Reçue" else c["etat"]
    st.markdown(f'**Caution : {c["montant"]:,} F CFP · {statut}**'.replace(",", " "))
    st.caption("La caution est indépendante du loyer et de la prise en charge. Aucun encaissement ou retenue automatique.")
    if d["mode"] == "Achat":
        return
    if c["etat"] in ("Sans caution", "À recevoir") and not d["retour"]:
        with st.expander("Montant et modalité convenus"):
            with st.form("ls_caution_convenue_" + key):
                somme = st.number_input("Montant de la caution F CFP", min_value=0, value=c["montant"], step=1)
                modes = ["À préciser", "Chèque", "Espèces"]
                mode = st.selectbox("Modalité de règlement de la caution", modes, index=modes.index(c["mode"]))
                if st.form_submit_button("Enregistrer les modalités"):
                    _agir(path, "caution_prevoir", acteur, d, montant=somme, mode=mode)
    if c["etat"] == "À recevoir" and not d["retour"]:
        with st.form("ls_caution_reception_" + key):
            mode = st.selectbox("Caution reçue par", ["Chèque", "Espèces"], index=1 if c["mode"] == "Espèces" else 0)
            recu = st.date_input("Caution reçue le", value=today, format="DD/MM/YYYY")
            ref = st.text_input("Référence du chèque ou du reçu de caisse")
            if st.form_submit_button("Confirmer la réception de la caution", type="primary"):
                _agir(path, "caution_recevoir", acteur, d, mode=mode, date=recu, reference=ref)
    if not d["retour"]:
        with st.expander("Enregistrer le retour du matériel"):
            with st.form("ls_retour_" + key):
                retour = st.date_input("Retour réel le", value=today, format="DD/MM/YYYY")
                etat = st.text_input("État de l'appareil et des accessoires")
                st.caption("Le retour arrête les futures périodes. Une facture déjà émise reste au journal et doit être régularisée explicitement si nécessaire.")
                if st.form_submit_button("Matériel rendu"):
                    _agir(path, "retour", acteur, d, date=retour, etat=etat)
    if d["retour"] and c["etat"] == "Reçue":
        st.warning("Caution à restituer au patient.")
        with st.form("ls_caution_restitution_" + key):
            jour_retour = st.date_input("Restitution le", value=today, format="DD/MM/YYYY")
            ref = st.text_input("Référence de restitution / reçu signé")
            libelle = "Confirmer le chèque rendu" if c["mode"] == "Chèque" else "Confirmer les espèces remboursées"
            if st.form_submit_button(libelle, type="primary"):
                _agir(path, "caution_restituer", acteur, d, date=jour_retour, reference=ref)
    if c["etat"] == "Restituée":
        st.success(f'Caution restituée par {c["rendu_par"]} le {_date(c["restitution"])}.')


def _facturation(state, path, acteur, today):
    d = _choisir(state, "ls_dossier_facturation")
    if not d:
        return
    st.subheader("1. Demande d'entente préalable")
    if d["prise"] == "Non remboursable":
        st.info("Dossier non remboursable : pas de demande d'entente à renseigner dans ce suivi.")
    else:
        _ententes(d, path, acteur, today, f'{d["id"]}_{d["revision"]}')
    st.subheader("2. Facturation")
    pretes = [p for p in suivi.taches(state, today)["facturer"] if p["dossier"] == d["id"]]
    if pretes:
        _facturer(state, path, acteur, today, pretes)
    else:
        st.info("Aucune période prête à facturer pour ce dossier. Vérifiez la prise en charge, l'accord et les échéances.")
    with st.expander("Historique de toutes les factures et règlements"):
        _journal_factures(state, path, acteur, today)


def _journal_factures(state, path, acteur, today):
    rows = []
    for f in reversed(state["factures"]):
        d = suivi.dossier(state, f["dossier"])
        rows.append({"Patient": d["patient"], "Référence": f["reference"], "Émise le": _date(f["emission"]),
                     "Du": _date(f["du"]), "Au": _date(f["au"]), "Montant F CFP": f["montant"],
                     "État": f["etat"], "Prise en charge": f["prise"], "Par": f["auteur"]})
    if not rows:
        st.info("Les factures enregistrées apparaîtront ici, avec leur période et leur règlement.")
        return
    _table(rows)
    st.download_button("Exporter les factures", pd.DataFrame(rows).to_csv(index=False, sep=";").encode("utf-8-sig"),
                       file_name="factures_locations.csv", mime="text/csv")
    ouvertes = [f for f in state["factures"] if f["etat"] == "Émise"]
    if ouvertes:
        par_id = {f["id"]: f for f in ouvertes}
        ident = st.selectbox("Facture à traiter", list(par_id), format_func=lambda i: f'{par_id[i]["reference"]} · {suivi.dossier(state, par_id[i]["dossier"])["patient"]}')
        f = par_id[ident]
        d = suivi.dossier(state, f["dossier"])
        with st.form("ls_paiement_" + ident + str(d["revision"])):
            reglement = st.date_input("Réglée le", value=today, format="DD/MM/YYYY")
            reference = st.text_input("Référence du règlement")
            if st.form_submit_button("Marquer comme réglée", type="primary"):
                _agir(path, "regler", acteur, d, facture=ident, date=reglement, reference=reference)
        with st.expander("Corriger une facture émise"):
            st.caption("Une annulation conserve la facture d'origine et remet la période à examiner. Effectuez aussi la régularisation dans votre logiciel métier.")
            with st.form("ls_annuler_" + ident + str(d["revision"])):
                motif = st.text_input("Motif et référence de régularisation")
                confirme = st.checkbox("La régularisation a été vérifiée dans le logiciel métier")
                if st.form_submit_button("Annuler l'enregistrement"):
                    if confirme:
                        _agir(path, "annuler_facture", acteur, d, facture=ident, motif=motif)
                    else:
                        st.error("Confirmez la vérification de la régularisation.")


def _reglages(state, path, acteur, today):
    with st.form("ls_parametres"):
        equipe = st.text_area("Équipe — un nom par ligne", value="\n".join(state["equipe"]))
        alerte = st.number_input("Prévenir avant la fin de couverture (jours)", min_value=1, max_value=180, value=state["alerte_j"])
        if st.form_submit_button("Enregistrer les préférences"):
            _agir(path, "parametres", acteur, equipe=equipe.splitlines(), alerte_j=alerte)
    st.subheader("Rappels par mail")
    st.caption("Un récapitulatif au maximum par jour, à l'heure de Nouvelle-Calédonie. Il contient des nombres et des actions, sans nom de patient. Le serveur doit rester allumé.")
    try:
        cfg = rappels.configuration(path.parent)
    except (ValueError, OSError):
        st.error("La configuration des rappels est illisible. Faites vérifier le fichier local avant de poursuivre.")
        return
    st.info("Rappels activés" if cfg["actif"] else "Rappels désactivés — renseignez les paramètres puis activez l'envoi.")
    with st.form("ls_mail_config"):
        destination = st.text_input("Adresse mail de la pharmacie", value=cfg["destinataire"])
        c1, c2 = st.columns(2)
        heure = c1.text_input("Heure locale HH:MM", value=cfg["heure"])
        noms = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        jours = c2.multiselect("Jours d'envoi", list(range(7)), default=cfg["jours"], format_func=lambda j: noms[j])
        url = st.text_input("Lien vers l'utilitaire (facultatif)", value=cfg.get("url", ""))
        with st.expander("Connexion au service d'envoi"):
            expediteur = st.text_input("Adresse d'expéditeur", value=cfg["expediteur"])
            hote = st.text_input("Serveur SMTP", value=cfg["hote"])
            c1, c2 = st.columns(2)
            securite = c1.selectbox("Connexion sécurisée", ["SSL", "STARTTLS"], index=0 if cfg["securite"] == "SSL" else 1)
            port = c2.number_input("Port SMTP", min_value=1, max_value=65535, value=cfg["port"])
            utilisateur = st.text_input("Identifiant SMTP", value=cfg["utilisateur"])
            st.caption("Le responsable du serveur doit renseigner le secret d'envoi dans PHARMACIE_SMTP_PASSWORD. Il n'est ni demandé ni affiché sur les postes de comptoir.")
        actif = st.checkbox("Activer les rappels automatiques", value=cfg["actif"])
        if st.form_submit_button("Enregistrer les rappels", type="primary"):
            try:
                rappels.enregistrer_configuration(path.parent, dict(actif=actif, destinataire=destination.strip(), expediteur=expediteur.strip(),
                    hote=hote.strip(), port=port, securite=securite, utilisateur=utilisateur.strip(), heure=heure, jours=jours, url=url.strip()))
            except (ValueError, OSError, VerrouIndisponible) as error:
                st.error(str(error))
            else:
                st.session_state["ls_message"] = "Paramètres des rappels enregistrés."
                st.rerun()
    journal = path.parent / rappels.JOURNAL
    if journal.exists():
        try:
            valeurs = json.loads(journal.read_text(encoding="utf-8"))
            _table([{"Jour": k, "État": v["statut"]} for k, v in sorted(valeurs.items(), reverse=True)][:10])
        except (ValueError, OSError, KeyError):
            st.warning("Le journal d'envoi doit être vérifié.")
    with st.expander("Essayer le scénario du matelas à air"):
        demo = suivi.demonstration(today)
        d = demo["dossiers"][0]
        a = d["accords"][0]
        st.caption(f'Démonstration sans enregistrement patient : demande envoyée par {a["initiateur"]} le {_date(a["envoyee"])}, accord reçu le {_date(a["reception"])}. Début de couverture supposé identique, à confirmer sur un vrai accord.')
        _table([{"Mois": p["numero"], "Facturation à préparer": _date(p["echeance"]),
                 "Du": _date(p["du"]), "Au": _date(p["au"]), "Alerte": "Renouvellement" if p["dernier"] else ""}
                for p in suivi.periodes(demo, d, today, toutes=True)])
    with st.expander("Sauvegarde des dossiers"):
        st.download_button("Télécharger la sauvegarde complète", json.dumps(state, ensure_ascii=False, indent=2),
            file_name="locations_sauvegarde.json", mime="application/json")
        st.caption("La sauvegarde contient les données patients. Conservez-la dans l'emplacement de sauvegarde de l'officine.")


def rendre(ancien_csv):
    path = Path(ancien_csv).parent / suivi.FICHIER
    try:
        state = suivi.initialiser(path, ancien_csv)
    except (ValueError, OSError, VerrouIndisponible) as error:
        st.error(str(error))
        return
    today = suivi.maintenant().date()
    with st.sidebar:
        st.markdown("### Équipe")
        acteur = st.text_input("Votre nom", key="ls_acteur", placeholder="Prénom / nom")
        if state["equipe"]:
            st.caption("Équipe : " + ", ".join(state["equipe"]))
        st.caption(f'Nouvelle-Calédonie · {_date(today)}')
        st.caption("Location · version 6.38")
    with st.container(key="locations_suivi"):
        st.markdown(STYLE, unsafe_allow_html=True)
        st.markdown('<div class="loc-intro"><div><div class="loc-eyebrow">Le suivi du matériel patient</div><h2>Locations & achats</h2><p>Les bonnes périodes. Les bons accords. Chaque geste tracé.</p></div><span class="loc-pill">Suivi quotidien · 6.38</span></div>', unsafe_allow_html=True)
        message = st.session_state.pop("ls_message", "")
        if message:
            st.success(message)
        tasks = suivi.taches(state, today)
        kpis = [("À facturer", len(tasks["facturer"]), "périodes prêtes"),
                ("À renouveler", len(tasks["renouveler"]), f'sous {state["alerte_j"]} jours ou dernier mois'),
                ("Dossiers", len(state["dossiers"]), "locations et achats"),
                ("Cautions à rendre", len(tasks["cautions"]), "après retour du matériel")]
        st.markdown('<div class="loc-kpis">' + ''.join(f'<div class="loc-kpi"><span>{escape(n)}</span><strong>{v}</strong><small>{escape(s)}</small></div>' for n, v, s in kpis) + '</div>', unsafe_allow_html=True)
        _nouveau(state, path, acteur, today)
        onglets = st.tabs(["À faire", "Dossiers patients", "Facturation", "Réglages & essai"])
        with onglets[0]:
            _a_faire(state, path, acteur, today)
        with onglets[1]:
            _fiche(state, path, acteur, today)
        with onglets[2]:
            _facturation(state, path, acteur, today)
        with onglets[3]:
            _reglages(state, path, acteur, today)
