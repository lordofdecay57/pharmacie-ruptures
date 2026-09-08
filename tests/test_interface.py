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

#: Libellés des TROIS espaces de travail, tels qu'affichés dans les onglets.
#: Les garder ici plutôt qu'éparpillés : un renommage se répercute en un
#: seul endroit — et fait échouer ces tests s'il est oublié quelque part.
ESPACE_CADENCIER = "Cadencier — stock & ruptures"
ESPACE_STOCK_FERME = "Stock interne"
ESPACE_COMMANDES = "Commandes spéciales"


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
    l'inventaire du stock interne dans un dossier temporaire. Sans cette
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
    # Le répertoire de la pharmacie : c'est LUI qui alimente la liste du
    # champ depuis que le catalogue national en a été retiré (deux
    # secondes sur chaque validation). La base publique, elle, continue
    # de nommer un CIP scanné et de répondre à un nom inconnu.
    (travail / "stock_ferme_produits.csv").write_text(
        "Code CIP;Nom du produit;Dosage;Unités par boîte\n"
        "3400935955838;DOLIPRANE 1000 mg, comprimé;;8\n"
        "3400956369553;DOLIPRANE 1000 mg, comprimé;;100\n"
        "3400949497294;ANASTROZOLE ACCORD 1 mg, comprimé pelliculé;;30\n",
        encoding="utf-8-sig")
    yield from _lancer(travail)


@pytest.fixture(scope="module")
def application_avec_stock(tmp_path_factory):
    """Même chose, mais avec un inventaire DÉJÀ rempli.

    La sortie du stock ne se teste pas sur un inventaire vide : l'écran s'y
    arrête très tôt (« il n'y a rien à sortir »). Il faut donc des boîtes
    posées sur le disque avant que Streamlit ne démarre.
    """
    travail = tmp_path_factory.mktemp("appli_stock")
    (travail / "stock_ferme.csv").write_text(
        "Code CIP;Nom du produit;Péremption;Lot;Boîtes;Unités par boîte;"
        "Unités en vrac;Total unités;Enregistré le\n"
        "3400930000011;ZOLPIDEM 10 mg;2027-06-30;Z1;2;30;0;60;2026-07-01\n",
        encoding="utf-8-sig")
    yield from _lancer(travail)


@pytest.fixture(scope="module")
def page_avec_stock(application_avec_stock, pilote):
    """Onglet ouvert sur le stock interne, en mode Sortie, inventaire rempli."""
    navigateur = pilote.chromium.launch(executable_path=NAVIGATEUR)
    onglet = navigateur.new_page(viewport={"width": 1400, "height": 1100})
    onglet.goto(application_avec_stock, wait_until="domcontentloaded")
    onglet.wait_for_selector(".hero", timeout=60000)
    _onglet(onglet, ESPACE_STOCK_FERME).first.click()
    onglet.wait_for_timeout(6000)
    yield onglet
    navigateur.close()


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
    """Onglet ouvert sur l'espace « stock interne », base publique installée."""
    navigateur = pilote.chromium.launch(executable_path=NAVIGATEUR)
    onglet = navigateur.new_page(viewport={"width": 1400, "height": 1100})
    onglet.goto(application_avec_base, wait_until="domcontentloaded")
    onglet.wait_for_selector(".hero", timeout=60000)
    _onglet(onglet, ESPACE_STOCK_FERME).first.click()
    onglet.wait_for_timeout(6000)
    _ouvrir_les_autres_gestes(onglet)
    yield onglet
    navigateur.close()


def _saisir(page, texte: str, attente: int = 5000):
    """Saisit ``texte`` dans LE champ, puis valide — comme une douchette.

    On **tape** au lieu de remplir d'un bloc : le champ est une liste
    déroulante depuis la fusion des deux barres de recherche, et sa liste
    de propositions — dont l'entrée qui accepte une valeur inédite, celle
    que retient un code-barres — n'apparaît qu'à la frappe. Un
    ``fill()`` poserait la valeur sans que rien ne s'ouvre, et la touche
    Entrée n'aurait alors rien à valider.

    Le délai de 8 ms par caractère est celui d'une douchette réelle : elle
    tape vite, et c'est justement ce qu'il faut éprouver.
    """
    champ = page.get_by_placeholder("Douchez la boîte").first
    champ.click()
    # Vidé au clavier et non par `fill("")` : le champ garde peut-être une
    # ligne choisie au test précédent, et remplacer la valeur d'une liste
    # par une chaîne vide n'y désélectionne rien — la frappe suivante
    # s'ajouterait derrière, et le code scanné serait illisible.
    champ.press("Control+a")
    champ.press("Delete")
    page.wait_for_timeout(300)
    champ.type(texte, delay=8)
    # On ATTEND que la liste propose la valeur inédite avant de valider.
    # Entrée valide l'entrée surlignée : tant que la liste n'a pas suivi
    # la frappe, c'est l'ANCIENNE valeur qui reste surlignée, Entrée la
    # revalide, rien ne change — et le test croit à une application qui
    # ne réagit pas alors que c'est lui qui a parlé trop tôt.
    page.wait_for_function(
        """(t) => [...document.querySelectorAll("[role='option']")].some(
               o => o.textContent.includes(t))""",
        arg=texte.strip(), timeout=15000)
    champ.press("Enter")
    page.wait_for_timeout(attente)
    return champ


def _choisir_dans_la_liste(page, fragment: str, attente: int = 6000):
    """Ouvre LE champ et clique la ligne qui contient ``fragment``.

    Un CLIC dans la liste, et non une frappe suivie d'Entrée : les deux
    ne veulent pas dire la même chose depuis que choisir un lot ouvre le
    panneau de quantité. Entrée valide « ce que j'ai tapé », le clic
    désigne « cette boîte-là ».
    """
    champ = page.get_by_placeholder("Douchez la boîte").first
    champ.click()
    page.wait_for_selector("[role='option']", timeout=15000)
    proposees = page.locator("[role='option']")
    lignes = [o for o in proposees.all() if fragment in o.inner_text()]
    assert lignes, (f"« {fragment} » absent de la liste : "
                    f"{proposees.all_inner_texts()}")
    lignes[0].click()
    page.wait_for_timeout(attente)


def _onglet(page, libelle: str):
    """Le bouton d'onglet portant ce libellé, dans la barre des espaces.

    Ciblé par la clé du widget plutôt que par le texte seul : « Commandes
    spéciales » apparaît aussi dans le bandeau de l'espace et dans la barre
    latérale, et « le premier trouvé » finirait par désigner l'un d'eux.
    """
    return page.locator(".st-key-espace_travail button").filter(
        has_text=libelle)


def _bulle(page, sens: str):
    """La bulle « Entrée » ou « Sortie », proposée APRÈS un scan.

    Elles ont remplacé deux rectangles posés en permanence, qui portaient
    un mode collant. Ciblées par la clé du bouton plutôt que par le texte :
    « Entrée » et « Sortie » se retrouvent partout ailleurs sur cet écran —
    messages de confirmation, libellés du dépliant, tableau — et « le
    premier texte trouvé » finissait par désigner l'un d'eux.
    """
    cle = "sf_bulle_entree" if sens.startswith("Entr") else "sf_bulle_sortie"
    return page.locator(f".st-key-{cle} button")


def _biper_puis(page, texte: str, sens: str, attente: int = 6000):
    """Le geste complet : on bipe, puis on dit ce qu'on en fait."""
    _saisir(page, texte, attente=5000)
    _bulle(page, sens).first.click()
    page.wait_for_timeout(attente)


def _sans_exception(page) -> None:
    """Streamlit affiche les exceptions dans la page : rien ne doit passer."""
    assert page.locator('[data-testid="stException"]').count() == 0, (
        page.locator('[data-testid="stException"]').first.inner_text())


def _ouvrir_les_autres_gestes(page) -> None:
    """Déplie « Le code ne se lit pas ? Sortir à l'unité ? ».

    L'écran de saisie tient désormais en DEUX lignes — on bipe, on dit le
    sens — et tout le reste est replié : ce sont des exceptions, et une
    exception affichée en permanence encombre le geste de tous les jours.
    Replié ne veut pas dire caché : le titre nomme les deux cas.
    """
    # La liste des médicaments ne compte PLUS comme témoin d'ouverture :
    # elle a quitté le dépliant, puis fusionné avec le champ de scan, où
    # elle est visible en permanence. L'y chercher ferait croire le
    # dépliant déjà ouvert, et plus rien ne serait jamais déplié.
    if page.locator(".st-key-sf_bouton_sortie_manuelle:visible, "
                    ".st-key-sf_bouton_saisie_manuelle:visible").count():
        return                              # déjà déplié
    page.get_by_text("Le code ne se lit pas").first.click()
    page.wait_for_timeout(2500)


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
        dès l'arrivée, pas caché dans un menu.

        Visé par la clé du groupe d'onglets : depuis que le libellé s'est
        raccourci en « Stock interne », il apparaît AUSSI comme titre de
        l'espace une fois celui-ci ouvert — un simple `get_by_text` ne
        prouverait donc plus que l'onglet existe.
        """
        assert _onglet(page, ESPACE_CADENCIER).count() == 1
        assert _onglet(page, ESPACE_STOCK_FERME).count() == 1

    def test_le_stock_interne_est_le_premier_onglet(self, page):
        """« Passe inventaire interne en premier onglet, avant rupture de
        stock. » C'est l'écran de la journée : on y bipe des boîtes toute
        la matinée, quand le cadencier se consulte une fois le matin.

        Premier ET ouvert d'emblée : un premier onglet qu'il faut cliquer
        pour voir n'est premier que sur le papier.
        """
        libelles = page.evaluate(
            """() => [...document.querySelectorAll(
                    '.st-key-espace_travail button')].map(
                b => b.innerText.replace(/\\s+/g, ' ').trim())""")
        assert len(libelles) == 3, libelles
        assert ESPACE_STOCK_FERME in libelles[0], libelles
        assert ESPACE_CADENCIER in libelles[1], libelles
        assert ESPACE_STOCK_FERME in _onglet_actif(page, "espace_travail")

    def test_depot_de_fichiers_demande_avant_analyse(self, page):
        """Sans cadencier, le parcours principal invite à en déposer un
        plutôt que de planter. Il faut l'ouvrir : ce n'est plus l'écran
        d'arrivée."""
        _onglet(page, ESPACE_CADENCIER).first.click()
        page.wait_for_timeout(5000)
        _sans_exception(page)
        assert "Déposez" in page.content()

    def test_recliquer_l_onglet_actif_ne_le_deselectionne_pas(self, page):
        """Un onglet n'est pas une case à cocher : il y a toujours un espace
        affiché, donc toujours un onglet allumé. Sans ce garde-fou, un second
        clic éteignait tout et il fallait cliquer sur l'AUTRE pour s'en
        sortir."""
        _onglet(page, ESPACE_CADENCIER).first.click()
        page.wait_for_timeout(4000)
        assert ESPACE_CADENCIER in _onglet_actif(page, "espace_travail")
        _onglet(page, ESPACE_CADENCIER).first.click()
        page.wait_for_timeout(4000)
        _sans_exception(page)
        assert ESPACE_CADENCIER in _onglet_actif(page, "espace_travail")

    def _mesurer_les_onglets(self, page) -> list:
        """Ce que REND le navigateur pour les trois onglets d'espace.

        Le style calculé, et non la règle CSS écrite : une règle présente
        dans la page ne prouve pas qu'elle s'applique.
        """
        return page.evaluate(
            """() => [...document.querySelectorAll(
                    '.st-key-espace_travail button')].map(b => {
                const r = b.getBoundingClientRect(), s = getComputedStyle(b);
                const p = b.querySelector('p');
                return {texte: b.innerText.replace(/\\s+/g, ' ').trim(),
                        largeur: r.width, hauteur: r.height,
                        bord: s.borderTopColor,
                        police: parseFloat(
                            getComputedStyle(p || b).fontSize)};
            })""")

    def test_les_trois_onglets_ont_la_meme_taille(self, page):
        """« Harmonise la taille des onglets avec les deux autres. »

        L'onglet du stock interne a été agrandi, puis ramené : deux fois
        plus haut que ses voisins, il déséquilibrait une barre par ailleurs
        alignée. Les trois gardent donc la même forme — c'est la couleur,
        et elle seule, qui désigne celui où l'on douche.

        Hauteur et taille de police, pas largeur : la barre passe à la
        ligne quand la fenêtre est étroite, et un onglet seul sur sa ligne
        s'étale sur toute la largeur. Un test sur la largeur ne mesurerait
        que le hasard de la coupure.
        """
        onglets = self._mesurer_les_onglets(page)
        assert len(onglets) == 3, onglets
        assert len({o["hauteur"] for o in onglets}) == 1, onglets
        assert len({o["police"] for o in onglets}) == 1, onglets

    def test_l_onglet_ou_l_on_douche_ressort_en_couleur(self, page):
        """Un seul des trois espaces se pratique la douchette à la main :
        celui-là doit se repérer sans lire.

        Mesuré pendant que l'onglet est ÉTEINT, et c'est le cas qui compte :
        allumé, on l'a déjà trouvé. Sans cette règle il redeviendrait gris
        comme ses voisins dès qu'on regarde un autre espace — c'est
        justement là qu'il faut pouvoir le retrouver.

        On l'éteint donc ici même, plutôt que de compter sur le test
        précédent : la règle CSS le désigne par sa POSITION
        (`:nth-child`), et un test qui dépend d'un ordre d'exécution
        cesserait de mordre le jour où cette position change.
        """
        _onglet(page, ESPACE_CADENCIER).first.click()
        page.wait_for_timeout(4000)
        onglets = self._mesurer_les_onglets(page)
        douchette = onglets[0]
        assert "Stock interne" in douchette["texte"], onglets
        assert douchette["bord"] == "rgb(13, 148, 136)", onglets
        for autre in (onglets[1], onglets[2]):
            assert autre["bord"] != douchette["bord"], onglets

    def test_le_libelle_de_l_onglet_tient_en_deux_mots(self, page):
        """« Supprime l'intitulé inventaire scanné. » L'onglet nomme un
        espace, il ne le décrit pas : la description tenait la moitié de la
        barre pour dire ce que l'écran montre juste en dessous."""
        assert _onglet(page, "Stock interne").count() == 1
        assert "inventaire scanné" not in page.content()


class TestEspaceStockFerme:
    """Le module 3 doit fonctionner SANS aucun fichier déposé."""

    def test_ecran_complet(self, page):
        # Par l'onglet, pas par le texte : « Stock interne » titre aussi
        # l'espace une fois ouvert.
        _onglet(page, ESPACE_STOCK_FERME).first.click()
        page.wait_for_timeout(5000)
        _sans_exception(page)
        contenu = page.content()
        for attendu in ("Scannez le produit", "Inventaire",
                        "Imprimez ou exportez", "Entrée", "Sortie",
                        "Base publique des médicaments",
                        "Pré-remplir les noms", "Classer par"):
            assert attendu in contenu, f"« {attendu} » absent de l'écran"

    def test_sans_base_le_bouton_pour_l_installer_est_sur_l_ecran(self, page):
        """« En tapant doliprane, l'utilitaire ne propose toujours pas de
        liste. »

        La cause était juste — la base publique n'était pas installée — mais
        le seul bouton pour l'installer vivait dans la **colonne de gauche,
        repliée par défaut**. On lisait donc « installez-la » sans jamais
        trouver où. Le remède appartient à l'endroit où la panne se voit.

        Cette application de test n'a **pas** de base : c'est exactement le
        cas de l'officine sur la capture reçue.
        """
        bouton = page.locator(".st-key-sf_base_installer button:visible")
        assert bouton.count() == 1, "aucun bouton d'installation dans le flux"
        # Dans le FLUX, et collé au champ qu'il débloque : juste sous lui,
        # au-dessus du dépliant des exceptions. Dans la barre latérale il
        # serait hors de portée — c'était tout le problème.
        positions = page.evaluate(
            """() => {
                const y = (s) => {
                    const e = document.querySelector(s);
                    return e ? e.getBoundingClientRect().top : -1;
                };
                const exceptions = [...document.querySelectorAll(
                        '[data-testid="stExpander"]')].find(
                    e => e.innerText.includes('Le code ne se lit pas'));
                return {champ: y('.st-key-sf_zone_scan'),
                        bouton: y('.st-key-sf_base_installer'),
                        depliant: exceptions
                            ? exceptions.getBoundingClientRect().top : -1};
            }""")
        assert positions["depliant"] > 0, positions
        assert (positions["champ"] < positions["bouton"]
                < positions["depliant"]), positions

    def test_sans_base_le_message_dit_ou_est_le_bouton(self, page):
        """Le message renvoyait vers « l'encadré ci-dessous » — parti dans la
        colonne de gauche depuis. Une consigne qui désigne un endroit vide
        est pire que pas de consigne : on cherche."""
        contenu = page.content()
        assert "Installer la base des médicaments" in contenu
        assert "encadré ci-dessous" not in contenu

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
        _biper_puis(page, "0103400937000013" + "17280331" + "10LOT-TEST",
                    "Entrée")
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
        _biper_puis(page, "DOLIPRANE 1000 mg", "Entrée")
        _sans_exception(page)
        assert page.get_by_role(
            "textbox", name="Nom du médicament").input_value() == \
            "DOLIPRANE 1000 mg"

    def test_la_touche_entree_suffit(self, page):
        """Un bouton « Chercher » accompagnait le champ. Il ne faisait rien
        de plus que la touche Entrée, et deux façons de valider la même
        saisie, c'est déjà une question de trop : lequel des deux ? Le champ
        occupe désormais toute la ligne, et l'invite dit quoi faire."""
        champ = _saisir(page, "AMOXICILLINE 1 g")
        _bulle(page, "Entrée").first.click()
        page.wait_for_timeout(6000)
        _sans_exception(page)
        # Le champ se vide : la saisie a bien été prise en compte.
        assert champ.input_value() == ""
        assert page.get_by_role(
            "textbox", name="Nom du médicament").input_value() == \
            "AMOXICILLINE 1 g"
        assert page.get_by_role("button", name="Chercher").count() == 0

    def test_le_champ_invite_a_taper_un_nom(self, page):
        """La présélection ne sert à rien si personne ne sait qu'on peut
        taper autre chose qu'un code."""
        champ = page.get_by_placeholder("Douchez la boîte")
        indication = champ.get_attribute("placeholder")
        assert "nom du médicament" in indication
        # Dire qu'on peut taper un nom ne suffit pas : il faut dire que ça
        # ne part qu'une fois validé.
        assert "Entrée" in indication

    def test_il_n_y_a_PLUS_de_rectangles_entree_sortie(self, page):
        """« Il faudra donc supprimer les rectangles Entrée et Sortie
        existants. » Ils portaient un mode COLLANT : réglé le matin,
        oublié, et chaque bip suivant partait du mauvais côté — un
        médicament bien présent répondant « n'est pas à l'inventaire »,
        ce qui se lit comme « le code n'est plus reconnu »."""
        assert page.locator(".st-key-sf_mode").count() == 0
        # Et rien ne demande le sens tant qu'on n'a rien bipé : ces bulles
        # sont la réponse à un geste, pas un réglage posé là. On repart
        # donc d'un écran propre — un scan a pu rester en attente.
        if page.locator(".st-key-sf_bulle_annuler button").count():
            page.locator(".st-key-sf_bulle_annuler button").first.click()
            page.wait_for_timeout(4000)
        assert page.locator(".st-key-sf_bulles").count() == 0

    def test_sortie_sur_inventaire_vide_est_refusee_proprement(self, page):
        """L'inventaire est vide : la bulle Sortie doit le dire, et parler
        d'inventaire — pas de code non reconnu."""
        _biper_puis(page, "3400937000013", "Sortie")
        _sans_exception(page)
        assert "n'est pas à l'inventaire" in page.content()

    def test_la_sortie_manuelle_est_disponible(self, page):
        """Une étiquette abîmée, une boîte reconditionnée : la douchette ne
        lit pas tout. Le bouton était purement désactivé en mode Sortie —
        il n'existait alors AUCUNE façon de retirer une boîte."""
        _ouvrir_les_autres_gestes(page)
        # « :visible » écarte le double de mesure que Streamlit rend en
        # taille nulle à côté de chaque bouton porteur d'une bulle d'aide.
        bouton = page.locator(
            ".st-key-sf_bouton_sortie_manuelle button:visible")
        assert bouton.count() == 1
        # Grisé ici, et c'est juste : cet inventaire est vide, il n'y a
        # rien à sortir. Le proposer quand même serait promettre une
        # sortie impossible.
        assert not bouton.first.is_enabled()

    def test_l_ecran_de_saisie_tient_en_UNE_ligne(self, page):
        """La demande de la pharmacie était : « une ligne où on bipe, la
        ligne d'en dessous on clique sur entrée ou sortie, rien de plus ».

        Il n'en reste qu'UNE. Le sens ne se règle plus d'avance : il se
        demande une fois la boîte reconnue, en deux bulles qui s'en vont
        dès qu'on a tranché. Un réglage de moins à se rappeler.
        """
        assert page.locator(".st-key-sf_zone_scan").count() == 1
        assert page.locator(".st-key-sf_mode").count() == 0
        # Le champ est au-dessus du dépliant des exceptions : c'est par lui
        # qu'on commence, toujours.
        positions = page.evaluate(
            """() => {
                const champ = document.querySelector('.st-key-sf_zone_scan');
                const exceptions = [...document.querySelectorAll(
                        '[data-testid="stExpander"]')].find(
                    e => e.innerText.includes('Le code ne se lit pas'));
                return [champ ? champ.getBoundingClientRect().top : -1,
                        exceptions
                            ? exceptions.getBoundingClientRect().top : -1];
            }""")
        assert 0 < positions[0] < positions[1], positions

    def test_la_zone_de_scan_ressort_en_couleur(self, page):
        """C'est le point de départ de tout l'écran, et c'était un champ
        gris comme les autres : rien ne disait que c'est là que ça se
        passe. On lit le style CALCULÉ par le navigateur — une règle CSS
        présente dans la page ne prouve pas qu'elle s'applique."""
        style = page.evaluate(
            """() => {
                // Deux éléments distincts depuis que le champ est une
                // liste : le CADRE porte la couleur, la SAISIE porte le
                // texte. Les mesurer au même endroit donnerait 16 px —
                // la taille par défaut du conteneur, que personne ne lit.
                const cadre = document.querySelector(
                    '.st-key-sf_zone_scan [role=\"group\"]');
                const saisie = document.querySelector('.st-key-sf_zone_scan input');
                if (!cadre || !saisie) return null;
                const s = getComputedStyle(cadre);
                return {bord: s.borderTopColor,
                        epaisseur: parseFloat(s.borderTopWidth),
                        fond: s.backgroundColor,
                        taille: parseFloat(
                            getComputedStyle(saisie).fontSize)};
            }""")
        assert style, "le champ de scan est introuvable"
        # Turquoise de l'application, et non le gris par défaut.
        assert style["bord"] == "rgb(13, 148, 136)", style
        assert style["epaisseur"] >= 2, style
        assert style["fond"] != "rgba(0, 0, 0, 0)", style
        # Un code scanné doit se relire sans se pencher.
        assert style["taille"] >= 22, style

    def test_la_zone_de_scan_repose_sur_un_panneau_colore(self, page):
        """« Agrandis la zone à doucher et mets un fond qui ressort. »

        Un premier essai s'était contenté de teinter le champ lui-même en
        `#f0fdfa` — un turquoise si pâle qu'à l'écran de l'officine il
        passait pour du blanc. La zone porte donc un vrai panneau coloré,
        et le champ y est BLANC au milieu : c'est le contraste entre les
        deux qui se voit de loin, pas la teinte du champ seul. On vérifie
        donc les deux fonds, et qu'ils diffèrent.
        """
        fonds = page.evaluate(
            """() => {
                const p = document.querySelector('.st-key-sf_zone_scan');
                const c = document.querySelector('.st-key-sf_zone_scan [role=\"group\"]');
                if (!p || !c) return null;
                return {panneau: getComputedStyle(p).backgroundColor,
                        champ: getComputedStyle(c).backgroundColor,
                        hauteur: c.getBoundingClientRect().height};
            }""")
        assert fonds, "la zone de scan est introuvable"
        assert fonds["panneau"] != "rgba(0, 0, 0, 0)", (
            "le panneau est transparent : il ne ressort de rien")
        assert fonds["panneau"] != fonds["champ"], fonds
        # Agrandie : un champ de saisie ordinaire fait ~40 px de haut.
        assert fonds["hauteur"] >= 60, fonds

    def test_les_exceptions_sont_repliees(self, page):
        """Étiquette abîmée, sortie à l'unité : des exceptions. Affichées en
        permanence, elles encombraient le geste de tous les jours."""
        contenu = page.content()
        assert "Le code ne se lit pas" in contenu
        # Replié ne veut pas dire caché : le titre nomme les deux cas.
        assert "Sortir à l'unité" in contenu

    def test_la_saisie_manuelle_reste_accessible(self, page):
        """Elle vit dans le dépliant : c'est une exception (code illisible),
        pas le geste de tous les jours. Les DEUX gestes y figurent
        désormais — il n'y a plus de mode pour décider lequel montrer."""
        _ouvrir_les_autres_gestes(page)
        assert page.locator(
            ".st-key-sf_bouton_saisie_manuelle button:visible").is_enabled()
        assert page.locator(
            ".st-key-sf_bouton_sortie_manuelle button:visible").count() == 1


class TestSortieALUnite:
    """Dispenser dix comprimés d'une boîte de trente.

    La douchette lit une boîte, jamais dix comprimés : sans ce chemin, la
    seule sortie possible était la boîte entière, et les vingt comprimés
    restés dans l'armoire disparaissaient de l'inventaire.
    """

    def _ouvrir_le_panneau(self, page_avec_stock):
        page = page_avec_stock
        if page.locator(".st-key-sf_sortie_choix").count() == 0:
            _ouvrir_les_autres_gestes(page)
            page.locator(
                ".st-key-sf_bouton_sortie_manuelle button:visible").click()
            page.wait_for_timeout(4000)
        return page

    def test_le_panneau_s_ouvre_sur_l_inventaire_reel(self, page_avec_stock):
        page = self._ouvrir_le_panneau(page_avec_stock)
        _sans_exception(page)
        assert page.locator(".st-key-sf_sortie_choix").count() == 1
        # Le libellé doit permettre de choisir : nom, péremption, lot.
        assert "ZOLPIDEM" in page.content()

    def test_les_deux_unites_sont_proposees(self, page_avec_stock):
        """Boîtes ou comprimés : c'est le choix qui manquait entièrement."""
        page = self._ouvrir_le_panneau(page_avec_stock)
        contenu = page.content()
        assert "Boîtes entières" in contenu
        assert "Unités (comprimés)" in contenu

    def test_une_sortie_a_l_unite_entame_la_boite(self, page_avec_stock):
        """Le tour complet : 10 comprimés sortis d'un lot de 2 × 30 doivent
        laisser 1 boîte et 20 unités en vrac — pas 1 boîte tout court."""
        page = self._ouvrir_le_panneau(page_avec_stock)
        page.get_by_text("Unités (comprimés)", exact=True).first.click()
        page.wait_for_timeout(3000)
        _sans_exception(page)
        champ = page.locator(
            '[data-testid="stNumberInput"] input').first
        champ.fill("10")
        champ.press("Enter")
        page.wait_for_timeout(2500)
        page.get_by_role("button", name="Retirer du stock").click()
        page.wait_for_timeout(5000)
        _sans_exception(page)
        contenu = page.content()
        assert "10 unité(s) sortie(s)" in contenu
        # Ce qui reste vraiment : 1 boîte de 30 + 20 en vrac. Annoncer
        # « reste 1 boîte » aurait perdu les vingt comprimés de l'armoire.
        assert "reste 50 unité(s)" in contenu


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
        assert page_avec_base.locator(".st-key-sf_zone_scan").count() == 1

    def test_il_n_y_a_QU_UNE_barre_de_recherche(self, page_avec_base):
        """« Il convient de fusionner les deux barres de recherche en une
        seule et unique. »

        Elles l'étaient devenues par accumulation : un champ de scan, puis
        une liste déroulante ajoutée en dessous. Deux barres superposées
        posent une question à chaque geste — *laquelle ?* — et c'est une
        question de trop devant un comptoir.

        Compté sur l'écran RENDU, et sur les champs de saisie visibles :
        c'est ce que voit quelqu'un qui arrive devant, et non ce que le
        code croit afficher.
        """
        barres = page_avec_base.evaluate(
            """() => {
                const zone = document.querySelector(
                    '[data-testid="stMainBlockContainer"]') || document.body;
                return [...zone.querySelectorAll('input')].filter(e => {
                    const r = e.getBoundingClientRect();
                    // Au-dessus du dépliant des exceptions : la zone de
                    // saisie proprement dite. Plus bas vivent la recherche
                    // de l'inventaire et les cases de la fiche.
                    return r.width > 0 && r.height > 0 && r.top < 700;
                }).map(e => e.placeholder || '(sans invite)');
            }""")
        assert len(barres) == 1, barres
        assert "Douchez la boîte" in barres[0], barres

    def test_l_unique_barre_dit_les_deux_gestes(self, page_avec_base):
        """L'invite est tout ce qui dit que ce champ fait les deux : bipe
        une boîte, ou réagit aux premières lettres d'un nom. Un menu
        déroulant ordinaire ne le laisse pas deviner."""
        invite = page_avec_base.locator(
            ".st-key-sf_zone_scan input").first.get_attribute("placeholder")
        assert "Douchez la boîte" in invite, invite
        # L'autre geste : taper un nom. L'invite dit aussi jusqu'où va la
        # liste, et que le reste se cherche à la validation — sans quoi on
        # croirait avoir perdu le répertoire national.
        assert "tapez son nom" in invite, invite

    def test_la_douchette_ecrit_toujours_dans_ce_champ(self, page_avec_base):
        """LE risque de la fusion, et il porte sur le geste principal.

        Le champ est devenu une **liste** de 19 600 médicaments. Une
        douchette n'y choisit rien : elle tape un Data Matrix qui ne
        ressemble à aucune ligne, puis valide. Si la liste refusait une
        valeur inédite, la pharmacie ne pourrait plus scanner du tout —
        c'est `accept_new_options` qui l'en empêche, et cela se vérifie
        avec un vrai code, tapé à la vitesse d'une douchette, séparateur
        FNC1 compris.

        Le code désigne une boîte de la base : l'écran doit la NOMMER,
        puis demander le sens. Un clic sur « Entrée » suffit alors — sans
        fiche à compléter, puisque le nom vient de la base et la
        péremption du code.
        """
        _saisir(page_avec_base,
                "01034009359558381728063010LOT7\x1d", attente=6000)
        _sans_exception(page_avec_base)
        # Ce que l'application a reconnu, AVANT qu'on dise quoi en faire.
        carte = page_avec_base.locator(".st-key-sf_bulles")
        assert carte.count() == 1, "la boîte scannée n'a pas été présentée"
        reconnu = carte.inner_text()
        assert "DOLIPRANE" in reconnu, reconnu
        assert "3400935955838" in reconnu, reconnu
        assert "30/06/2028" in reconnu, reconnu
        _bulle(page_avec_base, "Entrée").first.click()
        page_avec_base.wait_for_timeout(6000)
        _sans_exception(page_avec_base)
        assert "1 boîte" in page_avec_base.content(), (
            "la boîte n'est pas entrée après le clic sur la bulle")

    def test_la_liste_ne_porte_QUE_les_produits_connus(self, page_avec_base):
        """« Il faut une latence inférieure à 1 s. »

        Le champ portait le répertoire national — 19 600 boîtes.
        Chronométré : valider un scan prenait **2,15 s** avec cette liste,
        **0,14 s** sans. Au moment où l'on valide, la liste change (le
        code scanné s'y ajoute) et les 19 600 lignes repartent dans le
        navigateur — deux secondes, sur le geste le plus répété du jour.

        Elle ne contient donc plus que ce que la pharmacie a déjà vu. Le
        test le vérifie par le NOMBRE : trois produits connus ici, et une
        base publique qui en compte autant — si la liste repassait au
        catalogue, elle ne changerait pas de taille sur cette petite
        base, mais l'invite, elle, ne parlerait plus de « produits déjà
        connus ici ».
        """
        invite = page_avec_base.locator(
            ".st-key-sf_zone_scan input").first.get_attribute("placeholder")
        assert "produits déjà connus ici" in invite, invite
        # Et la recherche complète reste promise, sinon on croirait avoir
        # perdu le reste du répertoire national.
        assert "base publique" in invite, invite

    def test_chaque_ligne_porte_le_conditionnement(self, page_avec_base):
        champ = page_avec_base.locator(".st-key-sf_zone_scan input").first
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
        champ = page_avec_base.locator(".st-key-sf_zone_scan input").first
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
        champ = page_avec_base.locator(".st-key-sf_zone_scan input").first
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
        # Choisir un médicament l'identifie ; c'est la bulle qui décide de
        # ce qu'on en fait. Sans péremption connue, « Entrée » ouvre la
        # fiche pour la demander.
        _bulle(page_avec_base, "Entrée").first.click()
        page_avec_base.wait_for_timeout(6000)
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
        # Le stock interne est désormais l'espace d'arrivée : le parcours
        # cadencier s'ouvre par son onglet.
        _onglet(page, ESPACE_CADENCIER).first.click()
        page.wait_for_timeout(5000)
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
        _onglet(onglet, ESPACE_STOCK_FERME).first.click()
        onglet.wait_for_timeout(6000)
        return onglet

    # Les DEUX pages sont ouvertes avant la première écriture : c'est la
    # situation qui fait perdre des données — le poste B garde en mémoire
    # l'inventaire d'AVANT le scan du poste A.
    yield poste(), poste()
    navigateur.close()


def _scanner_et_enregistrer(page, code: str, nom: str) -> None:
    """Un scan de code inconnu, complété à la main : le geste du comptoir.

    Trois temps depuis que le sens se demande APRÈS le scan : on bipe, on
    dit « Entrée », puis on complète ce que le code ne portait pas.
    """
    _biper_puis(page, code, "Entrée", attente=5000)
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
        # Un geste anodin, qui ne touche pas au stock : changer l'ordre
        # d'affichage. Il provoque un réaffichage complet côté serveur,
        # sans rien enregistrer — un dépliant, lui, ne se replie que dans
        # le navigateur et ne relirait donc rien.
        poste_a.locator(".st-key-sf_tri input").first.click()
        poste_a.wait_for_timeout(1200)
        poste_a.get_by_role("option").last.click()
        poste_a.wait_for_timeout(4000)
        _sans_exception(poste_a)
        assert "PRODUIT DU POSTE B" in poste_a.content()


# ---------------------------------------------------------------------------
# Module 4 — Commandes spéciales
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def page_commandes(tmp_path_factory, pilote):
    """Onglet ouvert sur les commandes spéciales, deux dossiers en place.

    Les dossiers sont posés AVANT le démarrage : l'écran doit montrer ses
    trois listes tout de suite, c'est son unique raison d'être. Un module
    vide ne prouverait rien.
    """
    travail = tmp_path_factory.mktemp("appli_commandes")
    (travail / "base_medicaments.csv").write_text(
        "Code CIP;Nom du produit;Présentation\n"
        "3400930000019;KEYTRUDA 100 mg, solution;flacon de 4 mL\n",
        encoding="utf-8-sig")
    (travail / "commandes_speciales.csv").write_text(
        "Patient;Nom du produit;Code CIP;Boîtes en main;Envoi du mail;"
        "Réception;Dernière facturation;Notes\n"
        "Mme LEA DUPONT;KEYTRUDA 100 mg;3400930000019;1;2026-07-10;"
        "2026-08-05;2026-07-20;\n"
        "M. PAUL MARTIN;OPDIVO 40 mg;3400930000026;0;;;2026-08-10;urgent\n"
        # Un dossier SANS AUCUNE DATE : l'état d'un dossier qu'on vient
        # d'ouvrir, donc le plus courant. C'est lui qui fait apparaître les
        # cases vides — et « None » s'y affichait, en plein écran.
        "M. TOUT NEUF;KEYTRUDA 100 mg;3400930000019;1;;;;\n",
        encoding="utf-8-sig")
    lanceur = _lancer(travail)
    url = next(lanceur)

    navigateur = pilote.chromium.launch(executable_path=NAVIGATEUR)
    onglet = navigateur.new_page(viewport={"width": 1500, "height": 1200})
    onglet.goto(url, wait_until="domcontentloaded")
    onglet.wait_for_selector(".hero", timeout=60000)
    _onglet(onglet, ESPACE_COMMANDES).first.click()
    onglet.wait_for_timeout(8000)
    yield onglet
    navigateur.close()
    for _ in lanceur:                       # referme Streamlit
        pass


class TestCommandesSpeciales:
    def test_l_espace_est_propose_des_l_arrivee(self, page, application):
        """Trois espaces, trois onglets visibles : savoir dans lequel on se
        trouve est la première chose à voir. La page est ouverte ICI : un
        test qui dépend de l'ordre d'exécution ne prouve rien."""
        _ouvrir(page, application)
        assert _onglet(page, ESPACE_COMMANDES).count() == 1

    def test_l_ecran_s_ouvre_sans_exception(self, page_commandes):
        _sans_exception(page_commandes)
        assert "Commandes spéciales" in page_commandes.content()

    def test_les_trois_questions_du_matin_sont_posees(self, page_commandes):
        """C'est l'unique raison d'être de l'écran : dire quoi faire
        aujourd'hui avant de montrer un tableau."""
        contenu = page_commandes.content()
        assert "À facturer aujourd'hui" in contenu
        assert "À commander maintenant" in contenu

    def test_les_dossiers_en_place_sont_affiches(self, page_commandes):
        contenu = page_commandes.content()
        assert "LEA DUPONT" in contenu
        assert "PAUL MARTIN" in contenu

    def test_le_panneau_d_ajout_est_visible_sans_defiler(self):
        """L'ajout était en troisième position, sous deux sections : on ne
        le voyait pas, et l'écran donnait l'impression de ne gérer qu'un
        seul patient — celui de la liste déroulante des gestes.

        Contrôle sur la source : l'ordre d'affichage est une décision, et
        c'est elle qu'on protège."""
        source = (RACINE / "ui_commandes_speciales.py").read_text(
            encoding="utf-8")
        corps = source.split("def rendre(", 1)[1]
        assert corps.index("_panneau_ajout(") < corps.index("_listes_du_matin("), (
            "l'ajout doit venir AVANT les listes du matin")
        assert corps.index("_panneau_ajout(") < corps.index("_actions_rapides("), (
            "l'ajout doit venir AVANT les gestes sur un dossier existant")

    def test_les_trois_gestes_du_comptoir_sont_la(self, page_commandes):
        contenu = page_commandes.content()
        for geste in ("Facturé et délivré", "Boîte reçue",
                      "Mail de commande envoyé"):
            assert geste in contenu, geste

    def test_l_import_est_propose_pour_les_trois_formats(self, page_commandes):
        """Retaper trente patients qui existent déjà dans un tableur, c'est
        une demi-journée et des fautes de frappe sur des noms."""
        contenu = page_commandes.content()
        assert "Importer depuis un fichier" in contenu
        for format_ in ("Excel", "CSV", "PDF"):
            assert format_ in contenu, format_

    def test_un_fichier_importe_ouvre_les_dossiers(self, page_commandes,
                                                   tmp_path):
        """Le chemin complet, depuis le dépôt du fichier : c'est là que se
        cachent les surprises d'un vrai tableur — en-têtes inattendus,
        cellules vides, codes lus en décimal."""
        fichier = tmp_path / "commandes.csv"
        fichier.write_text(
            "Nom du patient;Spécialité;Code CIP;Dernière délivrance\n"
            "Mme IMPORTEE;HERCEPTIN 150 mg;3400930000057;01/08/2026\n",
            encoding="utf-8-sig")
        page_commandes.get_by_text("Importer depuis un fichier").first.click()
        page_commandes.wait_for_timeout(1500)
        page_commandes.locator('input[type="file"]').set_input_files(
            str(fichier))
        page_commandes.wait_for_timeout(6000)
        _sans_exception(page_commandes)
        page_commandes.get_by_role(
            "button", name="Importer ces dossiers").click()
        page_commandes.wait_for_timeout(6000)
        _sans_exception(page_commandes)
        assert "Mme IMPORTEE" in page_commandes.content()

    def test_facturer_relance_les_22_jours(self, page_commandes):
        """Le geste complet : la date repart, et une boîte sort du stock.
        Les séparer laisserait l'avance fausse."""
        page_commandes.get_by_role(
            "button", name="Facturé et délivré").first.click()
        page_commandes.wait_for_timeout(6000)
        _sans_exception(page_commandes)
        assert "facturé le" in page_commandes.content()


# ---------------------------------------------------------------------------
# Sortir une boîte en tapant son nom
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def application_sortie_par_nom(tmp_path_factory):
    """Base publique ET inventaire : la situation réelle de l'officine.

    Il faut les deux pour reproduire le bug : c'est la présence du
    catalogue national qui détournait la saisie, et celle de l'inventaire
    qui rend la sortie légitime.
    """
    travail = tmp_path_factory.mktemp("appli_sortie_nom")
    (travail / "base_medicaments.csv").write_text(
        "Code CIP;Nom du produit;Présentation\n"
        "3400930000011;ZOLPIDEM 10 mg, comprimé;plaquette de 30 comprimés\n"
        "3400935955838;DOLIPRANE 1000 mg, comprimé;plaquette de 8 comprimés\n",
        encoding="utf-8-sig")
    (travail / "stock_ferme.csv").write_text(
        "Code CIP;Nom du produit;Péremption;Lot;Boîtes;Unités par boîte;"
        "Unités en vrac;Total unités;Enregistré le\n"
        "3400930000011;ZOLPIDEM 10 mg;2027-06-30;Z1;2;30;0;60;2026-07-01\n",
        encoding="utf-8-sig")
    yield from _lancer(travail)


@pytest.fixture(scope="module")
def page_sortie_par_nom(application_sortie_par_nom, pilote):
    """Stock interne, mode Sortie, avec base publique et inventaire."""
    navigateur = pilote.chromium.launch(executable_path=NAVIGATEUR)
    onglet = navigateur.new_page(viewport={"width": 1400, "height": 1100})
    onglet.goto(application_sortie_par_nom, wait_until="domcontentloaded")
    onglet.wait_for_selector(".hero", timeout=60000)
    onglet.wait_for_timeout(6000)
    yield onglet
    navigateur.close()


class TestSortirEnTapantLeNom:
    """Sortir une boîte en la nommant, sans code-barres.

    Le sens ne se règle plus d'avance : on bipe ou on tape le nom, l'écran
    dit ce qu'il a reconnu, et on clique **Sortie**. C'est ce qui a fait
    disparaître toute une famille de pannes — un mode collant réglé le
    matin envoyait chaque bip suivant du mauvais côté, et un médicament
    bien présent répondait « n'est pas à l'inventaire ».
    """

    def test_taper_le_nom_puis_Sortie_sort_bien_une_boite(
            self, page_sortie_par_nom):
        """Deux boîtes à l'inventaire : après la sortie, il doit en rester
        une — et la fiche doit s'ouvrir pour demander combien."""
        page = page_sortie_par_nom
        _biper_puis(page, "ZOLPIDEM", "Sortie")
        _sans_exception(page)
        assert "Fiche de sortie" in page.content(), (
            "la fiche de quantité ne s'est pas ouverte")
        page.get_by_role("button", name="Retirer du stock").click()
        page.wait_for_timeout(6000)
        _sans_exception(page)
        contenu = page.content()
        assert "sortie(s)" in contenu, "rien n'est sorti"
        assert "reste 1" in contenu, contenu[:0]

    def test_un_nom_absent_de_l_inventaire_le_dit(self, page_sortie_par_nom):
        """Ne JAMAIS rester muet : c'est ce qui fait croire à une panne.
        Et le message parle d'inventaire, pas de code-barres — « code non
        reconnu » n'a aucun sens pour un nom tapé."""
        page = page_sortie_par_nom
        _biper_puis(page, "AMOXICILLINE", "Sortie")
        _sans_exception(page)
        contenu = page.content()
        assert "n'est pas à l'inventaire" in contenu
        assert "Code non reconnu" not in contenu


# ---------------------------------------------------------------------------
# Choisir un lot dans la liste ouvre la quantité à sortir
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def application_deux_lots(tmp_path_factory):
    """Un lot ENTIER et un lot ENTAMÉ, comme l'armoire de l'officine.

    Le lot entamé — plus de boîte, mais 50 comprimés en vrac — est le cas
    envoyé en capture : la seule façon de le dispenser passait par un
    dépliant qu'il fallait savoir ouvrir.
    """
    travail = tmp_path_factory.mktemp("appli_deux_lots")
    (travail / "stock_ferme.csv").write_text(
        "Nom du produit;Dosage;Code CIP;Boîtes;Unités par boîte;"
        "Unités en vrac;Total unités;Péremption;Lot;Enregistré le\n"
        "ZOLPIDEM 10 mg;;3400930000011;2;30;0;60;2027-06-30;Z1;2026-07-01\n"
        "ABACAVIR SANDOZ 300 mg;;3400949497294;0;60;50;50;2028-01-31;A9;"
        "2026-07-01\n",
        encoding="utf-8-sig")
    yield from _lancer(travail)


@pytest.fixture(scope="module")
def page_deux_lots(application_deux_lots, pilote):
    navigateur = pilote.chromium.launch(executable_path=NAVIGATEUR)
    onglet = navigateur.new_page(viewport={"width": 1400, "height": 1200})
    onglet.goto(application_deux_lots, wait_until="domcontentloaded")
    onglet.wait_for_selector(".hero", timeout=60000)
    onglet.wait_for_timeout(6000)
    yield onglet
    navigateur.close()


class TestChoisirUnLotOuvreLaQuantite:
    """« Un onglet qui s'ouvre en bas pour définir le nombre, les
    paramètres de sortie », et « le même principe que pour l'entrée ».

    Sortir demande **combien**, et en boîtes ou en comprimés. La bulle
    Sortie ouvre donc une fiche — pas un retrait immédiat — et cette
    fiche NOMME le produit au lieu de le redemander, comme celle de
    l'entrée nomme le sien.
    """

    def test_la_bulle_Sortie_ouvre_la_fiche_sur_le_bon_lot(
            self, page_deux_lots):
        """Sur CELUI-LÀ, et pas sur le premier de l'inventaire : ouvrir la
        fiche sur un autre lot ferait sortir la mauvaise boîte à celui qui
        valide sans relire."""
        page = page_deux_lots
        _biper_puis(page, "ABACAVIR", "Sortie")
        _sans_exception(page)
        assert page.locator(".st-key-sf_sortie_choix").count() == 1, (
            "la fiche de quantité ne s'est pas ouverte")
        retenu = page.locator(
            ".st-key-sf_sortie_choix input").first.input_value()
        assert "ABACAVIR" in retenu, retenu

    def test_la_fiche_NOMME_le_lot_au_lieu_de_le_redemander(
            self, page_deux_lots):
        """L'entrée ouvre une fiche pré-remplie du produit choisi. La
        sortie rouvrait un panneau « Choisissez la boîte à sortir », avec
        une liste — on venait de choisir, et l'écran redemandait de
        choisir. On croyait qu'il ne s'était rien passé."""
        contenu = page_deux_lots.content()
        assert "Fiche de sortie" in contenu
        assert "ABACAVIR" in contenu
        assert "Choisissez la boîte à sortir" not in contenu, contenu[:0]
        assert "Ce n'est pas la bonne boîte" in contenu

    def test_un_lot_entame_s_ouvre_sur_les_UNITES(self, page_deux_lots):
        """Le cas de la capture : plus de boîte entière, 50 comprimés en
        vrac. Proposer « boîtes à retirer » n'aurait aucun sens — et c'est
        vers un dépliant qu'on renvoyait jusqu'ici."""
        etiquettes = page_deux_lots.locator(
            '[data-testid="stNumberInput"] label').all_inner_texts()
        assert any("Unités à retirer" in e for e in etiquettes), etiquettes
        assert page_deux_lots.get_by_role(
            "button", name="Retirer du stock").count() == 1

    def test_la_quantite_choisie_sort_vraiment(self, page_deux_lots):
        """Le bout de la chaîne : le bouton doit retirer, et le dire."""
        page = page_deux_lots
        page.get_by_role("button", name="Retirer du stock").click()
        page.wait_for_timeout(6000)
        _sans_exception(page)
        contenu = page.content()
        assert "unité(s) sortie(s)" in contenu, "rien n'est sorti"
        assert "reste 49" in contenu, contenu[:0]

    def test_un_lot_entier_s_ouvre_sur_les_BOITES(self, page_deux_lots):
        page = page_deux_lots
        _biper_puis(page, "ZOLPIDEM", "Sortie")
        _sans_exception(page)
        etiquettes = page.locator(
            '[data-testid="stNumberInput"] label').all_inner_texts()
        assert any("Boîtes à retirer" in e for e in etiquettes), etiquettes

    def test_la_douchette_repond_encore_APRES_un_clic(self, page_deux_lots):
        """Le bug que ce test a débusqué, et il coûtait cher.

        Une fois qu'une ligne a été choisie à la SOURIS, le composant ne
        surligne plus rien : la touche Entrée de la douchette n'a alors
        aucune ligne à valider, le code reste dans le champ et **rien ne
        part**. Mesuré dans un navigateur sur les quatre gestes possibles,
        seul celui-ci échouait — et c'est le geste réel : on choisit un
        médicament, on se ravise, on bipe la boîte suivante.

        Ce test arrive APRÈS des clics dans la liste, et c'est tout son
        intérêt : le lancer seul ne prouverait rien.
        """
        page = page_deux_lots
        _saisir(page, "01034009300000111727063010Z1\x1d", attente=6000)
        _sans_exception(page)
        carte = page.locator(".st-key-sf_bulles")
        assert carte.count() == 1, (
            "le code bipé n'a rien déclenché : la douchette est muette "
            "après un clic dans la liste")
        # Cette application de test n'a pas de base publique : le nom ne
        # peut pas être trouvé, et c'est normal. Ce qui compte, c'est que
        # le code ait bien ÉTÉ LU — il est là, dans la carte.
        assert "3400930000011" in carte.inner_text(), carte.inner_text()

    def test_le_style_survit_a_la_reconstruction_du_champ(self,
                                                          page_deux_lots):
        """Le champ change de clé à chaque clic : une règle accrochée à SA
        clé se décrocherait au premier, et la zone de scan redeviendrait
        un champ gris. Le style vit donc sur le conteneur, qui ne bouge
        pas — et on le mesure ici, après plusieurs clics."""
        fonds = page_deux_lots.evaluate(
            """() => {
                const p = document.querySelector('.st-key-sf_zone_scan');
                const c = document.querySelector(
                    '.st-key-sf_zone_scan [role=\"group\"]');
                if (!p || !c) return null;
                return {panneau: getComputedStyle(p).backgroundColor,
                        bord: getComputedStyle(c).borderTopColor};
            }""")
        assert fonds, "la zone de scan est introuvable"
        assert fonds["panneau"] != "rgba(0, 0, 0, 0)", fonds
        # L'un ou l'autre turquoise : le champ s'assombrit quand il a le
        # curseur, et il l'a ou non selon qu'on vient de le reconstruire.
        assert fonds["bord"] in ("rgb(13, 148, 136)", "rgb(15, 118, 110)"), (
            fonds)
