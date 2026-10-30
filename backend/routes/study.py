"""Study timer and progress routes."""

from flask import Blueprint, jsonify, request
from mysql.connector import Error
from datetime import datetime
import traceback

from db import get_db

bp=Blueprint("study", __name__)

@bp.route(
    "/api/study/start",
    methods=["POST"]
)
def start_study():

    try:

        data = request.get_json(
            silent=True
        )

        if not data:

            return jsonify({

                "message":
                    "Invalid request."

            }), 400

        user_email = (
            data.get("user_email")
            or ""
        ).strip().lower()

        if not user_email:

            return jsonify({

                "message":
                    "User email is required."

            }), 400

        db = get_db()

        cursor = db.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT
                id,
                email
            FROM users
            WHERE email = %s
            LIMIT 1
            """,
            (user_email,)
        )

        user = cursor.fetchone()

        if not user:

            cursor.close()
            db.close()

            return jsonify({

                "message":
                    "User account not found."

            }), 404

        # -------------------------------------------------
        # CHECK FOR ALREADY RUNNING SESSION
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT
                id,
                started_at,
                duration_seconds
            FROM study_sessions
            WHERE user_id = %s
            AND finished_at IS NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (user["id"],)
        )

        active_session = cursor.fetchone()

        if active_session:

            started_at = active_session["started_at"]

            elapsed_seconds = max(
                0,
                int(
                    (
                        datetime.now()
                        -
                        started_at
                    ).total_seconds()
                )
            )

            cursor.close()
            db.close()

            return jsonify({

                "message":
                    "A study session is already running.",

                "session_id":
                    active_session["id"],

                "started_at":
                    started_at.isoformat(),

                "elapsed_seconds":
                    elapsed_seconds,

                "duration_seconds":
                    elapsed_seconds

            }), 200

        # -------------------------------------------------
        # CREATE NEW SESSION
        # -------------------------------------------------

        started_at = datetime.now()

        cursor.execute(
            """
            INSERT INTO study_sessions
            (
                user_id,
                user_email,
                duration_seconds,
                started_at,
                finished_at
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s,
                NULL
            )
            """,
            (
                user["id"],
                user["email"],
                0,
                started_at
            )
        )

        session_id = cursor.lastrowid

        db.commit()

        cursor.close()
        db.close()

        return jsonify({

            "message":
                "Study session started.",

            "session_id":
                session_id,

            "started_at":
                started_at.isoformat(),

            "elapsed_seconds":
                0,

            "duration_seconds":
                0

        }), 201

    except Error as error:

        print(
            "Start study database error:",
            error
        )

        return jsonify({

            "message":
                "Database error."

        }), 500

    except Exception as error:

        print(
            "Start study error:",
            error
        )

        return jsonify({

            "message":
                "Unable to start study session."

        }), 500


@bp.route(
    "/api/study/finish",
    methods=["POST"]
)
def finish_study():

    try:

        data = request.get_json(
            silent=True
        )

        if not data:

            return jsonify({

                "message":
                    "Invalid request."

            }), 400

        user_email = (
            data.get("user_email")
            or ""
        ).strip().lower()

        session_id = data.get(
            "session_id"
        )

        if not user_email:

            return jsonify({

                "message":
                    "User email is required."

            }), 400

        if not session_id:

            return jsonify({

                "message":
                    "Session ID is required."

            }), 400

        db = get_db()

        cursor = db.cursor(
            dictionary=True
        )

        # -------------------------------------------------
        # FIND USER
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT id
            FROM users
            WHERE email = %s
            LIMIT 1
            """,
            (user_email,)
        )

        user = cursor.fetchone()

        if not user:

            cursor.close()
            db.close()

            return jsonify({

                "message":
                    "User account not found."

            }), 404

        # -------------------------------------------------
        # GET ACTIVE SESSION
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT
                id,
                started_at,
                duration_seconds
            FROM study_sessions
            WHERE id = %s
            AND user_id = %s
            AND finished_at IS NULL
            LIMIT 1
            """,
            (
                session_id,
                user["id"]
            )
        )

        session = cursor.fetchone()

        if not session:

            cursor.close()
            db.close()

            return jsonify({

                "message":
                    "Study session not found or already finished."

            }), 404

        # -------------------------------------------------
        # CALCULATE ACTUAL ELAPSED TIME
        # -------------------------------------------------

        started_at = session["started_at"]

        finished_at = datetime.now()

        duration_seconds = max(
            0,
            int(
                (
                    finished_at
                    -
                    started_at
                ).total_seconds()
            )
        )

        # -------------------------------------------------
        # SAVE DURATION
        # -------------------------------------------------

        cursor.execute(
            """
            UPDATE study_sessions
            SET
                duration_seconds = %s,
                finished_at = %s
            WHERE id = %s
            AND user_id = %s
            AND finished_at IS NULL
            """,
            (
                duration_seconds,
                finished_at,
                session_id,
                user["id"]
            )
        )

        if cursor.rowcount == 0:

            cursor.close()
            db.close()

            return jsonify({

                "message":
                    "Study session not found or already finished."

            }), 404

        db.commit()

        cursor.close()
        db.close()

        return jsonify({

            "message":
                "Study session completed.",

            "duration_seconds":
                duration_seconds,

            "finished_at":
                finished_at.isoformat()

        }), 200

    except Error as error:

        print(
            "Finish study database error:",
            error
        )

        return jsonify({

            "message":
                "Database error."

        }), 500

    except Exception as error:

        print(
            "Finish study error:",
            error
        )

        return jsonify({

            "message":
                "Unable to finish study session."

        }), 500


@bp.route(
    "/api/study/active",
    methods=["GET"]
)
def get_active_study():

    try:

        user_email = (
            request.args.get(
                "user_email"
            )
            or ""
        ).strip().lower()

        if not user_email:

            return jsonify({

                "active":
                    False,

                "message":
                    "User email is required."

            }), 400

        db = get_db()

        cursor = db.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT
                u.id AS user_id,
                s.id AS session_id,
                s.started_at,
                s.duration_seconds
            FROM users u
            INNER JOIN study_sessions s
                ON s.user_id = u.id
            WHERE u.email = %s
            AND s.finished_at IS NULL
            ORDER BY s.id DESC
            LIMIT 1
            """,
            (user_email,)
        )

        session = cursor.fetchone()

        cursor.close()
        db.close()

        if not session:

            return jsonify({

                "active":
                    False,

                "elapsed_seconds":
                    0,

                "duration_seconds":
                    0

            }), 200

        elapsed_seconds = max(
            0,
            int(
                (
                    datetime.now()
                    -
                    session["started_at"]
                ).total_seconds()
            )
        )

        return jsonify({

            "active":
                True,

            "session_id":
                session["session_id"],

            "started_at":
                session["started_at"].isoformat(),

            "elapsed_seconds":
                elapsed_seconds,

            "duration_seconds":
                elapsed_seconds

        }), 200

    except Error as error:

        print(
            "Active study database error:",
            error
        )

        return jsonify({

            "active":
                False,

            "elapsed_seconds":
                0,

            "duration_seconds":
                0,

            "message":
                "Database error."

        }), 500

    except Exception as error:

        print(
            "Active study error:",
            error
        )

        return jsonify({

            "active":
                False,

            "elapsed_seconds":
                0,

            "duration_seconds":
                0,

            "message":
                "Unable to check active session."

        }), 500


@bp.route(
    "/api/study/time",
    methods=["GET"]
)
def get_study_time():

    try:

        user_email = (
            request.args.get(
                "user_email"
            )
            or ""
        ).strip().lower()

        if not user_email:

            return jsonify({

                "message":
                    "User email is required.",

                "seconds":
                    0,

                "minutes":
                    0,

                "hours":
                    0

            }), 400

        db = get_db()

        cursor = db.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT id
            FROM users
            WHERE email = %s
            LIMIT 1
            """,
            (user_email,)
        )

        user = cursor.fetchone()

        if not user:

            cursor.close()
            db.close()

            return jsonify({

                "message":
                    "User not found.",

                "seconds":
                    0,

                "minutes":
                    0,

                "hours":
                    0

            }), 404

        cursor.execute(
            """
            SELECT
                COALESCE(
                    SUM(duration_seconds),
                    0
                ) AS total_seconds
            FROM study_sessions
            WHERE user_id = %s
            AND finished_at IS NOT NULL
            """,
            (user["id"],)
        )

        result = cursor.fetchone()

        total_seconds = int(
            result["total_seconds"] or 0
        )

        cursor.close()
        db.close()

        total_minutes = (
            total_seconds // 60
        )

        total_hours = (
            total_seconds // 3600
        )

        return jsonify({

            "user_id":
                user["id"],

            "seconds":
                total_seconds,

            "minutes":
                total_minutes,

            "hours":
                total_hours

        }), 200

    except Error as error:

        print(
            "Study time database error:",
            error
        )

        return jsonify({

            "seconds":
                0,

            "minutes":
                0,

            "hours":
                0,

            "message":
                "Database error."

        }), 500

    except Exception as error:

        print(
            "Study time error:",
            error
        )

        return jsonify({

            "seconds":
                0,

            "minutes":
                0,

            "hours":
                0,

            "message":
                "Unable to load study time."

        }), 500


@bp.route(
    "/api/study/time/reset",
    methods=["DELETE"]
)
def reset_study_time():

    try:

        user_email = (
            request.args.get(
                "user_email"
            )
            or ""
        ).strip().lower()

        if not user_email:

            return jsonify({

                "message":
                    "User email is required."

            }), 400

        db = get_db()

        cursor = db.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT id
            FROM users
            WHERE email = %s
            LIMIT 1
            """,
            (user_email,)
        )

        user = cursor.fetchone()

        if not user:

            cursor.close()
            db.close()

            return jsonify({

                "message":
                    "User not found."

            }), 404

        # Never delete an active session.
        cursor.execute(
            """
            DELETE FROM study_sessions
            WHERE user_id = %s
            AND finished_at IS NOT NULL
            """,
            (user["id"],)
        )

        deleted_count = cursor.rowcount

        db.commit()

        cursor.close()
        db.close()

        return jsonify({

            "message":
                "Study time reset successfully.",

            "deleted_count":
                deleted_count

        }), 200

    except Error as error:

        print(
            "Reset study time database error:",
            error
        )

        return jsonify({

            "message":
                "Database error."

        }), 500

    except Exception as error:

        print(
            "Reset study time error:",
            error
        )

        return jsonify({

            "message":
                "Unable to reset study time."

        }), 500


@bp.route(
    "/api/progress",
    methods=["GET"]
)
def get_progress():

    db = None
    cursor = None

    try:

        # -------------------------------------------------
        # GET USER EMAIL
        # -------------------------------------------------

        user_email = (
            request.args.get(
                "user_email",
                ""
            )
            .strip()
            .lower()
        )


        if not user_email:

            return jsonify({

                "message":
                    "User email is required."

            }), 400


        # -------------------------------------------------
        # DATABASE
        # -------------------------------------------------

        db = get_db()

        cursor = db.cursor(
            dictionary=True
        )


        # -------------------------------------------------
        # USER
        # -------------------------------------------------

        cursor.execute(
            """
            SELECT
                id,
                name,
                email
            FROM users
            WHERE email = %s
            LIMIT 1
            """,
            (user_email,)
        )

        user = cursor.fetchone()


        if not user:

            return jsonify({

                "message":
                    "User not found."

            }), 404


        user_id = user["id"]


        # =================================================
        # 1. STUDY TIME
        # =================================================

        total_study_minutes = 0

        try:

            cursor.execute(
                """
                SELECT
                    COALESCE(
                        SUM(
                            duration_minutes
                        ),
                        0
                    ) AS total_minutes
                FROM study_sessions
                WHERE user_id = %s
                """,
                (user_id,)
            )

            row = cursor.fetchone()

            if row:

                total_study_minutes = int(
                    row["total_minutes"] or 0
                )

        except Exception as error:

            print(
                "Study time query skipped:",
                error
            )

            db.rollback()


        # =================================================
        # 2. MATERIALS
        # =================================================

        material_count = 0

        try:

            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total
                FROM materials
                WHERE user_id = %s
                """,
                (user_id,)
            )

            row = cursor.fetchone()

            if row:

                material_count = int(
                    row["total"] or 0
                )

        except Exception as error:

            print(
                "Materials query skipped:",
                error
            )

            db.rollback()


        # =================================================
        # 3. QUESTION ACTIVITY
        #
        # First try common question tables.
        # If they don't exist, keep value at 0.
        # =================================================

        questions_solved = 0

        possible_question_tables = [

            "question_attempts",
            "quiz_attempts",
            "question_history"

        ]


        for table_name in possible_question_tables:

            try:

                cursor.execute(
                    f"""
                    SELECT
                        COUNT(*) AS total
                    FROM {table_name}
                    WHERE user_id = %s
                    """,
                    (user_id,)
                )

                row = cursor.fetchone()

                if row:

                    questions_solved = int(
                        row["total"] or 0
                    )

                    break

            except Exception:

                db.rollback()

                continue


        # =================================================
        # 4. STUDY PLAN COUNT
        # =================================================

        plans_created = 0

        try:

            cursor.execute(
                """
                SELECT
                    COUNT(*) AS total
                FROM study_plans
                WHERE user_id = %s
                """,
                (user_id,)
            )

            row = cursor.fetchone()

            if row:

                plans_created = int(
                    row["total"] or 0
                )

        except Exception as error:

            print(
                "Study plan query skipped:",
                error
            )

            db.rollback()


        # =================================================
        # 5. GOALS
        # =================================================

        goals_completed = 0
        total_goals = 0

        possible_goal_tables = [

            "goals",
            "study_goals"

        ]


        for table_name in possible_goal_tables:

            try:

                cursor.execute(
                    f"""
                    SELECT
                        COUNT(*) AS total
                    FROM {table_name}
                    WHERE user_id = %s
                    """,
                    (user_id,)
                )

                row = cursor.fetchone()

                if row:

                    total_goals = int(
                        row["total"] or 0
                    )


                cursor.execute(
                    f"""
                    SELECT
                        COUNT(*) AS completed
                    FROM {table_name}
                    WHERE user_id = %s
                    AND (
                        status = 'completed'
                        OR completed = 1
                        OR is_completed = 1
                    )
                    """,
                    (user_id,)
                )

                row = cursor.fetchone()

                if row:

                    goals_completed = int(
                        row["completed"] or 0
                    )


                break

            except Exception:

                db.rollback()

                continue


        # =================================================
        # 6. OVERALL PROGRESS
        #
        # Progress is based on actual activity:
        #
        # Study time
        # Materials
        # Questions
        # Goals
        # =================================================

        progress_parts = []


        # Study time contribution
        study_progress = min(
            total_study_minutes / 600 * 100,
            100
        )

        progress_parts.append(
            study_progress
        )


        # Materials contribution
        material_progress = min(
            material_count / 10 * 100,
            100
        )

        progress_parts.append(
            material_progress
        )


        # Questions contribution
        question_progress = min(
            questions_solved / 50 * 100,
            100
        )

        progress_parts.append(
            question_progress
        )


        # Goals contribution
        if total_goals > 0:

            goal_progress = (
                goals_completed /
                total_goals
            ) * 100

        else:

            goal_progress = 0


        progress_parts.append(
            goal_progress
        )


        overall_progress = round(
            sum(progress_parts) /
            len(progress_parts)
        )


        # =================================================
        # 7. SUBJECT PROGRESS
        #
        # Use study plans as available subject/goal data.
        # =================================================

        subjects = []


        try:

            cursor.execute(
                """
                SELECT
                    goal,
                    COUNT(*) AS total_plans
                FROM study_plans
                WHERE user_id = %s
                GROUP BY goal
                ORDER BY total_plans DESC
                LIMIT 10
                """,
                (user_id,)
            )

            rows = cursor.fetchall()


            for row in rows:

                goal_name = row["goal"] or "Study"


                subjects.append({

                    "name":
                        goal_name,

                    "progress":
                        min(
                            int(row["total_plans"]) * 20,
                            100
                        )

                })

        except Exception as error:

            print(
                "Subject progress query skipped:",
                error
            )

            db.rollback()


        # =================================================
        # 8. LAST 7 DAYS STUDY ACTIVITY
        # =================================================

        weekly_activity = [
            0,
            0,
            0,
            0,
            0,
            0,
            0
        ]


        try:

            cursor.execute(
                """
                SELECT
                    DAYOFWEEK(started_at) AS day_number,
                    COALESCE(
                        SUM(duration_minutes),
                        0
                    ) AS minutes
                FROM study_sessions
                WHERE user_id = %s
                AND started_at >=
                    DATE_SUB(
                        NOW(),
                        INTERVAL 7 DAY
                    )
                GROUP BY DAYOFWEEK(
                    started_at
                )
                """,
                (user_id,)
            )

            rows = cursor.fetchall()


            for row in rows:

                day_number = int(row["day_number"] or 1)

                minutes = int(row["minutes"] or 0)


                # MySQL:
                # Sunday = 1
                # Monday = 2
                # ...
                # Saturday = 7
                #
                # Convert to:
                # Monday = index 0
                # Sunday = index 6

                index = (
                    day_number - 2
                ) % 7


                weekly_activity[
                    index
                ] = minutes

        except Exception as error:

            print(
                "Weekly activity query skipped:",
                error
            )

            db.rollback()


        # =================================================
        # 9. RECENT ACTIVITY
        # =================================================

        activities = []


        try:

            cursor.execute(
                """
                SELECT
                    duration_minutes,
                    started_at,
                    finished_at
                FROM study_sessions
                WHERE user_id = %s
                ORDER BY id DESC
                LIMIT 10
                """,
                (user_id,)
            )

            rows = cursor.fetchall()


            for row in rows:

                minutes =int(row["duration_minutes"]or 0)


                started = row["started_at"]


                time_text = ""


                if started:

                    try:

                        time_text = started.strftime("%d %b %Y, %I:%M %p")

                    except Exception:

                        time_text =str(started)


                activities.append({

                    "icon":
                        "⏱️",

                    "title":
                        "Study session",

                    "description":
                        (
                            str(minutes) +
                            " minutes studied"
                        ),

                    "time":
                        time_text

                })

        except Exception as error:

            print(
                "Activity query skipped:",
                error
            )

            db.rollback()


        # =================================================
        # CLOSE
        # =================================================

        cursor.close()
        cursor = None

        db.close()
        db = None


        # =================================================
        # RESPONSE
        # =================================================

        return jsonify({

            "message":
                "Progress loaded successfully.",

            "progress": {

                "materialsCompleted":
                    material_count,

                "studyTimeMinutes":
                    total_study_minutes,

                "questionsSolved":
                    questions_solved,

                "goalsCompleted":
                    goals_completed,

                "overallProgress":
                    overall_progress,

                "subjects":
                    subjects,

                "weeklyActivity":
                    weekly_activity,

                "activities":
                    activities,

                "studyPlansCreated":
                    plans_created

            }

        }), 200


    except Exception as error:

        import traceback

        print(
            "\n================ PROGRESS API ERROR ================\n"
        )

        traceback.print_exc()

        print(
            "\n======================================================\n"
        )


        if db:

            try:
                db.rollback()
            except Exception:
                pass


        return jsonify({

            "message":
                "Unable to load progress.",

            "error":
                str(error)

        }), 500


    finally:

        if cursor:

            try:
                cursor.close()
            except Exception:
                pass


        if db:

            try:
                db.close()
            except Exception:
                pass

