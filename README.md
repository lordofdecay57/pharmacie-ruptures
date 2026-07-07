# 💊 Gestion des ruptures de stock — pharmacie

Application **locale** (elle tourne sur votre PC, hors-ligne) qui croise chaque
jour :

1. le **cadencier** de la pharmacie (ventes + stock actuel),
2. la liste des **ruptures GPNC** (`ruptgpnc_ia`) — fournisseur principal,
3. la liste des **ruptures UNIPHARMA** (`ruptocdp_ia`) — fournisseur de dépannage,

et produit le fichier Excel de décision `commande_ruptures_AAAA-MM-JJ.xlsx`
(3 onglets : à commander chez UNIPHARMA · rupture chez les deux · traçabilité).

## La règle métier (stricte, sans buffer)

Un produit en rupture GPNC **que vous vendez** apparaît uniquement si :

- il a une date de réappro : `stock (en jours) < jours jusqu'à la réappro`
  (strictement — ex. Titanoréine réappro 16 j / stock 18 j → n'apparaît pas) ;
- il n'a pas de date de réappro : `stock (en jours) < 30` (objectif 30 jours
  de couverture).

S'il apparaît : disponible chez UNIPHARMA → **Onglet 1** avec la quantité à
commander (`Cmd`) et l'urgence (🔴 stock épuisé ou ≤ 3 j · 🟡 4-15 j ·
🟢 > 15 j) ; en rupture aussi chez UNIPHARMA → **Onglet 2** (anticiper
l'information patient, contacter GPNC).

## Anticipation des ruptures à venir

- **🔭 Vigilance stock** : produits que vous vendez, HORS liste de ruptures
  GPNC, dont la couverture passe sous 7 jours (réglable) — la rupture en
  rayon arrive, commander chez GPNC avant qu'elle se produise.
- **⚠️ Écartés de justesse** : produits écartés par la règle stricte avec
  moins de 3 jours de marge (réglable) — si la date de réappro glisse,
  c'est la rupture sèche. Visibles dans un onglet dédié, sans modifier la
  règle de commande.
- **Délai de livraison UNIPHARMA** (réglable, 1 jour par défaut) : ajouté à
  la couverture cible du calcul de `Cmd` — les boîtes commandées aujourd'hui
  n'arrivent pas aujourd'hui.
- **Tendance de la demande** : ↗ / ↘ / → par produit (3 derniers mois vs
  moyenne globale) ; option « rotation prudente » qui retient la moyenne la
  plus élevée pour ne jamais sous-couvrir un produit en croissance.
- **Dates de réappro repoussées** : l'historique mémorise la date annoncée ;
  si elle glisse d'une analyse à l'autre, alerte « repoussée N fois » —
  fournisseur peu fiable sur ce produit, privilégier le dépannage.
- **Ruptures longues** : un produit aux ventes écrasées à 0 sur toute la
  période mais déjà signalé dans l'historique passe en « À vérifier » au
  lieu d'être écarté en silence.

Les seuils se règlent dans la barre latérale (« 🎛️ Réglages d'anticipation »).

## Fonctionnalités complémentaires

- **Commande en cours** (colonne facultative du cadencier) : une quantité déjà
  commandée mais pas reçue est déduite du calcul de couverture et de `Cmd`,
  pour éviter de recommander ce qui est déjà en route.
- **Fiabilité de la rotation** : si un mois de ventes est à 0 au milieu de
  mois actifs, l'outil signale « ⚠️ rupture passée possible » — la rotation
  est probablement sous-estimée (le produit était en rupture, pas sans
  demande), à corriger manuellement si besoin.
- **Péremption / DLUO** (colonne facultative du cadencier) : alerte
  informative si la péremption est à moins de 90 jours — n'écarte pas le
  produit, sert juste à vérifier avant de commander davantage.
- **Suivi quotidien** : chaque analyse (hors mode démo) est ajoutée à
  `historique_commandes.csv` (local, jamais versionné). À chaque analyse,
  l'écran affiche le comparatif avec la précédente — 🆕 nouvelles ruptures à
  traiter, ✅ ruptures sorties de la liste — et l'onglet 1 marque chaque
  produit « 🆕 nouveau » ou « 🔁 N fois » (rupture qui traîne). Une
  ré-analyse le même jour remplace celle du jour (pas de doublon).

## Installation (une seule fois)

1. **Installer Python** (3.10 ou plus récent) : <https://www.python.org/downloads/>
   — sous Windows, cochez bien **« Add Python to PATH »** pendant l'installation.
2. Récupérer ce dossier `pharmacie-ruptures/` sur le PC (clé USB, téléchargement…).
3. C'est tout : le script de lancement installe les dépendances tout seul la
   première fois.

Installation manuelle si besoin :

```
pip install -r requirements.txt
```

## Lancement

- **Windows** : double-cliquez sur `lancer.bat`.
- **Mac** : double-cliquez sur `lancer.command` (la première fois : clic droit
  → Ouvrir, pour passer l'avertissement de sécurité).
- **À la main** : `streamlit run app.py`

Le navigateur s'ouvre sur `http://localhost:8501`. Pour arrêter l'app :
fermez la fenêtre noire (ou Ctrl+C dedans).

💡 **Pour découvrir l'outil sans fichiers** : cliquez sur
« 🧪 Essayer avec des données de démonstration » sur l'écran d'accueil —
l'analyse tourne sur un jeu fictif (Titanoréine, Ozempic, Aranesp…) sans
toucher à votre configuration.

## Utilisation (chaque jour)

1. **Exportez et déposez les 3 fichiers du jour** (`.xlsx`, `.xls` ou `.csv`)
   dans les trois zones.
2. **Vérifiez les colonnes** détectées (libellé, CIP, stock, ventes
   mensuelles, date de réappro) — corrigez avec les menus déroulants si
   besoin. Votre choix est **mémorisé** (`config.yaml`) : le lendemain,
   il est pré-rempli.
3. Choisissez la **date d'analyse** et la **période de rotation** (moyenne
   annuelle par défaut, ou 3 derniers mois) dans la **barre latérale** — qui
   affiche aussi la progression (fichiers déposés, analyse lancée).
4. Cliquez **« Lancer l'analyse »** : les 3 onglets s'affichent à l'écran avec
   le code couleur d'urgence et un bandeau de résumé.
5. Cliquez **« Télécharger le fichier Excel »**.

⚠️ Les correspondances de produits **incertaines** (libellés proches mais pas
identiques entre les fichiers) sont listées dans un panneau dédié : vérifiez-les
avant de commander. Le matching utilise le **code CIP en priorité** quand il est
présent dans les fichiers — c'est le plus fiable.

## Structure du projet

```
pharmacie-ruptures/
├── app.py                 # interface (Streamlit) — n'appelle que le moteur
├── .streamlit/config.toml # thème de l'interface (vert pharmacie)
├── moteur_ruptures.py     # moteur métier pur, testable indépendamment
├── config.yaml            # mapping de colonnes mémorisé (créé au 1er lancement)
├── historique_commandes.csv # historique des analyses (créé à la 1re analyse)
├── requirements.txt       # dépendances Python
├── lancer.bat             # double-clic Windows
├── lancer.command         # double-clic Mac
├── README.md
└── tests/
    └── test_moteur.py     # 82 tests (dont Titanoréine, Ozempic, Aranesp)
```

## Tests

```
cd pharmacie-ruptures
python -m pytest tests/ -q
```

Les cas de référence validés en conversation sont couverts :
Titanoréine (réappro 16 j, stock 18 j → écartée), Ozempic 1 mg (stock 5,
~16,5/mois → ~9 j → 🟡 modéré, Cmd 12), Aranesp 150 (stock 0, réappro 2 j →
🔴 urgent, Cmd ≥ 1).
