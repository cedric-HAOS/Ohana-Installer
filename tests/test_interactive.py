"""Tests de l'interface interactive en terminal."""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Interface

import pytest

from ohana_installer.interactive import (
    InstalledStatus,
    _is_downgrade,
    _network_configuration_form,
    _prefix_from_mask,
    run,
)
from ohana_installer.manifest import PlatformReleaseCatalog, PlatformReleaseEntry
from ohana_installer.network import (
    InitialNetworkConfiguration,
    NetworkProvisioningError,
    PendingNetworkChange,
)


@dataclass
class ScriptedInput:
    answers: list[str]

    def __call__(self, _prompt: str) -> str:
        if not self.answers:
            raise AssertionError("Aucune réponse interactive restante.")
        return self.answers.pop(0)


def test_interactive_menu_quits_without_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = io.StringIO()
    monkeypatch.setattr(
        "ohana_installer.interactive._installed_status",
        lambda: InstalledStatus(None, None, False),
    )
    commands: list[Sequence[str]] = []

    result = run(
        command_runner=lambda arguments: commands.append(arguments) or 0,
        input_function=ScriptedInput(["5"]),
        output=output,
    )

    assert result == 0
    assert commands == []
    assert "Ohana Installer 1.7.0" in output.getvalue()
    assert "Configurer le réseau" in output.getvalue()


def test_interactive_recommended_installs_on_empty_machine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = io.StringIO()
    monkeypatch.setattr(
        "ohana_installer.interactive._installed_status",
        lambda: InstalledStatus(None, None, False),
    )
    commands: list[Sequence[str]] = []

    result = run(
        command_runner=lambda arguments: commands.append(tuple(arguments)) or 0,
        input_function=ScriptedInput(["1", "", "5"]),
        output=output,
    )

    assert result == 0
    assert commands == [("install",)]


def test_interactive_recommended_updates_existing_installation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = io.StringIO()
    monkeypatch.setattr(
        "ohana_installer.interactive._installed_status",
        lambda: InstalledStatus("1.10.0", "1.9.0", True),
    )
    commands: list[Sequence[str]] = []

    result = run(
        command_runner=lambda arguments: commands.append(tuple(arguments)) or 0,
        input_function=ScriptedInput(["1", "", "5"]),
        output=output,
    )

    assert result == 0
    assert commands == [("update",)]


def test_interactive_selects_catalog_release_and_allows_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = io.StringIO()
    catalog = PlatformReleaseCatalog(
        schema_version=1,
        platform_name="Ohana",
        platform_version="1.0.22",
        default_platform_version="1.0.22",
        releases=(
            PlatformReleaseEntry(
                platform_version="1.0.22",
                release_tag="v1.0.22",
                agent_version="1.11.0",
                vision_version="1.10.0",
                status="recommended",
            ),
            PlatformReleaseEntry(
                platform_version="1.0.20",
                release_tag="v1.0.20",
                agent_version="1.10.0",
                vision_version="1.9.0",
                status="supported",
            ),
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.interactive._installed_status",
        lambda: InstalledStatus("1.11.0", "1.10.0", True),
    )
    monkeypatch.setattr(
        "ohana_installer.interactive.download_release_catalog",
        lambda _directory: catalog,
    )
    commands: list[Sequence[str]] = []

    result = run(
        command_runner=lambda arguments: commands.append(tuple(arguments)) or 0,
        input_function=ScriptedInput(["2", "1", "o", "", "5"]),
        output=output,
    )

    assert result == 0
    assert commands == [("update", "--platform-version", "1.0.20", "--allow-downgrade")]


def test_network_form_accepts_dotted_mask() -> None:
    state = {
        "interface": "eth0",
        "method": "manual",
        "address": "192.168.1.10/24",
        "gateway": "192.168.1.1",
        "dns_servers": ["192.168.1.11", "192.168.1.12"],
    }
    output = io.StringIO()

    configuration = _network_configuration_form(
        state=state,
        input_function=ScriptedInput(
            [
                "",
                "1",
                "192.168.1.20",
                "255.255.255.0",
                "",
                "",
                "",
            ]
        ),
        output=output,
    )

    assert configuration == InitialNetworkConfiguration(
        interface="eth0",
        method="manual",
        address=IPv4Interface("192.168.1.20/24"),
        gateway=IPv4Address("192.168.1.1"),
        dns_servers=(
            IPv4Address("192.168.1.11"),
            IPv4Address("192.168.1.12"),
        ),
    )


def test_interactive_network_confirms_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = io.StringIO()
    monkeypatch.setattr(
        "ohana_installer.interactive._installed_status",
        lambda: InstalledStatus("1.11.0", "1.10.0", True),
    )
    monkeypatch.setattr(
        "ohana_installer.interactive.read_network_state",
        lambda: {
            "interface": "eth0",
            "method": "manual",
            "address": "192.168.1.10/24",
            "gateway": "192.168.1.1",
            "dns_servers": ["192.168.1.11", "192.168.1.12"],
            "pending_change": None,
        },
    )
    configuration = InitialNetworkConfiguration(
        interface="eth0",
        method="auto",
    )
    monkeypatch.setattr(
        "ohana_installer.interactive._network_configuration_form",
        lambda **_kwargs: configuration,
    )
    monkeypatch.setattr(
        "ohana_installer.interactive.begin_network_configuration",
        lambda *_args, **_kwargs: PendingNetworkChange(
            transaction_id="a" * 32,
            expires_at=None,
            state={},
        ),
    )
    confirmations: list[str] = []
    monkeypatch.setattr(
        "ohana_installer.interactive.confirm_network_configuration",
        lambda transaction_id: confirmations.append(transaction_id) or {},
    )

    result = run(
        command_runner=lambda _arguments: 0,
        input_function=ScriptedInput(["3", "o", "o", "", "5"]),
        output=output,
    )

    assert result == 0
    assert confirmations == ["a" * 32]


def test_prefix_from_mask_rejects_non_contiguous_mask() -> None:
    with pytest.raises(NetworkProvisioningError, match="Masque IPv4 invalide"):
        _prefix_from_mask("255.0.255.0")


def test_is_downgrade_compares_agent_and_vision() -> None:
    status = InstalledStatus("1.11.0", "1.10.0", True)
    release = PlatformReleaseEntry(
        platform_version="1.0.20",
        release_tag="v1.0.20",
        agent_version="1.10.0",
        vision_version="1.9.0",
        status="supported",
    )

    assert _is_downgrade(status, release) is True
