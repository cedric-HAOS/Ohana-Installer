"""Tests de préparation du flux d'administration graphique."""

from __future__ import annotations

from pathlib import Path

from ohana_installer.administration import (
    DHCP_RELOAD_PATH_NAME,
    AdministrationPreparation,
    activate_administration,
    prepare_administration,
)


def make_configuration_files(
    temporary_path: Path,
) -> tuple[Path, Path, Path]:
    """Créer les trois configurations nécessaires."""
    agent_directory = temporary_path / "ohana-agent"
    vision_directory = temporary_path / "ohana-vision"
    agent_directory.mkdir()
    vision_directory.mkdir()
    agent_configuration = agent_directory / "shikamaru.yaml"
    infrastructure = agent_directory / "infrastructure.yaml"
    vision_configuration = vision_directory / "vision.yaml"
    agent_configuration.write_text(
        "version: 1\n",
        encoding="utf-8",
    )
    infrastructure.write_text(
        "infrastructure:\n  id: ohana-house\n  name: Ohana House\n",
        encoding="utf-8",
    )
    vision_configuration.write_text(
        "name: Ohana Vision\n",
        encoding="utf-8",
    )
    return (
        agent_configuration,
        infrastructure,
        vision_configuration,
    )


def test_prepare_administration_migrates_existing_configuration(
    tmp_path: Path,
) -> None:
    (
        agent_configuration,
        infrastructure,
        vision_configuration,
    ) = make_configuration_files(tmp_path)
    agent_token = agent_configuration.parent / "management.token"
    vision_token = vision_configuration.parent / "management.token"

    result = prepare_administration(
        agent_configuration_path=agent_configuration,
        agent_infrastructure_path=infrastructure,
        agent_token_path=agent_token,
        vision_configuration_path=vision_configuration,
        vision_token_path=vision_token,
        dnsmasq_executable=tmp_path / "missing-dnsmasq",
        dnsmasq_configuration_directory=(tmp_path / "dnsmasq.d"),
        systemd_directory=tmp_path / "systemd",
        require_linux=False,
        secure_ownership=False,
    )

    assert result.configured is True
    assert result.dhcp_enabled is False
    assert result.token_created is True
    assert agent_token.read_text(encoding="utf-8") == (vision_token.read_text(encoding="utf-8"))
    assert "administration:\n  enabled: true" in agent_configuration.read_text(encoding="utf-8")
    assert "    enabled: false" in agent_configuration.read_text(encoding="utf-8")
    assert "agent:\n  administration_enabled: true" in vision_configuration.read_text(
        encoding="utf-8"
    )


def test_prepare_administration_configures_dnsmasq_once(
    tmp_path: Path,
) -> None:
    (
        agent_configuration,
        infrastructure,
        vision_configuration,
    ) = make_configuration_files(tmp_path)
    dnsmasq = tmp_path / "dnsmasq"
    dnsmasq.touch()
    dnsmasq_directory = tmp_path / "dnsmasq.d"
    dnsmasq_directory.mkdir()
    systemd_directory = tmp_path / "systemd"
    arguments = {
        "agent_configuration_path": agent_configuration,
        "agent_infrastructure_path": infrastructure,
        "agent_token_path": (agent_configuration.parent / "management.token"),
        "vision_configuration_path": vision_configuration,
        "vision_token_path": (vision_configuration.parent / "management.token"),
        "dnsmasq_executable": dnsmasq,
        "dnsmasq_configuration_directory": (dnsmasq_directory),
        "systemd_directory": systemd_directory,
        "require_linux": False,
        "secure_ownership": False,
    }

    first = prepare_administration(**arguments)
    second = prepare_administration(**arguments)

    assert first.dhcp_enabled is True
    assert len(first.units_installed) == 2
    assert second.token_created is False
    assert agent_configuration.read_text(encoding="utf-8").count("administration:") == 1
    assert (systemd_directory / "ohana-dhcp-reload.path").is_file()
    assert "PathChanged=/run/ohana-agent/dhcp-reload.request" in (
        systemd_directory / "ohana-dhcp-reload.path"
    ).read_text(encoding="utf-8")


def test_prepare_administration_migrates_legacy_dnsmasq_name(
    tmp_path: Path,
) -> None:
    (
        agent_configuration,
        infrastructure,
        vision_configuration,
    ) = make_configuration_files(tmp_path)
    dnsmasq = tmp_path / "dnsmasq"
    dnsmasq.touch()
    dnsmasq_directory = tmp_path / "dnsmasq.d"
    dnsmasq_directory.mkdir()
    legacy = dnsmasq_directory / "00-ohanna.conf"
    legacy.write_text(
        "interface=eth0\n",
        encoding="utf-8",
    )

    prepare_administration(
        agent_configuration_path=agent_configuration,
        agent_infrastructure_path=infrastructure,
        agent_token_path=(agent_configuration.parent / "management.token"),
        vision_configuration_path=vision_configuration,
        vision_token_path=(vision_configuration.parent / "management.token"),
        dnsmasq_executable=dnsmasq,
        dnsmasq_configuration_directory=dnsmasq_directory,
        systemd_directory=tmp_path / "systemd",
        require_linux=False,
        secure_ownership=False,
    )

    corrected = dnsmasq_directory / "00-ohana.conf"
    assert corrected.read_text(encoding="utf-8") == ("interface=eth0\n")
    assert not legacy.exists()


def test_activate_administration_starts_path_unit(
    monkeypatch,
) -> None:
    enabled: list[str] = []
    started: list[str] = []
    monkeypatch.setattr(
        "ohana_installer.administration.enable_systemd_service",
        enabled.append,
    )
    monkeypatch.setattr(
        "ohana_installer.administration.start_systemd_service",
        started.append,
    )

    activate_administration(
        AdministrationPreparation(
            configured=True,
            dhcp_enabled=True,
            token_created=True,
        )
    )

    assert enabled == [DHCP_RELOAD_PATH_NAME]
    assert started == [DHCP_RELOAD_PATH_NAME]


def test_prepare_administration_secures_plugin_configurations(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (
        agent_configuration,
        infrastructure,
        vision_configuration,
    ) = make_configuration_files(tmp_path)
    plugins_directory = agent_configuration.parent / "plugins"
    plugins_directory.mkdir()

    for filename in ("dns.yaml", "ntp.yaml", "mqtt.yaml"):
        (plugins_directory / filename).write_text(
            "enabled: true\n",
            encoding="utf-8",
        )

    secured_paths: list[tuple[Path, str, int]] = []
    monkeypatch.setattr(
        "ohana_installer.administration._secure_mutable_path",
        lambda path, *, group_name, mode: secured_paths.append((path, group_name, mode)),
    )

    prepare_administration(
        agent_configuration_path=agent_configuration,
        agent_infrastructure_path=infrastructure,
        agent_token_path=(agent_configuration.parent / "management.token"),
        vision_configuration_path=vision_configuration,
        vision_token_path=(vision_configuration.parent / "management.token"),
        dnsmasq_executable=tmp_path / "missing-dnsmasq",
        dnsmasq_configuration_directory=tmp_path / "dnsmasq.d",
        systemd_directory=tmp_path / "systemd",
        require_linux=False,
        secure_ownership=True,
    )

    assert (
        plugins_directory,
        "ohana-agent",
        0o770,
    ) in secured_paths

    for filename in ("dns.yaml", "ntp.yaml", "mqtt.yaml"):
        assert (
            plugins_directory / filename,
            "ohana-agent",
            0o660,
        ) in secured_paths
