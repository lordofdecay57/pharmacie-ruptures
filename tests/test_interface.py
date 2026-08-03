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
    """Charge la page et renvoie les erreurs JavaScript observées."""
    erreurs: list = []
    page.on("pageerror", lambda e: erreurs.append(str(e)))
    page.goto(url, wait_until="networkidle")
    page.wait_for_timeout(4000)
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


class TestDemarrage:
    def test_accueil_s_affiche(self, page, application):
        erreurs = _ouvrir(page, application)
        assert erreurs == []
        _sans_exception(page)
        assert "Pilotage pharmacie" in page.content()

    def test_les_deux_espaces_sont_proposes(self, page):
        assert page.get_by_text("Stock en rotation & ruptures").count() >= 1
        assert page.get_by_text("Stock fermé (inventaire scanné)").count() >= 1

    def test_depot_de_fichiers_demande_avant_analyse(self, page):
        """Sans cadencier, le parcours principal invite à en déposer un
        plutôt que de planter."""
        assert "Déposez" in page.content()


class TestEspaceStockFerme:
    """Le module 3 doit fonctionner SANS aucun fichier déposé."""

    def test_ecran_complet(self, page):
        page.get_by_text("Stock fermé (inventaire scanné)").first.click()
        page.wait_for_timeout(5000)
        _sans_exception(page)
        contenu = page.content()
        for attendu in ("Scannez le produit", "Inventaire",
                        "Imprimez ou exportez", "Entrée", "Sortie"):
            assert attendu in contenu, f"« {attendu} » absent de l'écran"

    def test_scan_d_un_produit_inconnu_ouvre_la_fiche(self, page):
        champ = page.get_by_placeholder("Douchez la boîte")
        champ.fill("0103400937000013" + "17280331" + "10LOT-TEST")
        champ.press("Enter")
        page.wait_for_timeout(5000)
        _sans_exception(page)
        assert "Fiche du produit à enregistrer" in page.content()

    def test_sortie_sur_inventaire_vide_est_refusee_proprement(self, page):
        page.get_by_text("Sortie", exact=False).first.click()
        page.wait_for_timeout(3000)
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
