"""Chargement et validation du manifeste de plateforme."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

SUPPORTED_SCHEMA_VERSION = 1
GITHUB_REPOSITORY_PATTERN = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?/"
    r"[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?"
)
IDENTIFIER_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?")


class ManifestError(ValueError):
    """Erreur rencontrée lors du chargement ou de la validation du manifeste."""


@dataclass(frozen=True)
class ComponentService:
    """Contrat systemd officiel d'un composant."""

    filename: str
    description: str
    user: str
    group: str
    working_directory: Path
    executable: Path
    arguments: tuple[str, ...]


@dataclass(frozen=True)
class ConfigurationFile:
    """Fichier de configuration officiel."""

    source: str
    destination: Path


@dataclass(frozen=True)
class ComponentConfiguration:
    """Configuration officielle d'un composant."""

    directory: Path
    files: tuple[ConfigurationFile, ...]


@dataclass(frozen=True)
class ComponentPackage:
    """Package Python distribué pour un composant Ohana."""

    type: str
    filename: str


@dataclass(frozen=True)
class ComponentManifest:
    """Description d'un composant installable."""

    identifier: str
    name: str
    repository: str
    version: str
    release_tag: str
    package: ComponentPackage
    configuration: ComponentConfiguration | None = None
    service: ComponentService | None = None


@dataclass(frozen=True)
class RuntimeManifest:
    """Contraintes d'exécution de la plateforme."""

    minimum_python_version: str


@dataclass(frozen=True)
class CompatibilityManifest:
    """Compatibilité système déclarée par la plateforme."""

    operating_system_family: str
    service_manager: str


@dataclass(frozen=True)
class SystemCapability:
    """Implémentation système d'une capacité fournie par un profil."""

    identifier: str
    name: str
    implementation: str
    package: str
    service: str
    activation: str


@dataclass(frozen=True)
class InstallationProfile:
    """Profil de machine provisionné par Ohana-Installer."""

    identifier: str
    name: str
    capabilities: tuple[SystemCapability, ...]
    utilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlatformManifest:
    """Manifeste validé d'une release Ohana-Platform."""

    schema_version: int
    platform_name: str
    platform_version: str
    runtime: RuntimeManifest
    components: tuple[ComponentManifest, ...]
    compatibility: CompatibilityManifest
    profile: InstallationProfile | None = None


def load_manifest(path: Path | str) -> PlatformManifest:
    """Charger et valider un manifeste depuis un fichier YAML."""

    manifest_path = Path(path)

    try:
        raw_content = manifest_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ManifestError(f"Impossible de lire le manifeste {manifest_path}: {error}") from error

    try:
        raw_manifest = yaml.safe_load(raw_content)
    except yaml.YAMLError as error:
        raise ManifestError(
            f"Le manifeste {manifest_path} contient un YAML invalide: {error}"
        ) from error

    return parse_manifest(raw_manifest)


def parse_manifest(raw_manifest: Any) -> PlatformManifest:
    """Valider et convertir un manifeste YAML brut."""

    root = _require_mapping(raw_manifest, "manifest")

    schema_version = _require_integer(
        root,
        "schema_version",
        "manifest",
    )

    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise ManifestError(
            "Version de schéma non prise en charge : "
            f"{schema_version}. Version attendue : {SUPPORTED_SCHEMA_VERSION}."
        )

    platform = _require_mapping(
        root.get("platform"),
        "platform",
    )
    platform_name = _require_non_empty_string(
        platform,
        "name",
        "platform",
    )
    platform_version = _require_non_empty_string(
        platform,
        "version",
        "platform",
    )

    runtime = _parse_runtime(root.get("runtime"))
    components = _parse_components(root.get("components"))
    compatibility = _parse_compatibility(root.get("compatibility"))
    profile = _parse_profile(root.get("profile")) if root.get("profile") is not None else None

    return PlatformManifest(
        schema_version=schema_version,
        platform_name=platform_name,
        platform_version=platform_version,
        runtime=runtime,
        components=components,
        compatibility=compatibility,
        profile=profile,
    )


def _parse_profile(raw_profile: Any) -> InstallationProfile:
    """Valider le profil système optionnel de la plateforme."""

    profile = _require_mapping(raw_profile, "profile")
    identifier = _require_identifier(profile, "id", "profile")
    raw_utilities = profile.get("utilities", [])
    if not isinstance(raw_utilities, list):
        raise ManifestError("profile.utilities doit être une liste.")
    utilities: list[str] = []
    for index, raw_utility in enumerate(raw_utilities):
        if not isinstance(raw_utility, str) or not raw_utility.strip():
            raise ManifestError(f"profile.utilities[{index}] doit être un identifiant non vide.")
        utility = raw_utility.strip()
        if utility in utilities:
            raise ManifestError(f"profile.utilities contient un doublon : {utility}.")
        utilities.append(utility)
    raw_capabilities = _require_mapping(profile.get("capabilities"), "profile.capabilities")
    if not raw_capabilities:
        raise ManifestError("profile.capabilities ne peut pas être vide.")

    capabilities: list[SystemCapability] = []
    for raw_identifier, raw_capability in raw_capabilities.items():
        if not isinstance(raw_identifier, str) or not raw_identifier.strip():
            raise ManifestError("Chaque capacité doit posséder un identifiant non vide.")
        capability_identifier = raw_identifier.strip()
        path = f"profile.capabilities.{capability_identifier}"
        capability = _require_mapping(raw_capability, path)
        activation = _require_non_empty_string(capability, "activation", path)
        if activation not in {"automatic", "explicit"}:
            raise ManifestError(f"{path}.activation doit être 'automatic' ou 'explicit'.")
        service = _require_non_empty_string(capability, "service", path)
        if Path(service).name != service or not service.endswith(".service"):
            raise ManifestError(f"{path}.service doit être un simple nom d'unité .service.")
        package = _require_identifier(capability, "package", path)
        capabilities.append(
            SystemCapability(
                identifier=capability_identifier,
                name=_require_non_empty_string(capability, "name", path),
                implementation=_require_identifier(capability, "implementation", path),
                package=package,
                service=service,
                activation=activation,
            )
        )

    return InstallationProfile(
        identifier=identifier,
        name=_require_non_empty_string(profile, "name", "profile"),
        capabilities=tuple(capabilities),
        utilities=tuple(utilities),
    )


def build_release_download_url(
    component: ComponentManifest,
) -> str:
    """Construire l'URL de téléchargement du package d'un composant."""

    return (
        f"https://github.com/{component.repository}/releases/download/"
        f"{component.release_tag}/{component.package.filename}"
    )


def _parse_runtime(raw_runtime: Any) -> RuntimeManifest:
    runtime = _require_mapping(
        raw_runtime,
        "runtime",
    )
    python = _require_mapping(
        runtime.get("python"),
        "runtime.python",
    )

    minimum_version = _require_non_empty_string(
        python,
        "minimum_version",
        "runtime.python",
    )

    return RuntimeManifest(
        minimum_python_version=minimum_version,
    )


def _parse_components(
    raw_components: Any,
) -> tuple[ComponentManifest, ...]:
    """Valider les composants déclarés dans le manifeste."""

    components = _require_mapping(
        raw_components,
        "components",
    )

    if not components:
        raise ManifestError("La section components ne peut pas être vide.")

    parsed_components = tuple(
        _parse_component(identifier, raw_component)
        for identifier, raw_component in components.items()
    )

    identifiers = [component.identifier for component in parsed_components]

    if len(identifiers) != len(set(identifiers)):
        raise ManifestError("Le manifeste contient plusieurs composants avec le même identifiant.")

    return parsed_components


def _parse_component(
    identifier: Any,
    raw_component: Any,
) -> ComponentManifest:
    if not isinstance(identifier, str) or not identifier.strip():
        raise ManifestError("Chaque composant doit posséder un identifiant textuel non vide.")

    normalized_identifier = identifier.strip()
    component_path = f"components.{normalized_identifier}"
    component = _require_mapping(
        raw_component,
        component_path,
    )

    package_data = _require_mapping(
        component.get("package"),
        f"{component_path}.package",
    )

    package_type = _require_non_empty_string(
        package_data,
        "type",
        f"{component_path}.package",
    )

    if package_type != "wheel":
        raise ManifestError(f"{component_path}.package.type doit être égal à 'wheel'.")

    package = ComponentPackage(
        type=package_type,
        filename=_require_non_empty_string(
            package_data,
            "filename",
            f"{component_path}.package",
        ),
    )

    if not package.filename.endswith(".whl"):
        raise ManifestError(f"{component_path}.package.filename doit désigner un fichier .whl.")

    if Path(package.filename).name != package.filename:
        raise ManifestError(
            f"{component_path}.package.filename doit être un simple nom de fichier."
        )

    repository = _require_non_empty_string(
        component,
        "repository",
        component_path,
    )

    if GITHUB_REPOSITORY_PATTERN.fullmatch(repository) is None:
        raise ManifestError(
            f"{component_path}.repository doit respecter le format owner/repository."
        )

    raw_configuration = component.get("configuration")

    configuration = (
        _parse_configuration(
            raw_configuration,
            component_path,
        )
        if raw_configuration is not None
        else None
    )

    raw_service = component.get("service")

    service = (
        _parse_service(
            raw_service,
            component_path,
        )
        if raw_service is not None
        else None
    )

    version = _require_non_empty_string(
        component,
        "version",
        component_path,
    )
    release_tag = _require_non_empty_string(
        component,
        "release_tag",
        component_path,
    )

    if release_tag != f"v{version}":
        raise ManifestError(
            f"{component_path}.release_tag doit correspondre à la version v{version}."
        )

    return ComponentManifest(
        identifier=normalized_identifier,
        name=_require_non_empty_string(
            component,
            "name",
            component_path,
        ),
        repository=repository,
        version=version,
        release_tag=release_tag,
        package=package,
        configuration=configuration,
        service=service,
    )


def _parse_configuration(
    raw_configuration: Any,
    component_path: str,
) -> ComponentConfiguration:
    configuration_path = f"{component_path}.configuration"

    configuration = _require_mapping(
        raw_configuration,
        configuration_path,
    )

    directory_value = _require_non_empty_string(
        configuration,
        "directory",
        configuration_path,
    )
    directory_path = PurePosixPath(directory_value)

    if not directory_path.is_absolute():
        raise ManifestError(f"{configuration_path}.directory doit être un chemin absolu.")

    directory = Path(directory_value)

    raw_files = configuration.get("files")

    if not isinstance(raw_files, list) or not raw_files:
        raise ManifestError(f"{configuration_path}.files doit être une liste non vide.")

    files: list[ConfigurationFile] = []

    for index, raw_file in enumerate(raw_files):
        file_path = f"{configuration_path}.files[{index}]"
        file_data = _require_mapping(
            raw_file,
            file_path,
        )

        source = _require_non_empty_string(
            file_data,
            "source",
            file_path,
        )
        destination_value = _require_non_empty_string(
            file_data,
            "destination",
            file_path,
        )

        source_path = PurePosixPath(source)
        destination_path = PurePosixPath(destination_value)

        if source_path.is_absolute():
            raise ManifestError(f"{file_path}.source doit être relatif.")

        if ".." in source_path.parts:
            raise ManifestError(f"{file_path}.source ne peut pas contenir '..'.")

        if destination_path.is_absolute():
            raise ManifestError(f"{file_path}.destination doit être relatif.")

        if ".." in destination_path.parts:
            raise ManifestError(f"{file_path}.destination ne peut pas contenir '..'.")

        files.append(
            ConfigurationFile(
                source=source,
                destination=Path(destination_value),
            )
        )

    return ComponentConfiguration(
        directory=directory,
        files=tuple(files),
    )


def _parse_compatibility(
    raw_compatibility: Any,
) -> CompatibilityManifest:
    compatibility = _require_mapping(
        raw_compatibility,
        "compatibility",
    )
    operating_system = _require_mapping(
        compatibility.get("operating_system"),
        "compatibility.operating_system",
    )

    return CompatibilityManifest(
        operating_system_family=_require_non_empty_string(
            operating_system,
            "family",
            "compatibility.operating_system",
        ),
        service_manager=_require_non_empty_string(
            operating_system,
            "service_manager",
            "compatibility.operating_system",
        ),
    )


def _require_mapping(
    value: Any,
    path: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{path} doit être un objet YAML.")

    return value


def _require_non_empty_string(
    mapping: dict[str, Any],
    key: str,
    path: str,
) -> str:
    value = mapping.get(key)

    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{path}.{key} doit être une chaîne de caractères non vide.")

    return value.strip()


def _require_identifier(
    mapping: dict[str, Any],
    key: str,
    path: str,
) -> str:
    value = _require_non_empty_string(mapping, key, path)
    if IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ManifestError(
            f"{path}.{key} doit être un identifiant en minuscules séparé par des tirets."
        )
    return value


def _require_integer(
    mapping: dict[str, Any],
    key: str,
    path: str,
) -> int:
    value = mapping.get(key)

    if not isinstance(value, int) or isinstance(value, bool):
        raise ManifestError(f"{path}.{key} doit être un entier.")

    return value


def _parse_service(
    raw_service: Any,
    component_path: str,
) -> ComponentService:
    """Valider le contrat systemd d'un composant."""

    service_path = f"{component_path}.service"
    service = _require_mapping(
        raw_service,
        service_path,
    )

    filename = _require_non_empty_string(
        service,
        "filename",
        service_path,
    )

    if Path(filename).name != filename:
        raise ManifestError(f"{service_path}.filename doit être un simple nom de fichier.")

    if not filename.endswith(".service"):
        raise ManifestError(f"{service_path}.filename doit se terminer par '.service'.")

    working_directory_value = _require_non_empty_string(
        service,
        "working_directory",
        service_path,
    )
    executable_value = _require_non_empty_string(
        service,
        "executable",
        service_path,
    )

    working_directory_path = PurePosixPath(working_directory_value)
    executable_path = PurePosixPath(executable_value)

    if not working_directory_path.is_absolute():
        raise ManifestError(f"{service_path}.working_directory doit être un chemin absolu.")

    if not executable_path.is_absolute():
        raise ManifestError(f"{service_path}.executable doit être un chemin absolu.")

    raw_arguments = service.get("arguments", [])

    if not isinstance(raw_arguments, list):
        raise ManifestError(f"{service_path}.arguments doit être une liste.")

    arguments: list[str] = []

    for index, argument in enumerate(raw_arguments):
        if not isinstance(argument, str) or not argument:
            raise ManifestError(f"{service_path}.arguments[{index}] doit être une chaîne non vide.")

        if "\n" in argument or "\r" in argument:
            raise ManifestError(
                f"{service_path}.arguments[{index}] ne peut pas contenir de saut de ligne."
            )

        arguments.append(argument)

    return ComponentService(
        filename=filename,
        description=_require_non_empty_string(
            service,
            "description",
            service_path,
        ),
        user=_require_non_empty_string(
            service,
            "user",
            service_path,
        ),
        group=_require_non_empty_string(
            service,
            "group",
            service_path,
        ),
        working_directory=Path(working_directory_value),
        executable=Path(executable_value),
        arguments=tuple(arguments),
    )


CATALOG_SUPPORTED_SCHEMA_VERSION = 1
SEMANTIC_VERSION_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
CATALOG_RELEASE_STATUSES = frozenset({"recommended", "supported", "legacy"})


@dataclass(frozen=True)
class PlatformReleaseEntry:
    """Couple Agent/Vision publié par une release Ohana-Platform."""

    platform_version: str
    release_tag: str
    agent_version: str
    vision_version: str
    status: str


@dataclass(frozen=True)
class PlatformReleaseCatalog:
    """Catalogue officiel des compositions installables."""

    schema_version: int
    platform_name: str
    platform_version: str
    default_platform_version: str
    releases: tuple[PlatformReleaseEntry, ...]


def load_release_catalog(path: Path | str) -> PlatformReleaseCatalog:
    """Charger et valider un catalogue de releases depuis un fichier YAML."""

    catalog_path = Path(path)

    try:
        raw_content = catalog_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ManifestError(f"Impossible de lire le catalogue {catalog_path}: {error}") from error

    try:
        raw_catalog = yaml.safe_load(raw_content)
    except yaml.YAMLError as error:
        raise ManifestError(
            f"Le catalogue {catalog_path} contient un YAML invalide: {error}"
        ) from error

    return parse_release_catalog(raw_catalog)


def parse_release_catalog(raw_catalog: Any) -> PlatformReleaseCatalog:
    """Valider le catalogue des couples Agent/Vision publiés."""

    root = _require_mapping(raw_catalog, "catalogue")
    schema_version = _require_integer(root, "schema_version", "catalogue")

    if schema_version != CATALOG_SUPPORTED_SCHEMA_VERSION:
        raise ManifestError(
            "Version de schéma de catalogue non prise en charge : "
            f"{schema_version}. Version attendue : {CATALOG_SUPPORTED_SCHEMA_VERSION}."
        )

    platform = _require_mapping(root.get("platform"), "platform")
    platform_name = _require_non_empty_string(platform, "name", "platform")
    platform_version = _require_semantic_version(platform, "version", "platform")
    default_platform_version = _require_semantic_version(
        root,
        "default_platform_version",
        "catalogue",
    )

    raw_releases = root.get("releases")
    if not isinstance(raw_releases, list) or not raw_releases:
        raise ManifestError("catalogue.releases doit être une liste non vide.")

    releases = tuple(
        _parse_release_catalog_entry(raw_release, index)
        for index, raw_release in enumerate(raw_releases)
    )
    platform_versions = [release.platform_version for release in releases]

    if len(platform_versions) != len(set(platform_versions)):
        raise ManifestError(
            "Le catalogue contient plusieurs entrées pour la même version Platform."
        )

    if default_platform_version not in set(platform_versions):
        raise ManifestError(
            "catalogue.default_platform_version doit référencer une release déclarée."
        )

    recommended = tuple(release for release in releases if release.status == "recommended")
    if len(recommended) != 1:
        raise ManifestError(
            "Le catalogue doit contenir exactement une release avec le statut recommended."
        )

    if recommended[0].platform_version != default_platform_version:
        raise ManifestError(
            "La release recommended doit correspondre à catalogue.default_platform_version."
        )

    return PlatformReleaseCatalog(
        schema_version=schema_version,
        platform_name=platform_name,
        platform_version=platform_version,
        default_platform_version=default_platform_version,
        releases=releases,
    )


def select_catalog_release(
    catalog: PlatformReleaseCatalog,
    *,
    platform_version: str | None = None,
    agent_version: str | None = None,
    vision_version: str | None = None,
) -> PlatformReleaseEntry:
    """Sélectionner une composition exacte dans le catalogue."""

    if platform_version is not None:
        matching = tuple(
            release for release in catalog.releases if release.platform_version == platform_version
        )
        if len(matching) != 1:
            raise ManifestError(
                f"La version Ohana-Platform {platform_version} n'est pas déclarée "
                "dans le catalogue officiel."
            )
        return matching[0]

    if agent_version is None and vision_version is None:
        return select_catalog_release(
            catalog,
            platform_version=catalog.default_platform_version,
        )

    if agent_version is None or vision_version is None:
        raise ManifestError("Les versions Agent et Vision doivent être fournies ensemble.")

    matching = tuple(
        release
        for release in catalog.releases
        if release.agent_version == agent_version and release.vision_version == vision_version
    )

    if not matching:
        raise ManifestError(
            "Le couple Ohana-Agent "
            f"{agent_version} / Ohana-Vision {vision_version} n'est pas déclaré "
            "dans le catalogue officiel."
        )

    default_matches = tuple(
        release
        for release in matching
        if release.platform_version == catalog.default_platform_version
    )
    if default_matches:
        return default_matches[0]

    return max(
        matching,
        key=lambda release: _semantic_version_key(release.platform_version),
    )


def validate_manifest_catalog_entry(
    manifest: PlatformManifest,
    entry: PlatformReleaseEntry,
) -> None:
    """Vérifier qu'un manifeste correspond exactement à son entrée de catalogue."""

    if manifest.platform_version != entry.platform_version:
        raise ManifestError(
            "Le manifeste sélectionné annonce Ohana-Platform "
            f"{manifest.platform_version} au lieu de {entry.platform_version}."
        )

    components = {component.identifier: component for component in manifest.components}
    try:
        agent = components["agent"]
        vision = components["vision"]
    except KeyError as error:
        raise ManifestError(
            "Le manifeste sélectionné doit déclarer les composants agent et vision."
        ) from error

    if agent.version != entry.agent_version or vision.version != entry.vision_version:
        raise ManifestError(
            "Le manifeste sélectionné ne correspond pas au couple déclaré dans le catalogue : "
            f"Agent {agent.version} / Vision {vision.version}, attendu "
            f"Agent {entry.agent_version} / Vision {entry.vision_version}."
        )


def _parse_release_catalog_entry(
    raw_release: Any,
    index: int,
) -> PlatformReleaseEntry:
    path = f"catalogue.releases[{index}]"
    release = _require_mapping(raw_release, path)
    platform_version = _require_semantic_version(release, "platform_version", path)
    release_tag = _require_non_empty_string(release, "release_tag", path)

    if release_tag != f"v{platform_version}":
        raise ManifestError(
            f"{path}.release_tag doit correspondre à la version v{platform_version}."
        )

    status = _require_non_empty_string(release, "status", path)
    if status not in CATALOG_RELEASE_STATUSES:
        allowed = ", ".join(sorted(CATALOG_RELEASE_STATUSES))
        raise ManifestError(f"{path}.status doit être l'une des valeurs : {allowed}.")

    return PlatformReleaseEntry(
        platform_version=platform_version,
        release_tag=release_tag,
        agent_version=_require_semantic_version(release, "agent_version", path),
        vision_version=_require_semantic_version(release, "vision_version", path),
        status=status,
    )


def _require_semantic_version(
    mapping: dict[str, Any],
    key: str,
    path: str,
) -> str:
    version = _require_non_empty_string(mapping, key, path)
    if SEMANTIC_VERSION_PATTERN.fullmatch(version) is None:
        raise ManifestError(f"{path}.{key} doit être une version SemVer x.y.z.")
    return version


def _semantic_version_key(version: str) -> tuple[int, int, int]:
    if SEMANTIC_VERSION_PATTERN.fullmatch(version) is None:
        raise ManifestError(f"Version SemVer invalide : {version}.")
    major, minor, patch = version.split(".")
    return int(major), int(minor), int(patch)
