"""
WwiseSnap Snapshot Manager
Handles saving, loading, and deleting snapshots from a SQLite database.
DB location: C:\\Users\\jayth\\AppData\\Roaming\\WwiseSnap\\snapshots.db
"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path


# Fixed app-data path for the SQLite database
_DB_DIR = Path("C:/Users/jayth/AppData/Roaming/WwiseSnap")
_DB_PATH = _DB_DIR / "snapshots.db"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    object_name TEXT,
    object_path TEXT,
    object_guid TEXT,
    object_type TEXT,
    timestamp TEXT,
    properties TEXT,
    property_display TEXT,
    rtpc TEXT,
    effects TEXT,
    modifiers TEXT,
    attenuation TEXT
);
"""

_MIGRATE_ADD_MODIFIERS_SQL = """
ALTER TABLE snapshots ADD COLUMN modifiers TEXT;
"""

_MIGRATE_ADD_ATTENUATION_SQL = """
ALTER TABLE snapshots ADD COLUMN attenuation TEXT;
"""


def _dict_row_factory(cursor, row):
    """sqlite3 row factory that returns dicts."""
    fields = [description[0] for description in cursor.description]
    return dict(zip(fields, row))


def _deserialize_snap(row: dict) -> dict:
    """Parse JSON blob columns in a snapshot row into Python objects."""
    list_cols = ("rtpc", "effects", "modifiers")
    dict_cols = ("properties", "property_display", "attenuation")
    for col in dict_cols + list_cols:
        raw = row.get(col)
        if raw is None:
            row[col] = {} if col in dict_cols else []
        else:
            try:
                row[col] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                row[col] = {} if col in dict_cols else []
    return row


class SnapshotManager:
    def __init__(self):
        _DB_DIR.mkdir(parents=True, exist_ok=True)
        self._db_path = str(_DB_PATH)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = _dict_row_factory
        return conn

    def _init_db(self):
        """Create the snapshots table if it doesn't exist, and run migrations."""
        with self._get_conn() as conn:
            conn.execute(_CREATE_TABLE_SQL)
            existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(snapshots)")}
            if "modifiers" not in existing_cols:
                conn.execute(_MIGRATE_ADD_MODIFIERS_SQL)
            if "attenuation" not in existing_cols:
                conn.execute(_MIGRATE_ADD_ATTENUATION_SQL)
            conn.commit()

    # ── Public interface ───────────────────────────────────────────────────

    def get_snapshots(self) -> list[dict]:
        """Return list of all snapshot entries, ordered by timestamp desc."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM snapshots ORDER BY timestamp DESC"
            ).fetchall()
        return [_deserialize_snap(r) for r in rows]

    def get_snapshot_by_id(self, snap_id: str) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM snapshots WHERE id = ?", (snap_id,)
            ).fetchone()
        if row is None:
            return None
        return _deserialize_snap(row)

    def save_snapshot(
        self,
        name: str,
        object_path: str,
        object_name: str,
        object_guid: str,
        object_type: str,
        properties: dict,
        property_display: dict = None,
        modifiers: list = None,
        attenuation: dict = None,
    ) -> dict:
        """Create and persist a new snapshot. Returns the new snapshot dict."""
        snap = {
            "id": str(uuid.uuid4()),
            "name": name,
            "object_path": object_path,
            "object_name": object_name,
            "object_guid": object_guid,
            "object_type": object_type,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "properties": properties,
            "property_display": property_display if property_display is not None else {},
            "rtpc": [],
            "effects": [],
            "modifiers": modifiers if modifiers is not None else [],
            "attenuation": attenuation if attenuation is not None else {},
        }
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO snapshots
                   (id, name, object_name, object_path, object_guid, object_type,
                    timestamp, properties, property_display, rtpc, effects, modifiers,
                    attenuation)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snap["id"],
                    snap["name"],
                    snap["object_name"],
                    snap["object_path"],
                    snap["object_guid"],
                    snap["object_type"],
                    snap["timestamp"],
                    json.dumps(snap["properties"], ensure_ascii=False),
                    json.dumps(snap["property_display"], ensure_ascii=False),
                    json.dumps(snap["rtpc"], ensure_ascii=False),
                    json.dumps(snap["effects"], ensure_ascii=False),
                    json.dumps(snap["modifiers"], ensure_ascii=False),
                    json.dumps(snap["attenuation"], ensure_ascii=False),
                ),
            )
            conn.commit()
        return snap

    def delete_snapshot(self, snap_id: str) -> bool:
        """Remove a snapshot by ID. Returns True if found and removed."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM snapshots WHERE id = ?", (snap_id,)
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_all_snapshots(self) -> int:
        """Remove all snapshots. Returns the number of rows deleted."""
        with self._get_conn() as conn:
            cursor = conn.execute("DELETE FROM snapshots")
            conn.commit()
            return cursor.rowcount

    def rename_snapshot(self, snap_id: str, new_name: str) -> bool:
        """Rename a snapshot by ID."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "UPDATE snapshots SET name = ? WHERE id = ?", (new_name, snap_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def is_loaded(self) -> bool:
        """Always True — DB is always available."""
        return True

    def get_file_display(self) -> str:
        """Return the DB file path string."""
        return self._db_path

    # ── Export / Import ────────────────────────────────────────────────────

    def export_json(self, file_path: str) -> bool:
        """Write all snapshots to a JSON file. Returns True on success."""
        try:
            snaps = self.get_snapshots()
            data = {"snapshots": snaps}
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except OSError:
            return False

    def import_json(self, file_path: str) -> int:
        """
        Load snapshots from a JSON file and merge into DB.
        Skips duplicates by id. Returns number of snapshots imported.
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return 0

        snaps = data.get("snapshots", [])
        imported = 0
        with self._get_conn() as conn:
            for snap in snaps:
                snap_id = snap.get("id")
                if not snap_id:
                    continue
                # Skip if already exists
                existing = conn.execute(
                    "SELECT id FROM snapshots WHERE id = ?", (snap_id,)
                ).fetchone()
                if existing:
                    continue
                conn.execute(
                    """INSERT INTO snapshots
                       (id, name, object_name, object_path, object_guid, object_type,
                        timestamp, properties, property_display, rtpc, effects, modifiers,
                        attenuation)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        snap_id,
                        snap.get("name", "Imported"),
                        snap.get("object_name", ""),
                        snap.get("object_path", ""),
                        snap.get("object_guid", ""),
                        snap.get("object_type", ""),
                        snap.get("timestamp", ""),
                        json.dumps(snap.get("properties", {}), ensure_ascii=False),
                        json.dumps(snap.get("property_display", {}), ensure_ascii=False),
                        json.dumps(snap.get("rtpc", []), ensure_ascii=False),
                        json.dumps(snap.get("effects", []), ensure_ascii=False),
                        json.dumps(snap.get("modifiers", []), ensure_ascii=False),
                        json.dumps(snap.get("attenuation", {}), ensure_ascii=False),
                    ),
                )
                imported += 1
            conn.commit()
        return imported


# Module-level singleton
_manager: SnapshotManager | None = None


def get_manager() -> SnapshotManager:
    global _manager
    if _manager is None:
        _manager = SnapshotManager()
    return _manager
