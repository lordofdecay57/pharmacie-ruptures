# 🛏️ Cahier des charges — Module 5 « Location & achat »

**Ententes préalables CAFAT, matériel médical loué ou vendu au patient.**

Version 6.36 · Pharmacie de La Foa · Nouvelle-Calédonie

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

### 2.2 Les deux régimes : avec ou sans entente

Tout le matériel ne passe pas par la caisse.

| Régime | Matériel | Entente | Remboursement | Caution |
| --- | --- | --- | --- | --- |
| 📋 **Soumis à entente** | lit, VNI, concentrateur, fauteuil… | **oui** | selon l'accord | — |
| 🆓 **Sans entente requise** | **tensiomètre** | non | **non remboursé** | **3 000 F** |
| 🆓 **Sans entente requise** | **aérosol** | non | **remboursé sous conditions** | **5 000 F** |

Le régime **se propose d'après le nom du matériel** : taper « Tensiomètre
OMRON » ou « Aérosol Pari Boy » suffit — le régime bascule hors caisse et
la caution se remplit. La proposition reste modifiable ligne à ligne : un
cas qui sort de l'ordinaire doit pouvoir être reclassé.

> Mêlés aux dossiers soumis à entente, tensiomètres et aérosols
> s'afficheraient « rien de fait » à vie — c'est-à-dire comme un
> manquement. Ils n'en sont pas un. D'où leur **sous-onglet à part**.

Le défaut, quand le nom ne dit rien, est **« soumis à entente »** : le
régime surveillé. Un dossier classé hors caisse par erreur sortirait des
renouvellements sans que rien ne le signale, et l'entente expirerait en
silence. L'inverse n'ajoute qu'une ligne dans une liste.

Les montants sont ceux pratiqués à l'officine. Ils sont **proposés**, pas
imposés : un tarif qui change ne doit pas demander une nouvelle version du
programme.

### 2.3 Les deux modes

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

### 2.4 Ce qui est saisi, et ce qui se déduit

**Saisi** (et donc corrigeable) : patient, matériel, mode, régime, début
de fourniture, **date d'envoi de la demande**, **prénom de qui l'a
envoyée**, date de l'accord, durée de validité en mois, date de la
dernière facturation, **montant de la caution**, **date de restitution de
la caution**, **commentaire sur l'entente**, notes.

**Déduit** (et donc jamais stocké) : l'échéance, les jours qui en
restent, le statut de l'entente, les jours d'attente d'une réponse, la
prochaine facturation, les mois dus, le statut de facturation, le régime
proposé par le nom du matériel, les conditions de remboursement, le total
des cautions détenues.

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

### 3.3 La demande, et sa traçabilité

**Il y a une demande d'entente préalable à effectuer**, et elle précède
l'accord de plusieurs semaines. Elle porte deux choses :

- **la date d'envoi** à la caisse ;
- **le prénom de la personne de la pharmacie qui l'a envoyée**.

> Le prénom n'est pas une formalité. Trois semaines plus tard, quand la
> caisse n'a toujours pas répondu, c'est la seule façon de savoir à qui
> demander ce qui a été envoyé — et si ça l'a vraiment été.

Il est **obligatoire** : le module refuse d'enregistrer une demande sans
lui. La liste des prénoms **se remplit toute seule** à partir de ceux déjà
saisis — personne n'a d'annuaire à tenir à jour — et reste ouverte : un
remplaçant d'un après-midi ne doit pas être un obstacle.

Tant que la caisse n'a pas répondu, le dossier figure dans une **liste de
relances**, les plus anciennes en tête, avec le nombre de jours d'attente.

Un **commentaire d'entente** accompagne le dossier : relance, pièce
manquante, refus, numéro de dossier CAFAT. Il est **séparé des notes** de
la location — celles-ci décrivent le matériel et sa livraison, celui-là
raconte le dossier auprès de la caisse. Mélangés, on ne retrouve ni l'un
ni l'autre trois mois plus tard.

### 3.4 Les statuts d'entente

| Statut                      | Condition                                      |
| --------------------------- | ---------------------------------------------- |
| 🆓 Non requise              | régime « sans entente » (tensiomètre, aérosol) |
| ⚪ Rien de fait             | aucune demande envoyée, aucun accord           |
| 📨 Demande envoyée          | demande partie, réponse attendue               |
| 🟢 Valide                   | échéance à plus de 30 jours                    |
| 🔔 Dernier mois couvert     | la facturation suivante tomberait après l'échéance |
| 🟠 À renouveler             | échéance dans 30 jours ou moins (jour compris) |
| ⛔ Expirée                  | échéance dépassée                              |

> « Rien de fait » et « demande envoyée » ne se confondent plus.
> Auparavant, un dossier parti à la caisse se lisait comme un dossier
> oublié — et on le refaisait.

**Le délai d'alerte est de 30 jours** — le temps de revoir le médecin, de
refaire la demande et d'attendre la réponse de la caisse. Il est réglable
dans la barre latérale : si la caisse répond vite, 30 jours encombrent la
liste.

Le **jour de l'échéance compte encore** : « expire aujourd'hui » et
« a expiré hier » n'appellent pas le même geste.

### 3.5 La facturation

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

### 3.6 Le renouvellement proposé au dernier mois

**Au moment de la facturation du dernier mois couvert, le module propose
de renouveler le dossier d'entente préalable.**

Le dossier est « au dernier mois » quand **la facturation suivante
tomberait après l'échéance** : il n'y aura donc pas de mois d'après à
facturer sous cet accord.

C'est le moment utile, et il est choisi pour une raison :

- la **facturation est le seul geste mensuel certain** sur une location.
  C'est là qu'on tient le dossier en main, le patient identifié, la
  question fraîche ;
- attendre l'échéance, c'est la découvrir **une fois passée** ;
- prévenir plus tôt, c'est prévenir **tous les mois pour rien**, et une
  alerte permanente ne s'alerte plus de rien.

La proposition s'affiche **immédiatement après la facturation qui l'a
déclenchée**, en haut de l'écran, et la demande de renouvellement part de
là — avec sa date et son prénom, comme la première. Elle se refuse d'un
clic : la location s'arrête parfois là, et forcer une demande ferait
partir un dossier pour un lit déjà repris.

Ce signal passe **devant** le compte à rebours des 30 jours : le délai
d'alerte est réglable, et réglé court il ferait manquer le seul moment où
le dossier était ouvert. Un dossier au dernier mois figure donc dans
« à renouveler » quel que soit ce réglage.

Un **achat** n'a pas de mois suivant : la question ne se pose pas.

### 3.7 Ce que l'achat réglé ne fait plus

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

### 4.1 Cinq sous-onglets, dans l'ordre des questions

1. **✅ Ententes préalables** — le parcours complet : les demandes parties
   sans réponse en tête, puis toutes les ententes. Trois gestes distincts
   sur le dossier choisi — **📨 demande envoyée** (date + prénom),
   **✅ accord reçu** (date + durée), **💬 commentaire**. Trois et non un :
   ils n'arrivent pas le même jour, et un bouton unique obligerait à
   ressaisir ce qui est déjà su.

   « Demandé le » est la date d'**envoi** ; « Entente faite le » celle de
   l'**accord** — c'est de cette dernière que court la validité, et c'est
   elle que la caisse contrôlera.
2. **💰 Facturations** — ce qui est dû, et depuis combien de mois.
3. **🔁 À renouveler** — ce qui expire dans le délai d'alerte, les
   **expirées en tête** : elles ne sont plus prises en charge, chaque jour
   compte double.
4. **🛒 Achats** — leur propre liste, parce qu'ils ne se lisent pas comme
   une location : ni « prochaine facturation » ni « mois dus ». Montrer
   deux colonnes vides ferait douter d'une panne.
5. **🆓 Sans entente** — aérosols et tensiomètres. Ni échéance ni
   renouvellement : ce qui compte est la **caution** et ce que la caisse
   fait de l'appareil. Le total détenu est affiché, et la restitution
   s'enregistre d'un clic.

   > Une caution est de l'argent encaissé qui **appartient au patient**
   > tant qu'il n'a pas rendu l'appareil. Cet argent n'est pas à la
   > pharmacie : il est chez elle. Ne pas le suivre, c'est laisser 5 000 F
   > dans la caisse de quelqu'un d'autre.

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

### 4.3 Le bandeau — quatre tuiles, pas six

Six tenaient sur deux rangées, la sixième s'étirant seule sur toute la
largeur. **Une rangée qui déborde ne se lit plus d'un coup d'œil**, ce qui
est pourtant tout ce qu'on demande à un bandeau.

Les quatre retenues sont celles qui appellent un **geste** :

| Tuile | Seconde ligne |
| --- | --- |
| Dossiers suivis | loués · achetés · hors caisse |
| 📨 Demandes en attente | parties, sans réponse de la caisse |
| 🔁 À renouveler | dont N au dernier mois · N expirée(s) |
| 💰 À facturer | N mois dus · N F de cautions |

Ce qui les précise tient sur leur seconde ligne, où l'on n'a rien à
décider.

### 4.4 Ouvrir un dossier : trois champs

**Patient · Matériel · Mode.** Rien d'autre à l'écran.

Onze champs tenaient ici, et c'était onze de trop. **Dix des onze se
saisissent plus tard**, chacun par son propre geste : la demande dans
l'onglet des ententes, l'accord juste à côté, la facturation dans le sien,
la caution dans celui du hors-caisse. Les demander à l'ouverture, c'était
réclamer d'avance ce que la pharmacie apprendra dans les semaines qui
viennent — et noyer les trois seules réponses qu'elle a vraiment : **qui,
quoi, loué ou acheté**.

Le régime et la caution ne sont pas demandés du tout : ils se proposent
d'après le nom du matériel. Le début de location, laissé vide, vaut
aujourd'hui — un dossier s'ouvre le jour où le matériel part chez le
patient, neuf fois sur dix.

Le reste reste accessible, **replié**, pour le seul cas qui le justifie :
reprendre une location commencée avant l'arrivée de l'outil.

### 4.5 Ce qui est replié

Chaque sous-onglet montre **ce qui appelle un geste**, et replie ce qui
répond à « montre-moi tout » :

- les ententes montrent les **relances** ; la liste entière est dans un
  dépliant ;
- les facturations montrent ce qui est **dû** ; le reste est dans un
  dépliant ;
- les achats montrent ceux **à régler**, puis tous ;
- le hors-caisse montre les **cautions détenues**.

Le tableau de référence en bas d'écran répond déjà à « montre-moi tout » :
le dupliquer dans chaque onglet poussait le geste hors de l'écran.

### 4.6 Le tableau de référence

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

Chaque règle de ce document a son test. Au 22/09/2026 :

- **127 tests de logique** (`tests/test_location.py`) — calendrier,
  échéances, statuts, demande et traçabilité, dernier mois couvert,
  régimes, cautions, mois dus, modes, récapitulatif par patient,
  persistance, isolation ;
- **39 tests de navigateur** (`tests/test_interface.py`) — l'écran
  s'ouvre, les cinq sous-onglets y sont dans l'ordre, les listes
  contiennent ce qu'elles doivent et rien d'autre, les gestes
  enregistrent, la proposition de renouvellement naît de la facturation
  et se refuse ;
- **vérification par mutation** : chaque règle est cassée volontairement,
  et l'on s'assure qu'au moins un test tombe. Un test qui survit à la
  mutation de la règle qu'il prétend garder ne garde rien.

---

## 7. Hors périmètre (assumé)

Ce que le module **ne fait pas**, et pourquoi :

- **Il ne calcule aucun tarif de prise en charge.** Les tarifs CAFAT
  changent, varient par matériel et par convention ; un montant faux dans
  un outil est pire qu'un montant absent. Le module dit **quand** facturer
  et **combien de mois**, pas combien de francs la caisse versera. Les
  seuls montants qu'il tient sont les **cautions**, parce que ce sont des
  sommes fixes encaissées à l'officine — et elles restent modifiables.
- **Il ne transmet rien à la caisse.** Aucune télétransmission, aucun
  formulaire pré-rempli : le dossier se monte comme aujourd'hui, l'outil
  dit seulement qu'il est temps de le monter.
- **Il ne gère pas le parc matériel.** Quel lit précis est chez quel
  patient, son numéro de série, son entretien : ce n'est pas la question
  que ce module résout.
- **Il ne fait pas d'historique des ententes passées.** Une entente
  renouvelée remplace la précédente ; le commentaire d'entente permet d'en
  garder la trace en clair. Conserver la chaîne complète supposerait un
  second fichier.
- **Il ne suit pas les conditions de remboursement de l'aérosol.** La
  caisse le rembourse « sous conditions » — le module le dit, il ne juge
  pas si elles sont remplies. Inscrire ces conditions dans le programme,
  c'est se tromper le jour où elles changent.

Ces quatre points sont des **décisions**, pas des oublis. Ils peuvent être
repris — chacun ajouterait une colonne ou un fichier, pas une refonte.
