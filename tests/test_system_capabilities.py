"""Tests du provisionnement des capacités système d'INFRA-01."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ohana_installer.commands.install import _display_profile_provisioning
from ohana_installer.manifest import InstallationProfile, SystemCapability
from ohana_installer.system_capabilities import (
    CONFIGURATION_PATHS,
    CapabilityProvisioningError,
    activate_capability,
    provision_profile,
)


def _profile() -> InstallationProfile:
    return InstallationProfile(
        identifier="infra-01",
        name="INFRA-01",
        utilities=("age",),
        capabilities=(
            SystemCapability(
                identifier="dhcp",
                name="Attribution des adresses IP",
                implementation="dnsmasq",
                package="dnsmasq",
                service="dnsmasq.service",
                activation="explicit",
            ),
            SystemCapability(
                identifier="time-reference",
                name="Référence temporelle",
                implementation="chrony",
                package="chrony",
                service="chrony.service",
                activation="automatic",
            ),
        ),
    )


def test_provision_profile_installs_packages_without_starting_dhcp(
    tmp_path: Path,
    monkeypatch,
) -> None:
    chrony_configuration = tmp_path / "chrony.conf"
    chrony_configuration.write_text("pool distribution.example\n", encoding="utf-8")
    monkeypatch.setitem(
        CONFIGURATION_PATHS,
        "time-reference",
        chrony_configuration,
    )
    commands: list[tuple[str, ...]] = []

    def run_command(command, **_kwargs):
        normalized = tuple(command)
        commands.append(normalized)
        if normalized[0].endswith("dpkg-query"):
            return subprocess.CompletedProcess(normalized, 1, "", "absent")
        return subprocess.CompletedProcess(normalized, 0, "", "")

    results = provision_profile(_profile(), command_runner=run_command)

    assert all(result.package_created for result in results)
    assert len(results.utilities) == 1
    assert results.utilities[0].package == "age"
    assert results.utilities[0].display_name == "Utilitaire de chiffrement"
    assert results.utilities[0].package_created is True
    assert (
        "/usr/bin/systemctl",
        "mask",
        "--runtime",
        "dnsmasq.service",
    ) in commands
    assert "allow 192.168.1.0/24" in chrony_configuration.read_text(encoding="utf-8")
    assert chrony_configuration.with_name("chrony.conf.distribution").is_file()
    assert (
        "/usr/bin/apt-get",
        "install",
        "--yes",
        "--no-install-recommends",
        "dnsmasq",
        "chrony",
        "age",
    ) in commands
    assert (
        "/usr/bin/systemctl",
        "disable",
        "--now",
        "dnsmasq.service",
    ) in commands
    assert (
        "/usr/bin/systemctl",
        "enable",
        "--now",
        "chrony.service",
    ) in commands


def test_activate_dhcp_validates_configuration_before_starting(
    tmp_path: Path,
    monkeypatch,
) -> None:
    configuration = tmp_path / "00-ohana.conf"
    configuration.write_text("dhcp-authoritative\n", encoding="utf-8")
    monkeypatch.setitem(CONFIGURATION_PATHS, "dhcp", configuration)
    commands: list[tuple[str, ...]] = []

    def run_command(command, **_kwargs):
        normalized = tuple(command)
        commands.append(normalized)
        if normalized[0].endswith("dpkg-query"):
            return subprocess.CompletedProcess(
                normalized,
                0,
                "install ok installed",
                "",
            )
        return subprocess.CompletedProcess(normalized, 0, "", "")

    activate_capability("dhcp", command_runner=run_command)

    assert commands[-2:] == [
        ("/usr/sbin/dnsmasq", "--test"),
        ("/usr/bin/systemctl", "enable", "--now", "dnsmasq.service"),
    ]


def test_provision_profile_preserves_an_existing_active_dhcp() -> None:
    commands: list[tuple[str, ...]] = []

    def run_command(command, **_kwargs):
        normalized = tuple(command)
        commands.append(normalized)
        if normalized[0].endswith("dpkg-query"):
            return subprocess.CompletedProcess(
                normalized,
                0,
                "install ok installed",
                "",
            )
        return subprocess.CompletedProcess(normalized, 0, "", "")

    results = provision_profile(_profile(), command_runner=run_command)

    assert (
        "/usr/bin/systemctl",
        "disable",
        "--now",
        "dnsmasq.service",
    ) not in commands
    assert results.utilities[0].package_created is False


def test_profile_provisioning_displays_existing_age(capsys) -> None:
    def run_command(command, **_kwargs):
        normalized = tuple(command)
        if normalized[0].endswith("dpkg-query"):
            return subprocess.CompletedProcess(
                normalized,
                0,
                "install ok installed",
                "",
            )
        return subprocess.CompletedProcess(normalized, 0, "", "")

    result = provision_profile(_profile(), command_runner=run_command)

    _display_profile_provisioning(result)

    output = capsys.readouterr().out
    assert "✓ Utilitaire de chiffrement : age déjà présent." in output


def test_invalid_chrony_configuration_does_not_replace_existing_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    chrony_configuration = tmp_path / "chrony.conf"
    chrony_configuration.write_text("pool existing.example\n", encoding="utf-8")
    monkeypatch.setitem(
        CONFIGURATION_PATHS,
        "time-reference",
        chrony_configuration,
    )

    def run_command(command, **_kwargs):
        normalized = tuple(command)
        if normalized[0].endswith("dpkg-query"):
            return subprocess.CompletedProcess(normalized, 1, "", "absent")
        if normalized[0] == "/usr/sbin/chronyd":
            return subprocess.CompletedProcess(normalized, 1, "", "invalid")
        return subprocess.CompletedProcess(normalized, 0, "", "")

    with pytest.raises(CapabilityProvisioningError, match="chronyd"):
        provision_profile(_profile(), command_runner=run_command)

    assert chrony_configuration.read_text(encoding="utf-8") == "pool existing.example\n"
