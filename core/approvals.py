"""Approval broker: pluggable channels, approver authorisation, timeout -> deny,
once / session / always scopes, and argument-hash binding."""
from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from core.memory.store import init_db

log = logging.getLogger("harness.approvals")


def args_hash(tool: str, args: dict[str, Any]) -> str:
    canon = json.dumps({"tool": tool, "args": args}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode()).hexdigest()


@dataclass
class ApprovalRequest:
    tool: str
    args_hash: str
    rendered: str
    risk_tier: str
    session_id: str | None = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class ApprovalResult:
    approved: bool
    status: str  # approved | denied | timed_out
    approver: str | None = None
    scope: str = "once"
    note: str | None = None


Channel = Callable[[ApprovalRequest], Awaitable[None]]


class ApprovalBroker:
    def __init__(self, db_path=None, timeout: float | None = None,
                 approvers: tuple[str, ...] | None = None) -> None:
        self._db_path = db_path
        self._timeout = timeout
        self._approvers = approvers
        self.channels: list[Channel] = []
        self._pending: dict[str, tuple[ApprovalRequest, asyncio.Future]] = {}

    # -- configuration ---------------------------------------------------
    def add_channel(self, channel: Channel):
        self.channels.append(channel)
        return lambda: self.channels.remove(channel) if channel in self.channels else None

    def _conn(self):
        return init_db(self._db_path)

    def _settings(self):
        from core.settings import settings

        return settings()

    def authorized(self, approver: str) -> bool:
        allowed = self._approvers if self._approvers is not None else self._settings().approvers
        return not allowed or any(fnmatch.fnmatch(approver, pat) for pat in allowed)

    # -- persistence -----------------------------------------------------
    def is_remembered(self, tool: str, digest: str) -> bool:
        conn = self._conn()
        try:
            return conn.execute("SELECT 1 FROM approval_rules WHERE tool = ? AND args_hash = ?",
                                (tool, digest)).fetchone() is not None
        finally:
            conn.close()

    def _remember(self, tool: str, digest: str, approver: str | None) -> None:
        conn = self._conn()
        try:
            conn.execute("INSERT OR IGNORE INTO approval_rules VALUES (?, ?, ?, ?)",
                         (tool, digest, approver, datetime.now(timezone.utc).isoformat()))
            conn.commit()
        finally:
            conn.close()

    def _store(self, req: ApprovalRequest) -> None:
        conn = self._conn()
        try:
            conn.execute(
                """INSERT INTO approvals (id, session_id, tool, args_hash, rendered, risk_tier, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (req.id, req.session_id, req.tool, req.args_hash, req.rendered, req.risk_tier,
                 datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def _finish(self, req_id: str, status: str, approver: str | None, scope: str, note: str | None) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE approvals SET status=?, decided_by=?, scope=?, note=?, decided_at=? WHERE id=?",
                (status, approver, scope, note, datetime.now(timezone.utc).isoformat(), req_id),
            )
            conn.commit()
        finally:
            conn.close()

    # -- request / resolve -------------------------------------------------
    async def request(self, req: ApprovalRequest) -> ApprovalResult:
        self._store(req)
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[req.id] = (req, future)
        for channel in list(self.channels):
            try:
                await channel(req)
            except Exception as error:  # noqa: BLE001
                log.warning("approval channel failed: %s", error)
        timeout = self._timeout if self._timeout is not None else self._settings().approval_timeout
        try:
            result: ApprovalResult = await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            result = ApprovalResult(False, "timed_out", note="No response before the timeout; denied")
        except asyncio.CancelledError:
            self._finish(req.id, "cancelled", None, "once", None)
            raise
        finally:
            self._pending.pop(req.id, None)
        self._finish(req.id, result.status, result.approver, result.scope, result.note)
        if result.approved and result.scope == "always" and req.risk_tier != "R3":
            self._remember(req.tool, req.args_hash, result.approver)
        return result

    def resolve(self, req_id: str, approved: bool, approver: str, scope: str = "once",
                note: str | None = None) -> bool:
        """Resolve a pending approval. Returns False if unknown/unauthorised/already resolved."""
        entry = self._pending.get(req_id)
        if entry is None or not self.authorized(approver):
            return False
        req, future = entry
        if future.done():
            return False
        if scope not in {"once", "session", "always"}:
            scope = "once"
        if req.risk_tier == "R3" and scope != "once":
            scope = "once"
        future.set_result(ApprovalResult(approved, "approved" if approved else "denied",
                                         approver, scope, note))
        return True

    def pending(self) -> list[dict[str, Any]]:
        return [{"id": r.id, "tool": r.tool, "rendered": r.rendered, "risk_tier": r.risk_tier,
                 "session_id": r.session_id, "args_hash": r.args_hash}
                for r, f in self._pending.values() if not f.done()]


_default: ApprovalBroker | None = None


def get_broker() -> ApprovalBroker:
    global _default
    if _default is None:
        _default = ApprovalBroker()
    return _default


def set_broker(broker: ApprovalBroker | None) -> None:
    global _default
    _default = broker
