# -*- coding: utf-8 -*-
"""Écriture partagée : plusieurs postes sur le même fichier d'inventaire.

L'application peut être installée sur un serveur, chaque poste s'y
connectant par le navigateur. Le fichier d'inventaire est alors écrit par
plusieurs sessions à la fois, et la règle est simple : **rien de ce qui a
été enregistré ne doit disparaître**.

Ces tests-là sont volontairement rapides (des fils d'exécution, pas des
navigateurs) : ils vérifient les fondations. La démonstration grandeur
nature — deux navigateurs sur un vrai serveur — est dans
``test_interface.py``.
"""

import os
import threading
import time
from datetime import date
from pathlib import Path

import pytest

import stock_ferme


def _entree(nom: str, lot: str = "", boites: int = 1):
    return stock_ferme.EntreeStock(
        cip="", nom=nom, dosage="", boites=boites, unites_par_boite=0,
        peremption=date(2028, 6, 30), lot=lot)


def _ajouter(chemin: Path, nom: str, lot: str = "") -> None:
    stock_ferme.appliquer_a_l_inventaire(
        chemin, lambda courant: stock_ferme.ajouter_entree(
            courant, _entree(nom, lot)))


class TestEcritureAtomique:
    def test_le_fichier_provisoire_ne_reste_pas(self, tmp_path):
        chemin = tmp_path / "stock.csv"
        _ajouter(chemin, "PARACETAMOL")
        assert chemin.exists()
        assert [f.name for f in tmp_path.iterdir()] == ["stock.csv"], (
            "un fichier de travail oublié finirait par intriguer, et par "
            "être ouvert")

    def test_le_fichier_reste_lisible_meme_ecrit_de_partout(self, tmp_path):
        """Même sans verrou, une écriture ne doit jamais laisser un fichier
        à moitié rempli : le serveur écrit dans un fil par poste, et deux
        fichiers de travail portant le même nom se voleraient leur contenu.
        """
        chemin = tmp_path / "stock.csv"
        _ajouter(chemin, "PARACETAMOL")
        plein = stock_ferme.charger_inventaire(chemin)
        soucis = []

        def ecrire():
            try:
                for _ in range(20):
                    stock_ferme.sauver_inventaire(plein, chemin)
                    assert len(stock_ferme.charger_inventaire(chemin)) == 1
            except Exception as erreur:               # pragma: no cover
                soucis.append(erreur)

        fils = [threading.Thread(target=ecrire) for _ in range(6)]
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join()
        assert soucis == []

    def test_le_repertoire_est_cree_au_besoin(self, tmp_path):
        chemin = tmp_path / "sous" / "dossier" / "stock.csv"
        stock_ferme.sauver_inventaire(stock_ferme.inventaire_vide(), chemin)
        assert chemin.exists()


class TestVerrou:
    def test_un_seul_poste_a_la_fois(self, tmp_path):
        chemin = tmp_path / "stock.csv"
        chemin.write_text("", encoding="utf-8")
        dedans = []
        simultanes = []

        def travailler():
            with stock_ferme.verrou_fichier(chemin):
                dedans.append(1)
                simultanes.append(len(dedans))
                time.sleep(0.02)
                dedans.pop()

        fils = [threading.Thread(target=travailler) for _ in range(8)]
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join()
        assert max(simultanes) == 1, "deux postes ont écrit en même temps"

    def test_le_verrou_est_rendu_meme_apres_une_erreur(self, tmp_path):
        chemin = tmp_path / "stock.csv"
        with pytest.raises(ValueError):
            with stock_ferme.verrou_fichier(chemin):
                raise ValueError("panne au milieu de l'écriture")
        # Le verrou suivant doit être immédiat : sinon un incident bloquerait
        # le comptoir jusqu'au redémarrage du serveur.
        with stock_ferme.verrou_fichier(chemin, delai_s=0.1):
            pass

    def test_on_renonce_plutot_que_de_figer_l_ecran(self, tmp_path):
        chemin = tmp_path / "stock.csv"
        with stock_ferme.verrou_fichier(chemin):
            debut = time.monotonic()
            with pytest.raises(stock_ferme.VerrouIndisponible):
                with stock_ferme.verrou_fichier(chemin, delai_s=0.2):
                    pass
            assert time.monotonic() - debut < 2.0

    def test_un_verrou_abandonne_est_repris(self, tmp_path):
        """Un poste éteint en pleine écriture laisse son verrou derrière lui.
        Sans reprise, plus personne ne pourrait scanner."""
        chemin = tmp_path / "stock.csv"
        verrou = tmp_path / "stock.csv.verrou"
        verrou.write_text("1234", encoding="utf-8")
        vieux = time.time() - stock_ferme.AGE_VERROU_ABANDONNE_S - 10
        os.utime(verrou, (vieux, vieux))
        with stock_ferme.verrou_fichier(chemin, delai_s=0.5):
            pass
        assert not verrou.exists()


class TestMouvementsSimultanes:
    """Le cœur du sujet : deux gestes en même temps, deux gestes conservés."""

    def test_deux_postes_ajoutent_chacun_leur_produit(self, tmp_path):
        chemin = tmp_path / "stock.csv"
        fils = [threading.Thread(target=_ajouter,
                                 args=(chemin, f"PRODUIT {n}"))
                for n in range(12)]
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join()
        inventaire = stock_ferme.charger_inventaire(chemin)
        assert len(inventaire) == 12
        assert set(inventaire["Nom du produit"]) == {
            f"PRODUIT {n}" for n in range(12)}

    def test_douze_scans_du_meme_produit_font_douze_boites(self, tmp_path):
        chemin = tmp_path / "stock.csv"
        fils = [threading.Thread(target=_ajouter, args=(chemin, "DOLIPRANE",
                                                        "LOT-1"))
                for _ in range(12)]
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join()
        inventaire = stock_ferme.charger_inventaire(chemin)
        assert len(inventaire) == 1
        assert int(inventaire.iloc[0]["Boîtes"]) == 12

    def test_entrees_et_sorties_melangees_se_compensent(self, tmp_path):
        chemin = tmp_path / "stock.csv"
        _ajouter(chemin, "MORPHINE", "LOT-9")
        for _ in range(9):
            _ajouter(chemin, "MORPHINE", "LOT-9")

        def sortir():
            stock_ferme.appliquer_a_l_inventaire(
                chemin, lambda courant: stock_ferme.retirer_entree(
                    courant, "", "MORPHINE", date(2028, 6, 30), "LOT-9",
                    boites=1))

        fils = ([threading.Thread(target=sortir) for _ in range(6)]
                + [threading.Thread(target=_ajouter,
                                    args=(chemin, "MORPHINE", "LOT-9"))
                   for _ in range(4)])
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join()
        inventaire = stock_ferme.charger_inventaire(chemin)
        assert int(inventaire.iloc[0]["Boîtes"]) == 10 - 6 + 4

    def test_le_mouvement_voit_le_fichier_et_non_la_memoire(self, tmp_path):
        """Le mouvement reçoit l'inventaire du DISQUE : c'est ce qui empêche
        d'effacer la boîte scannée par le poste d'à côté."""
        chemin = tmp_path / "stock.csv"
        _ajouter(chemin, "PRODUIT DU POSTE A")
        vus = []
        stock_ferme.appliquer_a_l_inventaire(
            chemin, lambda courant: vus.append(
                list(courant["Nom du produit"])) or courant)
        assert vus == [["PRODUIT DU POSTE A"]]

    def test_un_mouvement_sans_effet_n_ecrit_rien(self, tmp_path):
        chemin = tmp_path / "stock.csv"
        _ajouter(chemin, "PARACETAMOL")
        avant = stock_ferme.empreinte_fichier(chemin)
        time.sleep(0.01)
        rendu = stock_ferme.appliquer_a_l_inventaire(chemin, lambda _: None)
        assert stock_ferme.empreinte_fichier(chemin) == avant
        assert list(rendu.tableau["Nom du produit"]) == ["PARACETAMOL"]
        assert rendu.empreinte == avant


class TestEmpreinteRendue:
    """L'empreinte rendue avec l'écriture doit décrire CETTE écriture.

    La relever après coup laissait passer un autre poste entre les deux :
    on retenait alors le fichier du voisin en croyant y voir le sien, et le
    poste se croyait à jour sans l'être — écran en retard, et une
    correction du tableau qui n'aurait plus vu le conflit.
    """

    def test_l_empreinte_rendue_est_celle_du_fichier_ecrit(self, tmp_path):
        chemin = tmp_path / "stock.csv"
        ecriture = stock_ferme.appliquer_a_l_inventaire(
            chemin, lambda courant: stock_ferme.ajouter_entree(
                courant, _entree("PARACETAMOL")))
        assert ecriture.empreinte == stock_ferme.empreinte_fichier(chemin)

    def test_l_empreinte_ne_decrit_pas_l_ecriture_d_un_autre(self, tmp_path):
        """Le voisin écrit pendant qu'on tient encore le verrou : son
        empreinte ne doit surtout pas devenir la nôtre."""
        chemin = tmp_path / "stock.csv"
        _ajouter(chemin, "PRODUIT DU POSTE A")
        rendues = []

        ecriture = stock_ferme.appliquer_a_l_inventaire(
            chemin, lambda courant: stock_ferme.ajouter_entree(
                courant, _entree("PRODUIT DU POSTE B")))
        rendues.append(ecriture.empreinte)
        # Un troisième poste écrit APRÈS, sans verrou de notre côté.
        _ajouter(chemin, "PRODUIT DU POSTE C")
        assert rendues[0] != stock_ferme.empreinte_fichier(chemin), (
            "l'empreinte rendue doit rester celle de notre écriture")


class TestEmpreinte:
    def test_un_fichier_absent_a_une_empreinte_neutre(self, tmp_path):
        assert stock_ferme.empreinte_fichier(tmp_path / "rien.csv") == (0, 0)

    def test_l_empreinte_change_quand_le_fichier_change(self, tmp_path):
        chemin = tmp_path / "stock.csv"
        _ajouter(chemin, "PARACETAMOL")
        avant = stock_ferme.empreinte_fichier(chemin)
        _ajouter(chemin, "IBUPROFENE")
        assert stock_ferme.empreinte_fichier(chemin) != avant

    def test_l_empreinte_ne_bouge_pas_sans_ecriture(self, tmp_path):
        chemin = tmp_path / "stock.csv"
        _ajouter(chemin, "PARACETAMOL")
        assert (stock_ferme.empreinte_fichier(chemin)
                == stock_ferme.empreinte_fichier(chemin))


class TestRepertoirePartage:
    def test_deux_postes_memorisent_chacun_leur_produit(self, tmp_path):
        chemin = tmp_path / "produits.csv"

        def memoriser(cip, nom):
            stock_ferme.appliquer_au_repertoire(
                chemin, lambda courant: stock_ferme.memoriser_produit(
                    courant, cip, nom))

        fils = [threading.Thread(target=memoriser,
                                 args=(f"340093000{n:04d}", f"PRODUIT {n}"))
                for n in range(10)]
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join()
        assert len(stock_ferme.charger_repertoire(chemin)) == 10


class TestStockDuLot:
    """Ce que le disque contient VRAIMENT pour un lot donné — le garde-fou
    d'une sortie manuelle décidée sur une liste déjà périmée."""

    def test_le_compte_est_celui_du_lot(self, tmp_path):
        chemin = tmp_path / "stock.csv"
        for _ in range(3):
            _ajouter(chemin, "DOLIPRANE", "LOT-1")
        _ajouter(chemin, "DOLIPRANE", "LOT-2")
        inventaire = stock_ferme.charger_inventaire(chemin)
        assert stock_ferme.stock_du_lot(
            inventaire, "", "DOLIPRANE", date(2028, 6, 30), "LOT-1") == 3
        assert stock_ferme.stock_du_lot(
            inventaire, "", "DOLIPRANE", date(2028, 6, 30), "LOT-2") == 1

    def test_un_lot_disparu_vaut_zero(self, tmp_path):
        chemin = tmp_path / "stock.csv"
        _ajouter(chemin, "DOLIPRANE", "LOT-1")
        inventaire = stock_ferme.charger_inventaire(chemin)
        assert stock_ferme.stock_du_lot(
            inventaire, "", "DOLIPRANE", date(2028, 6, 30), "LOT-X") == 0

    def test_un_inventaire_vide_vaut_zero(self):
        assert stock_ferme.stock_du_lot(
            stock_ferme.inventaire_vide(), "", "X", None, "") == 0


class _FauxStreamlit:
    """Le strict nécessaire pour exercer les fonctions d'écriture de l'écran.

    Elles ne dessinent rien : elles écrivent un fichier et posent un
    message. Un vrai Streamlit demanderait un navigateur pour vérifier deux
    lignes de gestion d'erreur.
    """

    def __init__(self):
        self.session_state = {}


@pytest.fixture
def ecran(tmp_path, monkeypatch):
    """L'écran du stock interne, branché sur des fichiers jetables."""
    pytest.importorskip("streamlit")
    import ui_stock_ferme

    faux = _FauxStreamlit()
    monkeypatch.setattr(ui_stock_ferme, "st", faux)
    monkeypatch.setattr(ui_stock_ferme, "INVENTAIRE_PATH",
                        tmp_path / "stock.csv")
    monkeypatch.setattr(ui_stock_ferme, "REPERTOIRE_PATH",
                        tmp_path / "produits.csv")
    return ui_stock_ferme, faux


class TestEcritureImpossible:
    """Le fichier ouvert dans Excel : Windows refuse de le remplacer.

    C'est le cas le plus fréquent, et il le devient davantage avec un
    serveur — tout tient sur une seule machine. Sans traitement, l'écran
    affichait une trace d'erreur en anglais au milieu du comptoir.
    """

    def test_le_comptoir_recoit_une_phrase_et_non_une_trace(
            self, ecran, monkeypatch):
        ui, faux = ecran

        def refuser(*_args, **_kwargs):
            raise PermissionError(13, "fichier utilise par un autre programme")

        monkeypatch.setattr(os, "replace", refuser)
        entree = _entree("PARACETAMOL")
        assert ui._appliquer(
            lambda courant: stock_ferme.ajouter_entree(courant, entree)) is None
        niveau, texte = faux.session_state["sf_message"]
        assert niveau == "avertissement"
        assert "Excel" in texte and "stock.csv" in texte

    def test_l_attente_du_verrou_a_son_propre_message(self, ecran,
                                                      monkeypatch):
        """Deux causes, deux remèdes : refaire le geste dans un instant, ou
        aller fermer Excel. Un message unique enverrait chercher au mauvais
        endroit."""
        ui, faux = ecran

        def occupe(*_args, **_kwargs):
            raise stock_ferme.VerrouIndisponible("un autre poste écrit")

        monkeypatch.setattr(stock_ferme, "appliquer_a_l_inventaire", occupe)
        assert ui._appliquer(lambda courant: courant) is None
        _, texte = faux.session_state["sf_message"]
        assert "Un autre poste enregistre" in texte
        assert "Excel" not in texte

    def test_le_stock_reste_intact(self, ecran, monkeypatch):
        """Rien n'a été perdu : c'est ce que le message promet."""
        ui, faux = ecran
        entree = _entree("PARACETAMOL")
        ui._appliquer(
            lambda courant: stock_ferme.ajouter_entree(courant, entree))

        def refuser(*_args, **_kwargs):
            raise PermissionError(13, "fichier utilise par un autre programme")

        monkeypatch.setattr(os, "replace", refuser)
        ui._appliquer(lambda courant: stock_ferme.ajouter_entree(
            courant, _entree("IBUPROFENE")))
        inventaire = stock_ferme.charger_inventaire(ui.INVENTAIRE_PATH)
        assert list(inventaire["Nom du produit"]) == ["PARACETAMOL"]


class TestEcranAJour:
    def test_l_empreinte_retenue_est_celle_de_notre_ecriture(self, ecran):
        """Sans quoi le poste se croirait à jour en affichant autre chose."""
        ui, faux = ecran
        ui._appliquer(lambda courant: stock_ferme.ajouter_entree(
            courant, _entree("PARACETAMOL")))
        assert (faux.session_state["sf_empreinte"]
                == stock_ferme.empreinte_fichier(ui.INVENTAIRE_PATH))

    def test_l_editeur_change_de_cle_a_chaque_ecriture(self, ecran):
        """Ses corrections en cours repèrent les lignes par POSITION : les
        rejouer sur un tableau réécrit recopierait un comptage sur le
        mauvais médicament."""
        ui, faux = ecran
        ui._appliquer(lambda courant: stock_ferme.ajouter_entree(
            courant, _entree("PARACETAMOL")))
        premiere = faux.session_state["sf_generation"]
        ui._appliquer(lambda courant: stock_ferme.ajouter_entree(
            courant, _entree("IBUPROFENE")))
        assert faux.session_state["sf_generation"] > premiere
