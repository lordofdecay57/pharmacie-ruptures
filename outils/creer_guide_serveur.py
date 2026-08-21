# -*- coding: utf-8 -*-
"""Fabrique « Guide-installation-serveur.pdf » : une étape par page.

Pourquoi un PDF alors que ``INSTALLATION-SERVEUR.txt`` existe déjà : les
deux ne se lisent pas dans la même situation. Le texte brut s'ouvre sans
rien installer et se copie ; le PDF **s'imprime et se coche**, debout
devant la machine, une page à la fois — c'est ce qui évite de perdre sa
place au milieu d'une installation qui dure trois quarts d'heure.

Le contenu est décrit UNE fois, dans ``ETAPES`` ci-dessous. Un test
compare ce qui est vérifiable entre le PDF et le texte brut (les étapes,
les scripts nommés, les avertissements), pour que les deux documents ne
divergent pas en silence.

Pas d'émoji : les polices PDF standard n'en ont pas le glyphe, et elles
sortiraient en carrés noirs à l'impression.

Régénérer après une retouche :

    python outils/creer_guide_serveur.py
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / "Guide-installation-serveur.pdf"

TITRE = "Installation sur un serveur"
SOUS_TITRE = "Pilotage pharmacie — toute la pharmacie sur une seule base"

#: Turquoise de l'application, ambre des avertissements, rouge du danger.
VERT = "#0f766e"
AMBRE = "#b45309"
ROUGE = "#b91c1c"
GRIS = "#57534e"
GRIS_CLAIR = "#f2f6f5"

#: Chaque étape : (numéro, titre, pourquoi, [actions], [(type, texte)]).
#: ``type`` vaut "attention" (ambre) ou "danger" (rouge).
ETAPES = [
    ("0", "Récupérer les données des postes",
     "C'est la seule étape de ce guide qu'on ne peut pas rattraper : ce qui "
     "a été scanné sur un poste n'existe nulle part ailleurs.",
     ["Sur chaque poste DÉJÀ équipé, ouvrez le dossier de l'utilitaire "
      "(celui qui contient lancer.bat).",
      "Copiez sur une clé USB les fichiers présents parmi : "
      "stock_ferme.csv, stock_ferme_produits.csv, commandes_speciales.csv, "
      "config.yaml, historique_commandes.csv.",
      "Un seul poste avait des données ? Vous les remettrez à l'étape 1, et "
      "tout sera conservé.",
      "Plusieurs postes avaient des données ? Gardez les clés de côté, "
      "installez le serveur avec le poste le plus complet, et demandez la "
      "fusion des autres — elles ne peuvent pas être recopiées les unes sur "
      "les autres."],
     [("danger", "NE SUPPRIMEZ RIEN sur les postes avant l'étape 8.")]),

    ("1", "Installer Python et le dossier",
     "Tout vit sur le serveur : c'est le seul ordinateur où l'on installe "
     "quoi que ce soit.",
     ["Installez Python depuis python.org, en cochant « Add python.exe to "
      "PATH ». C'est l'étape la plus souvent oubliée.",
      "Copiez le dossier « pharmacie-ruptures » sur le serveur, par exemple "
      "dans Documents.",
      "Si vous avez récupéré des fichiers de données, copiez-les MAINTENANT "
      "dans ce dossier, à côté de lancer.bat."],
     [("attention", "C'est le moment ou jamais pour les données : une fois "
                    "l'utilitaire démarré, il créerait ses propres fichiers "
                    "vides.")]),

    ("2", "Premier démarrage, et l'adresse à noter",
     "Le serveur affiche lui-même l'adresse que les postes devront ouvrir.",
     ["Double-cliquez sur lancer-serveur.bat — et NON sur lancer.bat, qui "
      "est fait pour un poste isolé.",
      "Une fenêtre noire s'ouvre. La première fois, elle installe des "
      "compléments : du texte défile une à deux minutes, c'est normal.",
      "Notez l'adresse affichée, par exemple http://192.168.1.10:8501. "
      "Vous en aurez besoin à l'étape 7.",
      "Si Windows demande « Autoriser Python à communiquer sur ces "
      "réseaux ? » : cochez Réseaux privés, décochez Réseaux publics, puis "
      "Autoriser l'accès. L'étape 3 est alors déjà faite."],
     [("attention", "Cette fenêtre noire EST l'application. La fermer arrête "
                    "l'utilitaire pour TOUTE la pharmacie.")]),

    ("3", "Ouvrir le port 8501 dans le pare-feu",
     "C'est l'oubli qui explique presque tous les « ça ne marche pas ».",
     ["Si vous avez cliqué « Autoriser l'accès » à l'étape 2, passez à "
      "l'étape 4.",
      "Sinon : menu Démarrer, tapez cmd, clic DROIT sur « Invite de "
      "commandes », puis « Exécuter en tant qu'administrateur ».",
      "Collez la commande ci-dessous en UNE SEULE LIGNE, puis Entrée.",
      "Vérifiez ensuite le profil du réseau : netsh advfirewall show "
      "currentprofile"],
     [("code", 'netsh advfirewall firewall add rule '
               'name="Pilotage pharmacie (8501)" dir=in action=allow '
               'protocol=TCP localport=8501 profile=private'),
      ("attention", "Le piège : cette règle ne s'applique QUE si Windows "
                    "considère le réseau comme « privé ». S'il répond "
                    "« Public », allez dans Paramètres > Réseau et Internet "
                    "> Ethernet et passez « Type de profil réseau » sur "
                    "« Privé ». Sur un réseau public, Windows bloque tout, "
                    "règle ou pas.")]),

    ("4", "Donner une adresse IP fixe au serveur",
     "Sans cela l'adresse change, et toutes les icônes des postes pointent "
     "dans le vide.",
     ["D'ABORD : en a-t-il déjà une ? Tapez ipconfig /all et cherchez la "
      "ligne « DHCP activé » de la carte utilisée.",
      "« DHCP activé : Non » — l'adresse est déjà fixe, passez à l'étape 5.",
      "« DHCP activé : Oui » — cela ne prouve rien : une réservation faite "
      "dans la box donne toujours la même adresse tout en passant par le "
      "DHCP. Vérifiez dans la box, rubrique DHCP > Baux statiques.",
      "MÉTHODE A (la meilleure) : relevez l'« Adresse physique » du serveur "
      "(son adresse MAC) et associez-la à une adresse fixe dans la box.",
      "MÉTHODE B : Paramètres > Réseau et Internet > Ethernet > Attribution "
      "IP > Modifier > Manuel. Préfixe de sous-réseau 24, passerelle et DNS "
      "= adresse de la box."],
     [("attention", "Si vous fixez l'adresse sur Windows, choisissez-en une "
                    "HORS de la plage distribuée par la box (si elle donne "
                    ".100 à .150, prenez .200). Sinon la box la donnera un "
                    "jour à un autre appareil, et les deux se gêneront un "
                    "matin sans qu'on comprenne pourquoi.")]),

    ("5", "Empêcher la mise en veille",
     "L'oubli auquel personne ne pense : un serveur endormi ne répond plus, "
     "et les postes affichent une page blanche sans explication.",
     ["Paramètres > Système > Alimentation.",
      "Réglez « Veille » sur « Jamais ».",
      "Le réglage de l'écran, lui, n'a aucune importance."],
     []),

    ("6", "La mise à jour automatique",
     "Un serveur allumé en permanence ne se met JAMAIS à jour tout seul : la "
     "mise à jour n'a lieu qu'au démarrage, et se reporte tant que "
     "l'application répond.",
     ["Double-cliquez UNE FOIS sur planifier-maj-serveur.bat.",
      "Windows fera la mise à jour chaque nuit à 5 h 00. Le script affiche "
      "la fiche enregistrée pour que vous puissiez la vérifier.",
      "Une autre heure : planifier-maj-serveur.bat 04:30. "
      "Pour annuler : planifier-maj-serveur.bat /supprimer.",
      "Le compte rendu de chaque nuit est écrit dans maj_serveur.log."],
     [("attention", "La session Windows du serveur doit rester OUVERTE — "
                    "écran verrouillé, c'est parfait ; déconnecté, la tâche "
                    "ne partira pas. Et la mise à jour redémarre "
                    "l'application : les postes perdent leur page une "
                    "trentaine de secondes. D'où l'heure creuse.")]),

    ("7", "Sur chaque poste : poser l'icône",
     "Rien n'est installé sur les postes. Ni Python, ni l'application, ni "
     "données : ils reçoivent une icône, qui n'est qu'une adresse.",
     ["Sur chaque poste, UNE SEULE FOIS, double-cliquez sur "
      "creer-raccourci-poste.bat.",
      "Trois façons d'y accéder : depuis le dossier du serveur partagé sur "
      "le réseau, en copiant ce seul fichier sur une clé USB, ou — sans "
      "script du tout — en tapant l'adresse dans le navigateur et en la "
      "mettant en favori.",
      "Il trouve l'adresse tout seul si le dossier du serveur est partagé. "
      "Sinon il la demande : tapez celle notée à l'étape 2.",
      "Une icône « Pharmacie » apparaît sur le Bureau. Double-cliquez pour "
      "vérifier TOUT DE SUITE que la page s'ouvre depuis ce poste."],
     [("attention", "La page ne s'ouvre pas ? C'est presque toujours "
                    "l'étape 3 (le pare-feu) ou le profil réseau resté sur "
                    "« Public ».")]),

    ("8", "Retirer les anciennes installations",
     "À faire seulement quand les étapes 1 à 7 fonctionnent, et quand vous "
     "avez vérifié que les données récupérées sont bien visibles dans "
     "l'application du serveur.",
     ["Supprimez le dossier « pharmacie-ruptures » du poste.",
      "Supprimez l'ANCIENNE icône du Bureau (celle qui lançait la copie "
      "locale), et gardez la nouvelle.",
      "Il n'y a pas de désinstallation au sens Windows : ce sont de simples "
      "dossiers et raccourcis."],
     [("danger", "Si vous laissez la copie locale, un jour quelqu'un la "
                 "lancera par erreur — l'ancienne icône est encore là — et "
                 "scannera dans un stock fantôme que personne d'autre ne "
                 "voit. Rien ne plante, rien ne prévient, et on s'en aperçoit "
                 "à l'inventaire.")]),
]

QUOTIDIEN = [
    "La fenêtre noire du serveur reste ouverte en permanence. On peut la "
    "réduire, jamais la fermer.",
    "Si le serveur redémarre (coupure, mise à jour Windows), quelqu'un doit "
    "relancer lancer-serveur.bat. Pour que cela se fasse tout seul : placez "
    "un raccourci vers ce fichier dans le dossier « shell:startup » "
    "(Windows + R, tapez shell:startup, Entrée).",
    "Les postes n'ont rien à faire : ils ouvrent leur icône.",
    "Plusieurs comptoirs peuvent scanner en même temps sans rien perdre : "
    "chaque geste est appliqué au fichier relu à l'instant, sous verrou.",
    "Mise à jour immédiate : quand le bandeau annonce une version, un "
    "encadré apparaît en haut de la colonne de gauche. Un clic depuis "
    "N'IMPORTE QUEL poste met à jour le serveur.",
    "Sauvegarde : tout tient dans le dossier du serveur. C'est plus simple "
    "qu'avant — et désormais indispensable, puisqu'il n'y a plus de copie "
    "sur les postes.",
]

DEPANNAGE = [
    ("Un poste n'ouvre pas la page",
     "La fenêtre noire du serveur est-elle ouverte ? Le port 8501 est-il "
     "autorisé (étape 3) ? Le réseau est-il « Privé » et non « Public » ? "
     "L'adresse de l'icône est-elle encore la bonne (étape 4) ?"),
    ("L'adresse du serveur a changé",
     "Rien n'est perdu : l'icône d'un poste est un simple fichier texte. "
     "Relancez creer-raccourci-poste.bat avec la nouvelle adresse, ou ouvrez "
     "Pharmacie.url sur le Bureau avec le Bloc-notes et corrigez la ligne "
     "URL=."),
    ("« Le fichier est ouvert dans un autre programme »",
     "Un fichier de données est ouvert dans Excel sur le serveur. Fermez "
     "Excel et refaites le geste : rien n'a été perdu."),
    ("La mise à jour de la nuit ne s'est pas faite",
     "Ouvrez maj_serveur.log dans le dossier du serveur : il dit ce qui "
     "s'est passé. La cause la plus fréquente est une session Windows "
     "déconnectée (étape 6)."),
    ("Le serveur ne répond plus le matin",
     "Vérifiez la mise en veille (étape 5), puis que la fenêtre noire est "
     "toujours là."),
]

CONFIDENTIALITE = (
    "L'utilitaire fonctionne sur le réseau local de la pharmacie. Vos "
    "données ne sont envoyées à aucun serveur extérieur : seules "
    "l'installation et les mises à jour utilisent Internet.\n\n"
    "À DÉCIDER EN CONNAISSANCE DE CAUSE : le module « Commandes spéciales » "
    "contient des NOMS DE PATIENTS associés à des traitements. "
    "L'application n'a PAS de mot de passe : toute personne qui atteint le "
    "réseau de la pharmacie peut l'ouvrir. C'est acceptable sur un réseau "
    "d'officine fermé, ce ne l'est pas sur un réseau ouvert au public.\n\n"
    "N'exposez jamais le port 8501 sur Internet.")


def _styles():
    from reportlab.lib.colors import HexColor
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    base = getSampleStyleSheet()
    return {
        "titre": ParagraphStyle(
            "titre", parent=base["Title"], fontSize=26, leading=30,
            textColor=HexColor(VERT), spaceAfter=6),
        "sous_titre": ParagraphStyle(
            "sous_titre", parent=base["Normal"], fontSize=12, leading=16,
            textColor=HexColor(GRIS), alignment=1),
        "etape_titre": ParagraphStyle(
            "etape_titre", parent=base["Heading1"], fontSize=19, leading=23,
            textColor=HexColor(VERT), spaceAfter=2),
        "pourquoi": ParagraphStyle(
            "pourquoi", parent=base["Normal"], fontSize=11, leading=15,
            textColor=HexColor(GRIS), fontName="Helvetica-Oblique",
            spaceAfter=14),
        "action": ParagraphStyle(
            "action", parent=base["Normal"], fontSize=11.5, leading=16),
        "encadre": ParagraphStyle(
            "encadre", parent=base["Normal"], fontSize=10.5, leading=14.5),
        "code": ParagraphStyle(
            "code", parent=base["Normal"], fontSize=8.5, leading=12,
            fontName="Courier"),
        "section": ParagraphStyle(
            "section", parent=base["Heading1"], fontSize=17, leading=21,
            textColor=HexColor(VERT), spaceAfter=10),
        "corps": ParagraphStyle(
            "corps", parent=base["Normal"], fontSize=11, leading=15.5),
    }


def _teinte(couleur: str, part: float = 0.09):
    """Version pâle d'une couleur, obtenue en la mélangeant à du blanc.

    Pas d'alpha : « #b91c1c14 » n'est pas une couleur transparente pour
    ReportLab mais un entier 32 bits — le fond sortait presque noir, et le
    texte de l'encadré DANGER devenait illisible. Un mélange se calcule, et
    s'imprime tel qu'il s'affiche.
    """
    from reportlab.lib.colors import Color, HexColor

    fond = HexColor(couleur)
    return Color(fond.red * part + (1 - part),
                 fond.green * part + (1 - part),
                 fond.blue * part + (1 - part))


def _encadre(texte: str, couleur: str, etiquette: str, style):
    """Un bandeau coloré : ce qu'il ne faut pas rater sur cette page."""
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table, TableStyle
    from xml.sax.saxutils import escape

    contenu = Paragraph(f"<b>{escape(etiquette)}</b> &nbsp; {escape(texte)}",
                        style)
    tableau = Table([[contenu]], colWidths=[165 * mm])
    tableau.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _teinte(couleur)),
        ("LINEBEFORE", (0, 0), (0, -1), 3, HexColor(couleur)),
        ("TEXTCOLOR", (0, 0), (-1, -1), HexColor(couleur)),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return tableau


def _action(numero: int, texte: str, style):
    """Une action, précédée d'une case à cocher.

    Le guide s'imprime : cocher au fur et à mesure évite de perdre sa place
    au milieu d'une installation qui dure trois quarts d'heure.
    """
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table, TableStyle
    from xml.sax.saxutils import escape

    case = Table([[""]], colWidths=[5 * mm], rowHeights=[5 * mm])
    case.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.9, HexColor(GRIS)),
        ("BACKGROUND", (0, 0), (-1, -1), white),
    ]))
    ligne = Table(
        [[case, Paragraph(escape(texte), style)]],
        colWidths=[10 * mm, 155 * mm])
    ligne.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return ligne


def _habillage(canevas, document):
    """Bandeau de tête et pied de page, sur chaque page sauf la couverture."""
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm

    largeur, hauteur = A4
    canevas.saveState()
    if document.page > 1:
        canevas.setFillColor(HexColor(VERT))
        canevas.rect(0, hauteur - 14 * mm, largeur, 14 * mm, stroke=0, fill=1)
        canevas.setFillColor(white)
        canevas.setFont("Helvetica-Bold", 9.5)
        canevas.drawString(18 * mm, hauteur - 9.5 * mm, TITRE.upper())
        canevas.setFont("Helvetica", 9.5)
        canevas.drawRightString(largeur - 18 * mm, hauteur - 9.5 * mm,
                                f"page {document.page}")
    canevas.setFillColor(HexColor(GRIS))
    canevas.setFont("Helvetica", 8)
    canevas.drawCentredString(
        largeur / 2, 10 * mm,
        "Pilotage pharmacie — la même procédure en texte brut : "
        "INSTALLATION-SERVEUR.txt")
    canevas.restoreState()


def _couverture(styles):
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer

    return [
        Spacer(1, 55 * mm),
        Paragraph(TITRE, styles["titre"]),
        Paragraph(SOUS_TITRE, styles["sous_titre"]),
        Spacer(1, 22 * mm),
        Paragraph(
            "<b>Ce que cela change.</b> Aujourd'hui, chaque poste a SA base : "
            "ce qui est scanné au comptoir 1 n'existe pas au comptoir 2. "
            "Après cette installation, l'utilitaire tourne sur UN SEUL "
            "ordinateur — le serveur — et les postes s'y connectent par leur "
            "navigateur. Une seule base, une seule mise à jour, une seule "
            "sauvegarde.", styles["corps"]),
        Spacer(1, 6 * mm),
        Paragraph(
            "<b>Rien n'est installé sur les postes.</b> Ni Python, ni "
            "l'application, ni données : ils reçoivent une icône, qui n'est "
            "qu'une adresse.", styles["corps"]),
        Spacer(1, 6 * mm),
        Paragraph(
            "<b>Une page par étape</b>, dans l'ordre, avec des cases à "
            "cocher. Comptez environ 45 minutes.", styles["corps"]),
        Spacer(1, 14 * mm),
        _encadre("Commencez par la page suivante, avant d'installer quoi que "
                 "ce soit : c'est la seule étape irréversible du guide.",
                 ROUGE, "À LIRE D'ABORD", styles["encadre"]),
    ]


def _page_etape(etape, styles):
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, Spacer

    numero, titre, pourquoi, actions, encadres = etape
    entete = ("AVANT DE COMMENCER" if numero == "0" else f"ÉTAPE {numero}")
    blocs = [PageBreak(), Spacer(1, 6 * mm),
             Paragraph(f'<font color="{GRIS}" size="11">{entete}</font><br/>'
                       f"{titre}", styles["etape_titre"]),
             Paragraph(pourquoi, styles["pourquoi"])]
    for i, action in enumerate(actions, 1):
        blocs.append(_action(i, action, styles["action"]))
    for genre, texte in encadres:
        blocs.append(Spacer(1, 5 * mm))
        if genre == "code":
            # L'etiquette est DANS l'encadre : imprimee, la commande tient
            # sur deux lignes, et sans ce rappel sous les yeux on la recopie
            # avec un retour a la ligne au milieu - elle echoue alors.
            blocs.append(_encadre(texte, GRIS, "UNE SEULE LIGNE :",
                                  styles["code"]))
        else:
            blocs.append(_encadre(
                texte, ROUGE if genre == "danger" else AMBRE,
                "DANGER" if genre == "danger" else "ATTENTION",
                styles["encadre"]))
    return blocs


def _pages_finales(styles):
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, Spacer
    from xml.sax.saxutils import escape

    blocs = [PageBreak(), Spacer(1, 6 * mm),
             Paragraph("Au quotidien", styles["section"])]
    for point in QUOTIDIEN:
        blocs.append(_action(0, point, styles["action"]))

    blocs += [PageBreak(), Spacer(1, 6 * mm),
              Paragraph("En cas de problème", styles["section"])]
    for symptome, remede in DEPANNAGE:
        blocs.append(Paragraph(f"<b>{escape(symptome)}</b>", styles["corps"]))
        blocs.append(Paragraph(escape(remede), styles["corps"]))
        blocs.append(Spacer(1, 5 * mm))

    blocs += [Spacer(1, 8 * mm),
              Paragraph("Confidentialité", styles["section"])]
    for paragraphe in CONFIDENTIALITE.split("\n\n"):
        blocs.append(Paragraph(escape(paragraphe), styles["corps"]))
        blocs.append(Spacer(1, 4 * mm))
    return blocs


def creer(sortie: Path = SORTIE) -> Path:
    """Écrit le PDF et renvoie son chemin."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate

    document = SimpleDocTemplate(
        str(sortie), pagesize=A4, title=f"{TITRE} — Pilotage pharmacie",
        author="Pilotage pharmacie", topMargin=22 * mm, bottomMargin=18 * mm,
        leftMargin=22 * mm, rightMargin=22 * mm)
    styles = _styles()
    elements = list(_couverture(styles))
    for etape in ETAPES:
        elements += _page_etape(etape, styles)
    elements += _pages_finales(styles)
    document.build(elements, onFirstPage=_habillage, onLaterPages=_habillage)
    return sortie


if __name__ == "__main__":
    chemin = creer()
    print(f"{chemin} — {chemin.stat().st_size // 1024} Ko")
    sys.exit(0)
