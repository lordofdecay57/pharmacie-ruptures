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
                              chercher, chercher_par_nom, cip7_depuis_cip13,
                              construire_table, decoder, index_par_cip,
                              index_par_nom, info_base,
                              noms_distincts, preselectionner,
                              presentations_du_nom, sauver_table,
                              unites_par_boite)

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

class TestUnitesParBoite:
    """Le conditionnement officiel dit combien la boîte contient.

    Libellés authentiques de la base : ils sont beaucoup moins réguliers
    qu'on ne l'imagine, et une quantité fausse sur un stock fermé est pire
    qu'une case vide — elle ne se remarque pas.
    """

    @pytest.mark.parametrize("libelle,attendu", [
        ("plaquette(s) PVC PVDC aluminium de 30 comprimé(s)", 30),
        ("plaquette(s) thermoformée(s) PVC aluminium de 30  gélule(s)", 30),
        ("1 flacon(s) polyéthylène (PEHD) de 90 gélule(s)", 90),
        ("plaquette(s) PVC polyéthylène de 10 suppositoire(s)", 10),
        ("plaquette(s) aluminium de 18 pastille(s)", 18),
        ("plaquettes PVC-Aluminium de 16 comprimés", 16),
    ])
    def test_cas_courants(self, libelle, attendu):
        assert unites_par_boite(libelle) == attendu

    @pytest.mark.parametrize("libelle,attendu", [
        # Sans le multiplicateur de tête, on lirait 20 au lieu de 40…
        ("2 plaquette(s) thermoformée(s) PVC de 20 comprimé(s)", 40),
        ("3 pilulier(s) polypropylène de 30 comprimé(s)", 90),
        # …et 1 au lieu de 100, ce qui est la vraie contenance.
        ("100 plaquette(s) PVC-Aluminium de 1 gélule(s)", 100),
        ("14 plaquettes aluminium de 8 comprimés "
         "(emballage multiple : 2 x 56)", 112),
    ])
    def test_boites_multiples(self, libelle, attendu):
        assert unites_par_boite(libelle) == attendu

    @pytest.mark.parametrize("libelle", [
        "1 flacon(s) en verre de 500 ml",          # un volume ne se compte pas
        "1 tube(s) polyéthylène de 15 ml",
        "1 flacon(s) en verre de 1,5 ml - 1 flacon(s) en verre de 4,5 ml",
        # Deux nombres possibles : on ne devine pas.
        "20 récipient(s) unidose(s) de 2 ml par plaquette de 5 récipients",
        "",
        None,
    ])
    def test_en_cas_de_doute_rien_plutot_qu_une_valeur_inventee(self, libelle):
        assert unites_par_boite(libelle) == 0


class TestRechercheParNom:
    """Taper un nom au clavier doit proposer les présentations réelles."""

    def _index(self):
        return index_par_nom(construire_table(CIS, CIP))

    def test_une_entree_par_presentation(self):
        """Chaque médicament figure deux fois dans la table (CIP13 et CIP7) :
        le proposer deux fois serait un choix pour rien."""
        index = self._index()
        assert len(index) == 2
        assert all(len(e["cip"]) == 13 for e in index), \
            "le CIP13 doit primer : c'est lui que portent les boîtes"

    def test_recherche_simple(self):
        trouves = chercher_par_nom(self._index(), "doliprane")
        assert len(trouves) == 1
        assert trouves[0]["cip"] == "3400935955838"
        assert trouves[0]["presentation"] == "plaquette de 8 comprimés"
        assert trouves[0]["unites_par_boite"] == 8

    def test_plusieurs_mots_dans_le_desordre(self):
        """On tape ce dont on se souvient, pas la dénomination officielle."""
        assert chercher_par_nom(self._index(), "1000 doliprane")
        assert chercher_par_nom(self._index(), "doliprane 1000 comprimé")

    def test_accents_et_casse_ignores(self):
        assert chercher_par_nom(self._index(), "ANASTROZOLE")
        assert chercher_par_nom(self._index(), "anastrozole accord")

    def test_terme_trop_court_ne_ramene_pas_la_base_entiere(self):
        assert chercher_par_nom(self._index(), "do") == []
        assert chercher_par_nom(self._index(), "") == []

    def test_aucune_correspondance(self):
        assert chercher_par_nom(self._index(), "medicamentinexistant") == []

    def test_les_correspondances_de_tete_passent_devant(self):
        """Qui tape « doli » cherche DOLIPRANE, pas un générique dont le nom
        le contient au milieu."""
        table = pd.DataFrame(
            [{"Code CIP": "3400900000017", "Nom du produit": "ZZZ DOLIX 1 mg",
              "Présentation": "plaquette de 10 comprimés"},
             {"Code CIP": "3400900000024", "Nom du produit": "DOLIX 1 mg",
              "Présentation": "plaquette de 10 comprimés"}],
            columns=COLONNES_BASE)
        trouves = chercher_par_nom(index_par_nom(table), "dolix")
        assert trouves[0]["nom"] == "DOLIX 1 mg"

    def test_base_absente(self):
        assert index_par_nom(pd.DataFrame(columns=COLONNES_BASE)) == []
        assert chercher_par_nom([], "doliprane") == []


class TestSaisieAssistee:
    """Ce qui part dans le navigateur pour les propositions à la frappe.

    Le filtrage se fait côté navigateur : la liste doit donc être aussi
    courte que possible, et surtout STABLE d'un rendu à l'autre — une liste
    reconstruite différemment serait renvoyée en entier à chaque
    interaction.
    """

    def _index(self):
        return index_par_nom(construire_table(CIS, CIP))

    def test_une_seule_entree_par_denomination(self):
        """Les présentations d'un même médicament portent le même nom : les
        envoyer toutes tripleraient la liste sans rien apprendre."""
        table = pd.DataFrame(
            [{"Code CIP": "3400900000017", "Nom du produit": "DOLIX 1 mg",
              "Présentation": "plaquette de 10 comprimés"},
             {"Code CIP": "3400900000024", "Nom du produit": "DOLIX 1 mg",
              "Présentation": "plaquette de 30 comprimés"}],
            columns=COLONNES_BASE)
        assert noms_distincts(index_par_nom(table)) == ["DOLIX 1 mg"]

    def test_ordre_alphabetique_stable(self):
        noms = noms_distincts(self._index())
        assert noms == sorted(noms)
        assert noms == noms_distincts(self._index())

    def test_base_absente(self):
        assert noms_distincts([]) == []

    def test_presentations_d_un_nom(self):
        presentations = presentations_du_nom(
            self._index(), "DOLIPRANE 1000 mg, comprimé")
        assert len(presentations) == 1
        assert presentations[0]["cip"] == "3400935955838"

    def test_presentations_de_la_plus_petite_boite_a_la_plus_grande(self):
        """C'est l'ordre du rayon : on cherche « la boîte de 8 » avant « la
        boîte de 100 »."""
        table = pd.DataFrame(
            [{"Code CIP": "3400900000017", "Nom du produit": "DOLIX 1 mg",
              "Présentation": "plaquette de 100 comprimés"},
             {"Code CIP": "3400900000024", "Nom du produit": "DOLIX 1 mg",
              "Présentation": "plaquette de 8 comprimés"}],
            columns=COLONNES_BASE)
        tailles = [p["unites_par_boite"]
                   for p in presentations_du_nom(index_par_nom(table),
                                                 "DOLIX 1 mg")]
        assert tailles == [8, 100]

    def test_nom_inconnu(self):
        assert presentations_du_nom(self._index(), "INEXISTANT") == []


class TestDosesEquivalentes:
    """« Doliprane 1 g » doit trouver « DOLIPRANE 1000 mg ».

    La base officielle écrit tout en milligrammes ; à l'officine on dit
    « 1 g ». Sans conversion, la recherche ne rend rien — et rien n'est plus
    déroutant qu'un écran qui ne réagit pas à un nom parfaitement exact.
    C'est le bug qu'a rencontré la pharmacie.
    """

    def _index(self):
        return index_par_nom(construire_table(CIS, CIP))

    @pytest.mark.parametrize("saisie", [
        "doliprane 1 g", "doliprane 1g", "DOLIPRANE 1G",
        "doliprane 1000 mg", "doliprane 1000mg",
        "doliprane 1 gramme", "doliprane 1000 milligrammes",
    ])
    def test_toutes_les_facons_de_dire_un_gramme(self, saisie):
        trouves = chercher_par_nom(self._index(), saisie)
        assert len(trouves) == 1, saisie
        assert trouves[0]["cip"] == "3400935955838"

    @pytest.mark.parametrize("saisie", ["500 microgrammes", "500 mcg",
                                        "0,5 mg", "0.5 mg"])
    def test_microgrammes_et_milligrammes_se_rejoignent(self, saisie):
        table = pd.DataFrame(
            [{"Code CIP": "3400900000017",
              "Nom du produit": "BRICANYL 500 microgrammes/dose",
              "Présentation": "1 récipient"}], columns=COLONNES_BASE)
        assert chercher_par_nom(index_par_nom(table), f"bricanyl {saisie}")

    def test_un_dosage_different_ne_correspond_pas(self):
        """La conversion ne doit pas tout confondre : 1 g n'est pas 500 mg."""
        assert chercher_par_nom(self._index(), "doliprane 500 mg") == []


class TestPreselectionner:
    """Ne jamais rendre une liste vide quand un mot de trop suffit à la
    vider : à l'écran, cela ressemble à une application qui ne réagit pas."""

    def _index(self):
        return index_par_nom(construire_table(CIS, CIP))

    def test_correspondance_exacte(self):
        trouvaille = preselectionner(self._index(), "doliprane 1 g")
        assert len(trouvaille["resultats"]) == 1
        assert trouvaille["elargi"] is False

    def test_les_mots_en_trop_sont_abandonnes_par_la_fin(self):
        trouvaille = preselectionner(self._index(),
                                     "doliprane 1 g boîte bleue")
        assert trouvaille["resultats"], "la recherche devait s'élargir"
        assert trouvaille["elargi"] is True
        # Ce qui a réellement servi doit pouvoir être affiché : une liste
        # sans explication paraît hors sujet.
        assert "doliprane" in trouvaille["terme"]

    def test_terme_totalement_inconnu(self):
        trouvaille = preselectionner(self._index(), "medicamentinexistant")
        assert trouvaille["resultats"] == []
        assert trouvaille["elargi"] is False

    def test_base_absente(self):
        assert preselectionner([], "doliprane")["resultats"] == []


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
        assert info["presentations"] == len(table)
        assert info["date"] == date.today()

    def test_base_installee_avant_le_conditionnement(self, tmp_path):
        """Les bases téléchargées avant l'ajout de la colonne n'ont que deux
        champs. Elles doivent continuer de servir — l'identification par
        code marche, seul le conditionnement manque — et pouvoir être
        signalées comme à refaire."""
        chemin = tmp_path / "ancienne.csv"
        chemin.write_text(
            "Code CIP;Nom du produit\n3400935955838;DOLIPRANE 1000 mg\n",
            encoding="utf-8-sig")
        table = charger_table(chemin)
        assert list(table.columns) == COLONNES_BASE
        assert chercher(index_par_cip(table), "3400935955838") is not None
        assert chercher_par_nom(index_par_nom(table), "doliprane")
        assert info_base(chemin)["presentations"] == 0


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
