"""Authentication, OTP, password reset and Google authentication routes."""

from flask import Blueprint, jsonify, request
from mysql.connector import Error
from datetime import datetime, timedelta
import random
import secrets
import traceback
from werkzeug.security import generate_password_hash, check_password_hash

from db import get_db
from config import (
    GOOGLE_CLIENT_ID, generate_token, send_otp_email,
    send_password_reset_otp_email, mark_password_reset_verified,
    is_password_reset_verified, clear_password_reset_verified,
    verify_google_id_token,
)

bp=Blueprint("auth", __name__)

@bp.route(
    "/api/auth/register",
    methods=["POST"]
)
def register():

    try:

        data = request.get_json(
            silent=True
        )

        if not data:

            return jsonify({

                "message":
                    "Invalid request."

            }), 400

        name = (
            data.get("name")
            or ""
        ).strip()

        email = (
            data.get("email")
            or ""
        ).strip().lower()

        password = (
            data.get("password")
            or ""
        )

        if len(name) < 2:

            return jsonify({

                "message":
                    "Please enter your full name."

            }), 400

        if not email:

            return jsonify({

                "message":
                    "Please enter your email."

            }), 400

        if len(password) < 6:

            return jsonify({

                "message":
                    "Password must contain at least 6 characters."

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
            (email,)
        )

        existing_user = cursor.fetchone()

        if existing_user:

            cursor.close()
            db.close()

            return jsonify({

                "message":
                    "An account with this email already exists. Please login."

            }), 409

        otp = str(
            random.randint(
                100000,
                999999
            )
        )

        otp_hash = generate_password_hash(
            otp
        )

        password_hash = generate_password_hash(
            password
        )

        expires_at = (
            datetime.now()
            +
            timedelta(minutes=10)
        )

        cursor.execute(
            """
            DELETE FROM email_otps
            WHERE email = %s
            """,
            (email,)
        )

        cursor.execute(
            """
            INSERT INTO email_otps
            (
                email,
                name,
                password_hash,
                otp_hash,
                expires_at,
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
                email,
                name,
                password_hash,
                otp_hash,
                expires_at
            )
        )

        db.commit()

        cursor.close()
        db.close()

        email_sent = send_otp_email(
            email,
            otp
        )

        if not email_sent:

            return jsonify({

                "message":
                    "Unable to send OTP email."

            }), 500

        return jsonify({

            "message":
                "OTP sent successfully.",

            "email":
                email

        }), 200

    except Error as error:

        print(
            "Register database error:",
            error
        )

        return jsonify({

            "message":
                "Database error: " +
                str(error)

        }), 500

    except Exception as error:

        print(
            "Register error:",
            error
        )

        return jsonify({

            "message":
                "Registration failed."

        }), 500


@bp.route(
    "/api/auth/verify-otp",
    methods=["POST"]
)
def verify_otp():

    try:

        data = request.get_json(
            silent=True
        )

        if not data:

            return jsonify({

                "message":
                    "Invalid request."

            }), 400

        email = (
            data.get("email")
            or ""
        ).strip().lower()

        otp = (
            data.get("otp")
            or ""
        ).strip()

        if not email or not otp:

            return jsonify({

                "message":
                    "Email and OTP are required."

            }), 400

        if (
            not otp.isdigit()
            or len(otp) != 6
        ):

            return jsonify({

                "message":
                    "Please enter a valid 6-digit OTP."

            }), 400

        db = get_db()

        cursor = db.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT
                id,
                email,
                name,
                password_hash,
                otp_hash,
                expires_at
            FROM email_otps
            WHERE email = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (email,)
        )

        record = cursor.fetchone()

        if not record:

            cursor.close()
            db.close()

            return jsonify({

                "message":
                    "OTP not found. Please register again."

            }), 404

        if (
            datetime.now()
            >
            record["expires_at"]
        ):

            cursor.close()
            db.close()

            return jsonify({

                "message":
                    "OTP has expired. Please request a new OTP."

            }), 410

        if not check_password_hash(
            record["otp_hash"],
            otp
        ):

            cursor.close()
            db.close()

            return jsonify({

                "message":
                    "Invalid OTP."

            }), 400

        cursor.execute(
            """
            SELECT id
            FROM users
            WHERE email = %s
            LIMIT 1
            """,
            (email,)
        )

        existing_user = cursor.fetchone()

        if existing_user:

            cursor.close()
            db.close()

            return jsonify({

                "message":
                    "Account already exists. Please login."

            }), 409

        cursor.execute(
            """
            INSERT INTO users
            (
                name,
                email,
                password_hash,
                role,
                email_verified,
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
                record["name"],
                record["email"],
                record["password_hash"],
                "client",
                1
            )
        )

        user_id = cursor.lastrowid

        cursor.execute(
            """
            DELETE FROM email_otps
            WHERE email = %s
            """,
            (email,)
        )

        db.commit()

        cursor.close()
        db.close()

        token = generate_token()

        return jsonify({

            "message":
                "Email verified successfully.",

            "token":
                token,

            "user": {

                "id":
                    user_id,

                "name":
                    record["name"],

                "email":
                    record["email"],

                "role":
                    "client"

            }

        }), 200

    except Error as error:

        print(
            "OTP database error:",
            error
        )

        return jsonify({

            "message":
                "Database error: " +
                str(error)

        }), 500

    except Exception as error:

        print(
            "OTP verification error:",
            error
        )

        return jsonify({

            "message":
                "OTP verification failed."

        }), 500


@bp.route(
    "/api/auth/resend-otp",
    methods=["POST"]
)
def resend_otp():

    try:

        data = request.get_json(
            silent=True
        )

        if not data:

            return jsonify({

                "message":
                    "Invalid request."

            }), 400

        email = (
            data.get("email")
            or ""
        ).strip().lower()

        if not email:

            return jsonify({

                "message":
                    "Email is required."

            }), 400

        db = get_db()

        cursor = db.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT
                id,
                email,
                name,
                password_hash,
                created_at
            FROM email_otps
            WHERE email = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (email,)
        )

        record = cursor.fetchone()

        if not record:

            cursor.close()
            db.close()

            return jsonify({

                "message":
                    "Registration not found. Please register again."

            }), 404

        if record["created_at"]:

            elapsed = (
                datetime.now()
                -
                record["created_at"]
            ).total_seconds()

            if elapsed < 30:

                remaining = int(
                    30 - elapsed
                )

                cursor.close()
                db.close()

                return jsonify({

                    "message":
                        f"Please wait {remaining} seconds before requesting another OTP."

                }), 429

        otp = str(
            random.randint(
                100000,
                999999
            )
        )

        otp_hash = generate_password_hash(
            otp
        )

        expires_at = (
            datetime.now()
            +
            timedelta(minutes=10)
        )

        cursor.execute(
            """
            UPDATE email_otps
            SET
                otp_hash = %s,
                expires_at = %s,
                created_at = NOW()
            WHERE id = %s
            """,
            (
                otp_hash,
                expires_at,
                record["id"]
            )
        )

        db.commit()

        cursor.close()
        db.close()

        email_sent = send_otp_email(
            email,
            otp
        )

        if not email_sent:

            return jsonify({

                "message":
                    "Unable to send OTP."

            }), 500

        return jsonify({

            "message":
                "A new OTP has been sent."

        }), 200

    except Error as error:

        print(
            "Resend database error:",
            error
        )

        return jsonify({

            "message":
                "Database error."

        }), 500

    except Exception as error:

        print(
            "Resend OTP error:",
            error
        )

        return jsonify({

            "message":
                "Unable to resend OTP."

        }), 500


@bp.route(
    "/api/auth/forgot-password",
    methods=["POST"]
)
def forgot_password():

    db = None
    cursor = None

    try:

        data = request.get_json(
            silent=True
        ) or {}

        email = (
            data.get("email")
            or ""
        ).strip().lower()

        if not email:

            return jsonify({
                "message":
                    "Email is required."
            }), 400

        db = get_db()

        cursor = db.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT
                id,
                name,
                email,
                password_hash
            FROM users
            WHERE email = %s
            LIMIT 1
            """,
            (email,)
        )

        user = cursor.fetchone()

        if not user:

            return jsonify({
                "message":
                    "No StudyAI account found with this email."
            }), 404

        # 30-second resend protection
        cursor.execute(
            """
            SELECT
                created_at
            FROM email_otps
            WHERE email = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (email,)
        )

        previous = cursor.fetchone()

        if previous and previous.get("created_at"):

            elapsed = (
                datetime.now()
                -
                previous["created_at"]
            ).total_seconds()

            if elapsed < 30:

                remaining = max(
                    1,
                    int(30 - elapsed)
                )

                return jsonify({
                    "message":
                        f"Please wait {remaining} seconds before requesting another OTP."
                }), 429

        otp = str(
            random.randint(
                100000,
                999999
            )
        )

        otp_hash = generate_password_hash(
            otp
        )

        expires_at = (
            datetime.now()
            +
            timedelta(minutes=10)
        )

        cursor.execute(
            """
            DELETE FROM email_otps
            WHERE email = %s
            """,
            (email,)
        )

        cursor.execute(
            """
            INSERT INTO email_otps
            (
                email,
                name,
                password_hash,
                otp_hash,
                expires_at,
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
                email,
                user["name"],
                user["password_hash"],
                otp_hash,
                expires_at
            )
        )

        db.commit()

        cursor.close()
        cursor = None

        db.close()
        db = None

        email_sent = send_password_reset_otp_email(
            email,
            otp
        )

        if not email_sent:

            return jsonify({
                "message":
                    "Unable to send OTP email. Check SMTP settings."
            }), 500

        return jsonify({
            "message":
                "OTP sent successfully.",
            "email":
                email
        }), 200

    except Error as error:

        print(
            "Forgot password database error:",
            error
        )

        if db:
            try:
                db.rollback()
            except Exception:
                pass

        return jsonify({
            "message":
                "Database error: " + str(error)
        }), 500

    except Exception as error:

        import traceback

        print(
            "\n========== FORGOT PASSWORD SEND ERROR ==========\n"
        )

        traceback.print_exc()

        print(
            "\n==================================================\n"
        )

        if db:
            try:
                db.rollback()
            except Exception:
                pass

        return jsonify({
            "message":
                "Unable to send password reset OTP.",
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


@bp.route(
    "/api/auth/forgot-password/verify",
    methods=["POST"]
)
def verify_forgot_password_otp():

    db = None
    cursor = None

    try:

        data = request.get_json(
            silent=True
        ) or {}

        email = (
            data.get("email")
            or ""
        ).strip().lower()

        otp = (
            data.get("otp")
            or ""
        ).strip()

        if not email or not otp:

            return jsonify({
                "message":
                    "Email and OTP are required."
            }), 400

        if not otp.isdigit() or len(otp) != 6:

            return jsonify({
                "message":
                    "Please enter a valid 6-digit OTP."
            }), 400

        db = get_db()

        cursor = db.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT
                id,
                otp_hash,
                expires_at
            FROM email_otps
            WHERE email = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (email,)
        )

        record = cursor.fetchone()

        if not record:

            return jsonify({
                "message":
                    "OTP not found. Please request a new OTP."
            }), 404

        if (
            not record["expires_at"]
            or
            datetime.now() > record["expires_at"]
        ):

            return jsonify({
                "message":
                    "OTP has expired. Please request a new OTP."
            }), 410

        if not check_password_hash(
            record["otp_hash"],
            otp
        ):

            return jsonify({
                "message":
                    "Invalid OTP."
            }), 400

        mark_password_reset_verified(
            email
        )

        return jsonify({
            "message":
                "OTP verified successfully.",
            "verified":
                True
        }), 200

    except Error as error:

        print(
            "Forgot password verify database error:",
            error
        )

        return jsonify({
            "message":
                "Database error: " + str(error)
        }), 500

    except Exception as error:

        import traceback

        print(
            "\n========== FORGOT PASSWORD VERIFY ERROR ==========\n"
        )

        traceback.print_exc()

        print(
            "\n====================================================\n"
        )

        return jsonify({
            "message":
                "Unable to verify OTP.",
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


@bp.route(
    "/api/auth/reset-password",
    methods=["POST"]
)
def reset_forgot_password():

    db = None
    cursor = None

    try:

        data = request.get_json(
            silent=True
        ) or {}

        email = (
            data.get("email")
            or ""
        ).strip().lower()

        new_password = (
            data.get("new_password")
            or ""
        )

        if not email or not new_password:

            return jsonify({
                "message":
                    "Email and new password are required."
            }), 400

        if len(new_password) < 6:

            return jsonify({
                "message":
                    "Password must contain at least 6 characters."
            }), 400

        if not is_password_reset_verified(
            email
        ):

            return jsonify({
                "message":
                    "Please verify the OTP before resetting your password."
            }), 403

        db = get_db()

        cursor = db.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT
                id
            FROM users
            WHERE email = %s
            LIMIT 1
            """,
            (email,)
        )

        user = cursor.fetchone()

        if not user:

            clear_password_reset_verified(
                email
            )

            return jsonify({
                "message":
                    "User account not found."
            }), 404

        new_password_hash = generate_password_hash(
            new_password
        )

        cursor.execute(
            """
            UPDATE users
            SET password_hash = %s
            WHERE id = %s
            """,
            (
                new_password_hash,
                user["id"]
            )
        )

        cursor.execute(
            """
            DELETE FROM email_otps
            WHERE email = %s
            """,
            (email,)
        )

        db.commit()

        clear_password_reset_verified(
            email
        )

        return jsonify({
            "message":
                "Password reset successfully."
        }), 200

    except Error as error:

        print(
            "Password reset database error:",
            error
        )

        if db:
            try:
                db.rollback()
            except Exception:
                pass

        return jsonify({
            "message":
                "Database error: " + str(error)
        }), 500

    except Exception as error:

        import traceback

        print(
            "\n========== PASSWORD RESET ERROR ==========\n"
        )

        traceback.print_exc()

        print(
            "\n==========================================\n"
        )

        if db:
            try:
                db.rollback()
            except Exception:
                pass

        return jsonify({
            "message":
                "Unable to reset password.",
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


@bp.route(
    "/api/auth/google-config",
    methods=["GET"]
)
def google_auth_config():

    if not GOOGLE_CLIENT_ID:

        return jsonify({
            "message": "Google Login is not configured on the server."
        }), 503

    return jsonify({
        "client_id": GOOGLE_CLIENT_ID
    }), 200


@bp.route(
    "/api/auth/google",
    methods=["POST"]
)
def google_auth():

    db = None
    cursor = None

    try:

        data = request.get_json(
            silent=True
        ) or {}

        credential = (
            data.get("credential")
            or ""
        ).strip()

        if not credential:

            return jsonify({
                "message":
                    "Google credential is required."
            }), 400

        google_user = verify_google_id_token(
            credential
        )

        email = google_user["email"]
        name = google_user["name"]

        db = get_db()

        cursor = db.cursor(
            dictionary=True
        )

        cursor.execute(
            """
            SELECT
                id,
                name,
                email,
                role,
                email_verified
            FROM users
            WHERE email = %s
            LIMIT 1
            """,
            (email,)
        )

        user = cursor.fetchone()

        # Existing StudyAI account:
        # log it in without changing its password.
        if user:

            if not user.get("email_verified"):

                cursor.execute(
                    """
                    UPDATE users
                    SET
                        email_verified = 1
                    WHERE id = %s
                    """,
                    (user["id"],)
                )

                user["email_verified"] = 1

            # Keep the existing StudyAI name unless empty.
            if not (user.get("name") or "").strip():

                cursor.execute(
                    """
                    UPDATE users
                    SET
                        name = %s
                    WHERE id = %s
                    """,
                    (
                        name,
                        user["id"]
                    )
                )

                user["name"] = name

        else:

            # New Google account.
            # A random password hash satisfies the existing schema;
            # the user never sees or uses this password.
            random_password_hash = generate_password_hash(
                secrets.token_urlsafe(32)
            )

            cursor.execute(
                """
                INSERT INTO users
                (
                    name,
                    email,
                    password_hash,
                    role,
                    email_verified,
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
                    name,
                    email,
                    random_password_hash,
                    "client",
                    1
                )
            )

            user = {
                "id": cursor.lastrowid,
                "name": name,
                "email": email,
                "role": "client",
                "email_verified": 1
            }

        db.commit()

        token = generate_token()


        return jsonify({

            "message":
                "Google login successful.",

            "token":
                token,

            "user": {

                "id":
                    user["id"],

                "name":
                    user["name"],

                "email":
                    user["email"],

                "role":
                    user.get("role")
                    or "client"

            }

        }), 200

    except ValueError as error:

        if db:
            try:
                db.rollback()
            except Exception:
                pass

        return jsonify({
            "message":
                str(error)
        }), 401

    except Error as error:

        if db:
            try:
                db.rollback()
            except Exception:
                pass

        print(
            "Google authentication database error:",
            error
        )

        return jsonify({
            "message":
                "Database error during Google Login.",
            "error":
                str(error)
        }), 500

    except Exception as error:

        if db:
            try:
                db.rollback()
            except Exception:
                pass

        import traceback
        print(
            "\n========== GOOGLE AUTH ERROR ==========\n"
        )
        traceback.print_exc()
        print(
            "\n=======================================\n"
        )

        return jsonify({
            "message":
                "Unable to complete Google Login.",
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


@bp.route(
    "/api/auth/login",
    methods=["POST"]
)
def login():

    db = None
    cursor = None

    try:

        data = request.get_json(silent=True) or {}

        email = (
            data.get("email") or ""
        ).strip().lower()

        password = data.get("password") or ""

        if not email or not password:
            return jsonify({
                "message": "Email and password are required."
            }), 400

        db = get_db()
        cursor = db.cursor(dictionary=True)

        # CLIENT LOGIN ONLY:
        # This endpoint checks ONLY password_hash.
        # admin_password_hash is NEVER checked here.
        cursor.execute(
            """
            SELECT
                id,
                name,
                email,
                password_hash,
                role,
                email_verified,
                created_at
            FROM users
            WHERE email = %s
            LIMIT 1
            """,
            (email,)
        )

        user = cursor.fetchone()

        if not user:
            return jsonify({
                "message": "Invalid email or password."
            }), 401

        if not user.get("email_verified"):
            return jsonify({
                "message": "Please verify your email first."
            }), 403

        if not check_password_hash(
            user["password_hash"],
            password
        ):
            return jsonify({
                "message": "Invalid email or password."
            }), 401

        token = generate_token()

        # IMPORTANT:
        # Even when the same database account also has an admin
        # credential, successful login through /api/auth/login is
        # a CLIENT session. The admin credential can only be used
        # through /api/admin/login.
        return jsonify({
            "message": "Login successful.",
            "token": token,
            "user": {
                "id": user["id"],
                "name": user["name"],
                "email": user["email"],
                "role": "client",
                "email_verified": bool(user["email_verified"]),
                "created_at": (
                    user["created_at"].isoformat()
                    if user["created_at"]
                    else None
                )
            }
        }), 200

    except Error as error:

        print("Login database error:", error)

        return jsonify({
            "message": "Database error: " + str(error)
        }), 500

    except Exception as error:

        print("Login error:", error)

        return jsonify({
            "message": "Login failed."
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


