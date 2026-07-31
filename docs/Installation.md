# Installation d'Ohana sur Raspberry Pi

Ce guide installe **Ohana-Installer 1.6.0**, puis Ohana-Agent et Ohana-Vision
depuis leurs releases GitHub officielles.

## Configuration recommandée

* Raspberry Pi 3, 4 ou 5 avec système 64 bits ;
* Raspberry Pi OS 64 bits basé sur Debian Trixie ;
* Python 3.13 ou supérieur ;
* systemd ;
* un compte autorisé à utiliser `sudo` ;
* un accès Internet à GitHub et à PyPI pendant l'installation.

Raspberry Pi OS Bookworm fournit normalement une version de Python trop ancienne
pour les releases Ohana actuelles. Pour passer de Bookworm à Trixie, Raspberry Pi recommande une
nouvelle installation du système plutôt qu'une mise à niveau majeure sur place.

## 1. Vérifier le système

```bash
cat /etc/os-release
uname -m
python3 --version
```

Les valeurs attendues sont notamment :

* `VERSION_CODENAME=trixie` ;
* `aarch64` pour un système 64 bits ;
* Python 3.13 ou supérieur.

## 2. Mettre à jour Raspberry Pi OS

```bash
sudo apt update
sudo apt full-upgrade
sudo apt install -y ca-certificates curl python3.13 python3.13-venv
```

Redémarrer si une mise à jour du noyau ou du firmware le demande :

```bash
sudo reboot
```

## 3. Télécharger la release officielle

```bash
mkdir -p "$HOME/ohana-installer-1.6.0"
cd "$HOME/ohana-installer-1.6.0"

curl --fail --location --remote-name \
  https://github.com/cedric-HAOS/Ohana-Installer/releases/download/v1.6.0/ohana_installer-1.6.0-py3-none-any.whl
curl --fail --location --remote-name \
  https://github.com/cedric-HAOS/Ohana-Installer/releases/download/v1.6.0/ohana_installer-1.6.0.tar.gz
curl --fail --location --remote-name \
  https://github.com/cedric-HAOS/Ohana-Installer/releases/download/v1.6.0/SHA256SUMS
```

## 4. Vérifier les artefacts

```bash
sha256sum --check SHA256SUMS
```

Les deux lignes doivent se terminer par `OK`. Ne pas poursuivre si une somme ne
correspond pas.

## 5. Installer Ohana-Installer dans un environnement isolé

L'utilisation d'un environnement virtuel évite de modifier le Python géré par
Raspberry Pi OS.

```bash
sudo python3.13 -m venv /opt/ohana-installer
sudo /opt/ohana-installer/bin/python -m pip install \
  ./ohana_installer-1.6.0-py3-none-any.whl
sudo ln -sfn /opt/ohana-installer/bin/ohana /usr/local/bin/ohana
```

Vérifier la commande :

```bash
ohana --version
```

Résultat attendu :

```text
ohana 1.6.0
```

## 6. Ouvrir Ohana-Installer

```bash
sudo ohana
```

Le menu propose :

```text
1. Installer ou mettre à jour Agent et Vision
2. Installer une composition antérieure
3. Configurer le réseau d’INFRA-01
4. Quitter
```

Choisir **1** pour une installation neuve ou une mise à jour vers la composition
recommandée. Les commandes explicites restent disponibles, notamment :

```bash
sudo ohana install
sudo ohana update
```

L'installateur :

1. vérifie Linux, systemd, Python, pip, les privilèges et l'accès à GitHub ;
2. télécharge le catalogue publié par la dernière release d’Ohana-Platform ;
3. sélectionne la composition recommandée ou celle demandée explicitement ;
4. vérifie cryptographiquement le catalogue, le manifeste et tous les téléchargements ;
5. affiche les versions d'Ohana-Agent et d'Ohana-Vision ;
6. télécharge les configurations Agent, dont DNS, NTP, MQTT, présence réseau
   et DHCP ;
7. demande une confirmation avant de modifier le système ;
8. installe et démarre les deux services systemd.

Répondre `oui` après avoir vérifié les versions affichées. Pour une installation
automatisée, la confirmation peut être acceptée explicitement :

```bash
sudo ohana install --yes
```


### Choisir une version différente

Lister les couples publiés :

```bash
ohana versions
```

Installer la composition Platform 1.0.20 :

```bash
sudo ohana install --platform-version 1.0.20
```

Installer le couple Agent 1.10.0 / Vision 1.9.0 :

```bash
sudo ohana install \
  --agent-version 1.10.0 \
  --vision-version 1.9.0
```

Le couple doit être déclaré dans le catalogue Platform.

## 7. Configurer graphiquement l'infrastructure

Avec les releases compatibles d'Ohana-Agent, Ohana-Vision et Ohana-Installer,
la configuration courante est accessible directement dans Vision :

1. ouvrir `http://ADRESSE_IP_DU_RASPBERRY_PI:8000` ;
2. choisir **Configuration** dans le menu ;
3. utiliser **Baux DHCP** pour la plage, les options, les réservations et les
   baux actifs ;
4. utiliser **Architecture** pour les équipements, services et liaisons ;
5. utiliser **Plugins** pour administrer DNS, NTP, MQTT et DHCP ;
6. vérifier le récapitulatif puis confirmer l'application.

Le navigateur ne lit et n'écrit aucun fichier YAML. Vision transmet les
modifications à l'API locale authentifiée d'Agent. Celui-ci valide les documents,
effectue des écritures atomiques et refuse une configuration DHCP que
`dnsmasq --test` n'accepte pas.

L'installateur conserve toujours les fichiers sous `/etc/ohana-agent` et
`/etc/ohana-vision` lors des mises à jour.

## 8. Vérifier l'installation

```bash
sudo systemctl is-active ohana-agent.service
sudo systemctl is-active ohana-vision.service

/opt/ohana-agent/venv/bin/ohana-agent --version
/opt/ohana-vision/venv/bin/ohana-vision --version
```

Les deux services doivent répondre `active`. L'interface d'Ohana-Vision est
ensuite disponible par défaut à l'adresse :

```text
http://ADRESSE_IP_DU_RASPBERRY_PI:8000
```

Pour connaître l'adresse IP du Raspberry Pi :

```bash
hostname -I
```

## Mise à jour

```bash
sudo ohana update
```

La commande vérifie d'abord la dernière release stable d'Ohana-Installer. Si
une version plus récente existe, elle remplace le package dans
`/opt/ohana-installer`, contrôle la nouvelle version puis reprend automatiquement
la commande. Elle utilise ensuite la composition Platform recommandée, ou celle
sélectionnée avec `--platform-version` ou le couple Agent/Vision, compare les
versions installées, affiche le plan de mise à jour et demande confirmation.

Chaque package déjà à la version cible est conservé sans téléchargement ni
réinstallation. La commande réconcilie néanmoins les fichiers de configuration
manquants et les unités systemd avec le manifeste Platform, puis redémarre et
vérifie les services. Les configurations locales existantes ne sont pas écrasées.
Les rétrogradations restent refusées par défaut. Une composition historique
explicitement choisie peut être appliquée avec `--allow-downgrade`.

L'option `--yes` est disponible pour une automatisation volontaire :

```bash
sudo ohana update --yes
```

La transition depuis Ohana-Installer 1.0.0 vers 1.0.1 doit être réalisée une
seule fois avec la procédure manuelle de ce guide, car la version 1.0.0 ne connaît
pas encore ce mécanisme. À partir de la version 1.0.1, `ohana update` met également
à jour l'Installer sans créer de seconde installation.

## Désinstallation

```bash
sudo ohana uninstall
```

La commande affiche les services et répertoires concernés, puis demande
confirmation. Les fichiers de configuration sous `/etc/ohana-agent` et
`/etc/ohana-vision` sont conservés.

## Diagnostic

État détaillé des services :

```bash
sudo systemctl status ohana-agent.service --no-pager
sudo systemctl status ohana-vision.service --no-pager
```

Derniers journaux :

```bash
sudo journalctl -u ohana-agent.service -n 100 --no-pager
sudo journalctl -u ohana-vision.service -n 100 --no-pager
```

## Références système

* [Documentation officielle de Raspberry Pi OS](https://www.raspberrypi.com/documentation/computers/os.html)
* [Package Debian Trixie python3.13-venv](https://packages.debian.org/trixie/python3.13-venv)


## Adresse statique d’INFRA-01

Dans le menu `sudo ohana`, choisir **3. Configurer le réseau d’INFRA-01**. Les
valeurs actives sont préremplies. Saisir l’adresse, le masque ou préfixe, la
passerelle et les DNS, puis confirmer la nouvelle connexion. Sans confirmation,
l’ancienne configuration est restaurée automatiquement après 180 secondes.

Cette opération ne télécharge et ne réinstalle aucun composant. La commande
explicite équivalente reste disponible :

```bash
sudo ohana network --yes \
  --interface eth0 \
  --address 192.168.1.10/24 \
  --gateway 192.168.1.1 \
  --dns 192.168.1.11 \
  --dns 192.168.1.12
```

Le helper NetworkManager nécessite une installation compatible avec Ohana-Agent
1.11.0 ou une version ultérieure.
