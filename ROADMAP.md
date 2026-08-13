# ROADMAP

Ce document présente la feuille de route officielle d'**Ohana-Installer**.

L'objectif du projet est de fournir un installateur simple, fiable et reproductible pour l'ensemble de l'écosystème Ohana.

---

# Version 1.8.0 — Capacités et restauration d'INFRA-01

**Statut : terminée.**

* [x] Provisionner dnsmasq, Chrony et age depuis le profil Platform.
* [x] Séparer installation, restauration, capacités et réseau dans le menu.
* [x] Restaurer une sauvegarde locale ou iCloud sans staging persistant.
* [x] Réinstaller la composition Agent/Vision exacte de la sauvegarde.
* [x] Valider et appliquer les fichiers avec retour arrière atomique.
* [x] Conserver le DHCP inactif jusqu'à une activation explicite.

# Version 1.7.3 — Installation rclone inter-systèmes

**Statut : terminée.**

* [x] Éviter le remplacement direct entre `/tmp` et `/usr`.
* [x] Conserver un remplacement atomique dans le répertoire de destination.
* [x] Tester explicitement la contrainte de même système de fichiers.

# Version 1.7.2 — Dépendance rclone vérifiée

**Statut : terminée.**

* [x] Installer automatiquement rclone avec Agent.
* [x] Épingler les archives Linux par architecture et leur SHA-256 officiel.
* [x] Préparer rclone avant l'arrêt des services pendant une mise à jour.
* [x] Publier les artefacts wheel, sdist et SHA256SUMS.

# Version 1.7.0 — Mise à jour automatique

**Statut : terminée.**

* [x] Ajouter une option dédiée au menu interactif.
* [x] Fournir `automatic-update enable|disable|status`.
* [x] Installer un timer systemd quotidien, persistant et aléatoirement décalé.
* [x] Éviter toute interruption lorsque les versions sont déjà courantes.
* [x] Supprimer les unités automatiques pendant la désinstallation.
* [x] Publier les artefacts wheel, sdist et SHA256SUMS.

# Version 1.6.1 — Fiabilité DHCP

**Statut : terminée.**

* [x] Déployer le helper de purge ciblée fourni par Ohana-Agent 1.11.1.
* [x] Conserver le rechargement historique pour Ohana-Agent 1.11.0.
* [x] Aligner le catalogue sur Ohana-Platform 1.0.23.
* [x] Publier les artefacts wheel, sdist et SHA256SUMS.

# Version 1.6.0 — Interface interactive finale

## 1. Menu principal

* [x] Ouvrir le menu avec `ohana` sans argument.
* [x] Installer ou mettre à jour la composition recommandée.
* [x] Sélectionner une composition antérieure dans le catalogue Platform.
* [x] Quitter sans modifier le système.

## 2. Réseau INFRA-01

* [x] Lire et préremplir la configuration NetworkManager active.
* [x] Accepter un masque CIDR ou décimal.
* [x] Appliquer sans installer ni mettre à jour Agent/Vision.
* [x] Restaurer automatiquement l’ancienne configuration sans confirmation.
* [x] Fournir la commande explicite `ohana network`.

## 3. Compatibilité

* [x] Conserver `ohana install`, `update`, `versions` et `uninstall`.
* [x] Ne pas ajouter de commande `ohana interactive`.
* [x] Continuer à faire évoluer les couples uniquement dans Ohana-Platform.
* [x] Version publique `ohana 1.6.0`.
* [x] 242 tests réussis.

---

# Version 1.5.0 — Catalogue des compositions

## 1. Catalogue Platform

* [x] Télécharger `release-catalog.yaml` depuis la dernière release Platform.
* [x] Lister les couples Agent/Vision avec `ohana versions`.
* [x] Sélectionner une composition par version Platform.
* [x] Sélectionner une composition par versions Agent et Vision.
* [x] Vérifier la concordance du catalogue avec le manifeste sélectionné.

## 2. Installation et mise à jour

* [x] Installer une composition historique sans modifier le code de l’Installer.
* [x] Refuser les couples non déclarés.
* [x] Préserver la sélection après l’auto-mise à jour de l’Installer.
* [x] Autoriser une rétrogradation uniquement avec `--allow-downgrade`.

## 3. Composition recommandée

* [x] Ohana-Platform 1.0.22.
* [x] Ohana-Agent 1.11.0.
* [x] Ohana-Vision 1.10.0.
* [x] Version publique `ohana 1.5.0`.
* [x] 230 tests réussis.

---

# Version 1.0.0

## 1. Initialisation du projet

### 1.1 Structure du dépôt

* Création de l'architecture du projet.
* Organisation des modules.
* Configuration du packaging Python.

### 1.2 Interface en ligne de commande

* Commande `ohana`.
* Gestion des arguments.
* Aide intégrée.
* Affichage de la version.

### 1.3 Qualité logicielle

* Configuration de Ruff.
* Configuration de Pytest.
* Couverture de tests initiale.
* Intégration continue.

---

## 2. Installation

### 2.1 Vérification de l'environnement

* Vérification du système d'exploitation.
* Vérification de Python.
* Vérification de Git.
* Vérification de la connectivité réseau.
* Vérification des prérequis.

### 2.2 Téléchargement des composants

* Détection des releases officielles.
* Téléchargement sécurisé.
* Vérification de la version.

### 2.3 Installation d'Ohana-Agent

* Installation du package.
* Création de l'environnement Python.
* Génération de la configuration.
* Installation du service système.

### 2.4 Installation d'Ohana-Vision

* Installation du package.
* Génération de la configuration.
* Installation du service système.

### 2.5 Validation

* Vérification du démarrage des services.
* Vérification des versions installées.
* Validation finale de l'installation.

---

## 3. Mise à jour

### 3.1 Détection

* Identification des versions installées.
* Recherche des nouvelles releases.

### 3.2 Mise à jour

* Téléchargement des nouvelles versions.
* Mise à jour des composants.
* Redémarrage des services.

### 3.3 Validation

* Vérification du bon fonctionnement.
* Confirmation de la réussite de la mise à jour.

---

## 4. Désinstallation

### 4.1 Arrêt

* Arrêt des services.
* Désactivation des services système.

### 4.2 Suppression

* Désinstallation des composants.
* Suppression des environnements Python.
* Nettoyage des fichiers installés.

### 4.3 Nettoyage

* Suppression optionnelle des fichiers de configuration.
* Vérification de la désinstallation complète.

---

## 5. Documentation

### 5.1 Documentation utilisateur

* README.
* Guide d'installation.
* Guide de mise à jour.
* Guide de désinstallation.

### 5.2 Documentation technique

* Architecture.
* Organisation du code.
* Contribution.

---

## 6. Validation finale

### 6.1 Tests

* Tests unitaires.
* Tests d'intégration.
* Validation des trois commandes principales.

### 6.2 Audit

* Audit de qualité.
* Audit des dépendances.
* Vérification du packaging.

### 6.3 Release

* Publication de la release officielle.
* Génération des artefacts.
* Publication de la documentation.

---

# Version 1.0.1

## 7. Administration graphique

* [x] Préparer le canal local authentifié entre Ohana-Vision et Ohana-Agent.
* [x] Générer et protéger le secret partagé.
* [x] Préparer les droits d'écriture minimaux sur l'infrastructure et les fichiers DHCP.
* [x] Installer les unités systemd dédiées au rechargement sécurisé de dnsmasq.
* [x] Migrer automatiquement `00-ohanna.conf` vers `00-ohana.conf`.

## 8. Mise à jour idempotente

* [x] Conserver un composant déjà à la version cible.
* [x] Ne pas télécharger, arrêter ou réinstaller un composant déjà à jour.
* [x] Afficher clairement les composants conservés dans le plan de mise à jour.

## 9. Mise à jour de l'Installer

* [x] Vérifier la dernière release stable avant la mise à jour de la plateforme.
* [x] Télécharger et vérifier le wheel officiel de l'Installer.
* [x] Remplacer la version installée dans le même environnement virtuel.
* [x] Relancer automatiquement `ohana update` avec la nouvelle version.
* [x] Retenter les erreurs HTTP GitHub transitoires.

## 10. Composition validée

* [x] Ohana-Platform 1.0.3.
* [x] Ohana-Agent 1.2.0.
* [x] Ohana-Vision 1.2.0.
* [x] 195 tests réussis.

---

# Version 1.0.2

## 11. Activation des unités systemd de surveillance

* [x] Accepter les unités `.path` dans les commandes systemd génériques.
* [x] Activer et démarrer `ohana-dhcp-reload.path` pendant une mise à jour.
* [x] Conserver la validation stricte des noms d’unités systemd.
* [x] 197 tests réussis.

---

# Version 1.0.3

## 12. Plugins administrables

* [x] Déployer les configurations DNS, NTP et MQTT depuis la release Agent.
* [x] Transmettre les chemins des trois configurations au service systemd.
* [x] Préparer les permissions nécessaires aux écritures d'Ohana-Agent.

## 13. Réconciliation de la composition Platform

* [x] Conserver les packages Python déjà à la version cible.
* [x] Installer les nouvelles configurations sans écraser les fichiers locaux.
* [x] Régénérer et remplacer les unités systemd devenues différentes.
* [x] Redémarrer et vérifier les services après réconciliation.

## 14. Composition validée

* [x] Ohana-Platform 1.0.6.
* [x] Ohana-Agent 1.3.0.
* [x] Ohana-Vision 1.3.0.
* [x] 198 tests réussis.

---

# Version 1.0.4

## 15. Présence réseau et DHCP

* [x] Déployer `network.example.yaml` vers `plugins/network.yaml`.
* [x] Déployer `dhcp.example.yaml` vers `plugins/dhcp.yaml`.
* [x] Transmettre `--network-config` et `--dhcp-config` au service Agent.

## 16. Composition validée

* [x] Ohana-Platform 1.0.7.
* [x] Ohana-Agent 1.5.0.
* [x] Ohana-Vision 1.4.0.
* [x] Version publique `ohana 1.0.4`.
* [x] 199 tests réussis.

# Version 1.0.10

## Composition officielle

* [x] Ohana-Platform 1.0.18.
* [x] Ohana-Agent 1.8.1.
* [x] Ohana-Vision 1.7.1.
* [x] Validation frontend des noms DNS DHCP.
* [x] Version publique `ohana 1.0.10`.

---

# Version 1.0.9

## Composition officielle

* [x] Ohana-Platform 1.0.17.
* [x] Ohana-Agent 1.8.1.
* [x] Ohana-Vision 1.7.0.
* [x] Correction de la fraîcheur contextuelle Téléinformation.
* [x] Version publique `ohana 1.0.9`.

---

# Version 1.0.8

## Composition officielle

* [x] Ohana-Platform 1.0.16.
* [x] Ohana-Agent 1.8.0.
* [x] Ohana-Vision 1.7.0.
* [x] Déployer la configuration Téléinformation Linky.
* [x] Version publique `ohana 1.0.8`.

---

# Version 1.0.7

## Composition officielle

* [x] Ohana-Platform 1.0.15.
* [x] Ohana-Agent 1.7.5.
* [x] Ohana-Vision 1.6.3.
* [x] Version publique `ohana 1.0.7`.

---

# Version 1.0.6

## Composition officielle

* [x] Ohana-Platform 1.0.14.
* [x] Ohana-Agent 1.7.4.
* [x] Ohana-Vision 1.6.3.
* [x] Version publique `ohana 1.0.6`.

---

# Version 1.0.5

## 17. Z-Wave, WireGuard et Shelly Telemetry

* [x] Déployer `wireguard.example.yaml` vers `plugins/wireguard.yaml`.
* [x] Déployer `shelly-telemetry.example.yaml` vers `plugins/shelly-telemetry.yaml`.
* [x] Déployer `zwave.example.yaml` vers `plugins/zwave.yaml`.

## 18. Composition validée

* [x] Ohana-Platform 1.0.13.
* [x] Ohana-Agent 1.7.3.
* [x] Ohana-Vision 1.6.2.
* [x] Version publique `ohana 1.0.5`.
* [x] 199 tests réussis.

---

# Version 1.0.11

## Composition officielle

* [x] Ohana-Platform 1.0.19.
* [x] Ohana-Agent 1.9.0.
* [x] Ohana-Vision 1.8.0.
* [x] Déployer `home-assistant-telemetry.example.yaml` vers
  `plugins/home-assistant-telemetry.yaml`.
* [x] Migrer une configuration locale `shelly-telemetry.yaml` sans l’écraser.
* [x] Version publique `ohana 1.0.11`.
* [x] 200 tests réussis.

---

# Évolutions futures

Les fonctionnalités suivantes sont volontairement reportées après la version 1.0.5 :

* Sauvegarde et restauration.
* Retour arrière (rollback).
* Diagnostic (`doctor`).
* État de la plateforme (`status`).
* Gestion des journaux.
* Installation sélective des composants.
* Mise à jour automatique planifiée.
* Support de Docker.
* Support de Kubernetes.
* Déploiement multi-sites.

La priorité reste de conserver un installateur officiel simple, fiable et stable pour l'écosystème Ohana.

# Version 1.0.12

**Statut : terminé.**

* [x] Ohana-Platform 1.0.20.
* [x] Ohana-Agent 1.10.0.
* [x] Ohana-Vision 1.9.0.
* [x] Déployer la configuration Téléinformation directe sans écraser les
  installations historiques.
* [x] Préserver les plages horaires enregistrées dans l’infrastructure.
* [x] Version publique `ohana 1.0.12`.

---



# Version 1.0.13

- [x] Composition Agent 1.11.0 / Vision 1.10.0 / Platform 1.0.21.
- [x] Préparation du helper NetworkManager et de la règle sudoers.
- [x] Provisionnement IPv4 initial statique ou DHCP.
- [x] Tests du déploiement réseau sécurisé.
