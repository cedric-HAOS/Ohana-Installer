"""Session iCloud rclone temporaire utilisée pendant une restauration."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ICloudAuthenticationError(RuntimeError):
    """Échec de création de la session iCloud temporaire."""


@dataclass(frozen=True)
class ICloudContinuation:
    """État opaque à renvoyer à rclone avec le code 2FA."""

    apple_id: str
    password: str
    state: str


class TemporaryICloudSession:
    """Configurer un remote iCloud dans un fichier placé en RAM."""

    def __init__(
        self,
        *,
        binary: Path,
        config_path: Path,
        remote_name: str = "icloud",
        runner: Any = subprocess.run,
    ) -> None:
        self.binary = binary
        self.config_path = config_path
        self.remote_name = remote_name
        self._runner = runner

    def begin(self, apple_id: str, password: str) -> ICloudContinuation | None:
        """Démarrer l'authentification et retourner un éventuel défi 2FA."""

        normalized_id = apple_id.strip()
        if not normalized_id or not password:
            raise ICloudAuthenticationError("Apple ID et mot de passe sont obligatoires.")
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        response = self._invoke(normalized_id, password)
        for _index in range(10):
            state = str(response.get("State") or "")
            if not state:
                self._secure_config()
                return None
            option = response.get("Option")
            option_name = option.get("Name") if isinstance(option, dict) else None
            if option_name == "config_2fa":
                return ICloudContinuation(normalized_id, password, state)
            default = option.get("Default") if isinstance(option, dict) else None
            if default is None:
                raise ICloudAuthenticationError(
                    f"rclone demande une option non prise en charge : {option_name!r}."
                )
            response = self._continue(
                ICloudContinuation(normalized_id, password, state),
                str(default),
            )
        raise ICloudAuthenticationError("rclone n'a pas terminé la configuration iCloud.")

    def complete(self, continuation: ICloudContinuation, code: str) -> None:
        """Terminer le défi 2FA puis accepter les valeurs par défaut restantes."""

        response = self._continue(continuation, code.strip())
        current = continuation
        for _index in range(10):
            state = str(response.get("State") or "")
            if not state:
                self._secure_config()
                return
            option = response.get("Option")
            default = option.get("Default") if isinstance(option, dict) else None
            if default is None:
                name = option.get("Name") if isinstance(option, dict) else None
                raise ICloudAuthenticationError(
                    f"rclone demande une option non prise en charge : {name!r}."
                )
            current = ICloudContinuation(current.apple_id, current.password, state)
            response = self._continue(current, str(default))
        raise ICloudAuthenticationError("rclone n'a pas terminé la configuration iCloud.")

    def _invoke(self, apple_id: str, password: str) -> dict[str, Any]:
        return self._run(
            [
                str(self.binary),
                "config",
                "create",
                self.remote_name,
                "iclouddrive",
                "service",
                "drive",
                "apple_id",
                apple_id,
                "password",
                password,
                "--config",
                str(self.config_path),
                "--non-interactive",
                "--obscure",
            ]
        )

    def _continue(
        self,
        continuation: ICloudContinuation,
        result: str,
    ) -> dict[str, Any]:
        return self._run(
            [
                str(self.binary),
                "config",
                "create",
                self.remote_name,
                "iclouddrive",
                "service",
                "drive",
                "apple_id",
                continuation.apple_id,
                "password",
                continuation.password,
                "--config",
                str(self.config_path),
                "--non-interactive",
                "--obscure",
                "--continue",
                "--state",
                continuation.state,
                "--result",
                result,
            ]
        )

    def _run(self, command: list[str]) -> dict[str, Any]:
        result = self._runner(
            command,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "RCLONE_CONFIG_PASS": ""},
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "erreur inconnue").strip()
            for key in ("apple_id", "password"):
                if key in command:
                    index = command.index(key) + 1
                    if index < len(command):
                        detail = detail.replace(command[index], "***")
            raise ICloudAuthenticationError(f"Impossible de configurer iCloud : {detail[:500]}")
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as error:
            raise ICloudAuthenticationError("Réponse JSON rclone invalide.") from error
        if not isinstance(payload, dict):
            raise ICloudAuthenticationError("Réponse JSON rclone invalide.")
        return payload

    def _secure_config(self) -> None:
        if not self.config_path.is_file():
            raise ICloudAuthenticationError("rclone n'a pas créé la configuration iCloud.")
        self.config_path.chmod(0o600)
