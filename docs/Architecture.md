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
* découvrir la dernière release stable d'Ohana-Platform ;
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
manifeste, après vérification de son digest SHA-256, constitue le contrat de
composition de l'installation.

Chaque tag et chaque nom d'asset d'Ohana-Agent et d'Ohana-Vision provient de ce
manifeste. L'asset correspondant est ensuite résolu dans la release GitHub épinglée,
puis sa taille et son digest SHA-256 sont vérifiés avant toute écriture sur disque.

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

La première version du projet privilégie une approche volontairement simple.

Trois commandes constituent le périmètre fonctionnel :

```text
ohana install
ohana update
ohana uninstall
```

Les fonctionnalités d'administration avancées seront introduites dans des versions ultérieures.

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

La composition Platform 1.0.14 déclare les configurations DNS, NTP, MQTT,
présence réseau, DHCP, WireGuard, Shelly Telemetry et Z-Wave attendues par
Ohana-Agent 1.7.4. Le même manifeste épingle Ohana-Vision 1.6.3 et fournit les
arguments de commande utilisés pour générer les unités systemd.

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

La version 1.0.6 cible les systèmes Linux utilisant **systemd**.

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
