# Ohana-Installer

> Installateur officiel de l'écosystème Ohana.

## Présentation

**Ohana-Installer** est le composant chargé d'installer, de mettre à jour et de désinstaller les produits officiels de l'écosystème **Ohana**.

Il automatise le déploiement d'une plateforme complète à partir des releases officielles publiées sur GitHub, sans contenir la logique métier des composants qu'il installe.

À terme, un nouvel utilisateur doit pouvoir installer une plateforme Ohana entièrement fonctionnelle à l'aide d'une seule commande.

---

# Écosystème

Ohana est composé de cinq projets complémentaires :

| Projet               | Rôle                                                            |
| -------------------- | --------------------------------------------------------------- |
| **Ohana-Platform**  | Architecture, documentation, contrats publics et Design System. |
| **Ohana-Agent**     | Collecte les observations et surveille l'infrastructure.        |
| **Ohana-Vision**    | Visualise les observations, l'état de santé et la topologie.    |
| **Ohana-Installer** | Installe, met à jour et désinstalle les composants officiels.   |
| **Ohana-House**     | Documente le déploiement domestique de référence.               |

Chaque projet possède une responsabilité clairement définie.

---

# Objectifs

Ohana-Installer poursuit quatre objectifs principaux :

* simplifier le déploiement de la plateforme ;
* garantir des installations reproductibles ;
* centraliser les mises à jour des composants ;
* proposer une procédure d'installation identique sur toutes les machines supportées.

---

# Fonctionnalités

La version **1.0.9** fournit trois commandes principales :

```text
ohana install
ohana update
ohana uninstall
```

## Installation

La commande :

```bash
ohana install
```

réalise automatiquement :

* la vérification de l'environnement ;
* la découverte de la dernière release stable d'Ohana-Platform ;
* la vérification SHA-256 et le téléchargement des releases officielles ;
* l'installation d'Ohana-Agent ;
* l'installation d'Ohana-Vision ;
* la génération des fichiers de configuration ;
* l'installation des services système ;
* la validation finale de l'installation.

Le manifeste vérifié est affiché avant toute modification. L'installation demande
ensuite une confirmation, négative par défaut.

---

## Mise à jour

La commande :

```bash
ohana update
```

commence par vérifier la dernière release stable d'Ohana-Installer. Si une
version plus récente existe, son wheel officiel est téléchargé, vérifié puis
installé avec `pip --upgrade` dans le même environnement virtuel. La commande se
relance ensuite automatiquement avec la nouvelle version.

Une fois l'Installer à jour, la commande découvre la dernière release stable
d'Ohana-Platform. Son manifeste détermine les releases exactes d'Ohana-Agent et
d'Ohana-Vision à installer.

L'installateur détecte les versions présentes :

* chaque package correspondant déjà au manifeste est conservé sans
  téléchargement ni réinstallation ;
* les configurations manquantes et les unités systemd sont toujours
  réconciliées avec la composition Platform ;
* les services sont redémarrés et vérifiés après cette réconciliation ;
* si une version cible est plus ancienne, la rétrogradation automatique est refusée ;
* sinon, le plan de mise à jour est affiché et doit être confirmé.

---

## Désinstallation

La commande :

```bash
ohana uninstall
```

supprime proprement les composants installés ainsi que les services associés.

Les services et répertoires concernés sont affichés avant une confirmation
négative par défaut.

---

## Confirmations et automatisation

Les trois commandes demandent une confirmation avant leur première opération
modificatrice. Une réponse vide ou négative annule sans erreur et sans modifier le
système.

L'option `--yes` accepte explicitement cette confirmation pour les scripts :

```bash
ohana install --yes
ohana update --yes
ohana uninstall --yes
```

---

## Intégrité des téléchargements

Le manifeste Platform, les wheels et les fichiers de configuration sont téléchargés
exclusivement depuis les assets des releases GitHub officielles. Chaque contenu est
comparé au digest SHA-256 publié par GitHub, ainsi qu'à sa taille déclarée, avant
d'être écrit sur disque. Un asset sans digest ou dont le contenu diffère est rejeté.
Les erreurs HTTP GitHub transitoires sont retentées automatiquement trois fois.

---

# Philosophie

Ohana-Installer ne contient aucune logique métier.

Il ne surveille pas l'infrastructure.

Il ne collecte pas d'observations.

Il ne fournit aucune interface utilisateur.

Son unique responsabilité consiste à gérer le cycle de vie des composants officiels de l'écosystème Ohana.

Cette séparation garantit un faible couplage entre les différents projets et facilite leur évolution indépendante.

---

# Architecture

Le processus d'installation suit le principe suivant :

```text
GitHub Releases
        │
        ▼
Téléchargement des composants
        │
        ▼
Installation
        │
        ▼
Configuration
        │
        ▼
Création des services
        │
        ▼
Validation
```

Les installations s'appuient exclusivement sur des **releases officielles**, garantissant un déploiement reproductible et indépendant des branches de développement.

La release Platform agit comme contrat de composition : son manifeste épingle les
tags et noms d'assets exacts des composants. Seule la sélection de la dernière
release stable Platform est automatique.

---

# Compatibilité

La version 1.0.9 cible les environnements Linux utilisant **systemd**.

Prérequis : **Python 3.13 ou supérieur**. Cette contrainte correspond au
minimum commun exigé par Ohana-Agent et Ohana-Vision.

La composition validée par `config/release-manifest.yaml` est :

* Ohana-Platform 1.0.17 ;
* Ohana-Agent 1.8.1 ;
* Ohana-Vision 1.7.0.

Elle déploie les configurations Agent pour DNS, NTP, MQTT, présence réseau,
DHCP, WireGuard, Shelly Telemetry et Z-Wave. Le manifeste détermine également
les arguments exacts transmis aux unités systemd.

---

# Développement

Utiliser Python 3.13 ou supérieur.

Création d'un environnement virtuel :

```bash
python -m venv .venv
```

Activation :

### Linux

```bash
source .venv/bin/activate
```

### Windows

```powershell
.venv\Scripts\Activate.ps1
```

Installation des dépendances de développement :

```bash
python -m pip install -e ".[dev]"
```

Lancement des validations :

```bash
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
```

---

# Documentation

La documentation du projet est disponible dans le répertoire `docs/`.

Les principales ressources sont :

* `ROADMAP.md`
* `CHANGELOG.md`
* [`docs/Architecture.md`](docs/Architecture.md)
* [`docs/Installation.md`](docs/Installation.md)

---

# Licence

Ce projet est distribué sous licence **MIT**.

Cette base reste volontairement concise et centrée sur la mission d'Ohana-Installer, en cohérence avec les README des autres projets de l'écosystème.


## Téléinformation Linky

La composition 1.0.9 déploie le fichier
`teleinformation.example.yaml` vers
`/etc/ohana-agent/plugins/teleinformation.yaml` et transmet l’argument
`--teleinformation-config` au service systemd Agent.
