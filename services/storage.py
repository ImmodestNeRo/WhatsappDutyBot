"""
Thread-safe JSON storage with atomic writes, fsync, and default-merging.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from typing import Any, Callable

from .utils import get_logger

logger = get_logger("StorageService")


class SafeJSONStorage:
    """Persistent JSON storage with locking, atomic writes and fsync."""

    def __init__(self, filepath: str, default_structure: dict[str, Any]) -> None:
        self.filepath = filepath
        self.backup_path = filepath + ".bak"
        self.default_structure = default_structure
        self._lock = threading.Lock()
        self._ensure_file()

    # ── Public API ─────────────────────────────────────────

    def read(self) -> dict[str, Any]:
        """Read the file from disk, merging in any missing default keys."""
        with self._lock:
            return self._read_and_merge()

    def write(self, data: dict[str, Any]) -> None:
        """Overwrite the file with *data*."""
        with self._lock:
            self._write_atomic(data)

    def update(self, mutator: Callable[[dict[str, Any]], None]) -> None:
        """Read → mutate in-place → write, all under the lock."""
        with self._lock:
            data = self._read_and_merge()
            mutator(data)
            self._write_atomic(data)

    # ── Internals ──────────────────────────────────────────

    def _ensure_file(self) -> None:
        """Create the file with defaults if it doesn't exist or is broken."""
        with self._lock:
            if not os.path.exists(self.filepath):
                logger.info("Creating %s with defaults.", self.filepath)
                self._write_atomic(self.default_structure)
            else:
                # Validate existing file — recover from backup if corrupted
                try:
                    self._read_raw()
                except (json.JSONDecodeError, IOError, OSError):
                    logger.error(
                        "File %s is corrupted at startup — recovering.", self.filepath
                    )
                    self._load_or_recover()

    def _read_raw(self) -> dict[str, Any]:
        """Read and parse the file. Must be called under the lock."""
        with open(self.filepath, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def _load_or_recover(self) -> dict[str, Any]:
        """Read main file; on corruption restore from ``.bak``, else defaults.

        The recovered data is always persisted back to the main file so the
        corrupted state doesn't linger on disk. Must be called under the lock.
        """
        try:
            return self._read_raw()
        except (json.JSONDecodeError, IOError, OSError) as exc:
            logger.error(
                "File %s unreadable (%s) — attempting backup restore.",
                self.filepath, exc,
            )

        if os.path.exists(self.backup_path):
            try:
                with open(self.backup_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                logger.warning("Restored state from backup %s.", self.backup_path)
                self._write_atomic(data)
                return data
            except (json.JSONDecodeError, IOError, OSError) as exc:
                logger.error("Backup %s also unreadable: %s", self.backup_path, exc)

        logger.error("No valid backup — resetting %s to defaults.", self.filepath)
        data = dict(self.default_structure)
        self._write_atomic(data)
        return data

    def _read_and_merge(self) -> dict[str, Any]:
        """Read file and fill in any keys missing from *default_structure*.

        This solves the problem where adding a new field to the code
        (e.g. ``group_jid``) would not appear in files created earlier.
        """
        data = self._load_or_recover()

        changed = False
        for key, default_val in self.default_structure.items():
            if key not in data:
                data[key] = default_val
                changed = True

        if changed:
            self._write_atomic(data)

        return data

    def _write_atomic(self, data: dict[str, Any]) -> None:
        """Write *data* to a temp file, fsync, then atomically rename.

        Before overwriting, the current (validated) file is copied to
        ``.bak`` so a single corruption can always be rolled back.
        """
        tmp_path = self.filepath + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
                fh.flush()
                os.fsync(fh.fileno())
            # Preserve the previous good version as a backup — but only if the
            # current file is itself valid, so we never overwrite a good backup
            # with corrupted data.
            if os.path.exists(self.filepath):
                try:
                    with open(self.filepath, "r", encoding="utf-8") as fh:
                        json.load(fh)
                    shutil.copy2(self.filepath, self.backup_path)
                except (json.JSONDecodeError, IOError, OSError) as exc:
                    logger.warning(
                        "Skipped backup refresh (current file unreadable): %s", exc
                    )
            os.replace(tmp_path, self.filepath)
        except Exception as exc:
            logger.error("Atomic write failed for %s: %s", self.filepath, exc)
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
