"""StudyAI Flask application entry point."""

from flask import Flask, jsonify
from flask_cors import CORS
from mysql.connector import Error

from db import get_db
from routes.auth import bp as auth_bp
from routes.materials import bp as materials_bp
from routes.study import bp as study_bp
from routes.ai import bp as ai_bp
from routes.admin import bp as admin_bp
from services.admin_service import ensure_admin_tables

app=Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

app.register_blueprint(auth_bp)
app.register_blueprint(materials_bp)
app.register_blueprint(study_bp)
app.register_blueprint(ai_bp)
app.register_blueprint(admin_bp)

# Create the small admin support tables once at startup.
try:
    ensure_admin_tables(get_db)
except Exception as startup_error:
    print("Admin support-table initialization skipped:", startup_error)

@app.get("/")
def home():
    return "StudyAI Backend is Running!"

@app.get("/api/test")
def test():
    try:
        db=get_db(); c=db.cursor(); c.execute("SELECT DATABASE()")
        result=c.fetchone()[0]; c.close(); db.close()
        return jsonify({"status":"connected","database":result})
    except Error as error:
        return jsonify({"status":"error","message":str(error)}),500

if __name__=="__main__":
    app.run(host="127.0.0.1",port=5000,debug=True,use_reloader=False)
