# Utiliser le suivi Location — version 6.38

Cette version remplace l'écran Location dans l'application Streamlit.
Les fichiers HTML du dossier `maquettes` ne sont pas nécessaires pour l'utiliser.
Le numéro **6.38** doit apparaître en haut de l'utilitaire après mise à jour et
redémarrage du serveur. Une actualisation du navigateur seule ne met pas le
programme à jour.

## Au comptoir

1. Renseigner **Votre nom** dans la barre latérale, puis ouvrir un dossier.
2. Choisir le matériel, Location ou Achat, le début réel et le rythme de
   préparation des factures. Le fauteuil propose Achat en premier.
3. Dans **Dossiers patients**, préciser la prise en charge : À vérifier,
   Remboursable ou Non remboursable. Consigner le motif, les conditions
   vérifiées et la prescription. Un aérosol n'est jamais classé automatiquement
   comme remboursable du seul fait de sa catégorie.
4. Dans **Facturation**, choisir le dossier. Renseigner d'abord la **date de
   demande d'entente préalable** et le **membre de l'équipe ayant initié la
   demande**, puis le canal et la référence. La date est celle de l'envoi réel,
   laissée vide jusqu'à sa saisie. Les demandes déjà enregistrées restent
   visibles, sans ressaisie. L'initiateur peut être différent de la personne
   qui enregistre le dossier. À réception, saisir la référence et les dates
   de couverture figurant sur l'accord. Chaque renouvellement garde son auteur.
5. **À faire** présente les périodes prêtes. Dans **Facturation**, après création
   de la facture dans le logiciel métier, enregistrer sa référence, sa date et
   son montant. L'entente correspondant à cette période est rappelée avant
   validation ; une demande de renouvellement ne remplace pas son historique.
   Le règlement s'enregistre séparément dans **Historique de toutes les factures
   et règlements**. Les dossiers non remboursables n'exigent pas de demande
   d'entente dans ce suivi.

Les mensualités suivent le début de la prestation, même si une facture est
enregistrée tardivement. Une période déjà facturée ne peut pas être facturée
une deuxième fois. Une dernière période de couverture affiche une alerte et
demande une confirmation avant enregistrement. L'alerte reste après la
facturation et après l'envoi de la demande, jusqu'à la couverture suivante.

Le rythme mensuel, hebdomadaire ou de 28 jours organise les échéances de
travail ; il ne détermine pas un tarif ni une règle CAFAT. Les montants,
conditions particulières, unités et périodes partielles restent à vérifier
dans le logiciel métier. Aucun taux de remboursement n'est déduit du statut
« Remboursable ». Les cas de rupture de couverture restent signalés.

## Locations privées, cautions et retours

Tout se trouve dans le même module. À la création d'une location :

| Matériel | Caution proposée |
| --- | ---: |
| Aérosol | 5 000 F CFP |
| Tensiomètre | 3 000 F CFP |

La modalité est **Chèque** ou **Espèces**. Le choix du moyen de règlement ne
marque pas la caution comme reçue. Sa réception, avec référence et auteur,
est une opération distincte. Un chèque reçu est suivi comme conservé non encaissé.

Le retour physique s'enregistre même en présence d'une anomalie. Il ne
restitue pas la caution et ne modifie pas les factures déjà émises. Une facture
couvrant une date après le retour est signalée pour régularisation.
Après restitution effective du chèque ou remboursement des espèces, confirmer
l'opération. Les retenues partielles et encaissements de chèques de caution
ne sont pas automatisés dans cette version.

Un appareil identifié ne peut pas être attribué simultanément à deux dossiers.
Au retour, il passe « À préparer ». Un contrôle explicite le remet disponible.

## Reprendre les dossiers existants

Au premier affichage, les lignes de `location.csv` sont reprises une seule fois
dans `locations_suivi.json`. Le CSV d'origine est conservé sans modification,
et chaque ligne d'origine reste consultable. Le nouveau fichier devient la
référence du suivi ; ne pas reprendre la saisie dans une ancienne version.

Une ancienne « Dernière facturation » ne permet pas de savoir quelle prestation
était couverte. Chaque dossier apparaît donc **à vérifier**, sans génération
de rattrapage. Indiquer le début réel, la première période encore non facturée
et la référence de la vérification. Pour un achat déjà facturé, cocher l'option
prévue : aucune nouvelle facture n'est créée et le règlement historique reste
consultable dans le logiciel métier d'origine.

La qualification de la prise en charge et les dates d'accord restent à
vérifier ; les anciennes durées ne deviennent pas automatiquement une nouvelle
couverture. Aucune caution n'est supposée reçue sur un ancien dossier.

Les écritures sont verrouillées entre postes, atomiques, et précédées d'une
copie `.bak` de la dernière version lisible. Les exports et sauvegardes se
trouvent dans Facturation et Réglages. Ils contiennent des données patients.

## Activer les rappels mail

Le moteur d'envoi est installé mais **désactivé par défaut**. Dans
**Location → Réglages & essai → Rappels par mail**, saisir l'adresse de la
pharmacie communiquée au responsable, les jours et l'heure locale souhaités.
La configuration reste sur le serveur dans `rappels_location.local.json`,
exclu de Git et protégé des mises à jour.

Le responsable du serveur doit aussi fournir :

- l'adresse d'expéditeur autorisée par son service d'envoi ;
- le serveur SMTP, le port et SSL ou STARTTLS ;
- l'identifiant SMTP si nécessaire ;
- le secret dans la variable d'environnement **PHARMACIE_SMTP_PASSWORD** du
  processus qui lance l'application. Ne pas le mettre dans le dépôt ni dans
  une capture d'écran des postes. Pour un compte nécessitant un secret
  d'application, utiliser celui fourni par le service d'envoi.

Activer ensuite la case d'envoi et enregistrer. Un travailleur démarre lors de
la première ouverture de l'application après le lancement du serveur et
continue tant que le processus Streamlit tourne. Le serveur doit rester allumé.
Une autre possibilité, pour un administrateur, consiste à planifier
`python rappels_location.py` sur ce même serveur ; la protection commune
contre les doublons couvre les deux modes de lancement.

Le récapitulatif indique le nombre de périodes à facturer, les dossiers à
compléter et les renouvellements. Il ne contient pas de nom de patient,
ne crée pas de facture et n'envoie pas d'entente à la CAFAT. Il ne part pas
s'il n'y a rien à rappeler. Les périodes déjà facturées sont exclues.

Un seul essai d'envoi est autorisé par jour dans le fuseau de Nouvelle-Calédonie.
En cas de coupure ou d'échec SMTP, le journal affiche un résultat à vérifier :
aucune relance aveugle le même jour, car le serveur destinataire peut avoir
accepté le mail malgré une coupure. L'équipe doit contrôler le résultat.
Le prochain jour programmé reprend le récapitulatif des tâches restantes.

## Essai sans modifier les dossiers

Dans Réglages, **Essayer le scénario du matelas à air** affiche un patient
fictif, une demande envoyée 15 jours auparavant, reçue 2 jours auparavant et
six périodes mensuelles. Le début de couverture est une hypothèse affichée.
Le sixième mois porte l'alerte de renouvellement. Aucun dossier patient réel
ni mail n'est créé par cet essai.

## Limites de cette version

Les factures officielles restent produites et corrigées dans le logiciel
métier. Le suivi ne calcule pas les tarifs CAFAT, paliers fauteuils, observance
respiratoire, prorata, reste à charge ni prestations annexes. Il ne génère pas
de contrat ou de télétransmission. Les prolongations modifiant des périodes
déjà facturées et les interruptions complexes doivent être traitées après
revue du dossier ; aucune modification automatique des anciennes factures.

Le passage du dépôt GitHub en privé nécessite aussi de prévoir un accès
authentifié pour les mises à jour : les anciennes URL de téléchargement public
ne suffisent plus. La visibilité du dépôt n'est pas changée par cette version.
