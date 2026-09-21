"""Parcours des écrans de stock et de commandes sur des fichiers isolés, avec les vrais widgets."""

import json
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import commandes_speciales as cs
import stock_ferme as sf
import ui_style


def champ(app, kind, label):
    return next(x for x in getattr(app, kind) if x.label == label)


def clic(app, label):
    champ(app, "button", label).click().run(timeout=20)
    assert not app.exception


def table_html(app):
    return "\n".join(m.value for m in app.markdown if '<table class="ph-table">' in m.value)


@pytest.fixture
def stock(tmp_path, monkeypatch):
    import ui_stock_ferme as ui
    for nom, fichier in [("INVENTAIRE_PATH", "stock.csv"),
                         ("REPERTOIRE_PATH", "produits.csv"),
                         ("BASE_MEDICAMENTS_PATH", "base.csv")]:
        monkeypatch.setattr(ui, nom, tmp_path / fichier)
    inventaire = sf.inventaire_vide()
    for nom, cip, jours, lot in [("PRODUIT ALPHA", "3400930000019", 180, "A"),
                                 ("PRODUIT BETA", "3400930000026", -5, "B")]:
        inventaire = sf.ajouter_entree(inventaire, sf.EntreeStock(
            nom=nom, cip=cip, boites=2, unites_par_boite=10,
            peremption=date.today() + timedelta(days=jours), lot=lot))
    sf.sauver_inventaire(inventaire, ui.INVENTAIRE_PATH)
    app = AppTest.from_string("import ui_stock_ferme as ui; ui.rendre()").run(timeout=20)
    assert not app.exception
    return app, ui.INVENTAIRE_PATH


@pytest.fixture
def commandes(tmp_path, monkeypatch):
    import ui_commandes_speciales as ui
    for nom, fichier in [("DOSSIERS_PATH", "commandes.csv"),
                         ("INVENTAIRE_PATH", "stock.csv"),
                         ("BASE_MEDICAMENTS_PATH", "base.csv")]:
        monkeypatch.setattr(ui, nom, tmp_path / fichier)
    dossiers = cs.dossier_vide()
    dossiers = cs.ajouter_dossier(dossiers, "ALICE TEST", "ALPHA", "3400930000019",
                                  boites=2, facturation=date.today() - timedelta(days=40))
    dossiers = cs.ajouter_dossier(dossiers, "BRUNO TEST", "BETA", "3400930000026",
                                  envoi=date.today() - timedelta(days=50), facturation=date.today())
    dossiers = cs.ajouter_dossier(dossiers, "CAMILLE TEST", "GAMMA", "3400930000033",
                                  boites=1, facturation=date.today() - timedelta(days=1))
    cs.sauver(dossiers, ui.DOSSIERS_PATH)
    app = AppTest.from_string("import ui_commandes_speciales as ui; ui.rendre()").run(timeout=20)
    assert not app.exception
    return app, ui.DOSSIERS_PATH


def test_stock_mouvements_masques_jusqu_au_clic_bip(stock):
    app, path = stock
    avant = path.read_bytes()
    assert "PRODUIT ALPHA" in table_html(app)
    assert not any(b.key in {"sf_bulle_entree", "sf_bulle_sortie",
                            "sf_bouton_saisie_manuelle", "sf_bouton_sortie_manuelle"}
                   for b in app.button)
    assert not any(s.key.startswith("sf_scan_") for s in app.selectbox)
    clic(app, "Bip une boîte")
    assert app.selectbox(key="sf_scan_0").value is None
    assert not any(b.key in {"sf_bulle_entree", "sf_bulle_sortie"} for b in app.button)
    choix = next(o for o in app.selectbox(key="sf_scan_0").options if "ALPHA" in o)
    app.selectbox(key="sf_scan_0").select(choix).run()
    assert not app.exception
    assert app.button(key="sf_bulle_entree") and app.button(key="sf_bulle_sortie")
    assert path.read_bytes() == avant


@pytest.mark.parametrize("geste", [None, "sf_bulle_entree", "sf_bulle_sortie"])
def test_stock_fermer_annule_le_mouvement_et_rouvre_un_champ_vide(stock, geste):
    app, path = stock
    avant = path.read_bytes()
    clic(app, "Bip une boîte")
    choix = next(o for o in app.selectbox(key="sf_scan_0").options if "ALPHA" in o)
    app.selectbox(key="sf_scan_0").select(choix).run()
    if geste:
        app.button(key=geste).click().run()
        assert not app.exception
    clic(app, "Fermer")
    assert not any(s.key.startswith("sf_scan_") for s in app.selectbox)
    assert not any(b.key in {"sf_bulle_entree", "sf_bulle_sortie"} for b in app.button)
    assert "PRODUIT ALPHA" in table_html(app)
    clic(app, "Bip une boîte")
    assert next(s for s in app.selectbox if s.key.startswith("sf_scan_")).value is None
    assert not app.session_state.get("sf_a_orienter")
    assert not app.session_state.get("sf_en_attente")
    assert not app.session_state["sf_sortie_manuelle"]
    assert path.read_bytes() == avant


def test_stock_selection_puis_sortie_retirent_seulement_le_lot_choisi(stock):
    app, path = stock
    clic(app, "Bip une boîte")
    choix = next(o for o in app.selectbox(key="sf_scan_0").options if "ALPHA" in o)
    app.selectbox(key="sf_scan_0").select(choix).run()
    assert not app.exception
    # Identifier ne retire rien ; Entrée et Sortie restent deux décisions.
    assert sf.charger_inventaire(path)["Boîtes"].sum() == 4
    app.button(key="sf_bulle_sortie").click().run()
    assert not app.exception
    clic(app, "➖ Retirer du stock")
    relu = sf.charger_inventaire(path).set_index("Nom du produit")
    assert relu.at["PRODUIT ALPHA", "Boîtes"] == 1
    assert relu.at["PRODUIT BETA", "Boîtes"] == 2
    # Le panneau reste ouvert pour la boîte suivante, sans sens mémorisé.
    assert any(s.key.startswith("sf_scan_") for s in app.selectbox)
    assert not any(b.key in {"sf_bulle_entree", "sf_bulle_sortie"} for b in app.button)


def test_stock_saisie_manuelle_enregistre_et_actualise_la_liste(stock):
    app, path = stock
    clic(app, "Bip une boîte")
    app.button(key="sf_bouton_saisie_manuelle").click().run()
    champ(app, "text_input", "Nom du médicament *").set_value("PRODUIT MANUEL")
    champ(app, "text_input", "Date de péremption *").set_value("122028")
    clic(app, "➕ Ajouter au stock")
    assert "PRODUIT MANUEL" in table_html(app)
    assert len(sf.charger_inventaire(path)) == 3


def test_stock_filtre_peremption_interdit_la_correction_du_stock_partiel(stock):
    app, path = stock
    avant = path.read_bytes()
    app.checkbox(key="sf_filtre_traiter").check().run()
    assert "PRODUIT BETA" in table_html(app)
    assert "PRODUIT ALPHA" not in table_html(app)
    assert not any(getattr(x, "key", "") and x.key.startswith("sf_editeur")
                   for x in app.dataframe)
    app.text_input(key="sf_recherche").set_value("ABSENT").run()
    assert "Aucun lot trouvé" in " ".join(x.value for x in app.markdown)
    assert path.read_bytes() == avant


def test_commandes_filtre_retard_reception_agit_sur_le_seul_dossier_visible(commandes):
    app, path = commandes
    next(x for x in app.get("button_group") if x.key == "cs_priorite").set_value("En retard").run()
    assert not app.exception
    assert "BRUNO TEST" in table_html(app)
    assert "ALICE TEST" not in table_html(app)
    assert app.selectbox(key="cs_geste_dossier").options == ["BRUNO TEST — BETA"]
    app.button(key="cs_recevoir").click().run()
    assert not app.exception
    relu = cs.charger(path).set_index("Patient")
    assert relu.at["BRUNO TEST", "Boîtes en main"] == 1
    assert cs.parser_date(relu.at["BRUNO TEST", "Réception"]) == date.today()
    assert relu.at["ALICE TEST", "Boîtes en main"] == 2
    assert not any(b.key == "cs_facturer" for b in app.button)


def test_commandes_selection_stable_apres_tri_et_ecriture_voisine(commandes):
    app, path = commandes
    cle = json.dumps(["CAMILLE TEST", "3400930000033", "GAMMA"], ensure_ascii=False)
    app.selectbox(key="cs_geste_dossier").select(cle).run()
    app.selectbox(key="cs_tri").select(cs.TRI_PATIENT).run()
    assert app.selectbox(key="cs_geste_dossier").value == cle
    # Un autre poste insère un dossier avant celui qui est sélectionné.
    courant = cs.ajouter_dossier(cs.charger(path), "AAA TEST", "ALPHA", "3400930000019")
    cs.sauver(courant, path)
    app.run()
    assert app.selectbox(key="cs_geste_dossier").value == cle
    app.button(key="cs_envoyer").click().run()
    relu = cs.charger(path).set_index("Patient")
    assert cs.parser_date(relu.at["CAMILLE TEST", "Envoi du mail"]) == date.today()
    assert cs.parser_date(relu.at["AAA TEST", "Envoi du mail"]) is None


def test_commandes_facturation_actualise_date_boites_et_filtre(commandes):
    app, path = commandes
    next(x for x in app.get("button_group") if x.key == "cs_priorite").set_value("À facturer").run()
    assert app.selectbox(key="cs_geste_dossier").options == ["ALICE TEST — ALPHA"]
    app.button(key="cs_facturer").click().run()
    assert not app.exception
    relu = cs.charger(path).set_index("Patient")
    assert relu.at["ALICE TEST", "Boîtes en main"] == 1
    assert cs.parser_date(relu.at["ALICE TEST", "Dernière facturation"]) == date.today()
    assert not table_html(app)


def test_commandes_recherche_vide_ne_propose_pas_d_action_ni_correction(commandes):
    app, path = commandes
    avant = path.read_bytes()
    app.text_input(key="cs_recherche").set_value("INTROUVABLE").run()
    assert not app.exception
    assert not any(b.key in {"cs_facturer", "cs_recevoir", "cs_envoyer"} for b in app.button)
    assert not any(getattr(x, "key", "") and x.key.startswith("cs_editeur")
                   for x in app.dataframe)
    assert path.read_bytes() == avant


def test_commandes_changement_patient_reinitialise_date_du_geste(commandes):
    app, _ = commandes
    app.date_input(key="cs_geste_date").set_value(date(2026, 1, 2)).run()
    cle = json.dumps(["CAMILLE TEST", "3400930000033", "GAMMA"], ensure_ascii=False)
    app.selectbox(key="cs_geste_dossier").select(cle).run()
    assert app.date_input(key="cs_geste_date").value == date.today()


def test_commandes_nouveau_dossier_accessible_et_conserve_les_existants(commandes):
    app, path = commandes
    app.button(key="cs_ouvrir_ajout").click().run()
    app.text_input(key="cs_nouveau_patient").set_value("NOUVEAU TEST")
    app.text_input(key="cs_nouveau_produit").set_value("DELTA")
    clic(app, "➕ Ouvrir le dossier")
    assert len(cs.charger(path)) == 4
    assert "NOUVEAU TEST" in table_html(app)


def test_tableau_html_ne_peut_pas_executer_un_nom_saisi():
    class Balises(HTMLParser):
        def __init__(self):
            super().__init__()
            self.balises = []
        def handle_starttag(self, tag, attrs):
            self.balises.append(tag)
    dangereux = '<img src=x onerror="alert(1)">\n\n<script>danger()</script>'
    html = ui_style.tableau_html(pd.DataFrame({"Patient": [dangereux], "Date": [pd.NaT]}), 'Suivi "test"')
    analyse = Balises()
    analyse.feed(html)
    assert "script" not in analyse.balises and "img" not in analyse.balises
    assert "&lt;img" in html and "NaT" not in html
    assert '<th scope="col">Patient</th>' in html


@pytest.mark.parametrize("espace", ["🔒  Stock interne", "💠  Commandes spéciales"])
def test_app_complete_ouvre_les_deux_espaces(tmp_path, monkeypatch, espace):
    import ui_stock_ferme
    import ui_commandes_speciales
    import ui_commun
    monkeypatch.setattr(ui_commun, "dossier_donnees", lambda: tmp_path)
    for module in [ui_stock_ferme, ui_commandes_speciales]:
        for nom in ["INVENTAIRE_PATH", "BASE_MEDICAMENTS_PATH", "REPERTOIRE_PATH", "DOSSIERS_PATH"]:
            if hasattr(module, nom):
                monkeypatch.setattr(module, nom, tmp_path / getattr(module, nom).name)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
    app.session_state["verifier_version"] = False
    app.session_state["espace_travail"] = espace
    app.run(timeout=20)
    assert not app.exception
    assert any('v6.38' in m.value for m in app.markdown)
