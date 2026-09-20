"""Récapitulatif de facturation, envoyé uniquement après configuration locale.

Un envoi au maximum par jour et par installation. Une tentative incertaine
ne repart jamais automatiquement : SMTP ne garantit pas l'idempotence.
"""
from __future__ import annotations

import json
import logging
import os
import re
import smtplib
import ssl
import threading
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlparse

import locations_suivi as suivi
from stockage_partage import verrou_fichier

CONFIG = "rappels_location.local.json"
JOURNAL = "rappels_location_envois.json"
_journal = logging.getLogger("pharmacie.rappels")


def configuration(dossier):
    path = Path(dossier) / CONFIG
    if not path.exists():
        return {"actif": False, "destinataire": "", "expediteur": "", "hote": "", "port": 465,
                "securite": "SSL", "utilisateur": "", "heure": "08:00", "jours": [0, 1, 2, 3, 4], "url": ""}
    return json.loads(path.read_text(encoding="utf-8"))


def valider(config):
    for key in ("destinataire", "expediteur"):
        if not re.fullmatch(r"[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+", config.get(key, "")):
            raise ValueError("Renseignez une adresse de destination et une adresse d'expéditeur valides.")
    if not config.get("hote") or any(c.isspace() for c in config["hote"]):
        raise ValueError("Renseignez le serveur SMTP.")
    if config.get("securite") not in ("SSL", "STARTTLS") or not 1 <= int(config["port"]) <= 65535:
        raise ValueError("Vérifiez la connexion SMTP sécurisée.")
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", config.get("heure", "")):
        raise ValueError("Renseignez l'heure au format HH:MM.")
    if not config.get("jours") or any(j not in range(7) for j in config["jours"]):
        raise ValueError("Choisissez au moins un jour d'envoi.")
    if config.get("url"):
        parsed = urlparse(config["url"])
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("L'adresse de l'utilitaire doit être un lien http ou https sans identifiants.")


def enregistrer_configuration(dossier, config):
    if config.get("actif"):
        valider(config)
        if config.get("utilisateur") and not os.environ.get("PHARMACIE_SMTP_PASSWORD"):
            raise ValueError("Le mot de passe SMTP doit être configuré sur le serveur avant l'activation.")
    # Ne jamais accepter un secret via ce fichier ou le navigateur partagé.
    config = {k: config.get(k) for k in configuration_defaut()}
    path = Path(dossier) / CONFIG
    with verrou_fichier(path):
        suivi.ecrire_json(path, config)


def configuration_defaut():
    return dict.fromkeys(("actif", "destinataire", "expediteur", "hote", "port", "securite",
                          "utilisateur", "heure", "jours", "url"))


def composer(state, config, today=None):
    tasks = suivi.taches(state, today)
    n = len(tasks["facturer"])
    incomplets = len(tasks["completer"])
    renouvellements = len(tasks["renouveler"])
    if not (n or incomplets or renouvellements):
        return None
    msg = EmailMessage()
    msg["From"] = config["expediteur"]
    msg["To"] = config["destinataire"]
    msg["Subject"] = f"Pharmacie — {n} facturation(s) à préparer"
    lignes = [f"{n} période(s) de location ou achat à facturer.",
              f"{incomplets} dossier(s) à compléter avant facturation.",
              f"{renouvellements} dossier(s) à renouveler, dont les derniers mois de prise en charge.",
              "", "Consultez le module Location pour les périodes et les actions à effectuer.",
              "Ce rappel ne crée aucune facture."]
    if config.get("url"):
        lignes.extend(["", config["url"]])
    msg.set_content("\n".join(lignes))
    return msg


def envoyer_smtp(msg, config):
    context = ssl.create_default_context()
    cls = smtplib.SMTP_SSL if config["securite"] == "SSL" else smtplib.SMTP
    kwargs = {"timeout": 20}
    if config["securite"] == "SSL":
        kwargs["context"] = context
    with cls(config["hote"], int(config["port"]), **kwargs) as client:
        if config["securite"] == "STARTTLS":
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        if config.get("utilisateur"):
            password = os.environ.get("PHARMACIE_SMTP_PASSWORD")
            if not password:
                raise ValueError("Configuration SMTP incomplète")
            client.login(config["utilisateur"], password)
        client.send_message(msg)


def executer(dossier, *, instant=None, transport=None):
    """Une itération du serveur ; aucune donnée patient ne sort par mail."""
    dossier = Path(dossier)
    config = configuration(dossier)
    if not config.get("actif"):
        return "désactivé"
    valider(config)
    now = (instant or suivi.maintenant()).astimezone(suivi.NOUMEA)
    if now.weekday() not in config["jours"] or now.strftime("%H:%M") < config["heure"]:
        return "hors horaire"
    msg = composer(suivi.lire(dossier / suivi.FICHIER), config, now.date())
    if msg is None:
        return "rien à rappeler"
    path = dossier / JOURNAL
    key = now.date().isoformat()
    with verrou_fichier(path):
        journal = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if key in journal:
            return "déjà tenté"
        journal[key] = {"statut": "En cours ou résultat à vérifier", "date": now.isoformat()}
        suivi.ecrire_json(path, journal)
    try:
        (transport or envoyer_smtp)(msg, config)
        statut = "Envoyé"
    except Exception as error:
        statut = "Échec ou résultat incertain — vérifier avant tout renvoi"
        _journal.warning("Rappel non confirmé (%s)", type(error).__name__)
    with verrou_fichier(path):
        journal = json.loads(path.read_text(encoding="utf-8"))
        journal[key]["statut"] = statut
        suivi.ecrire_json(path, journal)
    return statut


def demarrer(dossier):
    """À appeler une seule fois par processus via st.cache_resource."""
    def travail():
        attente = threading.Event()
        while True:
            try:
                executer(dossier)
            except Exception as error:
                _journal.warning("Rappels suspendus (%s) : vérifier la configuration locale", type(error).__name__)
            attente.wait(60)
    thread = threading.Thread(target=travail, name="rappels-locations", daemon=True)
    thread.start()
    return thread


if __name__ == "__main__":
    import ui_commun
    print(executer(ui_commun.dossier_donnees()))
