# Locations et achats : une facturation simple, adaptée à la CAFAT

Proposition fonctionnelle pour `pharmacie-ruptures` · 20 septembre 2026

**Le changement essentiel : suivre les périodes de location couvertes par chaque facture, puis préparer les lignes admissibles selon le matériel et le dossier.** Le mois peut rester le rythme de travail de l’équipe ; il ne doit pas déterminer arbitrairement l’unité tarifaire.

Ce document conserve la proposition de conception. Depuis la **version 6.36**, le suivi des périodes, les ententes datées et leur initiateur, la prise en charge à vérifier, les cautions, retours, factures et rappels configurables sont intégrés à l'utilitaire. Le [guide de la version 6.36](location-6.36.md) décrit précisément ce qui fonctionne et ses limites. Les profils tarifaires, retenues de caution, contrats complets et calculs CAFAT automatisés restent à développer après validation métier.

**Préférence de l’officine : privilégier l’achat pour les fauteuils.** À la création d’un dossier fauteuil, proposer « Achat » en premier. La prescription et l’accord doivent correspondre à ce mode. Conserver « Location temporaire » comme autre possibilité, sans abonnement mensuel créé par défaut pour un achat.

## Ce que les documents officiels apportent

### Accords et prise en charge

La circulaire du 5 décembre 2023, jointe au rappel du 18 février 2025, prévoit un accord préalable dès la première semaine pour les locations de lits, matelas à air, fauteuils et verticalisateurs, indépendamment du montant. Certaines autres catégories bénéficient d’un accord réputé acquis, notamment les appareils d’aérosols. Le document distingue aussi les situations ouvrant le remboursement CAFAT : rattachement à une longue maladie, maladie longue et coûteuse, hospitalisation, certains actes ou accident du travail/maladie professionnelle. La présence d’un article dans la LPPR ne suffit donc pas à établir la couverture du patient. [CAFAT, circulaire 2025/132 et annexe 2023/673](https://www.cafat.nc/wp-content/uploads/2025-132_LC_Rappel-des-modalites-de-PEC-des-articles-et-prestations-de-la-LPPR.pdf).

**Conséquence proposée :** des profils par catégorie, une prescription, le fondement de prise en charge et, lorsqu’il est requis, un accord documenté couvrant les dates concernées. Une demande envoyée ne vaut pas accord reçu. Le logiciel ne doit pas déduire une autorisation du seul écoulement du temps.

### Fauteuils roulants

Le document CAFAT daté du 2 février 2026 privilégie la prescription d’achat pour un besoin supérieur à six mois. Pour la location courte, il décrit un palier initial de 13 semaines puis un palier dégressif jusqu’à 26 semaines. Au-delà, il prévoit des parcours particuliers, dont une prolongation exceptionnelle de trois mois avec demande d’accord préalable. Il traite également les dossiers anciens et leurs transitions ; leur ancienneté ne doit pas être remise à zéro. La CAFAT présente ces indications comme provisoires, dans l’attente des travaux de la DASS. [CAFAT, document publié sous 2026/113, pages 1–6](https://www.cafat.nc/wp-content/uploads/2026-113_LC_Modifications-des-modalites-de-prise-en-charge-des-articles-etr-prestations-de-la-LPPR.pdf).

**Conséquence proposée :** un compteur de semaines depuis le début réel, une alerte avant changement de palier et un profil réglementaire daté, modifiable après vérification. Une situation ancienne ou dérogatoire exige une revue dédiée avant calcul automatique.

**Parcours fauteuil privilégié par l’officine :** prescription d’achat → devis et accord appropriés → délivrance → facture unique → suivi du règlement. Les prestations annexes ne sont ajoutées que si elles sont applicables et documentées. Un fauteuil acheté ne crée aucune échéance récurrente de location. « Facturé » et « Réglé » restent deux états distincts.

Un dossier actuellement loué peut afficher « Examiner l’achat » ; cette action ouvre une revue du dossier. Elle ne transforme pas les anciennes factures, ne suppose pas une prise en charge de l’achat et ne clôt pas la location tant que l’événement correspondant n’est pas enregistré. Une option d’achat après location et un achat initial doivent garder des profils distincts, notamment en présence d’une dérogation.

### Assistance respiratoire

La circulaire PPC du 15 mars 2024 décrit des forfaits dépendant de la phase de traitement, du télésuivi et de l’observance, avec des périodes de 28 jours pour les évaluations concernées. Elle prévoit la suspension de prise en charge pendant l’hospitalisation, du jour d’entrée à la veille du retour au domicile, puis la reprise des périodes en cours. [CAFAT, circulaire 2024/168](https://www.cafat.nc/wp-content/uploads/2024-168_LC_Rappel-des-regles-de-facturation-de-la-PPC.pdf).

**Conséquence proposée :** conserver un profil respiratoire séparé ; ne pas lui appliquer le calcul des lits ou des fauteuils. N’activer son calcul qu’après validation de toutes ses règles et données nécessaires. Le formulaire générique d’assistance respiratoire ne remplace pas les règles particulières à chaque traitement.

### Tarifs et références

La fiche CAFAT « Produits divers », datée du 22 février 2022 et toujours proposée sur la page fournisseurs consultée, différencie notamment oxygénothérapie, fabrication locale et matériel importé. Elle utilise des coefficients de tarification propres aux catégories. Ce n’est pas une simple conversion monétaire. Son ancienneté nécessite de confirmer son application aux codes et dates utilisés. [CAFAT, tarifs produits divers](https://www.cafat.nc/wp-content/uploads/Tarifs-PRODUITS-DIVERS.pdf).

**Conséquence proposée :** enregistrer, pour chaque tarif validé, le code, la désignation, l’unité, le montant en F CFP, la période d’application et la source. Séparer prix facturé, base de remboursement et part CAFAT ; ne pas présumer une prise en charge à 100 %. Une mise à jour ne recalcule jamais silencieusement une facture passée.

## Le parcours quotidien

Trois vues suffisent : **À traiter · En cours · Historique**. La première rassemble factures, pièces manquantes, retours et cautions à rendre. Un filtre **Tous / Prise en charge / Privé** adapte la liste. Le patient, le matériel, le mode, la période de location ou la date de délivrance et l’action utile restent sur la même ligne.

1. L’équipe choisit une date d’arrêté, proposée automatiquement à partir de son rythme habituel.
2. L’utilitaire recherche les périodes échues encore non facturées et applique le profil du matériel.
3. Les dossiers incomplets affichent la cause précise : accord, prescription, droits, tarif ou situation particulière à vérifier.
4. « Préparer » ouvre un récapitulatif : dates de prestation, unités, tarif applicable, montant et pièces de référence.
5. Après émission dans le logiciel métier, l’équipe enregistre la référence de facture. La période couverte passe dans l’historique.

Pour un achat de fauteuil, le même écran prépare une délivrance unique. Il ne calcule pas de « prochain mois à facturer ».

Le récapitulatif est un support de préparation : il ne vaut ni télétransmission CAFAT ni facture réglementaire. Ce choix conserve la simplicité de l’utilitaire et évite de ressaisir toute la facturation de l’officine.

Les réglages réglementaires apparaissent dans le détail du dossier. Au comptoir, l’utilisateur voit surtout « Prêt », « Pièce manquante » ou « Situation à vérifier ». La maquette utilise des patients et tarifs fictifs, clairement signalés.

## Équipe : qui a initié l’entente ?

Ajouter **« Demande initiée par »**, obligatoire pour chaque nouvelle demande d’entente et chaque renouvellement. Utiliser une liste des membres de l’équipe, avec un identifiant stable ; conserver le nom affiché dans l’historique même après le départ d’un collaborateur. Pour un ancien dossier, afficher « Non renseigné » tant que l’information n’a pas été retrouvée, sans attribuer rétroactivement un nom.

L’initiateur, l’auteur de l’envoi et le référent actuel du dossier peuvent être différents. Afficher surtout l’initiateur sur la fiche ; placer les autres détails dans l’historique. Chaque action mémorise sa date et son auteur : envoi, relance, accord enregistré, facture, remise, retour et mouvement de caution. Si l’application ne dispose pas de comptes individuels, proposer une sélection du membre de l’équipe au début de la session et préciser qu’il s’agit d’une attribution déclarative.

Exemple conservé : matelas à air, demande du 05/09/2026 initiée et envoyée par Camille, accord du 18/09 enregistré par Alex. Un renouvellement initié par Alex ne remplace jamais Camille dans la demande initiale. L’alerte reste collective et visible dans « À traiter », même si l’initiateur est absent.

## Locations privées : intégrées au même module

Conserver un seul dossier patient et un seul parc de matériels. Le financement (**prise en charge / privé**) et le mode (**location / achat**) sont des informations distinctes. La caution est une option du contrat, indépendante du financement. Cela évite deux listes concurrentes et permet de voir immédiatement quels appareils sont sortis.

À la création, sélectionner le matériel, puis le financement. Pour une location privée de tensiomètre ou d’aérosol, masquer les champs d’entente non pertinents et afficher seulement : patient et contact utile, appareil identifié, date de départ, retour prévu, tarif convenu et caution éventuelle. Enregistrer aussi les accessoires remis. Les tarifs sont des réglages de l’officine, jamais déduits des tarifs CAFAT. Les conditions de durée, de retard, de retour anticipé et d’arrondi doivent être explicites avant le calcul ; aucun supplément automatique fondé sur une règle implicite.

Pour chaque location d’aérosol, afficher explicitement **« Remboursable / Non remboursable / À vérifier »**. Le statut porte sur le dossier du patient et les conditions applicables, jamais sur tous les aérosols. Un nouveau dossier commence à « À vérifier ». Le détail conserve les conditions vérifiées ou le motif de non-prise en charge, la référence du justificatif et la personne/date de vérification. « Remboursable » décrit l’éligibilité ; le paiement effectif reste un suivi distinct et le taux n’est pas présumé égal à 100 %.

Tant que le statut reste « À vérifier », autoriser l’enregistrement et le suivi du matériel, sans sélectionner automatiquement le parcours de facturation CAFAT ou privé. Après vérification, présenter les champs du parcours approprié. Une correction du statut conserve les anciennes factures et opérations de caution ; toute régularisation est explicite. L’accord réputé acquis mentionné dans l’annexe CAFAT 2023/673 citée plus haut ne dispense pas de vérifier les conditions de prise en charge.

**Montants de caution fixés par l’officine : aérosol 5 000 F CFP ; tensiomètre 3 000 F CFP.** Préremplir le montant à la sélection du matériel, indépendamment du statut de remboursement. Ces montants proviennent des instructions de l’utilisateur et ne sont pas des tarifs CAFAT. À la création, la caution est « À recevoir » ; sa réception puis sa restitution nécessitent leurs propres enregistrements. Le montant convenu reste attaché au contrat même si le paramétrage du matériel change ensuite. Le prix de location demeure un montant distinct, à renseigner selon le parcours et les conditions applicables.

### Deux gestes principaux

1. **Remettre le matériel** : réserver un appareil disponible, confirmer les dates et conditions, enregistrer le règlement de location et la réception de la caution, puis garder une référence de reçu/contrat. Identifier la personne de l’équipe qui effectue la remise.
2. **Enregistrer le retour** : saisir la date réelle et l’état des accessoires/appareil, arrêter la location selon ses conditions, régler le solde éventuel et suivre la restitution de caution. Une anomalie ne doit pas empêcher d’enregistrer le retour physique.

Suivre le paiement de location et la caution séparément. Afficher le champ **« Modalité de règlement de la caution »**, avec les deux moyens prévus : **Chèque** ou **Espèces**. À la préparation du dossier, laisser « À préciser » tant que le choix n’est pas connu ; le renseigner lors de la réception effective. Pour la caution, mémoriser montant, modalité, référence, date et auteur. Distinguer **chèque conservé non encaissé**, **espèces reçues**, **restitution/remboursement à effectuer**, puis **restituée/remboursée**. Rendre un chèque et rembourser de l’argent sont deux opérations différentes. Ne jamais additionner automatiquement la caution au revenu de location dans les indicateurs. Le choix de la modalité ne marque pas, à lui seul, la caution comme reçue.

Une retenue éventuelle demande une décision explicite et documentée, avec motif, montant retenu, montant rendu et justificatif. Ne pas encaisser automatiquement un chèque conservé ni retenir la caution au seul motif d’un retard. Ces possibilités restent à cadrer dans les conditions de location de l’officine ; cette proposition ne détermine pas leur régime juridique.

### Alertes et disponibilité

- Retour dépassé : « Matériel à récupérer », avec contact et référent.
- Appareil rendu mais caution non restituée : « Caution à rendre », jusqu’à l’opération effective.
- Loyer restant à régler : tâche distincte du suivi de caution.
- Retour avec anomalie : dossier ouvert pour décision ; appareil indisponible.

Un dossier financier ne se clôt que lorsque le matériel est rendu, la location soldée et la caution traitée. L’appareil reste séparément « À préparer / À contrôler » jusqu’à sa remise à disposition. Empêcher la double attribution d’un même appareil. Les essais illustrent le retour conforme, les deux modes de caution et la qualification de la prise en charge ; les retenues, prolongations et contrats complets restent des parcours à construire. Les cautions paramétrées sont celles fixées par l’officine ; les loyers illustratifs ne sont pas des tarifs validés.

## Les contrôles à construire

| Situation | Comportement proposé |
| --- | --- |
| Facture établie tardivement | Garder ses dates de prestation ; sa date d’émission ne décale pas les prochaines périodes. |
| Plusieurs périodes impayées ou omises | Distinguer période jamais facturée et facture déjà émise non réglée. |
| Période déjà couverte | Refuser un chevauchement sur le même dossier et la même prestation ; proposer la correction de la facture existante. |
| Accord expirant pendant une période | Séparer les segments à examiner. Ne pas inventer de prorata pour une unité indivisible ou une semaine partielle. |
| Retour ou interruption | Enregistrer l’événement daté ; proposer l’arrêt ou la suspension selon le profil applicable. |
| Changement de tarif | Découper selon la date d’effet lorsque la règle l’autorise, et conserver les valeurs utilisées. |
| Rejet CAFAT | Garder la facture d’origine, le motif et le lien vers la régularisation ; ne pas recréer une période comme si elle n’avait jamais été facturée. |
| Accord sans dates certaines | Laisser le dossier à compléter ; ne pas ajouter automatiquement six mois. |

## Évolution des données

La colonne actuelle « Dernière facturation » ne permet pas de retrouver les prestations couvertes. Prévoir progressivement :

- Un identifiant stable de dossier, le début réel, le retour et les interruptions.
- Les prescriptions et accords successifs, avec références et dates de couverture explicites.
- Un profil de matériel et des tarifs versionnés.
- Un journal des factures et lignes : référence, émission, début/fin de prestation, unités, valeurs tarifaires conservées, état de transmission, paiement et corrections.

La date « facturé jusqu’au » doit être calculée à partir de périodes continues réellement couvertes. Prendre simplement la date de fin la plus récente masquerait un trou de facturation.

Pour reprendre les anciens CSV, conserver toutes les valeurs d’origine et demander une vérification de la couverture réelle à partir des factures existantes. Ne jamais assimiler automatiquement l’ancienne date de facturation à une fin de prestation. Aucun dossier historique ne doit produire de rattrapage automatique avant cette reprise.

## Ordre de réalisation

### Rappel mail des facturations à préparer

Demande de l’officine : envoyer un rappel des facturations à générer à l’adresse destinataire communiquée par la pharmacie le 20 septembre 2026. Cette adresse sera renseignée dans la configuration privée du serveur, sans être publiée dans ce dépôt public ; elle ne définit pas l’expéditeur. **Le destinataire a été communiqué, mais aucun service d’envoi ni planning n’est configuré actuellement.** La version 6.35 ne contient pas encore de moteur d’envoi.

Prévoir un récapitulatif unique des tâches de facturation encore ouvertes, à une fréquence et une heure configurables dans le fuseau Pacific/Noumea. Une proposition simple est un envoi quotidien les jours choisis par l’équipe, uniquement s’il reste quelque chose à traiter. Le mail rappelle les facturations à préparer ; il ne crée ni ne transmet de facture.

Séparer dans le récapitulatif les facturations prêtes et les dossiers à compléter. Faire apparaître les derniers mois nécessitant un renouvellement. Une facture déjà enregistrée ne revient plus comme nouvelle facture à générer. La date d’échéance provient du dossier, jamais de la date d’envoi du rappel. Par défaut, le mail contient les nombres de dossiers et les actions à effectuer, avec un accès à l’application si son adresse est configurée ; les informations nominatives restent dans l’utilitaire.

Exemple de message, sans données patient :

> Objet : Pharmacie — 3 facturations à préparer
>
> 3 dossiers de location sont à facturer. Parmi eux, 1 arrive au dernier mois de prise en charge : renouvellement à préparer.
> 2 autres dossiers nécessitent une vérification avant facturation.
> Ouvrez le module Location pour consulter les périodes et enregistrer les factures émises.

Prévoir une activation explicite après configuration privée du destinataire communiqué, de l’expéditeur et du service d’envoi. Les identifiants d’envoi restent dans la configuration locale du serveur, hors du dépôt Git. Exécuter la tâche sur un seul serveur, avec un journal d’envoi partagé pour éviter les doublons entre postes. Conserver la date du dernier envoi réussi et les erreurs ; limiter les nouvelles tentatives après échec et empêcher plusieurs envois simultanés du même rappel. L’envoi d’un rappel ne modifie jamais les factures, les accords ou les cautions.

Vérifications à prévoir : aucun envoi sans configuration active, destinataire exact, respect du fuseau, omission des dossiers déjà facturés, alerte du dernier mois, absence de noms dans le contenu par défaut, échec SMTP sans perte de tâche et protection contre les doublons.

### Développement progressif

**Première étape :** périodes de prestation, journal et référence de facture, accords datés, retour de matériel, interface épurée. Le montant peut d’abord rester celui du logiciel métier.

**Deuxième étape :** calcul assisté des seules familles dont les codes, tarifs, unités, arrondis et règles de semaines partielles sont confirmés. Commencer par les matériels réellement loués dans l’officine.

**Troisième étape :** profils spécifiques, notamment fauteuils avec règles transitoires et assistance respiratoire. Ne pas élargir les règles d’une famille à toutes les locations.

Avant activation des calculs, confronter les profils à quelques dossiers anonymisés et factures acceptées : changement de palier, fin d’accord, retour en cours de période, facture tardive, interruption et rejet. Les tarifs actuels et certains détails de proratisation n’ont pas été établis par cette recherche ; ils restent à confirmer par code et date de prestation.
