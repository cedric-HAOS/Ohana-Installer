"""Tests de chargement et de validation du manifeste."""

from __future__ import annotations

from pathlib import Path

import pytest

from ohana_installer.environment import MINIMUM_PYTHON_VERSION
from ohana_installer.manifest import (
    ManifestError,
    build_release_download_url,
    load_manifest,
    parse_manifest,
)

VALID_MANIFEST = {
    "schema_version": 1,
    "platform": {
        "name": "Ohana",
        "version": "1.0.0",
    },
    "runtime": {
        "python": {
            "minimum_version": "3.12",
        },
    },
    "components": {
        "agent": {
            "name": "Ohana-Agent",
            "repository": "cedric-HAOS/Ohana-Agent",
            "version": "1.0.0",
            "release_tag": "v1.0.0",
            "package": {
                "type": "wheel",
                "filename": "ohana_agent-1.0.0-py3-none-any.whl",
            },
            "configuration": {
                "directory": "/etc/ohana-agent",
                "files": [
                    {
                        "source": "shikamaru.yaml",
                        "destination": "shikamaru.yaml",
                    },
                    {
                        "source": "infrastructure.yaml",
                        "destination": "infrastructure.yaml",
                    },
                    {
                        "source": "dns.yaml",
                        "destination": "plugins/dns.yaml",
                    },
                ],
            },
            "service": {
                "filename": "ohana-agent.service",
                "description": "Ohana Agent",
                "user": "ohana",
                "group": "ohana",
                "working_directory": "/opt/ohana-agent",
                "executable": "/opt/ohana-agent/venv/bin/ohana-agent",
                "arguments": [
                    "--config",
                    "/etc/ohana-agent/shikamaru.yaml",
                    "--infrastructure",
                    "/etc/ohana-agent/infrastructure.yaml",
                    "--dns-config",
                    "/etc/ohana-agent/plugins/dns.yaml",
                ],
            },
        },
        "vision": {
            "name": "Ohana-Vision",
            "repository": "cedric-HAOS/Ohana-Vision",
            "version": "1.0.0",
            "release_tag": "v1.0.0",
            "package": {
                "type": "wheel",
                "filename": "ohana_vision-1.0.0-py3-none-any.whl",
            },
            "service": {
                "filename": "ohana-vision.service",
                "description": "Ohana Vision",
                "user": "ohana",
                "group": "ohana",
                "working_directory": "/opt/ohana-vision",
                "executable": "/opt/ohana-vision/venv/bin/ohana-vision",
                "arguments": [],
            },
        },
    },
    "compatibility": {
        "operating_system": {
            "family": "Linux",
            "service_manager": "systemd",
        },
    },
}


def test_parse_manifest_returns_validated_manifest() -> None:
    manifest = parse_manifest(VALID_MANIFEST)

    assert manifest.schema_version == 1
    assert manifest.platform_name == "Ohana"
    assert manifest.platform_version == "1.0.0"
    assert manifest.runtime.minimum_python_version == "3.12"
    assert manifest.compatibility.operating_system_family == "Linux"
    assert manifest.compatibility.service_manager == "systemd"

    assert len(manifest.components) == 2
    assert manifest.components[0].identifier == "agent"
    assert manifest.components[1].identifier == "vision"


def test_load_manifest_reads_yaml_file(tmp_path: Path) -> None:
    manifest_path = tmp_path / "release-manifest.yaml"
    manifest_path.write_text(
        """
schema_version: 1

platform:
  name: Ohana
  version: "1.0.0"

runtime:
  python:
    minimum_version: "3.12"

components:
  agent:
    name: Ohana-Agent
    repository: cedric-HAOS/Ohana-Agent
    version: "1.0.0"
    release_tag: v1.0.0
    package:
      type: wheel
      filename: ohana_agent-1.0.0-py3-none-any.whl

compatibility:
  operating_system:
    family: Linux
    service_manager: systemd
""".strip(),
        encoding="utf-8",
    )

    manifest = load_manifest(manifest_path)

    assert manifest.platform_version == "1.0.0"
    assert manifest.components[0].name == "Ohana-Agent"


def test_load_manifest_fails_when_file_does_not_exist(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "missing.yaml"

    with pytest.raises(ManifestError, match="Impossible de lire"):
        load_manifest(manifest_path)


def test_load_manifest_fails_with_invalid_yaml(tmp_path: Path) -> None:
    manifest_path = tmp_path / "invalid.yaml"
    manifest_path.write_text(
        "platform: [invalid",
        encoding="utf-8",
    )

    with pytest.raises(ManifestError, match="YAML invalide"):
        load_manifest(manifest_path)


def test_parse_manifest_rejects_invalid_schema_version() -> None:
    raw_manifest = {
        **VALID_MANIFEST,
        "schema_version": 2,
    }

    with pytest.raises(
        ManifestError,
        match="Version de schéma non prise en charge",
    ):
        parse_manifest(raw_manifest)


def test_parse_manifest_rejects_missing_platform() -> None:
    raw_manifest = dict(VALID_MANIFEST)
    raw_manifest.pop("platform")

    with pytest.raises(
        ManifestError,
        match="platform doit être un objet YAML",
    ):
        parse_manifest(raw_manifest)


def test_parse_manifest_rejects_empty_components() -> None:
    raw_manifest = {
        **VALID_MANIFEST,
        "components": {},
    }

    with pytest.raises(
        ManifestError,
        match="components ne peut pas être vide",
    ):
        parse_manifest(raw_manifest)


def test_parse_manifest_rejects_invalid_repository() -> None:
    raw_manifest = {
        **VALID_MANIFEST,
        "components": {
            "agent": {
                **VALID_MANIFEST["components"]["agent"],
                "repository": "Ohana-Agent",
            },
        },
    }

    with pytest.raises(
        ManifestError,
        match="owner/repository",
    ):
        parse_manifest(raw_manifest)


@pytest.mark.parametrize(
    "repository",
    [
        "../Ohana-Agent",
        "cedric-HAOS/../Ohana-Agent",
        "cedric HAOS/Ohana-Agent",
    ],
)
def test_parse_manifest_rejects_unsafe_repository(repository: str) -> None:
    raw_manifest = {
        **VALID_MANIFEST,
        "components": {
            "agent": {
                **VALID_MANIFEST["components"]["agent"],
                "repository": repository,
            },
        },
    }

    with pytest.raises(
        ManifestError,
        match="owner/repository",
    ):
        parse_manifest(raw_manifest)


def test_parse_manifest_rejects_non_wheel_package() -> None:
    raw_manifest = {
        **VALID_MANIFEST,
        "components": {
            "agent": {
                **VALID_MANIFEST["components"]["agent"],
                "package": {
                    "type": "archive",
                    "filename": "ohana-agent.tar.gz",
                },
            },
        },
    }

    with pytest.raises(
        ManifestError,
        match="doit être égal à 'wheel'",
    ):
        parse_manifest(raw_manifest)


def test_parse_manifest_rejects_invalid_wheel_filename() -> None:
    raw_manifest = {
        **VALID_MANIFEST,
        "components": {
            "agent": {
                **VALID_MANIFEST["components"]["agent"],
                "package": {
                    "type": "wheel",
                    "filename": "ohana-agent.tar.gz",
                },
            },
        },
    }

    with pytest.raises(
        ManifestError,
        match=r"fichier \.whl",
    ):
        parse_manifest(raw_manifest)


def test_parse_manifest_rejects_package_path() -> None:
    raw_manifest = {
        **VALID_MANIFEST,
        "components": {
            "agent": {
                **VALID_MANIFEST["components"]["agent"],
                "package": {
                    "type": "wheel",
                    "filename": "../agent.whl",
                },
            },
        },
    }

    with pytest.raises(
        ManifestError,
        match="simple nom de fichier",
    ):
        parse_manifest(raw_manifest)


def test_parse_manifest_rejects_release_tag_version_mismatch() -> None:
    raw_manifest = {
        **VALID_MANIFEST,
        "components": {
            "agent": {
                **VALID_MANIFEST["components"]["agent"],
                "release_tag": "v2.0.0",
            },
        },
    }

    with pytest.raises(
        ManifestError,
        match="doit correspondre à la version",
    ):
        parse_manifest(raw_manifest)


def test_build_release_download_url() -> None:
    manifest = parse_manifest(VALID_MANIFEST)
    component = manifest.components[0]

    url = build_release_download_url(component)

    assert url == (
        "https://github.com/cedric-HAOS/Ohana-Agent/releases/download/"
        "v1.0.0/ohana_agent-1.0.0-py3-none-any.whl"
    )


def test_repository_manifest_is_valid() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    manifest_path = repository_root / "config" / "release-manifest.yaml"

    manifest = load_manifest(manifest_path)

    assert manifest.platform_name == "Ohana"
    assert manifest.platform_version == "1.0.11"
    assert manifest.runtime.minimum_python_version == "3.13"
    assert {component.identifier for component in manifest.components} == {
        "agent",
        "vision",
    }

    agent = next(component for component in manifest.components if component.identifier == "agent")
    vision = next(
        component for component in manifest.components if component.identifier == "vision"
    )

    assert agent.version == "1.7.0"
    assert agent.release_tag == "v1.7.0"
    assert agent.package.filename == ("ohana_agent-1.7.0-py3-none-any.whl")
    assert agent.configuration is not None
    assert agent.service is not None
    assert agent.service.user == "ohana-agent"
    assert agent.service.group == "ohana-agent"
    assert tuple(
        (configuration_file.source, configuration_file.destination.as_posix())
        for configuration_file in agent.configuration.files
    ) == (
        ("shikamaru.example.yaml", "shikamaru.yaml"),
        ("infrastructure.example.yaml", "infrastructure.yaml"),
        ("dns.example.yaml", "plugins/dns.yaml"),
        ("ntp.example.yaml", "plugins/ntp.yaml"),
        ("mqtt.example.yaml", "plugins/mqtt.yaml"),
        ("network.example.yaml", "plugins/network.yaml"),
        ("dhcp.example.yaml", "plugins/dhcp.yaml"),
        ("zwave.example.yaml", "plugins/zwave.yaml"),
        ("wireguard.example.yaml", "plugins/wireguard.yaml"),
        ("shelly-telemetry.example.yaml", "plugins/shelly-telemetry.yaml"),
    )
    assert agent.service.arguments == (
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
        "--network-config",
        "/etc/ohana-agent/plugins/network.yaml",
        "--dhcp-config",
        "/etc/ohana-agent/plugins/dhcp.yaml",
        "--zwave-config",
        "/etc/ohana-agent/plugins/zwave.yaml",
        "--wireguard-config",
        "/etc/ohana-agent/plugins/wireguard.yaml",
        "--shelly-telemetry-config",
        "/etc/ohana-agent/plugins/shelly-telemetry.yaml",
    )

    assert vision.version == "1.6.0"
    assert vision.release_tag == "v1.6.0"
    assert vision.package.filename == ("ohana_vision-1.6.0-py3-none-any.whl")
    assert vision.configuration is not None
    assert vision.service is not None
    assert vision.service.user == "ohana-vision"
    assert vision.service.group == "ohana-vision"
    assert tuple(
        configuration_file.source for configuration_file in vision.configuration.files
    ) == ("vision.example.yaml",)


def test_repository_manifest_runtime_matches_installer() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    manifest = load_manifest(repository_root / "config" / "release-manifest.yaml")
    expected_version = ".".join(str(part) for part in MINIMUM_PYTHON_VERSION)

    assert manifest.runtime.minimum_python_version == expected_version


def test_parse_manifest_reads_agent_configuration() -> None:
    manifest = parse_manifest(VALID_MANIFEST)

    agent = next(component for component in manifest.components if component.identifier == "agent")

    assert agent.configuration is not None
    assert agent.configuration.directory == Path("/etc/ohana-agent")
    assert agent.configuration.files[0].source == "shikamaru.yaml"
    assert agent.configuration.files[2].destination == Path("plugins/dns.yaml")


def test_parse_manifest_accepts_component_without_configuration() -> None:
    manifest = parse_manifest(VALID_MANIFEST)

    vision = next(
        component for component in manifest.components if component.identifier == "vision"
    )

    assert vision.configuration is None


def test_parse_manifest_rejects_relative_configuration_directory() -> None:
    raw_manifest = {
        **VALID_MANIFEST,
        "components": {
            **VALID_MANIFEST["components"],
            "agent": {
                **VALID_MANIFEST["components"]["agent"],
                "configuration": {
                    "directory": "etc/ohana-agent",
                    "files": [
                        {
                            "source": "shikamaru.yaml",
                            "destination": "shikamaru.yaml",
                        },
                    ],
                },
            },
        },
    }

    with pytest.raises(
        ManifestError,
        match="doit être un chemin absolu",
    ):
        parse_manifest(raw_manifest)


def test_parse_manifest_rejects_absolute_configuration_destination() -> None:
    raw_manifest = {
        **VALID_MANIFEST,
        "components": {
            **VALID_MANIFEST["components"],
            "agent": {
                **VALID_MANIFEST["components"]["agent"],
                "configuration": {
                    "directory": "/etc/ohana-agent",
                    "files": [
                        {
                            "source": "shikamaru.yaml",
                            "destination": "/etc/passwd",
                        },
                    ],
                },
            },
        },
    }

    with pytest.raises(
        ManifestError,
        match="destination doit être relatif",
    ):
        parse_manifest(raw_manifest)


def test_parse_manifest_rejects_parent_directory_in_destination() -> None:
    raw_manifest = {
        **VALID_MANIFEST,
        "components": {
            **VALID_MANIFEST["components"],
            "agent": {
                **VALID_MANIFEST["components"]["agent"],
                "configuration": {
                    "directory": "/etc/ohana-agent",
                    "files": [
                        {
                            "source": "shikamaru.yaml",
                            "destination": "../passwd",
                        },
                    ],
                },
            },
        },
    }

    with pytest.raises(
        ManifestError,
        match="ne peut pas contenir",
    ):
        parse_manifest(raw_manifest)


def test_parse_manifest_reads_component_services() -> None:
    manifest = parse_manifest(VALID_MANIFEST)

    agent = next(component for component in manifest.components if component.identifier == "agent")
    vision = next(
        component for component in manifest.components if component.identifier == "vision"
    )

    assert agent.service is not None
    assert agent.service.filename == "ohana-agent.service"
    assert agent.service.user == "ohana"
    assert agent.service.arguments[0] == "--config"

    assert vision.service is not None
    assert vision.service.filename == "ohana-vision.service"
    assert vision.service.arguments == ()
