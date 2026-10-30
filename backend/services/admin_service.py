"""Database/service helpers used by the StudyAI Admin API."""


# =============================================================
# BASIC HELPERS
# =============================================================


def iso(value):
    """Convert a datetime value to ISO text for JSON responses."""
    return value.isoformat() if value else None


def _reset_cursor(cursor):
    """Reset/clear a cursor after a failed optional query when supported."""
    try:
        cursor.reset()
    except Exception:
        pass


def _scalar_count(cursor, sql, params=()):
    """Return COUNT()/SUM()-style scalar values from a normal tuple cursor."""
    try:
        cursor.execute(sql, params)
        row = cursor.fetchone()

        if not row:
            return 0

        # Normal MySQL connector cursor -> tuple/list.
        if isinstance(row, (tuple, list)):
            return int(row[0] or 0)

        # Dictionary cursor compatibility.
        if isinstance(row, dict):
            value = row.get("total")
            if value is None:
                value = row.get("completed")
            if value is None:
                value = row.get("total_seconds")
            return int(value or 0)

        return 0

    except Exception:
        _reset_cursor(cursor)
        return 0


def safe_count(cursor, sql, params=()):
    """Run a count query safely and return an integer."""
    return _scalar_count(cursor, sql, params)


# =============================================================
# USER PROGRESS
# =============================================================


def user_progress(cursor, user_id):
    """Calculate a lightweight overall progress percentage."""

    study_minutes = 0
    material_count = 0
    questions_solved = 0
    total_goals = 0
    goals_completed = 0

    # Study time
    try:
        cursor.execute(
            """
            SELECT COALESCE(SUM(duration_seconds), 0)
            FROM study_sessions
            WHERE user_id = %s
              AND finished_at IS NOT NULL
            """,
            (user_id,),
        )
        row = cursor.fetchone()

        if row:
            if isinstance(row, (tuple, list)):
                study_seconds = int(row[0] or 0)
            else:
                study_seconds = int(
                    row.get("total_seconds", 0) or 0
                )
            study_minutes = study_seconds // 60

    except Exception:
        _reset_cursor(cursor)

    # Materials
    try:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM materials
            WHERE user_id = %s
            """,
            (user_id,),
        )
        row = cursor.fetchone()

        if row:
            material_count = int(
                row[0] if isinstance(row, (tuple, list))
                else row.get("total", 0)
                or 0
            )

    except Exception:
        _reset_cursor(cursor)

    # Question activity: use whichever table exists first.
    for table_name in (
        "question_attempts",
        "quiz_attempts",
        "question_history",
    ):
        try:
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM {table_name}
                WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cursor.fetchone()

            if row:
                questions_solved = int(
                    row[0] if isinstance(row, (tuple, list))
                    else row.get("total", 0)
                    or 0
                )
                break

        except Exception:
            _reset_cursor(cursor)
            continue

    # Goals: use whichever table exists first.
    for table_name in (
        "goals",
        "study_goals",
    ):
        try:
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM {table_name}
                WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cursor.fetchone()

            if row:
                total_goals = int(
                    row[0] if isinstance(row, (tuple, list))
                    else row.get("total", 0)
                    or 0
                )

            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM {table_name}
                WHERE user_id = %s
                  AND (
                      status = 'completed'
                      OR completed = 1
                      OR is_completed = 1
                  )
                """,
                (user_id,),
            )
            row = cursor.fetchone()

            if row:
                goals_completed = int(
                    row[0] if isinstance(row, (tuple, list))
                    else row.get("completed", 0)
                    or 0
                )

            break

        except Exception:
            _reset_cursor(cursor)
            continue

    parts = [
        min(study_minutes / 600 * 100, 100),
        min(material_count / 10 * 100, 100),
        min(questions_solved / 50 * 100, 100),
        (
            goals_completed / total_goals * 100
            if total_goals
            else 0
        ),
    ]

    return round(sum(parts) / len(parts))


# =============================================================
# ADMIN TABLE / COLUMN INITIALIZATION
# =============================================================


def ensure_admin_tables(get_db):
    """Create admin support objects and admin password storage if missing."""

    db = get_db()
    cursor = db.cursor()

    try:
        # -----------------------------------------------------
        # Current database name
        # -----------------------------------------------------

        cursor.execute("SELECT DATABASE()")
        database_row = cursor.fetchone()
        database_name = (
            database_row[0]
            if database_row
            else None
        )

        if not database_name:
            raise RuntimeError(
                "Unable to determine the active MySQL database."
            )

        # -----------------------------------------------------
        # Ensure separate admin password column.
        # Client password remains users.password_hash.
        # -----------------------------------------------------

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = 'users'
              AND column_name = 'admin_password_hash'
            """,
            (database_name,),
        )

        column_row = cursor.fetchone()
        column_exists = bool(
            column_row and int(column_row[0] or 0) > 0
        )

        if not column_exists:
            cursor.execute(
                """
                ALTER TABLE users
                ADD COLUMN admin_password_hash VARCHAR(255) NULL
                """
            )

        # -----------------------------------------------------
        # Settings
        # -----------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_settings (
                setting_key VARCHAR(100) PRIMARY KEY,
                setting_value VARCHAR(255) NOT NULL,
                updated_at TIMESTAMP NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )

        # -----------------------------------------------------
        # Activity log
        # -----------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_activity (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                event_type VARCHAR(80) NOT NULL,
                title VARCHAR(255) NOT NULL,
                description TEXT NULL,
                user_id BIGINT NULL,
                user_email VARCHAR(255) NULL,
                created_at TIMESTAMP NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_admin_activity_created(created_at),
                INDEX idx_admin_activity_user(user_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )

        # -----------------------------------------------------
        # Default settings
        # -----------------------------------------------------

        defaults = {
            "registration_enabled": "1",
            "notifications_enabled": "1",
            "ai_enabled": "1",
            "pdf_upload_limit_mb": "25",
        }

        for key, value in defaults.items():
            cursor.execute(
                """
                INSERT INTO admin_settings
                    (setting_key, setting_value)
                VALUES
                    (%s, %s)
                ON DUPLICATE KEY UPDATE
                    setting_key = setting_key
                """,
                (key, value),
            )

        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        cursor.close()
        db.close()


# =============================================================
# ADMIN SETTINGS
# =============================================================


def get_setting(get_db, key, default=None):
    """Read one admin setting."""

    db = get_db()
    cursor = db.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT setting_value
            FROM admin_settings
            WHERE setting_key = %s
            LIMIT 1
            """,
            (key,),
        )

        row = cursor.fetchone()

        return (
            row["setting_value"]
            if row
            else default
        )

    except Exception:
        return default

    finally:
        cursor.close()
        db.close()


def set_setting(get_db, key, value):
    """Create/update one admin setting."""

    db = get_db()
    cursor = db.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO admin_settings
                (setting_key, setting_value)
            VALUES
                (%s, %s)
            ON DUPLICATE KEY UPDATE
                setting_value = VALUES(setting_value)
            """,
            (key, str(value)),
        )

        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        cursor.close()
        db.close()


# =============================================================
# ACTIVITY LOG
# =============================================================


def log_activity(
    get_db,
    event_type,
    title,
    description="",
    user_id=None,
    user_email=None,
):
    """Write one event to the admin activity log."""

    db = get_db()
    cursor = db.cursor()

    try:
        cursor.execute(
            """
            INSERT INTO admin_activity
            (
                event_type,
                title,
                description,
                user_id,
                user_email,
                created_at
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s,
                %s,
                NOW()
            )
            """,
            (
                event_type,
                title,
                description,
                user_id,
                user_email,
            ),
        )

        db.commit()

    except Exception:
        db.rollback()

    finally:
        cursor.close()
        db.close()
