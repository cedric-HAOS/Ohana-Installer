"""Commande de mise à jour."""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, NoReturn

from ohana_installer.administration import (
    AdministrationPreparation,
    AdministrationPreparationError,
    activate_administration,
    prepare_administration,
)
from ohana_installer.age_identity import AgeIdentityError, ensure_local_identity
from ohana_installer.commands.install import (
    AGENT_COMMAND_NAME,
    AGENT_ENVIRONMENT_PATH,
    AGENT_IDENTIFIER,
    VISION_COMMAND_NAME,
    VISION_ENVIRONMENT_PATH,
    VISION_IDENTIFIER,
    ConfigurationInstallationError,
    _check_services,
    _component_version,
    _display_manifest,
    _display_profile_provisioning,
    _download_components,
    _download_configurations,
    _enable_services,
    _ensure_service_accounts,
    _generate_services,
    _install_agent,
    _install_configurations,
    _install_shizune,
    _install_vision,
    _load_official_manifest,
    _load_selected_manifest,
    _reload_systemd,
    _start_services,
    display_administration,
    display_downloaded_configurations,
    display_environment,
    display_generated_services,
    display_installed_configurations,
    display_service_names,
    display_service_statuses,
    failure_message,
    failure_types,
)
from ohana_installer.configuration_migrations import (
    ConfigurationMigrationError,
    migrate_backup_configuration,
)
from ohana_installer.confirmation import confirm_action
from ohana_installer.environment import run_environment_checks
from ohana_installer.github import (
    DownloadedComponent,
    DownloadError,
    GitHubRelease,
    GitHubReleaseAsset,
    discover_latest_release,
    download_release_asset,
)
from ohana_installer.manifest import (
    ComponentManifest,
    ManifestError,
    PlatformManifest,
)
from ohana_installer.python_package import (
    InstalledPythonComponent,
    PackageInstallationError,
    inspect_installed_component,
    upgrade_wheel,
    verify_component_command,
)
from ohana_installer.rclone import RcloneInstallationError, ensure_rclone
from ohana_installer.release_selection import (
    ReleaseSelection,
    add_release_selection_arguments,
    release_selection_arguments,
    selection_from_args,
)
from ohana_installer.static_site import (
    InstalledStaticComponent,
    StaticSiteInstallationError,
    inspect_static_component,
)
from ohana_installer.system_account import SystemAccountError
from ohana_installer.system_capabilities import (
    CapabilityProvisioningError,
    profile_requires_provisioning,
    provision_profile,
)
from ohana_installer.systemd import (
    GeneratedSystemdService,
    InstalledSystemdService,
    SystemdCommandError,
    SystemdGenerationError,
    SystemdInstallationError,
    install_generated_services,
    stop_systemd_service,
)
from ohana_installer.version import __version__

UPDATE_ERROR = 3
INSTALLER_REPOSITORY = "cedric-HAOS/Ohana-Installer"
INSTALLER_COMMAND_NAME = "ohana"
INSTALLER_DISTRIBUTION_NAME = "ohana_installer"
type InstallerUpdateResult = Literal["current", "updated", "declined"]

COMPONENT_RUNTIMES = {
    AGENT_IDENTIFIER: (
        AGENT_ENVIRONMENT_PATH,
        AGENT_COMMAND_NAME,
    ),
    VISION_IDENTIFIER: (
        VISION_ENVIRONMENT_PATH,
        VISION_COMMAND_NAME,
    ),
}
InstalledComponent = InstalledPythonComponent | InstalledStaticComponent


def configure_parser(subparsers: argparse._SubParsersAction) -> None:
    """Configurer la sous-commande update."""

    parser = subparsers.add_parser(
        "update",
        help="Mettre à jour les composants officiels Ohana.",
        description="Mettre à jour les composants officiels Ohana.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Accepter automatiquement les confirmations.",
    )
    parser.add_argument(
        "--if-needed",
        action="store_true",
        help=(
            "Ne rien modifier lorsque l'Installer, Agent et Vision utilisent "
            "déjà les dernières versions officielles."
        ),
    )
    parser.add_argument(
        "--installer-already-checked",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    add_release_selection_arguments(parser)
    parser.add_argument(
        "--allow-downgrade",
        action="store_true",
        help=(
            "Autoriser explicitement l'installation d'un couple plus ancien "
            "que les versions actuellement installées."
        ),
    )
    parser.set_defaults(command_handler=run)


def _stop_services(
    generated_services: tuple[GeneratedSystemdService, ...],
) -> None:
    """Arrêter les services systemd avant leur mise à jour."""

    for generated_service in generated_services:
        stop_systemd_service(generated_service.path.name)


def _replace_services(
    generated_services: tuple[GeneratedSystemdService, ...],
) -> tuple[InstalledSystemdService, ...]:
    """Installer ou remplacer les unités systemd."""

    return install_generated_services(
        generated_services,
        replace=True,
    )


def _inspect_installed_components(
    manifest: PlatformManifest,
) -> dict[str, InstalledComponent | None]:
    """Détecter les versions actuellement installées."""

    installed_components: dict[
        str,
        InstalledComponent | None,
    ] = {}

    for component in manifest.components:
        if component.package.type == "static":
            try:
                installed_components[component.identifier] = inspect_static_component(component)
            except StaticSiteInstallationError as error:
                raise PackageInstallationError(str(error)) from error
            continue
        try:
            environment_path, command_name = COMPONENT_RUNTIMES[component.identifier]
        except KeyError as error:
            raise PackageInstallationError(
                f"Composant non pris en charge par la mise à jour : {component.identifier}."
            ) from error

        installed_components[component.identifier] = inspect_installed_component(
            environment_path=environment_path,
            command_name=command_name,
            component_name=component.name,
        )

    return installed_components


def _display_update_plan(
    manifest: PlatformManifest,
    installed_components: dict[
        str,
        InstalledComponent | None,
    ],
) -> None:
    """Afficher les versions installées et les versions cibles."""

    print("Plan de mise à jour :")

    for component in manifest.components:
        installed_component = installed_components[component.identifier]
        installed_version = (
            installed_component.version if installed_component is not None else "non installé"
        )
        already_current = (
            installed_component is not None and installed_component.version == component.version
        )
        suffix = " (déjà à jour, conservé)" if already_current else ""
        print(f"  {component.name}: {installed_version} → {component.version}{suffix}")


def _versions_are_current(
    manifest: PlatformManifest,
    installed_components: dict[
        str,
        InstalledComponent | None,
    ],
) -> bool:
    return all(
        installed_components[component.identifier] is not None
        and installed_components[component.identifier].version == component.version
        for component in manifest.components
    )


def _components_requiring_update(
    manifest: PlatformManifest,
    installed_components: dict[
        str,
        InstalledComponent | None,
    ],
) -> tuple[ComponentManifest, ...]:
    """Sélectionner uniquement les composants absents ou obsolètes."""

    return tuple(
        component
        for component in manifest.components
        if installed_components[component.identifier] is None
        or installed_components[component.identifier].version != component.version
    )


def _numeric_version(version: str) -> tuple[int, int, int] | None:
    parts = version.split(".")

    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None

    return tuple(int(part) for part in parts)


def _release_version(release: GitHubRelease) -> str:
    """Extraire une version SemVer simple depuis un tag de release."""

    if not release.tag_name.startswith("v"):
        raise DownloadError(
            f"La release {release.repository} utilise un tag invalide : {release.tag_name}."
        )

    version = release.tag_name.removeprefix("v")

    if _numeric_version(version) is None:
        raise DownloadError(
            f"La release {release.repository} utilise une version invalide : {release.tag_name}."
        )

    return version


def _find_installer_wheel(
    release: GitHubRelease,
    version: str,
) -> GitHubReleaseAsset:
    """Trouver l'unique wheel de l'Installer dans une release."""

    prefix = f"{INSTALLER_DISTRIBUTION_NAME}-{version}-"
    matching_assets = tuple(
        asset
        for asset in release.assets
        if asset.name.startswith(prefix) and asset.name.endswith(".whl")
    )

    if len(matching_assets) != 1:
        raise DownloadError(
            f"La release {release.repository}@{release.tag_name} doit "
            f"contenir exactement un wheel {prefix}*.whl."
        )

    return matching_assets[0]


def _prepare_installer_update(
    temporary_path: Path,
    *,
    assume_yes: bool,
) -> InstallerUpdateResult:
    """Mettre à niveau l'Installer dans son environnement courant."""

    print("Vérification d'Ohana-Installer...")

    release = discover_latest_release(INSTALLER_REPOSITORY)
    target_version = _release_version(release)
    installed_version = _numeric_version(__version__)
    available_version = _numeric_version(target_version)

    if installed_version is None or available_version is None:
        raise DownloadError(
            "Impossible de comparer la version installée "
            f"{__version__} à la release {release.tag_name}."
        )

    print(f"  Version installée : {__version__}")
    print(f"  Dernière version  : {target_version}")

    if available_version <= installed_version:
        print("✓ Ohana-Installer est déjà à jour.")
        return "current"

    print()

    if not confirm_action(
        "Mettre à jour Ohana-Installer avant de poursuivre ?",
        assume_yes=assume_yes,
    ):
        print("Mise à jour annulée.")
        return "declined"

    asset = _find_installer_wheel(release, target_version)
    wheel_path = download_release_asset(
        asset,
        temporary_path / asset.name,
    )

    print(f"✓ Ohana-Installer {target_version} téléchargé et vérifié.")

    upgrade_wheel(
        wheel_path,
        python_executable=sys.executable,
    )

    installed_component = verify_component_command(
        environment_path=Path(sys.prefix),
        command_name=INSTALLER_COMMAND_NAME,
        expected_version=target_version,
        component_name="Ohana-Installer",
    )

    print(f"✓ Ohana-Installer {installed_component.version} mis à jour.")
    return "updated"


def _restart_update(
    *,
    assume_yes: bool,
    if_needed: bool = False,
    selection: ReleaseSelection | None = None,
    allow_downgrade: bool = False,
) -> NoReturn:
    """Reprendre la commande avec la nouvelle version de l'Installer."""

    arguments = [
        sys.executable,
        "-m",
        "ohana_installer",
        "update",
    ]

    if assume_yes:
        arguments.append("--yes")

    if if_needed:
        arguments.append("--if-needed")

    arguments.extend(release_selection_arguments(selection))

    if allow_downgrade:
        arguments.append("--allow-downgrade")

    print("Reprise de la mise à jour avec la nouvelle version...")
    os.execv(sys.executable, arguments)


def _reject_downgrades(
    manifest: PlatformManifest,
    installed_components: dict[
        str,
        InstalledPythonComponent | None,
    ],
    *,
    allow_downgrade: bool = False,
) -> None:
    """Refuser une régression qui n'a pas été explicitement autorisée."""

    if allow_downgrade:
        return

    for component in manifest.components:
        installed_component = installed_components[component.identifier]

        if installed_component is None:
            continue

        installed_version = _numeric_version(installed_component.version)
        target_version = _numeric_version(component.version)

        if (
            installed_version is not None
            and target_version is not None
            and installed_version > target_version
        ):
            raise PackageInstallationError(
                f"La release Platform cible {component.name} "
                f"{component.version}, plus ancien que la version "
                f"installée {installed_component.version}. "
                "Utilisez --allow-downgrade pour confirmer explicitement "
                "cette rétrogradation."
            )


_UPDATE_FAILURES: tuple[tuple[tuple[type[Exception], ...], str], ...] = (
    ((SystemdCommandError,), "Commande systemd impossible"),
    ((SystemdInstallationError,), "Mise à jour systemd impossible"),
    ((SystemdGenerationError,), "Génération systemd impossible"),
    ((DownloadError,), "Téléchargement impossible"),
    ((ManifestError,), "Le manifeste officiel est invalide"),
    (
        (
            CapabilityProvisioningError,
            AgeIdentityError,
            ConfigurationMigrationError,
            PackageInstallationError,
            RcloneInstallationError,
        ),
        "Mise à jour impossible",
    ),
    ((ConfigurationInstallationError,), "Mise à jour des configurations impossible"),
    ((AdministrationPreparationError,), "Préparation de l'administration impossible"),
    ((SystemAccountError,), "Vérification des comptes système impossible"),
)


@dataclass(frozen=True)
class _UpdatePlan:
    """Components that differ from the target release, and their manifest."""

    manifest: PlatformManifest
    components_to_update: tuple[ComponentManifest, ...]

    @property
    def update_manifest(self) -> PlatformManifest:
        return replace(self.manifest, components=self.components_to_update)

    @property
    def updated_identifiers(self) -> set[str]:
        return {component.identifier for component in self.components_to_update}


def run(args: argparse.Namespace) -> int:
    """Exécuter la commande update."""

    assume_yes = bool(args.yes)
    if_needed = bool(args.if_needed)
    allow_downgrade = bool(args.allow_downgrade)

    try:
        release_selection = selection_from_args(args)
        if allow_downgrade and release_selection is None:
            raise ManifestError(
                "--allow-downgrade exige une version Platform ou un couple Agent/Vision explicite."
            )
    except ManifestError as error:
        print(f"✗ Sélection de version invalide : {error}")
        return UPDATE_ERROR

    if not display_environment(
        run_environment_checks(),
        "L'environnement ne permet pas de poursuivre la mise à jour.",
    ):
        return UPDATE_ERROR

    try:
        if not _update_installer_first(
            args,
            release_selection=release_selection,
            assume_yes=assume_yes,
            if_needed=if_needed,
            allow_downgrade=allow_downgrade,
        ):
            return 0

        print()
        print("Téléchargement du catalogue et du manifeste officiels...")

        with tempfile.TemporaryDirectory(
            prefix="ohana-installer-update-",
        ) as temporary_directory:
            temporary_path = Path(temporary_directory)
            plan = _plan_update(
                temporary_path,
                release_selection,
                if_needed=if_needed,
                allow_downgrade=allow_downgrade,
            )

            if plan is None:
                return 0

            print()

            if not confirm_action(
                "Appliquer cette mise à jour Ohana ?",
                assume_yes=assume_yes,
            ):
                print("Mise à jour annulée.")
                return 0

            print()
            if not _apply_update(plan, temporary_path):
                return UPDATE_ERROR
    except failure_types(_UPDATE_FAILURES) as error:
        print(failure_message(error, _UPDATE_FAILURES))
        return UPDATE_ERROR

    print()
    _display_update_summary(plan)
    return 0


def _update_installer_first(
    args: argparse.Namespace,
    *,
    release_selection: ReleaseSelection | None,
    assume_yes: bool,
    if_needed: bool,
    allow_downgrade: bool,
) -> bool:
    """Self-update Installer when needed; return False when the user declined."""
    installer_update: InstallerUpdateResult = "current"
    if not bool(args.installer_already_checked):
        with tempfile.TemporaryDirectory(
            prefix="ohana-installer-self-update-",
        ) as installer_temporary_directory:
            installer_update = _prepare_installer_update(
                Path(installer_temporary_directory),
                assume_yes=assume_yes,
            )

    if installer_update == "declined":
        return False

    if installer_update == "updated":
        _restart_update(
            assume_yes=assume_yes,
            if_needed=if_needed,
            selection=release_selection,
            allow_downgrade=allow_downgrade,
        )

    if migrate_backup_configuration():
        print()
        print("✓ /etc/ohana-agent/plugins/backup.yaml migré vers l'identité age gérée.")

    return True


def _plan_update(
    temporary_path: Path,
    release_selection: ReleaseSelection | None,
    *,
    if_needed: bool,
    allow_downgrade: bool,
) -> _UpdatePlan | None:
    """Compare the installed platform to the release; None when nothing to do."""
    if release_selection is None:
        manifest = _load_official_manifest(temporary_path)
    else:
        manifest = _load_selected_manifest(temporary_path, release_selection)

    print("✓ Catalogue et manifeste téléchargés et validés.")
    print()

    _display_manifest(manifest)

    print()

    installed_components = _inspect_installed_components(manifest)
    _display_update_plan(manifest, installed_components)

    versions_are_current = _versions_are_current(manifest, installed_components)
    profile_needs_provisioning = profile_requires_provisioning(manifest.profile)

    if versions_are_current and not profile_needs_provisioning and if_needed:
        print()
        print("✓ Ohana-Installer, Ohana-Agent et Ohana-Vision sont déjà à jour.")
        print("Aucun service n'a été redémarré.")
        return None

    if versions_are_current:
        print()
        print(
            "Ohana-Agent et Ohana-Vision utilisent déjà "
            "les versions de la dernière release Platform."
        )
        print(
            "La composition Platform va néanmoins être réconciliée "
            "(configurations et services systemd)."
        )

    _reject_downgrades(
        manifest,
        installed_components,
        allow_downgrade=allow_downgrade,
    )
    return _UpdatePlan(
        manifest=manifest,
        components_to_update=_components_requiring_update(
            manifest,
            installed_components,
        ),
    )


def _apply_update(plan: _UpdatePlan, temporary_path: Path) -> bool:
    """Apply the plan, then return whether every service is active again."""
    manifest = plan.manifest
    updated_identifiers = plan.updated_identifiers

    if manifest.profile is not None:
        print(f"Réconciliation du profil {manifest.profile.name}...")
        _display_profile_provisioning(provision_profile(manifest.profile))
        print()

    downloaded_components = _download_updated_components(plan, temporary_path)

    print()
    print("Téléchargement des configurations...")

    downloaded_configurations = _download_configurations(manifest, temporary_path)
    display_downloaded_configurations(downloaded_configurations)

    print()
    print("Vérification des comptes système...")

    for system_account in _ensure_service_accounts(manifest):
        print(f"✓ Groupe système {system_account.group_name} prêt.")
        print(f"✓ Compte système {system_account.username} prêt.")

    print()
    print("Génération des services systemd...")

    generated_services = _generate_services(manifest, temporary_path)
    display_generated_services(generated_services)

    print()
    print("Vérification des fichiers de configuration...")

    display_installed_configurations(_install_configurations(downloaded_configurations))

    if AGENT_IDENTIFIER in updated_identifiers:
        print()
        print("Préparation des sauvegardes iCloud...")

        rclone_version = ensure_rclone()
        print(f"✓ rclone {rclone_version} installé pour les sauvegardes iCloud.")
        recipient = ensure_local_identity()
        print(f"✓ Identité age INFRA-01 préparée ({recipient[:16]}…).")

    print()
    print("Arrêt des services systemd...")

    _stop_services(generated_services)

    for generated_service in generated_services:
        print(f"✓ {generated_service.path.name} arrêté.")

    _replace_packages(updated_identifiers, downloaded_components)

    print()
    print("Préparation de l'administration graphique...")

    administration = prepare_administration(
        agent_version=_component_version(manifest, AGENT_IDENTIFIER)
    )
    display_administration(administration)
    return _restart_services(generated_services, administration)


def _download_updated_components(
    plan: _UpdatePlan,
    temporary_path: Path,
) -> tuple[DownloadedComponent, ...]:
    print("Téléchargement des composants...")

    if not plan.components_to_update:
        print("✓ Aucun package Python à télécharger.")
        return ()

    downloaded_components = _download_components(plan.update_manifest, temporary_path)

    for downloaded_component in downloaded_components:
        component = downloaded_component.component
        print(f"✓ {component.name} {component.version} téléchargé.")

    return downloaded_components


def _replace_packages(
    updated_identifiers: set[str],
    downloaded_components: tuple[DownloadedComponent, ...],
) -> None:
    if AGENT_IDENTIFIER in updated_identifiers:
        print()
        print("Mise à jour d'Ohana-Agent...")

        installed_agent = _install_agent(downloaded_components, replace=True)

        print(f"✓ {installed_agent.name} {installed_agent.version} mis à jour.")

    if VISION_IDENTIFIER in updated_identifiers:
        print()
        print("Mise à jour d'Ohana-Vision...")

        installed_vision = _install_vision(downloaded_components, replace=True)

        print(f"✓ {installed_vision.name} {installed_vision.version} mis à jour.")

    if "shizune" in updated_identifiers:
        print()
        print("Mise à jour de Shizune...")
        installed_shizune = _install_shizune(downloaded_components, replace=True)
        print(
            f"✓ {installed_shizune.name} {installed_shizune.version} "
            f"mis à jour dans {installed_shizune.installation_path}."
        )


def _restart_services(
    generated_services: tuple[GeneratedSystemdService, ...],
    administration: AdministrationPreparation,
) -> bool:
    print()
    print("Mise à jour des services systemd...")

    installed_services = _replace_services(generated_services)

    for installed_service in installed_services:
        destination = installed_service.destination_path

        if installed_service.created:
            print(f"✓ {destination} installé.")
        elif installed_service.updated:
            print(f"✓ {destination} remplacé.")
        else:
            print(f"✓ {destination} conservé (déjà identique).")

    print()
    print("Rechargement de systemd...")

    _reload_systemd()

    print("✓ Configuration systemd rechargée.")
    activate_administration(administration)

    if administration.dhcp_enabled:
        print("✓ Surveillance du rechargement DHCP activée.")

    print()
    print("Activation des services systemd...")

    _enable_services(installed_services)
    display_service_names(installed_services, "activé")

    print()
    print("Redémarrage des services systemd...")

    _start_services(installed_services)
    display_service_names(installed_services, "démarré")

    print()
    print("Vérification des services systemd...")

    return display_service_statuses(
        _check_services(installed_services), stop_at_first_failure=False
    )


def _display_update_summary(plan: _UpdatePlan) -> None:
    updated_identifiers = plan.updated_identifiers

    if not updated_identifiers:
        print("Composition Ohana Platform réconciliée ; services redémarrés et vérifiés.")
    elif updated_identifiers == {AGENT_IDENTIFIER, VISION_IDENTIFIER}:
        print("Ohana-Agent et Ohana-Vision sont mis à jour, redémarrés et vérifiés.")
    else:
        component_name = plan.components_to_update[0].name
        print(f"{component_name} est mis à jour, redémarré et vérifié.")
