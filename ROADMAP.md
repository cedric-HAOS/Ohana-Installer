# ROADMAP

Ce document présente la feuille de route officielle d'**Ohana-Installer**.

L'objectif du projet est de fournir un installateur simple, fiable et reproductible pour l'ensemble de l'écosystème Ohana.

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

# Évolutions futures

Les fonctionnalités suivantes sont volontairement reportées après la version 1.0.1 :

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
