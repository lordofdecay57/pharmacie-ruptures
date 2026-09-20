"""Dossiers de location : périodes, accords, factures et cautions.

Les montants sont ceux saisis par l'équipe, jamais un tarif CAFAT déduit.
L'ancien CSV reste intact. Les écritures JSON sont atomiques et verrouillées.
"""
from __future__ import annotations

import copy
import csv
import json
import os
import tempfile
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from location import ajouter_mois, cle_patient, parser_date, parser_mode, MODE_ACHAT
from stockage_partage import verrou_fichier

FICHIER = "locations_suivi.json"
PRISES = ("À vérifier", "Remboursable", "Non remboursable")
CATEGORIES = ("Matelas à air", "Lit médicalisé", "Fauteuil roulant", "Aérosol",
              "Tensiomètre", "Assistance respiratoire", "Autre matériel")
CYCLES = ("Mensuel", "Hebdomadaire", "28 jours", "Ponctuel")
CAUTIONS = {"Aérosol": 5000, "Tensiomètre": 3000}
NOUMEA = timezone(timedelta(hours=11), "Pacific/Noumea")


def maintenant():
    return datetime.now(NOUMEA)


def texte(value):
    return " ".join(str(value or "").split())


def jour(value):
    result = parser_date(value)
    if result is None:
        raise ValueError("Renseignez une date valide.")
    return result


def iso(value):
    return jour(value).isoformat() if value else ""


def montant(value):
    try:
        n = float(value)
        if not n.is_integer() or n < 0 or n > 100_000_000:
            raise ValueError
        return int(n)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Le montant doit être un nombre entier positif en F CFP.") from None


def obligatoire(value, nom):
    value = texte(value)
    if not value:
        raise ValueError(f"Renseignez {nom}.")
    return value


def vide():
    return {"schema": 1, "revision": 0, "dossiers": [], "factures": [],
            "materiels": {}, "journal": [], "equipe": [], "alerte_j": 30}


def ecrire_json(path, contenu):
    """À appeler sous verrou. Aucun fichier incomplet ne remplace le bon."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, nom = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(contenu, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(nom, path)
    finally:
        if os.path.exists(nom):
            os.unlink(nom)


def lire(path):
    path = Path(path)
    if not path.exists():
        return vide()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if (state.get("schema") != 1 or not isinstance(state["dossiers"], list)
                or not isinstance(state["factures"], list)):
            raise ValueError
        return state
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise ValueError("Le fichier de suivi est illisible. Il est conservé : restaurez une sauvegarde avant de poursuivre.") from error


def categorie_ancienne(nom):
    nom = cle_patient(nom)
    for morceau, categorie in (("MATELAS", "Matelas à air"), ("LIT", "Lit médicalisé"),
                              ("FAUTEUIL", "Fauteuil roulant"), ("AEROSOL", "Aérosol"),
                              ("TENSIOMETRE", "Tensiomètre")):
        if morceau in nom:
            return categorie
    return "Autre matériel"


def nouveau(patient, categorie, debut, acteur, *, materiel="", mode=None,
            cycle="Mensuel", terme="Début de période", prise="À vérifier",
            fin_prevue="", appareil="", notes=""):
    if categorie not in CATEGORIES or cycle not in CYCLES or prise not in PRISES:
        raise ValueError("Catégorie, périodicité ou prise en charge inconnue.")
    mode = mode or ("Achat" if categorie == "Fauteuil roulant" else "Location")
    if mode not in ("Achat", "Location") or terme not in ("Début de période", "Fin de période"):
        raise ValueError("Mode de fourniture ou échéance inconnu.")
    debut = jour(debut).isoformat()
    fin_prevue = iso(fin_prevue)
    if fin_prevue and fin_prevue < debut:
        raise ValueError("La fin prévue précède le début.")
    if mode == "Location" and cycle == "Ponctuel" and not fin_prevue:
        raise ValueError("Une location ponctuelle nécessite une date de fin prévue.")
    return {"id": uuid.uuid4().hex, "revision": 0,
            "patient": obligatoire(patient, "le patient"), "categorie": categorie,
            "materiel": texte(materiel) or categorie, "mode": mode,
            "debut": debut, "debut_suivi": debut, "fin_prevue": fin_prevue,
            "cycle": "Ponctuel" if mode == "Achat" else cycle, "terme": terme,
            "prise": prise, "motif": "", "verifie_par": "", "verifie_le": "",
            "prescription": "", "appareil": texte(appareil), "notes": texte(notes),
            "cree_par": obligatoire(acteur, "votre nom dans l'équipe"),
            "accords": [], "retour": "", "etat_retour": "", "reprise_a_verifier": False,
            "source_ancienne": None, "achat_historique": False,
            "caution": {"montant": CAUTIONS.get(categorie, 0) if mode == "Location" else 0,
                        "mode": "À préciser", "etat": "À recevoir" if mode == "Location" and categorie in CAUTIONS else "Sans caution"}}


def initialiser(path, ancien_csv=None):
    """Import une seule fois, sans inférer de périodes à partir d'une facture."""
    path = Path(path)
    with verrou_fichier(path):
        if path.exists():
            return lire(path)
        state = vide()
        if ancien_csv and Path(ancien_csv).exists():
            with Path(ancien_csv).open(encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f, delimiter=";")
                if not {"Patient", "Matériel"}.issubset(reader.fieldnames or []):
                    raise ValueError("L'ancien CSV ne contient pas les colonnes Patient et Matériel ; il est conservé sans modification.")
                for row in reader:
                    if not any(row.values()):
                        continue
                    d = nouveau(row.get("Patient") or "À compléter", categorie_ancienne(row.get("Matériel")),
                                parser_date(row.get("Début de location")) or date.today(),
                                "Reprise des dossiers", materiel=row.get("Matériel") or "À compléter",
                                mode="Achat" if parser_mode(row.get("Mode")) == MODE_ACHAT else "Location",
                                notes=row.get("Notes", ""))
                    d.update(source_ancienne=row, reprise_a_verifier=True,
                             debut=iso(parser_date(row.get("Début de location"))), debut_suivi="")
                    # Aucune caution n'est supposée convenue ou reçue pour un ancien contrat.
                    d["caution"] = {"montant": 0, "mode": "À préciser", "etat": "Sans caution"}
                    state["dossiers"].append(d)
            state["migration"] = {"date": maintenant().isoformat(), "source": Path(ancien_csv).name}
        ecrire_json(path, state)
        return state


def dossier(state, identifiant):
    for d in state["dossiers"]:
        if d["id"] == identifiant:
            return d
    raise ValueError("Ce dossier n'existe plus. Rechargez l'écran.")


def factures(state, d):
    return [f for f in state["factures"] if f["dossier"] == d["id"] and f["etat"] != "Annulée"]


def chevauche(a, b, c, e):
    return a <= e and c <= b


def couverture(d, debut, fin):
    """Une union de couvertures consécutives, sans masquer un trou."""
    cursor = jour(debut)
    for a in sorted((a for a in d["accords"] if a["statut"] == "Accordée"), key=lambda a: a["du"]):
        start, end = jour(a["du"]), jour(a["au"])
        if end < cursor:
            continue
        if start > cursor:
            return False
        cursor = end + timedelta(days=1)
        if cursor > jour(fin):
            return True
    return False


def obstacles(d):
    if d.get("achat_historique"):
        return []
    result = []
    if d["reprise_a_verifier"]:
        result.append("Reprise de l'ancien dossier à vérifier")
    if not d["debut_suivi"]:
        result.append("Début de facturation à renseigner")
    if d["prise"] == "À vérifier":
        result.append("Conditions de prise en charge à vérifier")
    elif not d["motif"] or not d["verifie_par"]:
        result.append("Motif de prise en charge à documenter")
    if d["prise"] == "Remboursable":
        if not d["prescription"]:
            result.append("Référence de prescription à renseigner")
        if not any(a["statut"] == "Accordée" for a in d["accords"]):
            result.append("Accord ou fondement de couverture à enregistrer")
    return result


def periodes(state, d, aujourdhui=None, *, toutes=False):
    """Échéances de préparation, indépendantes des dates d'émission.

    Une périodicité choisie n'est pas une unité tarifaire. Une période
    écourtée est signalée pour saisie manuelle du montant.
    """
    today = aujourdhui or maintenant().date()
    if not d["debut_suivi"] or d["reprise_a_verifier"] or d.get("achat_historique"):
        return []
    debut = jour(d["debut"] or d["debut_suivi"])
    reprise = jour(d["debut_suivi"])
    limites = [jour(v) for v in (d["retour"], d["fin_prevue"]) if v]
    accords = [a for a in d["accords"] if a["statut"] == "Accordée"]
    if d["prise"] == "Remboursable":
        if not accords:
            return []
        limites.append(max(jour(a["au"]) for a in accords))
    horizon = min(limites) if limites else ajouter_mois(today, 1)
    horizon = min(horizon, ajouter_mois(today, 60)) if toutes else min(horizon, ajouter_mois(today, 1))
    if horizon < debut:
        return []
    existantes = factures(state, d)
    resultat = []
    if d["cycle"] == "Mensuel":
        premiere = max(0, (reprise.year - debut.year) * 12 + reprise.month - debut.month - 1)
    elif d["cycle"] in ("Hebdomadaire", "28 jours"):
        premiere = max(0, (reprise - debut).days // (7 if d["cycle"] == "Hebdomadaire" else 28))
    else:
        premiere = 0
    for numero in range(premiere, premiere + 1200):
        if d["cycle"] == "Mensuel":
            start, suivant = ajouter_mois(debut, numero), ajouter_mois(debut, numero + 1)
        elif d["cycle"] in ("Hebdomadaire", "28 jours"):
            pas = 7 if d["cycle"] == "Hebdomadaire" else 28
            start = debut + timedelta(days=pas * numero)
            suivant = start + timedelta(days=pas)
        else:
            if numero:
                break
            start = debut
            suivant = (jour(d["fin_prevue"]) if d["mode"] == "Location" else debut) + timedelta(days=1)
        if start > horizon:
            break
        debut_normal = start
        fin_normale = suivant - timedelta(days=1)
        fin = min(fin_normale, min(limites)) if limites else fin_normale
        if fin < reprise:
            continue
        start = max(start, reprise)
        echeance = start if d["terme"] == "Début de période" else fin
        if not toutes and echeance > today:
            break
        # Un ancien enregistrement chevauchant partiellement bloque la ligne,
        # il ne la fait pas disparaître comme si toute la période était couverte.
        overlapping = [f for f in existantes if chevauche(start.isoformat(), fin.isoformat(), f["du"], f["au"])]
        exacte = next((f for f in overlapping if f["du"] == start.isoformat() and f["au"] == fin.isoformat()), None)
        bloque = obstacles(d)
        if overlapping and not exacte:
            bloque.append("Une facture chevauche cette période : vérifier le journal")
        if d["prise"] == "Remboursable" and not couverture(d, start, fin):
            bloque.append("Accord ne couvrant pas toute la période")
        dernier = d["prise"] == "Remboursable" and not couverture(d, fin + timedelta(days=1), fin + timedelta(days=1))
        resultat.append({"id": f'{d["id"]}:{start}:{fin}', "dossier": d["id"],
                         "du": start.isoformat(), "au": fin.isoformat(), "echeance": echeance.isoformat(),
                         "numero": numero + 1, "partielle": fin < fin_normale or start > debut_normal, "dernier": dernier,
                         "blocages": bloque, "facture": exacte["id"] if exacte else ""})
    return resultat


def taches(state, aujourdhui=None):
    today = aujourdhui or maintenant().date()
    result = {"facturer": [], "completer": [], "renouveler": [], "cautions": [], "retours": [], "regulariser": []}
    for d in state["dossiers"]:
        for p in periodes(state, d, today):
            if not p["facture"] and not p["blocages"]:
                result["facturer"].append(p)
        problemes = obstacles(d)
        if any(p["blocages"] and not p["facture"] for p in periodes(state, d, today)):
            problemes.append("Période à vérifier")
        if problemes:
            result["completer"].append({"dossier": d["id"], "motifs": list(dict.fromkeys(problemes))})
        accords = [a for a in d["accords"] if a["statut"] == "Accordée"]
        if d["mode"] == "Location" and d["prise"] == "Remboursable" and accords and not d["retour"]:
            # Prochain segment ininterrompu : un accord futur avec un trou ne supprime pas l'alerte.
            actifs = [a for a in accords if jour(a["du"]) <= today <= jour(a["au"])]
            passes = [a for a in accords if jour(a["au"]) < today]
            if actifs:
                fin = max(jour(a["au"]) for a in actifs)
                for a in sorted(accords, key=lambda a: a["du"]):
                    if jour(a["du"]) <= fin + timedelta(days=1) and jour(a["au"]) > fin:
                        fin = jour(a["au"])
            elif passes:
                fin = max(jour(a["au"]) for a in passes)
            else:
                fin = jour(min(accords, key=lambda a: a["du"])["au"])
            dernier = any(p["dernier"] and p["au"] == fin.isoformat() for p in periodes(state, d, today))
            if (fin - today).days <= state.get("alerte_j", 30) or dernier:
                result["renouveler"].append({"dossier": d["id"], "fin": fin.isoformat(),
                    "demande_en_cours": any(a["statut"] == "Demandée" for a in accords_en_attente(d))})
        if d["retour"] and d["caution"]["etat"] == "Reçue":
            result["cautions"].append(d["id"])
        if d["mode"] == "Location" and not d["retour"] and d["fin_prevue"] and jour(d["fin_prevue"]) < today:
            result["retours"].append(d["id"])
        if d["retour"]:
            result["regulariser"].extend(f["id"] for f in factures(state, d) if f["au"] > d["retour"])
    return result


def accords_en_attente(d):
    return [a for a in d["accords"] if a["statut"] == "Demandée"]


def _evenement(state, d, action, acteur, details):
    acteur = obligatoire(acteur, "votre nom dans l'équipe")
    if acteur not in state["equipe"]:
        state["equipe"].append(acteur)
    state["journal"].append({"date": maintenant().isoformat(), "dossier": d["id"] if d else "",
                             "action": action, "auteur": acteur,
                             "details": {k: v.isoformat() if isinstance(v, (date, datetime)) else copy.deepcopy(v)
                                         for k, v in details.items()}})


def appliquer(path, action, *, identifiant="", acteur, revision=None, **params):
    """Chaque geste repart du disque et contrôle sa cible avant écriture."""
    path = Path(path)
    with verrou_fichier(path):
        state = lire(path)
        d = dossier(state, identifiant) if identifiant else None
        if d and revision is not None and d["revision"] != revision:
            raise ValueError("Ce dossier a changé sur un autre poste. Rechargez-le avant de recommencer.")
        executer(state, d, action, acteur, params)
        if d:
            d["revision"] += 1
        state["revision"] += 1
        # Copie de la dernière version lisible, sans remplacer le CSV d'origine.
        if path.exists():
            ecrire_json(path.with_suffix(".json.bak"), lire(path))
        ecrire_json(path, state)
        return state


def executer(state, d, action, acteur, p):
    obligatoire(acteur, "votre nom dans l'équipe")
    if action == "creer":
        d = nouveau(acteur=acteur, **p)
        identite = lambda x: (cle_patient(x["patient"]), cle_patient(x["materiel"]), x["mode"], cle_patient(x["appareil"]))
        if any(identite(ancien) == identite(d) and not ancien["retour"]
               and not ancien.get("achat_historique")
               and (ancien["mode"] == "Location" or not factures(state, ancien))
               for ancien in state["dossiers"]):
            raise ValueError("Un dossier actif identique existe déjà. Ouvrez-le ou précisez le numéro de l'autre appareil.")
        ref = d["appareil"]
        if ref and d["mode"] == "Location":
            if ref in state["materiels"] and state["materiels"][ref]["etat"] != "Disponible":
                raise ValueError("Cet appareil est déjà attribué ou attend un contrôle après retour.")
            state["materiels"][ref] = {"etat": "Attribué", "dossier": d["id"]}
        state["dossiers"].append(d)
    elif action == "qualifier":
        prise = p["prise"]
        if prise not in PRISES:
            raise ValueError("Prise en charge inconnue.")
        motif = obligatoire(p["motif"], "le motif et la référence des conditions vérifiées")
        d.update(prise=prise, motif=motif, verifie_par=acteur, verifie_le=jour(p["date"]).isoformat(),
                 prescription=texte(p.get("prescription")))
    elif action == "reprendre":
        if not d["reprise_a_verifier"]:
            raise ValueError("La reprise a déjà été effectuée.")
        debut = jour(p["debut"]).isoformat()
        suite = jour(p["debut_suivi"]).isoformat()
        if suite < debut:
            raise ValueError("La première période non facturée précède le début réel.")
        obligatoire(p["justification"], "la référence de la dernière période vérifiée")
        d.update(debut=debut, debut_suivi=suite, reprise_a_verifier=False,
                 achat_historique=bool(p.get("achat_deja_facture")) and d["mode"] == "Achat")
    elif action == "demander":
        if d["retour"]:
            raise ValueError("Le matériel est déjà revenu.")
        d["accords"].append({"id": uuid.uuid4().hex, "statut": "Demandée",
            "envoyee": jour(p["date"]).isoformat(), "canal": p.get("canal", "Mail"),
            "initiateur": obligatoire(p.get("initiateur") or acteur, "l'initiateur de la demande"),
            "envoi_enregistre_par": acteur, "reference_demande": obligatoire(p["reference"], "la référence de la demande"),
            "reception": "", "du": "", "au": "", "reference": ""})
    elif action == "accorder":
        a = next((a for a in d["accords"] if a["id"] == p["demande"]), None)
        if not a or a["statut"] != "Demandée":
            raise ValueError("Cette demande a déjà été traitée. Rechargez le dossier.")
        du, au, reception = jour(p["du"]).isoformat(), jour(p["au"]).isoformat(), jour(p["reception"]).isoformat()
        if au < du or reception < a["envoyee"]:
            raise ValueError("Les dates de l'accord sont incohérentes.")
        a.update(statut="Accordée", du=du, au=au, reception=reception,
                 reference=obligatoire(p["reference"], "la référence de l'accord"), enregistre_par=acteur)
    elif action == "refuser":
        a = next((a for a in d["accords"] if a["id"] == p["demande"]), None)
        if not a or a["statut"] != "Demandée":
            raise ValueError("Demande déjà traitée.")
        a.update(statut="Refusée", reception=jour(p["date"]).isoformat(), motif=obligatoire(p["motif"], "le motif du refus"), enregistre_par=acteur)
    elif action == "couverture":
        du, au = jour(p["du"]).isoformat(), jour(p["au"]).isoformat()
        if au < du:
            raise ValueError("La fin de couverture précède son début.")
        d["accords"].append({"id": uuid.uuid4().hex, "statut": "Accordée", "envoyee": "",
            "initiateur": acteur, "canal": "Vérification documentée", "reference_demande": "",
            "du": du, "au": au, "reception": jour(p["date"]).isoformat(), "enregistre_par": acteur,
            "reference": obligatoire(p["reference"], "le fondement de couverture et sa référence")})
    elif action == "facturer":
        pdate = jour(p["date"])
        periode = next((x for x in periodes(state, d, pdate) if x["id"] == p["periode"]), None)
        if not periode or periode["facture"] or periode["blocages"]:
            raise ValueError("La période n'est plus disponible ou son dossier est incomplet.")
        if (periode["partielle"] or periode["dernier"]) and not p.get("confirme"):
            raise ValueError("Confirmez la vérification du dernier mois ou de la période partielle.")
        reference = obligatoire(p["reference"], "la référence de facture")
        if any(f["reference"] == reference and f["dossier"] == d["id"] and f["etat"] != "Annulée" for f in state["factures"]):
            raise ValueError("Cette référence de facture existe déjà pour ce dossier.")
        state["factures"].append({"id": uuid.uuid4().hex, "dossier": d["id"],
            "du": periode["du"], "au": periode["au"], "emission": pdate.isoformat(),
            "reference": reference, "montant": montant(p["montant"]), "etat": "Émise",
            "auteur": acteur, "prise": d["prise"], "reglement": None})
    elif action in ("regler", "annuler_facture"):
        f = next((f for f in state["factures"] if f["id"] == p["facture"] and f["dossier"] == d["id"]), None)
        if not f or f["etat"] != "Émise":
            raise ValueError("Cette facture a déjà été réglée ou annulée.")
        if action == "regler":
            if jour(p["date"]).isoformat() < f["emission"]:
                raise ValueError("Le règlement précède la facture.")
            f.update(etat="Réglée", reglement={"date": jour(p["date"]).isoformat(), "auteur": acteur,
                                              "reference": obligatoire(p["reference"], "la référence du règlement")})
        else:
            f.update(etat="Annulée", motif_annulation=obligatoire(p["motif"], "le motif d'annulation"))
    elif action == "caution_prevoir":
        c = d["caution"]
        if c["etat"] in ("Reçue", "Restituée"):
            raise ValueError("Une caution reçue ne peut plus être modifiée.")
        valeur = montant(p["montant"])
        if p["mode"] not in ("À préciser", "Chèque", "Espèces"):
            raise ValueError("Choisissez chèque ou espèces.")
        c.update(montant=valeur, mode=p["mode"], etat="À recevoir" if valeur else "Sans caution")
    elif action == "caution_recevoir":
        c = d["caution"]
        if c["etat"] != "À recevoir" or d["retour"]:
            raise ValueError("Cette caution n'est pas à recevoir.")
        if p["mode"] not in ("Chèque", "Espèces"):
            raise ValueError("Choisissez chèque ou espèces.")
        c.update(etat="Reçue", mode=p["mode"], reception=jour(p["date"]).isoformat(), recu_par=acteur,
                 reference=obligatoire(p["reference"], "la référence du chèque ou du reçu"))
    elif action == "retour":
        if d["mode"] != "Location" or d["retour"]:
            raise ValueError("Ce matériel n'est pas en location active.")
        retour = jour(p["date"]).isoformat()
        if d["debut"] and retour < d["debut"]:
            raise ValueError("Le retour précède le début de location.")
        d.update(retour=retour, etat_retour=obligatoire(p["etat"], "l'état de l'appareil et des accessoires"))
        if d["appareil"]:
            state["materiels"][d["appareil"]] = {"etat": "À préparer", "dossier": d["id"]}
    elif action == "caution_restituer":
        c = d["caution"]
        if c["etat"] != "Reçue" or not d["retour"]:
            raise ValueError("Enregistrez le retour et vérifiez que la caution est encore détenue.")
        restitution = jour(p["date"]).isoformat()
        if restitution < max(d["retour"], c["reception"]):
            raise ValueError("La restitution précède le retour ou la réception de la caution.")
        c.update(etat="Restituée", restitution=restitution, rendu_par=acteur,
                 reference_restitution=obligatoire(p["reference"], "la référence de restitution"))
    elif action == "disponible":
        ref = p["appareil"]
        if ref not in state["materiels"] or state["materiels"][ref]["etat"] != "À préparer":
            raise ValueError("Cet appareil n'attend pas un contrôle.")
        state["materiels"][ref].update(etat="Disponible", controle_par=acteur, controle_le=jour(p["date"]).isoformat())
    elif action == "parametres":
        jours = int(p["alerte_j"])
        if not 1 <= jours <= 180:
            raise ValueError("Le délai d'alerte doit être compris entre 1 et 180 jours.")
        state.update(alerte_j=jours, equipe=list(dict.fromkeys(texte(n) for n in p["equipe"] if texte(n))))
    else:
        raise ValueError("Action inconnue.")
    _evenement(state, d, action, acteur, p)


def demonstration(today=None):
    """Scénario fictif en mémoire ; jamais écrit dans les dossiers patients."""
    today = today or maintenant().date()
    state = vide()
    start = today - timedelta(days=2)
    d = nouveau("PATIENT DÉMONSTRATION", "Matelas à air", start, "Camille (exemple)")
    d.update(prise="Remboursable", motif="Situation fictive vérifiée", verifie_par="Camille (exemple)",
             verifie_le=today.isoformat(), prescription="Prescription fictive")
    d["accords"].append({"id": "demo", "statut": "Accordée", "envoyee": (today - timedelta(days=15)).isoformat(),
        "initiateur": "Camille (exemple)", "canal": "Mail", "reference_demande": "EP-DEMO",
        "reception": start.isoformat(), "du": start.isoformat(),
        "au": (ajouter_mois(start, 6) - timedelta(days=1)).isoformat(), "reference": "ACCORD-DEMO"})
    state["dossiers"].append(d)
    return state
