"""StudyAI administrator authentication and management API."""

from datetime import datetime, timedelta
from functools import wraps
import secrets

from flask import Blueprint, jsonify, request, g
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_db
from services.admin_service import (
    ensure_admin_tables,
    get_setting,
    set_setting,
    log_activity,
    safe_count,
    user_progress,
    iso,
)

bp = Blueprint("admin", __name__, url_prefix="/api/admin")

_ADMIN_TOKENS = {}
TOKEN_HOURS = 8


def _request_token():
    authorization = (
        request.headers.get("Authorization") or ""
    ).strip()

    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()

    return (
        request.headers.get("X-Admin-Token") or ""
    ).strip()


def _issue_admin_token(user):
    token = secrets.token_urlsafe(32)

    _ADMIN_TOKENS[token] = {
        "user_id": user["id"],
        "email": user["email"],
        "expires_at": datetime.now() + timedelta(hours=TOKEN_HOURS),
    }

    return token


def _remove_expired_tokens():
    now = datetime.now()

    expired = [
        token
        for token, record in _ADMIN_TOKENS.items()
        if record.get("expires_at") <= now
    ]

    for token in expired:
        _ADMIN_TOKENS.pop(token, None)



def require_admin(fn):

    @wraps(fn)
    def wrapped(*args, **kwargs):

        _remove_expired_tokens()

        token = _request_token()
        record = _ADMIN_TOKENS.get(token)

        if not record:
            return jsonify({
                "message": "Admin authentication required."
            }), 401

        db = get_db()
        cursor = db.cursor(dictionary=True)

        try:

            cursor.execute(
                """
                SELECT
                    id,
                    name,
                    email,
                    role,
                    email_verified,
                    created_at
                FROM users
                WHERE id = %s
                LIMIT 1
                """,
                (record["user_id"],)
            )

            user = cursor.fetchone()

        finally:
            cursor.close()
            db.close()

        if (
            not user
            or str(user.get("role") or "").lower() != "admin"
        ):
            _ADMIN_TOKENS.pop(token, None)

            return jsonify({
                "message": "Admin access denied."
            }), 403

        g.admin_user = user
        g.admin_token = token

        return fn(*args, **kwargs)

    return wrapped


# =========================================================
# ADMIN LOGIN
# =========================================================

@bp.post("/login")
def admin_login():

    ensure_admin_tables(get_db)

    data = request.get_json(silent=True) or {}

    email = (
        data.get("email") or ""
    ).strip().lower()

    password = data.get("password") or ""

    if not email or not password:
        return jsonify({
            "message": "Admin email and password are required."
        }), 400

    db = get_db()
    cursor = db.cursor(dictionary=True)

    try:

        # IMPORTANT:
        # admin login checks ONLY admin_password_hash.
        # Client password_hash is deliberately NOT checked.
        cursor.execute(
            """
            SELECT
                id,
                name,
                email,
                admin_password_hash,
                role,
                email_verified
            FROM users
            WHERE email = %s
            LIMIT 1
            """,
            (email,)
        )

        user = cursor.fetchone()

        if not user:
            return jsonify({
                "message": "Invalid admin email or password."
            }), 401

        if str(user.get("role") or "").lower() != "admin":
            return jsonify({
                "message": "This account does not have administrator access."
            }), 403

        admin_hash = user.get("admin_password_hash")

        if not admin_hash:
            return jsonify({
                "message": "Admin password is not configured for this account."
            }), 403

        if not check_password_hash(
            admin_hash,
            password
        ):
            return jsonify({
                "message": "Invalid admin email or password."
            }), 401

        token = _issue_admin_token(user)

        log_activity(
            get_db,
            "admin_login",
            "Administrator login",
            email,
            user["id"],
            email,
        )

        return jsonify({
            "message": "Admin login successful.",
            "token": token,
            "user": {
                "id": user["id"],
                "name": user["name"],
                "email": user["email"],
                "role": "admin",
            }
        }), 200

    finally:
        cursor.close()
        db.close()


# =========================================================
# ADMIN DASHBOARD
# =========================================================

@bp.get("/dashboard")
@require_admin
def dashboard():

    db = get_db()
    cursor = db.cursor(dictionary=True)

    try:

        # TOTAL CLIENTS = every non-admin account in users.
        # This does NOT modify or depend on Client Management logic.
        total_clients = safe_count(
            cursor,
            """
            SELECT COUNT(*) AS total
            FROM users
            WHERE LOWER(TRIM(COALESCE(role, 'client'))) <> 'admin'
            """
        )

        # ACTIVE CLIENTS = only clients having a currently running,
        # non-stale study session. A session older than 30 minutes with
        # finished_at still NULL is treated as expired/stale and is not
        # counted as active.
        active_clients = safe_count(
            cursor,
            """
            SELECT COUNT(DISTINCT s.user_id) AS total
            FROM study_sessions s
            INNER JOIN users u ON u.id = s.user_id
            WHERE LOWER(TRIM(COALESCE(u.role, 'client'))) <> 'admin'
              AND s.finished_at IS NULL
              AND s.started_at >= (NOW() - INTERVAL 30 MINUTE)
            """
        )

        total_pdfs = safe_count(
            cursor,
            "SELECT COUNT(*) AS total FROM materials"
        )

        ai_generations = safe_count(
            cursor,
            "SELECT COUNT(*) AS total FROM study_plans"
        )

        # Keep the exact response shape expected by the current admin.html:
        # stats.total_clients / stats.active_clients / ...
        return jsonify({
            "stats": {
                "total_clients": total_clients,
                "active_clients": active_clients,
                "total_pdfs": total_pdfs,
                "ai_generations": ai_generations,
            },
            "settings": {
                "registration_enabled": get_setting(
                    get_db,
                    "registration_enabled",
                    "1"
                ),
                "notifications_enabled": get_setting(
                    get_db,
                    "notifications_enabled",
                    "1"
                ),
                "ai_enabled": get_setting(
                    get_db,
                    "ai_enabled",
                    "1"
                ),
            }
        }), 200

    finally:
        cursor.close()
        db.close()


# =========================================================
# USERS
# =========================================================

@bp.get("/users")
@require_admin
def users():

    db = get_db()
    cursor = db.cursor(dictionary=True)

    try:

        cursor.execute(
            """
            SELECT
                u.id,
                u.name,
                u.email,
                u.role,
                u.email_verified,
                u.created_at,
                (
                    SELECT COUNT(*)
                    FROM materials m
                    WHERE m.user_id = u.id
                ) AS pdfs,
                (
                    SELECT COUNT(*)
                    FROM study_plans p
                    WHERE p.user_id = u.id
                ) AS plans,
                EXISTS(
                    SELECT 1
                    FROM study_sessions s
                    WHERE s.user_id = u.id
                    AND s.finished_at IS NULL
                ) AS currently_active
            FROM users u
            ORDER BY u.id DESC
            """
        )

        rows = cursor.fetchall()

        # Admin panel client list should show actual clients.
        # Admin accounts remain available through the admin login,
        # but are not counted as normal clients.
        rows = [
            row for row in rows
            if str(row.get("role") or "client").lower() != "admin"
        ]

        for user in rows:
            user["created_at"] = iso(
                user.get("created_at")
            )

            user["pdfs"] = int(
                user.get("pdfs") or 0
            )

            user["plans"] = int(
                user.get("plans") or 0
            )

            user["currently_active"] = bool(
                user.get("currently_active")
            )

            user["status"] = (
                "Active"
                if user["currently_active"]
                else "Inactive"
            )

            user["progress"] = user_progress(
                cursor,
                user["id"]
            )

            user["email_verified"] = bool(
                user.get("email_verified")
            )

        return jsonify({
            "users": rows
        }), 200

    finally:
        cursor.close()
        db.close()


# =========================================================
# USER DETAIL
# =========================================================

@bp.get("/users/<int:user_id>")
@require_admin
def user_detail(user_id):

    db = get_db()
    cursor = db.cursor(dictionary=True)

    try:

        cursor.execute(
            """
            SELECT
                id,
                name,
                email,
                role,
                email_verified,
                created_at
            FROM users
            WHERE id = %s
            LIMIT 1
            """,
            (user_id,)
        )

        user = cursor.fetchone()

        if not user:
            return jsonify({
                "message": "User not found."
            }), 404

        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM materials
            WHERE user_id = %s
            """,
            (user_id,)
        )

        user["pdfs"] = int(
            (cursor.fetchone() or {}).get("total") or 0
        )

        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM study_plans
            WHERE user_id = %s
            """,
            (user_id,)
        )

        user["plans"] = int(
            (cursor.fetchone() or {}).get("total") or 0
        )

        user["created_at"] = iso(
            user.get("created_at")
        )

        user["progress"] = user_progress(
            cursor,
            user_id
        )

        return jsonify({
            "user": user
        }), 200

    finally:
        cursor.close()
        db.close()


# =========================================================
# DELETE CLIENT
# =========================================================

@bp.delete("/users/<int:user_id>")
@require_admin
def delete_user(user_id):

    db = get_db()
    cursor = db.cursor(dictionary=True)

    try:

        cursor.execute(
            """
            SELECT
                id,
                name,
                email,
                role
            FROM users
            WHERE id = %s
            LIMIT 1
            """,
            (user_id,)
        )

        user = cursor.fetchone()

        if not user:
            return jsonify({
                "message": "User not found."
            }), 404

        if str(user.get("role") or "").lower() == "admin":
            return jsonify({
                "message": "Admin accounts cannot be deleted from this panel."
            }), 403

        # Delete dependent application data first.
        dependent_tables = (
            "question_attempts",
            "quiz_attempts",
            "question_history",
            "study_plans",
            "study_sessions",
            "materials",
        )

        for table in dependent_tables:
            try:
                cursor.execute(
                    f"DELETE FROM {table} WHERE user_id = %s",
                    (user_id,)
                )
            except Exception:
                db.rollback()

        cursor.execute(
            "DELETE FROM users WHERE id = %s",
            (user_id,)
        )

        if cursor.rowcount == 0:
            db.rollback()
            return jsonify({
                "message": "User not found."
            }), 404

        db.commit()

        log_activity(
            get_db,
            "user_deleted",
            "User deleted",
            user["email"],
            user_id,
            user["email"],
        )

        return jsonify({
            "message": "User deleted successfully.",
            "user_id": user_id
        }), 200

    finally:
        cursor.close()
        db.close()


# =========================================================
# ACTIVITY
# =========================================================

@bp.get("/activity")
@require_admin
def activity():

    ensure_admin_tables(get_db)

    db = get_db()
    cursor = db.cursor(dictionary=True)

    try:

        cursor.execute(
            """
            SELECT
                id,
                event_type,
                title,
                description,
                user_id,
                user_email,
                created_at
            FROM admin_activity
            ORDER BY id DESC
            LIMIT 50
            """
        )

        rows = cursor.fetchall()

        for row in rows:
            row["created_at"] = iso(
                row.get("created_at")
            )

        return jsonify({
            "activities": rows
        }), 200

    finally:
        cursor.close()
        db.close()


# =========================================================
# DELETE ACTIVITY LOG
# =========================================================

@bp.delete("/activity/<int:activity_id>")
@require_admin
def delete_activity(activity_id):

    db = get_db()
    cursor = db.cursor()

    try:
        cursor.execute(
            """
            DELETE FROM admin_activity
            WHERE id = %s
            LIMIT 1
            """,
            (activity_id,)
        )

        if cursor.rowcount == 0:
            db.rollback()
            return jsonify({
                "message": "Activity log not found."
            }), 404

        db.commit()

        return jsonify({
            "message": "Activity log deleted successfully.",
            "activity_id": activity_id
        }), 200

    finally:
        cursor.close()
        db.close()


# =========================================================
# SETTINGS
# =========================================================

@bp.get("/settings")
@require_admin
def settings():

    ensure_admin_tables(get_db)

    db = get_db()
    cursor = db.cursor(dictionary=True)

    try:

        cursor.execute(
            """
            SELECT
                setting_key,
                setting_value,
                updated_at
            FROM admin_settings
            ORDER BY setting_key
            """
        )

        rows = cursor.fetchall()

        for row in rows:
            row["updated_at"] = iso(
                row.get("updated_at")
            )

        return jsonify({
            "settings": rows
        }), 200

    finally:
        cursor.close()
        db.close()


@bp.put("/settings/<setting_key>")
@require_admin
def update_setting(setting_key):

    allowed = {
        "registration_enabled",
        "notifications_enabled",
        "ai_enabled",
        "pdf_upload_limit_mb",
    }

    if setting_key not in allowed:
        return jsonify({
            "message": "Unknown setting."
        }), 404

    data = request.get_json(silent=True) or {}

    value = data.get("value")

    if value is None and "enabled" in data:
        value = "1" if bool(data["enabled"]) else "0"

    if value is None:
        return jsonify({
            "message": "Setting value is required."
        }), 400

    set_setting(
        get_db,
        setting_key,
        value
    )

    log_activity(
        get_db,
        "setting_changed",
        "System setting updated",
        f"{setting_key} = {value}",
    )

    return jsonify({
        "message": "Setting updated.",
        "setting_key": setting_key,
        "value": value
    }), 200


# =========================================================
# LOGOUT
# =========================================================

@bp.post("/logout")
@require_admin
def logout():

    token = g.get("admin_token")

    if token:
        _ADMIN_TOKENS.pop(token, None)

    return jsonify({
        "message": "Admin logged out."
    }), 200


# =========================================================
# CURRENT ADMIN
# =========================================================

@bp.get("/me")
@require_admin
def me():

    user = g.admin_user

    return jsonify({
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": "admin",
        }
    }), 200
