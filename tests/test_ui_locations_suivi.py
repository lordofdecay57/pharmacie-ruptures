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
    assert [t.label for t in app.tabs][:4] == ["À faire", "Dossiers patients", "Facturation", "Réglages & essai"]
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
    facturation = next(t for t in app.tabs if t.label == "Facturation")
    assert champ(facturation, "date_input", "Date de demande d'entente préalable").value is None
    champ(facturation, "text_input", "Membre de l'équipe ayant initié la demande").set_value("Camille")
    champ(facturation, "date_input", "Date de demande d'entente préalable").set_value(date(2026, 9, 5))
    champ(app, "text_input", "Référence de la demande / du mail").set_value("EP-TEST")
    clic(app, "Enregistrer la demande")
    a = s.lire(path)["dossiers"][0]["accords"][0]
    assert (a["envoyee"], a["initiateur"], a["envoi_enregistre_par"]) == ("2026-09-05", "Camille", "Alex")
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


@pytest.mark.parametrize("manquant", ["date", "membre"])
def test_facturation_demande_date_et_membre_avant_enregistrement(tmp_path, monkeypatch, manquant):
    path = tmp_path / s.FICHIER
    s.initialiser(path)
    s.appliquer(path, "creer", acteur="Alex", patient="TEST ENTENTE", categorie="Matelas à air", debut=s.maintenant().date())
    app = ui(tmp_path, monkeypatch)
    champ(app, "text_input", "Votre nom").set_value("Alex").run()
    if manquant != "date":
        champ(app, "date_input", "Date de demande d'entente préalable").set_value(s.maintenant().date())
    champ(app, "text_input", "Membre de l'équipe ayant initié la demande").set_value("" if manquant == "membre" else "Camille")
    champ(app, "text_input", "Référence de la demande / du mail").set_value("EP-TEST")
    clic(app, "Enregistrer la demande")
    assert not s.lire(path)["dossiers"][0]["accords"]
    assert any(("date de demande" if manquant == "date" else "membre de l'équipe") in e.value for e in app.error)


def test_facturation_reprend_la_bonne_entente_meme_si_un_renouvellement_existe(tmp_path, monkeypatch):
    today = s.maintenant().date()
    path = tmp_path / s.FICHIER
    state = s.demonstration(today)
    d = state["dossiers"][0]
    origine = dict(d["accords"][0])
    s.ecrire_json(path, state)
    state = s.appliquer(path, "demander", identifiant=d["id"], acteur="Alex",
                        date=today, initiateur="Robin", reference="RENOUVELLEMENT-TEST")
    demande = state["dossiers"][0]["accords"][-1]
    suite = s.jour(origine["au"]) + timedelta(days=1)
    s.appliquer(path, "accorder", identifiant=d["id"], acteur="Alex",
                demande=demande["id"], reception=today, du=suite,
                au=s.ajouter_mois(suite, 6) - timedelta(days=1), reference="ACCORD-SUIVANT")
    avant = path.read_bytes()
    app = ui(tmp_path, monkeypatch)
    app.selectbox(key="ls_periode").select_index(0).run()
    assert not app.exception
    facturation = next(t for t in app.tabs if t.label == "Facturation")
    rappels = [x.value for x in facturation.dataframe
               if "Date de demande d'entente préalable" in x.value.columns]
    historique = next(t for t in rappels if len(t) == 2)
    periode = next(t for t in rappels if len(t) == 1)
    assert historique.iloc[1]["Membre de l'équipe"] == "Robin"
    assert periode.iloc[0]["Membre de l'équipe"] == origine["initiateur"]
    assert periode.iloc[0]["Date de demande d'entente préalable"] == (today - timedelta(days=15)).strftime("%d/%m/%Y")
    assert periode.iloc[0]["Reçue le"] == (today - timedelta(days=2)).strftime("%d/%m/%Y")
    assert path.read_bytes() == avant


def test_facturation_changement_dossier_ne_reprend_pas_une_demande_non_validee(tmp_path, monkeypatch):
    path = tmp_path / s.FICHIER
    s.initialiser(path)
    for patient in ("TEST A", "TEST B"):
        s.appliquer(path, "creer", acteur="Alex", patient=patient, categorie="Matelas à air", debut=s.maintenant().date())
    app = ui(tmp_path, monkeypatch)
    champ(app, "text_input", "Votre nom").set_value("Alex").run()
    champ(app, "date_input", "Date de demande d'entente préalable").set_value(s.maintenant().date() - timedelta(days=15))
    champ(app, "text_input", "Membre de l'équipe ayant initié la demande").set_value("Camille")
    champ(app, "text_input", "Référence de la demande / du mail").set_value("EP-A")
    autre = s.lire(path)["dossiers"][1]
    app.selectbox(key="ls_dossier_facturation").select(autre["id"]).run()
    assert not app.exception
    assert champ(app, "date_input", "Date de demande d'entente préalable").value is None
    assert champ(app, "text_input", "Membre de l'équipe ayant initié la demande").value == "Alex"
    assert champ(app, "text_input", "Référence de la demande / du mail").value == ""
    assert all(not d["accords"] for d in s.lire(path)["dossiers"])


def test_location_non_remboursable_reste_facturable_sans_entente(tmp_path, monkeypatch):
    path = tmp_path / s.FICHIER
    today = s.maintenant().date()
    s.initialiser(path)
    state = s.appliquer(path, "creer", acteur="Alex", patient="TEST PRIVE",
                        categorie="Tensiomètre", debut=today, prise="Non remboursable")
    d = state["dossiers"][0]
    s.appliquer(path, "qualifier", identifiant=d["id"], acteur="Alex",
                prise="Non remboursable", motif="Location privée vérifiée", date=today)
    app = ui(tmp_path, monkeypatch)
    facturation = next(t for t in app.tabs if t.label == "Facturation")
    assert not any(c.label == "Date de demande d'entente préalable" for c in facturation.date_input)
    champ(app, "text_input", "Votre nom").set_value("Alex").run()
    app.selectbox(key="ls_periode").select_index(0).run()
    champ(app, "text_input", "Référence de facture").set_value("PRIVE-TEST")
    clic(app, "Enregistrer la facture")
    state = s.lire(path)
    assert len(state["factures"]) == 1
    assert not state["dossiers"][0]["accords"]
