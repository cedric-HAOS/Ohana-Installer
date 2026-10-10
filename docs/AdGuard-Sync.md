# Capacité de synchronisation AdGuard

Disponible avec Installer 1.16.0, Agent 1.47.0, Vision 1.38.0 et Platform 1.0.144.
Shizune 0.5.0 conserve le rendu de la tuile **Synchro AdGuard**.

## Installation et mise à jour

Le profil INFRA-01 déclare `adguard-sync`, comme DHCP/dnsmasq et la référence
chrony. Le moteur utilise les archives officielles `bakito/adguardhome-sync`
**0.9.4**, vérifiées par des SHA-256 fixés dans Installer. Architectures : amd64,
arm64 et armv7. Ce moteur n’est pas installé par apt.

Installer prépare `/opt/adguardhome-sync/adguardhome-sync`, le service
`adguardhome-sync.service`, le timer toutes les cinq minutes et le modèle
`/etc/ohana-agent/adguardhome-sync.yaml`. Il conserve les fichiers et unités
existants ; il ne démarre pas une synchronisation neuve. Le cycle publie les
réservations DHCP vers l’origine, réplique AdGuard, puis vérifie la réplique.
Chrony et dnsmasq conservent leurs propres politiques d’activation.

## Administration dans Vision

Dans **Configuration → Plugins → Synchronisation AdGuard**, deux commandes
sont distinctes : le moteur de synchronisation et sa surveillance.

1. Dans **Moteur de synchronisation**, renseigner les URL et utilisateurs des
   deux instances ; fournir leurs mots de passe lors de la première configuration.
2. Choisir **Enregistrer et vérifier les accès**. Une réponse API incorrecte ou
   un accès refusé empêche le remplacement du fichier existant. Aucun cycle
   n’est exécuté pendant cette validation en lecture seule.
3. Choisir **Activer la synchronisation** et confirmer la copie de l’origine
   vers la réplique. Le timer est activé uniquement après validation des deux API.
4. Activer la surveillance, appliquer ses paramètres et tester. Le plugin
   contrôle ensuite le cycle, sa fraîcheur et les sections répliquées.

Les mots de passe enregistrés ne sont jamais renvoyés à Vision. Un champ laissé
vide conserve le secret existant. Les accès sont modifiables après arrêt du
moteur, pour éviter de changer sa configuration pendant un cycle.
La validation initiale ne dépend pas de la résolution `infra-01.ohana.lan` :
le premier cycle peut encore devoir créer cette réécriture.

Pour l’exploitation en terminal, les commandes existantes sont étendues :

```bash
sudo ohana capability status
sudo ohana capability activate adguard-sync
sudo ohana capability deactivate adguard-sync
```

Agent possède les paramètres et leur validation. Installer prépare une règle
sudoers limitée aux deux commandes fixes du helper Agent, sans argument de
chemin et sans commande shell libre. Vision relaie ces opérations ; Shizune
reste un affichage de supervision.

## Sauvegarde et restauration

Le fichier d’accès, le fichier du plugin, l’infrastructure et
`/etc/ohana-agent/adguard-sync-state.json` sont inclus dans l’archive chiffrée
récursive d’INFRA-01. Ce dernier contient uniquement le choix durable
`enabled`, pas les identifiants. Le binaire et les unités sont reconstruits par
Installer, et non copiés depuis une archive système.

Installer rétablit les permissions nécessaires à Agent. Si la sauvegarde
contient une activation déjà enregistrée, il valide à nouveau les accès avant
de réactiver le timer. Un choix désactivé est conservé. Les anciennes sauvegardes
sans état d’activation laissent le moteur inactif. Une configuration AdGuard
présente dans une ancienne sauvegarde déclenche aussi la reconstruction du
moteur, même si son ancien manifeste n’annonçait pas cette capacité.

Un échec d’activation restaurée entraîne le retour arrière des configurations
et des états de service précédents. La désactivation DHCP reste explicite,
comme avant. Les installations manuelles existantes sont adoptées sans arrêt
ni redémarrage du timer ; son choix d’activation est enregistré pour les
sauvegardes suivantes.

## Validation

Tests avec réseau et systemd simulés : installation neuve inactive, vérification
des archives et candidats avant remplacement, conservation des configurations
et unités, accès masqués, activation authentifiée, restauration active/inactive,
ancienne sauvegarde et retour arrière. Les archives officielles des trois
architectures sont également comparées aux empreintes fixées. Ces contrôles
ne valent pas confirmation d’un déploiement ou d’une restauration en production.
