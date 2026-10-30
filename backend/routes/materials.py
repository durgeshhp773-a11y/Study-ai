"""Study material / PDF routes."""

from flask import Blueprint, jsonify, request
from mysql.connector import Error
from datetime import datetime

from db import get_db
from config import save_uploaded_pdf

bp=Blueprint("materials", __name__)

@bp.route(
    "/api/materials",
    methods=["POST"]
)
def save_material():
    db = None
    cursor = None

    try:
        # -------------------------------------------------
        # MULTIPART PDF UPLOAD (preferred)
        # -------------------------------------------------
        if request.files:
            pdf = (
                request.files.get("file")
                or request.files.get("pdf")
                or request.files.get("material")
            )

            user_email = (
                request.form.get("user_email")
                or ""
            ).strip().lower()

            if not user_email:
                return jsonify({
                    "message": "User email is required."
                }), 400

            if not pdf:
                return jsonify({
                    "message": "PDF file is required."
                }), 400

            name = (
                request.form.get("name")
                or pdf.filename
                or "Study Material.pdf"
            ).strip()

            db = get_db()
            cursor = db.cursor(dictionary=True)

            cursor.execute(
                """
                SELECT id, name, email, role
                FROM users
                WHERE email = %s
                LIMIT 1
                """,
                (user_email,)
            )

            user = cursor.fetchone()

            if not user:
                return jsonify({
                    "message": "User account not found."
                }), 404

            # Create the DB row first so we have a stable material id.
            cursor.execute(
                """
                INSERT INTO materials
                (
                    user_id,
                    user_email,
                    name,
                    size,
                    type,
                    uploaded_at
                )
                VALUES (%s, %s, %s, %s, %s, NOW())
                """,
                (
                    user["id"],
                    user_email,
                    name,
                    "0",
                    "application/pdf"
                )
            )

            material_id = cursor.lastrowid

            try:
                pdf_path = save_uploaded_pdf(
                    pdf,
                    user["id"],
                    material_id
                )
            except Exception:
                db.rollback()
                raise

            actual_size = pdf_path.stat().st_size

            cursor.execute(
                """
                UPDATE materials
                SET size = %s,
                    type = 'application/pdf',
                    uploaded_at = NOW()
                WHERE id = %s
                  AND user_id = %s
                """,
                (
                    str(actual_size),
                    material_id,
                    user["id"]
                )
            )

            db.commit()

            return jsonify({
                "message": "PDF uploaded successfully.",
                "material": {
                    "id": material_id,
                    "user_id": user["id"],
                    "user_email": user_email,
                    "name": name,
                    "size": str(actual_size),
                    "type": "application/pdf",
                    "uploaded_at": datetime.now().isoformat()
                }
            }), 201

        # -------------------------------------------------
        # BACKWARDS-COMPATIBLE JSON METADATA MODE
        # -------------------------------------------------
        data = request.get_json(silent=True)

        if not data:
            return jsonify({
                "message": "Upload a PDF using multipart/form-data."
            }), 415

        user_email = (
            data.get("user_email") or ""
        ).strip().lower()

        name = (
            data.get("name") or ""
        ).strip()

        size = (
            data.get("size") or ""
        ).strip()

        file_type = (
            data.get("type")
            or "application/pdf"
        ).strip()

        if not user_email:
            return jsonify({
                "message": "User email is required."
            }), 400

        if not name:
            return jsonify({
                "message": "Material name is required."
            }), 400

        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT id, name, email, role
            FROM users
            WHERE email = %s
            LIMIT 1
            """,
            (user_email,)
        )

        user = cursor.fetchone()

        if not user:
            return jsonify({
                "message": "User account not found."
            }), 404

        cursor.execute(
            """
            INSERT INTO materials
            (
                user_id,
                user_email,
                name,
                size,
                type,
                uploaded_at
            )
            VALUES (%s, %s, %s, %s, %s, NOW())
            """,
            (
                user["id"],
                user_email,
                name,
                size,
                file_type
            )
        )

        material_id = cursor.lastrowid
        db.commit()

        return jsonify({
            "message": (
                "Material metadata saved. "
                "Upload the actual PDF to enable AI reading."
            ),
            "material": {
                "id": material_id,
                "user_id": user["id"],
                "user_email": user_email,
                "name": name,
                "size": size,
                "type": file_type
            }
        }), 201

    except Error as error:
        if db:
            try:
                db.rollback()
            except Exception:
                pass

        print("Material database error:", error)

        return jsonify({
            "message": "Database error while saving material.",
            "error": str(error)
        }), 500

    except ValueError as error:
        if db:
            try:
                db.rollback()
            except Exception:
                pass

        return jsonify({
            "message": str(error)
        }), 400

    except Exception as error:
        if db:
            try:
                db.rollback()
            except Exception:
                pass

        print("Material save error:", error)

        return jsonify({
            "message": "Unable to save material.",
            "error": str(error)
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
    "/api/materials",
    methods=["GET"]
)
def get_materials():

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

                "materials":
                    [],

                "count":
                    0

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
                    "User account not found.",

                "materials":
                    [],

                "count":
                    0

            }), 404

        user_id = user["id"]

        cursor.execute(
            """
            SELECT
                id,
                user_id,
                user_email,
                name,
                size,
                type,
                uploaded_at,
                created_at
            FROM materials
            WHERE user_id = %s
            ORDER BY id DESC
            """,
            (user_id,)
        )

        materials = cursor.fetchall()

        cursor.close()
        db.close()

        for material in materials:

            if material.get("uploaded_at"):

                material["uploaded_at"] = (
                    material["uploaded_at"].isoformat()
                )

            if material.get("created_at"):

                material["created_at"] = (
                    material["created_at"].isoformat()
                )

        return jsonify({

            "message":
                "Materials loaded successfully.",

            "user_id":
                user_id,

            "user_email":
                user_email,

            "count":
                len(materials),

            "materials":
                materials

        }), 200

    except Error as error:

        print(
            "Get materials database error:",
            error
        )

        return jsonify({

            "message":
                "Database error while loading materials.",

            "materials":
                [],

            "count":
                0

        }), 500

    except Exception as error:

        print(
            "Get materials error:",
            error
        )

        return jsonify({

            "message":
                "Unable to load materials.",

            "materials":
                [],

            "count":
                0

        }), 500


@bp.route(
    "/api/materials/count",
    methods=["GET"]
)
def material_count():

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

                "count":
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
                    "User account not found.",

                "count":
                    0

            }), 404

        cursor.execute(
            """
            SELECT
                COUNT(*) AS total
            FROM materials
            WHERE user_id = %s
            """,
            (user["id"],)
        )

        result = cursor.fetchone()

        count = int(
            result["total"] or 0
        )

        cursor.close()
        db.close()

        return jsonify({

            "user_id":
                user["id"],

            "user_email":
                user_email,

            "count":
                count

        }), 200

    except Error as error:

        print(
            "Material count database error:",
            error
        )

        return jsonify({

            "message":
                "Database error.",

            "count":
                0

        }), 500

    except Exception as error:

        print(
            "Material count error:",
            error
        )

        return jsonify({

            "message":
                "Unable to get material count.",

            "count":
                0

        }), 500


@bp.route(
    "/api/materials/<int:material_id>",
    methods=["DELETE"]
)
def delete_material(material_id):

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
                    "User account not found."

            }), 404

        cursor.execute(
            """
            DELETE FROM materials
            WHERE id = %s
            AND user_id = %s
            """,
            (
                material_id,
                user["id"]
            )
        )

        deleted_rows = cursor.rowcount

        db.commit()

        cursor.close()
        db.close()

        if deleted_rows == 0:

            return jsonify({

                "message":
                    "Material not found."

            }), 404

        return jsonify({

            "message":
                "Material deleted successfully.",

            "material_id":
                material_id

        }), 200

    except Error as error:

        print(
            "Delete material database error:",
            error
        )

        return jsonify({

            "message":
                "Database error."

        }), 500

    except Exception as error:

        print(
            "Delete material error:",
            error
        )

        return jsonify({

            "message":
                "Unable to delete material."

        }), 500


@bp.route(
    "/api/materials/reset",
    methods=["DELETE"]
)
def reset_materials():

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
                    "User account not found."

            }), 404

        cursor.execute(
            """
            DELETE FROM materials
            WHERE user_id = %s
            """,
            (user["id"],)
        )

        deleted_count = cursor.rowcount

        db.commit()

        cursor.close()
        db.close()

        return jsonify({

            "message":
                "All study materials removed.",

            "deleted_count":
                deleted_count

        }), 200

    except Error as error:

        print(
            "Reset materials database error:",
            error
        )

        return jsonify({

            "message":
                "Database error while resetting materials."

        }), 500

    except Exception as error:

        print(
            "Reset materials error:",
            error
        )

        return jsonify({

            "message":
                "Unable to reset materials."

        }), 500

