"""Install the pinned rclone build required by the HAOS backup plugin."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile

RCLONE_VERSION = "1.74.4"
RCLONE_INSTALLATION_PATH = Path("/usr/bin/rclone")
RCLONE_ASSETS = {
    "x86_64": ("linux-amd64", "fe435e0c36228e7c2f116a8701f01127bb1f694005fc11d1f27186c8bca4115d"),
    "amd64": ("linux-amd64", "fe435e0c36228e7c2f116a8701f01127bb1f694005fc11d1f27186c8bca4115d"),
    "aarch64": ("linux-arm64", "97685285c9ad6a0cf17d5844115d2a67245af6444db672187074bd9c358de419"),
    "arm64": ("linux-arm64", "97685285c9ad6a0cf17d5844115d2a67245af6444db672187074bd9c358de419"),
    "armv7l": ("linux-arm-v7", "75844809d25d2534da96220727e7746a300e30ec8c676ca98c47affe5a752e7b"),
    "armv6l": ("linux-arm-v6", "c9e1048feb597938884c0fff314d5d9a002599933cb94ce17fee19599cbfa3f1"),
}


class RcloneInstallationError(RuntimeError):
    """Raised when the pinned rclone binary cannot be installed."""


def ensure_rclone(
    destination: Path = RCLONE_INSTALLATION_PATH,
) -> str:
    """Install and verify the pinned rclone release when needed."""
    if _installed_version(destination) == RCLONE_VERSION:
        return RCLONE_VERSION
    machine = platform.machine().casefold()
    try:
        asset_platform, expected_sha256 = RCLONE_ASSETS[machine]
    except KeyError as error:
        raise RcloneInstallationError(
            f"Architecture rclone non prise en charge : {machine or 'inconnue'}."
        ) from error
    filename = f"rclone-v{RCLONE_VERSION}-{asset_platform}.zip"
    url = f"https://downloads.rclone.org/v{RCLONE_VERSION}/{filename}"
    try:
        with tempfile.TemporaryDirectory(prefix="ohana-rclone-") as temporary:
            archive = Path(temporary) / filename
            _download(url, archive, expected_sha256)
            with ZipFile(archive) as bundle:
                member = next(
                    (name for name in bundle.namelist() if name.endswith("/rclone")),
                    None,
                )
                if member is None:
                    raise RcloneInstallationError(
                        "L'archive rclone ne contient pas le binaire attendu."
                    )
                extracted = Path(temporary) / "rclone"
                with bundle.open(member) as source, extracted.open("wb") as target:
                    shutil.copyfileobj(source, target)
                extracted.chmod(0o755)
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(extracted, destination)
    except (OSError, BadZipFile) as error:
        raise RcloneInstallationError(f"Impossible d'installer rclone : {error}") from error
    if _installed_version(destination) != RCLONE_VERSION:
        raise RcloneInstallationError("La version rclone installée est invalide.")
    return RCLONE_VERSION


def _download(url: str, destination: Path, expected_sha256: str) -> None:
    digest = hashlib.sha256()
    try:
        with urlopen(url, timeout=60) as response, destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
    except (HTTPError, URLError, OSError) as error:
        raise RcloneInstallationError(f"Impossible de télécharger rclone : {error}") from error
    if digest.hexdigest() != expected_sha256:
        destination.unlink(missing_ok=True)
        raise RcloneInstallationError("La somme SHA-256 de rclone est invalide.")


def _installed_version(binary: Path) -> str | None:
    if not binary.is_file():
        return None
    result = subprocess.run(
        [str(binary), "version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.startswith("rclone v"):
        return None
    return result.stdout.splitlines()[0].removeprefix("rclone v").strip()
