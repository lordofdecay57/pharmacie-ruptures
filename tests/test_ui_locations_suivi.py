from datetime import date, timedelta
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import locations_suivi as s
import rappels_location as mail


def ui(tmp_path, monkeypatch):
    import ui_location
    monkeypatch.setattr(ui_location, "DOSSIERS_PATH", tmp_path / "location.csv")
    return AppTest.from_string("import ui_location; ui_location.rendre(None, None)").run(timeout=20)


def champ(app, kind, label):
    return next(x for x in getattr(app, kind) if x.label == label)


def clic(app, label):
    champ(app, "button", label).click().run(timeout=20)
    assert not app.exception


def test_ecran_reel_nouveaux_onglets_et_cautions_aerosol(tmp_path, monkeypatch):
    app = ui(tmp_path, monkeypatch)
    assert not app.exception
    assert [t.label for t in app.tabs][:4] == ["À faire", "Dossiers patients", "Factures", "Réglages & essai"]
    champ(app, "selectbox", "Matériel").select("Aérosol").run()
    champ(app, "text_input", "Votre nom").set_value("Alex")
    champ(app, "text_input", "Patient").set_value("PATIENT TEST")
    clic(app, "Créer le dossier")
    d = s.lire(tmp_path / s.FICHIER)["dossiers"][0]
    assert d["caution"]["montant"] == 5000
    assert d["prise"] == "À vérifier"
    assert any("Aérosol : vérifiez" in item.value for item in app.info)
    assert champ(app, "selectbox", "Modalité de règlement de la caution").options == ["À préciser", "Chèque", "Espèces"]


def test_fauteuil_propose_achat_en_premier(tmp_path, monkeypatch):
    app = ui(tmp_path, monkeypatch)
    champ(app, "selectbox", "Matériel").select("Fauteuil roulant").run()
    assert champ(app, "selectbox", "Fourniture").value == "Achat"


def test_enregistrer_demande_auteur_et_reception_accord(tmp_path, monkeypatch):
    path = tmp_path / s.FICHIER
    s.initialiser(path)
    s.appliquer(path, "creer", acteur="Alex", patient="PATIENT TEST", categorie="Matelas à air", debut="2026-09-18")
    app = ui(tmp_path, monkeypatch)
    champ(app, "text_input", "Votre nom").set_value("Alex").run()
    champ(app, "text_input", "Demande initiée par").set_value("Camille")
    champ(app, "date_input", "Envoyée le").set_value(date(2026, 9, 5))
    champ(app, "text_input", "Référence de la demande / du mail").set_value("EP-TEST")
    clic(app, "Enregistrer la demande")
    a = s.lire(path)["dossiers"][0]["accords"][0]
    assert a["initiateur"] == "Camille"
    champ(app, "date_input", "Réponse reçue le").set_value(date(2026, 9, 18))
    champ(app, "date_input", "Couverture du").set_value(date(2026, 9, 18))
    champ(app, "date_input", "Couverture au (inclus)").set_value(date(2027, 3, 17))
    champ(app, "text_input", "Référence de l'accord / motif du refus").set_value("ACCORD-TEST")
    clic(app, "Enregistrer la réponse")
    a = s.lire(path)["dossiers"][0]["accords"][0]
    assert (a["initiateur"], a["enregistre_par"], a["reception"], a["au"]) == ("Camille", "Alex", "2026-09-18", "2027-03-17")


def test_dernier_mois_demande_confirmation_avant_facturation(tmp_path, monkeypatch):
    today = s.maintenant().date()
    state = s.demonstration(today)
    d = state["dossiers"][0]
    # Une seule période accordée, afin que la première soit aussi la dernière.
    d["accords"][0]["au"] = (s.ajouter_mois(s.jour(d["debut"]), 1) - timedelta(days=1)).isoformat()
    s.ecrire_json(tmp_path / s.FICHIER, state)
    app = ui(tmp_path, monkeypatch)
    app.selectbox(key="ls_periode").select_index(0).run()
    assert any("Dernière période" in w.value for w in app.warning)
    champ(app, "text_input", "Votre nom").set_value("Alex")
    champ(app, "text_input", "Référence de facture").set_value("F-1")
    clic(app, "Enregistrer la facture")
    assert not s.lire(tmp_path / s.FICHIER)["factures"]
    champ(app, "checkbox", "J'ai vérifié le montant et l'action de renouvellement").check()
    clic(app, "Enregistrer la facture")
    assert len(s.lire(tmp_path / s.FICHIER)["factures"]) == 1
    assert s.taches(s.lire(tmp_path / s.FICHIER), today)["renouveler"]


def test_caution_cheque_recue_puis_rendue_depuis_ecran(tmp_path, monkeypatch):
    path = tmp_path / s.FICHIER
    s.initialiser(path)
    s.appliquer(path, "creer", acteur="Alex", patient="TEST CAUTION", categorie="Tensiomètre", debut=s.maintenant().date())
    app = ui(tmp_path, monkeypatch)
    champ(app, "text_input", "Votre nom").set_value("Alex")
    champ(app, "text_input", "Référence du chèque ou du reçu de caisse").set_value("CH-1")
    clic(app, "Confirmer la réception de la caution")
    assert s.lire(path)["dossiers"][0]["caution"]["etat"] == "Reçue"
    champ(app, "text_input", "État de l'appareil et des accessoires").set_value("Complet")
    clic(app, "Matériel rendu")
    champ(app, "text_input", "Référence de restitution / reçu signé").set_value("Rendu signé")
    clic(app, "Confirmer le chèque rendu")
    assert s.lire(path)["dossiers"][0]["caution"]["etat"] == "Restituée"


def test_parametres_mail_stockes_uniquement_en_local(tmp_path, monkeypatch):
    app = ui(tmp_path, monkeypatch)
    champ(app, "text_input", "Adresse mail de la pharmacie").set_value("pharmacie@example.test")
    clic(app, "Enregistrer les rappels")
    cfg = mail.configuration(tmp_path)
    assert cfg["destinataire"] == "pharmacie@example.test"
    assert cfg["actif"] is False


def test_demo_ne_cree_pas_de_patient(tmp_path, monkeypatch):
    app = ui(tmp_path, monkeypatch)
    assert not app.exception
    assert s.lire(tmp_path / s.FICHIER)["dossiers"] == []
    assert any(len(table.value) == 6 and "Mois" in table.value.columns for table in app.dataframe)


def test_migration_visible_sans_facturation_auto(tmp_path, monkeypatch):
    (tmp_path / "location.csv").write_text("Patient;Matériel;Mode;Début de location;Dernière facturation\nTEST ANCIEN;Lit;Location;2026-01-01;2026-09-02\n")
    app = ui(tmp_path, monkeypatch)
    assert not app.exception
    assert any("ancienne version" in w.value for w in app.warning)
    assert not s.lire(tmp_path / s.FICHIER)["factures"]
