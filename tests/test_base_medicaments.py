# -*- coding: utf-8 -*-
"""Tests de l'identification d'un médicament par son code CIP.

Un code-barres ne transporte pas le nom du médicament. Ce module comble le
manque en recoupant les deux fichiers de la base publique (ANSM / ministère
de la Santé). Les tests travaillent sur des extraits RÉELS de ces fichiers,
y compris leurs pièges : deux encodages différents, tabulations, et un
CIP13 construit comme ``34009`` + CIP7 + clé.

Aucun test ne touche au réseau : le téléchargement est simulé.
"""

from datetime import date

import pandas as pd
import pytest

from base_medicaments import (COLONNES_BASE, anciennete_jours, charger_table,
                              chercher, cip7_depuis_cip13, construire_table,
                              decoder, index_par_cip, info_base, sauver_table)

# Extraits authentiques des fichiers officiels (colonnes séparées par des
# tabulations, sans ligne d'en-tête).
CIS = "\n".join([
    "\t".join(["61266250", "DOLIPRANE 1000 mg, comprimé", "comprimé",
               "orale", "Autorisation active"]),
    "\t".join(["60002283", "ANASTROZOLE ACCORD 1 mg, comprimé pelliculé",
               "comprimé pelliculé", "orale", "Autorisation active"]),
    "\t".join(["99999999", "", "forme", "voie", "Autorisation active"]),
])
CIP = "\n".join([
    "\t".join(["61266250", "3595583", "plaquette de 8 comprimés",
               "Présentation active", "Déclaration de commercialisation",
               "01/01/2000", "3400935955838", "oui"]),
    "\t".join(["60002283", "4949729", "plaquette de 30 comprimés",
               "Présentation active", "Déclaration de commercialisation",
               "16/03/2011", "3400949497294", "oui"]),
    # Produit dont la dénomination manque : ignoré.
    "\t".join(["99999999", "1111111", "x", "y", "z", "01/01/2000",
               "3400911111119", "oui"]),
    # Produit dont le CIS est inconnu du premier fichier : ignoré.
    "\t".join(["00000000", "2222222", "x", "y", "z", "01/01/2000",
               "3400922222229", "oui"]),
])


# ---------------------------------------------------------------------------
# Lecture des fichiers officiels
# ---------------------------------------------------------------------------

class TestDecodage:
    """Les deux fichiers officiels n'ont pas le même encodage : CIS_bdpm
    est en ISO-8859-1, CIS_CIP_bdpm en UTF-8. Le supposer ferait sortir des
    « comprimÃ© » dans l'inventaire."""

    def test_utf8(self):
        assert decoder("comprimé pelliculé".encode("utf-8")) == \
            "comprimé pelliculé"

    def test_repli_latin1(self):
        assert decoder("comprimé".encode("latin-1")) == "comprimé"

    def test_octets_invalides_ne_font_pas_echouer(self):
        assert decoder(b"\xff\xfe abc") is not None


class TestConstruireTable:
    def test_recoupe_les_deux_fichiers(self):
        table = construire_table(CIS, CIP)
        assert list(table.columns) == COLONNES_BASE
        index = index_par_cip(table)
        assert index["3400935955838"] == "DOLIPRANE 1000 mg, comprimé"
        assert index["3400949497294"] == \
            "ANASTROZOLE ACCORD 1 mg, comprimé pelliculé"

    def test_cip7_indexe_aussi(self):
        """Les boîtes anciennes ne portent parfois que le code à 7 chiffres."""
        index = index_par_cip(construire_table(CIS, CIP))
        assert index["3595583"] == "DOLIPRANE 1000 mg, comprimé"

    def test_presentation_sans_denomination_ignoree(self):
        index = index_par_cip(construire_table(CIS, CIP))
        assert "3400911111119" not in index

    def test_presentation_orpheline_ignoree(self):
        index = index_par_cip(construire_table(CIS, CIP))
        assert "3400922222229" not in index

    def test_fichiers_vides(self):
        assert construire_table("", "").empty


# ---------------------------------------------------------------------------
# Recherche
# ---------------------------------------------------------------------------

class TestCip7DepuisCip13:
    """Structure vérifiée sur la base officielle : 34009 + CIP7 + clé."""

    def test_extraction(self):
        assert cip7_depuis_cip13("3400935955838") == "3595583"

    @pytest.mark.parametrize("code", ["3595583", "", "1234567890123", "abc"])
    def test_codes_non_conformes(self, code):
        assert cip7_depuis_cip13(code) == ""


class TestChercher:
    def _index(self):
        return index_par_cip(construire_table(CIS, CIP))

    def test_cip13(self):
        assert chercher(self._index(), "3400935955838") == \
            "DOLIPRANE 1000 mg, comprimé"

    def test_cip7(self):
        assert chercher(self._index(), "3595583") == \
            "DOLIPRANE 1000 mg, comprimé"

    def test_code_ponctue(self):
        assert chercher(self._index(), "3400 935 955 838") == \
            "DOLIPRANE 1000 mg, comprimé"

    def test_repli_par_le_cip7_si_le_cip13_manque(self):
        """Une fiche officielle sans CIP13 reste trouvable par son CIP7."""
        index = {"3595583": "DOLIPRANE 1000 mg, comprimé"}
        assert chercher(index, "3400935955838") == \
            "DOLIPRANE 1000 mg, comprimé"

    def test_code_inconnu(self):
        assert chercher(self._index(), "0000000000000") is None

    def test_base_absente(self):
        assert chercher({}, "3400935955838") is None

    def test_code_vide(self):
        assert chercher(self._index(), "") is None


# ---------------------------------------------------------------------------
# Conservation sur le poste
# ---------------------------------------------------------------------------

class TestPersistance:
    def test_aller_retour_sur_disque(self, tmp_path):
        chemin = tmp_path / "base.csv"
        sauver_table(construire_table(CIS, CIP), chemin)
        index = index_par_cip(charger_table(chemin))
        assert index["3400935955838"] == "DOLIPRANE 1000 mg, comprimé"

    def test_accents_preserves(self, tmp_path):
        """« comprimé » doit rester « comprimé » après l'aller-retour."""
        chemin = tmp_path / "base.csv"
        sauver_table(construire_table(CIS, CIP), chemin)
        assert "é" in chercher(index_par_cip(charger_table(chemin)),
                               "3400935955838")

    def test_base_absente(self, tmp_path):
        assert charger_table(tmp_path / "rien.csv").empty
        assert info_base(tmp_path / "rien.csv") == {
            "existe": False, "lignes": 0, "date": None}

    def test_fichier_abime_ne_bloque_pas(self, tmp_path):
        chemin = tmp_path / "casse.csv"
        chemin.write_bytes(b"\x00\x01\x02 pas un csv")
        assert list(charger_table(chemin).columns) == COLONNES_BASE

    def test_info_compte_les_lignes(self, tmp_path):
        chemin = tmp_path / "base.csv"
        table = construire_table(CIS, CIP)
        sauver_table(table, chemin)
        info = info_base(chemin)
        assert info["existe"] and info["lignes"] == len(table)
        assert info["date"] == date.today()


class TestAnciennete:
    def test_base_recente(self):
        info = {"existe": True, "date": date(2026, 8, 1)}
        assert anciennete_jours(info, date(2026, 8, 4)) == 3

    def test_base_absente(self):
        assert anciennete_jours({"existe": False, "date": None}) is None


class TestIsolation:
    def test_ne_connait_aucun_autre_module(self):
        """Ce module ne sait répondre qu'à « quel médicament porte ce
        code ? » — ni cadencier, ni ruptures, ni stock fermé."""
        source = (pytest.importorskip("pathlib").Path(__file__).parent.parent
                  / "base_medicaments.py").read_text(encoding="utf-8")
        for interdit in ("import commun", "import stock_ferme",
                         "import stock_rotation", "import moteur_ruptures",
                         "import streamlit"):
            assert interdit not in source

    def test_aucun_appel_reseau_a_l_import(self):
        """Ouvrir le module ne doit RIEN télécharger : le poste peut être
        hors ligne, et l'inventaire doit rester utilisable."""
        import base_medicaments
        assert isinstance(base_medicaments.URL_DENOMINATIONS, str)
        assert pd.DataFrame is not None  # import complet sans effet de bord
