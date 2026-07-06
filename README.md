# 💊 Gestion des ruptures de stock — pharmacie

Application **locale** (elle tourne sur votre PC, hors-ligne) qui croise chaque
semaine :

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

## Utilisation (chaque semaine)

1. **Déposez les 3 fichiers** (`.xlsx`, `.xls` ou `.csv`) dans les trois zones.
2. **Vérifiez les colonnes** détectées (libellé, CIP, stock, ventes
   mensuelles, date de réappro) — corrigez avec les menus déroulants si
   besoin. Votre choix est **mémorisé** (`config.yaml`) : la semaine suivante,
   il est pré-rempli.
3. Choisissez la **date d'analyse** et la **période de rotation** (moyenne
   annuelle par défaut, ou 3 derniers mois).
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
├── moteur_ruptures.py     # moteur métier pur, testable indépendamment
├── config.yaml            # mapping de colonnes mémorisé (créé au 1er lancement)
├── requirements.txt       # dépendances Python
├── lancer.bat             # double-clic Windows
├── lancer.command         # double-clic Mac
├── README.md
└── tests/
    └── test_moteur.py     # 45 tests (dont Titanoréine, Ozempic, Aranesp)
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
