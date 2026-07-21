# 💊 Pilotage pharmacie — stock & ruptures

Application **locale** (elle tourne sur votre PC, hors-ligne) organisée en
**deux modules fonctionnels indépendants**, chacun son onglet principal :

- **📦 Gestion des stocks en rotation** (`stock_rotation.py`) — calcule un
  **stock min** et un **stock max** par produit à partir du seul cadencier,
  pour éviter la rupture (sous-stockage) et l'immobilisation de trésorerie
  (sur-stockage). Ne nécessite QUE le cadencier.
- **🚨 Gestion des ruptures** (`moteur_ruptures.py`) — croise le cadencier
  avec les listes de ruptures **GPNC** (`ruptgpnc_ia`, fournisseur
  principal) et **UNIPHARMA** (`ruptocdp_ia`, dépannage) pour produire le
  fichier Excel de commande quotidien.

Les deux modules sont **strictement isolés l'un de l'autre** (aucun ne
connaît les structures de données de l'autre) mais **mutualisent** leurs
calculs de consommation (rotation, tendance, variabilité, classement ABC,
correction des ruptures passées) via un troisième module, `commun.py` —
voir [Architecture](#architecture) plus bas.

## 📦 Module 1 — Gestion des stocks en rotation

### Méthode de calcul

Politique min/max exprimée directement en **jours de couverture** :

```
Stock min = consommation/jour × 14 jours (+ ajustement week-end)
Stock max = consommation/jour × 30 jours
```

Les couvertures (14 j / 30 j par défaut) sont réglables dans la barre
latérale. Les bornes sont arrondies à la **boîte entière supérieure**
(une borne de 4,2 boîtes se tient en rayon avec 5) et le stock max ne
passe jamais sous le stock min.

**Suppression du stock min pour les petits produits (règle officine)** :
pour les lignes dont le **stock max calculé est inférieur à 10 boîtes**, le
stock min est **supprimé** (mis à 0) — ces petits produits ne sont plus
pilotés par un point de commande automatique. Seuls les produits vendus
≥ 10/mois (max ≥ 10) conservent un stock min et déclenchent des commandes.
Le motif signale les lignes concernées.

**Périodes de calcul de la consommation** : annuelle (12 mois),
**semestrielle (6 mois)**, trimestrielle (3 mois), mensuelle (dernier
mois) ou lissée — au choix dans la barre latérale.

**Cadencier n+1 — ne ressortir que les lignes modifiées** : l'analyse
mémorise le stock min/max de chaque produit (`etat_stock_precedent.csv`).
À l'analyse suivante, seules les lignes dont le stock min ou max a **varié
d'au moins 10 %** (ou les produits nouveaux) sont ré-affichées et exportées
— les lignes inchangées sont masquées pour ne pas relire les mêmes
produits. Une case permet de tout réafficher. La première analyse affiche
tout (pas de référence antérieure).

#### Ajustement week-end (pas de réception samedi/dimanche)

Les commandes ne sont pas réceptionnées le week-end. Le stock min est donc
gonflé le jour de l'analyse pour couvrir l'attente supplémentaire :

| Jour de l'analyse | Jours ajoutés au stock min | Pourquoi |
|---|---|---|
| Vendredi | +2 j | Commande du vendredi reçue lundi |
| Samedi | +1 j | Commande du samedi reçue lundi |
| Dimanche → jeudi | +0 j | Réception le lendemain ouvré |

L'ajustement appliqué est affiché dans l'interface au-dessus des résultats.

#### Fiabilité du calcul de consommation

- **Produits récemment référencés** : les mois à 0 vente AVANT la première
  vente (produit pas encore au catalogue) sont exclus de la moyenne — sans
  quoi un générique lancé il y a 4 mois verrait sa rotation divisée par 3
  et son stock min sous-dimensionné d'autant.
- **Doublons de codes CIP** (changement de générique ou de fournisseur) :
  quand le même produit apparaît sous deux codes, les lignes sont
  fusionnées (stock et ventes additionnés, code le plus récent conservé).
  Sans fusion, l'ancien code à stock 0 déclencherait une commande fantôme
  d'un produit déjà en rayon sous son nouveau code.
- **Ruptures passées** (option, activée par défaut) : un mois à 0 vente
  encadré de mois actifs est interprété comme une rupture et interpolé,
  pas compté comme une absence de demande.

### Règle métier des 10 unités (urgence CONFIRMÉE, pas seuil seul)

> Si le stock actuel d'un produit passe sous un **seuil absolu** (10 unités
> par défaut) **ET** sous son propre stock min calculé, la cible de
> réassort est fixée **directement au stock max** — commande immédiate,
> sans passer par un recomplètement progressif jusqu'au seul stock min.

Concrètement, `determiner_cible_reassort()` applique 3 paliers, dans cet
ordre de priorité :

| Condition | Cible | Alerte |
|---|---|---|
| rotation ≤ seuil (1 boîte/mois) | — (écarté) | ⚪ Rotation faible |
| `stock < seuil (10)` **et** `stock < stock min` | **Stock max** (commande immédiate) | 🔴 Action requise |
| `stock < stock min` (sans les deux conditions ci-dessus) | Stock min (réassort progressif) | 🟡 Sous le min |
| `stock ≥ stock min` | Stock actuel (rien à faire) | 🟢 OK |

Le seuil des 10 unités reste un filet de sécurité qui prime sur le
recomplètement progressif — mais il ne suffit **plus à lui seul** à
déclencher l'urgence. Pour un produit à faible rotation, le stock min
calculé (14 j de consommation) est souvent lui-même inférieur à 10 unités :
sans la double condition, un stock **déjà au-dessus de son propre
minimum** déclenchait quand même une commande immédiate jusqu'au stock
max — sur un cadencier réel de 3 500 produits, c'était le cas de **9
alertes rouges sur 10**, gonflant les quantités proposées de plus de 130 %
sans justification métier. Un produit à rotation nulle (arrêté) ne
déclenche jamais d'alerte si la quantité à commander calculée est nulle.

### Produits à rotation faible écartés du réassort (⚪)

Les produits vendus au maximum **1 boîte/mois** (seuil réglable) sont
écartés du réassort automatique : commander 1 boîte de chacune des
centaines de références vendues très rarement encombrerait la commande
sans enjeu réel. Sur le cadencier réel, ce filtre fait passer la commande
de **1 231 à 425 lignes** (−65 %) tout en conservant l'essentiel du volume.
Ces produits restent visibles et cherchables dans l'application (filtre
« ⚪ Rotation faible ») mais ne figurent pas dans le fichier Excel de
commande. Mettre le seuil à 0 les réintègre tous.

### Commandes déjà en cours (déduites du calcul)

Si la colonne « Commande en cours » du cadencier est renseignée, les
boîtes déjà commandées mais pas encore reçues sont ajoutées au stock
physique pour évaluer la cible et l'urgence (`stock effectif = stock +
en cours`) — comme le fait déjà le Module 2. Sans cette déduction, l'outil
recommanderait de commander à nouveau ce qui est déjà en route. La colonne
« Stock actuel » affichée reste le stock physique réel ; la déduction est
mentionnée dans le motif.

### Garde-fou des modes de calcul réactifs

Les modes « Mensuelle », « Trimestrielle » et « Lissée » privilégient les
ventes récentes. Problème : un produit qui rote sur l'année mais a eu **0
vente le dernier mois** (rupture ou creux ponctuel) verrait sa rotation
tomber à 0 et **disparaître du pilotage** — une rupture masquée. Garde-fou :
quand le calcul récent tombe à 0 alors que la moyenne annuelle est
positive, l'outil **retombe sur la moyenne annuelle** pour garder le
produit piloté (le motif le signale). Sur le cadencier réel, cela évite de
perdre de vue ~500 produits en mode mensuel.

### Colonne « Stock min conseillé (variabilité) » (indicative)

À côté du stock min/max, une colonne indicative propose un stock min
**majoré d'une marge de sécurité pour les produits à ventes irrégulières**.
Le stock min de base est identique pour tous (14 j de couverture) quelle
que soit la régularité ; or un produit erratique mérite plus de tampon
qu'un produit régulier à volume égal. La marge ne s'applique **qu'au-delà
du seuil de stabilité** (CV > 0,3) et reste plafonnée (+120 % au plus). Elle
**ne change pas la quantité à commander** — le pharmacien s'y réfère
librement pour sécuriser les produits à demande instable.

### Solution progressive si l'historique manque

Un produit sans aucune vente enregistrée (nouveau, ou cadencier trop court)
utilise une **consommation par défaut** (paramètre, 0 = désactivé) le temps
que l'historique s'accumule. Dès qu'une seule vente réelle apparaît dans le
cadencier, le calcul réel prend automatiquement le dessus — aucune
intervention nécessaire.

### Paramètres (tous configurables dans la barre latérale, aucun codé en dur)

| Paramètre | Défaut | Rôle |
|---|---|---|
| Stock min | 14 j de couverture | Seuil de recomplètement |
| Stock max | 30 j de couverture | Cible de la commande immédiate |
| Seuil d'action immédiate | 10 unités | La règle des 10 unités |
| Consommation par défaut | 0 (désactivé) | Repli si pas d'historique |
| Seuil de stock dormant | 180 j de couverture | Trésorerie immobilisée |
| Calcul de la consommation | Annuelle | Annuelle / trimestrielle (3 mois) / mensuelle (dernier mois) / lissée |

### Tableau produit

| Colonne | Contenu |
|---|---|
| Alerte | 🔴 Action requise · 🟡 Sous le min · 🟢 OK |
| Classe | A/B/C (Pareto, 80/95 % des ventes) |
| Code CIP · Nom du produit · Stock actuel | — |
| Consommation/mois · Tendance · Variabilité | Contexte de décision |
| Stock min (calculé) · Stock max (calculé) | La politique de stock |
| Cible réassort · Qté à commander · Motif | La décision, explicable |

Un onglet **stock dormant** (couverture > seuil) liste les produits dont la
trésorerie est immobilisée — envisager retour fournisseur ou arrêt de
réassort. Export dédié : bouton « Excel du stock en rotation » (2 feuilles).

## 🚨 Module 2 — Gestion des ruptures

### La règle métier (stricte, sans buffer)

Un produit en rupture GPNC **que vous vendez** apparaît uniquement si :

- il a une date de réappro : `stock (en jours) < jours jusqu'à la réappro`
  (strictement — ex. Titanoréine réappro 16 j / stock 18 j → n'apparaît pas) ;
- il n'a pas de date de réappro : `stock (en jours) < 30` (objectif 30 jours
  de couverture).

S'il apparaît : disponible chez UNIPHARMA → **onglet À commander** avec la
quantité à commander (`Cmd`) et l'urgence (🔴 stock épuisé ou ≤ 3 j ·
🟡 4-15 j · 🟢 > 15 j) ; en rupture aussi chez UNIPHARMA → **onglet Sans
solution** (anticiper l'information patient, contacter GPNC).

### Anticipation des ruptures à venir

- **🔭 Vigilance stock** : produits HORS liste de ruptures GPNC dont la
  couverture passe sous 7 jours (réglable) — la rupture en rayon arrive,
  commander chez GPNC avant qu'elle se produise.
- **⚠️ Écartés de justesse** : écartés par la règle stricte avec moins de
  3 jours de marge (réglable) — si la réappro glisse, rupture sèche.
- **Délai de livraison UNIPHARMA** (réglable, 0 par défaut) : ajouté à la
  couverture cible du calcul de `Cmd`.
- **Dates de réappro repoussées** : l'historique mémorise la date annoncée ;
  si elle glisse d'une analyse à l'autre, alerte « repoussée N fois ».
- **Ruptures longues** : ventes écrasées à 0 sur toute la période mais déjà
  signalé → « À vérifier » au lieu d'un écartement silencieux.

### Priorisation quotidienne (le tri du matin)

- **Score de priorité 0-100** : 50 pts de risque de rupture à 7 jours
  (probabilité, calculée sur la variabilité réelle des ventes) + 30 pts de
  poids dans les ventes (classe A/B/C) + 20 pts de fiabilité de la réappro.
  L'onglet « À commander » est trié par ce score.
- **Correction des faux zéros** (activée par défaut) : un mois à 0 vente
  encadré de mois actifs = rupture passée, pas absence de demande — corrige
  le biais de sous-commande sur les produits qui ont déjà manqué.
- **Politique ABC** (option) : couverture cible sans date différenciée —
  A 21 j (réassort fréquent) · B 30 j · C 14 j. La règle d'apparition
  stricte ne change jamais, seule la quantité est affectée.
- **Validation de commande dans l'outil** : cochez/décochez les lignes,
  ajustez les quantités — l'export Excel reprend vos choix. Une **fiche
  produit** (🔎) montre l'historique complet avant de valider.
- **Suivi quotidien** : chaque analyse (hors démo) est ajoutée à
  `historique_commandes.csv` ; l'écran affiche le comparatif avec la
  précédente (🆕 nouvelles ruptures / ✅ résolues).

### Fonctionnalités complémentaires

- **Commande en cours** (colonne facultative) : déduite du calcul, évite de
  recommander ce qui arrive déjà.
- **Péremption / DLUO** (colonne facultative) : alerte informative si moins
  de 90 jours — n'écarte pas le produit.
- **Matching CIP13 ↔ CIP7** : les exports mélangent les deux formats, le
  moteur les rapproche automatiquement (CIP en priorité, sinon libellé +
  fuzzy matching).

## Architecture

Trois modules Python, une seule règle : **la logique métier est strictement
séparée de l'interface**, et les deux modules fonctionnels ne s'importent
jamais l'un l'autre.

```
commun.py            Fonctions PURES partagées (parsing, chargement de
                      fichiers .xlsx/.xls/.csv/.pdf, calculs de consommation :
                      rotation, tendance, variabilité, classement ABC,
                      correction des ruptures passées). Ni ruptures
                      fournisseurs, ni politique de stock min/max.

stock_rotation.py     MODULE 1 — logique métier pure du stock en rotation.
  (import commun)     Lit uniquement le cadencier. Stock min/max, règle des
                       10 unités, stock dormant.

moteur_ruptures.py    MODULE 2 — logique métier pure des ruptures.
  (import commun)     Croise cadencier + GPNC + UNIPHARMA. Urgence,
                       vigilance, écartés de justesse, score de priorité,
                       historique, suivi quotidien.

app.py                 Interface Streamlit UNIQUEMENT — importe les 3
  (import les 3)        modules ci-dessus, affiche 2 onglets principaux.
```

`stock_rotation.py` et `moteur_ruptures.py` n'importent **jamais** l'un de
l'autre : la mutualisation passe exclusivement par `commun.py`. C'est ce qui
garantit qu'on peut faire évoluer la politique de stock sans risquer de
casser le calcul des ruptures, et inversement.

## Installation (une seule fois)

> 📄 Pour transmettre ce dossier à une tierce personne (collègue,
> remplaçant…) : [`INSTALLATION.txt`](INSTALLATION.txt) est un pense-bête
> minimal (texte brut, s'ouvre avec le Bloc-notes, aucun logiciel requis)
> qui explique exactement quoi faire, dans l'ordre. Version illustrée et
> plus détaillée : [`Guide-installation.pdf`](Guide-installation.pdf)
> (installation de Python, téléchargement, premier lancement, mise à jour,
> dépannage).

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
fermez la fenêtre noire (ou Ctrl+C dedans). Le **numéro de version** est
affiché dans le bandeau (ex. `v2.1`) : il permet de vérifier d'un coup
d'œil que la dernière version tourne bien.

## Mise à jour (Windows, en un clic)

Double-cliquez sur **`mettre-a-jour.bat`** : il télécharge la dernière
version depuis GitHub, remplace les fichiers programme et relance l'app —
**sans toucher à vos données** (`config.yaml` et `historique_commandes.csv`
sont préservés). Après la mise à jour, vérifiez le numéro de version dans le
bandeau. Si le numéro n'a pas changé, faites **Ctrl + Maj + R** dans le
navigateur (cache de page).

💡 **Pour découvrir l'outil sans fichiers** : cliquez sur
« 🧪 Essayer avec des données de démonstration » sur l'écran d'accueil —
l'analyse tourne sur un jeu fictif sans toucher à votre configuration.

## Utilisation (chaque jour)

1. **Déposez au moins le cadencier** (`.xlsx`, `.xls`, `.csv` ou `.pdf`) —
   il suffit pour la Gestion des stocks en rotation. Déposez aussi les
   ruptures GPNC et UNIPHARMA pour activer la Gestion des ruptures. Le
   **cadencier WinPharma** est reconnu et converti automatiquement, dans
   les deux formats : export **CSV** (bandeau, colonnes achats/ventes
   mensuelles, chargement instantané — à préférer) et **PDF** multi-pages
   (~1 minute pour 200 pages, puis mis en cache).
2. **Vérifiez les colonnes** détectées — corrigez si besoin, mémorisé dans
   `config.yaml`.
3. **Réglez chaque module** dans la barre latérale (deux sections
   distinctes : 📦 Stock en rotation · 🚨 Gestion des ruptures), choisissez
   la date d'analyse.
4. Cliquez **« Lancer l'analyse »** : les deux onglets principaux
   s'affichent avec leurs tuiles de synthèse.
5. Téléchargez l'Excel de chaque module (boutons dédiés).

⚠️ Les correspondances de produits **incertaines** (Module Ruptures,
libellés proches mais pas identiques) sont listées dans un panneau dédié :
vérifiez-les avant de commander.

## Structure du projet

```
pharmacie-ruptures/
├── app.py                  # interface (Streamlit) — n'appelle que les 3 modules
├── commun.py                # fonctions pures partagées (parsing, fichiers, stats)
├── stock_rotation.py        # Module 1 — stock min/max, pur, testable indépendamment
├── moteur_ruptures.py       # Module 2 — ruptures GPNC/UNIPHARMA, pur, testable
├── .streamlit/config.toml   # thème de l'interface (vert pharmacie)
├── config.yaml               # mapping + réglages mémorisés (créé au 1er lancement)
├── historique_commandes.csv  # historique des analyses de ruptures (créé à la 1re)
├── requirements.txt          # dépendances Python
├── lancer.bat                 # double-clic Windows
├── lancer.command              # double-clic Mac
├── README.md
└── tests/
    ├── test_commun.py        # fonctions partagées (parsing, fichiers, statistiques)
    ├── test_stock_rotation.py # Module 1 : stock min/max, règle des 10 unités
    └── test_moteur.py         # Module 2 : ruptures, anticipation, priorisation
```

## Tests

```
cd pharmacie-ruptures
python -m pytest tests/ -q
```

156 tests. Cas de référence Module Ruptures : Titanoréine (réappro 16 j,
stock 18 j → écartée), Ozempic 1 mg (stock 5, ~16,5/mois → ~9 j → 🟡 modéré,
Cmd 12), Aranesp 150 (stock 0, réappro 2 j → 🔴 urgent, Cmd ≥ 1). Cas de
référence Module Stock : règle des 10 unités testée sous tous ses angles
(seuil prioritaire sur le stock min, non-régression sur les produits
arrêtés, paramètres reconfigurables).
