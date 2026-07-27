"""Tests d'installation des modèles de configuration."""

from pathlib import Path

import pytest

from ohana_installer.commands.install import (
    CONFIGURATION_DIRECTORY_MODE,
    CONFIGURATION_FILE_MODE,
    ConfigurationInstallationError,
    _install_configuration_file,
    _install_configurations,
    _secure_configuration_path,
)
from ohana_installer.github import DownloadedConfigurationFile
from ohana_installer.manifest import (
    ComponentConfiguration,
    ComponentManifest,
    ComponentPackage,
    ComponentService,
    ConfigurationFile,
)


def _build_downloaded_configuration(
    tmp_path: Path,
    *,
    source: str = "dns.example.yaml",
    destination: Path = Path("plugins/dns.yaml"),
    with_component_configuration: bool = True,
) -> DownloadedConfigurationFile:
    source_path = tmp_path / "downloads" / source
    source_path.parent.mkdir(parents=True)
    source_path.write_text("enabled: true\n", encoding="utf-8")

    configuration = ComponentConfiguration(
        directory=tmp_path / "etc" / "ohana-agent",
        files=(
            ConfigurationFile(
                source=source,
                destination=destination,
            ),
        ),
    )
    component = ComponentManifest(
        identifier="agent",
        name="Ohana-Agent",
        repository="cedric-HAOS/Ohana-Agent",
        version="1.1.0",
        release_tag="v1.1.0",
        package=ComponentPackage(
            type="wheel",
            filename="ohana_agent-1.1.0-py3-none-any.whl",
        ),
        configuration=(configuration if with_component_configuration else None),
        service=ComponentService(
            filename="ohana-agent.service",
            description="Ohana Agent",
            user="ohana",
            group="ohana",
            working_directory=Path("/opt/ohana-agent"),
            executable=Path("/opt/ohana-agent/venv/bin/ohana-agent"),
            arguments=(),
        ),
    )

    return DownloadedConfigurationFile(
        component=component,
        configuration_file=configuration.files[0],
        path=source_path,
    )


@pytest.fixture(autouse=True)
def avoid_real_configuration_ownership(monkeypatch) -> None:
    """Éviter les changements de propriétaire pendant les tests Windows."""

    monkeypatch.setattr(
        "ohana_installer.commands.install._secure_configuration_path",
        lambda path, *, group_name, mode: None,
    )


def test_install_configuration_file_creates_nested_destination(
    tmp_path: Path,
) -> None:
    downloaded_file = _build_downloaded_configuration(tmp_path)

    installed_file = _install_configuration_file(downloaded_file)

    assert installed_file.created is True
    assert installed_file.destination_path == (
        tmp_path / "etc" / "ohana-agent" / "plugins" / "dns.yaml"
    )
    assert installed_file.destination_path.read_text(encoding="utf-8") == "enabled: true\n"


def test_install_configuration_file_preserves_existing_file(
    tmp_path: Path,
) -> None:
    downloaded_file = _build_downloaded_configuration(tmp_path)
    configuration = downloaded_file.component.configuration
    assert configuration is not None

    destination = configuration.directory / downloaded_file.configuration_file.destination
    destination.parent.mkdir(parents=True)
    destination.write_text("local: true\n", encoding="utf-8")

    installed_file = _install_configuration_file(downloaded_file)

    assert installed_file.created is False
    assert destination.read_text(encoding="utf-8") == "local: true\n"


def test_install_configuration_file_rejects_directory_destination(
    tmp_path: Path,
) -> None:
    downloaded_file = _build_downloaded_configuration(
        tmp_path,
        destination=Path("dns.yaml"),
    )
    configuration = downloaded_file.component.configuration
    assert configuration is not None

    destination = configuration.directory / downloaded_file.configuration_file.destination
    destination.mkdir(parents=True)

    with pytest.raises(
        ConfigurationInstallationError,
        match="n'est pas un fichier",
    ):
        _install_configuration_file(downloaded_file)


def test_install_configuration_file_rejects_missing_source(
    tmp_path: Path,
) -> None:
    downloaded_file = _build_downloaded_configuration(tmp_path)
    downloaded_file.path.unlink()

    with pytest.raises(
        ConfigurationInstallationError,
        match="est introuvable",
    ):
        _install_configuration_file(downloaded_file)


def test_install_configuration_file_requires_component_configuration(
    tmp_path: Path,
) -> None:
    downloaded_file = _build_downloaded_configuration(
        tmp_path,
        with_component_configuration=False,
    )

    with pytest.raises(
        ConfigurationInstallationError,
        match="aucun répertoire de configuration",
    ):
        _install_configuration_file(downloaded_file)


def test_install_configurations_installs_all_files(
    tmp_path: Path,
) -> None:
    downloaded_files = tuple(
        _build_downloaded_configuration(
            tmp_path / plugin_name,
            source=f"{plugin_name}.example.yaml",
            destination=Path(f"plugins/{plugin_name}.yaml"),
        )
        for plugin_name in ("dns", "ntp", "mqtt")
    )

    installed_files = _install_configurations(downloaded_files)

    assert len(installed_files) == 3
    assert all(installed_file.created for installed_file in installed_files)
    assert tuple(file.destination_path.name for file in installed_files) == (
        "dns.yaml",
        "ntp.yaml",
        "mqtt.yaml",
    )


def test_install_configuration_file_secures_directories_and_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    downloaded_file = _build_downloaded_configuration(tmp_path)
    secured_paths: list[tuple[Path, str, int]] = []

    def record_permissions(
        path: Path,
        *,
        group_name: str,
        mode: int,
    ) -> None:
        secured_paths.append((path, group_name, mode))

    monkeypatch.setattr(
        "ohana_installer.commands.install._secure_configuration_path",
        record_permissions,
    )

    installed_file = _install_configuration_file(downloaded_file)
    configuration = downloaded_file.component.configuration
    assert configuration is not None

    assert installed_file.group_name == "ohana"
    assert secured_paths == [
        (
            configuration.directory,
            "ohana",
            CONFIGURATION_DIRECTORY_MODE,
        ),
        (
            configuration.directory / "plugins",
            "ohana",
            CONFIGURATION_DIRECTORY_MODE,
        ),
        (
            installed_file.destination_path,
            "ohana",
            CONFIGURATION_FILE_MODE,
        ),
    ]


def test_secure_configuration_path_applies_owner_group_and_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "vision.yaml"
    path.write_text("server: {}\n", encoding="utf-8")
    chown_calls: list[tuple[Path, str, str]] = []
    chmod_calls: list[tuple[Path, int]] = []

    def fake_chown(
        received_path: Path,
        *,
        user: str,
        group: str,
    ) -> None:
        chown_calls.append((received_path, user, group))

    def fake_chmod(received_path: Path, mode: int) -> None:
        chmod_calls.append((received_path, mode))

    monkeypatch.setattr(
        "ohana_installer.commands.install.shutil.chown",
        fake_chown,
    )
    monkeypatch.setattr(Path, "chmod", fake_chmod)

    _secure_configuration_path(
        path,
        group_name="ohana",
        mode=CONFIGURATION_FILE_MODE,
    )

    assert chown_calls == [(path, "root", "ohana")]
    assert chmod_calls == [(path, CONFIGURATION_FILE_MODE)]


def test_install_configuration_file_removes_new_file_when_securing_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    downloaded_file = _build_downloaded_configuration(tmp_path)
    configuration = downloaded_file.component.configuration
    assert configuration is not None
    destination = configuration.directory / downloaded_file.configuration_file.destination

    def fail_on_file(
        path: Path,
        *,
        group_name: str,
        mode: int,
    ) -> None:
        del group_name
        del mode

        if path == destination:
            raise ConfigurationInstallationError("permissions refusées")

    monkeypatch.setattr(
        "ohana_installer.commands.install._secure_configuration_path",
        fail_on_file,
    )

    with pytest.raises(
        ConfigurationInstallationError,
        match="permissions refusées",
    ):
        _install_configuration_file(downloaded_file)

    assert not destination.exists()


def test_install_configuration_file_rejects_symbolic_link_destination(
    tmp_path: Path,
    monkeypatch,
) -> None:
    downloaded_file = _build_downloaded_configuration(tmp_path)
    configuration = downloaded_file.component.configuration
    assert configuration is not None
    destination = configuration.directory / downloaded_file.configuration_file.destination
    original_is_symlink = Path.is_symlink

    def fake_is_symlink(path: Path) -> bool:
        if path == destination:
            return True

        return original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)

    with pytest.raises(
        ConfigurationInstallationError,
        match="ne peut pas être un lien symbolique",
    ):
        _install_configuration_file(downloaded_file)


def test_secure_configuration_path_reports_permission_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "vision.yaml"
    path.write_text("server: {}\n", encoding="utf-8")

    def raise_lookup_error(
        received_path: Path,
        *,
        user: str,
        group: str,
    ) -> None:
        del received_path
        del user
        del group
        raise LookupError("groupe introuvable")

    monkeypatch.setattr(
        "ohana_installer.commands.install.shutil.chown",
        raise_lookup_error,
    )

    with pytest.raises(
        ConfigurationInstallationError,
        match=r"root:ohana, 0640.*groupe introuvable",
    ):
        _secure_configuration_path(
            path,
            group_name="ohana",
            mode=CONFIGURATION_FILE_MODE,
        )
