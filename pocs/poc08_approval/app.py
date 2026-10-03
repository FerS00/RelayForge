"""API local de aprobaciones persistentes, idempotentes y con efectos trazables."""

from __future__ import annotations

import argparse
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Header, HTTPException


def create_app(db_path: Path, effects_dir: Path) -> FastAPI:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    effects_dir.mkdir(parents=True, exist_ok=True)

    def connect() -> sqlite3.Connection:
        connection = sqlite3.connect(db_path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, status TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS approvals(
                id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), operation TEXT NOT NULL,
                status TEXT NOT NULL, scope TEXT, decided_at TEXT, idempotency_key TEXT, decided_via TEXT
            );
            CREATE TABLE IF NOT EXISTS grants(job_id TEXT NOT NULL, operation TEXT NOT NULL,
                PRIMARY KEY(job_id, operation));
            CREATE TABLE IF NOT EXISTS effects(job_id TEXT NOT NULL, operation TEXT NOT NULL,
                executed_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS permission_requests(
                id TEXT PRIMARY KEY, tool_name TEXT NOT NULL, input_json TEXT NOT NULL,
                status TEXT NOT NULL, decision TEXT
            );
        """)

    app = FastAPI()

    def row_dict(row: sqlite3.Row | None) -> dict | None:
        return dict(row) if row is not None else None

    def execute_effect(db: sqlite3.Connection, job_id: str, operation: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        db.execute("INSERT INTO effects(job_id, operation, executed_at) VALUES (?, ?, ?)",
                   (job_id, operation, now))
        index = db.execute("SELECT COUNT(*) FROM effects WHERE job_id=? AND operation=?",
                           (job_id, operation)).fetchone()[0]
        name = f"{job_id}-{operation}-{index}.txt".replace("/", "_").replace("\\", "_")
        target = effects_dir / name
        if not target.exists():
            target.write_text(f"job={job_id}\noperation={operation}\n", encoding="utf-8", newline="\n")

    @app.post("/jobs")
    def create_job(payload: dict) -> dict:
        operation = payload.get("operation")
        if not isinstance(operation, str) or not operation:
            raise HTTPException(422, "operation is required")
        job_id, approval_id = str(uuid.uuid4()), str(uuid.uuid4())
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO jobs(id,status,version) VALUES(?, 'WAITING_APPROVAL', 1)", (job_id,))
            db.execute("INSERT INTO approvals(id,job_id,operation,status) VALUES(?,?,?,'pending')",
                       (approval_id, job_id, operation))
            db.commit()
        return {"id": job_id, "status": "WAITING_APPROVAL", "approval_id": approval_id}

    @app.post("/jobs/{job_id}/request")
    def request_operation(job_id: str, payload: dict) -> dict:
        operation = payload.get("operation")
        if not isinstance(operation, str) or not operation:
            raise HTTPException(422, "operation is required")
        approval_id = str(uuid.uuid4())
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone() is None:
                db.rollback()
                raise HTTPException(404, "Job not found")
            granted = db.execute("SELECT 1 FROM grants WHERE job_id=? AND operation=?",
                                 (job_id, operation)).fetchone() is not None
            status = "approved" if granted else "pending"
            db.execute("INSERT INTO approvals(id,job_id,operation,status,scope,decided_at,decided_via) "
                       "VALUES(?,?,?,?,?,?,?)", (approval_id, job_id, operation, status,
                        "job" if granted else None, datetime.now(timezone.utc).isoformat() if granted else None,
                        "grant" if granted else None))
            if granted:
                execute_effect(db, job_id, operation)
                db.execute("UPDATE jobs SET status='COMPLETED', version=version+1 WHERE id=?", (job_id,))
            db.commit()
        return {"approval_id": approval_id, "status": status,
                "decided_via": "grant" if granted else None}

    @app.get("/approvals")
    def list_approvals(status: str = "pending") -> list[dict]:
        with connect() as db:
            rows = db.execute("SELECT * FROM approvals WHERE status=? ORDER BY rowid", (status,)).fetchall()
        return [dict(row) for row in rows]

    @app.post("/approvals/{approval_id}/decision")
    def decide(approval_id: str, payload: dict, idempotency_key: str | None = Header(
            default=None, alias="Idempotency-Key")) -> dict:
        if not idempotency_key:
            raise HTTPException(422, "Idempotency-Key is required")
        decision, scope = payload.get("decision"), payload.get("scope")
        if decision not in {"approve", "reject"} or scope not in {"once", "job"}:
            raise HTTPException(422, "decision/scope invalid")
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            approval = db.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
            if approval is None:
                db.rollback()
                raise HTTPException(404, "Approval not found")
            if approval["status"] != "pending":
                if approval["idempotency_key"] == idempotency_key:
                    db.commit()
                    return {"approval_id": approval_id, "status": approval["status"],
                            "job_status": "COMPLETED" if approval["status"] == "approved" else "FAILED",
                            "effect_count": db.execute("SELECT COUNT(*) FROM effects WHERE job_id=? AND operation=?",
                                (approval["job_id"], approval["operation"])).fetchone()[0]}
                db.rollback()
                raise HTTPException(409, "Approval already decided")
            now = datetime.now(timezone.utc).isoformat()
            status = "approved" if decision == "approve" else "rejected"
            db.execute("UPDATE approvals SET status=?,scope=?,decided_at=?,idempotency_key=?,decided_via='user' "
                       "WHERE id=?", (status, scope, now, idempotency_key, approval_id))
            job_status = "COMPLETED" if decision == "approve" else "FAILED"
            if decision == "approve":
                execute_effect(db, approval["job_id"], approval["operation"])
                if scope == "job":
                    db.execute("INSERT OR IGNORE INTO grants(job_id,operation) VALUES(?,?)",
                               (approval["job_id"], approval["operation"]))
            db.execute("UPDATE jobs SET status=?,version=version+1 WHERE id=?",
                       (job_status, approval["job_id"]))
            db.commit()
            count = db.execute("SELECT COUNT(*) FROM effects WHERE job_id=? AND operation=?",
                               (approval["job_id"], approval["operation"])).fetchone()[0]
        return {"approval_id": approval_id, "status": status, "job_status": job_status, "effect_count": count}

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        with connect() as db:
            job = row_dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
        if job is None:
            raise HTTPException(404, "Job not found")
        return job

    @app.get("/effects")
    def get_effects() -> list[dict]:
        with connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM effects ORDER BY executed_at")]

    @app.post("/permission")
    def create_permission(payload: dict) -> dict:
        request_id = str(uuid.uuid4())
        tool_name = str(payload.get("tool_name", ""))
        input_value = payload.get("input", {})
        with connect() as db:
            db.execute("INSERT INTO permission_requests(id,tool_name,input_json,status) VALUES(?,?,?,'pending')",
                       (request_id, tool_name, json.dumps(input_value, ensure_ascii=False)))
        return {"id": request_id, "status": "pending", "tool_name": tool_name, "input": input_value}

    @app.get("/permission")
    def list_permissions(status: str = "pending") -> list[dict]:
        with connect() as db:
            rows = db.execute("SELECT * FROM permission_requests WHERE status=? ORDER BY rowid",
                              (status,)).fetchall()
        return [{"id": row["id"], "tool_name": row["tool_name"], "input": json.loads(row["input_json"]),
                 "status": row["status"]} for row in rows]

    @app.get("/permission/{request_id}")
    def get_permission(request_id: str) -> dict:
        with connect() as db:
            row = db.execute("SELECT * FROM permission_requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Permission request not found")
        return {"id": row["id"], "status": row["status"], "decision": row["decision"],
                "tool_name": row["tool_name"], "input": json.loads(row["input_json"])}

    @app.post("/permission/{request_id}/decision")
    def decide_permission(request_id: str, payload: dict) -> dict:
        decision = payload.get("decision")
        if decision not in {"allow", "deny"}:
            raise HTTPException(422, "decision must be allow or deny")
        with connect() as db:
            changed = db.execute("UPDATE permission_requests SET status='decided',decision=? "
                                 "WHERE id=? AND status='pending'", (decision, request_id)).rowcount
            if not changed and db.execute("SELECT 1 FROM permission_requests WHERE id=?",
                                          (request_id,)).fetchone() is None:
                raise HTTPException(404, "Permission request not found")
        return {"id": request_id, "decision": decision}

    return app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--effects", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8793)
    args = parser.parse_args()
    uvicorn.run(create_app(args.db, args.effects), host="127.0.0.1", port=args.port, log_config=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
