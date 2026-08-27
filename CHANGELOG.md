# CHANGELOG

Toutes les évolutions notables de ce projet seront documentées dans ce fichier.

Le format s'inspire de **Keep a Changelog** et respecte le **Versioning Sémantique (SemVer)**.

---

# [Unreleased] — Intégration de Shizune PWA

## Ajouté

- support des composants web statiques déclarés par le manifeste Platform ;
- téléchargement et extraction sûre de l’archive Shizune ;
- validation de `version.json` et installation dans `/var/www/shizune` ;
- désinstallation du répertoire statique Shizune avec les autres composants.

## Sécurité

- refus des chemins absolus, traversals et liens dans les archives PWA ;
- aucune réponse API privée n’est mise en cache par Installer.

# [1.11.1] — Migration Wake-on-LAN Katsuyu — 2026-08-25

## Corrigé

- À partir d’Agent 1.18.0, l’installation et la mise à jour ajoutent
  `administration.jobs.wake_on_lan` à `shikamaru.yaml` lorsqu’elle est absente.
- La migration reprend les valeurs de référence Agent et reste désactivée par
  défaut tant qu’aucune adresse MAC Wake-on-LAN n’est configurée.

## Compatibilité

- Une section `wake_on_lan` déjà présente est conservée intégralement, y compris
  ses valeurs locales ; la migration est idempotente.
- Les Agents 1.17.x conservent uniquement le contrat jobs/TLS existant et ne
  reçoivent pas de section Wake-on-LAN qu’ils ne connaissent pas.

# [1.11.0] — Migration du canal Shizune — 2026-08-24

## Ajouté

- À partir d’Agent 1.24.0, l’installation et la mise à jour ajoutent le listener
  compagnon HTTPS `8767` à `shikamaru.yaml` lorsqu’il est absent.
- Le listener réutilise l’autorité et le certificat TLS déjà provisionnés pour
  Katsuyu ; aucun nouveau système d’authentification n’est introduit.

## Compatibilité

- Les valeurs locales et une éventuelle section `administration.companion`
  existante sont conservées sans modification.
- APNs reste désactivé tant que les identifiants Apple et la clé `.p8` réels ne
  sont pas configurés ; la migration est idempotente.

# [1.10.0] — Provisionnement TLS Katsuyu — 2026-08-20

## Ajouté

- À partir d'Agent 1.17.0, l'installation et la mise à jour provisionnent le
  listener worker HTTPS dédié sur le port 8766.
- Installer génère une autorité locale privée, un certificat serveur limité à
  `infra-01.ohana.lan` et `192.168.1.10`, ainsi qu'un jeton worker distinct.

## Sécurité

- La clé de l'autorité reste accessible uniquement à root ; Agent ne reçoit
  que le certificat public, son certificat serveur et sa clé de service.
- Les permissions des secrets et du répertoire TLS sont réconciliées à chaque
  installation, et des matériaux partiels provoquent un échec explicite.

## Validation

- 297 tests réussis, dont une validation OpenSSL réelle de la chaîne serveur,
  Ruff et contrôles de distribution validés.

# [1.9.7] — Restauration des archives INFRA-01 compressées — 2026-08-13

## Corrigé

- La restauration détecte automatiquement les tar compressés produits par
  Agent 1.14.3, tout en conservant la compatibilité avec les archives tar non
  compressées antérieures.

## Validation

- 294 tests réussis, Ruff et contrôles de distribution validés.

# [1.9.6] — Accès sauvegarde aux données Vision — 2026-08-13

## Corrigé

- `ohana-agent.service` rejoint le groupe supplémentaire `ohana-vision` afin
  que la sauvegarde INFRA-01 puisse lire la configuration et la base Vision,
  sans rendre ces données accessibles aux autres comptes du système.
- Une mise à jour manuelle réconcilie cette permission même lorsque les paquets
  Agent et Vision utilisent déjà les versions recommandées.

## Validation

- 293 tests réussis, Ruff et contrôles de distribution validés.

# [1.9.5] — Identité visuelle du terminal — 2026-08-13

## Corrigé

- Le grand lettrage ASCII générique est remplacé par une adaptation terminal du
  logo officiel Ohana, associant le symbole à quatre pétales au mot-symbole.
- Les pétales reprennent leurs couleurs officielles : bleu en haut, vert à
  gauche, orange à droite et rouge en bas.
- Les couleurs ANSI sont limitées aux terminaux compatibles et respectent
  `NO_COLOR` ; les sorties redirigées restent sans séquences de contrôle.

## Validation

- 292 tests réussis, Ruff et contrôles de distribution validés.

# [1.9.4] — Restauration iCloud et alignement du logo — 2026-08-13

## Corrigé

- Le mot-symbole et son sous-titre sont alignés visuellement avec le centre du
  cadre du menu, y compris lorsque leurs largeurs ont une parité différente.
- Le menu de restauration ne demande plus inutilement l'Apple ID avant de
  laisser la commande réutiliser la connexion iCloud existante.
- L'absence du dossier distant des sauvegardes INFRA-01 est présentée comme une
  absence de sauvegarde, sans exposer l'erreur technique `directory not found`.

## Validation

- 290 tests réussis, Ruff et contrôles de distribution validés.

# [1.9.3] — Vérification au démarrage et connexion iCloud — 2026-08-13

## Modifié

- `sudo ohana` vérifie désormais immédiatement si une nouvelle version
  d'Ohana-Installer est disponible, propose son installation avant d'afficher
  le menu, puis redémarre automatiquement ce menu avec la nouvelle version.

## Corrigé

- La restauration iCloud réutilise automatiquement la connexion enregistrée
  dans `/etc/ohana-agent/rclone.conf`. Les identifiants Apple ne sont demandés
  que sur une machine neuve ou dépourvue de configuration iCloud locale.

## Validation

- 288 tests réussis, Ruff et contrôles de distribution validés.

# [1.9.2] — Sélection des sauvegardes iCloud — 2026-08-13

## Ajouté

- Le choix d'une sauvegarde iCloud affiche désormais les sauvegardes INFRA-01
  valides, de la plus récente à la plus ancienne, avec date, versions et
  identifiant technique, puis propose une sélection numérotée.
- Les parcours « dernière sauvegarde » et « choisir une sauvegarde » indiquent
  explicitement lorsqu'aucune sauvegarde INFRA-01 n'est disponible dans iCloud.

## Corrigé

- Le mot-symbole Ohana est centré comme un bloc unique : ses cinq lignes
  partagent désormais la même origine horizontale dans le terminal.

## Validation

- 284 tests réussis, Ruff et contrôles de distribution validés.

# [1.9.1] — Identité age pendant la mise à jour directe — 2026-08-13

## Corrigé

- Le parcours direct `sudo ohana update` crée, valide et synchronise désormais
  l'identité `age` d'INFRA-01 après la migration de `backup.yaml`, sans imposer
  un second lancement du menu interactif.

# [1.9.0] — Identité age et menus contextualisés — 2026-08-13

## Ajouté

- Une installation neuve installe `age` si nécessaire, crée l'identité
  d'INFRA-01 et enregistre sa copie de récupération dans iCloud dès que la
  connexion rclone est disponible.
- Au lancement du menu sur une installation existante, Installer valide une
  seule fois l'identité locale, la répare si nécessaire et la synchronise.
- Une restauration iCloud récupère automatiquement l'identité avant le
  déchiffrement et l'installe sur la nouvelle machine ; aucune clé ne doit être
  saisie dans ce parcours.
- Le passage à Installer 1.9.0 migre atomiquement le fichier `backup.yaml`
  existant : seuls les anciens paramètres `age` d'INFRA-01 sont remplacés par
  les chemins gérés, sans perdre les cibles, secrets, horaires ni rétention.

## Modifié

- Le menu principal s'ouvre sur un mot-symbole Ohana en ASCII, centré et
  compatible avec sa largeur de 72 colonnes.
- Chacune des huit actions du menu dispose de sa propre illustration ASCII
  compacte pour identifier visuellement le parcours sélectionné.
- Le menu des capacités diagnostique automatiquement DHCP et la référence
  temporelle, affiche leur état, puis ne propose pour chacune que l'action
  opposée : activer ou désactiver.
- Le menu interactif ne présente plus les compositions historiques : il reste
  limité aux neuf versions antérieures les plus récentes portant le statut
  `supported`.
- Les entrées `legacy` restent dans le catalogue et demeurent sélectionnables
  par leur version exacte pour restaurer une sauvegarde existante.

## Validation

- 279 tests réussis, Ruff et contrôles de distribution validés.

# [1.8.1] — Visibilité de l'utilitaire age — 2026-08-13

## Corrigé

- Le manifeste affiché mentionne désormais les utilitaires requis par le
  profil, notamment `age`.
- Le résultat du provisionnement indique si chaque utilitaire a été installé
  ou s'il était déjà présent.

# [1.8.0] — Capacités et restauration d'INFRA-01 — 2026-08-13

## Ajouté

- Le profil Platform provisionne les capacités DHCP avec dnsmasq et référence
  temporelle avec Chrony, ainsi que l'utilitaire `age`.
- Le menu distingue installation, restauration, mise à jour, capacités et
  configuration réseau.
- La commande `ohana restore` reconstruit INFRA-01 depuis une sauvegarde locale
  ou iCloud et réinstalle la composition Agent/Vision sauvegardée.
- La restauration vérifie la taille, le SHA-256, le périmètre des chemins et la
  correspondance entre le manifeste public et le descripteur chiffré.

## Sécurité

- Les traitements temporaires sont refusés hors `tmpfs`.
- L'application des fichiers est atomique avec retour arrière si dnsmasq ou
  Chrony refuse la configuration restaurée.
- Le DHCP reste inactif après restauration et exige la confirmation que
  l'ancien serveur DHCP a été désactivé.

## Validation

- 269 tests réussis, Ruff, manifeste Platform et contrats validés.

# [1.7.3] — Installation rclone inter-systèmes — 2026-08-11

## Corrigé

- Le binaire rclone est d'abord copié dans un fichier temporaire situé dans
  son répertoire de destination, puis remplacé atomiquement. L'installation
  fonctionne ainsi lorsque `/tmp` et `/usr` appartiennent à des systèmes de
  fichiers différents et ne déclenche plus l'erreur `EXDEV`.

## Qualité

- Le test d'installation exige désormais que le fichier intermédiaire et la
  destination partagent le même répertoire parent.

# [1.7.2] — Dépendance rclone vérifiée — 2026-08-11

## Ajouté

- Installation automatique de rclone lors de l'installation d'Agent et lors
  d'une mise à jour qui remplace Agent.
- Sélection des archives Linux AMD64, ARM64, ARMv7 ou ARMv6 et validation de
  leur SHA-256 officiel avant installation atomique dans `/usr/bin/rclone`.

## Modifié

- La préparation de rclone précède l'arrêt des services afin de ne pas allonger
  leur indisponibilité réseau.

# [1.7.1] — Stockage persistant des composants — 2026-08-10

## Modifié

- Les unités systemd d'Ohana-Agent et d'Ohana-Vision déclarent désormais leurs
  répertoires d'état avec `StateDirectory` et le mode `0750`.
- systemd crée `/var/lib/ohana-agent` et `/var/lib/ohana-vision` avec le
  propriétaire de service attendu avant leur démarrage, afin d'héberger
  l'outbox Agent et la base d'observations Vision.

## Qualité

- Tests des unités générées pour Agent et Vision, lint et suite complète
  validés avant publication.

---

# [1.7.0] — Mise à jour automatique — 2026-08-01

## Ajouté

- Option interactive d'activation et de désactivation de la mise à jour automatique.
- Commande scriptable `ohana automatic-update enable|disable|status`.
- Timer systemd quotidien à 04:00, persistant et décalé aléatoirement jusqu'à
  30 minutes, avec journaux centralisés dans systemd-journald.
- Mode `ohana update --if-needed` utilisé par le timer.

## Modifié

- Une exécution automatique ne réconcilie plus les configurations et ne redémarre
  plus Agent ou Vision lorsque Installer et les composants sont déjà à jour.
- La désinstallation supprime également le timer et son service.

## Qualité

- Tests des unités systemd, des commandes enable/disable et du chemin non disruptif.
- 247 tests réussis.

---

# [1.6.1] — Application fiable des réservations DHCP — 2026-07-31

## Corrigé

- Déploiement du helper `ohana-agent-dhcp-reload-helper` fourni par
  Ohana-Agent 1.11.1 afin de supprimer uniquement les anciens baux incompatibles
  avec une réservation nouvelle ou modifiée.
- Conservation de l’ancien rechargement dnsmasq pour les compositions
  historiques utilisant Ohana-Agent 1.11.0.
- Unité `ohana-agent.service` compatible avec l’appel du helper NetworkManager
  restreint par sudo.

## Modifié

- Composition recommandée alignée sur Ohana-Platform 1.0.23,
  Ohana-Agent 1.11.1 et Ohana-Vision 1.10.0.
- Retrait du catalogue des versions Platform qui ne possèdent aucune release
  GitHub téléchargeable.

## Qualité

- Validation des unités systemd modernes et historiques.
- 243 tests réussis.

---

# [1.6.0] — Interface interactive — 2026-07-30

## Ajouté

- Ouverture directe du menu interactif avec `ohana` sans argument.
- Installation ou mise à jour automatique de la composition recommandée.
- Liste sélectionnable des compositions antérieures publiées par Platform.
- Formulaire réseau prérempli pour l’adresse, le masque, la passerelle et les DNS.
- Commande autonome `ohana network` pour lire ou modifier NetworkManager sans
  installer Agent ou Vision.
- Acceptation des masques IPv4 en notation CIDR ou décimale dans le formulaire.

## Sécurité

- Retour automatique NetworkManager après 180 secondes sans confirmation.
- Confirmation supplémentaire avant une composition historique ou une
  rétrogradation.
- Conservation intégrale des commandes CLI pour les scripts et le dépannage.

## Qualité

- Interface sans dépendance graphique supplémentaire, adaptée au terminal local et à SSH.
- 242 tests réussis.

---

# [1.5.0] — Catalogue des couples Agent/Vision — 2026-07-30

## Ajouté

- Commande `ohana versions` listant les compositions publiées par Ohana-Platform.
- Sélection d’une composition avec `--platform-version`.
- Sélection directe d’un couple officiel avec `--agent-version` et
  `--vision-version`.
- Téléchargement du manifeste immuable de la release Platform correspondant au
  couple choisi.
- Option `--allow-downgrade` pour une rétrogradation explicitement sélectionnée.

## Sécurité

- Refus de tout couple Agent/Vision absent du catalogue officiel.
- Vérification de concordance entre le catalogue, la release Platform et son
  manifeste avant le téléchargement des composants.
- Conservation des sélecteurs de version après l’auto-mise à jour de l’Installer.

## Modifié

- Composition recommandée alignée sur Ohana-Platform 1.0.22, Ohana-Agent 1.11.0
  et Ohana-Vision 1.10.0.

## Qualité

- 230 tests réussis.

---

# [1.0.13] — Déploiement du Lot C — 2026-07-30

## Ajouté

- Préparation du helper NetworkManager privilégié et d’une règle `sudoers`
  strictement limitée à ce helper.
- Provisionnement IPv4 initial facultatif avec `--network-interface`,
  `--network-address`, `--network-gateway` et `--network-dns`, ou mode DHCP.
- Activation automatique de l’administration réseau Agent lorsque
  NetworkManager et le helper installé sont disponibles.

## Modifié

- Composition alignée sur Ohana-Platform 1.0.21, Ohana-Agent 1.11.0 et
  Ohana-Vision 1.10.0.

## Qualité

- Validation du sous-réseau, de la passerelle et des DNS avant application.
- Vérification de la règle `sudoers` avec `visudo` lorsqu’il est disponible.

---

# [1.0.12] — Déploiement du Lot B — 2026-07-30

## Modifié

- Composition alignée sur Ohana-Platform 1.0.20, Ohana-Agent 1.10.0 et
  Ohana-Vision 1.9.0.
- Déploiement du profil Téléinformation comprenant le mode HTTP direct vers
  Agent et maintien de la configuration historique lors d’une mise à jour.
- Conservation des métadonnées de plages horaires dans le fichier
  d’infrastructure administré par Agent.

## Compatibilité

- Les configurations locales Téléinformation existantes ne sont pas écrasées.
- Une nouvelle installation déploie le plugin direct désactivé jusqu’à la
  définition du jeton commun avec l’add-on `teleinfo2mqtt Ohana`.

---

# [1.0.11] — Déploiement du Lot A — 2026-07-30

## Modifié

- Manifestes Agent 1.9.0 et Vision 1.8.0.
- Migration automatique de `shelly-telemetry.yaml` vers `home-assistant-telemetry.yaml`.

---

# [1.0.10] - 2026-07-29

## Modifié

* Manifeste aligné sur Ohana-Platform 1.0.18.
* Ohana-Agent reste aligné sur 1.8.1.
* Ohana-Vision est aligné sur 1.7.1.
* La validation des noms DNS des réservations DHCP est désormais effectuée
  dans Vision avant l’appel à Agent.

## Validation

* Concordance stricte avec le manifeste officiel de Platform.

# [1.0.9] - 2026-07-29

## Modifié

* Manifeste aligné sur Ohana-Platform 1.0.17.
* Ohana-Agent aligné sur 1.8.1.
* Ohana-Vision reste aligné sur 1.7.0.
* La mise à jour Téléinformation n’exige aucun nouveau fichier de
  configuration : elle corrige la logique de fraîcheur du plugin Agent.

## Validation

* Concordance stricte avec le manifeste officiel de Platform.

# [1.0.8] - 2026-07-29

## Modifié

* Manifeste aligné sur Ohana-Platform 1.0.16.
* Ohana-Agent aligné sur 1.8.0.
* Ohana-Vision aligné sur 1.7.0.
* Déploiement de `teleinformation.example.yaml` vers
  `plugins/teleinformation.yaml`.
* Ajout de `--teleinformation-config` au service systemd Agent.

## Validation

* Concordance stricte avec le manifeste officiel de Platform.

# [1.0.7] - 2026-07-29

## Modifié

* Manifeste aligné sur Ohana-Platform 1.0.15.
* Ohana-Agent aligné sur 1.7.5.
* Ohana-Vision reste aligné sur 1.6.3.
* Tests d'auto-mise à jour préparés pour une future version 1.0.8.

## Validation

* Concordance stricte avec le manifeste officiel de Platform.
* 199 tests réussis.

# [1.0.6] - 2026-07-29

## Modifié

* Manifeste aligné sur Ohana-Platform 1.0.14.
* Ohana-Agent aligné sur 1.7.4.
* Ohana-Vision aligné sur 1.6.3.
* Tests d'auto-mise à jour préparés pour une future version 1.0.7.

## Validation

* Concordance stricte avec le manifeste officiel de Platform.
* 199 tests réussis.

# [1.0.5] - 2026-07-28

## Ajouté

* Déploiement des configurations Z-Wave, WireGuard et Shelly Telemetry.
* Ajout des arguments `--zwave-config`, `--wireguard-config` et
  `--shelly-telemetry-config` au service systemd d'Ohana-Agent.

## Modifié

* Manifeste aligné sur Ohana-Platform 1.0.13.
* Ohana-Agent aligné sur 1.7.3.
* Ohana-Vision aligné sur 1.6.2.
* Tests d'auto-mise à jour préparés pour une future version 1.0.6.

## Validation

* 199 tests réussis.

# [1.0.4] - 2026-07-27

## Ajouté

* Déploiement de la configuration du plugin de présence réseau d'Ohana-Agent.
* Déploiement de la configuration du plugin DHCP d'Ohana-Agent.
* Ajout des arguments `--network-config` et `--dhcp-config` à l'unité
  systemd d'Ohana-Agent.

## Modifié

* Manifest aligné sur Ohana-Platform 1.0.7, Ohana-Agent 1.5.0 et
  Ohana-Vision 1.4.0.
* Version publique de la commande `ohana` alignée sur la version du package.
* Tests d'auto-mise à jour préparés pour une future version 1.0.5.

## Validation

* Vérification des sept configurations Agent déployées par le manifeste.
* Vérification de la ligne de commande systemd complète d'Ohana-Agent.
* 199 tests réussis.

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
