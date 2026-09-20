from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
import copy
import json

import pytest

import locations_suivi as s
import rappels_location as mail

TODAY = date(2026, 9, 20)


def cas(tmp_path):
    path = tmp_path / s.FICHIER
    state = s.demonstration(TODAY)
    s.ecrire_json(path, state)
    return path, state, state["dossiers"][0]


def agir(path, d, action, **kw):
    return s.appliquer(path, action, identifiant=d["id"], acteur="Alex", **kw)


def facture(path, d, p, **kw):
    data = dict(periode=p["id"], date=p["echeance"], reference="F-" + str(p["numero"]), montant=1234, confirme=True)
    data.update(kw)
    return agir(path, d, "facturer", **data)


def test_scenario_six_mois_et_alerte_apres_sixieme_facture(tmp_path):
    path, state, d = cas(tmp_path)
    a = d["accords"][0]
    assert a["envoyee"] == "2026-09-05"
    assert a["reception"] == "2026-09-18"
    assert a["initiateur"] == "Camille (exemple)"
    ps = s.periodes(state, d, TODAY, toutes=True)
    assert len(ps) == 6
    assert ps[-1]["du"] == "2027-02-18"
    assert ps[-1]["au"] == "2027-03-17"
    assert [p["dernier"] for p in ps] == [False] * 5 + [True]
    for p in ps:
        state = facture(path, d, p)
    assert not s.taches(state, date(2027, 2, 18))["facturer"]
    assert len(s.taches(state, date(2027, 2, 18))["renouveler"]) == 1
    assert not s.taches(state, date(2027, 4, 1))["facturer"]


def test_facture_tardive_ne_decale_pas_les_periodes(tmp_path):
    path, state, d = cas(tmp_path)
    p = s.periodes(state, d, TODAY)[0]
    state = facture(path, d, p, date="2026-10-22")
    todo = s.taches(state, date(2026, 10, 22))["facturer"]
    assert [p["du"] for p in todo] == ["2026-10-18"]
    assert state["factures"][0]["etat"] == "Émise"
    assert state["factures"][0]["reglement"] is None


def test_un_seul_enregistrement_si_deux_postes_facturent(tmp_path):
    path, state, d = cas(tmp_path)
    p = s.periodes(state, d, TODAY)[0]
    def faire(_):
        try:
            facture(path, d, p)
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(faire, range(2))) == [False, True]
    assert len(s.lire(path)["factures"]) == 1


def test_relecture_refuse_une_modification_perimee(tmp_path):
    path, state, d = cas(tmp_path)
    agir(path, d, "demander", date=TODAY, reference="renouvellement")
    with pytest.raises(ValueError, match="autre poste"):
        s.appliquer(path, "qualifier", identifiant=d["id"], revision=0, acteur="Pat",
                    prise="Non remboursable", motif="vérifié", date=TODAY)


def test_demande_renouvellement_conserve_auteur_initial_et_alerte(tmp_path):
    path, state, d = cas(tmp_path)
    state = agir(path, d, "demander", date="2027-02-18", reference="REN-1")
    relu = state["dossiers"][0]
    assert relu["accords"][0]["initiateur"] == "Camille (exemple)"
    assert relu["accords"][1]["initiateur"] == "Alex"
    assert s.taches(state, date(2027, 2, 18))["renouveler"][0]["demande_en_cours"]
    state = agir(path, d, "accorder", demande=relu["accords"][1]["id"], reception="2027-02-20",
                 du="2027-03-18", au="2027-09-17", reference="ACCORD-2")
    assert not s.taches(state, date(2027, 2, 20))["renouveler"]


def test_un_trou_entre_deux_accords_reste_visible(tmp_path):
    path, state, d = cas(tmp_path)
    state = agir(path, d, "couverture", du="2027-04-01", au="2027-09-30", date="2027-03-20", reference="accord futur")
    assert s.taches(state, date(2027, 3, 20))["renouveler"][0]["fin"] == "2027-03-17"
    ps = s.periodes(state, state["dossiers"][0], date(2027, 4, 1))
    assert any("Accord ne couvrant pas toute la période" in p["blocages"] for p in ps)


def test_qualification_ne_signifie_pas_remboursement_integral(tmp_path):
    path, state, d = cas(tmp_path)
    state = agir(path, d, "qualifier", prise="À vérifier", motif="dossier à examiner", date=TODAY)
    assert not s.taches(state, TODAY)["facturer"]
    assert s.taches(state, TODAY)["completer"]


@pytest.mark.parametrize("categorie,somme", [("Aérosol", 5000), ("Tensiomètre", 3000)])
@pytest.mark.parametrize("mode", ["Chèque", "Espèces"])
def test_caution_distincte_loyer_et_restituee_explicitement(tmp_path, categorie, somme, mode):
    path = tmp_path / s.FICHIER
    s.initialiser(path)
    state = s.appliquer(path, "creer", acteur="Alex", patient="Patient fictif", categorie=categorie,
                        debut=TODAY, appareil="APP-1")
    d = state["dossiers"][0]
    assert d["prise"] == "À vérifier"
    assert d["caution"]["montant"] == somme
    state = agir(path, d, "caution_prevoir", montant=somme, mode=mode)
    assert state["dossiers"][0]["caution"]["etat"] == "À recevoir"
    state = agir(path, d, "caution_recevoir", mode=mode, date=TODAY, reference="RECU-1")
    assert not state["factures"]
    state = agir(path, d, "retour", date=TODAY + timedelta(days=1), etat="Complet, à nettoyer")
    assert state["dossiers"][0]["caution"]["etat"] == "Reçue"
    assert state["materiels"]["APP-1"]["etat"] == "À préparer"
    assert s.taches(state, TODAY)["cautions"] == [d["id"]]
    state = agir(path, d, "caution_restituer", date=TODAY + timedelta(days=1), reference="Rendu au patient")
    assert state["dossiers"][0]["caution"]["etat"] == "Restituée"
    assert not s.taches(state, TODAY)["cautions"]
    with pytest.raises(ValueError):
        agir(path, d, "caution_restituer", date=TODAY, reference="doublon")


def test_materiel_impossible_a_attribuer_deux_fois_ou_avant_controle(tmp_path):
    path = tmp_path / s.FICHIER
    s.initialiser(path)
    args = dict(categorie="Aérosol", debut=TODAY, appareil="A1")
    state = s.appliquer(path, "creer", acteur="Alex", patient="A", **args)
    with pytest.raises(ValueError, match="déjà attribué"):
        s.appliquer(path, "creer", acteur="Alex", patient="B", **args)
    agir(path, state["dossiers"][0], "retour", date=TODAY, etat="Conforme")
    with pytest.raises(ValueError, match="contrôle"):
        s.appliquer(path, "creer", acteur="Alex", patient="B", **args)
    s.appliquer(path, "disponible", acteur="Alex", appareil="A1", date=TODAY)
    state = s.appliquer(path, "creer", acteur="Alex", patient="B", **args)
    assert len(state["dossiers"]) == 2


def test_achat_fauteuil_par_defaut_une_facture_et_un_reglement_distincts(tmp_path):
    path = tmp_path / s.FICHIER
    s.initialiser(path)
    state = s.appliquer(path, "creer", acteur="Alex", patient="Patient A", categorie="Fauteuil roulant", debut=TODAY)
    d = state["dossiers"][0]
    assert d["mode"] == "Achat"
    state = agir(path, d, "qualifier", prise="Non remboursable", motif="Achat privé vérifié", date=TODAY)
    p = s.taches(state, TODAY)["facturer"][0]
    state = facture(path, d, p)
    assert not s.taches(state, date(2028, 1, 1))["facturer"]
    f = state["factures"][0]
    assert f["etat"] == "Émise"
    state = agir(path, d, "regler", facture=f["id"], date=TODAY, reference="CB-1")
    assert state["factures"][0]["etat"] == "Réglée"


def test_migration_ne_cree_aucune_facture_et_preserve_csv(tmp_path):
    csv = tmp_path / "location.csv"
    original = "Patient;Matériel;Mode;Début de location;Dernière facturation;Notes\nMme A;Matelas;Location;2026-01-01;2026-09-02;À conserver\n"
    csv.write_text(original)
    path = tmp_path / s.FICHIER
    state = s.initialiser(path, csv)
    d = state["dossiers"][0]
    assert d["source_ancienne"]["Dernière facturation"] == "2026-09-02"
    assert not s.taches(state, date(2027, 1, 1))["facturer"]
    assert csv.read_text() == original
    assert s.initialiser(path, csv) == state
    state = agir(path, d, "reprendre", debut="2026-01-01", debut_suivi="2026-10-01", justification="Facture jusqu'au 30/09")
    state = agir(path, d, "qualifier", prise="Non remboursable", motif="contrat privé", date=TODAY)
    assert not s.taches(state, TODAY)["facturer"]
    assert s.taches(state, date(2026, 10, 1))["facturer"][0]["du"] == "2026-10-01"


def test_achat_historique_deja_facture_sans_nouvelle_facture(tmp_path):
    csv = tmp_path / "location.csv"
    csv.write_text("Patient;Matériel;Mode;Début de location;Dernière facturation\nA;Fauteuil;Achat;2026-01-01;2026-02-01\n")
    path = tmp_path / s.FICHIER
    state = s.initialiser(path, csv)
    state = agir(path, state["dossiers"][0], "reprendre", debut="2026-01-01", debut_suivi="2026-01-01", justification="Facture F-1 vérifiée", achat_deja_facture=True)
    assert not s.taches(state, date(2027, 1, 1))["facturer"]
    assert not s.taches(state, date(2027, 1, 1))["completer"]


def test_fichier_corrompu_jamais_remplace_par_un_dossier_vide(tmp_path):
    path = tmp_path / s.FICHIER
    path.write_text('{"schema":')
    with pytest.raises(ValueError, match="illisible"):
        s.initialiser(path)
    assert path.read_text() == '{"schema":'


def test_retour_en_cours_de_periode_signale_regularisation(tmp_path):
    path, state, d = cas(tmp_path)
    state = facture(path, d, s.periodes(state, d, TODAY)[0])
    state = agir(path, d, "retour", date="2026-09-25", etat="Complet")
    assert s.taches(state, TODAY)["regulariser"] == [state["factures"][0]["id"]]
    assert state["factures"][0]["au"] == "2026-10-17"


def test_annulation_conserve_facture_et_rouvre_la_periode(tmp_path):
    path, state, d = cas(tmp_path)
    state = facture(path, d, s.periodes(state, d, TODAY)[0])
    state = agir(path, d, "annuler_facture", facture=state["factures"][0]["id"], motif="Erreur référence, avoir A-1")
    assert len(s.taches(state, TODAY)["facturer"]) == 1
    assert state["factures"][0]["etat"] == "Annulée"


def test_31_janvier_ne_derive_pas_en_mars():
    state = s.vide()
    d = s.nouveau("A", "Tensiomètre", date(2026, 1, 31), "Alex", fin_prevue="2026-04-30")
    state["dossiers"].append(d)
    ps = s.periodes(state, d, date(2026, 5, 1), toutes=True)
    assert [p["du"] for p in ps] == ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"]


def test_reprise_fin_fevrier_conserve_l_ancre_du_31_janvier():
    state = s.vide()
    d = s.nouveau("A", "Tensiomètre", date(2026, 1, 31), "Alex", fin_prevue="2026-04-30")
    d["debut_suivi"] = "2026-02-28"
    state["dossiers"].append(d)
    assert [p["du"] for p in s.periodes(state, d, date(2026, 5, 1), toutes=True)] == ["2026-02-28", "2026-03-31", "2026-04-30"]


def config_mail(tmp_path):
    cfg = mail.configuration(tmp_path)
    cfg.update(actif=True, destinataire="officine@example.test", expediteur="service@example.test",
               hote="smtp.example.test", heure="08:00", jours=list(range(7)))
    mail.enregistrer_configuration(tmp_path, cfg)
    return cfg


def test_aucun_envoi_avant_configuration(tmp_path):
    cas(tmp_path)
    assert mail.executer(tmp_path, transport=lambda *a: pytest.fail("mail inattendu")) == "désactivé"


def test_mail_destinataire_et_contenu_sans_patient(tmp_path):
    _, state, d = cas(tmp_path)
    cfg = config_mail(tmp_path)
    msg = mail.composer(state, cfg, TODAY)
    assert msg["To"] == "officine@example.test"
    assert d["patient"] not in msg.get_content()
    assert "1 période(s)" in msg.get_content()


def test_mail_unique_sur_deux_processus_et_jour_local(tmp_path):
    cas(tmp_path)
    config_mail(tmp_path)
    envois = []
    now = datetime(2026, 9, 20, 9, tzinfo=s.NOUMEA)
    def envoi(_):
        return mail.executer(tmp_path, instant=now, transport=lambda *a: envois.append(True))
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(envoi, range(2))) == ["Envoyé", "déjà tenté"]
    assert len(envois) == 1


def test_echec_smtp_ne_refait_pas_une_tentative_ambigue(tmp_path):
    cas(tmp_path)
    config_mail(tmp_path)
    def echec(*a):
        raise TimeoutError("Résultat inconnu")
    now = datetime(2026, 9, 20, 9, tzinfo=s.NOUMEA)
    assert mail.executer(tmp_path, instant=now, transport=echec).startswith("Échec")
    assert mail.executer(tmp_path, instant=now, transport=lambda *a: pytest.fail("doublon")) == "déjà tenté"
    assert not s.lire(tmp_path / s.FICHIER)["factures"]


def test_horaire_noumea_et_absence_de_taches(tmp_path):
    cas(tmp_path)
    config_mail(tmp_path)
    assert mail.executer(tmp_path, instant=datetime(2026, 9, 20, 7, tzinfo=s.NOUMEA)) == "hors horaire"
    s.ecrire_json(tmp_path / s.FICHIER, s.vide())
    assert mail.executer(tmp_path, instant=datetime(2026, 9, 20, 9, tzinfo=s.NOUMEA)) == "rien à rappeler"


def test_factures_deja_emises_absentes_du_rappel(tmp_path):
    path, state, d = cas(tmp_path)
    cfg = config_mail(tmp_path)
    state = facture(path, d, s.periodes(state, d, TODAY)[0])
    assert mail.composer(state, cfg, TODAY) is None


def test_configuration_interdit_injection_entete_et_secret_dans_json(tmp_path, monkeypatch):
    cfg = config_mail(tmp_path)
    cfg["destinataire"] = "a@example.test\nBcc:evil@example.test"
    with pytest.raises(ValueError):
        mail.enregistrer_configuration(tmp_path, cfg)
    cfg["destinataire"] = "a@example.test"
    cfg["password"] = "ne-jamais-ecrire"
    mail.enregistrer_configuration(tmp_path, cfg)
    assert "ne-jamais-ecrire" not in (tmp_path / mail.CONFIG).read_text()


@pytest.mark.parametrize("valeur", [-1, 2.5, float("inf"), "x"])
def test_montants_invalides_refuses(valeur):
    with pytest.raises(ValueError):
        s.montant(valeur)
