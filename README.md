# 💊 Pilotage pharmacie — stock & ruptures

Application **locale** (elle tourne sur votre PC, hors-ligne) organisée en
**trois modules fonctionnels indépendants** :

- **📦 Gestion des stocks en rotation** (`stock_rotation.py`) — calcule un
  **stock min** et un **stock max** par produit à partir du seul cadencier,
  pour éviter la rupture (sous-stockage) et l'immobilisation de trésorerie
  (sur-stockage). Ne nécessite QUE le cadencier.
- **🚨 Gestion des ruptures** (`moteur_ruptures.py`) — croise le cadencier
  avec les listes de ruptures **GPNC** (`ruptgpnc_ia`, fournisseur
  principal) et **UNIPHARMA** (`ruptocdp_ia`, dépannage) pour produire le
  fichier Excel de commande quotidien.
- **🔒 Gestion du stock fermé** (`stock_ferme.py`) — inventaire tenu **à
  part** du stock officinal (armoire sécurisée, dotation d'urgence, trousse,
  réserve de garde), rempli **à la douchette** boîte par boîte, avec la date
  de péremption de **chaque** boîte. Ne lit aucun fichier : il a son propre
  inventaire et ses propres impressions (CSV / PDF).

Les deux premiers modules sont **strictement isolés l'un de l'autre** (aucun ne
connaît les structures de données de l'autre) mais **mutualisent** leurs
calculs de consommation (rotation, tendance, variabilité, classement ABC,
correction des ruptures passées) via `commun.py` — voir
[Architecture](#architecture) plus bas. Le troisième module, lui, ne partage
**rien** : il ne dépend d'aucun fichier déposé, et se choisit dans le
sélecteur d'**espace de travail** en haut de l'écran.

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

> Cette règle ne s'applique que si le **document de base n'a pas changé** :
> si le cadencier déposé a une structure différente (colonnes de ventes
> différentes, autre fenêtre de mois), la comparaison n'a plus de sens →
> toutes les lignes ressortent et une nouvelle référence est enregistrée.

**Document de base** (vue par défaut) : centré sur le stock min/max —
Alerte, Code CIP, Nom, Stock min, Stock max, Stock min conseillé. Le
**Stock actuel** et la **Qté à commander** s'affichent via la case
« ＋ Colonnes d'analyse ».

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

## 🔒 Module 3 — Gestion du stock fermé

Inventaire tenu **à part** du stock officinal courant : armoire de
stupéfiants, dotation d'urgence, trousse, réserve de garde, rétrocessions.
Il n'a **aucun rapport** avec le cadencier : on y entre les boîtes une par
une, et on en sort une liste de contrôle imprimable.

### La péremption appartient à la boîte, pas au produit

C'est ce qui justifie un module dédié plutôt qu'une colonne de plus dans le
Module 1. Deux boîtes du même médicament peuvent expirer à six mois d'écart :
l'unité d'enregistrement est donc le **lot**, identifié par
`(code CIP, date de péremption, n° de lot)`.

- scanner deux fois la **même** boîte incrémente la ligne existante ;
- scanner une boîte de **péremption différente** crée une **nouvelle** ligne.

L'inventaire est toujours trié par péremption la plus proche : c'est l'ordre
dans lequel on veut traiter les boîtes, et celui de la liste imprimée.

**La péremption s'affiche en MOIS/ANNÉE** (`03/2028`) : c'est ce qui est
imprimé sur les cartons, et le jour prenait une place que la colonne n'a
pas. La date **complète reste enregistrée** — seul l'affichage est
raccourci — et la colonne « Jours restants », juste à côté, donne le compte
exact à la journée près. La liste **imprimée**, elle, garde la date
complète : sur le papier il n'y a pas de « jours restants » pour rattraper
un jour masqué.

**Tout le contenu est centré dans les cases.** Streamlit colle les nombres
au bord droit de leur colonne : sur une colonne large, le « 1 » des boîtes
se retrouvait à des centimètres de son en-tête et l'œil ne savait plus à
quelle colonne il appartenait. Le tableau modifiable et la vue filtrée
partagent la même déclaration de colonnes — deux réglages séparés
finiraient par diverger.

**Pas de colonne « Dosage ».** Il fait partie de la dénomination
(« DOLIPRANE 1000 mg, comprimé ») ; une colonne pour le répéter poussait la
péremption — la seule qui compte vraiment ici — hors de l'écran. Un dosage
saisi séparément rejoint le nom **dès l'enregistrement**, et les
inventaires écrits avant sont repliés à la relecture : l'identité d'un lot
sans code CIP repose sur son nom, l'afficher sous une forme et le stocker
sous une autre ferait échouer sa sortie en silence.

**Les barres obliques sont facultatives.** Une date par boîte, deux frappes
de `/` par date : sur un inventaire complet, cela fait des centaines de
frappes pour rien. Les chiffres seuls suffisent — c'est d'ailleurs ce qui
est imprimé sur les cartons.

| Ce qu'on tape | Ce qui est retenu |
|---|---|
| `082027` · `0827` · `08/2027` | 31 août 2027 (fin de mois) |
| `31082027` · `310827` · `31/08/2027` | 31 août 2027 |

Six chiffres sont ambigus — `082027` est un mois suivi d'une année,
`310827` un jour, un mois et une année courte. On tranche par le sens : un
mois vaut au plus 12, une année tient entre 1900 et 2199. Ce qui ne fait
pas une date (un code CIP tapé dans la mauvaise case, par exemple) est
refusé plutôt que deviné.

L'année doit rester **entre 1990 et 2099**. Au-delà, c'est une faute de
frappe : une boîte qui périme en l'an 9999 s'afficherait « 🟢 OK » pour
toujours, tout en bas de la liste, invisible. Mieux vaut faire retaper la
date. Les bornes sont **absolues** et non relatives au jour — la lecture
d'un inventaire ne doit pas dépendre de la date à laquelle on l'ouvre.

| Statut | Seuil | Signification |
|---|---|---|
| ⛔ Périmé | date dépassée | à retirer du stock |
| 🔴 < 1 mois | ≤ 30 j | la boîte ne passera pas le mois — action immédiate |
| 🟠 < 3 mois | ≤ 90 j | retrait ou remplacement à préparer |
| 🟡 < 6 mois | ≤ 180 j | à écouler en priorité |
| 🟢 OK | > 180 j | plus de six mois de marge |
| ⚪ Sans date | — | péremption non renseignée |

### Entrée ou sortie de stock

Un sélecteur **Entrée / Sortie** commande le champ de scan.

- **Entrée** : la boîte scannée rejoint l'inventaire (voir ci-dessous) ;
- **Sortie** : chaque scan retire **une boîte**. Le Data Matrix désigne la
  boîte exacte (CIP + péremption + lot) ; un code-barres linéaire ne donne
  que le produit, et c'est alors le lot qui **périme le plus tôt** qui sort
  — règle **FEFO** de l'officine. Si le lot scanné n'est pas à l'inventaire,
  l'outil sort la boîte la plus proche de la péremption **en le signalant** :
  sortir un lot pour un autre en silence ruinerait la traçabilité.

### Saisie : douchette ou clavier

Trois entrées possibles, dans l'ordre de rapidité :

1. **Data Matrix GS1** (boîtes récentes) — le code carré donne d'un seul
   scan le **code CIP**, la **date de péremption** et le **n° de lot**. Si
   le produit a déjà été nommé une fois, la boîte entre au stock **sans un
   clic** ;
2. **code-barres linéaire CIP13** (boîtes anciennes) ou **CIP7** — le code
   ne donne que l'identité du produit : la péremption reste à saisir ;
3. **saisie au clavier** — nom du médicament, dosage, CIP : utile pour les
   produits sans code-barres exploitable (préparations, dispositifs).

Le champ de scan se vide tout seul après chaque lecture, pour enchaîner les
boîtes sans intervention. Détails techniques pris en charge :

- **préfixes de symbologie** ajoutés par certaines douchettes (`]d2`, `]C1`,
  `]e0`, `]Q3`) ;
- **séparateur FNC1 absent** — plusieurs douchettes ne l'émettent pas. La
  lecture retenue est alors celle qui n'abandonne **aucun caractère
  inexpliqué**, et non la première coupe plausible : sans cette précaution,
  un lot `LOT42` suivi d'une péremption se lit `LOT4`, et un n° de série se
  retrouve amputé de son dernier chiffre ;
- **convention GS1 `JJ = 00`** (fin de mois) et **jour hors calendrier**
  (`31/02`, vu sur des codes mal générés) ramené au dernier jour du mois
  plutôt que rejeté — perdre la péremption d'une boîte coûterait plus cher
  que ce jour d'écart ;
- **code recopié à la main** avec espaces, points ou tirets
  (`3400 912 345 678`), sans confondre un libellé chiffré avec un code.

Si une fiche est ouverte et qu'une **autre** boîte est scannée avant de la
valider, l'abandon est signalé — pas silencieux.

### Comptage en boîtes ET à l'unité

Chaque lot porte trois quantités :

- **Boîtes** — le comptage principal ;
- **Unités par boîte** — le conditionnement (comprimés, ampoules…) ;
- **Unités en vrac** — ce qui reste d'une boîte entamée.

Le **total unités** vaut `boîtes × unités par boîte + vrac`. Sans
conditionnement renseigné, les boîtes ne sont **pas** converties : l'outil
préfère afficher « conditionnement non renseigné » plutôt qu'inventer un
total.

### Le nom du médicament ne vient PAS du code-barres

Aucun identifiant GS1 ne transporte le libellé d'un produit. Le Data Matrix
d'une boîte contient exactement quatre choses : le **GTIN** (qui porte le
code CIP), la **péremption**, le **n° de lot** et le **n° de série**. Un
encadré « 🔎 Que contient exactement le code scanné ? » le montre champ par
champ sur la boîte que l'on vient de scanner.

Le nom vient donc d'une table « code CIP → libellé ». Trois façons de la
remplir, de la plus automatique à la plus manuelle :

1. **la base publique des médicaments** (`base_medicaments.py`) — un bouton
   télécharge les fichiers officiels de l'ANSM / ministère de la Santé
   (`CIS_bdpm.txt` et `CIS_CIP_bdpm.txt`), les recoupe sur le code CIS et en
   tire ~42 000 correspondances (CIP13 **et** CIP7) et ~20 700
   présentations. Le nom s'affiche alors **au moment du scan**, sans rien
   saisir — et elle sert aussi **dans l'autre sens** : taper un nom propose
   les présentations correspondantes (voir « Présélection par le nom »).
   La table est conservée sur le poste : le téléchargement est explicite,
   et l'identification fonctionne ensuite **hors ligne** ;
2. **en bloc depuis votre catalogue** — l'encadré « 📇 Pré-remplir les noms
   depuis un fichier » avale un cadencier (`.xlsx`, `.csv`, `.pdf`) et n'en
   retient que les couples code + libellé. Utile pour ce que la base
   publique ne couvre pas ;
3. **à la volée** — le nom est demandé au premier scan d'un produit, une
   seule fois ; il est ensuite reconnu automatiquement.

Un nom trouvé dans la base publique est **recopié dans le répertoire de la
pharmacie** : il devient modifiable, et l'identification ne dépend plus de
la base ensuite.

> Le CIP13 français est construit `34009` + CIP7 + clé de contrôle
> (vérifié sur la base officielle) : une boîte lue en CIP7 retrouve donc sa
> fiche, et réciproquement.

> Le moteur ne reçoit que des couples déjà extraits : la lecture du fichier
> appartient à l'interface, ce qui laisse `stock_ferme.py` indépendant de
> tout format de catalogue.

### Mémoire

Deux fichiers, écrits à chaque modification et relus à l'ouverture :

- `stock_ferme.csv` — l'inventaire lui-même ;
- `stock_ferme_produits.csv` — le **répertoire** des produits déjà
  identifiés (CIP → nom, dosage, conditionnement). C'est lui qui permet
  qu'un produit nommé **une fois** n'ait plus jamais à l'être : au scan
  suivant, la douchette suffit.

L'inventaire se corrige directement dans le tableau (quantité, date, lot) et
une ligne de boîte sortie se supprime par la touche `Suppr`. Une **recherche**
(nom, dosage, code CIP ou n° de lot) et un filtre **« lots à traiter »**
(périmés et moins d'un mois) permettent de retrouver une boîte sans faire
défiler l'inventaire.

**Saisie assistée** — un code illisible, une boîte reconditionnée, et il
n'y a plus qu'à **taper les premières lettres** dans le menu sous le champ
de scan : les boîtes correspondantes s'affichent **aussitôt**, sans rien
valider. On précise le dosage pour affiner, on clique — la fiche est
remplie.

```
doliprane 1000
   DOLIPRANE 1000 mg, gélule — boîte de 8
   DOLIPRANE 1000 mg, comprimé — boîte de 8
   DOLIPRANE 1000 mg, comprimé — boîte de 100
   DOLIPRANE 1000 mg, comprimé effervescent sécable — boîte de 8
```

Une entrée par **boîte**, pas par médicament : le nom, le dosage et le
conditionnement tiennent sur la même ligne, donc **un seul geste** suffit —
il n'y a pas de second écran à confirmer. Un clic renseigne la
dénomination, le **code CIP** et les **unités par boîte** ; ne reste que la
péremption, la seule chose que la base ne peut pas savoir.

Le libellé dit `boîte de 8` plutôt que « plaquette(s) thermoformée(s)
PVC-aluminium de 8 comprimé(s) » : la matière de l'emballage n'apprend rien
et allonge une liste qui se parcourt à l'œil. Deux boîtes qui se liraient à
l'identique sont fondues en une — personne ne saurait les distinguer, et le
choix serait un tirage au sort.

Le filtrage se fait dans le **navigateur**, pas sur le serveur : les
~19 600 boîtes lui sont envoyées une fois, puis chaque frappe filtre
localement. Mesuré sur la base officielle complète : « doliprane » puis
« 1000 » aboutissent en **3,6 s** puis **0,8 s**, et une interaction
ordinaire de l'écran reste à **0,19 s**. Un champ texte ordinaire ne peut
pas le faire — Streamlit n'y réagit qu'à la validation, et l'écran semble
alors ne rien faire.

Le champ de scan accepte aussi un nom tapé au clavier, suivi d'**Entrée**
(ou du bouton « 🔎 Chercher ») : si une seule boîte porte ce nom, la fiche
se remplit directement ; sinon on est renvoyé vers la liste, où les dosages
se départagent.

Cette recherche par nom accepte plusieurs mots dans le désordre (« 1000 doliprane »),
ignore accents et casse, et fait remonter d'abord les noms qui
**commencent** par le terme tapé.

Deux points la rendent utilisable au comptoir plutôt que théoriquement
correcte :

- **les doses sont ramenées au milligramme des deux côtés.** La base
  officielle écrit « DOLIPRANE **1000 mg** » ; à l'officine on dit
  « Doliprane **1 g** ». `1 g`, `1g`, `1 gramme`, `1000 mg`, `1000mg` et
  `1000 milligrammes` désignent donc la même chose — de même que
  `500 microgrammes` et `0,5 mg` ;
- **un mot de trop ne vide pas la liste.** « Doliprane 1 g boîte bleue »
  n'existe dans aucune dénomination officielle : les mots sont abandonnés
  par la fin jusqu'à trouver, et l'écran indique ce qui a réellement servi.

Et quand il n'y a vraiment rien, l'écran le **dit** — en distinguant « ce
nom est introuvable » de « la base n'est pas installée ». Une liste vide
sans un mot ressemble à une application qui ne réagit pas. Le nombre d'unités n'est déduit que
lorsqu'il est certain : forme dénombrable (comprimés, gélules, sachets…),
un seul nombre possible, multiplicateur de tête pris en compte
(« 3 piluliers de 30 comprimés » = 90). Dans le doute, la case reste à 0 —
une quantité fausse sur un stock fermé ne se remarque pas.

**Sortie manuelle** — la douchette ne lit pas tout : étiquette abîmée,
boîte reconditionnée, produit sans code-barres. En mode **Sortie**, le
bouton **« ⌨️ Sortie manuelle »** ouvre la liste des boîtes en stock
(statut, nom, dosage, péremption, n° de lot, nombre de boîtes) : on désigne
celle qui sort et on choisit combien. Le maximum proposé est le stock du
lot — promettre davantage serait promettre une sortie que l'inventaire ne
peut pas honorer.

Et si l'inventaire est **vide** alors qu'on est en mode Sortie, l'écran le
dit et propose un bouton pour repasser en Entrée : chaque scan répondrait
sinon « ce produit n'est pas à l'inventaire », sans issue visible.

**Classement** — deux ordres, pour deux gestes différents :

| Ordre | À quelle question il répond |
|---|---|
| **Péremption (au plus proche)** — *par défaut* | « Que dois-je retirer ? » Ce qui périme demain arrive en tête, les lots sans date en queue |
| **Nom (A → Z)** | « Où est ce produit dans ma liste ? » On parcourt l'inventaire produit par produit devant l'armoire |

Le classement alphabétique ignore **accents et casse** — sans quoi
« ÉLAVIL » se rangerait après « ZOLPIDEM ». À nom égal, la boîte qui périme
la première reste en tête : c'est celle qu'on prend.

Le choix **suit jusqu'au CSV et au PDF** — une liste papier qui contredit
l'écran se relit en entier pour rien — et le PDF **annonce son classement**
dans son en-tête.

### Impression

La liste de stock s'exporte en **CSV** (`;` + BOM : Excel l'ouvre sans
réglage) et en **PDF**, en totalité ou limitée aux **lots à retirer**
(périmés et moins d'un mois) — c'est le besoin le plus fréquent (paysage, en-tête répété à chaque page, lignes
teintées selon l'urgence). Les deux comportent, pour chaque lot : **nom du
médicament, dosage, code CIP, nombre de boîtes, nombre d'unités et date de
péremption**, plus le n° de lot. Dans le PDF, le statut est écrit en toutes
lettres (les polices PDF standard n'ont pas de glyphe d'émoji) : la liste
reste lisible imprimée en noir et blanc.

## Architecture

Une seule règle : **la logique métier est strictement séparée de
l'interface**, et les modules fonctionnels ne s'importent jamais l'un
l'autre.

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

ui_commun.py          Règles PURES de l'interface (filtrage, empreintes,
  (aucun streamlit)    historique) — sorties d'app.py pour être testables.

base_medicaments.py   Identification d'un CIP via la base publique des
  (aucun autre module)  médicaments. Ne sait répondre qu'à « quel
                        médicament porte ce code ? ».

stock_ferme.py        MODULE 3 — logique métier pure du stock fermé.
  (n'importe RIEN     Lecture des codes scannés (Data Matrix GS1, CIP13,
   du projet)          CIP7), inventaire par lot, péremptions, exports
                       CSV et PDF. Ne lit aucun fichier déposé.

ui_stock_ferme.py     Interface Streamlit du MODULE 3, isolée dans son
  (import stock_ferme) propre fichier — reçoit d'app.py ses seules
                       fonctions d'habillage, en paramètres.

app.py                 Interface Streamlit UNIQUEMENT — importe les modules
  (import les 4)        ci-dessus, propose le sélecteur d'espace de travail
                        puis les 2 onglets du parcours « cadencier ».
```

`stock_rotation.py` et `moteur_ruptures.py` n'importent **jamais** l'un de
l'autre : la mutualisation passe exclusivement par `commun.py`.
`stock_ferme.py`, lui, n'importe aucun module du projet — un test le
vérifie. C'est ce qui
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

- **Windows** : double-cliquez sur l'icône 💊 **Pharmacie** du Bureau. Elle
  est créée automatiquement au premier lancement (voir ci-dessous) ; sinon,
  double-cliquez sur `lancer.bat` dans le dossier.
- **Mac** : double-cliquez sur `lancer.command` (la première fois : clic droit
  → Ouvrir, pour passer l'avertissement de sécurité).
- **À la main** : `streamlit run app.py`

### 💊 L'icône du Bureau

Au **tout premier** lancement, `lancer.bat` pose sur le Bureau une icône
**Pharmacie** — la même gélule que dans l'onglet du navigateur, sur le
turquoise de l'application. Un double-clic dessus ouvre l'utilitaire : plus
besoin de retrouver le dossier.

Le visuel est **monochrome** : un seul motif blanc sur l'aplat turquoise,
sans contour ni seconde couleur, et du vide autour. Le relief vient d'une
ombre portée très douce, pas d'un trait — un liseré sombre sur une forme
blanche fait aussitôt « autocollant ».

- **L'icône manque ?** L'application le voit et propose un bouton
  **« 📌 Créer l'icône maintenant »** en haut de sa barre latérale. Il
  disparaît de lui-même une fois l'icône posée — une proposition qui reste
  affichée après avoir été suivie n'est plus une aide. Rien à chercher dans
  le dossier : Windows masque l'extension `.bat`, et certains postes en
  interdisent l'exécution.
- Sinon, double-cliquez sur **`creer-raccourci.bat`**, elle revient.
- Elle n'est **pas** recréée toute seule à chaque démarrage : un témoin
  local (`.raccourci-bureau`) mémorise qu'elle a déjà été posée, pour
  qu'une suppression volontaire soit respectée.
- Le témoin retient la **version**, pas un simple « déjà fait » : après un
  changement de visuel, l'icône est reposée une fois. Sans cela, Windows
  continuerait d'afficher l'ancien dessin, qu'il garde en cache.
- Le Bureau est résolu par Windows lui-même, ce qui couvre les postes où il
  est redirigé (OneDrive, profil itinérant). Si PowerShell est interdit par
  la stratégie du poste, un raccourci Internet (`.url`, du texte brut)
  prend le relais — et si tout échoue, le script le **dit** plutôt que de
  laisser chercher.

`lancer.bat` **et** `mettre-a-jour.bat` posent l'icône. Les deux, parce que
`mettre-a-jour.bat` relance l'application lui-même : qui met à jour depuis
ce script ne passe jamais par `lancer.bat`, et n'aurait jamais vu son
icône apparaître.

> ⚠️ `mettre-a-jour.bat` n'est **jamais remplacé** par une mise à jour (il
> est en cours d'exécution pendant la copie des fichiers — voir
> [Mise à jour automatique](#mise-à-jour-automatique)). Les postes déjà
> installés ne reçoivent donc pas cet appel : sur ceux-là, un double-clic
> sur `creer-raccourci.bat` suffit, une seule fois.

Le fichier `pharmacie.ico` est **livré tout fait** dans le dépôt : le poste
de la pharmacie n'a besoin d'aucune bibliothèque graphique. Il contient
sept tailles (16 → 256 px) pour rester net partout, de la barre des tâches
aux grandes icônes de l'explorateur. Pour le régénérer après une retouche
du visuel : `python outils/creer_icone.py` (nécessite Pillow ; un test
vérifie que le fichier livré et le générateur ne divergent pas).

Le navigateur s'ouvre sur `http://localhost:8501`. Pour arrêter l'app :
fermez la fenêtre noire (ou Ctrl+C dedans). Le **numéro de version** est
affiché dans le bandeau (ex. `v3.2`) : il permet de vérifier d'un coup
d'œil que la dernière version tourne bien.

### Si l'application ne s'ouvre pas

**La fenêtre noire affiche `Email:` et rien ne se passe.** C'est le
questionnaire de bienvenue de Streamlit : il attend une réponse et bloque le
démarrage. Appuyez sur **Entrée** (sans rien taper) et l'application
s'ouvre. Cela n'arrive plus depuis la version 3.2 : le réglage
`server.showEmailPrompt = false` de `.streamlit/config.toml` supprime cette
question sur tous les postes.

**« Python n'est pas installé ».** Réinstallez Python depuis python.org en
cochant bien **« Add Python to PATH »**, puis rouvrez une nouvelle fenêtre
avant de relancer.

**Double-cliquer `lancer.bat` affiche « Port 8501 is not available ».**
L'application était déjà ouverte. Depuis la version 3.6, le lanceur le
détecte et **ouvre simplement le navigateur** sur la session en cours au
lieu d'échouer.

**La mise à jour semble n'avoir rien changé.** C'était presque toujours une
**ancienne version restée ouverte** : elle occupait l'adresse
`localhost:8501`, la nouvelle démarrait alors sur `localhost:8502`, et
l'onglet du navigateur continuait d'afficher l'ancienne.

Trois garde-fous rendent désormais ce scénario impossible à subir :

1. `mettre-a-jour.bat` **ferme lui-même** la version qui tourne avant de
   relancer — plus rien à penser ;
2. l'application démarre toujours sur **8501** : si le port reste pris,
   elle le dit au lieu de basculer en silence ;
3. le **bandeau signale une version périmée** (« ⬆️ v3.5 disponible »), et
   `mettre-a-jour.bat` affiche « Version installee : vX.Y » à la fin. Les
   deux numéros doivent concorder.

> La vérification de version lit un fichier public du dépôt et **ne
> transmet aucune donnée**. Poste hors ligne : rien ne s'affiche, rien ne
> bloque.

## Mise à jour automatique

L'utilitaire se met à jour **tout seul**, à deux moments :

- **à chaque lancement** (`lancer.bat` / `lancer.command`) — c'est le seul
  instant où remplacer des fichiers est sans danger, l'application n'étant
  pas encore démarrée ;
- **à l'ouverture de session Windows**, si vous activez la tâche planifiée :
  double-cliquez **`maj-auto-activer.bat`** une fois. Aucune fenêtre ne
  s'affiche, la vérification est discrète.
  (`maj-auto-desactiver.bat` fait l'inverse.)

Trois règles de prudence, appliquées par `maj_auto.py` :

| Situation | Ce qui se passe |
|---|---|
| L'application est **ouverte** | rien n'est touché — remplacer un module sous une session en cours la casserait |
| Le poste est **hors ligne** | rien n'est tenté, aucun message |
| La version publiée est **identique ou plus ancienne** | aucun téléchargement (seul `app.py` est lu, quelques Ko) |

Vos données — inventaire du stock fermé, historique, réglages, base des
médicaments — ne sont **jamais** écrasées. Le déroulement est consigné dans
`maj_auto.log`.

> Une mise à jour automatique installe du code sans relecture préalable. Si
> vous préférez garder la main, désactivez la tâche planifiée : le bandeau
> continuera de signaler les nouvelles versions, et `mettre-a-jour.bat`
> restera disponible à la demande.

## Mise à jour manuelle (Windows, en un clic)

Double-cliquez sur **`mettre-a-jour.bat`** : il télécharge la dernière
version depuis GitHub, remplace les fichiers programme et relance l'app —
**sans toucher à vos données** (`config.yaml`, `historique_commandes.csv`,
l'état du stock min/max et l'inventaire du stock fermé sont préservés). Après la mise à jour, vérifiez le numéro de version dans le
bandeau. Si le numéro n'a pas changé, faites **Ctrl + Maj + R** dans le
navigateur (cache de page).

💡 **Pour découvrir l'outil sans fichiers** : cliquez sur
« 🧪 Essayer avec des données de démonstration » sur l'écran d'accueil —
l'analyse tourne sur un jeu fictif sans toucher à votre configuration.

## Utilisation (chaque jour)

Le sélecteur d'**espace de travail**, en haut de l'écran, choisit entre le
parcours « cadencier » (Modules 1 et 2, décrit ci-dessous) et le **stock
fermé** (Module 3), qui, lui, ne demande aucun fichier : on y scanne, on
imprime.

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
├── app.py                  # interface (Streamlit) — n'appelle que les modules
├── commun.py                # fonctions pures partagées (parsing, fichiers, stats)
├── stock_rotation.py        # Module 1 — stock min/max, pur, testable indépendamment
├── moteur_ruptures.py       # Module 2 — ruptures GPNC/UNIPHARMA, pur, testable
├── stock_ferme.py           # Module 3 — stock fermé (scan, lots, péremptions)
├── base_medicaments.py      # identification d'un CIP via la base publique
├── ui_commun.py             # règles pures de l'interface (sans Streamlit)
├── ui_stock_ferme.py        # interface du Module 3 (Streamlit)
├── .streamlit/config.toml   # thème de l'interface (vert pharmacie)
├── config.yaml               # mapping + réglages mémorisés (créé au 1er lancement)
├── historique_commandes.csv  # historique des analyses de ruptures (créé à la 1re)
├── stock_ferme.csv           # inventaire du stock fermé (créé au 1er scan)
├── base_medicaments.csv      # base publique téléchargée (créée à la demande)
├── stock_ferme_produits.csv  # produits mémorisés du stock fermé (CIP → nom)
├── requirements.txt          # dépendances Python
├── maj_auto.py              # mise à jour automatique (testable, sans Streamlit)
├── maj-auto-activer.bat     # active la vérification au démarrage de Windows
├── maj-auto-desactiver.bat  # la désactive
├── lancer.bat                 # double-clic Windows
├── lancer.command              # double-clic Mac
├── creer-raccourci.bat       # pose l'icône 💊 « Pharmacie » sur le Bureau
├── raccourci.py             # la même pose, appelable depuis l'application
├── pharmacie.ico            # icône du raccourci (16 → 256 px)
├── pharmacie.png            # même visuel en 1024 px (Mac, documentation)
├── outils/creer_icone.py    # régénère l'icône (outil de développement)
├── README.md
└── tests/
    ├── test_commun.py        # fonctions partagées (parsing, fichiers, statistiques)
    ├── test_stock_rotation.py # Module 1 : stock min/max, règle des 10 unités
    ├── test_moteur.py         # Module 2 : ruptures, anticipation, priorisation
    ├── test_stock_ferme.py    # Module 3 : Data Matrix, lots, péremptions, exports
    ├── test_base_medicaments.py # identification par CIP (base publique)
    ├── test_maj_auto.py       # mise à jour auto : données préservées, app ouverte
    ├── test_ui_commun.py      # règles d'affichage : filtres, exports, historique
    ├── test_invariants.py     # propriétés vraies quelles que soient les données
    ├── test_icone.py          # icône du Bureau : tailles, script de raccourci
    ├── test_raccourci.py      # pose du raccourci : Bureau redirigé, replis
    └── test_interface.py      # fumée : l'application démarre et répond
```

Le test de fumée lance un vrai Streamlit et parcourt les deux espaces dans
un navigateur ; il s'ignore tout seul si Playwright n'est pas installé.

## Où l'application range vos données

`config.yaml`, `historique_commandes.csv`, l'état du stock min/max et
l'inventaire du stock fermé sont écrits **à côté du programme**, pas dans le
dossier depuis lequel on le lance : copier le dossier suffit à emporter
l'installation complète.

La variable d'environnement `PHARMACIE_DONNEES` permet de les ranger
ailleurs (dossier partagé, sauvegarde automatique) :

```
set PHARMACIE_DONNEES=D:\pharmacie\donnees   (Windows)
export PHARMACIE_DONNEES=~/pharmacie/donnees   (Mac/Linux)
```

C'est aussi ce qui permet à la suite de tests de tourner **sans jamais
toucher** à vos vraies données.

## Tests

```
cd pharmacie-ruptures
python -m pytest tests/ -q
```

450 tests. Cas de référence Module Ruptures : Titanoréine (réappro 16 j,
stock 18 j → écartée), Ozempic 1 mg (stock 5, ~16,5/mois → ~9 j → 🟡 modéré,
Cmd 12), Aranesp 150 (stock 0, réappro 2 j → 🔴 urgent, Cmd ≥ 1). Cas de
référence Module Stock : règle des 10 unités testée sous tous ses angles
(seuil prioritaire sur le stock min, non-régression sur les produits
arrêtés, paramètres reconfigurables). Cas de référence Module Stock fermé :
Data Matrix sans séparateur FNC1 (`…10LOT4217271130` → lot `LOT42`, et non
`LOT4` ; `…101234AB21987654321` → lot `1234AB` **et** série `987654321`),
deux péremptions du même CIP donnant deux lignes, PDF lisible sans émoji et
repliant les libellés trop longs.
