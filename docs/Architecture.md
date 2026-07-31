# Architecture

## Objectif

**Ohana-Installer** est l'installateur officiel de l'écosystème **Ohana**.

Sa responsabilité est d'installer, de mettre à jour et de désinstaller les composants officiels de la plateforme de manière fiable, reproductible et sécurisée.

Il ne contient aucune logique métier propre aux composants qu'il installe.

---

# Position dans l'écosystème

```text
                         Ohana Platform
                                │
        ┌───────────────┬───────┼───────┬───────────────┐
        │               │       │       │               │
        ▼               ▼       ▼       ▼               ▼
 Ohana-Agent    Ohana-Vision  Installer  Ohana-House  Contrats communs
 Observe et     Visualise et   Déploie    Documente    et composition
 configure      administre
```

Les responsabilités sont volontairement séparées.

| Projet           | Responsabilité                                                    |
| ---------------- | ----------------------------------------------------------------- |
| Ohana-Platform  | Définit l'architecture, les contrats publics et le Design System. |
| Ohana-Agent     | Observe l'infrastructure et produit des observations.             |
| Ohana-Vision    | Présente les données collectées.                                  |
| Ohana-Installer | Gère le cycle de vie des composants.                              |
| Ohana-House     | Documente le déploiement domestique réel et cible.                 |

Cette séparation limite le couplage entre les projets et facilite leur évolution indépendante.

---

# Responsabilités

Ohana-Installer est responsable de :

* vérifier les prérequis de l'environnement ;
* télécharger le catalogue officiel publié par Ohana-Platform ;
* sélectionner et vérifier une composition Agent/Vision officielle ;
* vérifier et télécharger les assets des releases officielles ;
* installer les composants ;
* générer les fichiers de configuration ;
* créer les services système ;
* mettre à jour sa propre version dans l'environnement virtuel courant ;
* mettre à jour les composants installés ;
* désinstaller proprement la plateforme.

Il n'est **pas** responsable :

* de collecter des observations ;
* de superviser l'infrastructure ;
* d'exposer une interface utilisateur ;
* d'exécuter des plugins métier ;
* de remplacer les fonctionnalités d'Ohana-Agent ou d'Ohana-Vision.

---

# Principes d'architecture

## Une responsabilité unique

Chaque composant de l'écosystème possède une responsabilité clairement identifiée.

Ohana-Installer se limite exclusivement à l'installation et à la maintenance des composants officiels.

---

## Releases officielles uniquement

Les installations reposent exclusivement sur les releases officielles publiées.

Le projet ne déploie jamais directement une branche Git de développement.

```text
GitHub Release
        │
        ▼
Téléchargement
        │
        ▼
Installation
```

Cette approche garantit des installations reproductibles et identiques entre les environnements.

---

## Chaîne d'intégrité

La dernière release stable d'Ohana-Platform est découverte avec l'API GitHub. Son
`release-catalog.yaml`, après vérification de son digest SHA-256, liste les
compositions installables. Chaque entrée référence une release Platform immuable.

Le `release-manifest.yaml` de la composition choisie est ensuite téléchargé et
comparé au catalogue. Chaque tag et chaque nom d'asset d'Ohana-Agent et
d'Ohana-Vision provient de ce manifeste. L'asset correspondant est résolu dans la
release GitHub épinglée, puis sa taille et son digest SHA-256 sont vérifiés avant
toute écriture sur disque.

```text
Dernière release Installer
             │
             ▼
Mise à niveau et reprise de la commande
             │
             ▼
Dernière release Platform
             │
             ▼
Catalogue des couples Agent/Vision
             │
             ▼
Release Platform sélectionnée
             │
             ▼
Manifeste vérifié et épinglage des composants
             │
             ▼
Releases Agent et Vision
             │
             ▼
Vérification SHA-256 des assets
             │
             ▼
Installation après confirmation
```

Un asset absent, ambigu, dépourvu de digest ou altéré interrompt l'opération.

---

## Aucun couplage métier

Ohana-Installer ne connaît pas le fonctionnement interne d'Ohana-Agent ni d'Ohana-Vision.

Il orchestre leur installation sans embarquer leur logique métier.

Chaque composant reste autonome et peut évoluer indépendamment.

---

## Simplicité

L’interface interactive et les commandes explicites utilisent les mêmes fonctions
internes. Aucun traitement d’installation, de catalogue ou de réseau n’est dupliqué.

```text
                    Services Installer existants
                     ▲                       ▲
                     │                       │
Interface `ohana` ───┘                       └── Commandes CLI explicites
```

Le menu couvre l’usage courant tandis que les commandes restent adaptées aux
scripts et au dépannage :

```text
ohana
ohana versions
ohana install
ohana update
ohana network
ohana uninstall
```

---

# Processus d'installation

Le processus suit les étapes suivantes :

```text
Vérification de l'environnement
               │
               ▼
Téléchargement des releases
               │
               ▼
Installation des composants
               │
               ▼
Génération des configurations
               │
               ▼
Installation des services
               │
               ▼
Validation finale
```

Chaque étape est validée avant de poursuivre afin de garantir une installation cohérente.

La composition recommandée Platform 1.0.22 déclare les configurations DNS, NTP,
MQTT, présence réseau, DHCP, WireGuard, Télémétrie Home Assistant,
Téléinformation et Z-Wave attendues par Ohana-Agent 1.11.0. Le même manifeste
épingle Ohana-Vision 1.10.0 et fournit les arguments utilisés pour générer les
unités systemd. Les compositions historiques restent sélectionnables dans le
catalogue.

Pendant une mise à jour, la comparaison des versions décide uniquement quels
packages Python doivent être remplacés. Les configurations et les unités systemd
sont toujours réconciliées avec le manifeste courant sans écraser les fichiers
locaux existants.

---

# Gestion des composants

Dans sa première version, Ohana-Installer gère les composants suivants :

* Ohana-Agent
* Ohana-Vision

Chaque composant est installé indépendamment.

Cette architecture permettra d'ajouter de nouveaux composants officiels sans remettre en cause le fonctionnement général de l'installateur.

---

# Compatibilité

La version 1.6.0 cible les systèmes Linux utilisant **systemd**.

Les environnements de développement Windows restent pris en charge pour le développement et les tests du projet.

---

# Évolutivité

L'architecture a été pensée pour permettre l'ajout progressif de nouvelles fonctionnalités sans modifier les principes fondateurs.

Les évolutions envisagées comprennent notamment :

* installation sélective des composants ;
* sauvegarde et restauration ;
* diagnostic de la plateforme ;
* mise à jour automatique planifiée ;
* support de nouveaux environnements de déploiement.

Ces évolutions devront préserver les principes suivants :

* responsabilité unique ;
* faible couplage ;
* simplicité ;
* installations reproductibles ;
* compatibilité avec les releases officielles.

---

# Conclusion

Ohana-Installer constitue le point d'entrée officiel de l'écosystème Ohana.

Son rôle est de rendre le déploiement, la mise à jour et la désinstallation des composants aussi simples que possible, tout en laissant à chaque produit la responsabilité de son propre domaine fonctionnel.


La composition 1.0.20 conserve la configuration Téléinformation introduite
en 1.0.16 et épingle Vision 1.9.0 pour la validation frontend des noms DNS
des réservations DHCP.


## Lot B : flux Téléinformation direct

La composition 1.0.20 conserve le flux MQTT vers Home Assistant mais ajoute un
flux HTTP indépendant de `teleinfo2mqtt` vers le port 8770 d’Ohana-Agent. Le
jeton d’ingestion est configuré dans Vision et dans l’add-on ; il n’accorde
aucun droit d’administration. Les plages horaires sont enregistrées dans les
métadonnées des équipements et restent portées par l’infrastructure Agent.


## Administration NetworkManager

Après l’installation du wheel Agent, Installer crée un wrapper root fixe vers
`ohana-agent-network-helper` et une règle sudoers réservée à l’utilisateur
`ohana-agent`. Agent ne reçoit aucun droit root général. Le helper accepte
uniquement `status`, `apply`, `confirm` et `rollback`.

Pendant une désinstallation, Installer confirme les transactions réseau encore
en attente afin de conserver la connexion active, puis retire le wrapper, la
règle sudoers et les instantanés root.


## Interface interactive

`ohana` sans argument vérifie la présence d’un terminal puis affiche un menu
numéroté compatible avec une console locale ou une session SSH. Le menu ne lance
aucun sous-processus `ohana` : il appelle le même parseur et les mêmes gestionnaires
que les commandes explicites.

La sélection d’une composition télécharge `release-catalog.yaml` au moment du
choix. La liste exclut la composition recommandée, déjà couverte par le premier
choix, et affiche les statuts supporté ou historique.

Le formulaire réseau utilise le helper NetworkManager limité livré depuis le Lot C.
L’application crée une transaction avec retour automatique ; la confirmation ou la
restauration utilise la même transaction que Vision.
