"""Tests de la mise a jour automatique."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ohana_installer.commands import automatic_update


def test_enable_installs_and_starts_daily_timer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(automatic_update, "SYSTEMD_SYSTEM_DIRECTORY", tmp_path)
    monkeypatch.setattr(
        automatic_update, "reload_systemd_daemon", lambda: commands.append(("reload",))
    )
    monkeypatch.setattr(
        automatic_update,
        "_run_systemctl",
        lambda *arguments, **_kwargs: commands.append(tuple(arguments)),
    )

    assert automatic_update.run(SimpleNamespace(automatic_update_action="enable")) == 0

    service = (tmp_path / automatic_update.SERVICE_NAME).read_text(encoding="utf-8")
    timer = (tmp_path / automatic_update.TIMER_NAME).read_text(encoding="utf-8")
    assert "ohana update --yes --if-needed" in service
    assert "OnCalendar=*-*-* 04:00:00" in timer
    assert "RandomizedDelaySec=30m" in timer
    assert "Persistent=true" in timer
    assert commands == [("reload",), ("enable", "--now", automatic_update.TIMER_NAME)]


def test_disable_is_idempotent_when_timer_is_already_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(automatic_update, "is_enabled", lambda: False)
    monkeypatch.setattr(
        automatic_update,
        "disable",
        lambda: pytest.fail("Le timer desactive ne doit pas etre desactive une seconde fois."),
    )

    assert automatic_update.run(SimpleNamespace(automatic_update_action="disable")) == 0


def test_remove_units_removes_service_and_timer(tmp_path: Path) -> None:
    for name in (automatic_update.SERVICE_NAME, automatic_update.TIMER_NAME):
        (tmp_path / name).write_text("unit", encoding="utf-8")

    assert automatic_update.remove_units(system_directory=tmp_path)
    assert not any(tmp_path.iterdir())
