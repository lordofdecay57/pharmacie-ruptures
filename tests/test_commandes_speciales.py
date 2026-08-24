# -*- coding: utf-8 -*-
"""Module 4 — Commandes spéciales : les deux horloges et la décision.

Ce module manipule de l'argent et l'attente d'un patient. Deux erreurs
coûtent cher, et ce sont elles que la suite traque :

- **facturer trop tôt** : la caisse refuse le dossier. Le compteur des 22
  jours doit donc être juste, et repartir de la bonne date ;
- **commander trop tard** : le patient attend l'avion un mois. La décision
  de commander doit tenir compte du délai d'import RÉEL, pas d'un
  à-peu-près.

Toutes les dates sont fixées dans les tests : un test qui dépend du jour où
on l'exécute ne prouve rien.
"""

import threading
from datetime import date, timedelta

import pandas as pd
import pytest

import commandes_speciales as cs

#: Jour de référence de toute la suite.
AUJOURDHUI = date(2026, 8, 17)


def _dossier(**modifications) -> pd.DataFrame:
    """Un dossier crédible, dont chaque test ne change que ce qui l'occupe."""
    valeurs = dict(patient="Mme Léa DUPONT", produit="KEYTRUDA 100 mg",
                   cip="3400930000019", boites=1,
                   facturation="01/08/2026")
    valeurs.update(modifications)
    return cs.ajouter_dossier(cs.dossier_vide(), **valeurs)


class TestSaisies:
    @pytest.mark.parametrize("saisie,attendu", [
        ("17/08/2026", date(2026, 8, 17)),
        ("17082026", date(2026, 8, 17)),
        ("2026-08-17", date(2026, 8, 17)),
        ("17-08-2026", date(2026, 8, 17)),
        ("17.08.2026", date(2026, 8, 17)),
        ("", None),
        ("pas une date", None),
        ("32/08/2026", None),
    ])
    def test_les_dates_se_tapent_comme_on_veut(self, saisie, attendu):
        """Taper les barres obliques à longueur de journée est du temps
        perdu : « 17082026 » doit suffire."""
        assert cs.parser_date(saisie) == attendu

    def test_le_cip_ne_garde_que_les_chiffres(self):
        assert cs.normaliser_cip(" 3400 930-000.019 ") == "3400930000019"

    @pytest.mark.parametrize("a,b", [
        ("Mme Léa DUPONT", "mme lea dupont"),
        ("Léa  DUPONT", "Lea DUPONT"),
        ("  PAUL martin ", "Paul Martin"),
    ])
    def test_un_patient_reste_le_meme_quelle_que_soit_la_frappe(self, a, b):
        """Deux dossiers pour la même personne feraient repartir les 22
        jours à zéro — donc facturer trop tôt, donc un refus de la caisse."""
        assert cs.cle_patient(a) == cs.cle_patient(b)


class TestHorlogeFacturation:
    def test_vingt_deux_jours_apres_la_derniere_facturation(self):
        assert cs.facturable_le("01/08/2026") == date(2026, 8, 23)

    def test_jamais_facture_est_facturable_tout_de_suite(self):
        """Un dossier neuf n'attend rien : il n'y a pas de précédent à
        respecter."""
        assert cs.facturable_le("") is None
        assert cs.jours_avant_facturation("", AUJOURDHUI) == 0
        assert cs.statut_facturation("", AUJOURDHUI) == cs.STATUT_JAMAIS_FACTURE

    def test_le_compte_a_rebours(self):
        assert cs.jours_avant_facturation("01/08/2026", AUJOURDHUI) == 6
        assert cs.statut_facturation("01/08/2026",
                                     AUJOURDHUI) == cs.STATUT_ATTENTE_FACTURATION

    def test_le_jour_meme_est_facturable(self):
        """Le 22e jour compte : attendre un jour de plus, c'est un jour de
        trésorerie perdu sur un produit très cher."""
        assert cs.jours_avant_facturation("26/07/2026", AUJOURDHUI) == 0
        assert cs.statut_facturation("26/07/2026",
                                     AUJOURDHUI) == cs.STATUT_FACTURABLE

    def test_le_retard_ne_devient_pas_negatif(self):
        """« Facturable depuis 40 jours » ne se décide pas autrement que
        « facturable » — et un nombre négatif dans une colonne se lit mal."""
        assert cs.jours_avant_facturation("01/01/2026", AUJOURDHUI) == 0


class TestHorlogeImport:
    def test_le_delai_se_mesure_au_lieu_de_s_estimer(self):
        """« Trois semaines à un mois » ne permet aucune décision. Le délai
        observé, si."""
        assert cs.delai_observe("10/07/2026", "05/08/2026") == 26

    @pytest.mark.parametrize("envoi,reception", [
        ("", "05/08/2026"), ("10/07/2026", ""),
        ("05/08/2026", "10/07/2026"),       # saisie inversée
    ])
    def test_un_delai_impossible_vaut_mieux_absent(self, envoi, reception):
        """Un délai négatif fausserait la médiane plus sûrement qu'une
        donnée manquante."""
        assert cs.delai_observe(envoi, reception) is None

    def test_la_mediane_et_non_la_moyenne(self):
        """Une commande oubliée trois mois dans un carton tirerait une
        moyenne vers le haut et ferait commander bien trop tôt pour tous les
        autres patients."""
        dossier = cs.dossier_vide()
        for i, (envoi, reception) in enumerate([
                ("01/01/2026", "26/01/2026"),      # 25 j
                ("01/02/2026", "27/02/2026"),      # 26 j
                ("01/03/2026", "01/07/2026")]):    # 122 j — l'accident
            dossier = cs.ajouter_dossier(
                dossier, f"PATIENT {i}", "PRODUIT", "3400930000019",
                envoi=envoi, reception=reception)
        assert cs.delai_habituel(dossier, "3400930000019") == 26

    def test_sans_aucune_mesure_on_prend_le_delai_pessimiste(self):
        """Sous-estimer ferait commander trop tard : on retient le haut de
        la fourchette annoncée."""
        assert cs.delai_habituel(cs.dossier_vide()) == cs.DELAI_IMPORT_DEFAUT_J

    def test_le_delai_d_un_autre_produit_sert_a_defaut(self):
        """Mieux vaut la mesure du voisin que le défaut théorique : c'est le
        même avion."""
        dossier = cs.ajouter_dossier(
            cs.dossier_vide(), "A", "AUTRE PRODUIT", "3400930000026",
            envoi="01/01/2026", reception="21/01/2026")
        assert cs.delai_habituel(dossier, "3400930000019") == 20


class TestStatutCommande:
    def test_rien_envoye_rien_en_cours(self):
        assert cs.statut_commande("", "", 30,
                                  AUJOURDHUI) == cs.STATUT_RIEN_EN_COURS

    def test_en_transit_dans_les_delais(self):
        assert cs.statut_commande("01/08/2026", "", 30,
                                  AUJOURDHUI) == cs.STATUT_EN_TRANSIT

    def test_en_retard_au_dela_du_delai_habituel(self):
        """C'est le signal qui déclenche la relance du grossiste."""
        assert cs.statut_commande("01/06/2026", "", 30,
                                  AUJOURDHUI) == cs.STATUT_RETARD

    def test_une_marge_evite_de_crier_au_loup(self):
        """Les délais d'import ne sont pas réguliers : deux jours d'écart
        n'appellent pas un coup de téléphone."""
        juste_avant = AUJOURDHUI - timedelta(days=30 + cs.MARGE_RETARD_J)
        assert cs.statut_commande(juste_avant, "", 30,
                                  AUJOURDHUI) == cs.STATUT_EN_TRANSIT

    def test_une_reception_anterieure_ouvre_un_nouveau_cycle(self):
        """La date de réception est celle de la boîte PRÉCÉDENTE : un mail
        parti après elle signifie qu'une nouvelle boîte est en route."""
        assert cs.commande_en_cours("01/08/2026", "10/07/2026")
        assert not cs.commande_en_cours("01/07/2026", "20/07/2026")


class TestDecisionCommander:
    """Le cœur du module : personne ne peut tenir ce calcul de tête sur
    trente dossiers, chacun avec ses dates."""

    def _decision(self, **modifications):
        dossier = _dossier(**modifications)
        return cs.a_commander(dossier.iloc[0], 30, 1, AUJOURDHUI)

    def test_une_boite_en_route_suffit(self):
        """Commander une seconde fois, c'est payer deux fois un produit très
        cher."""
        oui, raison = self._decision(envoi="01/08/2026", reception="")
        assert not oui
        assert "déjà en route" in raison

    def test_sans_avance_on_commande(self):
        oui, raison = self._decision(boites=0)
        assert oui
        assert "manque" in raison

    def test_on_commande_avant_que_l_avance_ne_parte(self):
        """La boîte en main sort à la prochaine facturation ; la suivante
        doit être arrivée pour celle d'après. Si le temps restant est plus
        court que l'import, il est DÉJÀ trop tard pour attendre."""
        oui, raison = self._decision(boites=1, facturation="27/07/2026")
        assert oui
        assert "import prend 30 j" in raison

    def test_une_avance_confortable_ne_declenche_rien(self):
        oui, raison = self._decision(boites=3, facturation="16/08/2026")
        assert not oui
        assert "autonomie" in raison

    def test_la_decision_suit_le_delai_reellement_observe(self):
        """Un produit qui arrive en huit jours ne demande pas d'être
        commandé aussi tôt qu'un produit qui met un mois."""
        ligne = _dossier(boites=1, facturation="27/07/2026").iloc[0]
        assert cs.a_commander(ligne, 30, 1, AUJOURDHUI)[0]
        assert not cs.a_commander(ligne, 8, 1, AUJOURDHUI)[0]


class TestVueEtListesDuMatin:
    def _trois_dossiers(self) -> pd.DataFrame:
        dossier = cs.ajouter_dossier(
            cs.dossier_vide(), "A FACTURER", "PRODUIT A", "3400930000019",
            boites=1, facturation="20/07/2026")
        dossier = cs.ajouter_dossier(
            dossier, "A COMMANDER", "PRODUIT B", "3400930000026",
            boites=0, facturation="10/08/2026")
        return cs.ajouter_dossier(
            dossier, "EN RETARD", "PRODUIT C", "3400930000033",
            boites=2, facturation="16/08/2026", envoi="01/05/2026")

    def test_la_vue_calcule_tout_ce_qui_se_deduit(self):
        vue = cs.vue_affichable(_dossier(), AUJOURDHUI)
        assert list(vue.columns) == cs.COLONNES_VUE
        # Les colonnes de dates sont typées « datetime64 » pour qu'une case
        # vide s'affiche vide plutôt que « None » : on compare donc à un
        # Timestamp, pas à un date.
        assert vue.iloc[0]["Facturable le"] == pd.Timestamp(2026, 8, 23)
        assert vue.iloc[0]["Jours avant facturation"] == 6

    def test_aucune_case_vide_ne_s_affiche_None(self):
        """« None » en plein tableau serait la seule note anglo-saxonne d'un
        écran entièrement en français — et personne ne sait ce que c'est.

        Le dossier de ce test n'a AUCUNE date : c'est l'état d'un dossier
        qu'on vient d'ouvrir, donc le plus courant. Le premier correctif
        n'avait traité que les nombres, et « Dern. facturation » affichait
        encore « None » à l'écran de la pharmacie.
        """
        neuf = cs.ajouter_dossier(cs.dossier_vide(), "NOUVEAU", "PRODUIT",
                                  boites=1)
        vue = cs.vue_affichable(neuf, AUJOURDHUI)
        for colonne in ("Attente (j)", "Délai observé (j)"):
            assert str(vue[colonne].dtype) == "Int64", colonne
        for colonne in ("Facturable le", "Envoi du mail", "Réception",
                        "Dernière facturation"):
            assert "datetime64" in str(vue[colonne].dtype), colonne
        assert vue.iloc[0].isna().any(), "ce dossier doit avoir des cases vides"
        assert "None" not in cs.exporter_csv(neuf,
                                             AUJOURDHUI).decode("utf-8-sig")

    def test_un_dossier_vide_ne_casse_rien(self):
        vue = cs.vue_affichable(cs.dossier_vide(), AUJOURDHUI)
        assert vue.empty
        assert list(vue.columns) == cs.COLONNES_VUE

    def test_chaque_liste_retient_le_dossier_qui_la_concerne(self):
        dossier = self._trois_dossiers()
        assert "A FACTURER" in list(
            cs.a_facturer_aujourdhui(dossier, AUJOURDHUI)["Patient"])
        assert "A COMMANDER" in list(
            cs.a_commander_maintenant(dossier, AUJOURDHUI)["Patient"])
        assert list(cs.commandes_en_retard(dossier,
                                           AUJOURDHUI)["Patient"]) == \
            ["EN RETARD"]

    def test_un_dossier_peut_tomber_dans_deux_listes(self):
        """Ce n'est pas un défaut, c'est le cas NORMAL : s'il ne reste
        qu'une boîte et qu'elle part aujourd'hui à la facturation, il faut
        facturer ET commander le même jour. Des listes rendues artificiellement
        exclusives cacheraient l'une des deux actions."""
        dossier = _dossier(boites=1, facturation="20/07/2026")
        assert "Mme Léa DUPONT" in list(
            cs.a_facturer_aujourdhui(dossier, AUJOURDHUI)["Patient"])
        assert "Mme Léa DUPONT" in list(
            cs.a_commander_maintenant(dossier, AUJOURDHUI)["Patient"])

    def test_le_resume_compte_les_patients_et_non_les_lignes(self):
        """Un patient sous deux traitements reste un patient."""
        dossier = cs.ajouter_dossier(_dossier(), "Mme Léa DUPONT",
                                     "REVLIMID 10 mg", "3400930000033")
        resume = cs.resume(dossier, AUJOURDHUI)
        assert resume["dossiers"] == 2
        assert resume["patients"] == 1

    @pytest.mark.parametrize("tri", cs.TRIS)
    def test_chaque_tri_rend_les_memes_lignes(self, tri):
        """Changer l'ordre ne doit jamais faire disparaître un dossier."""
        dossier = self._trois_dossiers()
        vue = cs.vue_affichable(dossier, AUJOURDHUI, tri)
        assert set(vue["Patient"]) == {"A FACTURER", "A COMMANDER",
                                       "EN RETARD"}

    def test_le_tri_par_facturation_met_le_facturable_en_tete(self):
        dossier = self._trois_dossiers()
        vue = cs.vue_affichable(dossier, AUJOURDHUI, cs.TRI_FACTURATION)
        assert vue.iloc[0]["Patient"] == "A FACTURER"


class TestMouvements:
    def test_le_meme_patient_et_le_meme_produit_ne_font_qu_un_dossier(self):
        """C'est l'invariant qui protège les 22 jours."""
        dossier = _dossier()
        dossier = cs.ajouter_dossier(dossier, "mme lea dupont",
                                     "KEYTRUDA 100 mg", "3400930000019",
                                     boites=2)
        assert len(dossier) == 1
        assert cs._entier(dossier.iloc[0]["Boîtes en main"]) == 2

    def test_completer_un_dossier_n_efface_pas_ce_qu_on_ne_retape_pas(self):
        dossier = cs.ajouter_dossier(_dossier(), "Mme Léa DUPONT",
                                     "KEYTRUDA 100 mg", "3400930000019",
                                     notes="à rappeler")
        assert dossier.iloc[0]["Dernière facturation"] == "2026-08-01"
        assert dossier.iloc[0]["Notes"] == "à rappeler"

    def test_un_produit_sans_cip_se_reconnait_a_son_nom(self):
        """Sans ce repli, chaque saisie créerait un dossier de plus et les
        22 jours repartiraient de zéro."""
        dossier = cs.ajouter_dossier(cs.dossier_vide(), "A", "PRODUIT SANS CODE")
        dossier = cs.ajouter_dossier(dossier, "A", "PRODUIT SANS CODE",
                                     boites=3)
        assert len(dossier) == 1

    def test_facturer_sort_une_boite_et_relance_les_22_jours(self):
        """Facturer et délivrer sont le même geste au comptoir : les
        séparer laisserait l'avance fausse."""
        dossier = cs.enregistrer_facturation(
            _dossier(boites=2), "Mme Léa DUPONT", "3400930000019",
            jour=AUJOURDHUI)
        assert cs._entier(dossier.iloc[0]["Boîtes en main"]) == 1
        assert cs.facturable_le(
            dossier.iloc[0]["Dernière facturation"]) == date(2026, 9, 8)

    def test_facturer_ne_descend_jamais_sous_zero(self):
        dossier = cs.enregistrer_facturation(
            _dossier(boites=0), "Mme Léa DUPONT", "3400930000019",
            jour=AUJOURDHUI)
        assert cs._entier(dossier.iloc[0]["Boîtes en main"]) == 0

    def test_recevoir_fait_entrer_la_boite_et_mesure_le_delai(self):
        dossier = _dossier(boites=0, envoi="20/07/2026")
        dossier = cs.enregistrer_reception(dossier, "Mme Léa DUPONT",
                                           "3400930000019",
                                           jour=AUJOURDHUI)
        ligne = dossier.iloc[0]
        assert cs._entier(ligne["Boîtes en main"]) == 1
        assert cs.delai_observe(ligne["Envoi du mail"],
                               ligne["Réception"]) == 28

    def test_envoyer_demarre_l_horloge_d_import(self):
        dossier = cs.enregistrer_envoi(_dossier(), "Mme Léa DUPONT",
                                       "3400930000019", jour=AUJOURDHUI)
        assert cs.commande_en_cours(dossier.iloc[0]["Envoi du mail"],
                                    dossier.iloc[0]["Réception"])

    def test_un_mouvement_sur_un_dossier_inconnu_ne_casse_rien(self):
        dossier = _dossier()
        for mouvement in (cs.enregistrer_envoi, cs.enregistrer_facturation,
                          cs.enregistrer_reception):
            assert len(mouvement(dossier, "INCONNU", "0000000000000")) == 1

    def test_un_dossier_sans_patient_ou_sans_produit_est_refuse(self):
        assert cs.ajouter_dossier(cs.dossier_vide(), "", "PRODUIT").empty
        assert cs.ajouter_dossier(cs.dossier_vide(), "PATIENT", "").empty

    def test_supprimer_un_dossier(self):
        assert cs.supprimer_dossier(_dossier(), "Mme Léa DUPONT",
                                    "3400930000019").empty


class TestTableauEdite:
    def test_les_colonnes_de_lecture_ne_repartent_pas_au_fichier(self):
        vue = cs.vue_affichable(_dossier(), AUJOURDHUI)
        propre = cs.normaliser_tableau_edite(vue)
        assert list(propre.columns) == cs.COLONNES_DOSSIER

    def test_une_ligne_ajoutee_puis_abandonnee_est_ecartee(self):
        """L'éditeur laisse une ligne vide dès qu'on clique « + » : la
        garder polluerait le fichier."""
        vue = cs.vue_affichable(_dossier(), AUJOURDHUI)
        vide = {c: "" for c in vue.columns}
        avec_vide = pd.concat([vue, pd.DataFrame([vide])], ignore_index=True)
        assert len(cs.normaliser_tableau_edite(avec_vide)) == 1

    def test_les_dates_reviennent_en_iso(self):
        vue = cs.vue_affichable(_dossier(), AUJOURDHUI)
        propre = cs.normaliser_tableau_edite(vue)
        assert propre.iloc[0]["Dernière facturation"] == "2026-08-01"


class TestRapprochementStock:
    """Le CIP identifie un produit, pas une boîte : on compare des totaux.

    Prétendre attribuer les boîtes une à une serait inventer une
    information que les données ne contiennent pas.
    """

    def _inventaire(self, *lignes) -> pd.DataFrame:
        return pd.DataFrame(list(lignes),
                            columns=["Code CIP", "Boîtes"])

    def test_l_accord_ne_signale_rien(self):
        rapprochement = cs.rapprochement_stock(
            _dossier(boites=1), self._inventaire(("3400930000019", 1)))
        assert rapprochement.iloc[0]["Écart"] == 0
        assert cs.ecarts_a_verifier(rapprochement).empty

    def test_une_boite_recue_mais_jamais_scannee(self):
        """Le dossier l'annonce, l'armoire ne l'a pas : à vérifier."""
        rapprochement = cs.rapprochement_stock(
            _dossier(boites=2), self._inventaire(("3400930000019", 1)))
        assert rapprochement.iloc[0]["Écart"] == -1
        assert len(cs.ecarts_a_verifier(rapprochement)) == 1

    def test_une_boite_scannee_qui_n_est_dans_aucun_dossier(self):
        rapprochement = cs.rapprochement_stock(
            _dossier(boites=1), self._inventaire(("3400930000019", 3)))
        assert rapprochement.iloc[0]["Écart"] == 2

    def test_deux_patients_sur_le_meme_produit_sont_additionnes(self):
        """C'est la limite assumée du rapprochement par CIP : on sait que
        deux boîtes manquent, pas pour qui."""
        dossier = cs.ajouter_dossier(_dossier(boites=1), "M. Paul MARTIN",
                                     "KEYTRUDA 100 mg", "3400930000019",
                                     boites=1)
        rapprochement = cs.rapprochement_stock(
            dossier, self._inventaire(("3400930000019", 0)))
        assert len(rapprochement) == 1
        assert rapprochement.iloc[0]["Annoncé par les dossiers"] == 2
        assert rapprochement.iloc[0]["Écart"] == -2

    def test_le_stock_ferme_sans_dossier_n_est_pas_un_ecart(self):
        """L'armoire contient bien d'autres choses que des commandes
        spéciales : les signaler serait du bruit."""
        rapprochement = cs.rapprochement_stock(
            _dossier(boites=1),
            self._inventaire(("3400930000019", 1), ("3400999999999", 40)))
        assert len(rapprochement) == 1

    def test_sans_inventaire_le_rapprochement_reste_lisible(self):
        rapprochement = cs.rapprochement_stock(_dossier(boites=1), None)
        assert rapprochement.iloc[0]["Présent au stock fermé"] == 0


class TestFichier:
    def test_un_aller_retour_conserve_tout(self, tmp_path):
        chemin = tmp_path / "commandes.csv"
        cs.sauver(_dossier(boites=2, envoi="10/07/2026",
                           reception="05/08/2026"), chemin)
        relu = cs.charger(chemin)
        assert relu.iloc[0]["Patient"] == "Mme Léa DUPONT"
        assert cs._entier(relu.iloc[0]["Boîtes en main"]) == 2
        assert relu.iloc[0]["Réception"] == "2026-08-05"

    def test_un_fichier_absent_donne_un_dossier_vide(self, tmp_path):
        assert cs.charger(tmp_path / "rien.csv").empty

    def test_un_fichier_illisible_n_empeche_pas_d_ouvrir(self, tmp_path):
        """Mieux vaut un écran vide et un avertissement au journal qu'une
        application qui refuse de démarrer au comptoir."""
        chemin = tmp_path / "casse.csv"
        chemin.write_bytes(b"\x00\x01 ceci n'est pas un CSV \xff")
        assert cs.charger(chemin).empty

    def test_deux_comptoirs_facturent_en_meme_temps(self, tmp_path):
        """Sans écriture sous verrou, la seconde facturation effacerait la
        première et les 22 jours repartiraient de la mauvaise date."""
        chemin = tmp_path / "commandes.csv"
        cs.sauver(cs.dossier_vide(), chemin)

        def ajouter(numero):
            cs.appliquer_aux_dossiers(
                chemin, lambda courant: cs.ajouter_dossier(
                    courant, f"PATIENT {numero}", "PRODUIT",
                    f"340093000{numero:04d}", boites=1))

        fils = [threading.Thread(target=ajouter, args=(n,)) for n in range(10)]
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join()
        assert len(cs.charger(chemin)) == 10

    def test_l_empreinte_est_rendue_avec_l_ecriture(self, tmp_path):
        chemin = tmp_path / "commandes.csv"
        ecriture = cs.appliquer_aux_dossiers(
            chemin, lambda courant: cs.ajouter_dossier(
                courant, "A", "PRODUIT", "3400930000019"))
        assert ecriture.empreinte == cs.empreinte_fichier(chemin)


class TestExports:
    def test_le_csv_s_ouvre_dans_excel_sans_reglage(self):
        octets = cs.exporter_csv(_dossier(), AUJOURDHUI)
        assert octets.startswith(b"\xef\xbb\xbf")       # BOM
        texte = octets.decode("utf-8-sig")
        assert ";" in texte.splitlines()[0]
        assert "Mme Léa DUPONT" in texte

    def test_le_csv_porte_les_colonnes_calculees(self):
        """C'est la liste du matin qu'on exporte, pas la saisie brute."""
        texte = cs.exporter_csv(_dossier(), AUJOURDHUI).decode("utf-8-sig")
        assert "Facturable le" in texte
        assert "À commander" in texte

    def test_le_pdf_est_un_pdf(self):
        pytest.importorskip("reportlab")
        assert cs.exporter_pdf(_dossier(), aujourdhui=AUJOURDHUI
                               ).startswith(b"%PDF")

    def test_un_dossier_vide_s_exporte_aussi(self):
        """La liste du matin peut être vide : c'est même une bonne
        nouvelle, et cela ne doit pas lever."""
        assert cs.exporter_csv(cs.dossier_vide(), AUJOURDHUI)
        pytest.importorskip("reportlab")
        assert cs.exporter_pdf(cs.dossier_vide(), aujourdhui=AUJOURDHUI)
