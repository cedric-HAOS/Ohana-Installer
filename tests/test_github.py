"""Tests de découverte et de téléchargement sécurisé sur GitHub."""

from __future__ import annotations

import hashlib
import json
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ohana_installer.github import (
    DEFAULT_PLATFORM_REPOSITORY,
    DownloadedComponent,
    DownloadedConfigurationFile,
    DownloadError,
    GitHubRelease,
    GitHubReleaseAsset,
    build_latest_release_api_url,
    build_release_asset_url,
    build_release_by_tag_api_url,
    discover_latest_release,
    download_component_configuration_files,
    download_component_package,
    download_component_packages,
    download_configuration_files,
    download_file,
    download_platform_manifest,
    find_release_asset,
    get_release_by_tag,
)
from ohana_installer.manifest import (
    ComponentConfiguration,
    ComponentManifest,
    ComponentPackage,
    ConfigurationFile,
    ManifestError,
)

VALID_MANIFEST_CONTENT = b"""
schema_version: 1

platform:
  name: Ohana
  version: "1.0.1"

runtime:
  python:
    minimum_version: "3.13"

components:
  agent:
    name: Ohana-Agent
    repository: cedric-HAOS/Ohana-Agent
    version: "1.1.1"
    release_tag: v1.1.1
    package:
      type: wheel
      filename: ohana_agent-1.1.1-py3-none-any.whl

  vision:
    name: Ohana-Vision
    repository: cedric-HAOS/Ohana-Vision
    version: "1.1.1"
    release_tag: v1.1.1
    package:
      type: wheel
      filename: ohana_vision-1.1.1-py3-none-any.whl

compatibility:
  operating_system:
    family: Linux
    service_manager: systemd
""".strip()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _response(content: bytes) -> MagicMock:
    response = MagicMock()
    response.read.return_value = content
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def _asset_payload(
    name: str,
    content: bytes,
    *,
    digest: str | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "browser_download_url": (
            f"https://github.com/cedric-HAOS/example/releases/download/v1.0.0/{name}"
        ),
        "digest": digest or f"sha256:{_sha256(content)}",
        "size": len(content),
    }


def _release_payload(
    *,
    tag_name: str = "v1.0.0",
    assets: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "tag_name": tag_name,
        "assets": [] if assets is None else assets,
    }


def _release_asset(
    name: str,
    content: bytes = b"content",
) -> GitHubReleaseAsset:
    return GitHubReleaseAsset(
        name=name,
        download_url=(f"https://github.com/cedric-HAOS/example/releases/download/v1.0.0/{name}"),
        sha256=_sha256(content),
        size=len(content),
    )


def _release(
    *assets: GitHubReleaseAsset,
    repository: str = "cedric-HAOS/Ohana-Agent",
    tag_name: str = "v1.0.0",
) -> GitHubRelease:
    return GitHubRelease(
        repository=repository,
        tag_name=tag_name,
        assets=assets,
    )


def _build_component(
    *,
    identifier: str = "agent",
    name: str = "Ohana-Agent",
    filename: str = "ohana_agent-1.0.0-py3-none-any.whl",
    configuration: ComponentConfiguration | None = None,
) -> ComponentManifest:
    return ComponentManifest(
        identifier=identifier,
        name=name,
        repository=f"cedric-HAOS/{name}",
        version="1.0.0",
        release_tag="v1.0.0",
        package=ComponentPackage(
            type="wheel",
            filename=filename,
        ),
        configuration=configuration,
    )


def test_build_release_urls() -> None:
    assert build_release_asset_url(
        repository="cedric-HAOS/Ohana-Platform",
        release_tag="v1.0.0",
        filename="release-manifest.yaml",
    ) == (
        "https://github.com/cedric-HAOS/Ohana-Platform/releases/download/"
        "v1.0.0/release-manifest.yaml"
    )
    assert build_latest_release_api_url("cedric-HAOS/Ohana-Platform") == (
        "https://api.github.com/repos/cedric-HAOS/Ohana-Platform/releases/latest"
    )
    assert build_release_by_tag_api_url(
        "cedric-HAOS/Ohana-Agent",
        "v1.0.0+test",
    ).endswith("/releases/tags/v1.0.0%2Btest")


def test_discover_latest_release_reads_assets(
    monkeypatch,
) -> None:
    content = b"artifact"
    payload = _release_payload(
        tag_name="v1.2.3",
        assets=[_asset_payload("artifact.whl", content)],
    )

    def fake_urlopen(request, timeout):
        assert request.full_url.endswith("/releases/latest")
        assert request.headers["X-github-api-version"] == "2022-11-28"
        assert timeout == 15.0
        return _response(json.dumps(payload).encode())

    monkeypatch.setattr(
        "ohana_installer.github.urllib.request.urlopen",
        fake_urlopen,
    )

    release = discover_latest_release("cedric-HAOS/example")

    assert release.tag_name == "v1.2.3"
    assert release.assets[0].name == "artifact.whl"
    assert release.assets[0].sha256 == _sha256(content)
    assert release.assets[0].size == len(content)


def test_discover_latest_release_rejects_missing_digest(
    monkeypatch,
) -> None:
    payload = _release_payload(
        assets=[
            _asset_payload(
                "artifact.whl",
                b"artifact",
                digest="missing",
            )
        ],
    )
    monkeypatch.setattr(
        "ohana_installer.github.urllib.request.urlopen",
        lambda request, timeout: _response(json.dumps(payload).encode()),
    )

    with pytest.raises(
        DownloadError,
        match="digest SHA-256",
    ):
        discover_latest_release("cedric-HAOS/example")


@pytest.mark.parametrize(
    "content, message",
    [
        (b"not json", "JSON invalide"),
        (b"[]", "objet JSON"),
    ],
)
def test_discover_latest_release_rejects_invalid_api_response(
    content: bytes,
    message: str,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "ohana_installer.github.urllib.request.urlopen",
        lambda request, timeout: _response(content),
    )

    with pytest.raises(DownloadError, match=message):
        discover_latest_release("cedric-HAOS/example")


def test_get_release_by_tag_validates_returned_tag(
    monkeypatch,
) -> None:
    payload = _release_payload(tag_name="v2.0.0")
    monkeypatch.setattr(
        "ohana_installer.github.urllib.request.urlopen",
        lambda request, timeout: _response(json.dumps(payload).encode()),
    )

    with pytest.raises(DownloadError, match=r"au lieu de v1\.0\.0"):
        get_release_by_tag(
            "cedric-HAOS/example",
            "v1.0.0",
        )


def test_find_release_asset_requires_exactly_one_match() -> None:
    asset = _release_asset("artifact.whl")
    release = _release(asset)

    assert find_release_asset(release, "artifact.whl") == asset

    with pytest.raises(
        DownloadError,
        match="exactement un asset",
    ):
        find_release_asset(release, "missing.whl")

    with pytest.raises(
        DownloadError,
        match="exactement un asset",
    ):
        find_release_asset(
            _release(asset, asset),
            "artifact.whl",
        )


def test_download_file_verifies_content_before_writing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    content = b"verified content"
    monkeypatch.setattr(
        "ohana_installer.github.urllib.request.urlopen",
        lambda request, timeout: _response(content),
    )
    destination = tmp_path / "downloads" / "artifact.txt"

    result = download_file(
        "https://example.invalid/artifact.txt",
        destination,
        expected_sha256=_sha256(content),
        expected_size=len(content),
    )

    assert result == destination
    assert destination.read_bytes() == content


def test_download_file_rejects_sha256_mismatch_without_writing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "ohana_installer.github.urllib.request.urlopen",
        lambda request, timeout: _response(b"tampered"),
    )
    destination = tmp_path / "artifact.txt"

    with pytest.raises(
        DownloadError,
        match="vérification SHA-256",
    ):
        download_file(
            "https://example.invalid/artifact.txt",
            destination,
            expected_sha256=_sha256(b"expected"),
        )

    assert not destination.exists()


def test_download_file_rejects_size_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    content = b"content"
    monkeypatch.setattr(
        "ohana_installer.github.urllib.request.urlopen",
        lambda request, timeout: _response(content),
    )

    with pytest.raises(DownloadError, match="Taille inattendue"):
        download_file(
            "https://example.invalid/artifact.txt",
            tmp_path / "artifact.txt",
            expected_sha256=_sha256(content),
            expected_size=len(content) + 1,
        )


def test_download_file_rejects_empty_content(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "ohana_installer.github.urllib.request.urlopen",
        lambda request, timeout: _response(b""),
    )

    with pytest.raises(DownloadError, match="est vide"):
        download_file(
            "https://example.invalid/artifact.txt",
            tmp_path / "artifact.txt",
            expected_sha256=_sha256(b""),
        )


@pytest.mark.parametrize(
    "raised_error, message",
    [
        (
            urllib.error.HTTPError(
                url="https://example.invalid",
                code=404,
                msg="Not Found",
                hdrs=None,
                fp=None,
            ),
            "statut HTTP 404",
        ),
        (
            urllib.error.URLError("connection refused"),
            "connection refused",
        ),
        (
            TimeoutError("timeout"),
            "timeout",
        ),
    ],
)
def test_download_file_normalizes_network_errors(
    raised_error: Exception,
    message: str,
    tmp_path: Path,
    monkeypatch,
) -> None:
    def raise_error(request, timeout):
        raise raised_error

    monkeypatch.setattr(
        "ohana_installer.github.urllib.request.urlopen",
        raise_error,
    )

    with pytest.raises(DownloadError, match=message):
        download_file(
            "https://example.invalid/artifact.txt",
            tmp_path / "artifact.txt",
            expected_sha256=_sha256(b"content"),
        )


def test_download_file_retries_transient_http_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    content = b"content"
    attempts = 0

    def fake_urlopen(request, timeout):
        nonlocal attempts
        attempts += 1

        if attempts < 3:
            raise urllib.error.HTTPError(
                url=request.full_url,
                code=504,
                msg="Gateway Timeout",
                hdrs=None,
                fp=None,
            )

        return _response(content)

    monkeypatch.setattr(
        "ohana_installer.github.urllib.request.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        "ohana_installer.github.time.sleep",
        lambda delay: None,
    )

    destination = download_file(
        "https://example.invalid/artifact.txt",
        tmp_path / "artifact.txt",
        expected_sha256=_sha256(content),
    )

    assert attempts == 3
    assert destination.read_bytes() == content


def test_download_file_stops_after_transient_http_retries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    attempts = 0

    def fake_urlopen(request, timeout):
        nonlocal attempts
        attempts += 1
        raise urllib.error.HTTPError(
            url=request.full_url,
            code=504,
            msg="Gateway Timeout",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(
        "ohana_installer.github.urllib.request.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        "ohana_installer.github.time.sleep",
        lambda delay: None,
    )

    with pytest.raises(DownloadError, match="statut HTTP 504"):
        download_file(
            "https://example.invalid/artifact.txt",
            tmp_path / "artifact.txt",
            expected_sha256=_sha256(b"content"),
        )

    assert attempts == 3


def test_download_platform_manifest_discovers_latest_and_verifies(
    tmp_path: Path,
    monkeypatch,
) -> None:
    asset = _asset_payload(
        "release-manifest.yaml",
        VALID_MANIFEST_CONTENT,
    )
    payload = _release_payload(
        tag_name="v1.0.1",
        assets=[asset],
    )

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/releases/latest"):
            return _response(json.dumps(payload).encode())

        return _response(VALID_MANIFEST_CONTENT)

    monkeypatch.setattr(
        "ohana_installer.github.urllib.request.urlopen",
        fake_urlopen,
    )
    destination = tmp_path / "release-manifest.yaml"

    manifest = download_platform_manifest(destination)

    assert manifest.platform_version == "1.0.1"
    assert destination.read_bytes() == VALID_MANIFEST_CONTENT


def test_download_platform_manifest_rejects_release_version_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    asset = _asset_payload(
        "release-manifest.yaml",
        VALID_MANIFEST_CONTENT,
    )
    payload = _release_payload(
        tag_name="v9.9.9",
        assets=[asset],
    )

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/releases/latest"):
            return _response(json.dumps(payload).encode())

        return _response(VALID_MANIFEST_CONTENT)

    monkeypatch.setattr(
        "ohana_installer.github.urllib.request.urlopen",
        fake_urlopen,
    )
    destination = tmp_path / "release-manifest.yaml"

    with pytest.raises(
        ManifestError,
        match="ne correspond pas à la release",
    ):
        download_platform_manifest(destination)

    assert not destination.exists()


def test_download_platform_manifest_removes_invalid_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    content = b"invalid: [yaml"
    payload = _release_payload(
        assets=[
            _asset_payload(
                "release-manifest.yaml",
                content,
            )
        ],
    )

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/releases/latest"):
            return _response(json.dumps(payload).encode())

        return _response(content)

    monkeypatch.setattr(
        "ohana_installer.github.urllib.request.urlopen",
        fake_urlopen,
    )
    destination = tmp_path / "release-manifest.yaml"

    with pytest.raises(ManifestError):
        download_platform_manifest(destination)

    assert not destination.exists()


def test_download_component_package_uses_release_digest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    component = _build_component()
    content = b"wheel-content"
    asset = _release_asset(component.package.filename, content)
    release = _release(asset)
    monkeypatch.setattr(
        "ohana_installer.github.get_release_by_tag",
        lambda repository, release_tag, timeout: release,
    )

    def fake_download_release_asset(
        release_asset,
        destination,
        *,
        timeout,
    ):
        assert release_asset == asset
        assert timeout == 15.0
        Path(destination).write_bytes(content)
        return Path(destination)

    monkeypatch.setattr(
        "ohana_installer.github.download_release_asset",
        fake_download_release_asset,
    )

    result = download_component_package(component, tmp_path)

    assert isinstance(result, DownloadedComponent)
    assert result.component == component
    assert result.path.read_bytes() == content


def test_download_component_packages_stops_on_first_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    agent = _build_component()
    vision = _build_component(
        identifier="vision",
        name="Ohana-Vision",
        filename="ohana_vision-1.0.0-py3-none-any.whl",
    )
    attempted_components: list[str] = []

    def fake_download_component_package(
        component,
        destination_directory,
        *,
        timeout,
    ):
        attempted_components.append(component.identifier)
        raise DownloadError("échec")

    monkeypatch.setattr(
        "ohana_installer.github.download_component_package",
        fake_download_component_package,
    )

    with pytest.raises(DownloadError, match="échec"):
        download_component_packages(
            (agent, vision),
            tmp_path,
        )

    assert attempted_components == ["agent"]


def test_download_component_configuration_files_uses_one_release(
    tmp_path: Path,
    monkeypatch,
) -> None:
    component = _build_component(
        configuration=ComponentConfiguration(
            directory=Path("/etc/ohana-agent"),
            files=(
                ConfigurationFile(
                    source="shikamaru.yaml",
                    destination=Path("shikamaru.yaml"),
                ),
                ConfigurationFile(
                    source="dns.yaml",
                    destination=Path("plugins/dns.yaml"),
                ),
            ),
        )
    )
    assets = (
        _release_asset("shikamaru.yaml"),
        _release_asset("dns.yaml"),
    )
    release = _release(*assets)
    release_calls = 0

    def fake_get_release(repository, release_tag, *, timeout):
        nonlocal release_calls
        release_calls += 1
        return release

    monkeypatch.setattr(
        "ohana_installer.github.get_release_by_tag",
        fake_get_release,
    )

    def fake_download_release_asset(
        asset,
        destination,
        *,
        timeout,
    ):
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_text("content", encoding="utf-8")
        return Path(destination)

    monkeypatch.setattr(
        "ohana_installer.github.download_release_asset",
        fake_download_release_asset,
    )

    results = download_component_configuration_files(
        component,
        tmp_path,
    )

    assert release_calls == 1
    assert len(results) == 2
    assert all(isinstance(result, DownloadedConfigurationFile) for result in results)
    assert results[0].path == (tmp_path / "configuration" / "agent" / "shikamaru.yaml")


def test_download_component_configuration_files_ignores_missing_configuration(
    tmp_path: Path,
) -> None:
    assert (
        download_component_configuration_files(
            _build_component(configuration=None),
            tmp_path,
        )
        == ()
    )


def test_download_configuration_files_collects_declared_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    agent = _build_component(
        configuration=ComponentConfiguration(
            directory=Path("/etc/ohana-agent"),
            files=(
                ConfigurationFile(
                    source="shikamaru.yaml",
                    destination=Path("shikamaru.yaml"),
                ),
            ),
        )
    )
    vision = _build_component(
        identifier="vision",
        name="Ohana-Vision",
        filename="ohana_vision-1.0.0-py3-none-any.whl",
    )

    def fake_download_configurations(
        component,
        destination_directory,
        *,
        timeout,
    ):
        if component.configuration is None:
            return ()

        configuration_file = component.configuration.files[0]
        return (
            DownloadedConfigurationFile(
                component=component,
                configuration_file=configuration_file,
                path=tmp_path / configuration_file.source,
            ),
        )

    monkeypatch.setattr(
        "ohana_installer.github.download_component_configuration_files",
        fake_download_configurations,
    )

    results = download_configuration_files(
        (agent, vision),
        tmp_path,
    )

    assert len(results) == 1
    assert results[0].component.identifier == "agent"
    assert DEFAULT_PLATFORM_REPOSITORY == ("cedric-HAOS/Ohana-Platform")
