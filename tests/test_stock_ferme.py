# -*- coding: utf-8 -*-
"""Tests du Module 3 — Gestion d'un stock interne (stock_ferme.py).

Deux points font tout l'intérêt de ce module et sont donc couverts en
priorité :

- la lecture du **Data Matrix GS1** des boîtes (CIP + péremption + lot en un
  seul scan), y compris quand la douchette n'émet pas le séparateur FNC1 ;
- le fait que la **péremption appartient à la boîte** : deux boîtes du même
  médicament qui n'expirent pas le même jour restent deux lignes distinctes.

Comme les deux autres modules, celui-ci est testé de façon AUTONOME : aucun
test n'a besoin du cadencier ni des fichiers de ruptures fournisseurs.
"""

from datetime import date

import pytest

from stock_ferme import (COLONNES_STOCK_FERME, EntreeStock, STATUT_CRITIQUE,
                         STATUT_IMMINENT, STATUT_INCONNU, STATUT_OK,
                         STATUT_PERIME,
                         STATUTS_A_TRAITER, STATUT_VIGILANCE, TRIS, TRI_NOM,
                         TRI_PEREMPTION,
                         ajouter_entree, charger_inventaire,
                         charger_repertoire, cip_depuis_gtin, cle_lot,
                         exporter_csv, exporter_pdf, filtrer_inventaire,
                         inventaire_affichable,
                         importer_repertoire, inventaire_vide,
                         jours_avant_peremption,
                         lot_a_sortir, lots_sortables,
                         memoriser_produit, nom_fichier_stock_ferme,
                         normaliser_tableau_edite,
                         parser_code_scanne, parser_datamatrix,
                         parser_peremption_saisie, produit_connu,
                         repertoire_vide, resume_inventaire, retirer_entree,
                         sauver_inventaire, sauver_repertoire,
                         sortir_unites, statut_peremption, total_unites,
                         COLONNES_ESSENTIELLES, vue_essentielle,
                         unites_disponibles, vrac_sans_boite)

AUJOURDHUI = date(2026, 7, 31)
GS = "\x1d"


# ---------------------------------------------------------------------------
# Lecture des codes scannés
# ---------------------------------------------------------------------------

class TestDataMatrix:
    """Le cas nominal : la douchette lit le Data Matrix de la boîte."""

    def test_gtin_peremption_et_lot(self):
        # 01 = GTIN(14) · 17 = péremption(6) · 10 = lot (variable, FNC1)
        code = parser_datamatrix("01034009123456781728022910ABC123" + GS)
        assert code is not None
        assert code.cip == "3400912345678"
        assert code.peremption == date(2028, 2, 29)
        assert code.lot == "ABC123"
        assert code.format == "datamatrix"

    def test_jour_hors_calendrier_ramene_en_fin_de_mois(self):
        """Codes mal générés (31/02) : mieux vaut la fin du mois que rien."""
        assert parser_datamatrix(
            "0103400912345678" + "17280231").peremption == date(2028, 2, 29)

    def test_ordre_des_champs_indifferent(self):
        code = parser_datamatrix("10LOT9" + GS + "0103400912345678" + "17280229")
        assert code.cip == "3400912345678"
        assert code.lot == "LOT9"
        assert code.peremption == date(2028, 2, 29)

    def test_numero_de_serie_lu(self):
        code = parser_datamatrix(
            "0103400912345678" + "17271130" + "10L1" + GS + "21SN0001")
        assert code.serie == "SN0001"
        assert code.lot == "L1"

    def test_prefixe_de_symbologie_retire(self):
        code = parser_datamatrix("]d20103400912345678" + "17271130")
        assert code is not None and code.cip == "3400912345678"

    def test_separateur_fnc1_absent(self):
        """Certaines douchettes n'émettent pas le GS : le lot ne doit pas
        avaler la péremption qui le suit."""
        code = parser_datamatrix("010340091234567810LOT4217271130")
        assert code.cip == "3400912345678"
        assert code.lot == "LOT42"
        assert code.peremption == date(2027, 11, 30)

    @pytest.mark.parametrize("code,lot,serie", [
        # Cas réel : lot PUIS série, aucun séparateur émis.
        ("010340093700001317270930101234AB21987654321", "1234AB", "987654321"),
        # Le n° de série ne doit pas être amputé de son dernier caractère.
        ("01034009123456782199988877710LOT9", "LOT9", "999888777"),
        # Rien après le lot : il court jusqu'au bout.
        ("010340091234567817271130" + "10ABC123", "ABC123", ""),
        # Lot entièrement numérique, indiscernable d'un identifiant.
        ("010340091234567817271130" + "10220518", "220518", ""),
    ])
    def test_lot_et_serie_sans_separateur(self, code, lot, serie):
        """Sans FNC1, la lecture retenue est celle qui n'abandonne aucun
        caractère inexpliqué — pas la première coupe plausible."""
        lu = parser_datamatrix(code)
        assert (lu.lot, lu.serie) == (lot, serie)

    def test_jour_00_signifie_fin_de_mois(self):
        code = parser_datamatrix("0103400912345678" + "17270300")
        assert code.peremption == date(2027, 3, 31)

    def test_contenu_non_gs1_refuse(self):
        assert parser_datamatrix("BONJOUR") is None
        assert parser_datamatrix("") is None

    def test_gtin_seul_accepte(self):
        code = parser_datamatrix("0103400912345678")
        assert code is not None and code.peremption is None


class TestCipDepuisGtin:
    def test_zero_de_tete_retire(self):
        assert cip_depuis_gtin("03400912345678") == "3400912345678"

    def test_gtin14_etranger_conserve(self):
        assert cip_depuis_gtin("13400912345678") == "13400912345678"

    def test_cip13_inchange(self):
        assert cip_depuis_gtin("3400912345678") == "3400912345678"


class TestCodeScanne:
    def test_code_barres_lineaire_cip13(self):
        code = parser_code_scanne("3400912345678")
        assert code.format == "cip13"
        assert code.cip == "3400912345678"
        assert code.peremption is None  # à saisir à la main

    def test_ancien_cip7(self):
        code = parser_code_scanne("1234567")
        assert code.format == "cip7" and code.cip == "1234567"

    def test_datamatrix_prioritaire_sur_le_lineaire(self):
        code = parser_code_scanne("0103400912345678" + "17280229")
        assert code.format == "datamatrix"
        assert code.peremption == date(2028, 2, 29)

    @pytest.mark.parametrize("saisie", ["3400 912 345 678", "3400-912-345-678",
                                        "3400.912.345.678"])
    def test_code_recopie_a_la_main_avec_separateurs(self, saisie):
        """Un CIP relevé sur la boîte est souvent espacé ou ponctué."""
        code = parser_code_scanne(saisie)
        assert code.format == "cip13" and code.cip == "3400912345678"

    @pytest.mark.parametrize("saisie", ["DOLIPRANE 1000", "12 34", "AB123456789"])
    def test_texte_libre_non_pris_pour_un_code(self, saisie):
        assert not parser_code_scanne(saisie).reconnu

    def test_contenu_inconnu_signale_sans_perte(self):
        code = parser_code_scanne("DOLIPRANE 1000")
        assert not code.reconnu
        assert code.brut == "DOLIPRANE 1000"

    def test_scan_vide(self):
        assert parser_code_scanne("").format == "inconnu"


class TestPeremptionSaisie:
    @pytest.mark.parametrize("saisie,attendu", [
        ("15/03/2027", date(2027, 3, 15)),
        ("03/2027", date(2027, 3, 31)),   # sans jour → fin de mois
        ("2027-03", date(2027, 3, 31)),
        ("2027-03-15", date(2027, 3, 15)),
        ("03/27", date(2027, 3, 31)),
        ("02/2028", date(2028, 2, 29)),   # année bissextile
    ])
    def test_formats_acceptes(self, saisie, attendu):
        assert parser_peremption_saisie(saisie) == attendu

    @pytest.mark.parametrize("saisie,attendu", [
        ("032027", date(2027, 3, 31)),      # MMAAAA — le cas courant
        ("15032027", date(2027, 3, 15)),    # JJMMAAAA
        ("0327", date(2027, 3, 31)),        # MMAA — le plus court
        ("150327", date(2027, 3, 15)),      # JJMMAA
        ("022028", date(2028, 2, 29)),      # année bissextile
    ])
    def test_les_barres_obliques_sont_facultatives(self, saisie, attendu):
        """Deux frappes par boîte, une date par boîte : sur un inventaire
        complet, taper les « / » fait des centaines de frappes pour rien."""
        assert parser_peremption_saisie(saisie) == attendu

    @pytest.mark.parametrize("saisie", [
        "132027",          # ni mois 13, ni jour 13 + mois 20
        "3400935955838",   # un code CIP tapé dans la mauvaise case
        "00000000",
        "3102",            # « mois » 31
        "12345",           # longueur qui ne veut rien dire
    ])
    def test_chiffres_qui_ne_font_pas_une_date(self, saisie):
        assert parser_peremption_saisie(saisie) is None

    def test_six_chiffres_tranches_par_le_sens(self):
        """« 082027 » est un mois puis une année ; « 310827 » un jour, un
        mois et une année courte. Un mois vaut au plus 12 — cela suffit à
        les distinguer sans rien demander."""
        assert parser_peremption_saisie("082027") == date(2027, 8, 31)
        assert parser_peremption_saisie("310827") == date(2027, 8, 31)

    def test_mois_invalide_refuse(self):
        assert parser_peremption_saisie("13/2027") is None

    @pytest.mark.parametrize("saisie", [
        "31129999", "31/12/9999", "082207", "00019999", "01/2100", "01/1989",
    ])
    def test_annee_invraisemblable_refusee(self, saisie):
        """Une faute de frappe sur l'année passait sans un mot, et la boîte
        s'affichait « OK » pour toujours — invisible en bas de la liste.
        Mieux vaut faire retaper la date."""
        assert parser_peremption_saisie(saisie) is None

    @pytest.mark.parametrize("saisie,attendu", [
        ("01/1990", date(1990, 1, 31)),     # une boîte périmée depuis
        ("01/2099", date(2099, 1, 31)),     # longtemps reste enregistrable
    ])
    def test_les_bornes_elles_memes_restent_acceptees(self, saisie, attendu):
        assert parser_peremption_saisie(saisie) == attendu

    def test_date_deja_typee_conservee(self):
        assert parser_peremption_saisie(date(2027, 5, 4)) == date(2027, 5, 4)

    def test_valeur_vide(self):
        assert parser_peremption_saisie("") is None
        assert parser_peremption_saisie(None) is None


# ---------------------------------------------------------------------------
# Comptage
# ---------------------------------------------------------------------------

class TestTotalUnites:
    def test_boites_pleines_et_vrac(self):
        assert total_unites(boites=3, unites_par_boite=30, unites_vrac=12) == 102

    def test_conditionnement_inconnu_ne_convertit_pas(self):
        """Sans unités/boîte, on ne devine pas : seul le vrac est compté."""
        assert total_unites(boites=3, unites_par_boite=0, unites_vrac=12) == 12

    def test_valeurs_negatives_ignorees(self):
        assert total_unites(-2, 30, -5) == 0


# ---------------------------------------------------------------------------
# Inventaire : une ligne par (produit, péremption, lot)
# ---------------------------------------------------------------------------

def _entree(**kw):
    # Le dosage fait partie du NOM, comme dans la base publique — il n'a
    # plus de colonne à lui. Les rares tests qui vérifient le repli du
    # dosage dans le nom le passent explicitement.
    base = dict(cip="3400912345678", nom="DOLIPRANE", dosage="",
                boites=1, unites_par_boite=8, unites_vrac=0,
                peremption=date(2027, 6, 30), lot="A1")
    base.update(kw)
    return EntreeStock(**base)


class TestAjouterEntree:
    def test_premiere_entree(self):
        inv = ajouter_entree(inventaire_vide(), _entree(), AUJOURDHUI)
        assert len(inv) == 1
        assert list(inv.columns) == COLONNES_STOCK_FERME
        assert inv.iloc[0]["Total unités"] == 8
        assert inv.iloc[0]["Enregistré le"] == AUJOURDHUI

    def test_meme_lot_scanne_deux_fois_incremente(self):
        inv = ajouter_entree(inventaire_vide(), _entree(), AUJOURDHUI)
        inv = ajouter_entree(inv, _entree(), AUJOURDHUI)
        assert len(inv) == 1
        assert inv.iloc[0]["Boîtes"] == 2
        assert inv.iloc[0]["Total unités"] == 16

    def test_peremptions_differentes_font_deux_lignes(self):
        """Le cœur du module : la date appartient à la boîte."""
        inv = ajouter_entree(inventaire_vide(), _entree(), AUJOURDHUI)
        inv = ajouter_entree(inv, _entree(peremption=date(2028, 1, 31)),
                             AUJOURDHUI)
        assert len(inv) == 2
        assert set(inv["Péremption"]) == {date(2027, 6, 30), date(2028, 1, 31)}

    def test_lots_differents_font_deux_lignes(self):
        inv = ajouter_entree(inventaire_vide(), _entree(), AUJOURDHUI)
        inv = ajouter_entree(inv, _entree(lot="B2"), AUJOURDHUI)
        assert len(inv) == 2

    def test_nom_deja_connu_conserve_si_le_scan_est_muet(self):
        inv = ajouter_entree(inventaire_vide(),
                             _entree(nom="DOLIPRANE", dosage="1000 mg"),
                             AUJOURDHUI)
        inv = ajouter_entree(inv, _entree(nom="", dosage=""), AUJOURDHUI)
        # Le dosage a rejoint le nom : une colonne de moins, rien de perdu.
        assert inv.iloc[0]["Nom du produit"] == "DOLIPRANE 1000 mg"

    def test_produit_sans_cip_identifie_par_son_nom(self):
        inv = ajouter_entree(inventaire_vide(),
                             _entree(cip="", nom="PRÉPARATION MAGISTRALE"),
                             AUJOURDHUI)
        inv = ajouter_entree(inv, _entree(cip="", nom="préparation magistrale"),
                             AUJOURDHUI)
        assert len(inv) == 1 and inv.iloc[0]["Boîtes"] == 2

    def test_vrac_seul_sans_boite(self):
        inv = ajouter_entree(inventaire_vide(),
                             _entree(boites=0, unites_vrac=5), AUJOURDHUI)
        assert inv.iloc[0]["Total unités"] == 5


class TestRetirerEntree:
    def test_decremente_le_lot(self):
        inv = ajouter_entree(inventaire_vide(), _entree(boites=3), AUJOURDHUI)
        inv = retirer_entree(inv, "3400912345678", "DOLIPRANE",
                             date(2027, 6, 30), "A1", boites=1)
        assert inv.iloc[0]["Boîtes"] == 2
        assert inv.iloc[0]["Total unités"] == 16

    def test_ligne_a_zero_disparait(self):
        inv = ajouter_entree(inventaire_vide(), _entree(boites=1), AUJOURDHUI)
        inv = retirer_entree(inv, "3400912345678", "DOLIPRANE",
                             date(2027, 6, 30), "A1", boites=1)
        assert inv.empty

    def test_ne_descend_pas_sous_zero(self):
        inv = ajouter_entree(inventaire_vide(),
                             _entree(boites=1, unites_vrac=3), AUJOURDHUI)
        inv = retirer_entree(inv, "3400912345678", "DOLIPRANE",
                             date(2027, 6, 30), "A1", boites=9)
        assert inv.iloc[0]["Boîtes"] == 0 and inv.iloc[0]["Unités en vrac"] == 3

    def test_lot_absent_sans_effet(self):
        inv = ajouter_entree(inventaire_vide(), _entree(), AUJOURDHUI)
        assert len(retirer_entree(inv, "9999999999999", "X", None, "")) == 1

    def test_inventaire_vide_reste_vide(self):
        assert retirer_entree(inventaire_vide(), "1", "X", None, "").empty


class TestTableauEdite:
    """Corrections faites à la main directement dans le tableau."""

    def _vue(self):
        inv = ajouter_entree(inventaire_vide(), _entree(boites=1), AUJOURDHUI)
        return inventaire_affichable(inv, AUJOURDHUI)

    def test_colonnes_de_lecture_retirees(self):
        propre = normaliser_tableau_edite(self._vue())
        assert list(propre.columns) == COLONNES_STOCK_FERME

    def test_quantite_corrigee_recalcule_le_total(self):
        vue = self._vue()
        vue.loc[0, "Boîtes"] = 4
        propre = normaliser_tableau_edite(vue)
        assert propre.iloc[0]["Boîtes"] == 4
        assert propre.iloc[0]["Total unités"] == 32

    def test_quantite_saisie_en_texte(self):
        vue = self._vue()
        vue.loc[0, "Boîtes"] = "3"
        assert normaliser_tableau_edite(vue).iloc[0]["Boîtes"] == 3

    def test_saisie_illisible_ramenee_a_zero(self):
        vue = self._vue()
        vue.loc[0, "Boîtes"] = "trois"
        assert normaliser_tableau_edite(vue).iloc[0]["Boîtes"] == 0

    def test_quantite_negative_ramenee_a_zero(self):
        vue = self._vue()
        vue.loc[0, "Unités en vrac"] = -7
        assert normaliser_tableau_edite(vue).iloc[0]["Unités en vrac"] == 0

    def test_ligne_ajoutee_vide_abandonnee(self):
        vue = self._vue()
        vue.loc[len(vue)] = {c: None for c in vue.columns}
        assert len(normaliser_tableau_edite(vue)) == 1

    def test_ligne_supprimee_disparait(self):
        assert normaliser_tableau_edite(self._vue().iloc[0:0]).empty

    def test_peremption_corrigee_relue(self):
        vue = self._vue()
        vue.loc[0, "Péremption"] = "12/2029"
        assert (normaliser_tableau_edite(vue).iloc[0]["Péremption"]
                == date(2029, 12, 31))

    def test_tableau_inchange_reste_identique(self):
        vue = self._vue()
        propre = normaliser_tableau_edite(vue)
        assert propre.iloc[0]["Nom du produit"] == "DOLIPRANE"
        assert propre.iloc[0]["Péremption"] == date(2027, 6, 30)
        assert propre.iloc[0]["Total unités"] == 8


class TestLotASortir:
    """Sortie de stock à la douchette : quelle boîte part ?"""

    def _inventaire(self):
        inv = inventaire_vide()
        for lot, peremption, boites in (("A1", date(2027, 6, 30), 3),
                                        ("B2", date(2026, 9, 15), 2),
                                        ("C3", date(2028, 1, 31), 1)):
            inv = ajouter_entree(inv, _entree(lot=lot, peremption=peremption,
                                              boites=boites), AUJOURDHUI)
        return inv

    def test_data_matrix_designe_la_boite_exacte(self):
        cible = lot_a_sortir(self._inventaire(), cip="3400912345678",
                             peremption=date(2027, 6, 30), lot="A1")
        assert (cible["lot"], cible["exact"], cible["boites"]) == ("A1", True, 3)

    def test_code_lineaire_sort_le_lot_qui_perime_le_plus_tot(self):
        """FEFO : sans quoi un lot vieillirait au fond de l'armoire."""
        cible = lot_a_sortir(self._inventaire(), cip="3400912345678")
        assert cible["lot"] == "B2"
        assert cible["peremption"] == date(2026, 9, 15)

    def test_lot_scanne_absent_replie_sur_fefo_en_le_signalant(self):
        cible = lot_a_sortir(self._inventaire(), cip="3400912345678",
                             lot="INEXISTANT")
        assert cible["lot"] == "B2"
        assert cible["exact"] is False  # l'interface doit le dire

    def test_lot_sans_date_passe_en_dernier(self):
        inv = ajouter_entree(self._inventaire(),
                             _entree(lot="SANSDATE", peremption=None),
                             AUJOURDHUI)
        assert lot_a_sortir(inv, cip="3400912345678")["lot"] == "B2"

    def test_produit_sans_cip_identifie_par_son_nom(self):
        inv = ajouter_entree(inventaire_vide(),
                             _entree(cip="", nom="PRÉPARATION"), AUJOURDHUI)
        assert lot_a_sortir(inv, nom="préparation")["nom"] == "PRÉPARATION"

    def test_produit_absent(self):
        assert lot_a_sortir(self._inventaire(), cip="9999999999999") is None

    def test_inventaire_vide(self):
        assert lot_a_sortir(inventaire_vide(), cip="3400912345678") is None

    def test_sortie_complete_puis_lot_suivant(self):
        """Deux scans successifs vident le lot le plus proche, puis passent
        naturellement au suivant."""
        inv = self._inventaire()
        for _ in range(2):
            cible = lot_a_sortir(inv, cip="3400912345678")
            inv = retirer_entree(inv, cible["cip"], cible["nom"],
                                 cible["peremption"], cible["lot"], boites=1)
        assert "B2" not in list(inv["Lot"])            # lot épuisé, ligne ôtée
        assert lot_a_sortir(inv, cip="3400912345678")["lot"] == "A1"


class TestUnLotEntameNEstPasUneBoite:
    """Une boîte ouverte n'a plus de boîte à sortir — et le disait quand même.

    Le geste : on dispense trois comprimés d'une boîte de dix (la ligne
    passe à zéro boîte, sept unités en vrac), puis on douche cette même
    boîte en mode Sortie. ``retirer_entree`` retirait alors « une boîte »
    de zéro — ``max(0, 0 - 1)`` — l'inventaire ne bougeait pas d'un iota,
    et l'écran annonçait en vert « 1 boîte sortie ».

    Pire avec plusieurs lots : la règle FEFO élisait le lot entamé, le plus
    proche de la péremption, et la douchette ne sortait plus RIEN, même
    avec quatre boîtes pleines sur la ligne d'à côté. Un stupéfiant sorti
    de l'armoire et resté à l'inventaire, sans un mot.
    """

    NOM = "DOLIPRANE"
    CIP = "3400912345678"
    PEREMPTION = date(2027, 1, 31)

    def _entame(self, boites=1, par_boite=10, unites=3, lot="ENTAME"):
        inv = ajouter_entree(inventaire_vide(),
                             _entree(lot=lot, peremption=self.PEREMPTION,
                                     boites=boites,
                                     unites_par_boite=par_boite), AUJOURDHUI)
        inv, _ = sortir_unites(inv, self.CIP, self.NOM, self.PEREMPTION, lot,
                               unites)
        return inv

    def test_le_lot_entame_n_a_plus_de_boite(self):
        inv = self._entame()
        assert int(inv.loc[0, "Boîtes"]) == 0
        assert int(inv.loc[0, "Unités en vrac"]) == 7

    def test_il_n_est_plus_propose_a_la_sortie(self):
        """Le seul lot du produit est entamé : il n'y a pas de boîte à
        sortir, et le dire vaut mieux que ne rien faire en silence."""
        assert lot_a_sortir(self._entame(), cip=self.CIP) is None

    def test_meme_designe_precisement_par_son_data_matrix(self):
        """Le Data Matrix nomme CETTE boîte — elle n'est plus entière."""
        assert lot_a_sortir(self._entame(), cip=self.CIP,
                            peremption=self.PEREMPTION, lot="ENTAME") is None

    def test_fefo_saute_le_lot_entame_et_prend_le_suivant(self):
        """LE cas qui perdait des boîtes : le lot entamé périme le premier,
        FEFO le choisissait, et rien ne sortait alors que quatre boîtes
        pleines attendaient juste à côté."""
        inv = self._entame()
        inv = ajouter_entree(inv, _entree(lot="PLEIN", boites=4,
                                          peremption=date(2028, 6, 30)),
                             AUJOURDHUI)
        cible = lot_a_sortir(inv, cip=self.CIP)
        assert cible is not None and cible["lot"] == "PLEIN"
        apres = retirer_entree(inv, cible["cip"], cible["nom"],
                               cible["peremption"], cible["lot"], boites=1)
        assert int(apres[apres["Lot"] == "PLEIN"]["Boîtes"].iloc[0]) == 3

    def test_le_vrac_reste_sortable_a_l_unite(self):
        """On écarte le lot de la sortie EN BOÎTE, pas de l'inventaire :
        ses sept comprimés se dispensent toujours."""
        inv = self._entame()
        assert unites_disponibles(inv, self.CIP, self.NOM,
                                  self.PEREMPTION, "ENTAME") == 7

    def test_vrac_sans_boite_permet_de_dire_la_verite(self):
        """« Ce produit n'est pas à l'inventaire » serait faux : il reste
        sept comprimés. Ce n'est pas la même réponse, ni le même geste."""
        assert vrac_sans_boite(self._entame(), cip=self.CIP) == 7

    def test_le_vrac_d_un_lot_encore_entier_ne_compte_pas(self):
        """Un lot qui GARDE une boîte se sort à la douchette : ses unités
        en vrac n'ont pas à apparaître dans le message de repli."""
        inv = self._entame(boites=2)          # une entamée, une entière
        assert int(inv.loc[0, "Boîtes"]) == 1
        assert vrac_sans_boite(inv, cip=self.CIP) == 0

    def test_produit_absent_n_a_pas_de_vrac(self):
        assert vrac_sans_boite(self._entame(), cip="9999999999999") == 0


class TestCleLot:
    def test_lot_insensible_a_la_casse(self):
        assert (cle_lot("340", "X", date(2027, 1, 1), "a1")
                == cle_lot("340", "X", date(2027, 1, 1), "A1"))

    def test_nom_ignore_quand_le_cip_est_connu(self):
        assert (cle_lot("340", "DOLIPRANE", None, "")
                == cle_lot("340", "AUTRE NOM", None, ""))


# ---------------------------------------------------------------------------
# Péremptions
# ---------------------------------------------------------------------------

class TestStatutPeremption:
    @pytest.mark.parametrize("peremption,attendu", [
        (date(2026, 7, 30), STATUT_PERIME),       # hier
        (date(2026, 7, 31), STATUT_IMMINENT),     # aujourd'hui : pas périmé
        (date(2026, 8, 15), STATUT_IMMINENT),     # 15 j
        (date(2026, 8, 30), STATUT_IMMINENT),     # 30 j pile
        (date(2026, 8, 31), STATUT_CRITIQUE),     # 31 j
        (date(2026, 10, 29), STATUT_CRITIQUE),    # 90 j pile
        (date(2026, 10, 30), STATUT_VIGILANCE),   # 91 j
        (date(2026, 11, 30), STATUT_VIGILANCE),   # 122 j
        (date(2027, 1, 27), STATUT_VIGILANCE),    # 180 j pile
        (date(2027, 1, 28), STATUT_OK),           # 181 j
        (date(2027, 6, 30), STATUT_OK),
        (None, STATUT_INCONNU),
    ])
    def test_feu_de_circulation(self, peremption, attendu):
        assert statut_peremption(peremption, AUJOURDHUI) == attendu

    def test_jours_restants_negatifs_si_perime(self):
        assert jours_avant_peremption(date(2026, 7, 21), AUJOURDHUI) == -10


class TestInventaireAffichable:
    def test_tri_par_peremption_la_plus_proche(self):
        inv = inventaire_vide()
        for jour, nom in ((date(2028, 1, 31), "TARD"),
                          (date(2026, 8, 5), "TOT"),
                          (None, "SANS DATE")):
            inv = ajouter_entree(inv, _entree(nom=nom, peremption=jour,
                                              lot=nom), AUJOURDHUI)
        vue = inventaire_affichable(inv, AUJOURDHUI)
        assert list(vue["Nom du produit"]) == ["TOT", "TARD", "SANS DATE"]

    def test_colonnes_de_lecture_ajoutees(self):
        vue = inventaire_affichable(
            ajouter_entree(inventaire_vide(), _entree(), AUJOURDHUI),
            AUJOURDHUI)
        assert vue.columns[0] == "Statut"
        assert "Jours restants" in vue.columns

    def test_inventaire_vide(self):
        assert inventaire_affichable(inventaire_vide(), AUJOURDHUI).empty

    def test_cellules_vides_d_un_fichier_ne_s_affichent_pas_en_nan(self):
        """Un CSV relu porte des NaN : ils doivent rester des cases vides,
        pas devenir « nan » à l'écran ni « None » à l'impression."""
        import pandas as pd
        brut = pd.DataFrame([{"Nom du produit": "PRÉPARATION", "Dosage": None,
                              "Code CIP": None, "Lot": None, "Boîtes": 2,
                              "Unités par boîte": 0, "Unités en vrac": 0,
                              "Total unités": 0, "Péremption": date(2027, 1, 1),
                              "Enregistré le": AUJOURDHUI}])
        vue = inventaire_affichable(brut, AUJOURDHUI)
        assert vue.iloc[0]["Code CIP"] == "" and vue.iloc[0]["Lot"] == ""
        texte = exporter_csv(brut, AUJOURDHUI).decode("utf-8-sig")
        assert "nan" not in texte.lower() and "None" not in texte
        # Un produit sans CIP compte quand même comme une référence.
        assert resume_inventaire(brut, AUJOURDHUI)["references"] == 1


class TestDosageDansLeNom:
    """Le dosage n'a plus de colonne : il fait partie du nom.

    Il figure déjà dans la dénomination officielle (« DOLIPRANE 1000 mg,
    comprimé ») ; une colonne pour le répéter poussait la péremption — la
    seule qui compte vraiment ici — hors de l'écran.
    """

    def test_le_dosage_saisi_rejoint_le_nom(self):
        inv = ajouter_entree(inventaire_vide(),
                             _entree(nom="MORPHINE", dosage="10 mg/mL"),
                             AUJOURDHUI)
        assert inv.iloc[0]["Nom du produit"] == "MORPHINE 10 mg/mL"
        assert inv.iloc[0]["Dosage"] == ""

    def test_un_dosage_deja_dans_le_nom_n_est_pas_repete(self):
        """Sinon une ligne réaffichée finirait par « DOLIPRANE 1 g 1 g »."""
        inv = ajouter_entree(inventaire_vide(),
                             _entree(nom="DOLIPRANE 1 g", dosage="1 g"),
                             AUJOURDHUI)
        assert inv.iloc[0]["Nom du produit"] == "DOLIPRANE 1 g"

    def test_aucune_colonne_dosage_a_l_affichage(self):
        vue = inventaire_affichable(
            ajouter_entree(inventaire_vide(), _entree(), AUJOURDHUI),
            AUJOURDHUI)
        assert "Dosage" not in vue.columns
        assert "Péremption" in vue.columns

    def test_inventaire_vide_a_les_memes_colonnes(self):
        """Un tableau vide et un tableau rempli doivent avoir la même forme,
        sans quoi l'affichage change de colonnes au premier scan."""
        vide = inventaire_affichable(inventaire_vide(), AUJOURDHUI)
        rempli = inventaire_affichable(
            ajouter_entree(inventaire_vide(), _entree(), AUJOURDHUI),
            AUJOURDHUI)
        assert list(vide.columns) == list(rempli.columns)

    def test_un_lot_sans_cip_reste_retrouvable_apres_le_repli(self):
        """Le vrai piège : l'identité d'un lot sans code CIP repose sur son
        nom. Si l'affichage montre « PRÉPARATION 5 % » pendant que le fichier
        dit « PRÉPARATION », la sortie ne décrémente rien."""
        inv = ajouter_entree(inventaire_vide(),
                             _entree(cip="", nom="PRÉPARATION", dosage="5 %"),
                             AUJOURDHUI)
        lot = lots_sortables(inv, AUJOURDHUI)[0]
        apres = retirer_entree(inv, lot["cip"], lot["nom"], lot["peremption"],
                               lot["lot"], boites=1)
        assert len(apres) == 0, "la boîte devait sortir de l'inventaire"

    def test_reprise_d_un_ancien_fichier(self, tmp_path):
        """Les inventaires écrits avant la disparition de la colonne sont
        repliés à la relecture, une fois pour toutes."""
        import pandas as pd
        chemin = tmp_path / "ancien.csv"
        pd.DataFrame([{"Nom du produit": "MORPHINE", "Dosage": "10 mg/mL",
                       "Code CIP": "", "Boîtes": 2, "Unités par boîte": 0,
                       "Unités en vrac": 0, "Total unités": 0,
                       "Péremption": "2027-06-30", "Lot": "A1",
                       "Enregistré le": "2026-07-31"}]).to_csv(
            chemin, index=False, sep=";", encoding="utf-8-sig")
        relu = charger_inventaire(chemin)
        assert relu.iloc[0]["Nom du produit"] == "MORPHINE 10 mg/mL"
        assert relu.iloc[0]["Dosage"] == ""


class TestVueEssentielle:
    """L'inventaire de tous les jours : trois colonnes, rien de plus.

    Demande de la pharmacie, mot pour mot : « au niveau de l'inventaire
    affiché on doit avoir seulement le nom du médicament, son CIP et
    savoir s'il est périmé, rien de plus ».

    Onze colonnes tenaient là — boîtes, unités par boîte, vrac, total,
    lot, date d'enregistrement, jours restants. Devant l'armoire on ne
    cherche que deux choses : est-ce le bon produit, et est-il encore
    bon.
    """

    def _inventaire(self):
        inv = inventaire_vide()
        for nom, cip, peremption in (
                ("ZOLPIDEM", "3400930000011", date(2020, 1, 1)),
                ("AMOXICILLINE", "3400930000028", date(2028, 1, 31))):
            inv = ajouter_entree(inv, _entree(nom=nom, cip=cip,
                                              peremption=peremption),
                                 AUJOURDHUI)
        return inv

    def test_exactement_trois_colonnes(self):
        vue = vue_essentielle(self._inventaire(), AUJOURDHUI)
        assert list(vue.columns) == ["Statut", "Nom du produit", "Code CIP"]
        assert list(vue.columns) == COLONNES_ESSENTIELLES

    def test_un_inventaire_vide_garde_ses_colonnes(self):
        """Sans elles, le tableau vide s'afficherait sans en-tête et on
        croirait l'écran cassé."""
        assert list(vue_essentielle(inventaire_vide()).columns) \
            == COLONNES_ESSENTIELLES

    def test_le_perime_se_voit(self):
        """« Savoir s'il est périmé » : c'est la seule des trois colonnes
        qui ne se lit pas sur la boîte."""
        vue = vue_essentielle(self._inventaire(), AUJOURDHUI)
        statuts = dict(zip(vue["Nom du produit"], vue["Statut"]))
        assert statuts["ZOLPIDEM"] == STATUT_PERIME
        assert statuts["AMOXICILLINE"] == STATUT_OK

    def test_aucune_ligne_n_est_perdue(self):
        """On retire des COLONNES, jamais un lot : un inventaire qui cache
        des lignes ne serait plus un inventaire."""
        inv = self._inventaire()
        complete = inventaire_affichable(inv, AUJOURDHUI)
        assert len(vue_essentielle(inv, AUJOURDHUI)) == len(complete)

    def test_le_meme_ordre_que_la_vue_complete(self):
        """Les deux tableaux sont l'un sous l'autre à l'écran : deux ordres
        différents feraient chercher la même ligne deux fois."""
        inv = self._inventaire()
        for tri in (TRI_PEREMPTION, TRI_NOM):
            essentielle = vue_essentielle(inv, AUJOURDHUI, tri)
            complete = inventaire_affichable(inv, AUJOURDHUI, tri)
            assert list(essentielle["Nom du produit"]) \
                == list(complete["Nom du produit"]), tri

    def test_le_dosage_reste_fondu_dans_le_nom(self):
        """Il fait partie de la dénomination : deux boîtes du même produit
        ne se distinguent que par lui."""
        inv = ajouter_entree(
            inventaire_vide(),
            _entree(nom="DOLIPRANE", dosage="1000 mg"), AUJOURDHUI)
        assert vue_essentielle(inv, AUJOURDHUI)["Nom du produit"][0] \
            == "DOLIPRANE 1000 mg"


class TestSortieALUnite:
    """Dispenser dix comprimés ne retire pas la boîte de trente.

    Au comptoir, une boîte s'entame : les vingt comprimés qui restent sont
    toujours dans l'armoire. Retirer la boîte entière les ferait disparaître
    de l'inventaire — c'est-à-dire les recommander pour rien, ou les laisser
    périmer sans jamais les voir.
    """

    def _lot(self, boites=2, par_boite=30, vrac=0):
        return ajouter_entree(
            inventaire_vide(),
            _entree(nom="ZOLPIDEM", cip="3400930000011", lot="Z1",
                    boites=boites, unites_par_boite=par_boite,
                    unites_vrac=vrac, peremption=date(2027, 6, 30)),
            AUJOURDHUI)

    def _sortir(self, inv, unites):
        return sortir_unites(inv, "3400930000011", "ZOLPIDEM",
                             date(2027, 6, 30), "Z1", unites)

    def _dispo(self, inv):
        return unites_disponibles(inv, "3400930000011", "ZOLPIDEM",
                                  date(2027, 6, 30), "Z1")

    def test_le_vrac_part_avant_qu_une_boite_soit_entamee(self):
        """Une seconde boîte ouverte pendant qu'un fond de boîte traîne,
        c'est du périmé annoncé."""
        apres, pris = self._sortir(self._lot(boites=2, vrac=5), 3)
        assert pris == 3
        assert int(apres.at[0, "Boîtes"]) == 2
        assert int(apres.at[0, "Unités en vrac"]) == 2

    def test_une_boite_s_entame_quand_le_vrac_ne_suffit_pas(self):
        apres, pris = self._sortir(self._lot(boites=2, vrac=0), 10)
        assert pris == 10
        assert int(apres.at[0, "Boîtes"]) == 1
        assert int(apres.at[0, "Unités en vrac"]) == 20
        assert int(apres.at[0, "Total unités"]) == 50

    def test_plusieurs_boites_s_enchainent(self):
        apres, pris = self._sortir(self._lot(boites=3, vrac=0), 65)
        assert pris == 65
        assert int(apres.at[0, "Boîtes"]) == 0
        assert int(apres.at[0, "Unités en vrac"]) == 25

    def test_on_ne_sort_jamais_plus_que_le_stock(self):
        """Promettre une sortie que l'inventaire ne peut pas honorer, c'est
        un inventaire faux dès le lendemain."""
        apres, pris = self._sortir(self._lot(boites=1, vrac=0), 45)
        assert pris == 30
        assert apres.empty

    def test_la_ligne_disparait_une_fois_videe(self):
        """Un stock interne se contrôle boîte à boîte : une ligne à zéro n'est
        que du bruit sur la liste imprimée."""
        apres, pris = self._sortir(self._lot(boites=0, vrac=12), 12)
        assert pris == 12
        assert apres.empty

    def test_sans_conditionnement_les_boites_ne_se_convertissent_pas(self):
        """Sans « unités par boîte », on ne sait pas ce que contient une
        boîte. L'inventer donnerait un stock d'unités imaginaire."""
        apres, pris = self._sortir(self._lot(boites=2, par_boite=0, vrac=4), 10)
        assert pris == 4
        assert int(apres.at[0, "Boîtes"]) == 2
        assert int(apres.at[0, "Unités en vrac"]) == 0

    def test_un_lot_inconnu_ne_touche_a_rien(self):
        inv = self._lot()
        apres, pris = sortir_unites(inv, "3400999999999", "INCONNU",
                                    date(2027, 6, 30), "X", 5)
        assert pris == 0
        assert int(apres.at[0, "Boîtes"]) == 2

    def test_une_demande_nulle_ne_touche_a_rien(self):
        apres, pris = self._sortir(self._lot(), 0)
        assert pris == 0
        assert int(apres.at[0, "Boîtes"]) == 2

    def test_le_maximum_propose_est_le_stock_reel(self):
        """C'est le plafond du champ de l'écran : au-dessus, on proposerait
        une sortie impossible."""
        assert self._dispo(self._lot(boites=2, par_boite=30, vrac=5)) == 65
        assert self._dispo(self._lot(boites=2, par_boite=0, vrac=4)) == 4
        assert self._dispo(inventaire_vide()) == 0

    def test_le_disponible_suit_les_sorties(self):
        inv = self._lot(boites=2, vrac=0)
        apres, _ = self._sortir(inv, 10)
        assert self._dispo(apres) == 50


class TestLotsSortables:
    """Sortie sans douchette : désigner la boîte dans une liste.

    Le bouton de saisie manuelle était purement désactivé en mode Sortie.
    Une étiquette abîmée, une boîte reconditionnée, un produit sans code —
    et il n'existait plus aucune façon de retirer une boîte.
    """

    def _inventaire(self):
        inv = inventaire_vide()
        for nom, cip, lot, peremption, boites in (
                ("ZOLPIDEM", "3400930000011", "Z1", date(2026, 8, 20), 2),
                ("AMOXICILLINE", "3400930000028", "A1", date(2028, 1, 31), 5),
                ("MORPHINE", "3400930000035", "M1", None, 1)):
            inv = ajouter_entree(inv, _entree(nom=nom, cip=cip, lot=lot,
                                              boites=boites,
                                              peremption=peremption),
                                 AUJOURDHUI)
        return inv

    def test_inventaire_vide(self):
        assert lots_sortables(inventaire_vide(), AUJOURDHUI) == []

    def test_chaque_lot_porte_de_quoi_le_retirer(self):
        lots = lots_sortables(self._inventaire(), AUJOURDHUI)
        assert len(lots) == 3
        for lot in lots:
            # Exactement les arguments de retirer_entree : sans eux, le
            # choix de l'écran ne se traduirait en rien.
            assert set(("cip", "nom", "peremption", "lot", "boites")) <= set(lot)

    def test_le_choix_se_traduit_en_sortie(self):
        """Le tour complet : ce que la liste propose doit réellement sortir."""
        inv = self._inventaire()
        lot = [l for l in lots_sortables(inv, AUJOURDHUI)
               if l["nom"] == "AMOXICILLINE"][0]
        apres = retirer_entree(inv, lot["cip"], lot["nom"], lot["peremption"],
                               lot["lot"], boites=2)
        restant = [l for l in lots_sortables(apres, AUJOURDHUI)
                   if l["nom"] == "AMOXICILLINE"][0]
        assert restant["boites"] == 3

    def test_un_lot_sans_date_est_sortable(self):
        """Rien ne presse à son sujet, mais on doit pouvoir le retirer."""
        noms = [l["nom"] for l in lots_sortables(self._inventaire(),
                                                 AUJOURDHUI)]
        assert "MORPHINE" in noms

    def test_une_ligne_a_zero_boite_n_est_pas_proposee(self):
        """La proposer serait promettre une sortie impossible."""
        inv = self._inventaire()
        morphine = [l for l in lots_sortables(inv, AUJOURDHUI)
                    if l["nom"] == "MORPHINE"][0]
        vide = retirer_entree(inv, morphine["cip"], morphine["nom"],
                              morphine["peremption"], morphine["lot"],
                              boites=morphine["boites"])
        assert "MORPHINE" not in [l["nom"] for l in
                                  lots_sortables(vide, AUJOURDHUI)]

    def test_le_libelle_dit_tout_ce_qu_il_faut_pour_choisir(self):
        """Deux boîtes du même médicament ne se distinguent que par leur
        péremption et leur lot : les omettre rendrait le choix aveugle."""
        lots = lots_sortables(self._inventaire(), AUJOURDHUI)
        zolpidem = [l for l in lots if l["nom"] == "ZOLPIDEM"][0]
        for attendu in ("ZOLPIDEM", "20/08/2026", "Z1", "2 boîte(s)"):
            assert attendu in zolpidem["libelle"], zolpidem["libelle"]
        sans_date = [l for l in lots if l["nom"] == "MORPHINE"][0]
        assert "sans date" in sans_date["libelle"]

    def test_une_boite_entamee_reste_sortable(self):
        """Zéro boîte pleine mais douze comprimés en vrac : les écarter de la
        liste rendrait ces comprimés impossibles à sortir, alors qu'ils sont
        bien dans l'armoire."""
        inv = ajouter_entree(
            inventaire_vide(),
            _entree(nom="ZOLPIDEM", cip="3400930000011", lot="Z9", boites=0,
                    unites_par_boite=30, unites_vrac=12,
                    peremption=date(2027, 6, 30)),
            AUJOURDHUI)
        lots = lots_sortables(inv, AUJOURDHUI)
        assert [l["nom"] for l in lots] == ["ZOLPIDEM"]
        assert lots[0]["unites"] == 12

    def test_chaque_lot_porte_de_quoi_sortir_a_l_unite(self):
        """Sans le conditionnement ni le vrac, l'écran ne saurait pas quel
        maximum proposer pour une sortie à l'unité."""
        inv = ajouter_entree(
            inventaire_vide(),
            _entree(nom="ZOLPIDEM", cip="3400930000011", lot="Z1", boites=2,
                    unites_par_boite=30, unites_vrac=5,
                    peremption=date(2027, 6, 30)),
            AUJOURDHUI)
        lot = lots_sortables(inv, AUJOURDHUI)[0]
        assert lot["unites_vrac"] == 5
        assert lot["unites_par_boite"] == 30
        assert lot["unites"] == 65
        # Le libellé doit montrer le vrac : sinon deux lignes identiques à
        # l'écran n'auraient pas le même stock réel.
        assert "2 boîte(s) + 5 unité(s)" in lot["libelle"]

    def test_l_ordre_suit_le_classement_demande(self):
        lots = lots_sortables(self._inventaire(), AUJOURDHUI, TRI_NOM)
        assert [l["nom"] for l in lots] == ["AMOXICILLINE", "MORPHINE",
                                            "ZOLPIDEM"]

    def test_par_defaut_le_plus_urgent_en_tete(self):
        lots = lots_sortables(self._inventaire(), AUJOURDHUI)
        assert lots[0]["nom"] == "ZOLPIDEM"


class TestTriAlphabetique:
    """Classer par nom : on parcourt l'inventaire devant l'armoire.

    Le tri par péremption répond à « que dois-je retirer ? ». Il ne répond
    pas à « où est ce produit dans ma liste ? » — d'où ce second ordre.
    """

    def _inventaire(self, produits):
        inv = inventaire_vide()
        for nom, peremption in produits:
            inv = ajouter_entree(inv, _entree(nom=nom, peremption=peremption,
                                              lot=f"{nom}-{peremption}"),
                                 AUJOURDHUI)
        return inv

    def test_ordre_alphabetique(self):
        inv = self._inventaire([("ZOLPIDEM", date(2026, 8, 5)),
                                ("AMOXICILLINE", date(2028, 1, 31)),
                                ("MORPHINE", date(2027, 3, 1))])
        vue = inventaire_affichable(inv, AUJOURDHUI, TRI_NOM)
        assert list(vue["Nom du produit"]) == [
            "AMOXICILLINE", "MORPHINE", "ZOLPIDEM"]

    def test_les_accents_ne_rejettent_pas_en_fin_de_liste(self):
        """Sans normalisation, « ÉLAVIL » se range après « ZOLPIDEM » : un
        classement qui ne suit pas l'ordre du dictionnaire ne sert à rien."""
        inv = self._inventaire([("ZOLPIDEM", date(2027, 1, 1)),
                                ("ÉLAVIL", date(2027, 1, 1)),
                                ("AMOXICILLINE", date(2027, 1, 1))])
        vue = inventaire_affichable(inv, AUJOURDHUI, TRI_NOM)
        assert list(vue["Nom du produit"]) == [
            "AMOXICILLINE", "ÉLAVIL", "ZOLPIDEM"]

    def test_la_casse_est_ignoree(self):
        inv = self._inventaire([("zolpidem", date(2027, 1, 1)),
                                ("Amoxicilline", date(2027, 1, 1))])
        vue = inventaire_affichable(inv, AUJOURDHUI, TRI_NOM)
        assert list(vue["Nom du produit"]) == ["Amoxicilline", "zolpidem"]

    def test_a_nom_egal_la_boite_qui_perime_la_premiere_reste_en_tete(self):
        """C'est celle qu'on prend : l'ordre alphabétique ne doit pas faire
        perdre le FEFO à l'intérieur d'un même produit."""
        inv = self._inventaire([("MORPHINE", date(2028, 1, 31)),
                                ("MORPHINE", date(2026, 8, 5)),
                                ("MORPHINE", date(2027, 3, 1))])
        vue = inventaire_affichable(inv, AUJOURDHUI, TRI_NOM)
        assert list(vue["Péremption"]) == [
            date(2026, 8, 5), date(2027, 3, 1), date(2028, 1, 31)]

    def test_le_tri_par_peremption_reste_le_defaut(self):
        """Ce qui périme demain doit sauter aux yeux sans rien régler."""
        inv = self._inventaire([("AMOXICILLINE", date(2028, 1, 31)),
                                ("ZOLPIDEM", date(2026, 8, 5))])
        sans_choix = inventaire_affichable(inv, AUJOURDHUI)
        explicite = inventaire_affichable(inv, AUJOURDHUI, TRI_PEREMPTION)
        assert list(sans_choix["Nom du produit"]) == ["ZOLPIDEM",
                                                      "AMOXICILLINE"]
        assert list(explicite["Nom du produit"]) == list(
            sans_choix["Nom du produit"])

    def test_chaque_ordre_propose_range_vraiment_autrement(self):
        """``TRIS`` est la liste offerte à l'écran, et l'interface s'en sert
        pour distinguer ses tableaux : deux entrées qui donneraient le même
        ordre seraient un réglage sans effet visible."""
        inv = self._inventaire([("ZOLPIDEM", date(2026, 8, 5)),
                                ("AMOXICILLINE", date(2028, 1, 31))])
        ordres = {tri: tuple(inventaire_affichable(inv, AUJOURDHUI, tri)
                             ["Nom du produit"]) for tri in TRIS}
        assert len(set(ordres.values())) == len(TRIS)

    def test_les_lots_sans_date_restent_en_dernier_par_peremption(self):
        inv = self._inventaire([("AMOXICILLINE", None),
                                ("ZOLPIDEM", date(2026, 8, 5))])
        assert list(inventaire_affichable(inv, AUJOURDHUI)["Nom du produit"]
                    ) == ["ZOLPIDEM", "AMOXICILLINE"]

    def test_le_classement_suit_jusqu_au_filtre(self):
        """Filtrer ne doit pas rebattre les lignes sous les yeux de qui
        vient de choisir son classement."""
        inv = self._inventaire([("ZOLPIDEM", date(2026, 8, 5)),
                                ("AMOXICILLINE", date(2026, 8, 10)),
                                ("MORPHINE", date(2026, 8, 1))])
        vue = filtrer_inventaire(inv, statuts=STATUTS_A_TRAITER,
                                 aujourdhui=AUJOURDHUI, tri=TRI_NOM)
        assert list(vue["Nom du produit"]) == [
            "AMOXICILLINE", "MORPHINE", "ZOLPIDEM"]

    def test_le_classement_suit_jusqu_au_csv(self):
        """La liste papier ne doit pas contredire l'écran."""
        inv = self._inventaire([("ZOLPIDEM", date(2026, 8, 5)),
                                ("AMOXICILLINE", date(2028, 1, 31))])
        lignes = exporter_csv(inv, AUJOURDHUI, TRI_NOM).decode(
            "utf-8-sig").splitlines()
        assert lignes[1].split(";")[1] == "AMOXICILLINE"

    def test_le_pdf_annonce_son_classement(self):
        """La liste se parcourt devant l'armoire : savoir dans quel ordre
        elle est rangée évite de la relire en entier."""
        pdfplumber = pytest.importorskip("pdfplumber")
        import io
        inv = self._inventaire([("ZOLPIDEM", date(2026, 8, 5))])
        with pdfplumber.open(io.BytesIO(
                exporter_pdf(inv, "Stock interne", AUJOURDHUI, TRI_NOM))) as pdf:
            texte = pdf.pages[0].extract_text()
        assert "Classement" in texte and "A-Z" in texte
        # La flèche « → » du libellé d'écran n'existe pas dans les polices
        # PDF standard : elle s'imprimerait en pavé noir.
        assert "→" not in texte


class TestFiltrerInventaire:
    """Recherche au comptoir et liste de retrait."""

    def _inventaire(self):
        inv = inventaire_vide()
        for nom, lot, peremption in (
                # Dénomination complète, dosage compris : c'est la forme que
                # rend la base publique, et celle que porte l'inventaire.
                ("DOLIPRANE 1000 mg", "A1", date(2026, 7, 1)),   # périmé
                ("MORPHINE", "B2", date(2026, 8, 10)),      # < 1 mois
                ("DIAZEPAM", "C3", date(2026, 9, 30)),      # < 3 mois
                ("NALOXONE", "D4", date(2028, 1, 31))):     # OK
            inv = ajouter_entree(inv, _entree(nom=nom, lot=lot,
                                              peremption=peremption),
                                 AUJOURDHUI)
        return inv

    def test_sans_filtre_tout_passe(self):
        assert len(filtrer_inventaire(self._inventaire(),
                                      aujourdhui=AUJOURDHUI)) == 4

    def test_liste_de_retrait(self):
        """Le besoin le plus fréquent : périmés et lots du mois."""
        retrait = filtrer_inventaire(self._inventaire(),
                                     statuts=STATUTS_A_TRAITER,
                                     aujourdhui=AUJOURDHUI)
        assert list(retrait["Nom du produit"]) == ["DOLIPRANE 1000 mg",
                                                   "MORPHINE"]

    @pytest.mark.parametrize("terme,attendu", [
        ("morph", "MORPHINE"),       # nom, insensible à la casse
        ("c3", "DIAZEPAM"),          # n° de lot
        ("1000 mg", "DOLIPRANE 1000 mg"),   # dosage, inclus dans le nom
    ])
    def test_recherche_sur_les_quatre_colonnes(self, terme, attendu):
        trouve = filtrer_inventaire(self._inventaire(), recherche=terme,
                                    aujourdhui=AUJOURDHUI)
        assert attendu in list(trouve["Nom du produit"])

    def test_recherche_sans_resultat(self):
        assert filtrer_inventaire(self._inventaire(), recherche="ZZZ",
                                  aujourdhui=AUJOURDHUI).empty

    def test_terme_non_interprete_comme_expression_reguliere(self):
        inv = ajouter_entree(self._inventaire(),
                             _entree(nom="VITAMINE D3 (30)", lot="Z9"),
                             AUJOURDHUI)
        trouve = filtrer_inventaire(inv, recherche="(30)",
                                    aujourdhui=AUJOURDHUI)
        assert list(trouve["Nom du produit"]) == ["VITAMINE D3 (30)"]

    def test_recherche_et_palier_se_cumulent(self):
        trouve = filtrer_inventaire(self._inventaire(), recherche="o",
                                    statuts=STATUTS_A_TRAITER,
                                    aujourdhui=AUJOURDHUI)
        assert list(trouve["Nom du produit"]) == ["DOLIPRANE 1000 mg",
                                                  "MORPHINE"]

    def test_resultat_reutilisable_tel_quel(self):
        """La sortie a la forme d'un inventaire : elle se réaffiche et
        s'exporte sans conversion — c'est ce qui permet d'imprimer la
        liste de retrait."""
        retrait = filtrer_inventaire(self._inventaire(),
                                     statuts=STATUTS_A_TRAITER,
                                     aujourdhui=AUJOURDHUI)
        assert list(retrait.columns) == COLONNES_STOCK_FERME
        assert list(inventaire_affichable(retrait, AUJOURDHUI)["Statut"]) == [
            STATUT_PERIME, STATUT_IMMINENT]
        texte = exporter_csv(retrait, AUJOURDHUI).decode("utf-8-sig")
        assert "DOLIPRANE" in texte and "NALOXONE" not in texte

    def test_inventaire_vide(self):
        vide = filtrer_inventaire(inventaire_vide(), recherche="X",
                                  aujourdhui=AUJOURDHUI)
        assert vide.empty and list(vide.columns) == COLONNES_STOCK_FERME


class TestResume:
    def test_compteurs(self):
        inv = inventaire_vide()
        inv = ajouter_entree(inv, _entree(boites=2), AUJOURDHUI)
        inv = ajouter_entree(inv, _entree(lot="B", boites=1,
                                          peremption=date(2026, 7, 1)),
                             AUJOURDHUI)
        inv = ajouter_entree(inv, _entree(cip="3400900000001", nom="AUTRE",
                                          boites=1, peremption=None),
                             AUJOURDHUI)
        resume = resume_inventaire(inv, AUJOURDHUI)
        assert resume["lignes"] == 3
        assert resume["references"] == 2   # deux CIP distincts
        assert resume["boites"] == 4
        assert resume["perimes"] == 1
        assert resume["sans_date"] == 1

    def test_compteurs_de_peremption_par_palier(self):
        inv = inventaire_vide()
        for lot, peremption in (("P", date(2026, 7, 1)),     # périmé
                                ("I", date(2026, 8, 10)),    # < 1 mois
                                ("C", date(2026, 9, 30)),    # < 3 mois
                                ("V", date(2026, 12, 31)),   # < 6 mois
                                ("O", date(2028, 1, 31))):   # OK
            inv = ajouter_entree(inv, _entree(lot=lot, peremption=peremption),
                                 AUJOURDHUI)
        resume = resume_inventaire(inv, AUJOURDHUI)
        assert resume["perimes"] == 1
        assert resume["imminents"] == 1
        assert resume["critiques"] == 1
        assert resume["vigilance"] == 1
        assert resume["lignes"] == 5

    def test_resume_vide(self):
        vide = resume_inventaire(inventaire_vide(), AUJOURDHUI)
        assert vide["lignes"] == 0 and vide["imminents"] == 0


# ---------------------------------------------------------------------------
# Mémoire (persistance sur disque)
# ---------------------------------------------------------------------------

class TestPersistanceInventaire:
    def test_aller_retour_sur_disque(self, tmp_path):
        chemin = tmp_path / "stock_ferme.csv"
        inv = ajouter_entree(inventaire_vide(), _entree(boites=4), AUJOURDHUI)
        sauver_inventaire(inv, chemin)
        relu = charger_inventaire(chemin)
        assert len(relu) == 1
        assert relu.iloc[0]["Boîtes"] == 4
        assert relu.iloc[0]["Péremption"] == date(2027, 6, 30)
        assert relu.iloc[0]["Nom du produit"] == "DOLIPRANE"

    def test_fichier_absent_donne_un_inventaire_vide(self, tmp_path):
        assert charger_inventaire(tmp_path / "rien.csv").empty

    def test_fichier_illisible_ne_bloque_pas_le_module(self, tmp_path):
        chemin = tmp_path / "casse.csv"
        chemin.write_bytes(b"\x00\x01\x02 pas un csv")
        assert list(charger_inventaire(chemin).columns) == COLONNES_STOCK_FERME

    def test_sauvegarde_d_un_inventaire_vide(self, tmp_path):
        chemin = tmp_path / "vide.csv"
        sauver_inventaire(inventaire_vide(), chemin)
        assert charger_inventaire(chemin).empty


class TestImportRepertoire:
    """Pré-remplissage en bloc : c'est ce qui évite de taper les noms.

    Un code-barres ne transporte pas le libellé du médicament ; il doit
    venir d'une table « CIP → nom », typiquement le catalogue de l'officine.
    """

    def test_import_puis_reconnaissance_au_scan(self):
        rep, ajoutes, ignores = importer_repertoire(repertoire_vide(), [
            {"cip": "3400935955838", "nom": "DOLIPRANE 1000",
             "dosage": "1000 mg", "unites_par_boite": 8},
            {"cip": "3400937000013", "nom": "MORPHINE"},
        ])
        assert (ajoutes, ignores) == (2, 0)
        assert produit_connu(rep, "3400935955838") == {
            "nom": "DOLIPRANE 1000", "dosage": "1000 mg",
            "unites_par_boite": 8}

    def test_lignes_sans_code_ou_sans_nom_ignorees(self):
        rep, ajoutes, ignores = importer_repertoire(repertoire_vide(), [
            {"cip": "", "nom": "SANS CODE"},
            {"cip": "3400930000000", "nom": ""},
            {"cip": "3400930000017", "nom": "BON"},
        ])
        assert (ajoutes, ignores) == (1, 2)

    def test_cip_repete_dans_le_fichier_ne_fait_qu_une_ligne(self):
        """Un catalogue liste souvent plusieurs fois le même code."""
        rep, ajoutes, _ = importer_repertoire(repertoire_vide(), [
            {"cip": "340", "nom": "ANCIEN LIBELLÉ", "dosage": "1 g"},
            {"cip": "340", "nom": "LIBELLÉ À JOUR"},
        ])
        assert ajoutes == 1 and len(rep) == 1
        connu = produit_connu(rep, "340")
        assert connu["nom"] == "LIBELLÉ À JOUR"
        assert connu["dosage"] == "1 g"  # l'info déjà lue n'est pas perdue

    def test_reimport_met_a_jour_sans_dupliquer(self):
        rep = memoriser_produit(repertoire_vide(), "340", "ANCIEN NOM")
        rep, ajoutes, _ = importer_repertoire(
            rep, [{"cip": "340", "nom": "NOUVEAU NOM", "dosage": "500 mg"}])
        assert ajoutes == 0 and len(rep) == 1
        assert produit_connu(rep, "340")["nom"] == "NOUVEAU NOM"

    def test_saisie_manuelle_prime_pas_ecrasee_par_le_vide(self):
        """Un dosage saisi à la main ne doit pas être effacé par un fichier
        qui ne renseigne pas cette colonne."""
        rep = memoriser_produit(repertoire_vide(), "340", "X", "500 mg", 30)
        rep, _, _ = importer_repertoire(rep, [{"cip": "340", "nom": "X"}])
        connu = produit_connu(rep, "340")
        assert connu["dosage"] == "500 mg" and connu["unites_par_boite"] == 30

    def test_codes_ponctues_normalises(self):
        rep, _, _ = importer_repertoire(
            repertoire_vide(), [{"cip": "3400 935 955 838", "nom": "X"}])
        assert produit_connu(rep, "3400935955838")["nom"] == "X"

    def test_fichier_vide(self):
        rep, ajoutes, ignores = importer_repertoire(repertoire_vide(), [])
        assert rep.empty and (ajoutes, ignores) == (0, 0)

    def test_le_moteur_ignore_d_ou_vient_le_fichier(self):
        """Le moteur ne reçoit que des couples déjà extraits — pas un
        tableau, pas un fichier. C'est ce qui le garde indépendant du format
        du catalogue : la lecture du fichier appartient à l'interface."""
        def _flux():                      # un simple générateur suffit
            yield {"cip": "340", "nom": "X"}
        rep, ajoutes, _ = importer_repertoire(repertoire_vide(), _flux())
        assert ajoutes == 1 and produit_connu(rep, "340")["nom"] == "X"


class TestRepertoire:
    def test_produit_memorise_puis_retrouve(self):
        rep = memoriser_produit(repertoire_vide(), "3400912345678",
                                "DOLIPRANE", "1000 mg", 8)
        connu = produit_connu(rep, "3400912345678")
        assert connu == {"nom": "DOLIPRANE", "dosage": "1000 mg",
                         "unites_par_boite": 8}

    def test_mise_a_jour_sans_doublon(self):
        rep = memoriser_produit(repertoire_vide(), "340", "ANCIEN NOM")
        rep = memoriser_produit(rep, "340", "NOUVEAU NOM", "500 mg")
        assert len(rep) == 1
        assert produit_connu(rep, "340")["nom"] == "NOUVEAU NOM"

    def test_cip_inconnu(self):
        assert produit_connu(repertoire_vide(), "340") is None

    def test_produit_sans_nom_non_memorise(self):
        assert memoriser_produit(repertoire_vide(), "340", "").empty

    def test_aller_retour_sur_disque(self, tmp_path):
        chemin = tmp_path / "repertoire.csv"
        sauver_repertoire(
            memoriser_produit(repertoire_vide(), "340", "DOLIPRANE", "1 g", 8),
            chemin)
        assert produit_connu(charger_repertoire(chemin), "340")[
            "unites_par_boite"] == 8


# ---------------------------------------------------------------------------
# Impression
# ---------------------------------------------------------------------------

class TestExports:
    def _inventaire(self):
        """Un lot par palier de péremption, pour couvrir toute la légende."""
        inv = ajouter_entree(inventaire_vide(), _entree(boites=2), AUJOURDHUI)
        for lot, peremption in (("B2", date(2026, 8, 10)),    # < 1 mois
                                ("C3", date(2026, 9, 30)),    # < 3 mois
                                ("D4", date(2026, 12, 31)),   # < 6 mois
                                ("E5", date(2026, 7, 1))):    # périmé
            inv = ajouter_entree(inv, _entree(lot=lot, peremption=peremption),
                                 AUJOURDHUI)
        return inv

    def test_csv_contient_les_informations_demandees(self):
        texte = exporter_csv(self._inventaire(), AUJOURDHUI).decode("utf-8-sig")
        entete = texte.splitlines()[0]
        # Pas de colonne « Dosage » : il fait partie du nom du produit.
        assert "Dosage" not in entete
        for colonne in ("Nom du produit", "Code CIP", "Boîtes",
                        "Unités", "Péremption", "Lot"):
            assert colonne in entete
        assert "DOLIPRANE" in texte
        assert "3400912345678" in texte
        assert "10/08/2026" in texte  # péremption au format français

    def test_csv_trie_la_peremption_la_plus_proche_en_tete(self):
        lignes = exporter_csv(self._inventaire(),
                              AUJOURDHUI).decode("utf-8-sig").splitlines()
        assert "01/07/2026" in lignes[1]   # le lot périmé d'abord
        assert "10/08/2026" in lignes[2]   # puis le plus proche

    def test_csv_porte_les_quatre_paliers(self):
        texte = exporter_csv(self._inventaire(), AUJOURDHUI).decode("utf-8-sig")
        for statut in (STATUT_PERIME, STATUT_IMMINENT, STATUT_CRITIQUE,
                       STATUT_VIGILANCE, STATUT_OK):
            assert statut in texte

    def test_csv_d_un_inventaire_vide(self):
        texte = exporter_csv(inventaire_vide(), AUJOURDHUI).decode("utf-8-sig")
        assert "Nom du produit" in texte

    def test_pdf_genere(self):
        pytest.importorskip("reportlab")
        contenu = exporter_pdf(self._inventaire(), aujourdhui=AUJOURDHUI)
        assert contenu.startswith(b"%PDF")
        assert len(contenu) > 1000

    def test_pdf_lisible_sans_emoji(self):
        """Les polices PDF standard n'ont pas de glyphe d'émoji : le statut
        doit être écrit en toutes lettres, sinon la colonne est illisible."""
        pytest.importorskip("reportlab")
        pdfplumber = pytest.importorskip("pdfplumber")
        contenu = exporter_pdf(self._inventaire(), aujourdhui=AUJOURDHUI)
        with pdfplumber.open(pytest.importorskip("io").BytesIO(contenu)) as pdf:
            texte = "\n".join(p.extract_text() or "" for p in pdf.pages)
        for palier in ("PÉRIMÉ", "< 1 mois", "< 3 mois", "< 6 mois", "OK"):
            assert palier in texte
        assert not any(c in texte for c in "⛔🔴🟠🟡🟢⚪")
        assert "DOLIPRANE" in texte and "3400912345678" in texte
        assert "10/08/2026" in texte

    def test_pdf_replie_les_noms_longs(self):
        """Un libellé plus large que sa colonne doit se replier, pas déborder
        sur les colonnes voisines (sinon la ligne imprimée est illisible)."""
        pytest.importorskip("reportlab")
        pdfplumber = pytest.importorskip("pdfplumber")
        import io as _io
        long = ("PARACETAMOL BIOGARAN CONSEIL 1000 mg comprimé pelliculé "
                "sécable boîte de 8")
        inv = ajouter_entree(inventaire_vide(),
                             _entree(nom=long, boites=2), AUJOURDHUI)
        with pdfplumber.open(_io.BytesIO(
                exporter_pdf(inv, aujourdhui=AUJOURDHUI))) as pdf:
            texte = pdf.pages[0].extract_text()
        # Le code CIP et la quantité restent intacts, donc non chevauchés.
        assert "3400912345678" in texte
        # Le libellé se replie : on le retrouve en entier une fois les
        # retours à la ligne recollés, et NON tronqué.
        assert "comprimé pelliculé sécable" in texte
        assert "boîte de 8" in texte.replace("\n", " ")

    def test_pdf_echappe_les_caracteres_xml(self):
        """« & » et « < » sont du balisage pour ReportLab : mal échappés,
        ils feraient échouer la génération."""
        pytest.importorskip("reportlab")
        inv = ajouter_entree(inventaire_vide(),
                             _entree(nom="AMOXICILLINE & <ARROW>"), AUJOURDHUI)
        assert exporter_pdf(inv, aujourdhui=AUJOURDHUI).startswith(b"%PDF")

    def test_pdf_d_un_inventaire_vide(self):
        pytest.importorskip("reportlab")
        assert exporter_pdf(inventaire_vide(),
                            aujourdhui=AUJOURDHUI).startswith(b"%PDF")

    def test_nom_de_fichier_date(self):
        assert (nom_fichier_stock_ferme("csv", AUJOURDHUI)
                == "stock_ferme_2026-07-31.csv")
        assert (nom_fichier_stock_ferme(".pdf", AUJOURDHUI)
                == "stock_ferme_2026-07-31.pdf")


class TestIsolation:
    """Le module ne doit dépendre d'aucun des deux autres."""

    def test_aucun_import_des_autres_modules(self):
        source = (pytest.importorskip("pathlib").Path(__file__).parent.parent
                  / "stock_ferme.py").read_text(encoding="utf-8")
        for interdit in ("import moteur_ruptures", "import stock_rotation",
                         "from moteur_ruptures", "from stock_rotation"):
            assert interdit not in source
