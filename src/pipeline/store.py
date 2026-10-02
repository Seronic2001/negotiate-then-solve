"""Central store (proposal L1 and "State and memory"): requests, constraint
records, timetable versions, the concession ledger and an audit log, in
SQLite (``:memory:`` for tests and runs, a file for the portal).

Justifications and raw request text stay here with restricted access; what
leaves the store for explanations is the constraint, never the reason.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime

from core.schemas import (
    ConcessionEntry,
    Constraint,
    Placement,
    Request,
    RequestStatus,
    TimetableVersion,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, body TEXT NOT NULL, status TEXT NOT NULL,
                                     dedupe_key TEXT, thread_id TEXT);
CREATE TABLE IF NOT EXISTS constraints (id TEXT PRIMARY KEY, body TEXT NOT NULL, active INTEGER NOT NULL,
                                        request_id TEXT);
CREATE TABLE IF NOT EXISTS versions (version INTEGER PRIMARY KEY, body TEXT NOT NULL, parent INTEGER,
                                     approved_by TEXT, published INTEGER NOT NULL DEFAULT 0, case_id TEXT,
                                     created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ledger (n INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (n INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, at TEXT NOT NULL,
                                   kind TEXT NOT NULL, body TEXT NOT NULL);
"""


class _Rows(list):
    """A query's rows, already fetched; read like a cursor."""

    def fetchone(self):
        return self[0] if self else None

    def fetchall(self) -> list:
        return list(self)


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        self._lock = threading.Lock()

    def _exec(self, sql: str, args: tuple = ()) -> _Rows:
        # rows are read under the lock: the connection is shared, and another thread's
        # statement or commit can reset a cursor that is still being read
        with self._lock:
            rows = _Rows(self.db.execute(sql, args).fetchall())
            self.db.commit()
            return rows

    # -- requests ----------------------------------------------------------------

    def add_request(self, r: Request, dedupe_key: str | None = None) -> bool:
        """False if an identical request (same key) is already stored."""
        if dedupe_key and self._exec("SELECT 1 FROM requests WHERE dedupe_key=?", (dedupe_key,)).fetchone():
            return False
        self._exec("INSERT INTO requests VALUES (?,?,?,?,?)",
                   (r.id, r.model_dump_json(), r.status.value, dedupe_key, r.thread_id))
        return True

    def save_request(self, r: Request) -> None:
        self._exec("UPDATE requests SET body=?, status=? WHERE id=?", (r.model_dump_json(), r.status.value, r.id))

    def request(self, rid: str) -> Request | None:
        row = self._exec("SELECT body FROM requests WHERE id=?", (rid,)).fetchone()
        return Request.model_validate_json(row[0]) if row else None

    def requests(self, status: RequestStatus | None = None) -> list[Request]:
        rows = (self._exec("SELECT body FROM requests WHERE status=?", (status.value,)) if status
                else self._exec("SELECT body FROM requests"))
        return [Request.model_validate_json(b) for (b,) in rows.fetchall()]

    def next_request_id(self) -> str:
        (n,) = self._exec("SELECT COUNT(*) FROM requests").fetchone()
        return f"R-{n + 1:05d}"

    # -- constraints ---------------------------------------------------------------

    def add_constraints(self, cons: list[Constraint], request_id: str | None = None, active: bool = True) -> None:
        for c in cons:
            self._exec("INSERT OR REPLACE INTO constraints VALUES (?,?,?,?)",
                       (c.id, c.model_dump_json(), int(active), request_id))

    def set_active(self, cid: str, active: bool) -> None:
        self._exec("UPDATE constraints SET active=? WHERE id=?", (int(active), cid))

    def constraints(self, active_only: bool = True) -> list[Constraint]:
        sql = "SELECT body FROM constraints" + (" WHERE active=1" if active_only else "")
        return [Constraint.model_validate_json(b) for (b,) in self._exec(sql).fetchall()]

    # -- timetable versions ----------------------------------------------------------

    def propose_version(self, assignment: dict[str, Placement], case_id: str,
                        week: int | None = None) -> TimetableVersion:
        cur = self.current_version(week) or self.current_version()
        (n,) = self._exec("SELECT COALESCE(MAX(version), 0) FROM versions").fetchone()
        v = TimetableVersion(version=n + 1, assignment=assignment, parent=cur.version if cur else None, week=week)
        self._exec("INSERT INTO versions VALUES (?,?,?,?,?,?,?)",
                   (v.version, v.model_dump_json(), v.parent, None, 0, case_id, datetime.now().isoformat()))
        return v

    def publish_version(self, version: int, approved_by: str) -> TimetableVersion:
        row = self._exec("SELECT body FROM versions WHERE version=?", (version,)).fetchone()
        if row is None:
            raise KeyError(version)
        v = TimetableVersion.model_validate_json(row[0]).model_copy(update={"approved_by": approved_by})
        self._exec("UPDATE versions SET body=?, approved_by=?, published=1 WHERE version=?",
                   (v.model_dump_json(), approved_by, version))
        return v

    def current_version(self, week: int | None = None) -> TimetableVersion | None:
        """Latest published semester timetable, or for ``week`` the latest
        published repair of that week (None if the week was never repaired)."""
        for (body,) in self._exec("SELECT body FROM versions WHERE published=1 ORDER BY version DESC").fetchall():
            v = TimetableVersion.model_validate_json(body)
            if v.week == week:
                return v
        return None

    def version(self, version: int) -> TimetableVersion | None:
        row = self._exec("SELECT body FROM versions WHERE version=?", (version,)).fetchone()
        return TimetableVersion.model_validate_json(row[0]) if row else None

    def rollback(self, to_version: int, approved_by: str) -> TimetableVersion:
        """Publish a copy of an earlier version as the newest one."""
        old = self.version(to_version)
        if old is None:
            raise KeyError(to_version)
        v = self.propose_version(old.assignment, case_id=f"rollback-{to_version}", week=old.week)
        return self.publish_version(v.version, approved_by)

    # -- ledger and audit log ----------------------------------------------------------

    def record_concession(self, e: ConcessionEntry) -> None:
        self._exec("INSERT INTO ledger (body) VALUES (?)", (e.model_dump_json(),))

    def ledger(self) -> list[ConcessionEntry]:
        return [ConcessionEntry.model_validate_json(b) for (b,) in
                self._exec("SELECT body FROM ledger ORDER BY n").fetchall()]

    def log(self, case_id: str | None, kind: str, **body) -> None:
        self._exec("INSERT INTO events (case_id, at, kind, body) VALUES (?,?,?,?)",
                   (case_id, datetime.now().isoformat(), kind, json.dumps(body, default=str)))

    def events(self, case_id: str | None = None, kind: str | None = None, after: int = 0,
               limit: int | None = None) -> list[dict]:
        sql, args = "SELECT n, case_id, at, kind, body FROM events WHERE n > ?", [after]
        if case_id:
            sql += " AND case_id=?"
            args.append(case_id)
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        rows = self._exec(sql + " ORDER BY n" + (f" LIMIT {int(limit)}" if limit else ""), tuple(args)).fetchall()
        return [{"n": n, "case": c, "at": a, "kind": k, **json.loads(b)} for n, c, a, k, b in rows]

    def versions(self) -> list[dict]:
        rows = self._exec("SELECT version, parent, approved_by, published, case_id, created_at, body "
                          "FROM versions ORDER BY version").fetchall()
        return [{"version": v, "parent": p, "approved_by": a, "published": bool(pub), "case": c,
                 "created_at": t, "week": json.loads(b).get("week")} for v, p, a, pub, c, t, b in rows]
