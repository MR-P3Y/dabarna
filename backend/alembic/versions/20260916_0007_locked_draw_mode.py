from __future__ import annotations

import hashlib
import json

from alembic import op
import sqlalchemy as sa


revision = "20260916_0007"
down_revision = "20260916_0006"
branch_labels = None
depends_on = None


_EVENT_ENUM_VALUES = (
    "GAME_CREATED",
    "CARDS_PURCHASED",
    "GAME_STARTED",
    "GAME_START_REJECTED",
    "DRAW_MODE_SELECTED",
    "AUTO_DRAW_ARMED",
    "AUTO_DRAW_STARTED",
    "AUTO_DRAW_PAUSED",
    "AUTO_DRAW_RESUMED",
    "AUTO_DRAW_STOPPED",
    "AUTO_DRAW_TAMPER_DETECTED",
    "NUMBER_CALLED",
    "NUMBER_UNDONE",
    "PRIZE_COL",
    "PRIZE_ROW",
    "GAME_ENDED",
    "GAME_LOBBY_CLOSED",
    "ERROR",
)

_OLD_EVENT_ENUM_VALUES = (
    "GAME_CREATED",
    "CARDS_PURCHASED",
    "GAME_STARTED",
    "GAME_START_REJECTED",
    "NUMBER_CALLED",
    "NUMBER_UNDONE",
    "PRIZE_COL",
    "PRIZE_ROW",
    "GAME_ENDED",
    "GAME_LOBBY_CLOSED",
    "ERROR",
)


def _enum_sql(values: tuple[str, ...]) -> str:
    return ",".join(f"'{value}'" for value in values)


def _commitment(sequence: list[int]) -> str:
    canonical = ",".join(str(int(value)) for value in sequence)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def upgrade() -> None:
    op.add_column("games", sa.Column("draw_mode", sa.String(length=16), nullable=True))
    op.add_column("games", sa.Column("draw_interval_seconds", sa.Integer(), nullable=True))
    op.add_column("games", sa.Column("draw_mode_selected_by", sa.BigInteger(), nullable=True))
    op.add_column("games", sa.Column("draw_mode_selected_at", sa.TIMESTAMP(), nullable=True))
    op.add_column("games", sa.Column("draw_mode_locked_at", sa.TIMESTAMP(), nullable=True))
    op.create_index("idx_games_draw_mode", "games", ["draw_mode"], unique=False)

    op.add_column("game_auto_draws", sa.Column("sequence_commitment", sa.String(length=64), nullable=True))

    bind = op.get_bind()

    # Existing non-LOBBY games must remain playable after deployment.
    # Games that have ever used game_auto_draws are treated as AUTO; others as MANUAL.
    bind.execute(sa.text("""
        UPDATE games g
        LEFT JOIN game_auto_draws a ON a.game_id = g.id
        SET
            g.draw_mode = CASE WHEN a.game_id IS NOT NULL THEN 'AUTO' ELSE 'MANUAL' END,
            g.draw_interval_seconds = CASE WHEN a.game_id IS NOT NULL THEN a.interval_seconds ELSE NULL END,
            g.draw_mode_selected_by = g.admin_user_id,
            g.draw_mode_selected_at = COALESCE(g.started_at, g.created_at),
            g.draw_mode_locked_at = COALESCE(g.started_at, g.created_at)
        WHERE g.status <> 'LOBBY'
    """))

    rows = bind.execute(sa.text("SELECT game_id, sequence_json FROM game_auto_draws")).mappings().all()
    for row in rows:
        raw = row["sequence_json"]
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = []
        sequence = [int(value) for value in raw] if isinstance(raw, list) else []
        if sequence:
            bind.execute(
                sa.text("UPDATE game_auto_draws SET sequence_commitment=:commitment WHERE game_id=:game_id"),
                {"commitment": _commitment(sequence), "game_id": int(row["game_id"])},
            )

    if bind.dialect.name != "mysql":
        return

    op.execute(
        f"ALTER TABLE game_events MODIFY COLUMN kind ENUM({_enum_sql(_EVENT_ENUM_VALUES)}) NOT NULL"
    )

    op.execute("DROP TRIGGER IF EXISTS trg_games_draw_mode_guard")
    op.execute("""
        CREATE TRIGGER trg_games_draw_mode_guard
        BEFORE UPDATE ON games
        FOR EACH ROW
        BEGIN
            DECLARE v_auto_count INT DEFAULT 0;

            IF OLD.status = 'LOBBY' AND NEW.status = 'RUNNING' THEN
                IF NEW.draw_mode IS NULL OR NEW.draw_mode NOT IN ('MANUAL', 'AUTO') THEN
                    SIGNAL SQLSTATE '45000'
                        SET MESSAGE_TEXT = 'draw mode must be selected before game start';
                END IF;

                IF NEW.draw_mode = 'AUTO' THEN
                    IF NEW.draw_interval_seconds IS NULL OR NEW.draw_interval_seconds NOT IN (5, 8, 10, 15) THEN
                        SIGNAL SQLSTATE '45000'
                            SET MESSAGE_TEXT = 'valid auto draw interval must be selected before game start';
                    END IF;

                    SELECT COUNT(*) INTO v_auto_count
                    FROM game_auto_draws
                    WHERE game_id = OLD.id
                      AND status = 'ARMED'
                      AND interval_seconds = NEW.draw_interval_seconds
                      AND sequence_commitment IS NOT NULL;

                    IF v_auto_count <> 1 THEN
                        SIGNAL SQLSTATE '45000'
                            SET MESSAGE_TEXT = 'auto draw must be armed before game start';
                    END IF;
                END IF;

                SET NEW.draw_mode_locked_at = UTC_TIMESTAMP();
            END IF;

            IF (OLD.status <> 'LOBBY' OR OLD.draw_mode_locked_at IS NOT NULL) AND (
                NOT (NEW.draw_mode <=> OLD.draw_mode)
                OR NOT (NEW.draw_interval_seconds <=> OLD.draw_interval_seconds)
            ) THEN
                SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'draw mode is permanently locked after game start';
            END IF;
        END
    """)

    op.execute("DROP TRIGGER IF EXISTS trg_games_auto_draw_activate")
    op.execute("""
        CREATE TRIGGER trg_games_auto_draw_activate
        AFTER UPDATE ON games
        FOR EACH ROW
        BEGIN
            IF OLD.status = 'LOBBY' AND NEW.status = 'RUNNING' AND NEW.draw_mode = 'AUTO' THEN
                UPDATE game_auto_draws
                SET
                    status = 'RUNNING',
                    next_draw_at = DATE_ADD(UTC_TIMESTAMP(), INTERVAL interval_seconds SECOND),
                    started_at = UTC_TIMESTAMP(),
                    paused_at = NULL,
                    stopped_at = NULL
                WHERE game_id = NEW.id AND status = 'ARMED';
            END IF;
        END
    """)

    op.execute("DROP TRIGGER IF EXISTS trg_game_called_numbers_auto_insert_guard")
    op.execute("""
        CREATE TRIGGER trg_game_called_numbers_auto_insert_guard
        BEFORE INSERT ON game_called_numbers
        FOR EACH ROW
        BEGIN
            DECLARE v_mode VARCHAR(16) DEFAULT NULL;
            DECLARE v_locked TIMESTAMP DEFAULT NULL;

            SELECT draw_mode, draw_mode_locked_at
            INTO v_mode, v_locked
            FROM games
            WHERE id = NEW.game_id;

            IF v_mode = 'AUTO' AND v_locked IS NOT NULL THEN
                IF COALESCE(@davarna_auto_draw_game_id, 0) <> NEW.game_id THEN
                    SIGNAL SQLSTATE '45000'
                        SET MESSAGE_TEXT = 'manual number insertion is forbidden for locked AUTO games';
                END IF;
            END IF;
        END
    """)

    op.execute("DROP TRIGGER IF EXISTS trg_game_called_numbers_auto_delete_guard")
    op.execute("""
        CREATE TRIGGER trg_game_called_numbers_auto_delete_guard
        BEFORE DELETE ON game_called_numbers
        FOR EACH ROW
        BEGIN
            DECLARE v_mode VARCHAR(16) DEFAULT NULL;
            DECLARE v_locked TIMESTAMP DEFAULT NULL;

            SELECT draw_mode, draw_mode_locked_at
            INTO v_mode, v_locked
            FROM games
            WHERE id = OLD.game_id;

            IF v_mode = 'AUTO' AND v_locked IS NOT NULL THEN
                SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'undo is forbidden for locked AUTO games';
            END IF;
        END
    """)

    op.execute("DROP TRIGGER IF EXISTS trg_game_auto_draw_immutable")
    op.execute("""
        CREATE TRIGGER trg_game_auto_draw_immutable
        BEFORE UPDATE ON game_auto_draws
        FOR EACH ROW
        BEGIN
            DECLARE v_mode VARCHAR(16) DEFAULT NULL;
            DECLARE v_locked TIMESTAMP DEFAULT NULL;

            SELECT draw_mode, draw_mode_locked_at
            INTO v_mode, v_locked
            FROM games
            WHERE id = NEW.game_id;

            IF v_mode = 'AUTO' AND v_locked IS NOT NULL THEN
                IF NOT (NEW.interval_seconds <=> OLD.interval_seconds)
                   OR NOT (NEW.sequence_commitment <=> OLD.sequence_commitment)
                   OR CAST(NEW.sequence_json AS CHAR) <> CAST(OLD.sequence_json AS CHAR) THEN
                    SIGNAL SQLSTATE '45000'
                        SET MESSAGE_TEXT = 'AUTO sequence and interval are immutable after game start';
                END IF;
            END IF;
        END
    """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        op.execute("DROP TRIGGER IF EXISTS trg_game_auto_draw_immutable")
        op.execute("DROP TRIGGER IF EXISTS trg_game_called_numbers_auto_delete_guard")
        op.execute("DROP TRIGGER IF EXISTS trg_game_called_numbers_auto_insert_guard")
        op.execute("DROP TRIGGER IF EXISTS trg_games_auto_draw_activate")
        op.execute("DROP TRIGGER IF EXISTS trg_games_draw_mode_guard")
        op.execute(
            "DELETE FROM game_events WHERE kind IN ("
            "'DRAW_MODE_SELECTED','AUTO_DRAW_ARMED','AUTO_DRAW_STARTED','AUTO_DRAW_PAUSED',"
            "'AUTO_DRAW_RESUMED','AUTO_DRAW_STOPPED','AUTO_DRAW_TAMPER_DETECTED')"
        )
        op.execute(
            f"ALTER TABLE game_events MODIFY COLUMN kind ENUM({_enum_sql(_OLD_EVENT_ENUM_VALUES)}) NOT NULL"
        )

    op.drop_column("game_auto_draws", "sequence_commitment")
    op.drop_index("idx_games_draw_mode", table_name="games")
    op.drop_column("games", "draw_mode_locked_at")
    op.drop_column("games", "draw_mode_selected_at")
    op.drop_column("games", "draw_mode_selected_by")
    op.drop_column("games", "draw_interval_seconds")
    op.drop_column("games", "draw_mode")
