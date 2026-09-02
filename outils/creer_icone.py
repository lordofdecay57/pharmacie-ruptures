# -*- coding: utf-8 -*-
"""Fabrique l'icône de l'application : une gélule blanche sur turquoise.

Outil de développement : le résultat (``pharmacie.ico``)
est versionné dans le dépôt, de sorte que le poste de la pharmacie n'a
**jamais** besoin de Pillow ni d'une police emoji pour afficher son raccourci.
Ce script ne sert qu'à régénérer ces deux fichiers si le visuel change.

Le motif est **dessiné**, pas copié d'une police emoji : une police couleur
(NotoColorEmoji) n'existe qu'en une seule taille de bitmap, et la réduction à
16 px — la taille utilisée dans la barre des tâches Windows — donne une bouillie
illisible. Un tracé vectoriel reste net à toutes les tailles.

Parti pris graphique : **monochrome**. Un seul motif blanc sur l'aplat
turquoise de l'application, sans contour noir ni seconde couleur, et du vide
autour. Le relief vient d'une ombre portée très douce, pas d'un trait — c'est
ce qui distingue une icône d'un pictogramme de dessin animé.

Usage :

    python outils/creer_icone.py
"""

from __future__ import annotations

import io
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

RACINE = Path(__file__).resolve().parent.parent

#: Turquoise de l'application (bandeau et onglet actif) : le raccourci du
#: bureau doit se reconnaître d'un coup d'œil comme « la même chose » que
#: l'écran qui s'ouvre. Léger dégradé vertical, juste assez pour que la
#: tuile ne soit pas plate.
FOND_HAUT = (17, 132, 120)
FOND_BAS = (11, 84, 78)

BLANC = (255, 255, 255)
#: Séparation des deux demi-coques : un trait dans le ton du fond, jamais du
#: noir — un liseré sombre sur une forme blanche fait aussitôt « autocollant ».
SEPARATION = (13, 108, 99)

#: Tailles inscrites dans le .ico. Windows pioche celle qui lui convient :
#: 16 dans la barre des tâches, 32 dans l'explorateur, 256 en grandes
#: icônes. Une seule taille suffirait à l'affichage mais laisserait le
#: système redimensionner lui-même, avec un rendu flou.
TAILLES = (16, 24, 32, 48, 64, 128, 256)

#: À partir de cette taille, la vignette est compressée en PNG (256 px non
#: compressé pèse à lui seul 256 Ko). En dessous, on reste en bitmap brut :
#: voir ``assembler_ico``.
SEUIL_PNG = 128

#: On dessine 8× trop grand puis on réduit : les bords obliques de la gélule
#: sont ainsi lissés, sans avoir à tracer le moindre antialiasing à la main.
COTE = 1024
SUR_ECHANTILLON = 8


def _fond(cote: int) -> Image.Image:
    """Carré aux coins arrondis, en dégradé turquoise vertical."""
    degrade = Image.new("RGB", (1, cote))
    for y in range(cote):
        part = y / max(cote - 1, 1)
        degrade.putpixel((0, y), tuple(
            round(haut + (bas - haut) * part)
            for haut, bas in zip(FOND_HAUT, FOND_BAS)))
    degrade = degrade.resize((cote, cote))

    masque = Image.new("L", (cote, cote), 0)
    ImageDraw.Draw(masque).rounded_rectangle(
        (0, 0, cote - 1, cote - 1), radius=round(cote * 0.225), fill=255)

    image = Image.new("RGBA", (cote, cote), (0, 0, 0, 0))
    image.paste(degrade, (0, 0), masque)
    return image


def _gelule(longueur: int, epaisseur: int) -> Image.Image:
    """Gélule horizontale, blanche, sur fond transparent.

    Dessinée à plat puis tournée par l'appelant — une rotation de l'image
    entière est bien plus simple (et plus propre) qu'un tracé oblique.
    """
    marge = 4                       # évite que la rotation rogne les bords
    taille = (longueur + 2 * marge, epaisseur + 2 * marge)
    boite = (marge, marge, marge + longueur - 1, marge + epaisseur - 1)

    image = Image.new("RGBA", taille, (0, 0, 0, 0))
    trace = ImageDraw.Draw(image)
    trace.rounded_rectangle(boite, radius=epaisseur // 2, fill=BLANC)

    # Le seul détail intérieur : la jonction des deux demi-coques. Un trait
    # fin, dans le ton du fond — il disparaît de lui-même en 16 px, où la
    # gélule doit de toute façon se lire comme une seule forme.
    milieu = marge + longueur // 2
    trace.line((milieu, boite[1] + 1, milieu, boite[3] - 1),
               fill=SEPARATION, width=max(2, round(epaisseur * 0.035)))
    return image


def _ombre(motif: Image.Image, cote: int) -> tuple:
    """Ombre portée très douce du motif, et son décalage vertical.

    Elle détache la gélule du fond sans ajouter le moindre trait : c'est ce
    qui remplace le contour noir de la première version.
    """
    ombre = Image.new("RGBA", motif.size, (0, 0, 0, 0))
    ombre.paste((0, 0, 0, 70), mask=motif.split()[3])
    return (ombre.filter(ImageFilter.GaussianBlur(cote * 0.012)),
            round(cote * 0.012))


def construire(cote: int = COTE) -> Image.Image:
    """Icône complète, en RGBA, au côté demandé."""
    grand = cote * SUR_ECHANTILLON

    gelule = _gelule(round(grand * 0.60), round(grand * 0.245))
    gelule = gelule.rotate(45, resample=Image.BICUBIC, expand=True)
    motif = Image.new("RGBA", (grand, grand), (0, 0, 0, 0))
    motif.alpha_composite(gelule, ((grand - gelule.width) // 2,
                                   (grand - gelule.height) // 2))

    image = _fond(grand)
    ombre, decalage = _ombre(motif, grand)
    image.alpha_composite(ombre, (0, decalage))
    image.alpha_composite(motif)

    return image.resize((cote, cote), Image.LANCZOS)


def _charge_utile(icone: Image.Image, taille: int, format_bitmap: str) -> bytes:
    """Contenu d'une seule vignette, tel que Pillow sait l'encoder.

    On passe par un .ico mono-taille puis on en extrait la charge utile :
    fabriquer un DIB à la main (en-tête, lignes inversées, masque de
    transparence) serait du code délicat que Pillow écrit déjà juste.
    """
    tampon = io.BytesIO()
    icone.resize((taille, taille), Image.LANCZOS).save(
        tampon, format="ICO", sizes=[(taille, taille)],
        bitmap_format=format_bitmap)
    octets = tampon.getvalue()
    longueur, decalage = struct.unpack("<II", octets[6 + 8:6 + 16])
    return octets[decalage:decalage + longueur]


def assembler_ico(icone: Image.Image, tailles=TAILLES) -> bytes:
    """Assemble le fichier .ico, vignette par vignette.

    Pillow encode **tout** en PNG, y compris les petites tailles. Windows
    récent s'en accommode, mais la barre des tâches et le cache d'icônes de
    certaines versions n'affichent alors rien du tout. On garde donc le
    format historique (DIB) en dessous de 128 px — celui que tous les
    Windows savent lire — et le PNG au-delà, où il divise le poids par dix.
    """
    vignettes = [
        (t, _charge_utile(icone, t, "png" if t >= SEUIL_PNG else "bmp"))
        for t in sorted(tailles)]

    entete = struct.pack("<HHH", 0, 1, len(vignettes))
    decalage = len(entete) + 16 * len(vignettes)
    annuaire, corps = b"", b""
    for taille, donnees in vignettes:
        annuaire += struct.pack(
            "<BBBBHHII", taille % 256, taille % 256, 0, 0, 1, 32,
            len(donnees), decalage)
        corps += donnees
        decalage += len(donnees)
    return entete + annuaire + corps


def ecrire(dossier: Path = RACINE) -> Path:
    """Écrit ``pharmacie.ico`` et renvoie son chemin.

    Le PNG d'aperçu 1024 px qui l'accompagnait ne servait qu'à la
    documentation, et descendait pourtant sur le poste de la pharmacie
    à chaque mise à jour. Un fichier de plus à ne pas reconnaître dans
    un dossier où l'on cherche déjà lancer.bat.
    """
    ico = dossier / "pharmacie.ico"
    ico.write_bytes(assembler_ico(construire()))
    return ico


def main() -> int:
    ico = ecrire()
    print(f"{ico.name} — {ico.stat().st_size} octets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
