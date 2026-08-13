"""Tests de l'interface interactive en terminal."""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Interface
from pathlib import Path
from typing import NoReturn

import pytest

from ohana_installer.interactive import (
    MENU_WIDTH,
    OHANA_WORDMARK,
    STEP_ARTWORKS,
    InstalledStatus,
    _check_installer_before_menu,
    _is_downgrade,
    _network_configuration_form,
    _prefix_from_mask,
    _render_step_artwork,
    _select_release,
    run,
)
from ohana_installer.manifest import PlatformReleaseCatalog, PlatformReleaseEntry
from ohana_installer.network import (
    InitialNetworkConfiguration,
    NetworkProvisioningError,
    PendingNetworkChange,
)
from ohana_installer.system_capabilities import CapabilityStatus


@dataclass
class ScriptedInput:
    answers: list[str]

    def __call__(self, _prompt: str) -> str:
        if not self.answers:
            raise AssertionError("Aucune réponse interactive restante.")
        return self.answers.pop(0)


def test_each_menu_action_has_unique_ascii_artwork() -> None:
    expected = {
        "install",
        "restore",
        "update",
        "composition",
        "capabilities",
        "network",
        "automatic-update",
        "quit",
    }

    assert set(STEP_ARTWORKS) == expected
    assert len({artwork for _title, artwork in STEP_ARTWORKS.values()}) == len(expected)

    for identifier, (title, _artwork) in STEP_ARTWORKS.items():
        output = io.StringIO()
        _render_step_artwork(output, identifier)
        rendered = output.getvalue()

        assert title in rendered
        assert rendered.isascii()
        assert all(len(line) <= MENU_WIDTH for line in rendered.splitlines())


def test_installer_is_checked_once_before_menu(tmp_path: Path) -> None:
    output = io.StringIO()
    calls: list[tuple[Path, bool]] = []

    warning = _check_installer_before_menu(
        output,
        update_preparer=lambda path, *, assume_yes: (
            calls.append((path, assume_yes)) or "current"
        ),
        restart=lambda: pytest.fail("Le menu ne doit pas redémarrer."),
    )

    assert warning is None
    assert len(calls) == 1
    assert calls[0][1] is False


def test_installer_update_restarts_interactive_menu() -> None:
    output = io.StringIO()

    def restart() -> NoReturn:
        raise RuntimeError("menu restarted")

    with pytest.raises(RuntimeError, match="menu restarted"):
        _check_installer_before_menu(
            output,
            update_preparer=lambda _path, *, assume_yes: "updated",
            restart=restart,
        )


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
        input_function=ScriptedInput(["8"]),
        output=output,
    )

    assert result == 0
    assert commands == []
    rendered = output.getvalue()
    assert " ___  _   _    _    _   _    _" in rendered
    assert "/ _ \\| | | |  / \\  | \\ | |  / \\" in rendered
    assert "I N S T A L L E R" in rendered
    assert rendered.index("I N S T A L L E R") < rendered.index("Ohana Installer 1.9.4")
    assert "Ohana Installer 1.9.4" in rendered
    rendered_lines = rendered.splitlines()
    logo_lines = rendered_lines[:5]
    expected_padding = (MENU_WIDTH - max(map(len, OHANA_WORDMARK[:5])) + 1) // 2
    assert all(line.startswith(" " * expected_padding) for line in logo_lines)
    assert [line[expected_padding:] for line in logo_lines] == list(OHANA_WORDMARK[:5])
    title_line = next(line for line in rendered_lines if "I N S T A L L E R" in line)
    expected_title_padding = (MENU_WIDTH - len(OHANA_WORDMARK[-1]) + 1) // 2
    assert title_line == " " * expected_title_padding + OHANA_WORDMARK[-1]
    assert "Configurer le réseau" in rendered
    assert "FIN DE SESSION" in rendered


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
        input_function=ScriptedInput(["1", "", "8"]),
        output=output,
    )

    assert result == 0
    assert commands == [("install",)]
    assert "INSTALLATION" in output.getvalue()


def test_interactive_update_is_a_distinct_menu_action(
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
        input_function=ScriptedInput(["3", "", "8"]),
        output=output,
    )

    assert result == 0
    assert commands == [("update", "--installer-already-checked")]
    assert "MISE A JOUR" in output.getvalue()


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
            PlatformReleaseEntry(
                platform_version="1.0.19",
                release_tag="v1.0.19",
                agent_version="1.9.0",
                vision_version="1.8.0",
                status="legacy",
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
        input_function=ScriptedInput(["4", "1", "o", "", "8"]),
        output=output,
    )

    assert result == 0
    assert commands == [("update", "--platform-version", "1.0.20", "--allow-downgrade")]
    rendered = output.getvalue()
    assert "Compositions Agent/Vision antérieures supportées (1)" in rendered
    assert "Platform 1.0.19" not in rendered
    assert (
        "Les compositions historiques restent utilisables pour restaurer une sauvegarde existante."
    ) in rendered


def test_interactive_limits_supported_release_menu_to_nine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = io.StringIO()
    supported = tuple(
        PlatformReleaseEntry(
            platform_version=f"1.0.{51 - index}",
            release_tag=f"v1.0.{51 - index}",
            agent_version=f"1.{13 - index}.0",
            vision_version=f"1.{12 - index}.0",
            status="supported",
        )
        for index in range(10)
    )
    catalog = PlatformReleaseCatalog(
        schema_version=1,
        platform_name="Ohana",
        platform_version="1.0.52",
        default_platform_version="1.0.52",
        releases=(
            PlatformReleaseEntry(
                platform_version="1.0.52",
                release_tag="v1.0.52",
                agent_version="1.13.1",
                vision_version="1.12.1",
                status="recommended",
            ),
            *supported,
        ),
    )
    monkeypatch.setattr(
        "ohana_installer.interactive.download_release_catalog",
        lambda _directory: catalog,
    )

    selected = _select_release(
        input_function=ScriptedInput(["0"]),
        output=output,
    )

    assert selected is None
    rendered = output.getvalue()
    assert "Compositions Agent/Vision antérieures supportées (9)" in rendered
    assert "Platform 1.0.43" in rendered
    assert "Platform 1.0.42" not in rendered


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
        input_function=ScriptedInput(["6", "o", "o", "", "8"]),
        output=output,
    )

    assert result == 0
    assert confirmations == ["a" * 32]


def test_interactive_dhcp_activation_uses_generic_previous_server_wording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = io.StringIO()
    monkeypatch.setattr(
        "ohana_installer.interactive._installed_status",
        lambda: InstalledStatus("1.12.7", "1.11.8", True),
    )
    monkeypatch.setattr(
        "ohana_installer.interactive.local_capability_statuses",
        lambda: (
            CapabilityStatus(
                identifier="dhcp",
                name="Attribution des adresses IP",
                implementation="dnsmasq",
                installed=True,
                configured=True,
                active=False,
                state="Configurée, inactive",
            ),
            CapabilityStatus(
                identifier="time-reference",
                name="Référence temporelle",
                implementation="chrony",
                installed=True,
                configured=True,
                active=True,
                state="Active",
            ),
        ),
    )
    commands: list[Sequence[str]] = []

    result = run(
        command_runner=lambda arguments: commands.append(tuple(arguments)) or 0,
        input_function=ScriptedInput(["5", "1", "o", "", "8"]),
        output=output,
    )

    assert result == 0
    assert commands == [("capability", "activate", "dhcp", "--yes")]
    rendered = output.getvalue()
    assert "DHCP (dnsmasq) : Configurée, inactive" in rendered
    assert "Référence temporelle (chrony) : Active" in rendered
    assert "1. Activer DHCP" in rendered
    assert "2. Désactiver la référence temporelle" in rendered
    assert "Afficher le diagnostic" not in rendered
    assert "L'ancien serveur DHCP a-t-il été désactivé ?" in rendered
    assert "Freebox" not in rendered


def test_interactive_builds_local_restore_command(
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
        input_function=ScriptedInput(
            ["2", "3", "E:/Ohana/infra-01.agekey", "E:/Ohana/Backups", "", "8"]
        ),
        output=output,
    )

    assert result == 0
    assert commands == [
        (
            "restore",
            "--identity",
            "E:/Ohana/infra-01.agekey",
            "--local",
            "E:/Ohana/Backups",
        )
    ]


@pytest.mark.parametrize(
    ("restore_choice", "expected_command"),
    (
        ("1", ("restore", "--icloud")),
        ("2", ("restore", "--icloud", "--choose-backup")),
    ),
)
def test_interactive_defers_icloud_connection_and_choice_to_restore_command(
    monkeypatch: pytest.MonkeyPatch,
    restore_choice: str,
    expected_command: tuple[str, ...],
) -> None:
    output = io.StringIO()
    monkeypatch.setattr(
        "ohana_installer.interactive._installed_status",
        lambda: InstalledStatus(None, None, False),
    )
    commands: list[Sequence[str]] = []

    result = run(
        command_runner=lambda arguments: commands.append(tuple(arguments)) or 0,
        input_function=ScriptedInput(["2", restore_choice, "", "8"]),
        output=output,
    )

    assert result == 0
    assert commands == [expected_command]
    rendered = output.getvalue()
    assert "Apple ID" not in rendered
    assert "Identifiant de sauvegarde" not in rendered


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
