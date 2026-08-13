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

La version **1.8.0** fournit une interface interactive et huit commandes explicites :

```text
ohana
ohana versions
ohana install
ohana restore
ohana update
ohana network
ohana capability
ohana automatic-update
ohana uninstall
```

## Interface interactive

La commande la plus simple ouvre directement le menu :

```bash
sudo ohana
```

```text
1. Installer une nouvelle machine INFRA-01
2. Restaurer INFRA-01
3. Mettre à jour une installation Ohana
4. Installer une composition antérieure
5. Gérer les capacités d’INFRA-01
6. Configurer le réseau d’INFRA-01
7. Mise à jour automatique : désactivée
8. Quitter
```

L'installation neuve, la mise à jour et la gestion des capacités sont volontairement
séparées. Le profil `infra-01` déclaré par Platform provisionne dnsmasq pour la
capacité DHCP et Chrony pour la référence temporelle. dnsmasq reste arrêté jusqu'à
une activation explicite ; Chrony est configuré, validé puis activé. La configuration
réseau reste une opération indépendante qui ne réinstalle aucun composant.

## Mise à jour automatique

```bash
sudo ohana automatic-update enable
sudo ohana automatic-update status
sudo ohana automatic-update disable
```

Le timer vérifie les mises à jour chaque jour à 04:00, avec un délai aléatoire
maximal de 30 minutes et rattrapage au prochain démarrage. Lorsque Installer,
Agent et Vision sont déjà à jour, aucune configuration n'est modifiée et aucun
service n'est redémarré. Les exécutions sont consultables avec :

```bash
sudo systemctl status ohana-update.timer
sudo journalctl -u ohana-update.service
```

Les commandes explicites restent disponibles pour les scripts et le dépannage.

## Installation

La commande :

```bash
ohana install
```

réalise automatiquement :

* la vérification de l'environnement ;
* la lecture du catalogue officiel publié par Ohana-Platform ;
* le provisionnement des capacités système du profil INFRA-01 ;
* la vérification SHA-256 et le téléchargement des releases officielles ;
* l'installation d'Ohana-Agent ;
* l'installation d'Ohana-Vision ;
* la génération des fichiers de configuration ;
* l'installation des services système ;
* la validation finale de l'installation.

Le manifeste vérifié est affiché avant toute modification. L'installation demande
ensuite une confirmation, négative par défaut. Sans sélecteur, la composition
recommandée par la dernière release Platform est utilisée.

## Restauration d'INFRA-01

Une sauvegarde locale peut être restaurée avec :

```bash
sudo ohana restore \
  --local /media/usb/infra-01-20260813T040000Z \
  --identity /media/usb/ohana-infra-01.agekey
```

Installer peut également retrouver la sauvegarde la plus récente dans iCloud :

```bash
sudo ohana restore \
  --icloud
```

Installer récupère automatiquement dans iCloud l'identité `age` associée à la
sauvegarde, puis demande l'identifiant Apple, le mot de passe et, si nécessaire,
le code 2FA dans
une session rclone temporaire. Les archives, la configuration rclone et les
fichiers déchiffrés restent dans `/run`, qui doit être un `tmpfs` : aucune copie
intermédiaire n'est écrite sur la carte microSD.

Installer vérifie le manifeste, la taille et le SHA-256 du fichier chiffré,
refuse les chemins non autorisés dans l'archive, installe la composition exacte
Agent/Vision sauvegardée, puis restaure les configurations et la base Vision de
manière atomique. Agent, Vision et Chrony sont redémarrés après validation.
Le DHCP restauré reste inactif jusqu'à une activation explicite avec
`ohana capability activate dhcp`.

## Capacités d'INFRA-01

Afficher leur état :

```bash
sudo ohana capability status
```

Une capacité possède un état distinct : absente, installée, configurée ou active.
La mise en production du DHCP reste volontairement séparée de son installation :

```bash
sudo ohana capability activate dhcp
```

L'Installer rappelle qu'un seul serveur DHCP doit être actif et demande :
`L'ancien serveur DHCP a-t-il été désactivé ?`. Il valide ensuite la configuration
avec `dnsmasq --test` avant d'activer le service. Le retour arrière local est :

```bash
sudo ohana capability deactivate dhcp
```

## Choix du couple Agent/Vision

Afficher les compositions déclarées par Platform :

```bash
ohana versions
```

Installer une composition par sa version Platform :

```bash
sudo ohana install --platform-version 1.0.20
```

Ou saisir directement le couple officiel :

```bash
sudo ohana install \
  --agent-version 1.10.0 \
  --vision-version 1.9.0
```

Installer refuse toute combinaison absente de `release-catalog.yaml`. Il ne fabrique
jamais un couple Agent/Vision arbitraire.

---

## Configuration réseau

La configuration réseau peut être réalisée depuis le choix 6 du menu interactif.
Les valeurs actives sont préremplies et le formulaire accepte un préfixe CIDR ou
un masque décimal, par exemple `24` ou `255.255.255.0`. La nouvelle configuration
est appliquée avec un retour automatique de 180 secondes tant qu’elle n’est pas
confirmée. Cette opération ne déclenche aucune installation Agent/Vision.

La commande explicite reste disponible :

```bash
sudo ohana network
```

Elle affiche l’état courant. Une configuration statique peut être appliquée avec :

```bash
sudo ohana network --yes \
  --interface eth0 \
  --address 192.168.1.10/24 \
  --gateway 192.168.1.1 \
  --dns 192.168.1.11 \
  --dns 192.168.1.12
```

## Provisionnement réseau pendant l’installation

Cette fonction nécessite une composition comprenant Ohana-Agent 1.11.0 ou une
version ultérieure, soit Platform 1.0.21 ou une version ultérieure dans le
catalogue actuel.

Pour configurer INFRA-01 sans commande `nmcli` manuelle :

```bash
sudo ohana install --yes \
  --network-interface eth0 \
  --network-address 192.168.1.10/24 \
  --network-gateway 192.168.1.1 \
  --network-dns 192.168.1.11 \
  --network-dns 192.168.1.12
```

Le mode DHCP initial est également disponible avec
`--network-interface eth0 --network-dhcp`. L’installateur prépare le helper
NetworkManager, valide la règle `sudoers`, applique la connexion puis confirme
la transaction locale. Les modifications ultérieures sont disponibles dans
Vision, page **Configuration → Réseau Agent**.

## Mise à jour

La commande :

```bash
ohana update
```

commence par vérifier la dernière release stable d'Ohana-Installer. Si une
version plus récente existe, son wheel officiel est téléchargé, vérifié puis
installé avec `pip --upgrade` dans le même environnement virtuel. La commande se
relance ensuite automatiquement avec la nouvelle version.

Une fois l'Installer à jour, la commande utilise la composition recommandée par
Ohana-Platform, ou la composition explicitement sélectionnée avec les mêmes options
que `install`. Le manifeste de la release Platform choisie détermine les releases
exactes d'Ohana-Agent et d'Ohana-Vision.

L'installateur détecte les versions présentes :

* chaque package correspondant déjà au manifeste est conservé sans
  téléchargement ni réinstallation ;
* les configurations manquantes et les unités systemd sont toujours
  réconciliées avec la composition Platform ;
* les services sont redémarrés et vérifiés après cette réconciliation ;
* si une version cible est plus ancienne, la rétrogradation est refusée par défaut ;
* une rétrogradation explicitement sélectionnée exige `--allow-downgrade` ;
* le plan de mise à jour est affiché et doit être confirmé.

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

Les commandes modificatrices demandent une confirmation avant leur première opération
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

Il ne fournit aucune interface web persistante ; son interface utilisateur reste limitée au terminal d’administration.

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

La dernière release Platform publie un catalogue des compositions disponibles.
Chaque entrée pointe vers une release Platform immuable dont le manifeste épingle les
tags et noms d'assets exacts des composants. Ajouter un couple au catalogue ne
nécessite donc aucune nouvelle version de l'Installer.

---

# Compatibilité

La version 1.8.0 cible les environnements Linux utilisant **systemd**. Les
unités créent aussi les répertoires d'état persistants d'Agent et Vision sous
`/var/lib`, avec un accès limité au compte de service.

Prérequis : **Python 3.13 ou supérieur**. Cette contrainte correspond au
minimum commun exigé par Ohana-Agent et Ohana-Vision.

La composition recommandée validée par `config/release-manifest.yaml` est :

* Ohana-Platform 1.0.23 ;
* Ohana-Agent 1.11.1 ;
* Ohana-Vision 1.10.0.

`config/release-catalog.yaml` contient toutes les compositions officiellement
sélectionnables par Installer 1.8.0.

Elle déploie les configurations Agent pour DNS, NTP, MQTT, présence réseau,
DHCP, WireGuard, Télémétrie Home Assistant et Z-Wave. Le manifeste détermine également
les arguments exacts transmis aux unités systemd.

L'installation ou la mise à jour d'Ohana-Agent installe aussi la version
épinglée de `rclone` requise par le plugin de sauvegarde iCloud. L'archive
officielle est contrôlée avec sa somme SHA-256 avant que le binaire soit placé
dans `/usr/bin/rclone`. La connexion au compte Apple reste ensuite réalisée
depuis Vision et n'est jamais inscrite dans le manifeste Platform.

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


## Migrations de configuration

Lors d’une mise à jour, une configuration locale `shelly-telemetry.yaml` est
recopiée automatiquement vers `home-assistant-telemetry.yaml` si le nouveau
fichier n’existe pas encore.

Les compositions Platform à partir de 1.0.16 déploient le fichier
`teleinformation.example.yaml` vers
`/etc/ohana-agent/plugins/teleinformation.yaml`. À partir de Platform 1.0.20,
le profil Téléinformation prend également en charge le mode HTTP direct avec
l’add-on `teleinfo2mqtt Ohana`.

Installer conserve toujours les configurations locales existantes. Une
composition historique ne reçoit que les fichiers et arguments déclarés par
son propre manifeste immuable.
