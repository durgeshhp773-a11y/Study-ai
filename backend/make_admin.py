"""Interactive helper to grant/remove admin access without exposing passwords in shell history."""

from getpass import getpass
from werkzeug.security import generate_password_hash

from db import get_db
from services.admin_service import ensure_admin_tables


def main():
    ensure_admin_tables(get_db)
    email = input("User email: ").strip().lower()
    if not email:
        raise SystemExit("Email is required.")

    db = get_db()
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id,name,email,role FROM users WHERE email=%s LIMIT 1",
            (email,)
        )
        user = cursor.fetchone()
        if not user:
            raise SystemExit("No user account exists with that email.")

        print(f"Account: {user['name']} <{user['email']}>")
        current = str(user.get("role") or "client").lower()
        print(f"Current role: {current}")
        new_role = input("Role [admin/client]: ").strip().lower() or current

        if new_role == "admin":
            password = getpass("New admin password: ")
            confirm = getpass("Confirm admin password: ")
            if len(password) < 6:
                raise SystemExit("Admin password must contain at least 6 characters.")
            if password != confirm:
                raise SystemExit("Admin passwords do not match.")
            cursor.execute(
                "UPDATE users SET role='admin', admin_password_hash=%s WHERE id=%s",
                (generate_password_hash(password), user["id"])
            )
            db.commit()
            print("Admin access enabled.")
            print("Client password was NOT changed.")

        elif new_role == "client":
            cursor.execute(
                "UPDATE users SET role='client', admin_password_hash=NULL WHERE id=%s",
                (user["id"],)
            )
            db.commit()
            print("Admin access removed. Client password remains unchanged.")

        else:
            raise SystemExit("Role must be admin or client.")
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    main()
