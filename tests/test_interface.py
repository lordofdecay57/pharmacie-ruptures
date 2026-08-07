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


@pytest.fixture(scope="module")
def application(tmp_path_factory):
    """Streamlit lancé sur un port libre, sur des données JETABLES.

    ``PHARMACIE_DONNEES`` déplace la configuration, l'historique et
    l'inventaire du stock fermé dans un dossier temporaire. Sans cette
    variable, ces fichiers vivent à côté du programme (et non dans le
    répertoire de lancement) : le test lirait — et écraserait — les données
    réelles de la pharmacie.
    """
    pytest.importorskip("streamlit")
    pytest.importorskip("playwright")
    if not Path(NAVIGATEUR).exists():
        pytest.skip("navigateur Playwright absent")

    port = _port_libre()
    travail = tmp_path_factory.mktemp("appli")
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
def page(application):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        navigateur = p.chromium.launch(executable_path=NAVIGATEUR)
        onglet = navigateur.new_page(viewport={"width": 1400, "height": 1000})
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
                        "Pré-remplir les noms"):
            assert attendu in contenu, f"« {attendu} » absent de l'écran"

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
