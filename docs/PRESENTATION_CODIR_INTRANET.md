# L'Intranet de l'Institut Le Val Mandé — présentation fonctionnelle

*Document de synthèse à destination du CODIR — support de base pour la génération d'une vidéo de présentation (NotebookLM / Gemini).*

---

## 1. En une phrase

L'intranet est le **guichet unique numérique** de l'Institut Le Val Mandé : chaque salarié, sur chaque établissement, y accède avec son compte professionnel pour faire une demande, suivre son traitement et obtenir une réponse — sans papier, sans mail perdu, sans coup de fil au mauvais service.

Il remplace une mosaïque d'usages informels (mails, appels, formulaires papier, tableurs partagés) par un **parcours structuré, tracé et piloté**, commun à tous les établissements et services support de l'Institut Le Val Mandé : Informatique, DRH, DAF/Achats, Services Techniques, Services Généraux, et les établissements médico-sociaux (ESAT, MAS, FAM, IME, FH, FV, SAMSAH, SAVIE, Accueil, Archipelle, Gîte, etc.).

---

## 2. Pourquoi cet outil : le constat de départ

Avant l'intranet, une demande simple — signaler un PC en panne, commander une fourniture, déclarer l'arrivée d'un nouveau salarié, monter un dossier de séjour — transitait par des canaux différents selon la personne, le service et l'établissement. Conséquences concrètes :

- **Pas de traçabilité** : impossible de savoir qui a demandé quoi, quand, et où en est le traitement.
- **Pas de règle commune** : chaque service gérait ses demandes à sa manière, avec ou sans validation hiérarchique.
- **Perte de temps** : relances téléphoniques, mails égarés, ressaisies multiples de la même information.
- **Aucun pilotage** : la direction n'avait pas de vue d'ensemble sur les volumes de demandes, les délais de traitement, ni sur les points de blocage.

L'intranet répond à ces quatre problèmes avec une plateforme unique, accessible depuis un navigateur, sur tous les sites.

---

## 3. Un point d'entrée unique pour tous les salariés : le Portail

Dès la connexion, chaque salarié arrive sur un **portail personnel** qui présente, sous forme de tuiles simples et visuelles, tous les services auxquels il peut s'adresser :

- **Informatique** — panne PC, réseau, logiciel, imprimante
- **DRH** — contrat, RIB, informations personnelles, rendez-vous
- **DAF / Achats** — bons de commande, factures, budget
- **Services Techniques** — travaux, maintenance, plomberie
- **Services Généraux** — enlèvements et demandes logistiques
- **Dépannage Imago** — assistance sur le logiciel métier
- **Bon de commande : délégation de signature** — commandes rapides inférieures à 400 € TTC
- **Demande de matériel informatique** — PC, écrans, périphériques, soumis à validation
- **Agent recruté (FCPI)** — déclaration d'une nouvelle arrivée
- **Dossier de séjour** — dépôt d'un dossier de séjour, devis et PV de sécurité
- **Publication d'actualités** — proposer un article pour la vie de l'Institut Le Val Mandé
- ainsi que tous les **formulaires métier spécifiques** créés au fil de l'eau par les administrateurs (voir section 7)

Chaque salarié voit également, sur ce même portail : ses notifications en temps réel, l'historique de ses propres demandes, et — selon les établissements — une messagerie d'équipe simple pour échanger sans sortir de l'outil. L'interface s'adapte au mode sombre/clair et fonctionne aussi bien sur ordinateur que sur mobile.

---

## 4. Le cœur du système : la gestion des demandes (tickets) et leurs circuits de validation

Chaque demande déposée devient un **ticket** suivi de bout en bout, avec un identifiant unique, un statut visible à tout moment, et un historique complet des échanges.

Le point fort de l'outil : **le circuit de validation s'adapte automatiquement à la nature de la demande**, sans que l'utilisateur ait à se poser la question du bon interlocuteur :

- **Validation hiérarchique** : certaines demandes passent d'abord par le manager du demandeur avant d'être transmises au service concerné.
- **Validation technique** : pour les sujets qui le nécessitent, un second regard expert est requis avant traitement.
- **Circuit budgétaire DAF** : les demandes d'achat suivent un parcours dédié — validation du manager DAF, puis **signature électronique du directeur** avant engagement de la dépense.
- **Prise en charge et clôture** : un agent du service concerné prend la demande en charge, peut fixer un rendez-vous avec le demandeur, échanger avec lui, puis clôturer une fois la demande résolue.
- **Réaffectation et transfert** : une demande mal orientée peut être réattribuée à un autre agent ou transférée vers un autre service sans repartir de zéro.

Chaque étape déclenche automatiquement les **notifications** aux bonnes personnes (demandeur informé de l'avancement, solveur informé d'une nouvelle demande, manager informé d'une validation en attente), avec relance par email lorsque nécessaire.

### Tableaux de bord dédiés par rôle

- **Tableau de bord Manager** : vue sur les demandes de son périmètre à valider ou à suivre.
- **Tableau de bord Solveur / Service support** : liste des demandes à traiter, prise en charge en un clic, historique.
- **Historique global** : recherche et consultation de toutes les demandes passées, avec export.

---

## 5. Pilotage et statistiques : donner à la direction une vision d'ensemble

Un module de **statistiques dédié** permet à l'encadrement de suivre, service par service et sur la période de son choix :

- le volume de demandes reçues, en cours et clôturées,
- la répartition par type de demande et par établissement,
- les délais de traitement,
- une vue mensuelle glissante pour identifier les tendances.

Ces données sont **exportables (Excel)** pour être intégrées dans des présentations de pilotage ou des comités — un outil directement utile au CODIR pour objectiver l'activité des services support plutôt que de s'appuyer sur des ressentis.

---

## 6. Le parcours d'un agent recruté (FCPI) : un onboarding automatisé

Historiquement, l'arrivée d'un nouveau salarié déclenchait une série de démarches séparées auprès de plusieurs services (création du poste informatique, ouverture des accès, dotation en matériel, badge, etc.), chacune initiée manuellement.

Avec le module **FCPI (Fiche de Création de Poste Informatique)**, un seul formulaire de déclaration d'arrivée génère et distribue **automatiquement** les sous-demandes nécessaires vers chaque service concerné (Informatique, DAF, Généraux…), avec les bonnes informations déjà pré-remplies (identité, service, date d'entrée). Cette fiche suit ensuite son propre circuit de validation (manager RH, puis direction RH) avant dispatch. Résultat : plus aucune étape de l'accueil d'un nouveau salarié n'est oubliée, et chaque service sait précisément ce qu'il doit préparer et dans quel délai.

---

## 7. Dossiers de séjour (établissements médico-sociaux)

Pour les établissements organisant des séjours (vacances adaptées, activités), un module dédié permet de déposer un **dossier de séjour complet** (descriptif, devis, PV de sécurité) directement en ligne. Le dossier suit un circuit de validation managériale puis est dispatché aux services concernés pour organisation — avec, là encore, traçabilité complète et zéro papier volant.

---

## 8. Publication d'actualités : un circuit éditorial simple

Tout salarié peut proposer une **actualité** (texte et visuels) pour la vie de l'Institut Le Val Mandé. L'article passe par une validation de la direction, peut être renvoyé en correction si besoin, puis publié une fois validé. Ce module donne à chaque établissement une voix dans la communication interne, sans perdre le contrôle éditorial.

---

## 9. Le moteur de formulaires génériques : une plateforme qui s'adapte sans développement

C'est la brique la plus stratégique pour l'avenir de l'outil : un **constructeur de formulaires (« form builder »)** entièrement piloté depuis un back-office, sans écrire une ligne de code.

Un administrateur peut, en quelques minutes :

- créer un nouveau formulaire métier (nom, description, champs : texte, liste déroulante, choix multiple, case à cocher, date, nombre, pièce jointe simple ou multiple…),
- définir les **étapes de validation** propres à ce formulaire (qui valide, dans quel ordre),
- définir **vers quels services** les demandes issues de ce formulaire doivent être dispatchées, et sous quelle forme,
- activer, dupliquer ou désactiver le formulaire à tout moment.

Une fois publié, le formulaire apparaît automatiquement comme une nouvelle tuile sur le portail de tous les salariés concernés. **8 formulaires métier sont déjà déployés en production** avec ce moteur, preuve que la plateforme peut désormais absorber de nouveaux besoins de l'Institut Le Val Mandé (nouveaux process, nouveaux établissements, nouvelles demandes réglementaires) sans dépendre systématiquement d'un développement informatique dédié — un gain d'autonomie et de réactivité pour l'organisation.

---

## 10. Gestion du parc informatique et du matériel

### Inventaire

Le service informatique dispose d'un module d'**inventaire du matériel** (ordinateurs, écrans, périphériques…) : ajout, modification, suppression, et **import/export en masse via Excel** pour synchroniser rapidement l'inventaire avec les outils existants.

### Prêts de matériel

Un module dédié suit les **prêts de matériel** aux salariés : qui a emprunté quoi, depuis quand, avec détection automatique des conflits (matériel déjà prêté faisant l'objet d'une nouvelle demande), gestion du retour, et import/export Excel.

### Générateur de fiches de prêt

Un outil dédié à l'espace technique permet de **générer automatiquement une fiche de prêt** prête à imprimer ou signer, à partir des informations du salarié et du matériel — supprimant la ressaisie manuelle et harmonisant le document utilisé par tous les techniciens.

---

## 11. Back-office d'administration

Les administrateurs disposent d'un **hub d'administration** central donnant accès à :

- la **gestion des utilisateurs** (rôles, droits, rattachement à un service),
- le **constructeur de formulaires** décrit en section 9,
- le **tableau de bord de supervision technique** (section 12),
- des accès rapides vers tous les modules métier (tickets, inventaire, prêts, espace technique) pour un pilotage centralisé.

### Rôles et sécurité des accès

L'accès à l'intranet est protégé par une **authentification unique reliée à l'annuaire de l'Institut Le Val Mandé (Active Directory / LDAP)** : chaque salarié se connecte avec son identifiant professionnel habituel, sans mot de passe supplémentaire à retenir. Les droits affichés et les actions possibles dépendent du **rôle** de la personne (Salarié, Manager, Directeur, Solveur d'un service support, Administrateur), garantissant que chacun ne voit et n'agit que sur ce qui le concerne.

---

## 12. Supervision technique : un outil qui surveille sa propre santé

Un tableau de bord de **supervision système**, réservé aux administrateurs, vérifie en continu :

- la disponibilité de la base de données,
- la connexion à l'annuaire (Active Directory/LDAP), condition de la connexion de tous les salariés,
- l'espace disque disponible,
- la présence et la fraîcheur des **sauvegardes automatiques** (une alerte se déclenche si aucune sauvegarde récente n'est détectée),
- l'état général du service (« en ligne », « dégradation détectée », « incident critique »).

Cette supervision, associée à un script de surveillance externe, garantit que les problèmes techniques sont détectés **avant** de bloquer les utilisateurs, et sécurise la continuité de service d'un outil devenu central pour le fonctionnement quotidien des établissements.

---

## 13. Notifications et communication interne

- **Notifications en temps réel** : chaque salarié est alerté dès qu'une de ses demandes avance (prise en charge, validation, réponse, clôture), directement dans l'intranet et par email lorsque c'est pertinent.
- **Messagerie d'équipe intégrée** : un espace d'échange simple entre collègues, accessible sans quitter l'outil.

---

## 14. Ce que cet outil change concrètement pour l'Institut Le Val Mandé

| Avant | Avec l'intranet |
|---|---|
| Demandes dispersées (mail, tél, papier) | Un point d'entrée unique, identique pour tous les établissements |
| Aucune traçabilité | Chaque demande a un statut, un historique, un responsable identifié |
| Validations informelles ou oubliées | Circuits de validation formalisés et automatiques selon le type de demande |
| Onboarding d'un nouveau salarié = démarches manuelles dispersées | Un formulaire déclenche automatiquement toutes les démarches nécessaires |
| Toute nouvelle demande métier = développement informatique | Un formulaire configurable en quelques minutes, sans développement |
| Aucune vision consolidée pour la direction | Statistiques et exports par service, par période, exploitables en comité |
| Inventaire et prêts de matériel sur tableurs isolés | Suivi centralisé, avec import/export et détection des conflits |
| Pas de vue sur la santé de l'outil | Supervision continue et alertes proactives |

---

## 15. En résumé pour le CODIR

L'intranet est passé, en quelques mois, d'un outil de tickets informatiques à une **plateforme de gestion des demandes internes pour toute l'Institut Le Val Mandé** : DRH, DAF, Services Techniques, Services Généraux, et l'ensemble des établissements médico-sociaux. Son architecture — en particulier le moteur de formulaires configurables — lui permet d'absorber de nouveaux besoins métier au rythme de l'Institut Le Val Mandé, sans dépendre systématiquement de développements informatiques supplémentaires. C'est aujourd'hui un outil de **traçabilité, d'efficacité et de pilotage**, et une brique d'infrastructure numérique sur laquelle l'Institut Le Val Mandé peut continuer à construire.
