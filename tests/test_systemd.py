"""Tests de génération des unités systemd."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ohana_installer.manifest import (
    ComponentManifest,
    ComponentPackage,
    ComponentService,
)
from ohana_installer.systemd import (
    GeneratedSystemdService,
    InstalledSystemdService,
    SystemdCommandError,
    SystemdGenerationError,
    SystemdInstallationError,
    SystemdServiceStatus,
    disable_systemd_service,
    enable_systemd_service,
    generate_component_service,
    generate_systemd_services,
    get_systemd_service_status,
    get_systemd_services_status,
    install_generated_service,
    install_generated_services,
    reload_systemd_daemon,
    remove_systemd_service,
    render_systemd_service,
    start_systemd_service,
    start_systemd_services,
    stop_systemd_service,
)


def test_enable_systemd_service_runs_expected_command(
    monkeypatch,
) -> None:
    received_command: list[str] | None = None

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal received_command
        received_command = command

        assert check is True
        assert capture_output is True
        assert text is True
        assert timeout == 30.0

        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        "ohana_installer.systemd.subprocess.run",
        fake_run,
    )

    enable_systemd_service("ohana-agent.service")

    assert received_command == [
        "systemctl",
        "enable",
        "ohana-agent.service",
    ]


def test_enable_systemd_service_accepts_path_unit(
    monkeypatch,
) -> None:
    received_command: list[str] | None = None

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal received_command
        del kwargs
        received_command = command
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        "ohana_installer.systemd.subprocess.run",
        fake_run,
    )

    enable_systemd_service("ohana-dhcp-reload.path")

    assert received_command == [
        "systemctl",
        "enable",
        "ohana-dhcp-reload.path",
    ]


def test_enable_systemd_service_rejects_invalid_name() -> None:
    with pytest.raises(
        SystemdCommandError,
        match="Nom de service systemd invalide",
    ):
        enable_systemd_service("../ohana-agent.service")


def test_enable_systemd_service_requires_service_suffix() -> None:
    with pytest.raises(
        SystemdCommandError,
        match=r"doit se terminer par '\.service' ou '\.path'",
    ):
        enable_systemd_service("ohana-agent")


def test_enable_systemd_service_handles_command_error(
    monkeypatch,
) -> None:
    def raise_command_error(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del kwargs

        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=command,
            stderr="permission denied",
        )

    monkeypatch.setattr(
        "ohana_installer.systemd.subprocess.run",
        raise_command_error,
    )

    with pytest.raises(
        SystemdCommandError,
        match="permission denied",
    ):
        enable_systemd_service("ohana-agent.service")


def test_enable_systemd_service_handles_timeout(
    monkeypatch,
) -> None:
    def raise_timeout(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del kwargs

        raise subprocess.TimeoutExpired(
            cmd=command,
            timeout=30.0,
        )

    monkeypatch.setattr(
        "ohana_installer.systemd.subprocess.run",
        raise_timeout,
    )

    with pytest.raises(
        SystemdCommandError,
        match="délai autorisé",
    ):
        enable_systemd_service("ohana-agent.service")


def _build_generated_service(
    directory: Path,
) -> GeneratedSystemdService:
    """Construire une unité systemd générée pour les tests."""

    component = ComponentManifest(
        identifier="agent",
        name="Ohana-Agent",
        repository="cedric-HAOS/Ohana-Agent",
        version="1.0.0",
        release_tag="v1.0.0",
        package=ComponentPackage(
            type="wheel",
            filename="ohana_agent-1.0.0-py3-none-any.whl",
        ),
        service=ComponentService(
            filename="ohana-agent.service",
            description="Ohana Agent",
            executable=Path("/opt/ohana-agent/venv/bin/ohana-agent"),
            arguments=(),
            user="ohana",
            group="ohana",
            working_directory=Path("/opt/ohana-agent"),
        ),
    )

    content = "[Unit]\nDescription=Ohana Agent\n"
    path = directory / "generated" / "ohana-agent.service"

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        content,
        encoding="utf-8",
        newline="\n",
    )

    return GeneratedSystemdService(
        component=component,
        path=path,
        content=content,
    )


def test_start_systemd_services_starts_all_services(
    tmp_path: Path,
    monkeypatch,
) -> None:
    agent = _build_component(
        service=_build_agent_service(),
    )

    vision = _build_component(
        identifier="vision",
        name="Ohana-Vision",
        service=ComponentService(
            filename="ohana-vision.service",
            description="Ohana Vision",
            user="ohana",
            group="ohana",
            working_directory=Path("/opt/ohana-vision"),
            executable=Path("/opt/ohana-vision/venv/bin/ohana-vision"),
            arguments=(),
        ),
    )

    installed_agent = InstalledSystemdService(
        component=agent,
        source_path=tmp_path / "ohana-agent.service",
        destination_path=(tmp_path / "systemd" / "ohana-agent.service"),
        created=True,
    )

    installed_vision = InstalledSystemdService(
        component=vision,
        source_path=tmp_path / "ohana-vision.service",
        destination_path=(tmp_path / "systemd" / "ohana-vision.service"),
        created=True,
    )

    started_services: list[str] = []

    def fake_start_systemd_service(
        service_name: str,
        *,
        systemctl_executable: Path | str,
        timeout: float,
    ) -> None:
        assert systemctl_executable == "systemctl"
        assert timeout == 30.0
        started_services.append(service_name)

    monkeypatch.setattr(
        "ohana_installer.systemd.start_systemd_service",
        fake_start_systemd_service,
    )

    start_systemd_services(
        (
            installed_agent,
            installed_vision,
        )
    )

    assert started_services == [
        "ohana-agent.service",
        "ohana-vision.service",
    ]


def _generate_agent_service(
    tmp_path: Path,
) -> GeneratedSystemdService:
    component = _build_component(
        service=_build_agent_service(),
    )

    return generate_component_service(
        component,
        tmp_path,
    )


def test_install_generated_service_copies_unit(
    tmp_path: Path,
) -> None:
    generated_directory = tmp_path / "generated"
    system_directory = tmp_path / "systemd"

    generated_service = _generate_agent_service(
        generated_directory,
    )

    result = install_generated_service(
        generated_service,
        system_directory=system_directory,
    )

    destination = system_directory / "ohana-agent.service"

    assert result.created is True
    assert result.destination_path == destination
    assert destination.exists()
    assert (
        destination.read_text(
            encoding="utf-8",
        )
        == generated_service.content
    )


def test_install_generated_service_accepts_identical_existing_unit(
    tmp_path: Path,
) -> None:
    generated_directory = tmp_path / "generated"
    system_directory = tmp_path / "systemd"

    generated_service = _generate_agent_service(
        generated_directory,
    )

    system_directory.mkdir()
    destination = system_directory / "ohana-agent.service"
    destination.write_text(
        generated_service.content,
        encoding="utf-8",
        newline="\n",
    )

    result = install_generated_service(
        generated_service,
        system_directory=system_directory,
    )

    assert result.created is False
    assert result.destination_path == destination


def test_install_generated_service_rejects_different_existing_unit(
    tmp_path: Path,
) -> None:
    generated_directory = tmp_path / "generated"
    system_directory = tmp_path / "systemd"

    generated_service = _generate_agent_service(
        generated_directory,
    )

    system_directory.mkdir()
    destination = system_directory / "ohana-agent.service"
    destination.write_text(
        "custom content\n",
        encoding="utf-8",
    )

    with pytest.raises(
        SystemdInstallationError,
        match="contenu différent",
    ):
        install_generated_service(
            generated_service,
            system_directory=system_directory,
        )


def test_install_generated_service_rejects_missing_source(
    tmp_path: Path,
) -> None:
    component = _build_component(
        service=_build_agent_service(),
    )

    generated_service = GeneratedSystemdService(
        component=component,
        path=tmp_path / "missing.service",
        content="[Unit]\n",
    )

    with pytest.raises(
        SystemdInstallationError,
        match="unité générée est introuvable",
    ):
        install_generated_service(
            generated_service,
            system_directory=tmp_path / "systemd",
        )


def test_install_generated_services_installs_all_units(
    tmp_path: Path,
) -> None:
    generated_directory = tmp_path / "generated"
    system_directory = tmp_path / "systemd"

    agent = _build_component(
        service=_build_agent_service(),
    )
    vision = _build_component(
        identifier="vision",
        name="Ohana-Vision",
        service=ComponentService(
            filename="ohana-vision.service",
            description="Ohana Vision",
            user="ohana",
            group="ohana",
            working_directory=Path("/opt/ohana-vision"),
            executable=Path("/opt/ohana-vision/venv/bin/ohana-vision"),
            arguments=(),
        ),
    )

    generated_services = generate_systemd_services(
        (agent, vision),
        generated_directory,
    )

    results = install_generated_services(
        generated_services,
        system_directory=system_directory,
    )

    assert len(results) == 2
    assert (system_directory / "ohana-agent.service").exists()
    assert (system_directory / "ohana-vision.service").exists()


def _build_component(
    *,
    identifier: str = "agent",
    name: str = "Ohana-Agent",
    service: ComponentService | None = None,
) -> ComponentManifest:
    return ComponentManifest(
        identifier=identifier,
        name=name,
        repository=f"cedric-HAOS/{name}",
        version="1.0.0",
        release_tag="v1.0.0",
        package=ComponentPackage(
            type="wheel",
            filename=f"{identifier}-1.0.0.whl",
        ),
        service=service,
    )


def _build_agent_service() -> ComponentService:
    return ComponentService(
        filename="ohana-agent.service",
        description="Ohana Agent",
        user="ohana",
        group="ohana",
        working_directory=Path("/opt/ohana-agent"),
        executable=Path("/opt/ohana-agent/venv/bin/ohana-agent"),
        arguments=(
            "--config",
            "/etc/ohana-agent/shikamaru.yaml",
            "--infrastructure",
            "/etc/ohana-agent/infrastructure.yaml",
            "--dns-config",
            "/etc/ohana-agent/plugins/dns.yaml",
            "--ntp-config",
            "/etc/ohana-agent/plugins/ntp.yaml",
            "--mqtt-config",
            "/etc/ohana-agent/plugins/mqtt.yaml",
        ),
    )


def test_render_systemd_service() -> None:
    content = render_systemd_service(_build_agent_service())

    assert "[Unit]" in content
    assert "Description=Ohana Agent" in content
    assert "After=network-online.target" in content
    assert "User=ohana" in content
    assert "Group=ohana" in content
    assert "WorkingDirectory=/opt/ohana-agent" in content
    assert (
        "ExecStart=/opt/ohana-agent/venv/bin/ohana-agent "
        "--config /etc/ohana-agent/shikamaru.yaml "
        "--infrastructure /etc/ohana-agent/infrastructure.yaml "
        "--dns-config /etc/ohana-agent/plugins/dns.yaml "
        "--ntp-config /etc/ohana-agent/plugins/ntp.yaml "
        "--mqtt-config /etc/ohana-agent/plugins/mqtt.yaml"
    ) in content
    assert "Restart=on-failure" in content
    assert "SupplementaryGroups=ohana-vision systemd-journal" in content
    assert "RuntimeDirectory=ohana-agent" in content
    assert "RuntimeDirectoryMode=0750" in content
    assert "StateDirectory=ohana-agent" in content
    assert "StateDirectoryMode=0750" in content
    assert "NoNewPrivileges=false" in content
    assert "WantedBy=multi-user.target" in content
    assert content.endswith("\n")


def test_vision_service_does_not_receive_agent_backup_group() -> None:
    service = ComponentService(
        filename="ohana-vision.service",
        description="Ohana Vision",
        user="ohana-vision",
        group="ohana-vision",
        working_directory=Path("/opt/ohana-vision"),
        executable=Path("/opt/ohana-vision/venv/bin/ohana-vision"),
        arguments=(),
    )

    content = render_systemd_service(service)

    assert "SupplementaryGroups=" not in content


def test_generate_component_service_writes_file(
    tmp_path: Path,
) -> None:
    component = _build_component(
        service=_build_agent_service(),
    )

    result = generate_component_service(
        component,
        tmp_path,
    )

    expected_path = tmp_path / "ohana-agent.service"

    assert result.path == expected_path
    assert expected_path.exists()
    assert expected_path.read_text(encoding="utf-8") == result.content


def test_generate_component_service_rejects_missing_service(
    tmp_path: Path,
) -> None:
    component = _build_component(service=None)

    with pytest.raises(
        SystemdGenerationError,
        match="ne déclare aucun service",
    ):
        generate_component_service(
            component,
            tmp_path,
        )


def test_generate_systemd_services_generates_declared_services(
    tmp_path: Path,
) -> None:
    agent_service = _build_agent_service()

    vision_service = ComponentService(
        filename="ohana-vision.service",
        description="Ohana Vision",
        user="ohana",
        group="ohana",
        working_directory=Path("/opt/ohana-vision"),
        executable=Path("/opt/ohana-vision/venv/bin/ohana-vision"),
        arguments=(),
    )

    agent = _build_component(
        service=agent_service,
    )
    vision = _build_component(
        identifier="vision",
        name="Ohana-Vision",
        service=vision_service,
    )

    results = generate_systemd_services(
        (agent, vision),
        tmp_path,
    )

    assert len(results) == 2
    assert (tmp_path / "ohana-agent.service").exists()
    assert (tmp_path / "ohana-vision.service").exists()
    vision_content = (tmp_path / "ohana-vision.service").read_text(encoding="utf-8")
    assert "StateDirectory=ohana-vision" in vision_content
    assert "StateDirectoryMode=0750" in vision_content


def test_generate_systemd_services_ignores_component_without_service(
    tmp_path: Path,
) -> None:
    agent = _build_component(
        service=_build_agent_service(),
    )
    component_without_service = _build_component(
        identifier="other",
        name="Other",
        service=None,
    )

    results = generate_systemd_services(
        (agent, component_without_service),
        tmp_path,
    )

    assert len(results) == 1
    assert results[0].component.identifier == "agent"


def test_reload_systemd_daemon_runs_expected_command(
    monkeypatch,
) -> None:
    received_command: list[str] | None = None

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal received_command
        received_command = command

        assert check is True
        assert capture_output is True
        assert text is True
        assert timeout == 30.0

        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        "ohana_installer.systemd.subprocess.run",
        fake_run,
    )

    reload_systemd_daemon()

    assert received_command == [
        "systemctl",
        "daemon-reload",
    ]


def test_reload_systemd_daemon_handles_command_error(
    monkeypatch,
) -> None:
    def raise_command_error(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del kwargs

        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=command,
            stderr="access denied",
        )

    monkeypatch.setattr(
        "ohana_installer.systemd.subprocess.run",
        raise_command_error,
    )

    with pytest.raises(
        SystemdCommandError,
        match="access denied",
    ):
        reload_systemd_daemon()


def test_reload_systemd_daemon_handles_timeout(
    monkeypatch,
) -> None:
    def raise_timeout(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del kwargs

        raise subprocess.TimeoutExpired(
            cmd=command,
            timeout=30.0,
        )

    monkeypatch.setattr(
        "ohana_installer.systemd.subprocess.run",
        raise_timeout,
    )

    with pytest.raises(
        SystemdCommandError,
        match="délai autorisé",
    ):
        reload_systemd_daemon()


def test_reload_systemd_daemon_handles_os_error(
    monkeypatch,
) -> None:
    def raise_os_error(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del command
        del kwargs

        raise OSError("systemctl introuvable")

    monkeypatch.setattr(
        "ohana_installer.systemd.subprocess.run",
        raise_os_error,
    )

    with pytest.raises(
        SystemdCommandError,
        match="systemctl introuvable",
    ):
        reload_systemd_daemon()


def test_start_systemd_service_runs_expected_command(
    monkeypatch,
) -> None:
    received_command: list[str] | None = None

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal received_command
        received_command = command

        assert check is True
        assert capture_output is True
        assert text is True
        assert timeout == 30.0

        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        "ohana_installer.systemd.subprocess.run",
        fake_run,
    )

    start_systemd_service("ohana-agent.service")

    assert received_command == [
        "systemctl",
        "start",
        "ohana-agent.service",
    ]


def test_start_systemd_service_accepts_path_unit(
    monkeypatch,
) -> None:
    received_command: list[str] | None = None

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal received_command
        del kwargs
        received_command = command
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        "ohana_installer.systemd.subprocess.run",
        fake_run,
    )

    start_systemd_service("ohana-dhcp-reload.path")

    assert received_command == [
        "systemctl",
        "start",
        "ohana-dhcp-reload.path",
    ]


def test_start_systemd_service_rejects_invalid_name() -> None:
    with pytest.raises(
        SystemdCommandError,
        match="Nom de service systemd invalide",
    ):
        start_systemd_service("../ohana-agent.service")


def test_start_systemd_service_requires_service_suffix() -> None:
    with pytest.raises(
        SystemdCommandError,
        match=r"doit se terminer par '\.service' ou '\.path'",
    ):
        start_systemd_service("ohana-agent")


def test_start_systemd_service_handles_command_error(
    monkeypatch,
) -> None:
    def raise_command_error(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del kwargs

        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=command,
            stderr="service failed",
        )

    monkeypatch.setattr(
        "ohana_installer.systemd.subprocess.run",
        raise_command_error,
    )

    with pytest.raises(
        SystemdCommandError,
        match="service failed",
    ):
        start_systemd_service("ohana-agent.service")


def test_start_systemd_service_handles_timeout(
    monkeypatch,
) -> None:
    def raise_timeout(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del kwargs

        raise subprocess.TimeoutExpired(
            cmd=command,
            timeout=30.0,
        )

    monkeypatch.setattr(
        "ohana_installer.systemd.subprocess.run",
        raise_timeout,
    )

    with pytest.raises(
        SystemdCommandError,
        match="délai autorisé",
    ):
        start_systemd_service("ohana-agent.service")


def test_start_systemd_service_handles_os_error(
    monkeypatch,
) -> None:
    def raise_os_error(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del command
        del kwargs

        raise OSError("systemctl introuvable")

    monkeypatch.setattr(
        "ohana_installer.systemd.subprocess.run",
        raise_os_error,
    )

    with pytest.raises(
        SystemdCommandError,
        match="systemctl introuvable",
    ):
        start_systemd_service("ohana-agent.service")


def test_get_systemd_service_status_returns_active(
    monkeypatch,
) -> None:
    received_command: list[str] | None = None

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal received_command
        received_command = command

        assert check is False
        assert capture_output is True
        assert text is True
        assert timeout == 30.0

        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="active\n",
            stderr="",
        )

    monkeypatch.setattr(
        "ohana_installer.systemd.subprocess.run",
        fake_run,
    )

    result = get_systemd_service_status("ohana-agent.service")

    assert received_command == [
        "systemctl",
        "is-active",
        "ohana-agent.service",
    ]
    assert result == SystemdServiceStatus(
        service_name="ohana-agent.service",
        active=True,
        status="active",
    )


def test_get_systemd_service_status_returns_inactive(
    monkeypatch,
) -> None:
    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del kwargs

        return subprocess.CompletedProcess(
            command,
            returncode=3,
            stdout="inactive\n",
            stderr="",
        )

    monkeypatch.setattr(
        "ohana_installer.systemd.subprocess.run",
        fake_run,
    )

    result = get_systemd_service_status("ohana-agent.service")

    assert result.active is False
    assert result.status == "inactive"


def test_get_systemd_service_status_returns_failed(
    monkeypatch,
) -> None:
    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del kwargs

        return subprocess.CompletedProcess(
            command,
            returncode=3,
            stdout="failed\n",
            stderr="",
        )

    monkeypatch.setattr(
        "ohana_installer.systemd.subprocess.run",
        fake_run,
    )

    result = get_systemd_service_status("ohana-agent.service")

    assert result.active is False
    assert result.status == "failed"


def test_get_systemd_service_status_rejects_invalid_name() -> None:
    with pytest.raises(
        SystemdCommandError,
        match="Nom de service systemd invalide",
    ):
        get_systemd_service_status("../ohana-agent.service")


def test_get_systemd_service_status_requires_service_suffix() -> None:
    with pytest.raises(
        SystemdCommandError,
        match=r"doit se terminer par '\.service' ou '\.path'",
    ):
        get_systemd_service_status("ohana-agent")


def test_get_systemd_service_status_handles_timeout(
    monkeypatch,
) -> None:
    def raise_timeout(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del kwargs

        raise subprocess.TimeoutExpired(
            cmd=command,
            timeout=30.0,
        )

    monkeypatch.setattr(
        "ohana_installer.systemd.subprocess.run",
        raise_timeout,
    )

    with pytest.raises(
        SystemdCommandError,
        match="délai autorisé",
    ):
        get_systemd_service_status("ohana-agent.service")


def test_get_systemd_service_status_handles_os_error(
    monkeypatch,
) -> None:
    def raise_os_error(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del command
        del kwargs

        raise OSError("systemctl introuvable")

    monkeypatch.setattr(
        "ohana_installer.systemd.subprocess.run",
        raise_os_error,
    )

    with pytest.raises(
        SystemdCommandError,
        match="systemctl introuvable",
    ):
        get_systemd_service_status("ohana-agent.service")


def test_get_systemd_services_status_checks_all_services(
    tmp_path: Path,
    monkeypatch,
) -> None:
    agent = _build_component(
        service=_build_agent_service(),
    )
    vision = _build_component(
        identifier="vision",
        name="Ohana-Vision",
        service=ComponentService(
            filename="ohana-vision.service",
            description="Ohana Vision",
            user="ohana",
            group="ohana",
            working_directory=Path("/opt/ohana-vision"),
            executable=Path("/opt/ohana-vision/venv/bin/ohana-vision"),
            arguments=(),
        ),
    )

    installed_services = (
        InstalledSystemdService(
            component=agent,
            source_path=tmp_path / "ohana-agent.service",
            destination_path=(tmp_path / "systemd" / "ohana-agent.service"),
            created=True,
        ),
        InstalledSystemdService(
            component=vision,
            source_path=tmp_path / "ohana-vision.service",
            destination_path=(tmp_path / "systemd" / "ohana-vision.service"),
            created=True,
        ),
    )

    checked_services: list[str] = []

    def fake_get_systemd_service_status(
        service_name: str,
        *,
        systemctl_executable: Path | str,
        timeout: float,
    ) -> SystemdServiceStatus:
        assert systemctl_executable == "systemctl"
        assert timeout == 30.0
        checked_services.append(service_name)

        return SystemdServiceStatus(
            service_name=service_name,
            active=True,
            status="active",
        )

    monkeypatch.setattr(
        "ohana_installer.systemd.get_systemd_service_status",
        fake_get_systemd_service_status,
    )

    results = get_systemd_services_status(installed_services)

    assert checked_services == [
        "ohana-agent.service",
        "ohana-vision.service",
    ]
    assert all(result.active for result in results)


def test_install_generated_service_refuses_different_existing_unit(
    tmp_path: Path,
) -> None:
    generated_service = _build_generated_service(tmp_path)
    system_directory = tmp_path / "system"

    system_directory.mkdir()
    destination = system_directory / generated_service.path.name
    destination.write_text("ancien contenu", encoding="utf-8")

    with pytest.raises(
        SystemdInstallationError,
        match="contenu différent",
    ):
        install_generated_service(
            generated_service,
            system_directory=system_directory,
        )


def test_install_generated_service_replaces_different_existing_unit(
    tmp_path: Path,
) -> None:
    generated_service = _build_generated_service(tmp_path)
    system_directory = tmp_path / "system"

    system_directory.mkdir()
    destination = system_directory / generated_service.path.name
    destination.write_text("ancien contenu", encoding="utf-8")

    result = install_generated_service(
        generated_service,
        system_directory=system_directory,
        replace=True,
    )

    assert (
        destination.read_text(
            encoding="utf-8",
        )
        == generated_service.content
    )
    assert result.created is False
    assert result.updated is True


def test_stop_systemd_service_runs_expected_command(
    monkeypatch,
) -> None:
    received_command: list[str] | None = None

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal received_command
        received_command = command

        assert kwargs["check"] is True
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True

        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        "ohana_installer.systemd.subprocess.run",
        fake_run,
    )

    stop_systemd_service("ohana-agent.service")

    assert received_command == [
        "systemctl",
        "stop",
        "ohana-agent.service",
    ]


def test_disable_systemd_service_runs_expected_command(
    monkeypatch,
) -> None:
    received_command: list[str] | None = None

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool,
        text: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal received_command
        received_command = command

        assert check is True
        assert capture_output is True
        assert text is True
        assert timeout == 30.0

        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(
        "ohana_installer.systemd.subprocess.run",
        fake_run,
    )

    disable_systemd_service("ohana-agent.service")

    assert received_command == [
        "systemctl",
        "disable",
        "ohana-agent.service",
    ]


def test_remove_systemd_service_removes_existing_unit(
    tmp_path: Path,
) -> None:
    service_path = tmp_path / "ohana-agent.service"
    service_path.write_text(
        "[Unit]\n",
        encoding="utf-8",
    )

    removed = remove_systemd_service(
        "ohana-agent.service",
        system_directory=tmp_path,
    )

    assert removed is True
    assert service_path.exists() is False


def test_remove_systemd_service_accepts_missing_unit(
    tmp_path: Path,
) -> None:
    removed = remove_systemd_service(
        "ohana-agent.service",
        system_directory=tmp_path,
    )

    assert removed is False


def test_remove_systemd_service_rejects_invalid_name(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        SystemdCommandError,
        match="Nom de service systemd invalide",
    ):
        remove_systemd_service(
            "../ohana-agent.service",
            system_directory=tmp_path,
        )
