"""Install the pinned AdGuard replication engine without starting replication."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
from contextlib import suppress
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import yaml

VERSION = "0.9.4"
BINARY = Path("/opt/adguardhome-sync/adguardhome-sync")
CONFIGURATION = Path("/etc/ohana-agent/adguardhome-sync.yaml")
SYSTEMD_DIRECTORY = Path("/etc/systemd/system")
HELPER = Path("/opt/ohana-agent/venv/bin/ohana-agent-adguard-sync-helper")
STATE = Path("/etc/ohana-agent/adguard-sync-state.json")
SUDOERS = Path("/etc/sudoers.d/ohana-agent-adguard-sync")
TIMER = "adguardhome-sync.timer"
SERVICE = "adguardhome-sync.service"
ASSETS = {
    "x86_64": ("amd64", "b451d31054d912c2973bda5793ec6f538ab834e335e71d959f1561cf75b2c9de"),
    "amd64": ("amd64", "b451d31054d912c2973bda5793ec6f538ab834e335e71d959f1561cf75b2c9de"),
    "aarch64": ("arm64", "5e376ae27496e334f4d067725b3ca9bc048392df7701ed089238e3cbe6531024"),
    "arm64": ("arm64", "5e376ae27496e334f4d067725b3ca9bc048392df7701ed089238e3cbe6531024"),
    "armv7l": ("armv7", "421b239058bef5a655e52ca6afa0d943b2e5dcd7f46ed269830f2f955b366e13"),
}
CONFIGURATION_TEMPLATE = """# Configure and activate in Vision; credentials are not distributed.
cron: ""
runOnStart: true
api:
  port: 0
origin:
  url: http://192.168.1.11
  username: admin
  password: ""
replica:
  url: http://192.168.1.12
  username: admin
  password: ""
features:
  dhcp:
    serverConfig: false
    staticLeases: false
"""
SERVICE_TEMPLATE = """# Managed by Ohana-Installer
[Unit]
Description=Ohana DHCP reservations and AdGuard Home replication
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
Group=ohana-agent
ExecStart=/opt/ohana-agent/venv/bin/ohana-agent-adguard-reservations
ExecStart=/opt/adguardhome-sync/adguardhome-sync run \
  --config /etc/ohana-agent/adguardhome-sync.yaml --cron= --api-port=0 --runOnStart=true
ExecStart=/opt/ohana-agent/venv/bin/ohana-agent-adguard-reservations --verify-replica
TimeoutStartSec=180
UMask=0027
"""
TIMER_TEMPLATE = """# Managed by Ohana-Installer
[Unit]
Description=Synchronize Ohana reserved DNS names every five minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
Unit=adguardhome-sync.service

[Install]
WantedBy=timers.target
"""


class AdGuardInstallationError(RuntimeError):
    """The verified engine could not be installed."""


def installed_version(binary: Path = BINARY) -> str | None:
    if not binary.is_file() or binary.is_symlink():
        return None
    try:
        result = subprocess.run(
            (str(binary), "--version"),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"\bversion v?(\d+\.\d+\.\d+)\b", result.stdout)
    return match[1] if result.returncode == 0 and match else None


def needs_provisioning() -> bool:
    return (
        installed_version() != VERSION
        or not CONFIGURATION.is_file()
        or not STATE.is_file()
        or (HELPER.is_file() and not SUDOERS.is_file())
        or any(not (SYSTEMD_DIRECTORY / name).is_file() for name in (SERVICE, TIMER))
    )


def configuration_ready() -> bool:
    """An empty installation template is not an operational configuration."""
    try:
        with CONFIGURATION.open("rb") as source:
            raw = source.read(65537)
        if len(raw) > 65536:
            return False
        document = yaml.safe_load(raw)
        return isinstance(document, dict) and all(
            isinstance(document.get(role), dict)
            and all(
                isinstance(document[role].get(field), str) and document[role][field]
                for field in ("url", "username", "password")
            )
            for role in ("origin", "replica")
        )
    except (OSError, yaml.YAMLError):
        return False


def ensure_binary(destination: Path = BINARY) -> bool:
    """Verify the archive and candidate before atomically replacing the binary."""
    if installed_version(destination) == VERSION:
        return False
    try:
        architecture, expected = ASSETS[platform.machine().casefold()]
    except KeyError as error:
        raise AdGuardInstallationError("Architecture AdGuard non prise en charge.") from error
    filename = f"adguardhome-sync_{VERSION}_linux_{architecture}.tar.gz"
    url = f"https://github.com/bakito/adguardhome-sync/releases/download/v{VERSION}/{filename}"
    staging: Path | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="ohana-adguard-") as directory:
            archive = Path(directory) / filename
            digest = hashlib.sha256()
            size = 0
            with urlopen(url, timeout=60) as response, archive.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > 32 * 1024 * 1024:
                        raise AdGuardInstallationError("Archive AdGuard trop volumineuse.")
                    output.write(chunk)
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise AdGuardInstallationError("Somme SHA-256 AdGuard invalide.")
            with tarfile.open(archive, "r:gz") as bundle:
                members = [member for member in bundle if member.name == "adguardhome-sync"]
                if (
                    len(members) != 1
                    or not members[0].isfile()
                    or members[0].size > 64 * 1024 * 1024
                ):
                    raise AdGuardInstallationError("Binaire AdGuard absent ou invalide.")
                source = bundle.extractfile(members[0])
                if source is None:
                    raise AdGuardInstallationError("Binaire AdGuard illisible.")
                destination.parent.mkdir(parents=True, exist_ok=True)
                descriptor, name = tempfile.mkstemp(prefix=".adguard-", dir=destination.parent)
                staging = Path(name)
                with source, os.fdopen(descriptor, "wb") as target:
                    shutil.copyfileobj(source, target)
                staging.chmod(0o755)
                if installed_version(staging) != VERSION:
                    raise AdGuardInstallationError("Version du binaire AdGuard invalide.")
                os.replace(staging, destination)
        return True
    except (OSError, URLError, tarfile.TarError) as error:
        raise AdGuardInstallationError("Installation du moteur AdGuard impossible.") from error
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)


def provision(*, command_runner=subprocess.run, secure_ownership: bool = True) -> bool:
    """Keep operator configuration, units and activation; never enable a new timer."""
    created = ensure_binary()
    if CONFIGURATION.is_symlink():
        raise AdGuardInstallationError("Configuration AdGuard non régulière.")
    CONFIGURATION.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIGURATION.exists():
        CONFIGURATION.write_text(CONFIGURATION_TEMPLATE, encoding="utf-8", newline="\n")
    CONFIGURATION.chmod(0o660)
    if secure_ownership:
        # The service account is created later during a fresh installation.
        with suppress(LookupError):
            shutil.chown(CONFIGURATION, user="root", group="ohana-agent")
    if STATE.is_symlink():
        raise AdGuardInstallationError("État AdGuard non régulier.")
    if not STATE.exists():
        enabled = command_runner(
            ("/usr/bin/systemctl", "is-enabled", TIMER),
            capture_output=True,
            text=True,
            check=False,
        )
        STATE.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "enabled": enabled.returncode == 0 and enabled.stdout.strip() == "enabled",
                }
            ),
            encoding="utf-8",
        )
        STATE.chmod(0o640)
    SYSTEMD_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for name, content in ((SERVICE, SERVICE_TEMPLATE), (TIMER, TIMER_TEMPLATE)):
        target = SYSTEMD_DIRECTORY / name
        if target.is_symlink():
            raise AdGuardInstallationError("Unité AdGuard non régulière.")
        if not target.exists():
            target.write_text(content, encoding="utf-8", newline="\n")
            target.chmod(0o644)
    result = command_runner(
        ("/usr/bin/systemctl", "daemon-reload"),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise AdGuardInstallationError("Rechargement systemd AdGuard impossible.")
    return created


def prepare_administration(*, secure_ownership: bool = True) -> None:
    """Grant only the fixed activation/deactivation commands to Agent."""
    if secure_ownership:
        for path in (CONFIGURATION, STATE):
            if path.is_file() and not path.is_symlink():
                shutil.chown(path, user="root", group="ohana-agent")
                path.chmod(0o660 if path == CONFIGURATION else 0o640)
    if not HELPER.is_file():
        return  # A historical Agent can still run the pre-existing systemd cycle.
    SUDOERS.parent.mkdir(parents=True, exist_ok=True)
    SUDOERS.write_text(
        f"ohana-agent ALL=(root) NOPASSWD: {HELPER} activate, {HELPER} deactivate\n",
        encoding="utf-8",
        newline="\n",
    )
    SUDOERS.chmod(0o440)
    if secure_ownership:
        shutil.chown(SUDOERS, user="root", group="root")
    result = subprocess.run(
        ("/usr/sbin/visudo", "-cf", str(SUDOERS)),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode:
        SUDOERS.unlink(missing_ok=True)
        raise AdGuardInstallationError("Règle sudoers AdGuard invalide.")
