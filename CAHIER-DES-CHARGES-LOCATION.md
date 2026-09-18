# 🛏️ Cahier des charges — Module 5 « Location & achat »

**Ententes préalables CAFAT, matériel médical loué ou vendu au patient.**

Version 6.34 · Pharmacie de La Foa · Nouvelle-Calédonie

---

## 1. Pourquoi ce module existe

Fournir un lit médicalisé, un fauteuil roulant, une VNI ou un concentrateur
d'oxygène à un patient suppose **l'accord préalable de la caisse**. Cet
accord — l'**entente préalable** — porte une date et une durée, et il
**expire**.

Passée l'échéance :

- la fourniture n'est plus prise en charge ;
- le matériel reste pourtant chez le patient ;
- plus personne ne la paie — ni la caisse, ni le patient qui ne savait pas.

Rien, dans l'outil existant, ne le rappelait. Le cadencier ne connaît que
les boîtes, le stock interne ne connaît que ce qui est scanné, les
commandes spéciales ne connaissent que les médicaments chers. Les ententes
vivaient sur un cahier et dans une mémoire.

**Ce que le module doit empêcher, en une phrase :** qu'une échéance se
découvre le jour où la caisse refuse de payer.

---

## 2. Ce qui est suivi

### 2.1 L'unité de suivi : le dossier

Un **dossier** = un patient × un matériel × un mode.

Le même patient peut avoir plusieurs dossiers : il loue un lit ET achète
un déambulateur. Il peut même avoir deux dossiers sur le **même**
matériel — un fauteuil d'abord loué, puis acheté : ce sont deux ententes,
deux facturations, et les confondre effacerait l'historique de la location
le jour de l'achat.

### 2.2 Les deux modes

|                          | 🛏️ **Location**                     | 🛒 **Achat**                    |
| ------------------------ | ----------------------------------- | ------------------------------- |
| Entente préalable        | oui, **renouvelable**               | oui, **une fois**               |
| Facturation              | **tous les mois**                   | **une seule fois**              |
| Une fois facturé         | redevient dû le mois suivant        | **terminé**, plus rien          |
| Échéance de l'entente    | à surveiller en permanence          | sans objet une fois réglé       |

Les deux vivent dans **le même fichier**, avec **le même vocabulaire de
statuts** et **les mêmes gestes**. Deux fichiers séparés auraient coupé
chaque patient en deux, et il aurait fallu le chercher deux fois pour
répondre à « où en suis-je ? ».

### 2.3 Ce qui est saisi, et ce qui se déduit

**Saisi** (et donc corrigeable) : patient, matériel, mode, début de
fourniture, date de l'entente préalable, durée de validité en mois, date
de la dernière facturation, notes.

**Déduit** (et donc jamais stocké) : l'échéance, les jours qui en
restent, le statut de l'entente, la prochaine facturation, les mois dus,
le statut de facturation.

> Une valeur enregistrée qui se déduit finit par contredire ce dont elle
> est déduite. C'est pourquoi le fichier ne contient aucune de ces
> colonnes-là : elles sont recalculées à chaque affichage.

---

## 3. Les règles de calcul

### 3.1 La durée de validité est **saisie par dossier**

La caisse accorde au cas par cas selon le matériel. Le module **n'invente
aucune règle** : il propose une valeur par défaut (6 mois), modifiable
ligne à ligne.

> Inventer une règle unique ferait expirer des dossiers sans prévenir, ou
> les ferait renouveler pour rien.

### 3.2 L'échéance reste dans le calendrier

`échéance = date de l'entente + durée en mois`

Le 31 janvier plus un mois est le **28 février** (le 29 en année
bissextile), pas le 3 mars. Ajouter 30 jours ferait dériver l'échéance
d'un mois sur l'autre : sur six mois, l'entente expirerait **cinq jours
trop tôt** — cinq jours sans prise en charge.

### 3.3 Les statuts d'entente

| Statut             | Condition                                      |
| ------------------ | ---------------------------------------------- |
| ⚪ Sans entente     | aucune date d'accord saisie                    |
| 🟢 Valide          | échéance à plus de 30 jours                    |
| 🟠 À renouveler    | échéance dans 30 jours ou moins (jour compris) |
| ⛔ Expirée         | échéance dépassée                              |

**Le délai d'alerte est de 30 jours** — le temps de revoir le médecin, de
refaire la demande et d'attendre la réponse de la caisse. Il est réglable
dans la barre latérale : si la caisse répond vite, 30 jours encombrent la
liste.

Le **jour de l'échéance compte encore** : « expire aujourd'hui » et
« a expiré hier » n'appellent pas le même geste.

### 3.4 La facturation

La location se facture **tous les mois**.

| Statut                | Condition                                      |
| --------------------- | ---------------------------------------------- |
| ⚪ Jamais facturée     | aucune date de facturation                    |
| 🟢 À facturer         | un mois au moins s'est écoulé                  |
| 🟡 À jour             | le mois n'est pas encore échu                  |
| ✅ Réglé              | **achat** déjà facturé — terminé               |

**Les mois dus sont comptés**, pas seulement signalés. Une location
facturée en janvier et oubliée jusqu'en avril, ce sont **trois** mois dus.
Afficher « à facturer » sans le nombre ferait encaisser un mois et croire
le dossier à jour.

### 3.5 Ce que l'achat réglé ne fait plus

Une fois l'achat facturé :

- il **sort des facturations** — l'y laisser ferait facturer deux fois le
  même fauteuil ;
- il **sort des renouvellements** — le matériel est payé, il est au
  patient ; son entente a servi et peut expirer sans que personne n'ait
  rien à faire. L'y laisser noierait les vraies échéances sous des
  dossiers clos.

Tant qu'il **n'est pas** facturé, en revanche, son entente doit rester
valide : c'est elle que la caisse contrôlera le jour du règlement.

---

## 4. L'écran

### 4.1 Quatre sous-onglets, dans l'ordre des questions

1. **✅ Ententes préalables** — laquelle est accordée, depuis quand,
   jusqu'à quand. Et le geste « l'accord est arrivé » : sa date, sa durée.
   La date saisie est celle de **l'accord**, pas celle de la demande —
   c'est d'elle que court la validité, et c'est elle que la caisse
   contrôlera.
2. **💰 Facturations** — ce qui est dû, et depuis combien de mois.
3. **🔁 À renouveler** — ce qui expire dans le délai d'alerte, les
   **expirées en tête** : elles ne sont plus prises en charge, chaque jour
   compte double.
4. **🛒 Achats** — leur propre liste, parce qu'ils ne se lisent pas comme
   une location : ni « prochaine facturation » ni « mois dus ». Montrer
   deux colonnes vides ferait douter d'une panne.

### 4.2 L'harmonisation par patient

- La colonne **Mode** figure dans **toutes** les listes. Sans elle, il
  faudrait retourner au tableau complet pour chaque patient — et c'est
  exactement le va-et-vient que ces vues évitent.
- Une **vue par patient** ouvre le tableau de référence : une ligne par
  personne, locations et achats confondus, avec ce qu'elle loue, ce
  qu'elle a acheté, ce qui presse et ce qui est dû.

  > Le patient au téléphone ne demande pas « où en est ma location de
  > lit » : il demande **où il en est**.

  Le **pire statut** de ses dossiers remonte sur sa ligne — si l'un de ses
  appareils n'est plus pris en charge, c'est ce qu'il faut voir. Les
  patients dont une entente est tombée passent en tête.
- « Mme DUPONT », « mme dupont » et « Mme Dupont » sont **la même
  personne**. Sans cette réduction, le même patient reviendrait en trois
  lignes, chacune avec sa moitié d'historique.

### 4.3 Le bandeau

Quatre nombres, visibles sans rien ouvrir : dossiers suivis (dont loués /
achetés), à renouveler, ententes expirées, à facturer (avec le total des
mois dus).

### 4.4 Le tableau de référence

Corrigeable à la main : dates, durées, mode. Le mode est une **liste
fermée** — « loc. », « LOCATION » ou « louée » tapés librement sortiraient
le dossier de son sous-onglet sans que rien ne le signale.

Ajout d'un dossier par le « + » de la dernière ligne, suppression par
sélection puis Suppr — la location est terminée, le matériel est revenu.

Le tableau ne devient modifiable que sur la liste **entière** : corriger
une vue filtrée réécrirait les dossiers en perdant les lignes masquées.

---

## 5. Contraintes techniques

### 5.1 Robustesse

- **Une date illisible ne doit jamais faire tomber l'écran.** Ces dossiers
  sont saisis à la main ; une faute de frappe ne peut pas priver toute la
  pharmacie de son outil. Les formats `jj/mm/aaaa`, `jj-mm-aaaa`,
  `jj.mm.aaaa`, `aaaa-mm-jj` et `jj/mm/aa` sont acceptés ; le reste est
  traité comme une case vide.
- Une date aberrante — « 1926 » pour « 2026 » — ne doit pas figer l'écran
  en comptant mille mois : le compte de retard est borné.
- Un fichier illisible n'empêche pas l'ouverture du module : on repart
  d'un dossier vide, l'ancien fichier reste sur le disque, et l'incident
  part au journal.

### 5.2 Travail à plusieurs postes

Les fichiers vivent sur le dossier partagé. Deux comptoirs peuvent
enregistrer au même instant : chaque écriture **relit le fichier sous
verrou**, applique le mouvement, puis réécrit. On n'écrase jamais la photo
prise à l'ouverture de la page.

Une correction du tableau complet est **refusée** si un autre poste a
modifié les dossiers pendant la saisie — plutôt qu'effacer son travail.

### 5.3 Données nominatives

`location.csv` porte des **noms de patients**. Il est dans `.gitignore`,
aux côtés de `commandes_speciales.csv` : il ne part jamais sur GitHub, et
il n'est pas remplacé par les mises à jour.

### 5.4 Isolation

Le module ne lit ni le cadencier, ni les ruptures, ni l'inventaire du
stock interne, ni les commandes spéciales. Il ne connaît que ses propres
dossiers, et n'importe que le service de stockage partagé — un test
d'architecture le vérifie à chaque exécution de la suite.

La logique (`location.py`) **n'importe pas Streamlit** : elle est donc
éprouvable sans navigateur, ce qui permet de la tester en moins d'une
seconde.

---

## 6. Ce qui est éprouvé

Chaque règle de ce document a son test. Au 18/09/2026 :

- **93 tests de logique** (`tests/test_location.py`) — calendrier,
  échéances, statuts, mois dus, modes, récapitulatif par patient,
  persistance, isolation ;
- **19 tests de navigateur** (`tests/test_interface.py`) — l'écran
  s'ouvre, les quatre sous-onglets y sont dans l'ordre, les listes
  contiennent ce qu'elles doivent et rien d'autre, les gestes
  enregistrent ;
- **vérification par mutation** : chaque règle est cassée volontairement,
  et l'on s'assure qu'au moins un test tombe. Un test qui survit à la
  mutation de la règle qu'il prétend garder ne garde rien.

---

## 7. Hors périmètre (assumé)

Ce que le module **ne fait pas**, et pourquoi :

- **Il ne calcule aucun montant.** Les tarifs CAFAT changent, varient par
  matériel et par convention ; un montant faux dans un outil est pire
  qu'un montant absent. Le module dit **quand** facturer et **combien de
  mois**, pas combien de francs.
- **Il ne transmet rien à la caisse.** Aucune télétransmission, aucun
  formulaire pré-rempli : le dossier se monte comme aujourd'hui, l'outil
  dit seulement qu'il est temps de le monter.
- **Il ne gère pas le parc matériel.** Quel lit précis est chez quel
  patient, son numéro de série, son entretien : ce n'est pas la question
  que ce module résout.
- **Il ne fait pas d'historique des ententes passées.** Une entente
  renouvelée remplace la précédente. Conserver la chaîne complète
  supposerait un second fichier et n'a jamais été demandé.

Ces quatre points sont des **décisions**, pas des oublis. Ils peuvent être
repris — chacun ajouterait une colonne ou un fichier, pas une refonte.
