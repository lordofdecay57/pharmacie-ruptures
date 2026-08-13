# -*- coding: utf-8 -*-
"""Test de fumée de l'interface : l'application démarre-t-elle vraiment ?

La suite couvre les moteurs et les règles d'affichage, mais rien ne
garantissait qu'`app.py` s'exécute — une erreur de syntaxe, un import
manquant ou un appel Streamlit invalide ne se voyait qu'en ouvrant le
navigateur. Ces tests parcourent les trois espaces de travail sur un
Streamlit réellement lancé et échouent à la moindre exception affichée.

Ils sont ignorés automatiquement si Streamlit ou Playwright manquent, pour
que la suite reste exécutable sur un poste sans navigateur.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
NAVIGATEUR = "/opt/pw-browsers/chromium"
DEMARRAGE_MAX_S = 60

#: Libellés des deux espaces de travail, tels qu'affichés dans les onglets.
#: Les garder ici plutôt qu'éparpillés : un renommage se répercute en un
#: seul endroit — et fait échouer ces tests s'il est oublié quelque part.
ESPACE_CADENCIER = "Cadencier — stock & ruptures"
ESPACE_STOCK_FERME = "Stock fermé — inventaire scanné"


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _attendre(port: int, delai: float = DEMARRAGE_MAX_S) -> bool:
    fin = time.time() + delai
    while time.time() < fin:
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.5)
    return False


def _lancer(travail: Path):
    """Streamlit sur un port libre, sur le dossier de données donné."""
    pytest.importorskip("streamlit")
    pytest.importorskip("playwright")
    if not Path(NAVIGATEUR).exists():
        pytest.skip("navigateur Playwright absent")

    port = _port_libre()
    environnement = dict(os.environ, PHARMACIE_DONNEES=str(travail))
    processus = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(RACINE / "app.py"),
         "--server.headless", "true", "--server.port", str(port),
         "--browser.gatherUsageStats", "false"],
        cwd=travail, env=environnement,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        if not _attendre(port):
            processus.kill()
            sortie = (processus.stdout.read() or b"").decode(errors="replace")
            pytest.fail(f"Streamlit n'a pas démarré :\n{sortie[-2000:]}")
        yield f"http://127.0.0.1:{port}"
    finally:
        processus.terminate()
        try:
            processus.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            processus.kill()


@pytest.fixture(scope="module")
def application(tmp_path_factory):
    """Streamlit lancé sur des données JETABLES, sans base publique.

    ``PHARMACIE_DONNEES`` déplace la configuration, l'historique et
    l'inventaire du stock fermé dans un dossier temporaire. Sans cette
    variable, ces fichiers vivent à côté du programme (et non dans le
    répertoire de lancement) : le test lirait — et écraserait — les données
    réelles de la pharmacie.
    """
    yield from _lancer(tmp_path_factory.mktemp("appli"))


@pytest.fixture(scope="module")
def application_avec_base(tmp_path_factory):
    """Même chose, mais avec une base publique minuscule déjà installée.

    La saisie assistée n'existe QUE si la base est là : sans elle, il n'y a
    rien à proposer et le menu ne s'affiche pas. Il faut donc une seconde
    application pour la voir à l'œuvre.
    """
    travail = tmp_path_factory.mktemp("appli_base")
    (travail / "base_medicaments.csv").write_text(
        "Code CIP;Nom du produit;Présentation\n"
        "3400935955838;DOLIPRANE 1000 mg, comprimé;"
        "plaquette de 8 comprimés\n"
        "3400956369553;DOLIPRANE 1000 mg, comprimé;"
        "plaquette de 100 comprimés\n"
        "3400949497294;ANASTROZOLE ACCORD 1 mg, comprimé pelliculé;"
        "plaquette de 30 comprimés\n",
        encoding="utf-8-sig")
    yield from _lancer(travail)


def _ouvrir(page, url: str) -> list:
    """Charge la page et renvoie les erreurs JavaScript observées.

    On attend le bandeau lui-même plutôt qu'un délai fixe : le premier
    rendu peut prendre plus longtemps que prévu (dépendances à charger,
    vérification de version sur un réseau lent), et un test qui échoue au
    chronomètre n'apprend rien sur l'application.
    """
    erreurs: list = []
    page.on("pageerror", lambda e: erreurs.append(str(e)))
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector(".hero", timeout=60000)
    page.wait_for_timeout(2500)
    return erreurs


@pytest.fixture(scope="module")
def pilote():
    """Un SEUL Playwright pour tout le module.

    Deux contextes ``sync_playwright`` ouverts en même temps dans le même
    fil refusent de démarrer : les navigateurs des différentes applications
    testées doivent donc partager celui-ci.
    """
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="module")
def page(application, pilote):
    navigateur = pilote.chromium.launch(executable_path=NAVIGATEUR)
    onglet = navigateur.new_page(viewport={"width": 1400, "height": 1000})
    yield onglet
    navigateur.close()


@pytest.fixture(scope="module")
def page_avec_base(application_avec_base, pilote):
    """Onglet ouvert sur l'espace « stock fermé », base publique installée."""
    navigateur = pilote.chromium.launch(executable_path=NAVIGATEUR)
    onglet = navigateur.new_page(viewport={"width": 1400, "height": 1100})
    onglet.goto(application_avec_base, wait_until="domcontentloaded")
    onglet.wait_for_selector(".hero", timeout=60000)
    onglet.get_by_text(ESPACE_STOCK_FERME).first.click()
    onglet.wait_for_timeout(6000)
    yield onglet
    navigateur.close()


def _sans_exception(page) -> None:
    """Streamlit affiche les exceptions dans la page : rien ne doit passer."""
    assert page.locator('[data-testid="stException"]').count() == 0, (
        page.locator('[data-testid="stException"]').first.inner_text())


def _onglet_actif(page, cle: str) -> str:
    """Libellé de l'onglet sélectionné du groupe ``cle``, ou ``""``.

    Deux façons de reconnaître l'onglet actif, pour suivre Streamlit sans
    dépendre d'une version : « aria-checked » est l'attribut standard,
    « kind » l'attribut interne des versions ≤ 1.58. Le style de
    l'application s'appuie sur les deux — ce test vérifie donc exactement
    ce que voit l'utilisateur.
    """
    return page.evaluate(
        """(cle) => {
            const bloc = document.querySelector('.st-key-' + cle);
            if (!bloc) return '';
            const actif = [...bloc.querySelectorAll('button')].find(
                b => b.getAttribute('aria-checked') === 'true'
                  || b.getAttribute('kind') === 'segmented_controlActive');
            return actif ? actif.innerText.replace(/\\s+/g, ' ').trim() : '';
        }""", cle)


class TestDemarrage:
    def test_accueil_s_affiche(self, page, application):
        erreurs = _ouvrir(page, application)
        assert erreurs == []
        _sans_exception(page)
        assert "Pilotage pharmacie" in page.content()

    def test_les_deux_espaces_sont_proposes(self, page):
        """Les deux espaces ne partagent rien : le choix doit être visible
        dès l'arrivée, pas caché dans un menu."""
        assert page.get_by_text(ESPACE_CADENCIER).count() >= 1
        assert page.get_by_text(ESPACE_STOCK_FERME).count() >= 1

    def test_depot_de_fichiers_demande_avant_analyse(self, page):
        """Sans cadencier, le parcours principal invite à en déposer un
        plutôt que de planter."""
        assert "Déposez" in page.content()

    def test_recliquer_l_onglet_actif_ne_le_deselectionne_pas(self, page):
        """Un onglet n'est pas une case à cocher : il y a toujours un espace
        affiché, donc toujours un onglet allumé. Sans ce garde-fou, un second
        clic éteignait tout et il fallait cliquer sur l'AUTRE pour s'en
        sortir."""
        assert ESPACE_CADENCIER in _onglet_actif(page, "espace_travail")
        page.get_by_text(ESPACE_CADENCIER).first.click()
        page.wait_for_timeout(4000)
        _sans_exception(page)
        assert ESPACE_CADENCIER in _onglet_actif(page, "espace_travail")


class TestEspaceStockFerme:
    """Le module 3 doit fonctionner SANS aucun fichier déposé."""

    def test_ecran_complet(self, page):
        page.get_by_text(ESPACE_STOCK_FERME).first.click()
        page.wait_for_timeout(5000)
        _sans_exception(page)
        contenu = page.content()
        for attendu in ("Scannez le produit", "Inventaire",
                        "Imprimez ou exportez", "Entrée", "Sortie",
                        "Base publique des médicaments",
                        "Pré-remplir les noms", "Classer par"):
            assert attendu in contenu, f"« {attendu} » absent de l'écran"

    def test_classer_par_nom_est_selectionnable(self, page):
        """Le choix de l'ordre est sur l'écran, pas dans la barre latérale :
        c'est un geste qu'on fait en regardant la liste. Le test le change
        vraiment — c'est le rerendu complet qui vaut d'être vérifié."""
        selecteur = page.locator(".st-key-sf_tri")
        assert selecteur.count() == 1, "le sélecteur de classement est absent"
        champ = selecteur.locator("input").first
        # L'ordre par péremption reste le défaut : ce qui périme demain doit
        # sauter aux yeux sans qu'on ait rien à régler.
        assert "Péremption" in champ.input_value()

        champ.click()
        page.wait_for_timeout(800)
        champ.press("ArrowDown")
        page.wait_for_timeout(400)
        champ.press("Enter")
        page.wait_for_timeout(3000)
        _sans_exception(page)
        assert champ.input_value() == "Nom (A → Z)"
        # Le document imprimé suit l'écran : une liste papier qui contredit
        # le tableau se relit en entier pour rien.
        assert "nom (a → z)" in page.content().lower()

    def test_base_absente_signalee_sans_bloquer(self, page):
        """Le poste peut être hors ligne : l'absence de base publique se
        signale, mais l'inventaire reste utilisable."""
        _sans_exception(page)
        assert "non installée" in page.content()

    def test_scan_d_un_produit_inconnu_ouvre_la_fiche(self, page):
        champ = page.get_by_placeholder("Douchez la boîte")
        champ.fill("0103400937000013" + "17280331" + "10LOT-TEST")
        champ.press("Enter")
        page.wait_for_timeout(5000)
        _sans_exception(page)
        contenu = page.content()
        assert "Fiche du produit à enregistrer" in contenu
        # Se voir réclamer le nom d'une boîte qu'on vient de scanner passe
        # pour un bug si l'on n'explique pas qu'un code-barres ne le contient
        # pas. L'explication fait partie du correctif, pas de la décoration.
        assert "ne contient" in contenu and "nom du médicament" in contenu

    def test_nom_manquant_explique_pourquoi(self, page):
        """Valider sans le nom doit dire quoi faire, pas seulement refuser."""
        page.get_by_role("button", name="Ajouter au stock").click()
        page.wait_for_timeout(4000)
        _sans_exception(page)
        contenu = page.content()
        assert "Nom du médicament manquant" in contenu
        assert "recopiez-le depuis la boîte" in contenu

    def test_un_nom_tape_au_clavier_remplit_la_fiche(self, page):
        """Sans base publique installée, il n'y a rien à proposer — mais ce
        qui vient d'être tapé doit au moins servir de nom. Le retaper dans
        la fiche juste en dessous n'aurait aucun sens."""
        champ = page.get_by_placeholder("Douchez la boîte")
        champ.fill("DOLIPRANE 1000 mg")
        champ.press("Enter")
        page.wait_for_timeout(5000)
        _sans_exception(page)
        assert page.get_by_role(
            "textbox", name="Nom du médicament").input_value() == \
            "DOLIPRANE 1000 mg"

    def test_le_bouton_chercher_vaut_la_touche_entree(self, page):
        """La douchette valide toute seule ; un nom tapé au clavier, non.
        Sans ce bouton, le champ restait plein et il ne se passait
        strictement rien — c'est le blocage rencontré en officine."""
        champ = page.get_by_placeholder("Douchez la boîte")
        champ.fill("AMOXICILLINE 1 g")
        page.get_by_role("button", name="Chercher").click()
        page.wait_for_timeout(5000)
        _sans_exception(page)
        # Le champ se vide : la saisie a bien été prise en compte.
        assert champ.input_value() == ""
        assert page.get_by_role(
            "textbox", name="Nom du médicament").input_value() == \
            "AMOXICILLINE 1 g"

    def test_le_champ_invite_a_taper_un_nom(self, page):
        """La présélection ne sert à rien si personne ne sait qu'on peut
        taper autre chose qu'un code."""
        champ = page.get_by_placeholder("Douchez la boîte")
        indication = champ.get_attribute("placeholder")
        assert "nom de médicament" in indication
        # Dire qu'on peut taper un nom ne suffit pas : il faut dire que ça
        # ne part qu'une fois validé.
        assert "Entrée" in indication

    def test_recliquer_le_mode_actif_ne_le_deselectionne_pas(self, page):
        """Même garde-fou pour Entrée / Sortie : un scan a toujours un sens,
        aucun des deux ne doit pouvoir rester éteint."""
        assert "Entrée" in _onglet_actif(page, "sf_mode")
        page.get_by_text("Entrée", exact=False).first.click()
        page.wait_for_timeout(4000)
        _sans_exception(page)
        assert "Entrée" in _onglet_actif(page, "sf_mode")

    def test_sortie_sur_inventaire_vide_est_refusee_proprement(self, page):
        page.get_by_text("Sortie", exact=False).first.click()
        page.wait_for_timeout(3000)
        assert "Sortie" in _onglet_actif(page, "sf_mode")
        champ = page.get_by_placeholder("Douchez la boîte")
        champ.fill("3400937000013")
        champ.press("Enter")
        page.wait_for_timeout(4000)
        _sans_exception(page)
        assert "Sortie impossible" in page.content()

    def test_l_impasse_du_mode_sortie_est_signalee(self, page):
        """Sortir d'un inventaire vide ne peut que rater : chaque scan
        répondait « pas à l'inventaire » et le second bouton était grisé.
        L'écran doit dire pourquoi, et offrir la sortie de secours."""
        contenu = page.content()
        assert "il n'y a rien à sortir" in contenu
        assert page.get_by_role("button", name="Passer en Entrée").count() == 1

    def test_la_sortie_manuelle_est_disponible(self, page):
        """Une étiquette abîmée, une boîte reconditionnée : la douchette ne
        lit pas tout. Le bouton était purement désactivé en mode Sortie —
        il n'existait alors AUCUNE façon de retirer une boîte."""
        bouton = page.get_by_role("button", name="Sortie manuelle")
        assert bouton.count() == 1
        assert bouton.first.is_enabled()

    def test_le_bouton_ramene_en_entree(self, page):
        """Le seul geste qui débloque l'écran doit tenir en un clic."""
        page.get_by_role("button", name="Passer en Entrée").click()
        page.wait_for_timeout(4000)
        _sans_exception(page)
        assert "Entrée" in _onglet_actif(page, "sf_mode")
        assert page.get_by_role("button",
                                name="Saisie manuelle").first.is_enabled()


class TestSaisieAssistee:
    """Tout se choisit dans UNE liste, à la frappe, sans rien valider.

    Deux exigences successives de la pharmacie : les propositions doivent
    venir dès les premières lettres (un champ texte Streamlit ne réagit
    qu'à la validation), et le nom, le dosage et le conditionnement doivent
    tenir sur la même ligne — plus de second écran « Médicaments trouvés »
    à confirmer.
    """

    def test_le_menu_est_present(self, page_avec_base):
        _sans_exception(page_avec_base)
        assert page_avec_base.locator(".st-key-sf_auto_nom").count() == 1

    def test_chaque_ligne_porte_le_conditionnement(self, page_avec_base):
        champ = page_avec_base.locator(".st-key-sf_auto_nom input").first
        champ.click()
        page_avec_base.wait_for_selector("[role='option']", timeout=15000)
        depart = page_avec_base.locator("[role='option']").all_inner_texts()
        # Une entrée par BOÎTE : le Doliprane a deux conditionnements.
        assert len(depart) == 3, depart
        assert any("boîte de 8" in p for p in depart), depart
        assert any("boîte de 100" in p for p in depart), depart
        # L'emballage n'apparaît pas : il allongerait la liste sans rien
        # apprendre.
        assert not any("plaquette" in p for p in depart), depart

    def test_les_propositions_arrivent_a_la_frappe(self, page_avec_base):
        champ = page_avec_base.locator(".st-key-sf_auto_nom input").first
        for lettre in "DOLI":
            champ.press(lettre)
        # Le tri de Streamlit est APPROXIMATIF : il fait remonter ce qui
        # correspond sans forcément écarter le reste. Ce qui compte, et ce
        # que voit l'utilisateur, c'est que le bon médicament passe en tête
        # — sans avoir rien validé.
        page_avec_base.wait_for_function(
            "document.querySelectorAll(\"[role='option']\")[0]"
            ".textContent.includes('DOLIPRANE')", timeout=15000)
        _sans_exception(page_avec_base)

    def test_le_dosage_affine_dans_la_meme_liste(self, page_avec_base):
        """« puis le dosage pour affiner » : pas de second écran."""
        champ = page_avec_base.locator(".st-key-sf_auto_nom input").first
        champ.type(" 1000")
        page_avec_base.wait_for_function(
            "document.querySelectorAll(\"[role='option']\")[0]"
            ".textContent.includes('1000 mg')", timeout=15000)
        _sans_exception(page_avec_base)

    def test_un_seul_clic_remplit_toute_la_fiche(self, page_avec_base):
        """Nom, code CIP et unités par boîte d'un coup — sans passer par un
        panneau « Médicaments trouvés » ni un bouton de confirmation."""
        page_avec_base.locator("[role='option']").first.click()
        page_avec_base.wait_for_timeout(5000)
        _sans_exception(page_avec_base)
        assert "Médicaments trouvés" not in page_avec_base.content()
        assert page_avec_base.get_by_role(
            "textbox", name="Nom du médicament").input_value() == \
            "DOLIPRANE 1000 mg, comprimé"
        # « exact » : la recherche de l'inventaire, plus bas, contient aussi
        # « code CIP » dans son libellé.
        assert page_avec_base.get_by_role(
            "textbox", name="Code CIP",
            exact=True).input_value() == "3400935955838"
        assert page_avec_base.get_by_role(
            "spinbutton", name="Unités par boîte",
            exact=True).input_value() == "8"

    def test_la_peremption_s_ecrit_en_chiffres_seuls(self, page_avec_base):
        """Une date par boîte, deux frappes de « / » par date : sur un
        inventaire complet, cela fait des centaines de frappes pour rien.
        « 082027 » doit valoir « 08/2027 », donc le 31 août."""
        page_avec_base.get_by_role(
            "textbox", name="Date de péremption").fill("082027")
        page_avec_base.get_by_role("button", name="Ajouter au stock").click()
        page_avec_base.wait_for_timeout(5000)
        _sans_exception(page_avec_base)
        contenu = page_avec_base.content()
        assert "31/08/2027" in contenu, "la fin de mois doit être retenue"
        assert "DOLIPRANE 1000 mg" in contenu


class TestModeDemonstration:
    """Le jeu de démonstration fait tourner les deux modules cadencier de
    bout en bout — c'est le chemin le plus large qu'on puisse parcourir
    sans fichier réel."""

    def test_analyse_complete(self, page, application):
        _ouvrir(page, application)
        page.get_by_role("button", name="Essayer avec des données de "
                                        "démonstration").click()
        page.wait_for_timeout(6000)
        _sans_exception(page)
        page.get_by_role("button", name="Lancer l'analyse").click()
        page.wait_for_timeout(15000)
        _sans_exception(page)
        contenu = page.content()
        assert "Résultats" in contenu
        assert "Gestion des stocks en rotation" in contenu
        assert "Gestion des ruptures" in contenu

    def test_les_exports_sont_proposes(self, page):
        assert page.get_by_role("button", name="Excel", exact=False).count() >= 1


# ---------------------------------------------------------------------------
# Plusieurs postes sur un même serveur
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def serveur_partage(tmp_path_factory):
    """Une application, un dossier de données — comme sur le serveur."""
    yield from _lancer(tmp_path_factory.mktemp("appli_partagee"))


@pytest.fixture(scope="module")
def deux_postes(serveur_partage, pilote):
    """Deux navigateurs INDÉPENDANTS sur la même application.

    Deux contextes, pas deux onglets : chacun a ses propres cookies, donc
    sa propre session Streamlit et sa propre mémoire — exactement deux
    comptoirs de la pharmacie devant le même serveur.
    """
    navigateur = pilote.chromium.launch(executable_path=NAVIGATEUR)

    def poste():
        contexte = navigateur.new_context(
            viewport={"width": 1400, "height": 1000})
        onglet = contexte.new_page()
        onglet.goto(serveur_partage, wait_until="domcontentloaded")
        onglet.wait_for_selector(".hero", timeout=60000)
        onglet.get_by_text(ESPACE_STOCK_FERME).first.click()
        onglet.wait_for_timeout(6000)
        return onglet

    # Les DEUX pages sont ouvertes avant la première écriture : c'est la
    # situation qui fait perdre des données — le poste B garde en mémoire
    # l'inventaire d'AVANT le scan du poste A.
    yield poste(), poste()
    navigateur.close()


def _scanner_et_enregistrer(page, code: str, nom: str) -> None:
    """Un scan de code inconnu, complété à la main : le geste du comptoir."""
    champ = page.get_by_placeholder("Douchez la boîte")
    champ.fill(code)
    champ.press("Enter")
    page.wait_for_timeout(4000)
    page.get_by_role("textbox", name="Nom du médicament").fill(nom)
    page.get_by_role("textbox", name="Date de péremption").fill("062028")
    page.get_by_role("button", name="Ajouter au stock").click()
    page.wait_for_timeout(4000)


class TestPostesSimultanes:
    """Le stock est partagé : ce que scanne un poste ne doit jamais
    disparaître parce qu'un autre a scanné juste après.

    Ce test a d'abord été écrit pour CONSTATER la perte : les deux postes
    enregistraient une boîte chacun, et le fichier n'en contenait qu'une.
    Il reste ici pour que cela ne puisse pas revenir sans qu'on le voie.
    """

    def test_les_deux_boites_sont_conservees(self, deux_postes):
        poste_a, poste_b = deux_postes
        _scanner_et_enregistrer(
            poste_a, "0103400930000110" + "17280630" + "10LOT-A",
            "PRODUIT DU POSTE A")
        _sans_exception(poste_a)
        assert "PRODUIT DU POSTE A" in poste_a.content()

        _scanner_et_enregistrer(
            poste_b, "0103400930000280" + "17280630" + "10LOT-B",
            "PRODUIT DU POSTE B")
        _sans_exception(poste_b)

        contenu = poste_b.content()
        assert "PRODUIT DU POSTE B" in contenu
        assert "PRODUIT DU POSTE A" in contenu, (
            "la boîte du poste A a disparu de l'inventaire : le poste B a "
            "réenregistré la version qu'il avait en mémoire")

    def test_chaque_poste_voit_le_stock_de_l_autre(self, deux_postes):
        """Le poste A doit voir la boîte du poste B SANS recharger sa page.

        Un simple clic suffit à réafficher l'écran ; sa session, elle, garde
        l'inventaire d'avant. Sans relecture du fichier, le poste A
        continuerait d'afficher un stock qui n'existe plus — et sa
        prochaine correction l'écrirait tel quel.
        """
        poste_a, _ = deux_postes
        assert "PRODUIT DU POSTE B" not in poste_a.content(), (
            "l'écran du poste A ne peut pas déjà être à jour : ce test "
            "vérifie la relecture, il lui faut un écran périmé au départ")
        # Un geste anodin, qui ne touche pas au stock : recliquer le mode
        # déjà actif. Il provoque un réaffichage, sans rien enregistrer.
        poste_a.locator(".st-key-sf_mode button").first.click()
        poste_a.wait_for_timeout(4000)
        _sans_exception(poste_a)
        assert "PRODUIT DU POSTE B" in poste_a.content()
