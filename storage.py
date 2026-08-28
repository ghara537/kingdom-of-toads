"""Kingdom of Toads — durable tables.

One JSON file per table, written through after every state transition. The
in-memory table is always the working copy; disk is a backup that only gets
read at startup.

Writes are atomic (temp file plus rename) so a process killed mid-write leaves
the previous good file intact rather than a truncated one.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import config


class TableStorage:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path if path is not None else config.DATA_DIR)
        self.enabled = True
        try:
            self.path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # read-only filesystem: run without persistence
            self.enabled = False
            self.error = str(exc)

    def file_for(self, code: str) -> Path:
        return self.path / f"{code}.json"

    def save(self, data: dict[str, Any]) -> None:
        if not self.enabled:
            return
        target = self.file_for(data["code"])
        handle = tempfile.NamedTemporaryFile(
            "w", dir=self.path, prefix=".tmp-", suffix=".json",
            delete=False, encoding="utf-8",
        )
        try:
            with handle:
                json.dump(data, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(handle.name, target)
        except Exception:
            Path(handle.name).unlink(missing_ok=True)
            raise

    def delete(self, code: str) -> None:
        if self.enabled:
            self.file_for(code).unlink(missing_ok=True)

    def load_all(self) -> list[dict[str, Any]]:
        """Every saved table. Unreadable files are skipped, never fatal."""
        if not self.enabled:
            return []
        loaded = []
        for file in sorted(self.path.glob("*.json")):
            try:
                with file.open(encoding="utf-8") as handle:
                    loaded.append(json.load(handle))
            except (json.JSONDecodeError, OSError, KeyError):
                continue
        return loaded
