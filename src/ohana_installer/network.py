"""Provisionnement initial et administration de NetworkManager."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Interface
from pathlib import Path

NETWORK_HELPER_PATH = Path("/usr/local/sbin/ohana-network-helper")
NETWORK_SUDOERS_PATH = Path("/etc/sudoers.d/ohana-agent-network")
AGENT_NETWORK_HELPER_ENTRYPOINT = Path("/opt/ohana-agent/venv/bin/ohana-agent-network-helper")
NMCLI_PATH = Path("/usr/bin/nmcli")
VISUDO_PATH = Path("/usr/sbin/visudo")
NETWORK_STATE_DIRECTORY = Path("/var/lib/ohana-agent/network")


class NetworkProvisioningError(RuntimeError):
    """Erreur pendant la préparation ou le provisionnement réseau."""


@dataclass(frozen=True)
class InitialNetworkConfiguration:
    """Configuration IPv4 demandée à l'installateur."""

    interface: str
    method: str
    address: IPv4Interface | None = None
    gateway: IPv4Address | None = None
    dns_servers: tuple[IPv4Address, ...] = ()

    def __post_init__(self) -> None:
        if self.method not in {"manual", "auto"}:
            raise NetworkProvisioningError("Le mode réseau doit être manual ou auto.")
        if not 1 <= len(self.interface) <= 32 or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-"
            for character in self.interface
        ):
            raise NetworkProvisioningError("Le nom de l'interface réseau est invalide.")
        if self.method == "auto":
            return
        if self.address is None or self.gateway is None or not self.dns_servers:
            raise NetworkProvisioningError(
                "Une adresse, une passerelle et au moins un DNS sont requis en mode statique."
            )
        if self.gateway not in self.address.network:
            raise NetworkProvisioningError(
                "La passerelle doit appartenir au même sous-réseau que l'adresse statique."
            )
        if self.address.ip in {
            self.address.network.network_address,
            self.address.network.broadcast_address,
        }:
            raise NetworkProvisioningError(
                "L'adresse statique ne peut pas être l'adresse réseau ou broadcast."
            )

    def payload(self) -> dict[str, object]:
        return {
            "interface": self.interface,
            "method": self.method,
            "address": str(self.address) if self.address is not None else None,
            "gateway": str(self.gateway) if self.gateway is not None else None,
            "dns_servers": [str(server) for server in self.dns_servers],
        }


@dataclass(frozen=True)
class NetworkAdministrationPreparation:
    """État de préparation du helper privilégié."""

    enabled: bool
    helper_installed: bool
    sudoers_installed: bool


@dataclass(frozen=True)
class PendingNetworkChange:
    """Transaction NetworkManager en attente de confirmation."""

    transaction_id: str
    expires_at: str | None
    state: dict[str, object]


def prepare_network_administration(
    *,
    helper_path: Path = NETWORK_HELPER_PATH,
    sudoers_path: Path = NETWORK_SUDOERS_PATH,
    entrypoint_path: Path = AGENT_NETWORK_HELPER_ENTRYPOINT,
    nmcli_path: Path = NMCLI_PATH,
    visudo_path: Path = VISUDO_PATH,
    secure_ownership: bool = True,
) -> NetworkAdministrationPreparation:
    """Installer le wrapper root et la règle sudoers strictement dédiée."""
    if not nmcli_path.is_file():
        return NetworkAdministrationPreparation(
            enabled=False,
            helper_installed=False,
            sudoers_installed=False,
        )
    if not entrypoint_path.is_file():
        raise NetworkProvisioningError(
            f"Le helper réseau Agent est introuvable : {entrypoint_path}."
        )

    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_content = "\n".join(
        [
            "#!/bin/sh",
            f'exec "{entrypoint_path}" "$@"',
            "",
        ]
    )
    helper_path.write_text(helper_content, encoding="utf-8", newline="\n")
    helper_path.chmod(0o755)

    sudoers_path.parent.mkdir(parents=True, exist_ok=True)
    sudoers_path.write_text(
        f"ohana-agent ALL=(root) NOPASSWD: {helper_path} *\n",
        encoding="utf-8",
        newline="\n",
    )
    sudoers_path.chmod(0o440)

    if secure_ownership:
        try:
            shutil.chown(helper_path, user="root", group="root")
            shutil.chown(sudoers_path, user="root", group="root")
        except (LookupError, OSError) as error:
            raise NetworkProvisioningError(
                f"Impossible de sécuriser l'administration réseau : {error}"
            ) from error

    if visudo_path.is_file():
        result = subprocess.run(
            [str(visudo_path), "-cf", str(sudoers_path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            sudoers_path.unlink(missing_ok=True)
            helper_path.unlink(missing_ok=True)
            raise NetworkProvisioningError(
                result.stderr.strip() or "La règle sudoers réseau est invalide."
            )

    return NetworkAdministrationPreparation(
        enabled=True,
        helper_installed=True,
        sudoers_installed=True,
    )


def remove_network_administration(
    *,
    helper_path: Path = NETWORK_HELPER_PATH,
    sudoers_path: Path = NETWORK_SUDOERS_PATH,
    state_directory: Path = NETWORK_STATE_DIRECTORY,
) -> bool:
    """Retirer le helper privilégié en confirmant les transactions en attente."""
    exists = helper_path.exists() or sudoers_path.exists() or state_directory.exists()
    if not exists:
        return False

    if state_directory.is_dir() and helper_path.is_file():
        for transaction_path in sorted(state_directory.glob("*.json")):
            transaction_id = transaction_path.stem
            result = subprocess.run(
                [str(helper_path), "confirm", transaction_id],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if result.returncode != 0:
                raise NetworkProvisioningError(
                    result.stderr.strip()
                    or f"Impossible de confirmer la transaction réseau {transaction_id}."
                )

    sudoers_path.unlink(missing_ok=True)
    helper_path.unlink(missing_ok=True)
    if state_directory.exists():
        if not state_directory.is_dir() or state_directory.is_symlink():
            raise NetworkProvisioningError(
                f"Le chemin d'état réseau est invalide : {state_directory}."
            )
        shutil.rmtree(state_directory)
    return True


def _run_helper_json(
    arguments: list[str],
    *,
    helper_path: Path,
    input_payload: dict[str, object] | None = None,
    timeout: int = 40,
) -> dict[str, object]:
    """Exécuter le helper restreint et valider sa réponse JSON."""
    if not helper_path.is_file():
        raise NetworkProvisioningError(f"Le helper réseau est introuvable : {helper_path}.")

    result = subprocess.run(
        [str(helper_path), *arguments],
        input=(
            json.dumps(input_payload, separators=(",", ":")) if input_payload is not None else None
        ),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise NetworkProvisioningError(
            result.stderr.strip() or "L'opération NetworkManager a été refusée."
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise NetworkProvisioningError(
            "Le helper réseau a retourné une réponse invalide."
        ) from error
    if not isinstance(payload, dict):
        raise NetworkProvisioningError("L'état réseau retourné est invalide.")
    return payload


def read_network_state(
    *,
    helper_path: Path = NETWORK_HELPER_PATH,
) -> dict[str, object]:
    """Lire la configuration NetworkManager réellement active."""
    return _run_helper_json(
        ["status"],
        helper_path=helper_path,
        timeout=20,
    )


def begin_network_configuration(
    configuration: InitialNetworkConfiguration,
    *,
    helper_path: Path = NETWORK_HELPER_PATH,
    rollback_seconds: int = 180,
) -> PendingNetworkChange:
    """Appliquer une configuration avec retour automatique tant qu'elle n'est pas confirmée."""
    if not 30 <= rollback_seconds <= 300:
        raise NetworkProvisioningError(
            "Le délai de retour automatique doit être compris entre 30 et 300 secondes."
        )

    payload = _run_helper_json(
        ["apply", "--rollback-seconds", str(rollback_seconds)],
        helper_path=helper_path,
        input_payload=configuration.payload(),
    )
    transaction_id = payload.get("transaction_id")
    state = payload.get("state")
    expires_at = payload.get("expires_at")
    if not isinstance(transaction_id, str) or len(transaction_id) != 32:
        raise NetworkProvisioningError("Le helper réseau n'a pas retourné de transaction valide.")
    if not isinstance(state, dict):
        raise NetworkProvisioningError(
            "Le helper réseau n'a pas retourné le nouvel état NetworkManager."
        )
    return PendingNetworkChange(
        transaction_id=transaction_id,
        expires_at=expires_at if isinstance(expires_at, str) else None,
        state=state,
    )


def confirm_network_configuration(
    transaction_id: str,
    *,
    helper_path: Path = NETWORK_HELPER_PATH,
) -> dict[str, object]:
    """Confirmer définitivement une transaction réseau."""
    return _run_helper_json(
        ["confirm", transaction_id],
        helper_path=helper_path,
        timeout=20,
    )


def rollback_network_configuration(
    transaction_id: str,
    *,
    helper_path: Path = NETWORK_HELPER_PATH,
) -> dict[str, object]:
    """Restaurer immédiatement la configuration précédant une transaction."""
    return _run_helper_json(
        ["rollback", transaction_id],
        helper_path=helper_path,
        timeout=30,
    )


def apply_initial_network_configuration(
    configuration: InitialNetworkConfiguration,
    *,
    helper_path: Path = NETWORK_HELPER_PATH,
    rollback_seconds: int = 90,
) -> dict[str, object]:
    """Appliquer puis confirmer une configuration initiale avec rollback de sécurité."""
    change = begin_network_configuration(
        configuration,
        helper_path=helper_path,
        rollback_seconds=rollback_seconds,
    )
    return confirm_network_configuration(
        change.transaction_id,
        helper_path=helper_path,
    )
