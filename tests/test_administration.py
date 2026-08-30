"""Tests de préparation du flux d'administration graphique."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from ohana_installer import administration as administration_module
from ohana_installer.administration import (
    DHCP_RELOAD_HELPER_PATH,
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
    reload_service = (systemd_directory / "ohana-dhcp-reload.service").read_text(encoding="utf-8")
    assert f"ExecStart={DHCP_RELOAD_HELPER_PATH}" in reload_service
    assert "ReadWritePaths=/var/lib/misc" in reload_service


def test_prepare_administration_keeps_legacy_reload_for_agent_1_11_0(
    tmp_path: Path,
) -> None:
    agent_configuration, infrastructure, vision_configuration = make_configuration_files(tmp_path)
    dnsmasq = tmp_path / "dnsmasq"
    dnsmasq.touch()
    dnsmasq_directory = tmp_path / "dnsmasq.d"
    dnsmasq_directory.mkdir()
    systemd_directory = tmp_path / "systemd"

    prepare_administration(
        agent_configuration_path=agent_configuration,
        agent_infrastructure_path=infrastructure,
        agent_token_path=agent_configuration.parent / "management.token",
        vision_configuration_path=vision_configuration,
        vision_token_path=vision_configuration.parent / "management.token",
        dnsmasq_executable=dnsmasq,
        dnsmasq_configuration_directory=dnsmasq_directory,
        systemd_directory=systemd_directory,
        require_linux=False,
        secure_ownership=False,
        agent_version="1.11.0",
    )

    reload_service = (systemd_directory / "ohana-dhcp-reload.service").read_text(encoding="utf-8")
    assert "systemctl reload-or-restart dnsmasq.service" in reload_service
    assert str(DHCP_RELOAD_HELPER_PATH) not in reload_service


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


def test_prepare_administration_enables_network_helper(
    tmp_path: Path,
) -> None:
    agent_configuration, infrastructure, vision_configuration = make_configuration_files(tmp_path)
    nmcli = tmp_path / "nmcli"
    nmcli.write_text("#!/bin/sh\n", encoding="utf-8")
    nmcli.chmod(0o755)
    entrypoint = tmp_path / "ohana-agent-network-helper"
    entrypoint.write_text("#!/bin/sh\n", encoding="utf-8")
    entrypoint.chmod(0o755)
    helper = tmp_path / "local" / "ohana-network-helper"
    sudoers = tmp_path / "sudoers.d" / "ohana-agent-network"

    result = prepare_administration(
        agent_configuration_path=agent_configuration,
        agent_infrastructure_path=infrastructure,
        agent_token_path=agent_configuration.parent / "management.token",
        vision_configuration_path=vision_configuration,
        vision_token_path=vision_configuration.parent / "management.token",
        dnsmasq_executable=tmp_path / "missing-dnsmasq",
        dnsmasq_configuration_directory=tmp_path / "dnsmasq.d",
        systemd_directory=tmp_path / "systemd",
        require_linux=False,
        secure_ownership=False,
        network_helper_path=helper,
        network_sudoers_path=sudoers,
        network_entrypoint_path=entrypoint,
        nmcli_path=nmcli,
        visudo_path=tmp_path / "missing-visudo",
    )

    content = agent_configuration.read_text(encoding="utf-8")
    assert result.network_enabled is True
    assert "  network:\n    enabled: true" in content
    assert f"    helper_path: {helper.as_posix()}" in content


def test_prepare_administration_omits_network_for_legacy_agent(
    tmp_path: Path,
) -> None:
    agent_configuration, infrastructure, vision_configuration = make_configuration_files(tmp_path)

    result = prepare_administration(
        agent_configuration_path=agent_configuration,
        agent_infrastructure_path=infrastructure,
        agent_token_path=agent_configuration.parent / "management.token",
        vision_configuration_path=vision_configuration,
        vision_token_path=vision_configuration.parent / "management.token",
        dnsmasq_executable=tmp_path / "missing-dnsmasq",
        dnsmasq_configuration_directory=tmp_path / "dnsmasq.d",
        systemd_directory=tmp_path / "systemd",
        require_linux=False,
        secure_ownership=False,
        agent_version="1.7.3",
        nmcli_path=tmp_path / "nmcli",
        network_entrypoint_path=tmp_path / "missing-entrypoint",
    )

    content = agent_configuration.read_text(encoding="utf-8")
    assert result.network_enabled is False
    assert "  network:" not in content
    assert "  dhcp:" in content


def test_prepare_administration_removes_network_before_legacy_downgrade(
    tmp_path: Path,
) -> None:
    agent_configuration, infrastructure, vision_configuration = make_configuration_files(tmp_path)
    agent_configuration.write_text(
        """version: 1
administration:
  enabled: true
  host: 127.0.0.1
  port: 8765
  token_file: /etc/ohana-agent/management.token
  network:
    enabled: true
    helper_path: /usr/local/sbin/ohana-network-helper
    sudo_path: /usr/bin/sudo
    rollback_seconds: 90
  dhcp:
    enabled: false
""",
        encoding="utf-8",
    )

    prepare_administration(
        agent_configuration_path=agent_configuration,
        agent_infrastructure_path=infrastructure,
        agent_token_path=agent_configuration.parent / "management.token",
        vision_configuration_path=vision_configuration,
        vision_token_path=vision_configuration.parent / "management.token",
        dnsmasq_executable=tmp_path / "missing-dnsmasq",
        dnsmasq_configuration_directory=tmp_path / "dnsmasq.d",
        systemd_directory=tmp_path / "systemd",
        require_linux=False,
        secure_ownership=False,
        agent_version="1.10.0",
    )

    content = agent_configuration.read_text(encoding="utf-8")
    assert "  network:" not in content
    assert "  dhcp:\n    enabled: false" in content


def test_prepare_administration_enables_jobs_with_a_dedicated_tls_listener(
    tmp_path: Path,
    monkeypatch,
) -> None:
    agent_configuration, infrastructure, vision_configuration = make_configuration_files(tmp_path)
    openssl = tmp_path / "openssl"
    openssl.write_text("executable", encoding="utf-8")
    tls_directory = agent_configuration.parent / "tls"

    def fake_openssl(command: list[str]) -> None:
        for option in ("-keyout", "-out"):
            if option in command:
                target = Path(command[command.index(option) + 1])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f"generated {target.name}", encoding="utf-8")

    monkeypatch.setattr(administration_module, "_run_openssl", fake_openssl)

    result = prepare_administration(
        agent_configuration_path=agent_configuration,
        agent_infrastructure_path=infrastructure,
        agent_token_path=agent_configuration.parent / "management.token",
        vision_configuration_path=vision_configuration,
        vision_token_path=vision_configuration.parent / "management.token",
        dnsmasq_executable=tmp_path / "missing-dnsmasq",
        dnsmasq_configuration_directory=tmp_path / "dnsmasq.d",
        systemd_directory=tmp_path / "systemd",
        require_linux=False,
        secure_ownership=False,
        agent_version="1.17.0",
        worker_token_path=agent_configuration.parent / "katsuyu.token",
        worker_tls_directory=tls_directory,
        openssl_path=openssl,
    )

    content = agent_configuration.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)
    assert result.jobs_enabled is True
    assert result.worker_tls_enabled is True
    assert "  jobs:\n    enabled: true" in content
    assert "    worker_tls:\n      enabled: true" in content
    assert "      host: 0.0.0.0\n      port: 8766" in content
    assert (agent_configuration.parent / "katsuyu.token").stat().st_size > 32
    assert (tls_directory / "ca.crt").is_file()
    assert (tls_directory / "worker.crt").is_file()
    assert parsed["administration"]["jobs"]["worker_tls"]["port"] == 8766
    assert "wake_on_lan" not in parsed["administration"]["jobs"]


def test_wake_on_lan_batching_requires_agent_1_26_4() -> None:
    assert administration_module.supports_wake_on_lan_batching("1.26.3") is False
    assert administration_module.supports_wake_on_lan_batching("1.26.4") is True


def test_infra_log_source_requires_agent_1_26_12() -> None:
    assert administration_module.supports_infra_log_source("1.26.11") is False
    assert administration_module.supports_infra_log_source("1.26.12") is True


def test_infra_log_source_migration_is_additive_and_idempotent(tmp_path: Path) -> None:
    configuration = tmp_path / "shikamaru.yaml"
    configuration.write_text(
        """version: 1
administration:
  enabled: true
  jobs:
    enabled: true
    logs:
      enabled: true
      schedule: "15 4 * * *"
      sources:
        - linky-01
      window_hours: 12
      max_bytes_per_source: 1048576
      timeout_seconds: 600
    worker_tls:
      enabled: true
""",
        encoding="utf-8",
    )

    administration_module._ensure_agent_infra_log_source(configuration)
    administration_module._ensure_agent_infra_log_source(configuration)

    content = configuration.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)
    logs = parsed["administration"]["jobs"]["logs"]
    assert content.count("        - infra-01") == 1
    assert logs == {
        "enabled": True,
        "schedule": "15 4 * * *",
        "sources": ["infra-01", "linky-01"],
        "window_hours": 12,
        "max_bytes_per_source": 1048576,
        "timeout_seconds": 600,
    }


def test_infra_log_source_migration_repairs_misaligned_existing_sources(
    tmp_path: Path,
) -> None:
    configuration = tmp_path / "shikamaru.yaml"
    configuration.write_text(
        """version: 1
administration:
  enabled: true
  jobs:
    enabled: true
    logs:
      enabled: true
      schedule: "0 5 * * *"
      sources:
      - ha-01
      - linky-01
      - zwave-01
      window_hours: 24
    worker_tls:
      enabled: true
""",
        encoding="utf-8",
    )

    administration_module._ensure_agent_infra_log_source(configuration)
    administration_module._ensure_agent_infra_log_source(configuration)

    content = configuration.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)
    assert content.count("        - infra-01") == 1
    assert parsed["administration"]["jobs"]["logs"]["sources"] == [
        "infra-01",
        "ha-01",
        "linky-01",
        "zwave-01",
    ]


def test_infra_log_source_migration_does_not_write_invalid_yaml(tmp_path: Path) -> None:
    configuration = tmp_path / "shikamaru.yaml"
    original = """version: 1
administration:
  jobs:
    logs:
      sources:
        - linky-01
  invalid: [
"""
    configuration.write_text(original, encoding="utf-8")

    with pytest.raises(
        administration_module.AdministrationPreparationError,
        match="YAML invalide",
    ):
        administration_module._ensure_agent_infra_log_source(configuration)

    assert configuration.read_text(encoding="utf-8") == original


def test_prepare_administration_adds_wake_on_lan_for_agent_1_18_0(
    tmp_path: Path,
    monkeypatch,
) -> None:
    agent_configuration, infrastructure, vision_configuration = make_configuration_files(tmp_path)
    openssl = tmp_path / "openssl"
    openssl.write_text("executable", encoding="utf-8")
    tls_directory = agent_configuration.parent / "tls"

    def fake_openssl(command: list[str]) -> None:
        for option in ("-keyout", "-out"):
            if option in command:
                target = Path(command[command.index(option) + 1])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f"generated {target.name}", encoding="utf-8")

    monkeypatch.setattr(administration_module, "_run_openssl", fake_openssl)
    arguments = {
        "agent_configuration_path": agent_configuration,
        "agent_infrastructure_path": infrastructure,
        "agent_token_path": agent_configuration.parent / "management.token",
        "vision_configuration_path": vision_configuration,
        "vision_token_path": vision_configuration.parent / "management.token",
        "vision_companion_ca_path": vision_configuration.parent / "companion-ca.crt",
        "dnsmasq_executable": tmp_path / "missing-dnsmasq",
        "dnsmasq_configuration_directory": tmp_path / "dnsmasq.d",
        "systemd_directory": tmp_path / "systemd",
        "require_linux": False,
        "secure_ownership": False,
        "agent_version": "1.18.0",
        "worker_token_path": agent_configuration.parent / "katsuyu.token",
        "worker_tls_directory": tls_directory,
        "openssl_path": openssl,
    }

    prepare_administration(**arguments)
    prepare_administration(**arguments)

    content = agent_configuration.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)
    wake_on_lan = parsed["administration"]["jobs"]["wake_on_lan"]
    assert content.count("    wake_on_lan:") == 1
    assert wake_on_lan == {
        "enabled": False,
        "worker_id": "katsuyu-bubule",
        "mac_address": None,
        "broadcast_address": "192.168.1.255",
        "port": 9,
        "wait_timeout_seconds": 180,
        "available_for_seconds": 30,
    }


def test_wake_on_lan_migration_preserves_an_existing_section(tmp_path: Path) -> None:
    configuration = tmp_path / "shikamaru.yaml"
    configuration.write_text(
        """version: 1
administration:
  enabled: true
  jobs:
    enabled: true
    wake_on_lan:
      enabled: true
      worker_id: katsuyu-Bubule
      mac_address: AA:BB:CC:DD:EE:FF
      broadcast_address: 10.0.0.255
      port: 7
      wait_timeout_seconds: 240
      available_for_seconds: 60
    worker_tls:
      enabled: true
  dhcp:
    enabled: true
""",
        encoding="utf-8",
    )

    administration_module._ensure_agent_wake_on_lan_section(configuration)

    parsed = yaml.safe_load(configuration.read_text(encoding="utf-8"))
    assert parsed["administration"]["jobs"]["wake_on_lan"] == {
        "enabled": True,
        "worker_id": "katsuyu-Bubule",
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "broadcast_address": "10.0.0.255",
        "port": 7,
        "wait_timeout_seconds": 240,
        "available_for_seconds": 60,
        "packet_burst_count": 3,
        "burst_interval_seconds": 0.1,
        "retry_count": 2,
        "retry_delay_seconds": 1.0,
        "batch_window_seconds": 600,
        "planned_window_start_hour": 0,
        "planned_window_end_hour": 5,
        "schedule_timezone": "Europe/Paris",
        "minimum_interval_seconds": 7200,
        "shutdown_after_completion": True,
    }


def test_prepare_administration_adds_shizune_listener_without_replacing_local_values(
    tmp_path: Path,
    monkeypatch,
) -> None:
    agent_configuration, infrastructure, vision_configuration = make_configuration_files(tmp_path)
    agent_configuration.write_text(
        """version: 1
administration:
  enabled: true
  host: 192.168.1.10
  port: 9876
  dhcp:
    enabled: false
""",
        encoding="utf-8",
    )
    openssl = tmp_path / "openssl"
    openssl.write_text("executable", encoding="utf-8")
    tls_directory = agent_configuration.parent / "tls"

    def fake_openssl(command: list[str]) -> None:
        for option in ("-keyout", "-out"):
            if option in command:
                target = Path(command[command.index(option) + 1])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f"generated {target.name}", encoding="utf-8")

    monkeypatch.setattr(administration_module, "_run_openssl", fake_openssl)
    arguments = {
        "agent_configuration_path": agent_configuration,
        "agent_infrastructure_path": infrastructure,
        "agent_token_path": agent_configuration.parent / "management.token",
        "vision_configuration_path": vision_configuration,
        "vision_token_path": vision_configuration.parent / "management.token",
        "dnsmasq_executable": tmp_path / "missing-dnsmasq",
        "dnsmasq_configuration_directory": tmp_path / "dnsmasq.d",
        "systemd_directory": tmp_path / "systemd",
        "require_linux": False,
        "secure_ownership": False,
        "agent_version": "1.24.0",
        "vision_companion_ca_path": vision_configuration.parent / "companion-ca.crt",
        "worker_token_path": agent_configuration.parent / "katsuyu.token",
        "worker_tls_directory": tls_directory,
        "openssl_path": openssl,
    }

    first = prepare_administration(**arguments)
    second = prepare_administration(**arguments)

    content = agent_configuration.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)
    companion = parsed["administration"]["companion"]
    assert first.companion_enabled is True
    assert second.companion_enabled is True
    assert content.count("  companion:") == 1
    assert parsed["administration"]["host"] == "192.168.1.10"
    assert parsed["administration"]["port"] == 9876
    assert companion["host"] == "0.0.0.0"
    assert companion["port"] == 8767
    assert companion["certificate_file"] == (tls_directory / "worker.crt").as_posix()
    assert companion["push"]["enabled"] is False
    vision = yaml.safe_load(vision_configuration.read_text(encoding="utf-8"))
    assert vision["agent"]["companion_enabled"] is True
    assert vision["agent"]["companion_url"] == "https://infra-01.ohana.lan:8767"
    assert (
        vision["agent"]["companion_ca_file"]
        == (vision_configuration.parent / "companion-ca.crt").as_posix()
    )
    assert (vision_configuration.parent / "companion-ca.crt").read_text(encoding="utf-8") == (
        tls_directory / "ca.crt"
    ).read_text(encoding="utf-8")


def test_companion_migration_preserves_an_existing_section(tmp_path: Path) -> None:
    configuration = tmp_path / "shikamaru.yaml"
    configuration.write_text(
        """version: 1
administration:
  enabled: true
  companion:
    enabled: false
    host: 10.0.0.10
    port: 9443
    credential_ttl_days: 12
  dhcp:
    enabled: true
""",
        encoding="utf-8",
    )

    administration_module._ensure_agent_companion_section(
        configuration,
        ca_certificate_path=Path("/etc/ohana-agent/tls/ca.crt"),
        certificate_path=Path("/etc/ohana-agent/tls/worker.crt"),
        private_key_path=Path("/etc/ohana-agent/tls/worker.key"),
    )

    parsed = yaml.safe_load(configuration.read_text(encoding="utf-8"))
    assert parsed["administration"]["companion"] == {
        "enabled": False,
        "host": "10.0.0.10",
        "port": 9443,
        "credential_ttl_days": 12,
    }


def test_jobs_migration_preserves_existing_retention_and_replaces_only_tls(
    tmp_path: Path,
) -> None:
    configuration = tmp_path / "shikamaru.yaml"
    configuration.write_text(
        """version: 1
administration:
  enabled: true
  host: 127.0.0.1
  port: 8765
  jobs:
    enabled: false
    database_path: /custom/jobs.db
    worker_token_file: /old/token
    retention_days: 7
    max_active_jobs: 42
    worker_tls:
      enabled: false
      port: 9999
  dhcp:
    enabled: true
""",
        encoding="utf-8",
    )

    administration_module._ensure_agent_jobs_section(
        configuration,
        worker_token_path=Path("/etc/ohana-agent/katsuyu.token"),
        ca_certificate_path=Path("/etc/ohana-agent/tls/ca.crt"),
        certificate_path=Path("/etc/ohana-agent/tls/worker.crt"),
        private_key_path=Path("/etc/ohana-agent/tls/worker.key"),
    )

    content = configuration.read_text(encoding="utf-8")
    assert "    enabled: true" in content
    assert "    database_path: /custom/jobs.db" in content
    assert "    retention_days: 7" in content
    assert "    max_active_jobs: 42" in content
    assert content.count("    worker_tls:") == 1
    assert "      port: 8766" in content
    assert "      port: 9999" not in content


def test_generated_worker_certificate_is_a_valid_server_chain(tmp_path: Path) -> None:
    openssl = shutil.which("openssl")
    if openssl is None:
        candidates = (
            Path(r"C:\Program Files\Git\usr\bin\openssl.exe"),
            Path(r"C:\Program Files\Git\mingw64\bin\openssl.exe"),
        )
        openssl = next((str(path) for path in candidates if path.is_file()), None)
    if openssl is None:
        pytest.skip("OpenSSL is unavailable")

    paths = administration_module._prepare_worker_tls(
        directory=tmp_path / "tls",
        openssl_path=Path(openssl),
        dns_name="infra-01.ohana.lan",
        ip_address="192.168.1.10",
        secure_ownership=False,
    )
    verified = subprocess.run(
        [
            openssl,
            "verify",
            "-purpose",
            "sslserver",
            "-CAfile",
            str(paths["ca_certificate"]),
            str(paths["certificate"]),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert verified.returncode == 0, verified.stderr
