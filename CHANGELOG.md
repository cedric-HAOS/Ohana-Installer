# CHANGELOG

Toutes les évolutions notables de ce projet seront documentées dans ce fichier.

Le format s'inspire de **Keep a Changelog** et respecte le **Versioning Sémantique (SemVer)**.

---

# [1.0.3] - 2026-07-27

## Ajouté

* Déploiement des configurations officielles des plugins DNS, NTP et MQTT.
* Ajout des arguments `--ntp-config` et `--mqtt-config` à l'unité systemd
  d'Ohana-Agent.

## Modifié

* Manifest aligné sur Ohana-Platform 1.0.6, Ohana-Agent 1.3.0 et
  Ohana-Vision 1.3.0.
* Les configurations de plugins sont préparées avec les droits nécessaires aux
  écritures atomiques réalisées par Ohana-Agent.
* `ohana update` réconcilie désormais les configurations et les unités systemd
  même lorsque les packages Python sont déjà à la version cible.
* Les packages déjà à jour restent conservés sans téléchargement ni
  réinstallation.

## Validation

* Vérification du téléchargement des cinq configurations Agent depuis une même
  release GitHub.
* Vérification de l'installation des configurations DNS, NTP et MQTT.
* Vérification de la ligne de commande systemd complète d'Ohana-Agent.
* 198 tests réussis.

---

# [1.0.2] - 2026-07-24

## Corrigé

* Les unités systemd de type `.path` peuvent désormais être activées et
  démarrées par le flux d'administration DHCP.
* La mise à jour ne s’interrompt plus lors de l’activation de
  `ohana-dhcp-reload.path`.

## Validation

* Compatibilité conservée avec Ohana-Platform 1.0.3, Ohana-Agent 1.2.0
  et Ohana-Vision 1.2.0.
* 197 tests réussis.

---

# [1.0.1] - 2026-07-24

## Ajouté

* Préparation automatique de l'administration graphique entre Vision et Agent.
* Création d'un secret partagé distinct pour chaque compte de service, sans
  exposition au navigateur.
* Préparation des droits minimaux nécessaires aux écritures atomiques de
  l'infrastructure et des fichiers DHCP gérés.
* Installation d'une unité systemd privilégiée dédiée au rechargement de
  dnsmasq après validation par Agent.
* Migration automatique de l'ancien fichier `00-ohanna.conf` vers
  `00-ohana.conf`.
* Vérification de la dernière release stable d'Ohana-Installer au début de
  `ohana update`.
* Mise à niveau de l'Installer dans son environnement virtuel courant avec
  reprise automatique de la commande avant la mise à jour d'Agent et Vision.

## Corrigé

* `ohana update` ne télécharge, n'arrête et ne réinstalle plus un composant
  lorsque sa version correspond déjà à la version cible du manifeste Platform.
* Le plan de mise à jour indique explicitement les composants conservés.
* Les erreurs HTTP GitHub transitoires, notamment `502`, `503` et `504`, sont
  retentées avant d'abandonner le téléchargement.

## Validation

* Manifeste aligné sur Ohana-Platform 1.0.3, Ohana-Agent 1.2.0 et
  Ohana-Vision 1.2.0.
* 195 tests réussis.

---

# [1.0.0] - 2026-07-24

Première version officielle d'**Ohana-Installer**.

## Modifié

* Passage du runtime minimal à Python 3.13.
* Ciblage du manifeste Ohana-Platform `v1.0.1`.
* Alignement sur Ohana-Agent et Ohana-Vision `v1.1.1`.
* Utilisation de comptes systemd dédiés à chaque composant.
* Modernisation des métadonnées de licence du package.

## Ajouté

### Projet

* Création du dépôt Ohana-Installer.
* Mise en place de l'architecture du projet.
* Packaging Python.
* Commande CLI `ohana`.

### Installation

* Vérification de l'environnement.
* Découverte automatique de la dernière release stable d'Ohana-Platform.
* Vérification SHA-256 du manifeste, des wheels et des configurations avant écriture.
* Téléchargement des releases officielles épinglées par le manifeste Platform.
* Installation d'Ohana-Agent.
* Installation d'Ohana-Vision.
* Génération des fichiers de configuration.
* Installation des services système.
* Validation automatique de l'installation.
* Confirmation négative par défaut et option d'automatisation `--yes`.

### Mise à jour

* Détection des versions installées.
* Recherche des nouvelles releases.
* Absence de modification lorsque les versions sont déjà à jour.
* Refus des rétrogradations automatiques.
* Mise à jour des composants.
* Redémarrage automatique des services.
* Validation de la mise à jour.
* Confirmation négative par défaut et option d'automatisation `--yes`.

### Désinstallation

* Arrêt des services.
* Désinstallation des composants.
* Suppression des services système.
* Nettoyage de l'installation.
* Conservation des fichiers de configuration locale.
* Confirmation négative par défaut et option d'automatisation `--yes`.

### Documentation

* README.
* ROADMAP.
* CHANGELOG.
* Documentation d'architecture.
* Guide d'installation sur Raspberry Pi, de mise à jour et de désinstallation.

### Qualité

* Tests unitaires.
* Tests d'intégration.
* Audit final.
* Première release officielle.

---

# Versions antérieures

Aucune.
