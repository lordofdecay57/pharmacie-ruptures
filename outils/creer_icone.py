# -*- coding: utf-8 -*-
"""Fabrique l'icône de l'application (💊 sur fond turquoise).

Outil de développement : le résultat (``pharmacie.ico`` et ``pharmacie.png``)
est versionné dans le dépôt, de sorte que le poste de la pharmacie n'a
**jamais** besoin de Pillow ni d'une police emoji pour afficher son raccourci.
Ce script ne sert qu'à régénérer ces deux fichiers si le visuel change.

Le motif est **dessiné**, pas copié d'une police emoji : une police couleur
(NotoColorEmoji) n'existe qu'en une seule taille de bitmap, et la réduction à
16 px — la taille utilisée dans la barre des tâches Windows — donne une bouillie
illisible. Un tracé vectoriel reste net à toutes les tailles.

Usage :

    python outils/creer_icone.py
"""

from __future__ import annotations

import io
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw

RACINE = Path(__file__).resolve().parent.parent

#: Turquoise de l'application (bandeau et onglet actif) : le raccourci du
#: bureau doit se reconnaître d'un coup d'œil comme « la même chose » que
#: l'écran qui s'ouvre.
FOND_HAUT = (17, 138, 125)
FOND_BAS = (13, 90, 84)

BLANC = (255, 255, 255)
AMBRE = (249, 146, 47)
CONTOUR = (8, 61, 57)

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
        (0, 0, cote - 1, cote - 1), radius=round(cote * 0.22), fill=255)

    image = Image.new("RGBA", (cote, cote), (0, 0, 0, 0))
    image.paste(degrade, (0, 0), masque)
    return image


def _gelule(longueur: int, epaisseur: int) -> Image.Image:
    """Gélule horizontale : moitié blanche, moitié ambre, sur fond transparent.

    Dessinée à plat puis tournée par l'appelant — une rotation de l'image
    entière est bien plus simple (et plus propre) qu'un tracé oblique.
    """
    marge = round(epaisseur * 0.12)      # place pour le contour, non rogné
    taille = (longueur + 2 * marge, epaisseur + 2 * marge)
    boite = (marge, marge, marge + longueur - 1, marge + epaisseur - 1)
    rayon = epaisseur // 2
    milieu = marge + longueur // 2

    # Les deux demi-coques sont découpées dans UNE seule silhouette, par
    # masque : dessiner deux rectangles arrondis mitoyens laisserait un
    # liseré transparent au raccord, visible dès la réduction en 32 px.
    silhouette = Image.new("L", taille, 0)
    ImageDraw.Draw(silhouette).rounded_rectangle(boite, radius=rayon, fill=255)
    demi_droite = silhouette.copy()
    ImageDraw.Draw(demi_droite).rectangle((0, 0, milieu, taille[1]), fill=0)

    image = Image.new("RGBA", taille, (0, 0, 0, 0))
    image.paste(BLANC, mask=silhouette)
    image.paste(AMBRE, mask=demi_droite)

    # Le trait de séparation des deux demi-coques, puis le contour général :
    # sans eux, la gélule blanche se fond dans les fortes réductions.
    trace = ImageDraw.Draw(image)
    trace.line((milieu, boite[1], milieu, boite[3]),
               fill=CONTOUR, width=round(epaisseur * 0.05))
    trace.rounded_rectangle(boite, radius=rayon, outline=CONTOUR,
                            width=round(epaisseur * 0.07))
    return image


def construire(cote: int = COTE) -> Image.Image:
    """Icône complète, en RGBA, au côté demandé."""
    grand = cote * SUR_ECHANTILLON
    image = _fond(grand)

    gelule = _gelule(round(grand * 0.62), round(grand * 0.30))
    gelule = gelule.rotate(45, resample=Image.BICUBIC, expand=True)
    image.alpha_composite(gelule, (
        (grand - gelule.width) // 2, (grand - gelule.height) // 2))

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


def ecrire(dossier: Path = RACINE) -> tuple:
    """Écrit ``pharmacie.ico`` et ``pharmacie.png``; renvoie les deux chemins."""
    icone = construire()
    ico = dossier / "pharmacie.ico"
    png = dossier / "pharmacie.png"
    ico.write_bytes(assembler_ico(icone))
    icone.save(png, format="PNG")          # Mac, Linux, documentation
    return ico, png


def main() -> int:
    ico, png = ecrire()
    for chemin in (ico, png):
        print(f"{chemin.name} — {chemin.stat().st_size} octets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
