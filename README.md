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
- **🔒 Gestion du stock interne** (`stock_ferme.py`) — inventaire tenu **à
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

## 🔒 Module 3 — Gestion du stock interne

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

### L'écran de saisie : deux lignes, rien de plus

C'est la demande de la pharmacie, mot pour mot : *« une ligne où on bipe et
où on peut noter le nom du médicament, la ligne d'en dessous on clique sur
entrée ou sortie, rien de plus »*. L'outil doit être utilisable **par
quelqu'un qui ne connaît rien à l'informatique**.

```
╔═════════════════════════════════════════════════════════════════════╗
║ ┌─────────────────────────────────────────────────────────────────┐ ║
║ │  🔦 Douchez la boîte — ou tapez les premières lettres          ⌄ │ ║  ← panneau turquoise
║ └─────────────────────────────────────────────────────────────────┘ ║
╚═════════════════════════════════════════════════════════════════════╝
┌──────────────────────────────┬──────────────────────────────────────┐
│         ➕ Entrée            │            ➖ Sortie                  │
└──────────────────────────────┴──────────────────────────────────────┘
   ⌨️ Le code ne se lit pas ? Sortir à l'unité ?          ▸ (replié)
```

### Une seule barre, qui fait les deux

Il y en a eu deux, par accumulation : un champ de scan, puis une liste
déroulante ajoutée en dessous pour chercher par le nom. **Deux barres
superposées posent une question à chaque geste** — *laquelle ?* — et c'est
une question de trop devant un comptoir.

Elles n'en font plus qu'une. C'est une liste déroulante qui **accepte aussi
une valeur inédite**, et cela suffit à couvrir les deux gestes :

| Ce qu'on fait | Ce qui se passe |
|---|---|
| **on tape des lettres** | la liste se réduit à la frappe ; chaque ligne porte le nom, le dosage **et** la taille de la boîte, et un clic remplit toute la fiche |
| **on douche une boîte** | le code ne ressemble à aucune ligne : la liste propose de l'accepter tel quel, et la douchette valide déjà par sa touche **Entrée** |

> **Le risque de cette fusion porte sur le geste principal**, et il est
> testé comme tel : le champ est devenu une liste de 19 600 médicaments, et
> une douchette n'y choisit rien. Un test navigateur tape un vrai Data
> Matrix — séparateur FNC1 compris, à la vitesse d'une douchette — et
> vérifie que la boîte entre au stock sans fiche à compléter. Si la liste
> refusait une valeur inédite, la pharmacie ne pourrait plus scanner du
> tout.

Un bouton **« 🔎 Chercher »** avait accompagné le champ, avant cela. Il a
été retiré pour la même raison : il ne faisait rien de plus que la touche
**Entrée**.

> Streamlit écrit **« Add: … »** au-dessus de la liste quand ce qu'on tape
> n'y figure pas. C'est le seul mot d'anglais de l'écran, il vient du
> composant et ne se traduit pas. Une douchette ne le lit pas ; c'est ce
> qu'elle valide.

**La zone où l'on douche repose sur un panneau turquoise**, et le champ y
est **blanc au milieu** — c'est le contraste entre les deux qui se voit de
loin. Un premier essai s'était contenté de teinter le champ lui-même d'un
turquoise très pâle : à l'écran de l'officine, il passait pour du blanc.
Le champ est aussi **nettement plus haut**, et son texte plus grand : un
code scanné se relit d'un coup d'œil, sans se pencher. Et il **s'allume
quand il a le curseur** : une douchette n'écrit que dans le champ actif, et
un bip perdu parce que le curseur était ailleurs ne laisse aucune trace à
l'écran.

Le champ est **au-dessus** du sens : on bipe d'abord, on regarde le sens
ensuite. Il reste choisi d'un scan à l'autre — on le règle une fois le
matin.

Ce que cela remplace : l'écran portait **deux dispositions différentes**
selon le mode — trois boutons en Entrée, deux encadrés côte à côte en
Sortie — et il fallait le relire à chaque bascule pour retrouver le champ.

**La recherche par nom demande la base publique des médicaments.** Sans
elle, le champ reste une saisie libre — la douchette continue de
fonctionner — et **le bouton qui l'installe s'affiche juste en dessous** :

```
🔎 Taper un nom demande la base publique des médicaments, qui n'est pas
   encore installée sur ce poste…
┌─────────────────────────────────────────────────────────────────────┐
│              ⬇️  Installer la base des médicaments                   │
└─────────────────────────────────────────────────────────────────────┘
```

> Le bouton **n'existait que dans la colonne de gauche**, repliée par
> défaut. L'officine lisait donc *« installez-la »* sans jamais trouver
> où, et la recherche par nom restait muette — signalée comme une panne.
> Le remède appartient à l'endroit où la panne se voit. Le message
> renvoyait d'ailleurs vers « l'encadré ci-dessous », parti dans la barre
> latérale depuis : une consigne qui désigne un endroit vide est pire que
> pas de consigne.

Ne reste **replié** que ce qui est vraiment exceptionnel : la saisie
manuelle d'une boîte absente du catalogue national, et la sortie à l'unité.
Replié ne veut pas dire caché : **le titre nomme les deux cas**.

La **base publique des médicaments** et l'**import du répertoire** ont
quitté le flux principal pour la **colonne de gauche**, celle qui se replie.
Ce sont des réglages qu'on fait une fois, pas des gestes de comptoir ; au
milieu de l'écran, entre le scan et l'inventaire, ils occupaient la place de
ce qu'on regarde tous les jours.

### Entrée ou sortie de stock

Le sélecteur **Entrée / Sortie**, sous le champ, commande le scan.

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

Le champ de scan accepte aussi un nom tapé au clavier, suivi d'**Entrée** :
si une seule boîte porte ce nom, la fiche se remplit directement ; sinon on
est renvoyé vers la liste, où les dosages se départagent.

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
une quantité fausse sur un stock interne ne se remarque pas.

**Deux façons de sortir du stock** :

| | Ce qu'il fait | Quand s'en servir |
|---|---|---|
| **🔦 Le bip de la boîte** — le champ | chaque bip retire **une boîte entière** | le geste courant : la boîte part telle quelle |
| **⌨️ Sortie manuelle** — dans le dépliant | on désigne le lot dans une liste, puis le nombre | étiquette illisible, ou sortie **à l'unité** |

**Sortie manuelle** — la douchette ne lit pas tout : étiquette abîmée,
boîte reconditionnée, produit sans code-barres. Le bouton ouvre la liste
des boîtes en stock (statut, nom, dosage, péremption, n° de lot, boîtes et
unités en vrac) : on désigne celle qui sort et on choisit combien. Le
maximum proposé est le stock du lot — promettre davantage serait promettre
une sortie que l'inventaire ne peut pas honorer.

**Sortie à l'unité** — une douchette lit une boîte, jamais dix comprimés.
Le panneau de sortie manuelle propose donc **Boîtes entières** ou **Unités
(comprimés)**. À l'unité, une boîte **s'entame** : sortir 10 comprimés d'un
lot de 2 boîtes de 30 laisse **1 boîte + 20 unités en vrac**, et le lot
reste à l'inventaire avec 50 unités. Retirer la boîte entière aurait fait
disparaître des vingt comprimés réellement présents dans l'armoire — donc
les recommander pour rien, ou les laisser périmer sans jamais les voir.

Deux règles portent tout le reste :

- **le vrac part avant qu'une boîte ne soit entamée.** Ouvrir une seconde
  boîte pendant qu'un fond de boîte traîne, c'est du périmé annoncé ;
- **sans conditionnement connu** (« unités par boîte » à 0), une boîte ne se
  convertit pas en comprimés : seul le vrac déjà compté peut sortir. Inventer
  un contenu donnerait un stock d'unités imaginaire.

**Un lot entamé n'est plus une boîte.** Un lot qui n'a plus de boîte pleine
mais garde des unités en vrac reste proposé à la **sortie manuelle** — ces
comprimés sont bien dans l'armoire — mais il est écarté de la **sortie à la
douchette**, qui retire une boîte entière. Il n'y a plus de boîte à retirer.

> Corrigé après audit (v6.19), et ce bug-là coûtait des boîtes. Doucher un
> lot entamé retirait « une boîte » de zéro : l'inventaire ne bougeait pas,
> et l'écran annonçait pourtant en vert « 1 boîte sortie ». Pire, la règle
> FEFO élisait ce lot entamé comme le plus proche de la péremption — la
> douchette ne sortait alors **plus rien du tout**, même avec quatre boîtes
> pleines juste à côté. Le scan répond désormais : « Plus de boîte entière —
> il reste 7 unité(s) d'une boîte entamée », et renvoie vers la sortie à
> l'unité ; s'il existe un autre lot avec des boîtes, c'est lui qui sort.

Et si l'inventaire est **vide** alors qu'on est en mode Sortie, l'écran le
dit et propose un bouton pour repasser en Entrée : chaque scan répondrait
sinon « ce produit n'est pas à l'inventaire », sans issue visible.

### L'inventaire affiché : trois colonnes, et rien au-dessus

**Les cinq compteurs ont disparu.** « Lots enregistrés », « Boîtes »,
« ⛔ Périmés », « 🔴 Moins d'un mois », « 🟠 Moins de 3 mois » tenaient une
bande entière au-dessus d'un tableau qui dit déjà tout cela — ligne par
ligne, avec le statut en tête. Ils repoussaient l'inventaire lui-même sous
la ligne de flottaison, et c'est lui qu'on vient voir.

> L'en-tête du **PDF garde son total**. Sur le papier il n'y a pas de
> défilement : le résumé y est la seule vue d'ensemble.

Autre demande de la pharmacie, mot pour mot : *« au niveau de l'inventaire
affiché on doit avoir seulement le nom du médicament, son CIP et savoir
s'il est périmé, rien de plus »*.

| Statut | Nom du produit | Code CIP |
|---|---|---|
| ⛔ Périmé | ZOLPIDEM 10 mg | 3400930000011 |
| 🟢 OK | AMOXICILLINE 1 g | 3400930000028 |

Onze colonnes tenaient là : boîtes, unités par boîte, vrac, total, lot,
date d'enregistrement, jours restants. Devant l'armoire on ne cherche que
**deux choses** — est-ce le bon produit, et est-il encore bon. Le statut est
la seule des trois qui ne se lise pas sur la boîte.

Le détail s'ouvre d'un clic, sous le tableau : **🔧 Voir le détail et
corriger les quantités**. C'est là que vit le tableau modifiable. On ne
retire que des **colonnes**, jamais un lot : un inventaire qui cache des
lignes ne serait plus un inventaire.

> Le **CSV et le PDF restent complets**. Réduire l'écran n'est pas réduire
> la liste papier : sur le papier on coche des quantités devant l'armoire,
> et il n'y a pas de dépliant. Un test l'interdit.

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

## 💠 Module 4 — Commandes spéciales

En Nouvelle-Calédonie, les médicaments très chers ne sont pas au stock : ils
sont commandés à l'unité, par mail, et **importés du continent**. Le délai
est de trois semaines à un mois.

### Deux horloges, et tout l'intérêt est dans leur décalage

| Horloge | Part de | Dure | Ce qu'elle décide |
|---|---|---|---|
| **Approvisionnement** | l'envoi du mail | le délai d'import | quand la boîte arrivera |
| **Facturation** | la dernière facturation | **22 jours** (minimum imposé par la caisse) | quand on peut encaisser |

Facturer tous les 22 jours va **plus vite** que la consommation réelle (une
boîte par mois environ). Ce décalage est exactement ce qui permet :

- d'**avancer la trésorerie** — indispensable sur des produits payés au
  grossiste bien avant d'être remboursés ;
- de constituer la **boîte d'avance** qui absorbe le mois d'import. Sans
  elle, le patient attend l'avion.

Un **dossier** = un patient + un médicament, suivi dans le temps. Le couple
est ce qui porte les 22 jours : deux dossiers pour la même personne et le
même produit feraient repartir le compteur à zéro, donc facturer trop tôt,
donc un refus de la caisse. Le nom est comparé **sans accent ni casse** pour
que « Mme Léa DUPONT » et « lea dupont » restent la même personne.

### Ce qui est saisi, et ce qui se déduit

**Saisi à la main** : patient, médicament, boîtes en main, date d'envoi du
mail, date de réception, date de dernière facturation. Le **code CIP se
remplit tout seul** : tapez les premières lettres du médicament, choisissez
la boîte dans la liste, le code arrive avec (les 41 000 codes de la base
publique, comme dans le module 3).

**Déduit** — c'est là qu'un tableur s'arrête et qu'un module commence :

- **Facturable le** = dernière facturation + 22 j, avec le compte à rebours ;
- **Délai réellement observé** = réception − envoi. Au bout de quelques
  mois, vous ne dites plus « trois semaines à un mois » : vous savez que *ce*
  produit met 26 jours. C'est la **médiane** qui est retenue, pas la
  moyenne — une commande oubliée trois mois dans un carton ferait sinon
  commander bien trop tôt pour tous les autres patients ;
- **En attente depuis N jours**, et 🔴 **en retard** au-delà du délai
  habituel (plus cinq jours de marge : les imports ne sont pas réguliers) ;
- **À commander** : si la prochaine boîte ne peut pas arriver avant la
  facturation suivante, il faut commander **aujourd'hui**.

### L'écran du matin : trois listes avant tout le reste

1. **💰 À facturer aujourd'hui** — les 22 jours sont écoulés ;
2. **📦 À commander maintenant** — sinon le patient attendra l'avion ;
3. **⏰ Commandes en retard** — mail parti, rien reçu : relancez.

Un même dossier peut tomber dans **deux listes à la fois**, et c'est le cas
normal : s'il ne reste qu'une boîte et qu'elle part aujourd'hui à la
facturation, il faut facturer **et** commander. Des listes rendues
artificiellement exclusives cacheraient l'une des deux actions.

### Import d'un fichier existant (Excel, CSV, PDF)

Retaper trente patients qui existent déjà dans un tableur, c'est une
demi-journée et des fautes de frappe sur des noms. Le panneau
**📂 Importer depuis un fichier**, en haut de l'écran, avale les quatre
formats que lit déjà le reste de l'application : `.xlsx`, `.xlsm`, `.xls`,
`.csv` et `.pdf`.

Vos en-têtes n'ont pas à ressembler aux nôtres : l'application **propose**
la correspondance (« Nom du patient » → Patient, « Spécialité » → Médicament,
« Dernière délivrance » → Dernière facturation) et vous la corrigez avant
d'importer. Seuls le patient et le médicament sont obligatoires.

> **Vos dossiers sont complétés, jamais remplacés.** Un patient déjà suivi
> garde ses dates et son avance si le fichier ne les porte pas. C'est la
> distinction qui compte : « colonne absente du fichier » et « zéro dans le
> fichier » ne sont pas la même chose — les confondre remettrait à zéro
> l'avance de chaque patient, et l'avance est précisément ce qui évite au
> patient d'attendre l'avion.

Une ligne sans patient ou sans médicament est ignorée et comptée. Une date
illisible n'empêche pas le dossier d'être ouvert : elle se corrige ensuite
dans le tableau.

### Les trois gestes du comptoir

**Facturé et délivré**, **Boîte reçue**, **Mail de commande envoyé** : chacun
met à jour la date **et** le nombre de boîtes, parce que ce sont les mêmes
gestes dans la réalité. Facturer sort une boîte du stock ; recevoir en fait
entrer une. Laisser corriger deux cases à la main laisserait l'avance
fausse.

### Rapprochement avec le stock interne

Les boîtes de commandes spéciales sont aussi scannées au stock interne
(module 3). Le module compare, **par code CIP**, ce que les dossiers
annoncent et ce qui est physiquement là — et signale les écarts : une boîte
reçue mais jamais scannée, ou scannée sans être rattachée à un dossier.

> ⚠️ Ce que ce rapprochement ne peut **pas** faire : le code CIP identifie un
> produit, pas une boîte. Si deux patients suivent le même médicament, rien
> dans l'inventaire ne dit laquelle des boîtes est pour qui. On compare donc
> des **totaux par produit**. Prétendre attribuer les boîtes une à une
> serait inventer une information que les données ne contiennent pas.

### Données nominatives

C'est le **seul** module qui contient des noms de patients associés à des
traitements. Le fichier `commandes_speciales.csv` ne quitte jamais la
pharmacie (il n'est pas versionné, et une mise à jour ne l'écrase jamais).
Mais sur un serveur en réseau local **sans mot de passe**, quiconque atteint
le réseau atteint l'application : c'est acceptable sur un réseau d'officine
fermé, ce ne l'est pas sur un réseau ouvert. Ne l'exposez pas sur Internet.

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

stockage_partage.py   Écriture d'un fichier PARTAGÉ entre plusieurs postes :
  (aucun autre module)  verrou, écriture atomique, empreinte relevée sous le
                        verrou. Ne connaît aucun métier. Partagé par les
                        modules 3 et 4 — cette mécanique délicate n'existe
                        qu'à un seul endroit, la dupliquer serait la voir
                        diverger, et une divergence ici perd des données.

stock_ferme.py        MODULE 3 — logique métier pure du stock interne.
  (stockage_partage   Lecture des codes scannés (Data Matrix GS1, CIP13,
   seulement)          CIP7), inventaire par lot, péremptions, exports
                       CSV et PDF. Ne lit aucun fichier déposé.

ui_stock_ferme.py     Interface Streamlit du MODULE 3, isolée dans son
  (import stock_ferme) propre fichier — reçoit d'app.py ses seules
                       fonctions d'habillage, en paramètres.

commandes_speciales.py MODULE 4 — logique métier pure des commandes
  (stockage_partage    spéciales. Les deux horloges (22 jours de la caisse,
   seulement)          délai d'import mesuré), la décision de commander, le
                       rapprochement par CIP. Ne va RIEN chercher tout seul :
                       l'inventaire du stock interne lui est passé en
                       paramètre.

ui_commandes_speciales.py Interface Streamlit du MODULE 4.
  (+ base_medicaments)

app.py                 Interface Streamlit UNIQUEMENT — importe les modules
  (import les 6)        ci-dessus, propose le sélecteur d'espace de travail
                        puis les 2 onglets du parcours « cadencier ».
```

`stock_rotation.py` et `moteur_ruptures.py` n'importent **jamais** l'un de
l'autre : la mutualisation passe exclusivement par `commun.py`.
`stock_ferme.py` et `commandes_speciales.py` n'importent que
`stockage_partage.py`, et jamais l'un l'autre — un test le vérifie. Le
rapprochement du module 4 avec les boîtes du stock interne se fait donc en
LISANT son fichier, sans dépendre de son code. C'est ce qui
garantit qu'on peut faire évoluer la politique de stock sans risquer de
casser le calcul des ruptures, et inversement.

## Installation (une seule fois)

> 📄 Pour transmettre ce dossier à une tierce personne (collègue,
> remplaçant…) : [`INSTALLATION.txt`](INSTALLATION.txt) est un pense-bête
> minimal (texte brut, s'ouvre avec le Bloc-notes, aucun logiciel requis)
> qui explique exactement quoi faire, dans l'ordre.
>
> 🖧 **Pour toute la pharmacie sur une seule base**, deux documents qui
> disent la même procédure et répondent à deux situations :
> [`INSTALLATION-SERVEUR.txt`](INSTALLATION-SERVEUR.txt) s'ouvre au
> Bloc-notes sans rien installer et se copie ;
> [`Guide-installation-serveur.pdf`](Guide-installation-serveur.pdf)
> **s'imprime et se coche**, une étape par page, pour se lire debout devant
> la machine sans perdre sa place. Un test compare les deux pour qu'ils ne
> divergent pas. Ils contiennent tout ce que la section
> [Installation sur un serveur](#-installation-sur-un-serveur-toute-la-pharmacie-sur-une-seule-base)
> détaille ci-dessous, mais en texte brut : pas besoin de savoir ouvrir un
> fichier Markdown le jour où l'on est devant le serveur.

1. **Installer Python** (3.10 ou plus récent) :
   <https://www.python.org/downloads/windows/> — prenez **« Windows installer
   (64-bit) »**, dont le nom finit par `-amd64.exe`, et cochez **« Add
   python.exe to PATH »** pendant l'installation.
2. Récupérer ce dossier `pharmacie-ruptures/` sur le PC (clé USB, téléchargement…).
3. C'est tout : le script de lancement installe les dépendances tout seul la
   première fois.

### Quand Python reste « introuvable » après l'installation

Trois causes, toutes rencontrées sur le serveur de la pharmacie, et toutes
invisibles depuis la fenêtre noire :

| Ce qui se passe | Comment s'en sortir |
|---|---|
| Le fichier téléchargé est un **`.msix`** : ce n'est pas un installeur mais un paquet du Microsoft Store. Un Windows Server n'a pas de quoi l'ouvrir et propose le **Bloc-notes**. | Reprendre la ligne **« Windows installer (64-bit) »**, en `-amd64.exe`. |
| La case **« Add python.exe to PATH »** a été oubliée. Python est bien installé, mais la commande `python` ne répond pas. | Les scripts se rabattent d'eux-mêmes sur le lanceur **`py`**, installé dans tous les cas. Pour rétablir proprement : relancer l'installeur → **Modify** → cocher la case. |
| Une **fenêtre noire ouverte avant** l'installation garde l'ancien PATH. L'installation semble n'avoir rien changé. | La fermer et relancer le script. |

Un quatrième cas, plus sournois : Windows 10/11 pose un **faux `python.exe`**
dans `WindowsApps`, dont le seul rôle est d'ouvrir le Microsoft Store. Il
répond à `where python` — ce sur quoi les scripts se fiaient — sans démarrer
aucun Python. Ils **lancent désormais réellement Python** (`python --version`)
au lieu de chercher son nom, ce que le raccourci du Store ne peut pas simuler.

Pour savoir où l'on en est, dans une invite de commandes (touche Windows,
`cmd`, Entrée) :

```
py --version
```

Si cela répond, Python est installé et c'est le PATH qui manque — les scripts
fonctionneront quand même.

Installation manuelle si besoin :

```
pip install -r requirements.txt
```

## Lancement

- **Windows** : double-cliquez sur l'icône 💊 **Pilotage pharmacie** du Bureau. Elle
  est créée automatiquement au premier lancement (voir ci-dessous) ; sinon,
  double-cliquez sur `lancer.bat` dans le dossier.
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

> **Avant toute chose : double-cliquez sur `verifier-installation.bat`.**
> Il ne répare rien et ne modifie rien — il regarde, et il dit ce qu'il
> voit : le programme est-il là, Python est-il installé, les compléments
> aussi, **l'application tourne-t-elle**, quelle version, quel montage, qui
> d'autre travaille sur le dossier, et quelles données sont présentes avec
> leur date. Chaque point est suivi de ce qu'il faut faire.
>
> Un outil de diagnostic qui répare tout seul est un outil qu'on n'ose plus
> lancer quand ça va mal. Celui-ci se lance sans réfléchir — un test
> interdit toute commande qui écrirait quoi que ce soit.

**« Désolé, impossible d'accéder à cette page » / `ERR_CONNECTION_REFUSED`
sur `localhost:8501`.** Le navigateur dit vrai : il n'y a rien à afficher
parce que **l'application n'est pas démarrée**. Ce message vient d'Edge, pas
de nous, et il ne dit ni cela ni quoi faire. Double-cliquez sur `lancer.bat`
ou sur l'icône 💊 du Bureau. La fenêtre noire qui s'ouvre **est**
l'application : la fermer l'arrête, et l'onglet du navigateur affiche alors
exactement cette page.

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

## 🖧 Installation sur un serveur (toute la pharmacie sur une seule base)

Par défaut, chaque poste a **sa propre** base : ce qui est scanné au
comptoir 1 n'existe pas au comptoir 2. Pour que toute la pharmacie
travaille sur **un seul inventaire**, on installe l'utilitaire sur un
ordinateur serveur et les postes s'y connectent par leur navigateur.

**Rien n'est installé sur les postes.** Ni Python, ni l'application, ni
données : ils reçoivent une icône, qui n'est qu'une adresse.

### La procédure complète, dans l'ordre

Rien d'autre à faire que ces huit points, et rien à sauter : chacun
correspond à une panne qui, sinon, se découvre en pleine journée.

**Sur le serveur**

1. Installer Python et le dossier `pharmacie-ruptures/` comme sur un poste
   normal (voir [Installation](#installation-une-seule-fois)).
2. Double-cliquer sur **`lancer-serveur.bat`**. Il affiche l'adresse à
   donner aux postes, par exemple `http://192.168.1.10:8501`.
3. Autoriser le **port 8501** dans le pare-feu Windows —
   [comment faire](#ouvrir-le-port-8501-dans-le-pare-feu). C'est l'oubli
   qui explique presque tous les « ça ne marche pas ».
4. Donner au serveur une **adresse IP fixe** —
   [comment faire, et comment savoir s'il en a déjà une](#donner-une-ip-fixe-au-serveur).
   Sans cela l'adresse change, et toutes les icônes des postes pointent
   dans le vide.
5. Empêcher le serveur de **se mettre en veille** —
   [comment faire](#empêcher-la-mise-en-veille). Endormi, il ne répond
   plus.
6. Lancer **`planifier-maj-serveur.bat`** —
   [pourquoi c'est indispensable](#tenir-le-serveur-à-jour). Un serveur
   allumé en permanence ne se met **jamais** à jour tout seul.

**Sur chaque poste**

7. Lancer **`creer-raccourci-poste.bat`** —
   [détail](#sur-chaque-poste-une-fois). Il pose l'icône du Bureau. Rien
   n'est installé sur le poste.
8. Lancer **`planifier-ouverture-poste.bat`** —
   [détail](#louverture-automatique-du-matin). L'utilitaire s'ouvrira tout
   seul chaque matin à 08:00. Facultatif, mais c'est le geste qui fait
   lire l'écran du matin.
9. **Avant** de supprimer l'ancienne installation d'un poste, récupérer ses
   fichiers — [lesquels et pourquoi](#les-postes-déjà-équipés). Ce qui y a
   été scanné n'existe nulle part ailleurs.

> ⚠️ La **fenêtre noire du serveur EST l'application**. La fermer arrête
> l'utilitaire pour toute la pharmacie. Sur un serveur qui redémarre la
> nuit, placez un raccourci vers `lancer-serveur.bat` dans le dossier
> `shell:startup` pour qu'il reparte tout seul.

#### Ouvrir le port 8501 dans le pare-feu

**Le plus simple : laisser Windows le demander.** Au tout premier
`lancer-serveur.bat`, une fenêtre apparaît — « Autoriser Python à
communiquer sur ces réseaux ». Cochez **Réseaux privés**, décochez Réseaux
publics, puis **Autoriser l'accès**. Il n'y a rien d'autre à faire.

Si la fenêtre n'est pas apparue, ou si on a cliqué « Annuler » : menu
Démarrer → `cmd` → clic droit sur **Invite de commandes** → **Exécuter en
tant qu'administrateur**, puis :

```
netsh advfirewall firewall add rule name="Pilotage pharmacie (8501)" dir=in action=allow protocol=TCP localport=8501 profile=private
```

- vérifier : `netsh advfirewall firewall show rule name="Pilotage pharmacie (8501)"`
- annuler : `netsh advfirewall firewall delete rule name="Pilotage pharmacie (8501)"`

Par les fenêtres : Windows + R → `wf.msc` → **Règles de trafic entrant** →
clic droit → **Nouvelle règle** → **Port** → TCP, ports locaux `8501` →
**Autoriser la connexion** → cocher **Privé** seulement → nommer la règle.

> ⚠️ Une règle « privé » ne s'applique que si Windows classe le réseau
> comme privé. Vérifiez avec `netsh advfirewall show currentprofile` ; si
> c'est « Public », passez **Paramètres → Réseau et Internet → Ethernet →
> Type de profil réseau** sur **Privé**. Sur un réseau public, Windows
> bloque tout, règle ou pas.

#### Donner une IP fixe au serveur

**D'abord : en a-t-il déjà une ?** Il y a deux façons d'avoir une IP fixe,
et l'une des deux ressemble à une IP dynamique quand on regarde vite.
`ipconfig /all`, puis la ligne **`DHCP activé`** de la carte active :

| Ce qu'on lit | Ce que ça veut dire |
|---|---|
| `DHCP activé : Non` | IP fixe réglée **sur le poste**. C'est fait. |
| `DHCP activé : Oui` | L'adresse vient de la box — cela ne dit pas encore si elle est fixe. |

Le second cas est ambigu parce qu'une **réservation dans la box** donne
toujours la même adresse *tout en passant par le DHCP* : Windows affiche
`Oui` alors que l'adresse ne bougera jamais. Pour trancher, ouvrez la page
d'administration de la box → **DHCP → Baux statiques / Réservations**, et
vérifiez que l'adresse MAC du serveur y figure.

- `Non`, ou `Oui` **avec** réservation → rien à faire.
- `Oui` **sans** réservation → l'adresse peut changer : agissez.

Dans les deux cas où il n'y a rien à faire, une seule vérification reste
utile : que l'adresse soit **hors de la plage distribuée par la box**. Le
cas qui se voit en officine, c'est une IP fixe posée *dans* cette plage —
cela marche des mois, puis un poste neuf reçoit la même adresse et les
deux tombent le même matin.

**Pour en poser une, la bonne méthode : la réservation dans la box.** Elle
ne peut pas entrer en conflit et survit à une réinstallation de Windows.

1. Sur le serveur : `ipconfig /all`.
2. Relever l'**Adresse physique** de la carte active (`A1-B2-C3-D4-E5-F6`)
   — c'est son adresse MAC.
3. Ouvrir la page d'administration de la box (souvent `http://192.168.1.1`).
4. Chercher **DHCP** → « Baux statiques », « Réservation d'adresse » ou
   « Adresse IP fixe », et associer cette adresse MAC à l'IP voulue.

Sinon, directement sur Windows : `ipconfig /all` d'abord, pour noter
l'**Adresse IPv4**, la **Passerelle par défaut** et les **Serveurs DNS**.
Puis **Paramètres → Réseau et Internet → Ethernet** → à côté de
« Attribution IP », **Modifier** → **Manuel** → activer **IPv4** :

- **Adresse IP** : une adresse **hors de la plage distribuée par la box**
  (si elle donne de .100 à .150, prenez `192.168.1.200`) — sinon la box la
  donnera un jour à un autre appareil, et les deux se gêneront ;
- **Longueur du préfixe de sous-réseau** : `24` (l'équivalent de
  255.255.255.0, que demande l'ancien panneau `ncpa.cpl`) ;
- **Passerelle** et **DNS préféré** : l'adresse de la box.

En ligne de commande (invite en administrateur) :

```
netsh interface ip show config
netsh interface ip set address name="Ethernet" static 192.168.1.200 255.255.255.0 192.168.1.1
netsh interface ip set dns name="Ethernet" static 192.168.1.1
```

Ensuite, relancez `lancer-serveur.bat` pour lire l'adresse définitive, puis
repassez sur les postes avec `creer-raccourci-poste.bat` si elle a changé.

> Si l'adresse change un jour malgré tout, rien n'est perdu : les icônes
> des postes sont de simples fichiers texte. Relancez
> `creer-raccourci-poste.bat` avec la nouvelle adresse, ou ouvrez
> `Pilotage pharmacie.url` du Bureau avec le Bloc-notes et corrigez la ligne
> `URL=`.

#### Empêcher la mise en veille

C'est l'oubli auquel personne ne pense : un serveur endormi ne répond
plus, et les postes affichent une page blanche sans explication.

**Paramètres → Système → Alimentation** → « Veille » → **Jamais**. Le
réglage de l'écran, lui, n'a aucune importance.

### Tenir le serveur à jour

**Un serveur qui tourne en continu ne se met JAMAIS à jour tout seul.** La
mise à jour automatique n'a lieu qu'au **démarrage** de l'application, et
elle se reporte tant que celle-ci répond sur le port 8501 — pour ne pas
interrompre une session en cours. Une machine allumée en permanence ne
remplit jamais ces deux conditions : sans le réglage ci-dessous, la
pharmacie resterait indéfiniment sur sa version du premier jour.

#### Chaque nuit, sans y penser (recommandé)

Sur le serveur, **une seule fois** :

```
planifier-maj-serveur.bat
```

Windows lancera la mise à jour tous les jours à **05:00**. Pour une autre
heure : `planifier-maj-serveur.bat 04:30`. Pour retirer la tâche :
`planifier-maj-serveur.bat /supprimer`.

Le script **affiche** la fiche enregistrée par Windows plutôt que d'affirmer
que c'est fait. Pour la revoir plus tard :

```
schtasks /query /tn "Pilotage pharmacie - mise a jour" /v /fo list
```

Deux conditions à connaître :

- la **session Windows du serveur doit rester ouverte** — écran verrouillé,
  c'est parfait ; déconnecté, la tâche ne partira pas. C'est aussi pour cela
  que la tâche s'exécute sous votre compte et non sous `SYSTEM` : c'est dans
  votre session que vit la fenêtre noire de l'application ;
- la mise à jour **redémarre l'application**. Les postes perdent leur page
  quelques secondes, et une fiche de complément en cours de saisie est
  perdue. D'où l'heure creuse.

#### À la main, quand le bandeau le signale

Le plus simple est le **bouton de la barre latérale** (voir
[Le bouton d'installation](#-le-bouton-dinstallation-le-chemin-normal)) :
sur un serveur, il lance le bon script et demande confirmation avant de
déconnecter les postes.

À défaut, sur le serveur lui-même, double-cliquez sur
**`mettre-a-jour-serveur.bat`** : il arrête l'application, remplace les
fichiers et **la relance en mode serveur**.

> Sur un serveur, préférez `mettre-a-jour-serveur.bat`. `mettre-a-jour.bat`
> **fonctionnerait** — les postes retrouveraient l'application, car
> Streamlit écoute par défaut sur toutes les cartes réseau — mais il
> relance avec les réglages d'un poste isolé : un navigateur s'ouvre sur
> l'écran du serveur, une icône pointant vers le mauvais lanceur atterrit
> sur son Bureau, et rien n'est écrit dans `maj_serveur.log`. Surtout, il
> ne sait ni se taire ni rendre la main : c'est pourquoi la tâche de nuit
> ne peut pas l'employer.

#### Savoir ce qui s'est passé cette nuit

Chaque exécution écrit dans **`maj_serveur.log`**, à côté de l'application :
horodatage, version avant et après, et la raison en cas d'abandon. Une mise
à jour faite à 5 h du matin doit rester explicable au matin.

En cas d'échec (Internet coupé, archive illisible), **rien n'est modifié** et
l'application en cours continue de tourner : une mise à jour ratée ne doit
jamais fermer la pharmacie.

> Comme `mettre-a-jour.bat`, le script `mettre-a-jour-serveur.bat` n'est
> **jamais remplacé** par une mise à jour — il est en cours d'exécution
> pendant que les fichiers sont copiés, et cmd relit le fichier au fil des
> lignes. Ses propres améliorations n'atteignent donc que les installations
> neuves.

### Sur chaque poste, une fois

Double-cliquer sur **`creer-raccourci-poste.bat`** (depuis le dossier
partagé du serveur, ou une clé USB). Il pose sur le Bureau la même icône
💊 **Pharmacie**, qui ouvre l'application du serveur dans le navigateur.

Il trouve l'adresse tout seul si le dossier du serveur est partagé
(`adresse-serveur.txt`, écrit à chaque démarrage) ; sinon il la demande, et
accepte aussi bien `192.168.1.10` que l'adresse complète recopiée depuis le
navigateur.

### L'ouverture automatique du matin

L'écran du matin — péremptions à traiter, commandes à facturer, commandes à
passer — ne vaut que s'il est **lu avant** que la journée commence. Compter
sur quelqu'un pour cliquer une icône à 8 heures, c'est compter sur le seul
moment où personne n'a le temps.

Double-cliquer une fois sur **`planifier-ouverture-poste.bat`**, sur chaque
poste, depuis le dossier partagé :

```
planifier-ouverture-poste.bat              tous les jours à 08:00
planifier-ouverture-poste.bat 07:45        à l'heure voulue
planifier-ouverture-poste.bat /supprimer   retire la tâche
```

> **À refaire sur chaque poste.** Windows ne connaît que les tâches de la
> machine où on les crée — il n'existe aucun réglage central. C'est la même
> visite que `creer-raccourci-poste.bat` : autant enchaîner les deux.

**« 08:00 heure de Calédonie » n'existe pas pour Windows :** il ne connaît
que le fuseau réglé sur la machine. Le script affiche donc ce fuseau **et
l'heure qu'il est**, et prévient si ce n'est pas celui de Nouméa (*Central
Pacific Standard Time*, UTC+11). Un poste réglé ailleurs partirait à côté
sans que rien ne le signale, et on mettrait des mois à s'en apercevoir.

Trois problèmes se cachent derrière une demande qui paraît simple :

| Le piège | Ce que fait le script |
|---|---|
| Une tâche « tous les jours à 08:00 » **ne part jamais** sur un poste allumé à 08h10 — c'est-à-dire le cas ordinaire d'une officine. | Elle repasse **tous les quarts d'heure pendant quatre heures**, puis renonce : à midi, personne n'a plus besoin qu'on lui ouvre son écran du matin. |
| Ce rattrapage rouvrirait l'écran toutes les quinze minutes, en plein travail. | Un **témoin daté** : une ouverture par jour, pas deux. Il est **local au poste** — posé sur le partage, le premier poste ouvert priverait tous les autres. |
| À 08:00, le serveur peut **encore être en train de démarrer**. Le navigateur n'afficherait qu'une page d'erreur, et le témoin du jour interdirait toute nouvelle tentative. | Le script vérifie que le serveur répond. S'il ne répond pas, **il ne marque rien** : la répétition suivante ouvrira dès qu'il sera debout. |

Le script s'adapte tout seul à l'installation : si `adresse-serveur.txt`
est là, il ouvre le navigateur sur le serveur ; sinon il démarre
`lancer.bat` sur le poste.

Une fois la fenêtre fermée en cours de journée, elle ne revient pas d'elle-
même — l'icône 💊 du Bureau est là pour ça. Le lendemain matin, si.

> La session Windows doit être **ouverte** au moment dit. Écran verrouillé,
> c'est bien : la tâche part et la page attend derrière le verrou. Session
> fermée, non — Windows ne lance rien pour un utilisateur absent.

### Les postes déjà équipés

Il n'y a pas de désinstallation au sens Windows : **supprimez le dossier
`pharmacie-ruptures/` du poste et son icône du Bureau**. Le laisser en
place, c'est risquer qu'un jour on lance la copie locale par erreur et
qu'on alimente une base que personne d'autre ne voit.

**Avant de supprimer**, récupérez les fichiers de ce poste — ce qui y a été
scanné ne se trouve nulle part ailleurs :

- `stock_ferme.csv` (l'inventaire) ;
- `stock_ferme_produits.csv` (les produits mémorisés) ;
- `config.yaml` et `historique_commandes.csv` si le poste servait aussi aux
  modules cadencier.

### Ce que le partage change (et ce qu'il ne change pas)

- **Écritures simultanées.** Deux comptoirs peuvent scanner en même temps.
  L'inventaire n'est jamais réécrit « en bloc » depuis la mémoire d'un
  poste : chaque geste est appliqué au fichier **relu à l'instant**, sous
  verrou. Une boîte scannée ne peut donc pas être effacée par le poste
  d'à côté (`tests/test_concurrence.py`, et deux navigateurs réels dans
  `tests/test_interface.py`).
- **Écran à jour.** Chaque poste relit l'inventaire dès que le fichier a
  changé : il voit les boîtes des autres sans recharger sa page.
- **Correction dans le tableau.** Elle remplace l'inventaire entier — c'est
  sa nature. Si un autre poste a scanné pendant la saisie, la correction
  est **refusée** et annoncée, plutôt que d'effacer son travail en
  silence.
- **Mise à jour.** Une seule à faire, sur le serveur — mais elle ne se fera
  pas toute seule sans un réglage à poser une fois : voir
  [Tenir le serveur à jour](#tenir-le-serveur-à-jour) ci-dessous.
- **Fichier ouvert dans Excel.** Windows refuse alors de le remplacer.
  L'application le dit en une phrase et n'enregistre rien plutôt que de
  laisser croire que c'est fait ; fermez Excel et refaites le geste.
- **Pas de mot de passe.** Quiconque atteint le réseau de la pharmacie
  atteint l'application. C'est acceptable sur un réseau d'officine fermé ;
  ne l'exposez pas sur Internet.
- **Sauvegarde.** Tout est dans un seul dossier sur le serveur, ce qui
  simplifie la sauvegarde — et la rend indispensable : il n'y a plus de
  copie sur les postes.

### Le dossier posé sur un partage réseau

Rien n'empêche de mettre le dossier sur un partage
(`\\srv-lafoa\KaoriPHARM\Utilitaire Gestion de stock`) et de lancer les
scripts depuis là. **Mais cmd refuse un chemin UNC comme répertoire
courant** : il se rabat sur `C:\Windows` en annonçant seulement

```
Les chemins d'acces UNC ne sont pas pris en charge.
Utilisation du repertoire Windows par defaut.
```

et tout ce qui suit cherche alors dans `C:\Windows`. On obtient trois
erreurs en cascade — `Could not open requirements file`, `can't open file
C:\Windows\maj_auto.py`, `File does not exist: app.py` — dont **aucune ne
nomme la cause**.

Les scripts montent désormais eux-mêmes un lecteur temporaire (`pushd`) et
fonctionnent depuis un partage. Deux détails qui allaient de pair :

- ceux qui n'ouvrent aucun fichier par un chemin relatif
  (`creer-raccourci.bat`, `planifier-maj-serveur.bat`, les deux
  `maj-auto-*.bat`) **ne changent plus de répertoire du tout** — tout y
  passe par `%~dp0`. `creer-raccourci.bat` est appelé à chaque démarrage
  dans le processus cmd de `lancer.bat` : y monter un lecteur en aurait
  empilé un par lancement ;
- la tâche de nuit relance le serveur **détaché**, puis se termine
  aussitôt. L'enfant hérite du répertoire courant mais **pas** du montage
  qui le rend valide : il refait le sien, sinon le serveur repartirait
  dans le vide et la pharmacie trouverait porte close au matin.

Si Windows ne peut vraiment pas monter de lecteur (plus une seule lettre
libre), les scripts le **disent** au lieu de continuer ailleurs, et
proposent les deux issues : connecter le partage à une lettre de lecteur,
ou copier le dossier sur le disque local.

#### Lequel choisir, en deux phrases

**Tout sur le serveur, une icône sur les postes** — c'est le montage
recommandé, et celui que décrit
[la procédure complète](#la-procédure-complète-dans-lordre) :

| | |
|---|---|
| **Sur le serveur** | Python + le dossier. On lance `lancer-serveur.bat`, et **on laisse la fenêtre noire ouverte** : elle *est* l'application. Une session Windows doit rester ouverte. |
| **Sur chaque poste** | `creer-raccourci-poste.bat`, une fois. **Rien d'autre** — ni Python, ni le programme, ni données. L'icône n'est qu'une adresse. |

Ce que cela demande en plus : le port 8501 ouvert, une IP fixe, pas de mise
en veille, et `planifier-maj-serveur.bat` pour que le serveur se mette à
jour. Ce que cela évite : Python sur cinq postes, cinq installations à
maintenir, cinq fois plus d'occasions que quelque chose diverge.

**L'autre montage** — le dossier partagé, chaque poste lance l'application
lui-même — demande Python partout, mais aucune machine à garder allumée.
Les deux fonctionnent ; ce qui ne fonctionne pas, c'est de les mélanger.

> **Deux déploiements possibles, à ne pas mélanger.** Soit le serveur fait
> tourner l'application (`lancer-serveur.bat` **sur le serveur**) et les
> postes n'ont qu'une icône de navigateur — rien n'est installé chez eux ;
> soit chaque poste lance `lancer.bat` depuis le partage, et **Python doit
> alors être installé sur chaque poste**. Le premier est celui que décrit
> [la procédure complète](#la-procédure-complète-dans-lordre) : une seule
> mise à jour, une seule machine à surveiller.

#### Quand chaque poste lance l'application depuis le partage

C'est le second déploiement : le dossier vit sur le disque du serveur,
partagé, **rien ne tourne sur le serveur lui-même**, et chaque poste y lance
son propre Streamlit sur les mêmes fichiers. C'est un choix légitime — il
évite d'avoir à garder une session ouverte en permanence sur le serveur, et
avec elle le pare-feu, l'IP fixe et la mise en veille.

**La bonne méthode, poste par poste :**

1. installer **Python** sur le poste
   ([comment](#installation-une-seule-fois)) — indispensable, l'application
   tourne chez lui ;
2. depuis le dossier partagé, double-cliquer sur **`lancer.bat`**.

C'est tout, et c'est aussi le geste de tous les jours. `lancer.bat` installe
les dépendances Python **sur ce poste**, pose l'icône 💊 du Bureau, vérifie
s'il existe une nouvelle version, puis ouvre l'application.

> ⚠️ **Ne pas se servir de `mettre-a-jour.bat` pour installer un poste.** Il
> fonctionne — mais il **re-télécharge et réécrit tout le dossier partagé**,
> depuis chaque poste, à chaque fois. Sur cinq postes, c'est cinq
> réécritures du dossier de toute la pharmacie pour un travail que
> `lancer.bat` fait sans y toucher. Gardez-le pour ce à quoi il sert :
> forcer une mise à jour, en dehors des heures d'ouverture.

##### « Installation des fichiers… » et plus rien

Ce blocage a été vu en officine, sur un poste qu'il fallait installer.
L'écran restait figé sur cette ligne, indéfiniment. Trois causes empilées,
dont aucune ne s'annonçait :

- **`robocopy` réessaie un million de fois par défaut**, trente secondes
  entre chaque. Un seul fichier verrouillé, et c'est près d'un an
  d'attente. Il renonce maintenant au bout de deux essais et **dit** ce qui
  bloque ;
- **l'application était fermée à l'étape suivante** — on remplaçait donc
  les fichiers pendant qu'elle tournait encore. Elle est désormais fermée
  **avant** la copie ;
- **le fichier verrouillé avait un nom** : `pharmacie.ico`. Chaque
  raccourci du Bureau pointait dessus *sur le partage*, et l'Explorateur le
  garde ouvert. L'icône est maintenant copiée sur le poste, comme le
  faisait déjà `creer-raccourci-poste.bat`.

> **Un mot sur la façon dont ce correctif vous parvient.** `mettre-a-jour.bat`
> s'excluait de sa propre copie — à raison : cmd relit un `.bat` au fil des
> lignes, le remplacer sous ses pieds lui ferait exécuter n'importe quoi.
> Mais il s'excluait **aussi** de la mise à jour automatique, qui est du
> Python et ne l'exécute pas. Un bug dedans était donc **incorrigible à
> distance** : réparé dans le dépôt, il restait indéfiniment sur le disque
> de la pharmacie. C'est exactement ce qui s'est produit — le poste tournait
> encore sur une version affichant « [3/4] ». `maj_auto` a désormais le
> droit de les corriger ; chacun continue de s'exclure de sa **propre**
> copie.
>
> Conséquence pratique : **cette fois-ci, remplacez les deux
> `mettre-a-jour*.bat` à la main** dans le dossier partagé. Les suivantes se
> feront toutes seules.

Dans ce déploiement, les étapes 3 (pare-feu), 4 (IP fixe), 5 (veille) et 6
(`planifier-maj-serveur.bat`) de la procédure serveur **ne servent à rien** :
le port 8501 reste local à chaque poste, et aucune application ne tourne sur
le serveur.

Les écritures simultanées sont couvertes depuis le début (verrou, écriture
atomique, relecture sous verrou). Deux choses ne l'étaient pas, et ne se
voient que dans ce déploiement précis :

**Un seul poste recevait son icône.** `creer-raccourci.bat` gardait son
témoin « icône déjà posée » **dans le dossier de l'application** — donc sur
le partage. Le premier poste équipé l'écrivait, et tous les suivants y
lisaient « déjà fait » devant un Bureau vide. Le témoin vit désormais dans
`%LOCALAPPDATA%\Pharmacie\`, qui appartient à la machine.

**Un poste mettait à jour sous les autres.** `maj_auto` vérifiait qu'aucune
application ne tournait — sur `127.0.0.1`, c'est-à-dire chez elle seule. Le
scénario, un matin ordinaire :

1. le comptoir 1 ouvre l'application à 07h55 ;
2. le comptoir 2 la lance à 08h05. Son port 8501 **à lui** est libre, donc
   `maj_auto` se croit seul, télécharge la nouvelle version et remplace les
   fichiers du dossier partagé ;
3. Streamlit, chez le comptoir 1, recharge ses modules à chaud — et l'écran
   part en erreur au milieu d'un scan.

Chaque lancement dépose maintenant un **marqueur à son nom**
(`.postes-actifs/`) et le retire en partant. La mise à jour ne touche à
rien tant qu'il en reste un, et **nomme** les postes concernés : « Dossier
en cours d'utilisation par : COMPTOIR-1 ». On sait à qui aller demander de
fermer sa fenêtre, plutôt que de lire « occupé ».

Le marqueur **périme au bout de 16 heures** — une journée de travail. Un
poste éteint brutalement laisse le sien : sans péremption, une seule
coupure de courant figerait la pharmacie sur sa version pour toujours, et
personne ne saurait pourquoi.

**Les AUTRES postes, pas tous** — corrigé après audit (v6.19). Fermer la
fenêtre noire par la croix est la façon documentée d'arrêter l'application,
et elle tue `cmd` avant sa dernière ligne, `presence.py --sortir` : le poste
laisse donc son propre marqueur derrière lui à peu près chaque soir. Au
lancement suivant, `maj_auto` s'y voyait lui-même, refusait de se mettre à
jour, et affichait « Dossier en cours d'utilisation par : COMPTOIR-2 »
**sur** le poste COMPTOIR-2. La mise à jour automatique ne se faisait plus
pendant seize heures, sans que rien ne le dise — c'est l'explication du
« j'ai téléchargé la dernière version, tes modifications n'apparaissent
pas ». La session en cours de ce poste-ci, elle, reste couverte : le test du
port répond avant, et c'est lui qui la protège.

La conséquence pratique est la bonne : **la mise à jour se fait au premier
lancement du matin**, quand personne d'autre n'est encore ouvert. C'est
exactement le moment où elle est sans danger.

**Et la mise à jour manuelle ?** `mettre-a-jour.bat` réécrit le dossier sans
passer par `maj_auto`. Il regarde donc lui aussi qui travaille, et le **dit
avant** de toucher à quoi que ce soit :

```
[ATTENTION] Ces postes utilisent le dossier en ce moment :

COMPTOIR-1
COMPTOIR-3

Remplacer les fichiers maintenant interrompra leur ecran, en
pleine dispensation.

  Continuer quand meme ? (o/N) :
```

Ici, contrairement à la mise à jour automatique, c'est **quelqu'un qui
décide** : le script ne refuse pas, il montre qui sera interrompu. Le cas
courant — personne d'autre — ne pose aucune question et reste un simple
double-clic.

Il ne se compte pas lui-même : sa propre application va de toute façon
redémarrer. Se compter ferait apparaître l'avertissement à chaque fois, et
on apprendrait à passer outre sans le lire.

Sur le serveur, la version de nuit ne pose pas la question — personne n'est
devant. Elle **renonce**, le consigne dans `maj_serveur.log`, et la nuit
suivante réessaiera.

## ⬆️ Le bouton d'installation (le chemin normal)

Quand une nouvelle version est publiée, le bandeau l'annonce et un encadré
**⬆️ Version disponible** apparaît en haut de la barre latérale. Un clic sur
**« Installer la vX.Y »** suffit : l'application redémarre et la page se
recharge toute seule au bout d'une minute environ. Rien de ce qui est
enregistré n'est perdu.

C'est le geste normal, et il existe pour une raison précise : **le
double-clic sur l'icône du Bureau ne met jamais à jour une application déjà
ouverte.** `lancer.bat` appelle bien la mise à jour automatique, mais
celle-ci se reporte tant que l'application répond — et personne ne ferme
l'application avant de cliquer sur son icône. Le bandeau annonçait donc une
version sans donner le moyen de la prendre.

- L'encadré n'apparaît **que** lorsqu'il sert : à jour, il n'y a rien à dire.
- **Sur un serveur**, un clic redémarre l'application de toute la pharmacie :
  l'encadré le dit, et demande de cocher « J'ai prévenu les autres postes »
  avant d'agir. C'est le bon script qui est lancé
  (`mettre-a-jour-serveur.bat`), reconnu au drapeau avec lequel
  l'application a démarré — pas à un fichier témoin qui pourrait mentir.
- Une fenêtre noire s'ouvre et montre la mise à jour se dérouler : ne la
  fermez pas.
- Si le lancement échoue (script interdit sur le poste, droits insuffisants),
  l'application le **dit** en français et reste debout : il reste le
  double-clic sur le script, décrit plus bas.

## Mise à jour automatique

L'utilitaire se met à jour **tout seul**, à deux moments :

- **à chaque lancement** (`lancer.bat`) — c'est le seul instant où
  remplacer des fichiers est sans danger, l'application n'étant pas encore
  démarrée ;
- **chaque nuit sur un serveur** (`planifier-maj-serveur.bat`), qui ne
  redémarre jamais et ne passerait donc jamais par le point précédent.

**Tout ou rien.** Si un seul fichier est ouvert par un autre programme,
`maj_auto` **n'écrit rien** et dit lequel fermer. Le cas réel : l'Explorateur
garde `pharmacie.ico` ouvert pour chaque raccourci du Bureau qui pointe
dessus ; la copie avançait jusque-là puis s'arrêtait, laissant le dossier **à
moitié** en nouvelle version — un `app.py` neuf sur un `ui_stock_ferme.py`
ancien, donc un écran qui plante sur une fonction qui n'existe pas encore.
Un dossier à moitié mis à jour est pire qu'un dossier en retard.

Trois règles de prudence, appliquées par `maj_auto.py` :

| Situation | Ce qui se passe |
|---|---|
| L'application est **ouverte** | rien n'est touché — remplacer un module sous une session en cours la casserait |
| Le poste est **hors ligne** | rien n'est tenté, aucun message |
| La version publiée est **identique ou plus ancienne** | aucun téléchargement (seul `app.py` est lu, quelques Ko) |

Vos données — inventaire du stock interne, historique, réglages, base des
médicaments — ne sont **jamais** écrasées. Le déroulement est consigné dans
`maj_auto.log`.

### Ce que contient le ZIP téléchargé

**34 fichiers, 718 Ko** — le programme, et rien d'autre.

Le dépôt contient aussi tout ce qui sert à **fabriquer** le programme :
2,4 Mo de tests, les outils qui dessinent l'icône et composent le guide PDF.
L'archive les emportait tous. `maj_auto` les écartait bien à l'installation,
mais celui qui télécharge le ZIP **à la main** dépliait tout dans le dossier
de l'officine — cent fichiers inconnus autour de `lancer.bat`, et personne
ne lance un utilitaire dont il ne reconnaît aucun fichier.

`.gitattributes` marque ces chemins `export-ignore` : c'est le mécanisme que
GitHub applique à son bouton **Download ZIP** comme à l'URL que `maj_auto`
télécharge. Les fichiers **restent dans le dépôt** — ils ne sont pas
supprimés, ils ne sont pas *exportés*, et la suite de tests continue de
tourner.

> Le filtre de `maj_auto` reste en place, volontairement : un poste peut
> installer une archive plus ancienne, faite avant ce fichier. Un test
> vérifie que les deux listes ne divergent pas.

**Sur votre partage, le ménage reste à faire une fois** : une mise à jour
ajoute et remplace, elle ne supprime jamais. Les dossiers `tests` et
`outils` déjà déposés y sont encore — vous pouvez les effacer à la main,
rien n'en dépend.

> Une mise à jour automatique installe du code sans relecture préalable. Si
> vous préférez garder la main, désactivez la tâche planifiée : le bandeau
> continuera de signaler les nouvelles versions, et `mettre-a-jour.bat`
> restera disponible à la demande.

## Mise à jour manuelle (Windows, en un clic)

Double-cliquez sur **`mettre-a-jour.bat`** : il télécharge la dernière
version depuis GitHub, remplace les fichiers programme et relance l'app —
**sans toucher à vos données** (`config.yaml`, `historique_commandes.csv`,
l'état du stock min/max et l'inventaire du stock interne sont préservés). Après la mise à jour, vérifiez le numéro de version dans le
bandeau. Si le numéro n'a pas changé, faites **Ctrl + Maj + R** dans le
navigateur (cache de page).

💡 **Pour découvrir l'outil sans fichiers** : cliquez sur
« 🧪 Essayer avec des données de démonstration » sur l'écran d'accueil —
l'analyse tourne sur un jeu fictif sans toucher à votre configuration.

## Utilisation (chaque jour)

Le sélecteur d'**espace de travail**, en haut de l'écran, choisit entre le
parcours « cadencier » (Modules 1 et 2, décrit ci-dessous) et le **stock
interne** (Module 3), qui, lui, ne demande aucun fichier : on y scanne, on
imprime.

**Le stock interne est le premier onglet, et l'écran d'arrivée.** C'est
celui de la journée : on y bipe des boîtes toute la matinée, quand le
cadencier se consulte une fois le matin. Il était deuxième, et le cadencier
s'ouvrait par défaut — il fallait donc un clic pour arriver là où l'on
passe ses heures. Premier **et** ouvert d'emblée : un premier onglet qu'il
faut cliquer pour voir n'est premier que sur le papier.

**Les trois onglets ont la même taille**, et un seul est en couleur :
**🔒 Stock interne** porte le turquoise de l'application en permanence —
allumé comme éteint — quand les deux autres restent neutres. C'est le seul
des trois où l'on prend la douchette en main, et il doit se repérer **sans
lire**.

> Il a d'abord été agrandi, puis ramené à la taille des autres : deux fois
> plus haut que ses voisins, il déséquilibrait une barre par ailleurs
> alignée. La couleur suffit à le désigner, et elle ne décale rien.

Son libellé disait **« Stock interne — inventaire scanné »**. La moitié de
la place partait à décrire ce que l'écran montre juste en dessous : un
onglet **nomme** un espace, il ne le décrit pas.

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
├── stock_ferme.py           # Module 3 — stock interne (scan, lots, péremptions)
├── base_medicaments.py      # identification d'un CIP via la base publique
├── ui_commun.py             # règles pures de l'interface (sans Streamlit)
├── ui_stock_ferme.py        # interface du Module 3 (Streamlit)
├── .streamlit/config.toml   # thème de l'interface (vert pharmacie)
├── config.yaml               # mapping + réglages mémorisés (créé au 1er lancement)
├── historique_commandes.csv  # historique des analyses de ruptures (créé à la 1re)
├── stock_ferme.csv           # inventaire du stock interne (créé au 1er scan)
├── base_medicaments.csv      # base publique téléchargée (créée à la demande)
├── stock_ferme_produits.csv  # produits mémorisés du stock interne (CIP → nom)
├── requirements.txt          # dépendances Python
├── maj_auto.py              # mise à jour automatique (testable, sans Streamlit)
├── presence.py              # qui utilise le dossier partagé en ce moment
├── lancer.bat                 # double-clic Windows
├── mettre-a-jour.bat        # mise à jour en un clic (poste isolé)
├── lancer-serveur.bat       # démarre l'application POUR TOUTE la pharmacie
├── mettre-a-jour-serveur.bat   # met à jour le serveur et le redémarre
├── planifier-maj-serveur.bat   # la fait chaque nuit (le serveur ne dort pas)
├── creer-raccourci-poste.bat   # icône du Bureau d'un poste, vers le serveur
├── planifier-ouverture-poste.bat # ouvre l'utilitaire chaque matin à 08:00
├── ouvrir-le-matin.bat      # ce que cette tâche lance (une fois par jour)
├── verifier-installation.bat # diagnostic d'un poste : il regarde, il ne touche à rien
├── creer-raccourci.bat       # pose l'icône 💊 « Pilotage pharmacie » sur le Bureau
├── raccourci.py             # la même pose, appelable depuis l'application
├── pharmacie.ico            # icône du raccourci (16 → 256 px)
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
l'inventaire du stock interne sont écrits **à côté du programme**, pas dans le
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
arrêtés, paramètres reconfigurables). Cas de référence Module Stock interne :
Data Matrix sans séparateur FNC1 (`…10LOT4217271130` → lot `LOT42`, et non
`LOT4` ; `…101234AB21987654321` → lot `1234AB` **et** série `987654321`),
deux péremptions du même CIP donnant deux lignes, PDF lisible sans émoji et
repliant les libellés trop longs.
