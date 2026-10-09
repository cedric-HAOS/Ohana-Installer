"""Stage durable client credentials without replaying distributed jobs."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path, PurePosixPath

import yaml

TABLE_GROUPS = {
    "distributed_worker_credentials": "jobs",
    "companion_credentials": "control",
    "companion_push_tokens": "control",
}


def stage_authorizations(payload: Path, destination_root: Path) -> list[tuple[Path, Path]]:
    """Import the known credential tables into copies of the installed databases."""
    export = payload / "etc/ohana-agent/recovery/authorizations.json"
    if not export.is_file():
        return []
    document = json.loads(export.read_text(encoding="utf-8"))
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != 1
        or not isinstance(document.get("tables"), dict)
        or not set(document["tables"]).issubset(TABLE_GROUPS)
    ):
        raise ValueError("Invalid authorization backup contract")
    configuration = yaml.safe_load((payload / "etc/ohana-agent/shikamaru.yaml").read_text())
    administration = configuration.get("administration", {})
    jobs = administration.get("jobs", {}).get(
        "database_path", "/var/lib/ohana-agent/distributed-jobs.db"
    )
    paths = {"jobs": jobs, "control": administration.get("database_path") or jobs}
    staged: dict[Path, Path] = {}
    for table, content in document["tables"].items():
        configured = PurePosixPath(paths[TABLE_GROUPS[table]])
        if ".." in configured.parts:
            raise ValueError("Invalid authorization database path")
        relative = Path(*configured.relative_to(PurePosixPath("/")).parts)
        if not relative.is_relative_to(Path("var/lib/ohana-agent")):
            raise ValueError("Authorization database outside Agent state directory")
        target = destination_root / relative
        if relative not in staged:
            copy = payload.parent / f"authorizations-{len(staged)}.db"
            with (
                closing(
                    sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)
                ) as source,
                closing(sqlite3.connect(copy)) as destination,
            ):
                source.backup(destination)
            staged[relative] = copy
        with closing(sqlite3.connect(staged[relative])) as connection, connection:
            columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
            if (
                not isinstance(content, dict)
                or not columns
                or content.get("columns") != columns
                or not isinstance(content.get("rows"), list)
                or any(
                    not isinstance(row, list) or len(row) != len(columns) for row in content["rows"]
                )
            ):
                raise ValueError(f"Invalid authorization table: {table}")
            connection.execute(f'DELETE FROM "{table}"')
            placeholders = ",".join("?" for _ in columns)
            connection.executemany(
                f'INSERT INTO "{table}" VALUES ({placeholders})', content["rows"]
            )
    return [(source, relative) for relative, source in staged.items()]
