"""MySQL connection helper."""

import mysql.connector
from flask import current_app

from config import DB_CONFIG


def get_db():
    return mysql.connector.connect(
        host=DB_CONFIG["host"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        database=DB_CONFIG["database"],
    )
