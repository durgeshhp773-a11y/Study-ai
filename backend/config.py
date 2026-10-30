"""StudyAI shared configuration and reusable backend helpers."""

import json
import os
import random
import secrets
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request as UrlRequest, urlopen

from google import genai
from dotenv import load_dotenv
from google.genai import types
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
MATERIAL_UPLOAD_DIR = BASE_DIR / "uploads" / "materials"
MATERIAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_PDF_MIME_TYPES = {
    "application/pdf",
    "application/x-pdf",
}
MAX_PDF_SIZE = 25 * 1024 * 1024

DB_CONFIG = {
    "host": os.environ.get("MYSQL_HOST", "localhost"),
    "port": int(os.environ.get("MYSQL_PORT", "3306")),
    "user": os.environ.get("MYSQL_USER", "root"),
    "password": os.environ.get("MYSQL_PASSWORD", ""),
    "database": os.environ.get("MYSQL_DATABASE", "studyai"),
}
SMTP_EMAIL = os.environ.get("STUDYAI_SMTP_EMAIL", "").strip()
SMTP_PASSWORD = os.environ.get("STUDYAI_SMTP_PASSWORD", "").strip()
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

PASSWORD_RESET_VERIFIED = {}
PASSWORD_RESET_VERIFIED_MINUTES = 10

GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_TIMEOUT_MS = 10000
GEMINI_RETRY_ATTEMPTS = 1

def material_pdf_path(user_id, material_id):
    user_dir = MATERIAL_UPLOAD_DIR / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir / f"{int(material_id)}.pdf"


def save_uploaded_pdf(file_storage, user_id, material_id):
    if not file_storage or not file_storage.filename:
        raise ValueError("PDF file is required.")

    content_type = (
        file_storage.mimetype or ""
    ).strip().lower()

    filename = file_storage.filename.lower()
    if content_type not in ALLOWED_PDF_MIME_TYPES and not filename.endswith(".pdf"):
        raise ValueError("Only PDF files are supported.")

    path = material_pdf_path(user_id, material_id)

    # Stream to disk and enforce the size limit.
    total = 0
    with path.open("wb") as output:
        while True:
            chunk = file_storage.stream.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_PDF_SIZE:
                output.close()
                try:
                    path.unlink()
                except OSError:
                    pass
                raise ValueError("PDF is too large. Maximum size is 25 MB.")
            output.write(chunk)

    if total == 0:
        try:
            path.unlink()
        except OSError:
            pass
        raise ValueError("The uploaded PDF is empty.")

    return path


def get_gemini_client():

    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:

        raise RuntimeError(
            "Gemini API key is not configured. "
            "Please set GEMINI_API_KEY first."
        )

    retry_options = types.HttpRetryOptions(
        attempts=GEMINI_RETRY_ATTEMPTS,
        initial_delay=0.1,
        max_delay=0.1,
        exp_base=1.0,
        jitter=0.0
    )

    http_options = types.HttpOptions(
        timeout=GEMINI_TIMEOUT_MS,
        retry_options=retry_options
    )

    return genai.Client(
        api_key=api_key,
        http_options=http_options
    )


def get_selected_material(
    cursor,
    user_id,
    material_id
):

    try:

        material_id = int(
            material_id
        )

    except (
        TypeError,
        ValueError
    ):

        raise ValueError(
            "A valid PDF material_id is required."
        )

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
        WHERE id = %s
          AND user_id = %s
        LIMIT 1
        """,
        (
            material_id,
            user_id
        )
    )

    material = cursor.fetchone()

    if not material:

        raise LookupError(
            "Selected study material was not found "
            "for this account."
        )

    pdf_path = material_pdf_path(
        user_id,
        material_id
    )

    if (
        not pdf_path.exists()
        or pdf_path.stat().st_size == 0
    ):

        raise FileNotFoundError(
            "The selected PDF file is not stored on the server. "
            "Please upload the PDF again from Study Materials."
        )

    return material, pdf_path


def clean_ai_json(text):

    text = (
        text
        or ""
    ).strip()

    if text.startswith(
        "```json"
    ):

        text = text[7:]

    elif text.startswith(
        "```"
    ):

        text = text[3:]

    if text.endswith(
        "```"
    ):

        text = text[:-3]

    return text.strip()


def generate_from_local_pdf(
    client,
    model,
    pdf_path,
    prompt,
    max_output_tokens=1800
):

    pdf_path = Path(pdf_path)

    if not pdf_path.exists():

        raise FileNotFoundError(
            "Selected PDF file was not found."
        )

    try:

        pdf_bytes = pdf_path.read_bytes()

        print(
            "Gemini PDF -> inline request:",
            pdf_path.name,
            f"({len(pdf_bytes)} bytes)"
        )

        pdf_part = types.Part.from_bytes(
            data=pdf_bytes,
            mime_type="application/pdf"
        )

        response = client.models.generate_content(

            model=model,

            contents=[
                prompt,
                pdf_part
            ],

            config=types.GenerateContentConfig(

                response_mime_type="application/json",

                max_output_tokens=max_output_tokens,

                thinking_config=types.ThinkingConfig(
                    thinking_level="low"
                )

            )
        )

        print(
            "Gemini AI -> success"
        )

        return response

    except Exception as error:

        error_text = str(error)

        print(
            "\n========== FAST GEMINI ERROR =========="
        )
        print(error_text)
        print(
            "=======================================\n"
        )

        if (
            "503" in error_text
            or "UNAVAILABLE" in error_text
            or "high demand" in error_text
            or "overloaded" in error_text
        ):

            raise RuntimeError(
                "Gemini AI is temporarily busy. "
                "Please try again in a few seconds."
            ) from error

        if (
            "timeout" in error_text.lower()
            or "timed out" in error_text.lower()
            or "deadline" in error_text.lower()
            or "read operation timed out" in error_text.lower()
        ):

            raise RuntimeError(
                "Gemini AI took too long to respond. "
                "Please try again."
            ) from error

        raise


def mark_password_reset_verified(email):
    PASSWORD_RESET_VERIFIED[email] = (
        datetime.now()
        + timedelta(minutes=PASSWORD_RESET_VERIFIED_MINUTES)
    )


def is_password_reset_verified(email):
    expires_at = PASSWORD_RESET_VERIFIED.get(email)

    if not expires_at:
        return False

    if datetime.now() > expires_at:
        PASSWORD_RESET_VERIFIED.pop(email, None)
        return False

    return True


def clear_password_reset_verified(email):
    PASSWORD_RESET_VERIFIED.pop(email, None)


def _send_email(message):
    """
    Send Gmail mail reliably.

    Primary connection:
        smtp.gmail.com:465 using implicit SSL

    Fallback connection:
        smtp.gmail.com:587 using STARTTLS

    The fallback keeps the existing Gmail configuration usable
    on networks that block one of the SMTP ports.
    """

    errors = []

    # ---------------------------------------------------------
    # Method 1: Gmail SSL / port 465
    # ---------------------------------------------------------
    try:

        with smtplib.SMTP_SSL(
            "smtp.gmail.com",
            465,
            timeout=30
        ) as server:

            server.login(
                SMTP_EMAIL,
                SMTP_PASSWORD
            )

            server.send_message(message)

        return True

    except Exception as error:
        errors.append(
            f"SSL/465: {repr(error)}"
        )

    # ---------------------------------------------------------
    # Method 2: Gmail STARTTLS / port 587
    # ---------------------------------------------------------
    try:

        with smtplib.SMTP(
            "smtp.gmail.com",
            587,
            timeout=30
        ) as server:

            server.ehlo()

            server.starttls()

            server.ehlo()

            server.login(
                SMTP_EMAIL,
                SMTP_PASSWORD
            )

            server.send_message(message)

        return True

    except Exception as error:
        errors.append(
            f"STARTTLS/587: {repr(error)}"
        )

    print(
        "Email sending error:",
        " | ".join(errors)
    )

    return False


def send_otp_email(email, otp):

    if not SMTP_EMAIL or not SMTP_PASSWORD:

        print()
        print("=" * 55)
        print("STUDYAI OTP - LOCAL TEST MODE")
        print("Email :", email)
        print("OTP   :", otp)
        print("=" * 55)
        print()

        return True

    message = EmailMessage()

    message["Subject"] = (
        "StudyAI - Email Verification OTP"
    )

    message["From"] = SMTP_EMAIL
    message["To"] = email

    message.set_content(
        f"""
Hello,

Your StudyAI email verification OTP is:

{otp}

This OTP is valid for 10 minutes.

If you did not create a StudyAI account,
please ignore this email.

Regards,
StudyAI Team
"""
    )

    return _send_email(message)


def send_password_reset_otp_email(email, otp):

    if not SMTP_EMAIL or not SMTP_PASSWORD:

        print()
        print("=" * 55)
        print("STUDYAI PASSWORD RESET OTP - LOCAL TEST MODE")
        print("Email :", email)
        print("OTP   :", otp)
        print("=" * 55)
        print()

        return True

    message = EmailMessage()

    message["Subject"] = (
        "StudyAI - Password Reset OTP"
    )

    message["From"] = SMTP_EMAIL
    message["To"] = email

    message.set_content(
        f"""
Hello,

Your StudyAI password reset OTP is:

{otp}

This OTP is valid for 10 minutes.

If you did not request a password reset,
please ignore this email.

Regards,
StudyAI Team
"""
    )

    return _send_email(message)


def generate_token():

    return secrets.token_urlsafe(32)


def verify_google_id_token(id_token):

    if not GOOGLE_CLIENT_ID:
        raise RuntimeError(
            "GOOGLE_CLIENT_ID is not configured on the server."
        )

    if not id_token:
        raise ValueError("Google credential is required.")

    # Verify the signed Google token through Google's tokeninfo
    # endpoint, then validate the audience / issuer / expiry.
    request_url = (
        "https://oauth2.googleapis.com/tokeninfo?"
        + f"id_token={id_token}"
    )

    req = UrlRequest(
        request_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "StudyAI/1.0"
        },
        method="GET"
    )

    try:
        with urlopen(req, timeout=8) as response:
            raw = response.read().decode("utf-8")
    except Exception as error:
        raise ValueError(
            "Google token verification failed."
        ) from error

    try:
        claims = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(
            "Google returned an invalid token response."
        ) from error

    if claims.get("aud") != GOOGLE_CLIENT_ID:
        raise ValueError("Google token audience is invalid.")

    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise ValueError("Google token issuer is invalid.")

    try:
        expires_at = int(
            claims.get("exp", "0")
        )
    except (TypeError, ValueError):
        raise ValueError("Google token expiry is invalid.")

    if expires_at <= int(datetime.now().timestamp()):
        raise ValueError("Google token has expired.")

    email = (
        claims.get("email")
        or ""
    ).strip().lower()

    name = (
        claims.get("name")
        or claims.get("given_name")
        or ""
    ).strip()

    email_verified = (
        str(
            claims.get("email_verified", "")
        ).lower()
        == "true"
    )

    if not email or not email_verified:
        raise ValueError(
            "Google account email is missing or not verified."
        )

    if not name:
        name = email.split("@")[0]

    return {
        "email": email,
        "name": name[:255]
    }

