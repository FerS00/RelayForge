from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from relayforge.db.session import create_db_engine, run_migrations


def test_migration_schema_and_sqlite_pragmas(tmp_path: Path) -> None:
    path = tmp_path / "empty.db"
    run_migrations(path)
    engine = create_db_engine(path)
    assert set(inspect(engine).get_table_names()) == {
        "alembic_version",
        "artifacts",
        "attachments",
        "chat_turns",
        "chat_actions",
        "conversations",
        "messages",
        "events",
        "jobs",
        "job_steps",
        "repositories",
        "pairing_codes",
        "auth_sessions",
        "findings",
        "approvals",
        "approval_grants",
        "agent_health",
        "previews",
        "desktop_targets",
    }
    assert {column["name"] for column in inspect(engine).get_columns("jobs")} >= {"retry_at", "retry_count"}
    with engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        assert connection.scalar(text("PRAGMA journal_mode")) == "wal"
        assert connection.scalar(text("PRAGMA busy_timeout")) == 5000
    config = Config()
    config.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parents[2] / "src/relayforge/db/migrations"),
    )
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path.as_posix()}")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
    config.attributes.pop("connection", None)
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()


def test_upgrade_and_downgrade_preserve_phase1_rows(tmp_path: Path) -> None:
    path = tmp_path / "upgrade.db"
    run_migrations(path)
    config = Config()
    config.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parents[2] / "src/relayforge/db/migrations"),
    )
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path.as_posix()}")
    engine = create_db_engine(path)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0001_initial")
    config.attributes.pop("connection", None)
    with engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO conversations
                (id, title, workspace_dir, orchestrator, session_id, session_established, created_at,
                 updated_at)
                VALUES ('conversation-1', 'Stored', '/workspace', 'claude', 'session-1', 0, 't1', 't1')
            """)
        )
        connection.execute(
            text("""
                INSERT INTO messages
                (id, conversation_id, role, content, step_id, status, idempotency_key, ts)
                VALUES ('message-1', 'conversation-1', 'user', 'hello', 'step-1', 'complete', NULL, 't1')
            """)
        )
        connection.execute(
            text("""
                INSERT INTO events
                (conversation_id, seq, ts, type, actor, step_id, payload_json)
                VALUES ('conversation-1', 1, 't1', 'legacy.event', 'core', NULL, '{}')
            """)
        )
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    config.attributes.pop("connection", None)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT content FROM messages WHERE id = 'message-1'")) == "hello"
        assert (
            connection.scalar(text("SELECT type FROM events WHERE conversation_id = 'conversation-1'"))
            == "legacy.event"
        )
        assert (
            connection.scalar(text("SELECT job_id FROM events WHERE conversation_id = 'conversation-1'"))
            is None
        )
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0001_initial")
    config.attributes.pop("connection", None)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT content FROM messages WHERE id = 'message-1'")) == "hello"
        assert "job_id" not in {column["name"] for column in inspect(connection).get_columns("events")}
    engine.dispose()


def test_phase3_downgrade_preserves_phase2_jobs(tmp_path: Path) -> None:
    path = tmp_path / "phase3.db"
    run_migrations(path)
    engine = create_db_engine(path)
    with engine.begin() as connection:
        connection.execute(
            text("""
                INSERT INTO conversations
                (id, title, workspace_dir, orchestrator, session_id, session_established, created_at,
                 updated_at)
                VALUES ('c3', 'Existing', '/workspace', 'claude', 's3', 0, 't1', 't1')
            """)
        )
        connection.execute(
            text("""
            INSERT INTO jobs
            (id, number, title, request_text, workflow, status, conversation_id, approval_kind, iteration,
             max_iterations, base_sha, branch, worktree_path, orchestrator_session_id, created_at, updated_at,
             finished_at, version, error_code, error_message, idempotency_key)
            VALUES ('j3', 3, 'Existing', 'Request', 'plan', 'COMPLETED', 'c3', NULL, 1, 3, NULL, NULL,
                    NULL, 's3', 't1', 't1', 't1', 3, NULL, NULL, 'key3')
        """)
        )
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[2] / "src/relayforge/db/migrations")
    )
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path.as_posix()}")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0002_jobs")
    config.attributes.pop("connection", None)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT title FROM jobs WHERE id = 'j3'")) == "Existing"
        assert "repositories" not in inspect(connection).get_table_names()
        assert "repository_id" not in {column["name"] for column in inspect(connection).get_columns("jobs")}
    engine.dispose()


def test_chat_migration_preserves_job_children_and_event_sequences(app):
    import json

    from sqlalchemy import select

    from relayforge.db.models import Approval, ApprovalGrant, Artifact, Finding, JobStep

    job, _ = app.state.jobs.create_job("Stored", "Request", "migration-fixture")
    with app.state.jobs.sessions.begin() as session:
        step = session.scalar(select(JobStep).where(JobStep.job_id == job["id"]))
        approval = Approval(
            id="a-preserve",
            job_id=job["id"],
            operation_json="{}",
            operation_hash="a" * 64,
            diff_hash="b" * 64,
            idempotency_key="approval-preserve",
        )
        session.add(approval)
        session.flush()
        session.add_all(
            [
                ApprovalGrant(
                    id="grant-preserve", approval_id=approval.id, job_id=job["id"], matcher_json="{}"
                ),
                Artifact(
                    id="artifact-preserve",
                    job_id=job["id"],
                    step_id=step.id,
                    kind="report",
                    path="fixture.txt",
                    sha256="a" * 64,
                    size=1,
                ),
                Finding(
                    id="finding-preserve",
                    job_id=job["id"],
                    audit_step_id=step.id,
                    audit_no=1,
                    external_id="f1",
                    severity="Leve",
                    file="fixture.txt",
                    title="Stored",
                    evidence="Existing",
                    recommendation="Preserve",
                ),
            ]
        )
    tables = ("job_steps", "events", "artifacts", "findings", "approvals", "approval_grants")

    def capture():
        with app.state.engine.connect() as connection:
            return {
                table: sorted(
                    json.dumps(dict(row), sort_keys=True)
                    for row in connection.exec_driver_sql("SELECT * FROM " + table).mappings()
                )
                for table in tables
            }

    before = capture()
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[2] / "src/relayforge/db/migrations")
    )
    config.set_main_option("sqlalchemy.url", f"sqlite:///{app.state.db_path.as_posix()}")
    for operation, revision in ((command.downgrade, "0010_attachments"), (command.upgrade, "head")):
        with app.state.engine.begin() as connection:
            config.attributes["connection"] = connection
            operation(config, revision)
        assert capture() == before
    with app.state.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert (
            connection.exec_driver_sql(
                "SELECT next_event_seq FROM conversations WHERE id=?", (job["conversation_id"],)
            ).scalar()
            == 2
        )


def test_chat_downgrade_refuses_shared_jobs_before_changing_tables(app):
    import pytest

    first, _ = app.state.jobs.create_job("One", "Request", "downgrade-one")
    app.state.jobs.create_job("Two", "Request", "downgrade-two", conversation_id=first["conversation_id"])
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[2] / "src/relayforge/db/migrations")
    )
    with pytest.raises(RuntimeError, match="several Jobs"), app.state.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0010_attachments")
    assert "chat_actions" in inspect(app.state.engine).get_table_names()
    assert len(app.state.jobs.list_jobs()) == 2


def test_preview_migration_downgrade_preserves_existing_conversation_and_job_rows(app):
    from sqlalchemy import text

    job, _ = app.state.jobs.create_job("Migration row", "Keep this job", "preview-migration")
    with app.state.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO previews (id, conversation_id, root_path, kind, argv_json, status, "
                "last_access_at, created_at, version) VALUES (:id, :cid, :root, :kind, :argv, :status, "
                ":access, :created, :version)"
            ),
            {
                "id": "preview-migration-row",
                "cid": job["conversation_id"],
                "root": "/workspace/site",
                "kind": "static",
                "argv": "[]",
                "status": "running",
                "access": "t1",
                "created": "t1",
                "version": 0,
            },
        )
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[2] / "src/relayforge/db/migrations")
    )
    config.set_main_option("sqlalchemy.url", f"sqlite:///{app.state.db_path.as_posix()}")
    with app.state.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0011_chat_execution")
    config.attributes.pop("connection", None)
    assert "previews" not in inspect(app.state.engine).get_table_names()
    with app.state.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT id FROM jobs WHERE id=:id"), {"id": job["id"]}).scalar()
            == job["id"]
        )
        assert (
            connection.execute(
                text("SELECT id FROM conversations WHERE id=:id"), {"id": job["conversation_id"]}
            ).scalar()
            == job["conversation_id"]
        )
    with app.state.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    config.attributes.pop("connection", None)
    assert "previews" in inspect(app.state.engine).get_table_names()


def test_settings_migration_round_trip_preserves_rows_with_defaults(app):
    from sqlalchemy import text

    from relayforge.core.conversation_settings import DEFAULT_TOOLS_JSON, load_tools

    conversation = app.state.chat.create_conversation()
    job, _ = app.state.jobs.create_job("Settings row", "Keep this job", "settings-migration")
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[2] / "src/relayforge/db/migrations")
    )
    config.set_main_option("sqlalchemy.url", f"sqlite:///{app.state.db_path.as_posix()}")
    with app.state.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0012_previews")
    config.attributes.pop("connection", None)
    columns = {column["name"] for column in inspect(app.state.engine).get_columns("conversations")}
    assert {"effort", "tools_json", "settings_version"}.isdisjoint(columns)
    with app.state.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    config.attributes.pop("connection", None)
    with app.state.engine.connect() as connection:
        row = connection.execute(
            text("SELECT effort, tools_json, settings_version FROM conversations WHERE id=:id"),
            {"id": conversation["id"]},
        ).one()
        assert (row[0], row[2]) == ("", 0)
        assert load_tools(row[1]) == load_tools(DEFAULT_TOOLS_JSON)
        assert connection.execute(text("SELECT id FROM jobs WHERE id=:id"), {"id": job["id"]}).scalar()
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").first() is None
