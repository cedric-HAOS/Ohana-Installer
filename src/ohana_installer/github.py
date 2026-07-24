"""Découverte et téléchargement sécurisé des artefacts GitHub."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ohana_installer.manifest import (
    ComponentManifest,
    ConfigurationFile,
    ManifestError,
    PlatformManifest,
    load_manifest,
)

DEFAULT_PLATFORM_REPOSITORY = "cedric-HAOS/Ohana-Platform"
DEFAULT_MANIFEST_FILENAME = "release-manifest.yaml"
DEFAULT_TIMEOUT = 15.0
GITHUB_API_ROOT = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
SHA256_HEX_LENGTH = 64
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_DELAY = 1.0
RETRYABLE_HTTP_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


class DownloadError(RuntimeError):
    """Erreur rencontrée pendant la découverte ou le téléchargement."""


@dataclass(frozen=True)
class GitHubReleaseAsset:
    """Asset publié dans une release GitHub."""

    name: str
    download_url: str
    sha256: str
    size: int


@dataclass(frozen=True)
class GitHubRelease:
    """Release GitHub officielle et ses assets vérifiables."""

    repository: str
    tag_name: str
    assets: tuple[GitHubReleaseAsset, ...]


@dataclass(frozen=True)
class DownloadedComponent:
    """Composant dont le package a été téléchargé."""

    component: ComponentManifest
    path: Path


@dataclass(frozen=True)
class DownloadedConfigurationFile:
    """Fichier de configuration officiel téléchargé."""

    component: ComponentManifest
    configuration_file: ConfigurationFile
    path: Path


def build_release_asset_url(
    *,
    repository: str,
    release_tag: str,
    filename: str,
) -> str:
    """Construire l'URL GitHub publique d'un artefact."""

    return f"https://github.com/{repository}/releases/download/{release_tag}/{filename}"


def build_latest_release_api_url(repository: str) -> str:
    """Construire l'URL API de la dernière release stable."""

    return f"{GITHUB_API_ROOT}/repos/{repository}/releases/latest"


def build_release_by_tag_api_url(
    repository: str,
    release_tag: str,
) -> str:
    """Construire l'URL API d'une release identifiée par son tag."""

    encoded_tag = urllib.parse.quote(release_tag, safe="")
    return f"{GITHUB_API_ROOT}/repos/{repository}/releases/tags/{encoded_tag}"


def _github_request(url: str, *, accept: str) -> urllib.request.Request:
    """Construire une requête GitHub explicite et versionnée."""

    return urllib.request.Request(
        url,
        headers={
            "User-Agent": "Ohana-Installer",
            "Accept": accept,
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
    )


def _read_response(
    url: str,
    *,
    accept: str,
    timeout: float,
) -> bytes:
    """Lire une réponse GitHub et retenter les erreurs transitoires."""

    request = _github_request(url, accept=accept)

    for attempt in range(1, DEFAULT_RETRY_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout,
            ) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            retryable = error.code in RETRYABLE_HTTP_STATUS_CODES
            last_attempt = attempt == DEFAULT_RETRY_ATTEMPTS

            if not retryable or last_attempt:
                raise DownloadError(
                    f"La requête GitHub a échoué avec le statut HTTP {error.code} : {url}"
                ) from error

            time.sleep(DEFAULT_RETRY_DELAY * attempt)
        except urllib.error.URLError as error:
            raise DownloadError(f"La requête GitHub a échoué : {error.reason}") from error
        except (TimeoutError, OSError) as error:
            raise DownloadError(f"La requête GitHub a échoué : {error}") from error

    raise DownloadError(f"La requête GitHub a échoué après plusieurs tentatives : {url}")


def _read_json_object(
    url: str,
    *,
    timeout: float,
) -> Mapping[str, Any]:
    """Télécharger et décoder un objet JSON depuis l'API GitHub."""

    content = _read_response(
        url,
        accept="application/vnd.github+json",
        timeout=timeout,
    )

    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DownloadError(f"L'API GitHub a renvoyé un JSON invalide : {url}") from error

    if not isinstance(payload, Mapping):
        raise DownloadError(f"L'API GitHub n'a pas renvoyé un objet JSON : {url}")

    return payload


def _require_string(
    payload: Mapping[str, Any],
    key: str,
    context: str,
) -> str:
    value = payload.get(key)

    if not isinstance(value, str) or not value.strip():
        raise DownloadError(f"{context}.{key} doit être une chaîne non vide.")

    return value.strip()


def _parse_sha256_digest(value: Any, context: str) -> str:
    """Valider un digest GitHub au format ``sha256:<hex>``."""

    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise DownloadError(f"{context} ne fournit pas de digest SHA-256 vérifiable.")

    digest = value.removeprefix("sha256:").lower()

    if len(digest) != SHA256_HEX_LENGTH:
        raise DownloadError(f"{context} fournit un digest SHA-256 invalide.")

    try:
        bytes.fromhex(digest)
    except ValueError as error:
        raise DownloadError(f"{context} fournit un digest SHA-256 invalide.") from error

    return digest


def _parse_release_asset(
    payload: Any,
    *,
    repository: str,
    release_tag: str,
) -> GitHubReleaseAsset:
    if not isinstance(payload, Mapping):
        raise DownloadError(f"La release {repository}@{release_tag} contient un asset invalide.")

    context = f"La release {repository}@{release_tag}, asset {payload.get('name', '<sans nom>')}"
    name = _require_string(payload, "name", context)
    download_url = _require_string(
        payload,
        "browser_download_url",
        context,
    )
    sha256 = _parse_sha256_digest(payload.get("digest"), context)
    size = payload.get("size")

    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise DownloadError(f"{context} fournit une taille invalide.")

    return GitHubReleaseAsset(
        name=name,
        download_url=download_url,
        sha256=sha256,
        size=size,
    )


def _parse_release(
    payload: Mapping[str, Any],
    *,
    repository: str,
) -> GitHubRelease:
    release_tag = _require_string(payload, "tag_name", "release")
    raw_assets = payload.get("assets")

    if not isinstance(raw_assets, list):
        raise DownloadError(
            f"La release {repository}@{release_tag} ne contient pas une liste d'assets valide."
        )

    assets = tuple(
        _parse_release_asset(
            asset,
            repository=repository,
            release_tag=release_tag,
        )
        for asset in raw_assets
    )

    return GitHubRelease(
        repository=repository,
        tag_name=release_tag,
        assets=assets,
    )


def discover_latest_release(
    repository: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> GitHubRelease:
    """Découvrir la dernière release stable d'un dépôt."""

    payload = _read_json_object(
        build_latest_release_api_url(repository),
        timeout=timeout,
    )
    return _parse_release(payload, repository=repository)


def get_release_by_tag(
    repository: str,
    release_tag: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> GitHubRelease:
    """Charger les métadonnées d'une release par son tag."""

    payload = _read_json_object(
        build_release_by_tag_api_url(repository, release_tag),
        timeout=timeout,
    )
    release = _parse_release(payload, repository=repository)

    if release.tag_name != release_tag:
        raise DownloadError(
            f"GitHub a renvoyé le tag {release.tag_name} au lieu de "
            f"{release_tag} pour {repository}."
        )

    return release


def find_release_asset(
    release: GitHubRelease,
    filename: str,
) -> GitHubReleaseAsset:
    """Trouver un asset unique par son nom."""

    matching_assets = tuple(asset for asset in release.assets if asset.name == filename)

    if len(matching_assets) != 1:
        raise DownloadError(
            f"La release {release.repository}@{release.tag_name} doit "
            f"contenir exactement un asset nommé {filename}."
        )

    return matching_assets[0]


def download_file(
    url: str,
    destination: Path | str,
    *,
    expected_sha256: str,
    expected_size: int | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Path:
    """Télécharger un fichier et vérifier son intégrité avant écriture."""

    expected_digest = _parse_sha256_digest(
        f"sha256:{expected_sha256}",
        f"Le téléchargement {url}",
    )
    content = _read_response(
        url,
        accept="application/octet-stream",
        timeout=timeout,
    )

    if not content:
        raise DownloadError(f"Le fichier téléchargé depuis {url} est vide.")

    if expected_size is not None and len(content) != expected_size:
        raise DownloadError(
            f"Taille inattendue pour {url} : {len(content)} octets reçus, {expected_size} attendus."
        )

    actual_digest = hashlib.sha256(content).hexdigest()

    if not hmac.compare_digest(actual_digest, expected_digest):
        raise DownloadError(
            f"Échec de la vérification SHA-256 pour {url} : "
            f"{actual_digest} reçu, {expected_digest} attendu."
        )

    destination_path = Path(destination)
    destination_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        destination_path.write_bytes(content)
    except OSError as error:
        raise DownloadError(
            f"Impossible d'écrire le fichier {destination_path} : {error}"
        ) from error

    return destination_path


def download_release_asset(
    asset: GitHubReleaseAsset,
    destination: Path | str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> Path:
    """Télécharger un asset avec les garanties fournies par GitHub."""

    return download_file(
        asset.download_url,
        destination,
        expected_sha256=asset.sha256,
        expected_size=asset.size,
        timeout=timeout,
    )


def download_platform_manifest(
    destination: Path | str,
    *,
    repository: str = DEFAULT_PLATFORM_REPOSITORY,
    release_tag: str | None = None,
    filename: str = DEFAULT_MANIFEST_FILENAME,
    timeout: float = DEFAULT_TIMEOUT,
) -> PlatformManifest:
    """Découvrir, télécharger et valider le manifeste officiel."""

    if release_tag is None:
        release = discover_latest_release(
            repository,
            timeout=timeout,
        )
    else:
        release = get_release_by_tag(
            repository,
            release_tag,
            timeout=timeout,
        )

    asset = find_release_asset(release, filename)
    destination_path = Path(destination)
    downloaded_path = download_release_asset(
        asset,
        destination_path,
        timeout=timeout,
    )

    try:
        manifest = load_manifest(downloaded_path)

        if release.tag_name != f"v{manifest.platform_version}":
            raise ManifestError(
                "La version du manifeste Platform "
                f"{manifest.platform_version} ne correspond pas à la release "
                f"{release.tag_name}."
            )

        return manifest
    except ManifestError:
        with suppress(OSError):
            downloaded_path.unlink(missing_ok=True)

        raise


def download_component_package(
    component: ComponentManifest,
    destination_directory: Path | str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> DownloadedComponent:
    """Télécharger et vérifier le package déclaré d'un composant."""

    release = get_release_by_tag(
        component.repository,
        component.release_tag,
        timeout=timeout,
    )
    asset = find_release_asset(
        release,
        component.package.filename,
    )
    destination_path = Path(destination_directory) / component.package.filename
    downloaded_path = download_release_asset(
        asset,
        destination_path,
        timeout=timeout,
    )

    return DownloadedComponent(
        component=component,
        path=downloaded_path,
    )


def download_component_packages(
    components: Iterable[ComponentManifest],
    destination_directory: Path | str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[DownloadedComponent, ...]:
    """Télécharger les packages de plusieurs composants."""

    destination_path = Path(destination_directory)
    return tuple(
        download_component_package(
            component,
            destination_path,
            timeout=timeout,
        )
        for component in components
    )


def download_component_configuration_files(
    component: ComponentManifest,
    destination_directory: Path | str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[DownloadedConfigurationFile, ...]:
    """Télécharger et vérifier les configurations d'un composant."""

    if component.configuration is None:
        return ()

    release = get_release_by_tag(
        component.repository,
        component.release_tag,
        timeout=timeout,
    )
    component_directory = Path(destination_directory) / "configuration" / component.identifier
    downloaded_files: list[DownloadedConfigurationFile] = []

    for configuration_file in component.configuration.files:
        asset = find_release_asset(
            release,
            configuration_file.source,
        )
        destination = component_directory / configuration_file.source
        downloaded_path = download_release_asset(
            asset,
            destination,
            timeout=timeout,
        )
        downloaded_files.append(
            DownloadedConfigurationFile(
                component=component,
                configuration_file=configuration_file,
                path=downloaded_path,
            )
        )

    return tuple(downloaded_files)


def download_configuration_files(
    components: Iterable[ComponentManifest],
    destination_directory: Path | str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[DownloadedConfigurationFile, ...]:
    """Télécharger les configurations de tous les composants."""

    downloaded_files: list[DownloadedConfigurationFile] = []

    for component in components:
        downloaded_files.extend(
            download_component_configuration_files(
                component,
                destination_directory,
                timeout=timeout,
            )
        )

    return tuple(downloaded_files)
