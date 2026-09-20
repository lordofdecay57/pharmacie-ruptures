"""Régressions des gestes Location, sur Streamlit sans navigateur externe."""

from datetime import date

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

import location as loc


def _dossiers():
    dossiers = loc.ajouter_dossier(
        None, "Patient A", "Lit", entente="2026-06-01", validite_mois=3)
    return loc.ajouter_dossier(
        dossiers, "Patient B", "Fauteuil", entente="2026-06-01",
        validite_mois=12)


def _ententes(dossiers):
    app = AppTest.from_string('''
import streamlit as st
from datetime import date
import location as loc
import ui_location as ui
dossiers = st.session_state["dossiers"]
vue = loc.vue_affichable(dossiers, date(2026, 9, 20))
ui._onglet_ententes(dossiers, vue, date(2026, 9, 20))
''')
    app.session_state["dossiers"] = dossiers
    return app.run()


def test_la_validite_suit_le_dossier_choisi():
    app = _ententes(_dossiers())
    assert app.number_input[0].value == 3
    app.selectbox[0].select_index(1).run()
    assert not app.exception
    assert app.number_input[0].value == 12


def test_une_duree_en_cours_de_saisie_reste_sur_le_meme_dossier():
    app = _ententes(_dossiers())
    app.number_input[0].set_value(9).run()
    assert not app.exception
    assert app.number_input[0].value == 9


def test_enregistrer_l_entente_modifie_le_bon_dossier_sur_disque(
        tmp_path, monkeypatch):
    import ui_location as ui
    chemin = tmp_path / "location.csv"
    monkeypatch.setattr(ui, "DOSSIERS_PATH", chemin)
    loc.sauver(_dossiers(), chemin)
    app = AppTest.from_string('''
from datetime import date
import location as loc
import ui_location as ui
dossiers = loc.charger(ui.DOSSIERS_PATH)
ui._onglet_ententes(dossiers,
    loc.vue_affichable(dossiers, date(2026, 9, 20)), date(2026, 9, 20))
''').run()
    app.selectbox[0].select_index(1).run()
    app.button[0].click().run()
    assert not app.exception
    relu = loc.charger(chemin).set_index("Patient")
    assert relu.loc["Patient B", "Validité (mois)"] == "12"
    assert relu.loc["Patient B", "Entente préalable"] == "2026-09-20"
    assert relu.loc["Patient A", "Validité (mois)"] == "3"
    assert relu.loc["Patient A", "Entente préalable"] == "2026-06-01"


def test_un_dossier_supprime_ne_redirige_pas_le_geste_vers_un_autre():
    dossiers = _dossiers()
    app = _ententes(dossiers)
    app.selectbox[0].select_index(1).run()
    app.session_state["dossiers"] = dossiers.iloc[:1]
    app.run()
    assert not app.exception
    assert app.selectbox[0].value is None
    assert not app.button


def test_la_date_de_facturation_ne_passe_pas_au_patient_suivant():
    app = AppTest.from_string('''
import streamlit as st
from datetime import date
import location as loc
import ui_location as ui
dossiers = st.session_state["dossiers"]
ui._onglet_facturations(dossiers,
    loc.vue_affichable(dossiers, date(2026, 9, 20)), date(2026, 9, 20))
''')
    app.session_state["dossiers"] = _dossiers()
    app.run()
    app.date_input[0].set_value(date(2026, 9, 5)).run()
    assert app.date_input[0].value == date(2026, 9, 5)
    app.selectbox[0].select_index(1).run()
    assert not app.exception
    assert app.date_input[0].value == date(2026, 9, 20)


def test_le_dossier_selectionne_ne_change_pas_apres_reclassement():
    dossiers = _dossiers()
    app = _ententes(dossiers)
    app.selectbox[0].select_index(1).run()
    # Une mise à jour sur un autre poste replace B devant A.
    dossiers = loc.enregistrer_entente(
        dossiers, "Patient B", "Fauteuil", date(2025, 1, 1), 12,
        loc.MODE_LOCATION)
    app.session_state["dossiers"] = dossiers
    app.run()
    assert not app.exception
    assert "Patient B" in app.selectbox[0].format_func(app.selectbox[0].value)


def test_un_tri_ne_rejoue_pas_une_correction_sur_un_autre_patient():
    app = AppTest.from_string('''
import streamlit as st
from datetime import date
import location as loc
import ui_location as ui
vue = loc.vue_affichable(st.session_state["dossiers"], date(2026, 9, 20))
if st.session_state.get("inverser", False):
    vue = vue.iloc[::-1].reset_index(drop=True)
st.session_state["correction"] = ui._tableau(vue)
''')
    app.session_state["dossiers"] = _dossiers()
    app.run()
    cle = app.get("dataframe")[0].key
    app.session_state[cle] = {
        "edited_rows": {0: {"Notes": "Note du patient A"}},
        "added_rows": [], "deleted_rows": []}
    app.run()
    assert app.session_state["correction"].iloc[0]["Notes"] == "Note du patient A"
    app.session_state["inverser"] = True
    app.run()
    assert not app.exception
    assert app.session_state["correction"] is None


def test_le_compteur_utilise_le_delai_d_alerte_choisi(tmp_path, monkeypatch):
    import ui_location as ui
    chemin = tmp_path / "location.csv"
    monkeypatch.setattr(ui, "DOSSIERS_PATH", chemin)
    loc.sauver(loc.ajouter_dossier(
        None, "Patient A", "Lit", entente="2026-04-01", validite_mois=6),
        chemin)
    app = AppTest.from_string('''
import ui_location as ui
from datetime import date
import location as loc
ui._bandeau(loc.resume(loc.charger(ui.DOSSIERS_PATH), date(2026, 9, 20), 5),
            lambda label, valeur, *args, **kwargs:
                f"{label}={valeur};{kwargs.get('sous', '')}", 5)
''')
    app.session_state["lo_date"] = date(2026, 9, 20)
    app.session_state["lo_alerte"] = 5
    app.run()
    assert not app.exception
    assert any("À renouveler=0;" in m.value for m in app.markdown)
    assert any("sous 5 jours" in m.value for m in app.markdown)
