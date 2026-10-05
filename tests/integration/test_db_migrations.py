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
