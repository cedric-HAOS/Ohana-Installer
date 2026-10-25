"""Compte rendu d'une restauration, lisible par l'Agent.

Une restauration d'INFRA-01 est une opération réelle sur une vraie machine : seul
l'Installer sait comment elle s'est terminée. Il écrit un petit fichier JSON, sans
secret, que l'Agent lit pour tenir son registre des restaurations (une
restauration réussie, partielle ou échouée y devient un test déclaré par
l'Installer). Écrire ce compte rendu ne doit jamais faire échouer la restauration.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ohana_installer.version import __version__

REPORT_DIRECTORY = Path("/var/lib/ohana-installer/restore-reports")
OUTCOMES = ("ok", "partial", "failed")
# After these stages the machine has been modified: a failure leaves it half restored.
MODIFYING_STAGES = ("install", "configuration", "identity")
_SECRETS = re.compile(
    r"(password|token|cookie|session[_-]?id|trust|secret)[\"'=: ]+[^\s,\"']+",
    re.IGNORECASE,
)


def _local_zone() -> tzinfo:
    """Paris, or UTC where the machine has no time zone database (the Agent
    expresses every report in Paris time anyway)."""
    try:
        return ZoneInfo("Europe/Paris")
    except ZoneInfoNotFoundError:
        return UTC


@dataclass
class RestoreProgress:
    """Where a restoration has got to, for its report."""

    mode: str
    stage: str = "selection"
    backup_id: str | None = None


def outcome_for_failure(stage: str) -> str:
    return "partial" if stage in MODIFYING_STAGES else "failed"


def _clean(detail: str) -> str:
    return _SECRETS.sub(r"\1=***", " ".join(detail.split()))[:300]


def write_report(
    progress: RestoreProgress,
    outcome: str,
    detail: str = "",
    *,
    directory: Path | None = None,
    now: datetime | None = None,
) -> Path | None:
    """Write the report; returns its path, or ``None`` when it cannot be written."""
    if outcome not in OUTCOMES:
        raise ValueError(f"Résultat de restauration inconnu : {outcome!r}.")
    zone = _local_zone()
    finished = (now or datetime.now(zone)).astimezone(zone)
    report_id = str(uuid4())
    document = {
        "schema_version": 1,
        "report_id": report_id,
        "target": "infra-01",
        "outcome": outcome,
        "mode": progress.mode,
        "stage": progress.stage,
        "backup_id": progress.backup_id,
        "detail": _clean(detail),
        "finished_at": finished.isoformat(timespec="seconds"),
        "installer_version": __version__,
    }
    directory = directory or REPORT_DIRECTORY
    try:
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o755)
        path = directory / f"{finished:%Y%m%dT%H%M%S}-{report_id[:8]}.json"
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        path.chmod(0o644)
    except OSError:
        return None
    return path
