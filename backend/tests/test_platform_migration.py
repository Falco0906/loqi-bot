"""Tests for safe, configured migration diagnostics."""

from services.platform import migration


def test_manual_migration_instructions_use_configured_supabase_url(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project-from-api.supabase.co")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    instructions = migration._manual_migration_instructions()

    assert "db.project-from-api.supabase.co" in instructions
    assert "dashboard/project/project-from-api/sql/new" in instructions
    assert "llckvmpwmovhchfpjnsa" not in instructions


def test_manual_migration_instructions_fall_back_to_database_url(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres:secret@db.project-from-database.supabase.co:5432/postgres",
    )

    instructions = migration._manual_migration_instructions()

    assert "db.project-from-database.supabase.co" in instructions
    assert "dashboard/project/project-from-database/sql/new" in instructions
    assert "secret" not in instructions


def test_manual_migration_instructions_use_safe_placeholder_without_project_config(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    instructions = migration._manual_migration_instructions()

    assert "db.<project-ref>.supabase.co" in instructions
    assert "dashboard/project/<project-ref>/sql/new" in instructions


def test_apply_migrations_logs_configured_project_instructions(monkeypatch):
    messages: list[str] = []
    monkeypatch.setenv("SUPABASE_URL", "https://configured-project.supabase.co")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(migration, "_check_table_exists", lambda: False)
    monkeypatch.setattr(migration, "_log", messages.append)

    assert migration.apply_migrations() is False

    assert "dashboard/project/configured-project/sql/new" in messages[-1]
