# -*- coding: utf-8 -*-
"""L'icône du Bureau et le script qui la pose.

Ces fichiers ne sont exécutés par personne pendant les tests : c'est
Windows qui affiche l'icône et PowerShell qui crée le raccourci. Ce qu'on
peut vérifier ici — et qui suffit à éviter les régressions réellement
survenues — c'est que l'icône est présente dans le dépôt, qu'elle contient
les tailles dont Windows a besoin, et que le script pointe bien sur les
fichiers voisins.
"""

from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
ICONE = RACINE / "pharmacie.ico"
APERCU = RACINE / "pharmacie.png"
SCRIPT = RACINE / "creer-raccourci.bat"
LANCEUR = RACINE / "lancer.bat"

#: Doit rester identique à ``outils/creer_icone.py``.
TAILLES_ATTENDUES = {16, 24, 32, 48, 64, 128, 256}


class TestIcone:
    def test_icone_versionnee(self):
        """L'icône est livrée toute faite : le poste de la pharmacie n'a ni
        Pillow ni police emoji pour la fabriquer."""
        assert ICONE.is_file(), "pharmacie.ico manquant à la racine"
        assert APERCU.is_file(), "pharmacie.png manquant à la racine"

    def test_toutes_les_tailles_windows(self):
        """Sans la petite taille, Windows réduit lui-même le 256 px et
        l'icône de la barre des tâches devient une bouillie."""
        Image = pytest.importorskip("PIL.Image", reason="Pillow absent")
        with Image.open(ICONE) as image:
            tailles = {largeur for largeur, hauteur in image.info["sizes"]
                       if largeur == hauteur}
        assert TAILLES_ATTENDUES <= tailles, (
            f"tailles manquantes : {sorted(TAILLES_ATTENDUES - tailles)}")

    def test_petites_tailles_en_bitmap_brut(self):
        """Pillow encode tout en PNG par défaut ; la barre des tâches de
        certains Windows n'affiche alors rien. Les petites vignettes doivent
        rester au format historique (DIB), le PNG étant réservé aux grandes
        où il divise le poids par dix."""
        import struct
        octets = ICONE.read_bytes()
        nombre = struct.unpack("<H", octets[4:6])[0]
        formats = {}
        for i in range(nombre):
            entree = octets[6 + 16 * i:6 + 16 * (i + 1)]
            largeur = entree[0] or 256
            decalage = struct.unpack("<I", entree[12:16])[0]
            formats[largeur] = (
                "PNG" if octets[decalage:decalage + 4] == b"\x89PNG" else "DIB")

        for taille, format_ in sorted(formats.items()):
            attendu = "PNG" if taille >= 128 else "DIB"
            assert format_ == attendu, f"{taille} px encodé en {format_}"

    def test_le_generateur_reproduit_l_icone(self, tmp_path):
        """Le script de fabrication et le fichier livré ne doivent pas
        diverger : sinon on retouche le générateur sans que l'icône bouge."""
        pytest.importorskip("PIL.Image", reason="Pillow absent")
        import sys
        sys.path.insert(0, str(RACINE / "outils"))
        import creer_icone

        ico, png = creer_icone.ecrire(tmp_path)
        assert ico.read_bytes() == ICONE.read_bytes()
        assert png.read_bytes() == APERCU.read_bytes()


class TestScriptDeRaccourci:
    def test_script_present(self):
        assert SCRIPT.is_file()

    def _texte(self, avec_commentaires: bool = True) -> str:
        texte = SCRIPT.read_text(encoding="utf-8", errors="replace")
        if avec_commentaires:
            return texte
        return "\n".join(l for l in texte.splitlines()
                         if not l.strip().upper().startswith("REM"))

    def test_pointe_sur_le_lanceur_et_l_icone(self):
        texte = self._texte()
        assert "lancer.bat" in texte
        assert "pharmacie.ico" in texte

    def test_bureau_resolu_par_windows(self):
        """Un chemin en dur ``%USERPROFILE%\\Desktop`` rate les postes dont
        le Bureau est redirigé (OneDrive, profil itinérant) : le raccourci
        atterrit dans un dossier que l'utilisateur ne voit jamais."""
        instructions = self._texte(avec_commentaires=False)
        assert "GetFolderPath('Desktop')" in instructions
        assert "%USERPROFILE%\\Desktop" not in instructions

    def test_guillemets_equilibres(self):
        """Un guillemet orphelin dans un .bat ne se voit qu'à l'exécution,
        sur le poste de la pharmacie — et avale silencieusement la fin de la
        ligne. Un précédent bug de ce type a coûté une version."""
        for numero, ligne in enumerate(
                self._texte(avec_commentaires=False).splitlines(), 1):
            assert ligne.count('"') % 2 == 0, (
                f"guillemet non refermé ligne {numero} : {ligne}")

    def test_mode_silencieux_pour_l_appel_automatique(self):
        """Au premier lancement le script est appelé par lancer.bat : il ne
        doit ni afficher de fenêtre ni attendre une touche."""
        assert "/silencieux" in self._texte()


class TestPremierLancement:
    """L'icône doit apparaître sans que personne ait à chercher un script."""

    def test_le_lanceur_cree_l_icone(self):
        texte = LANCEUR.read_text(encoding="utf-8", errors="replace")
        assert "creer-raccourci.bat" in texte
        assert "/silencieux" in texte

    def test_une_seule_fois(self):
        """Un témoin évite qu'une icône supprimée volontairement revienne à
        chaque démarrage."""
        texte = LANCEUR.read_text(encoding="utf-8", errors="replace")
        assert ".raccourci-bureau" in texte

    def test_le_temoin_reste_local_au_poste(self):
        """Il ne doit ni être versionné ni voyager dans une mise à jour."""
        ignore = (RACINE / ".gitignore").read_text(encoding="utf-8")
        assert ".raccourci-bureau" in ignore
