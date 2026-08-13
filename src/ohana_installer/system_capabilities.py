"""Provisionnement des capacités système déclarées par Ohana-Platform."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from ohana_installer.manifest import InstallationProfile, SystemCapability

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]

APT_GET = "/usr/bin/apt-get"
DPKG_QUERY = "/usr/bin/dpkg-query"
SYSTEMCTL = "/usr/bin/systemctl"


class CapabilityProvisioningError(RuntimeError):
    """Échec d'installation ou de gestion d'une capacité système."""


@dataclass(frozen=True)
class ProvisionedCapability:
    """Résultat du provisionnement d'une capacité."""

    capability: SystemCapability
    package_created: bool


@dataclass(frozen=True)
class ProvisionedUtility:
    """Résultat du provisionnement d'un utilitaire système."""

    package: str
    display_name: str
    package_created: bool


@dataclass(frozen=True)
class ProfileProvisioningResult:
    """Résultat complet du provisionnement d'un profil de machine."""

    capabilities: tuple[ProvisionedCapability, ...] = ()
    utilities: tuple[ProvisionedUtility, ...] = ()

    def __iter__(self):
        """Conserver l'itération historique sur les capacités."""

        return iter(self.capabilities)


@dataclass(frozen=True)
class CapabilityStatus:
    """État local observable d'une capacité système."""

    identifier: str
    name: str
    implementation: str
    installed: bool
    configured: bool
    active: bool
    state: str


KNOWN_CAPABILITIES = {
    "dhcp": SystemCapability(
        identifier="dhcp",
        name="Attribution des adresses IP",
        implementation="dnsmasq",
        package="dnsmasq",
        service="dnsmasq.service",
        activation="explicit",
    ),
    "time-reference": SystemCapability(
        identifier="time-reference",
        name="Référence temporelle",
        implementation="chrony",
        package="chrony",
        service="chrony.service",
        activation="automatic",
    ),
}

CONFIGURATION_PATHS = {
    "dhcp": Path("/etc/dnsmasq.d/00-ohana.conf"),
    "time-reference": Path("/etc/chrony/chrony.conf"),
}

UTILITY_DISPLAY_NAMES = {
    "age": "Utilitaire de chiffrement",
}

CHRONY_CONFIGURATION = """\
#################################################
# Ohana-House — Référence temporelle INFRA-01
#################################################

pool fr.pool.ntp.org iburst

driftfile /var/lib/chrony/chrony.drift
makestep 1.0 3
rtcsync
allow 192.168.1.0/24
local stratum 10
logdir /var/log/chrony
"""


def _run(
    command: Sequence[str],
    *,
    command_runner: CommandRunner = subprocess.run,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = command_runner(
            tuple(command),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise CapabilityProvisioningError(
            f"Impossible d'exécuter {command[0]} : {error}"
        ) from error
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "erreur inconnue").strip()
        raise CapabilityProvisioningError(f"La commande {' '.join(command)} a échoué : {detail}")
    return completed


def package_is_installed(
    package: str,
    *,
    command_runner: CommandRunner = subprocess.run,
) -> bool:
    """Indiquer si un paquet Debian est installé."""

    completed = _run(
        (DPKG_QUERY, "-W", "-f=${Status}", package),
        command_runner=command_runner,
        check=False,
    )
    return completed.returncode == 0 and completed.stdout.strip() == "install ok installed"


def _systemctl(
    *arguments: str,
    command_runner: CommandRunner = subprocess.run,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return _run(
        (SYSTEMCTL, *arguments),
        command_runner=command_runner,
        check=check,
    )


def provision_profile(
    profile: InstallationProfile | None,
    *,
    command_runner: CommandRunner = subprocess.run,
) -> ProfileProvisioningResult:
    """Installer les capacités d'un profil avec une activation maîtrisée."""

    if profile is None:
        return ProfileProvisioningResult()

    created = {
        capability.identifier: not package_is_installed(
            capability.package,
            command_runner=command_runner,
        )
        for capability in profile.capabilities
    }
    missing = tuple(
        capability for capability in profile.capabilities if created[capability.identifier]
    )
    missing_utilities = tuple(
        utility
        for utility in profile.utilities
        if not package_is_installed(utility, command_runner=command_runner)
    )
    created_utilities = {utility: utility in missing_utilities for utility in profile.utilities}
    protected_services = tuple(capability.service for capability in missing)

    try:
        for service in protected_services:
            _systemctl("mask", "--runtime", service, command_runner=command_runner)
        if missing or missing_utilities:
            _run((APT_GET, "update"), command_runner=command_runner)
            _run(
                (
                    APT_GET,
                    "install",
                    "--yes",
                    "--no-install-recommends",
                    *(capability.package for capability in missing),
                    *missing_utilities,
                ),
                command_runner=command_runner,
            )
    finally:
        for service in protected_services:
            _systemctl(
                "unmask",
                "--runtime",
                service,
                command_runner=command_runner,
                check=False,
            )

    results = tuple(
        ProvisionedCapability(
            capability=capability,
            package_created=created[capability.identifier],
        )
        for capability in profile.capabilities
    )

    for result in results:
        capability = result.capability
        if capability.activation == "explicit" and result.package_created:
            _systemctl(
                "disable",
                "--now",
                capability.service,
                command_runner=command_runner,
                check=False,
            )
        elif capability.activation == "automatic":
            if result.package_created and capability.identifier == "time-reference":
                _configure_chrony(command_runner=command_runner)
            _systemctl(
                "enable",
                "--now",
                capability.service,
                command_runner=command_runner,
            )

    utilities = tuple(
        ProvisionedUtility(
            package=utility,
            display_name=UTILITY_DISPLAY_NAMES.get(utility, "Utilitaire système"),
            package_created=created_utilities[utility],
        )
        for utility in profile.utilities
    )

    return ProfileProvisioningResult(
        capabilities=results,
        utilities=utilities,
    )


def profile_requires_provisioning(
    profile: InstallationProfile | None,
    *,
    command_runner: CommandRunner = subprocess.run,
) -> bool:
    """Indiquer si au moins un paquet du profil est absent."""

    return bool(
        profile
        and (
            any(
                not package_is_installed(utility, command_runner=command_runner)
                for utility in profile.utilities
            )
            or any(
                not package_is_installed(
                    capability.package,
                    command_runner=command_runner,
                )
                for capability in profile.capabilities
            )
        )
    )


def _configure_chrony(
    *,
    command_runner: CommandRunner = subprocess.run,
) -> None:
    """Remplacer la configuration de distribution lors d'une installation neuve."""

    destination = CONFIGURATION_PATHS["time-reference"]
    backup = destination.with_name(f"{destination.name}.distribution")
    temporary_path: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=".ohana-chrony-",
            delete=False,
        ) as temporary:
            temporary.write(CHRONY_CONFIGURATION)
            temporary_path = Path(temporary.name)
        os.chmod(temporary_path, 0o644)
        _run(
            ("/usr/sbin/chronyd", "-p", "-f", str(temporary_path)),
            command_runner=command_runner,
        )
        if destination.is_file() and not backup.exists():
            shutil.copy2(destination, backup)
        os.replace(temporary_path, destination)
    except OSError as error:
        raise CapabilityProvisioningError(
            f"Impossible de configurer Chrony dans {destination} : {error}"
        ) from error
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)


def capability_status(
    capability: SystemCapability,
    *,
    command_runner: CommandRunner = subprocess.run,
) -> CapabilityStatus:
    """Lire l'état installé, configuré et actif d'une capacité."""

    installed = package_is_installed(capability.package, command_runner=command_runner)
    configuration_path = CONFIGURATION_PATHS.get(capability.identifier)
    configured = bool(configuration_path and configuration_path.is_file())
    active = False
    if installed:
        completed = _systemctl(
            "is-active",
            capability.service,
            command_runner=command_runner,
            check=False,
        )
        active = completed.returncode == 0 and completed.stdout.strip() == "active"

    if not installed:
        state = "Absente"
    elif active:
        state = "Active"
    elif configured:
        state = "Configurée, inactive"
    else:
        state = "Installée, non configurée"

    return CapabilityStatus(
        identifier=capability.identifier,
        name=capability.name,
        implementation=capability.implementation,
        installed=installed,
        configured=configured,
        active=active,
        state=state,
    )


def local_capability_statuses(
    *,
    command_runner: CommandRunner = subprocess.run,
) -> tuple[CapabilityStatus, ...]:
    """Retourner les états des capacités système connues d'INFRA-01."""

    return tuple(
        capability_status(capability, command_runner=command_runner)
        for capability in KNOWN_CAPABILITIES.values()
    )


def activate_capability(
    identifier: str,
    *,
    command_runner: CommandRunner = subprocess.run,
) -> None:
    """Valider puis activer une capacité installée."""

    try:
        capability = KNOWN_CAPABILITIES[identifier]
    except KeyError as error:
        raise CapabilityProvisioningError(f"Capacité inconnue : {identifier}.") from error
    if not package_is_installed(capability.package, command_runner=command_runner):
        raise CapabilityProvisioningError(f"La capacité {capability.name} n'est pas installée.")
    configuration_path = CONFIGURATION_PATHS.get(identifier)
    if configuration_path is not None and not configuration_path.is_file():
        raise CapabilityProvisioningError(
            f"La configuration attendue est absente : {configuration_path}."
        )
    if identifier == "dhcp":
        _run(("/usr/sbin/dnsmasq", "--test"), command_runner=command_runner)
    _systemctl(
        "enable",
        "--now",
        capability.service,
        command_runner=command_runner,
    )


def deactivate_capability(
    identifier: str,
    *,
    command_runner: CommandRunner = subprocess.run,
) -> None:
    """Arrêter et désactiver une capacité connue."""

    try:
        capability = KNOWN_CAPABILITIES[identifier]
    except KeyError as error:
        raise CapabilityProvisioningError(f"Capacité inconnue : {identifier}.") from error
    _systemctl(
        "disable",
        "--now",
        capability.service,
        command_runner=command_runner,
    )
