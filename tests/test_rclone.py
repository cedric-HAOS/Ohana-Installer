from __future__ import annotations

import hashlib
import io
import os
from zipfile import ZipFile

from ohana_installer import rclone


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_ensure_rclone_downloads_verified_architecture(
    tmp_path,
    monkeypatch,
) -> None:
    archive_buffer = io.BytesIO()
    with ZipFile(archive_buffer, "w") as archive:
        archive.writestr("rclone-v1.74.4-linux-arm64/rclone", b"rclone-binary")
    archive_content = archive_buffer.getvalue()
    monkeypatch.setattr(rclone.platform, "machine", lambda: "aarch64")
    monkeypatch.setitem(
        rclone.RCLONE_ASSETS,
        "aarch64",
        ("linux-arm64", hashlib.sha256(archive_content).hexdigest()),
    )
    monkeypatch.setattr(
        rclone,
        "urlopen",
        lambda *args, **kwargs: Response(archive_content),
    )
    monkeypatch.setattr(
        rclone,
        "_installed_version",
        lambda path: rclone.RCLONE_VERSION if path.is_file() else None,
    )
    destination = tmp_path / "rclone"

    assert rclone.ensure_rclone(destination) == rclone.RCLONE_VERSION
    assert destination.read_bytes() == b"rclone-binary"
    if os.name != "nt":
        assert destination.stat().st_mode & 0o777 == 0o755
