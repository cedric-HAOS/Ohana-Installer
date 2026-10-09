import json
import sqlite3

import pytest

from ohana_installer.restore_authorizations import stage_authorizations


def test_stage_credentials_preserves_jobs_and_live_database(tmp_path):
    payload = tmp_path / "payload"
    export = payload / "etc/ohana-agent/recovery/authorizations.json"
    export.parent.mkdir(parents=True)
    (export.parent.parent / "shikamaru.yaml").write_text(
        json.dumps({"administration": {"jobs": {"database_path": "/var/lib/ohana-agent/jobs.db"}}})
    )
    machine = tmp_path / "machine"
    target = machine / "var/lib/ohana-agent/jobs.db"
    target.parent.mkdir(parents=True)
    with sqlite3.connect(target) as connection:
        connection.executescript(
            "CREATE TABLE distributed_worker_credentials(worker_id TEXT, token_sha256 TEXT);"
            "INSERT INTO distributed_worker_credentials VALUES ('old','old-hash');"
            "CREATE TABLE distributed_jobs(job_id TEXT);"
            "INSERT INTO distributed_jobs VALUES ('live-job');"
        )
    export.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tables": {
                    "distributed_worker_credentials": {
                        "columns": ["worker_id", "token_sha256"],
                        "rows": [["bubule", "worker-hash"]],
                    }
                },
            }
        )
    )
    [(staging, relative)] = stage_authorizations(payload, machine)
    assert relative.as_posix() == "var/lib/ohana-agent/jobs.db"
    with sqlite3.connect(staging) as connection:
        assert connection.execute("SELECT * FROM distributed_worker_credentials").fetchall() == [
            ("bubule", "worker-hash")
        ]
        assert connection.execute("SELECT * FROM distributed_jobs").fetchall() == [("live-job",)]
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT * FROM distributed_worker_credentials").fetchall() == [
            ("old", "old-hash")
        ]


def test_old_backup_without_authorizations_is_compatible(tmp_path):
    assert stage_authorizations(tmp_path / "payload", tmp_path / "machine") == []


def test_rejects_pending_job_import(tmp_path):
    export = tmp_path / "payload/etc/ohana-agent/recovery/authorizations.json"
    export.parent.mkdir(parents=True)
    export.write_text(json.dumps({"schema_version": 1, "tables": {"distributed_jobs": {}}}))
    with pytest.raises(ValueError, match="contract"):
        stage_authorizations(tmp_path / "payload", tmp_path / "machine")
