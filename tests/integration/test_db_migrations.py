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
        "conversations",
        "messages",
        "events",
    }
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
    command.downgrade(config, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()
