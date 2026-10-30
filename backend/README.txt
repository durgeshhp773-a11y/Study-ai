StudyAI Modular Backend

Folder structure:
backend/
  app.py
  config.py
  db.py
  routes/auth.py
  routes/materials.py
  routes/study.py
  routes/ai.py
  routes/admin.py
  services/admin_service.py
  uploads/materials/

Run:
  python app.py

Frontend can be opened directly from File Explorer using file:// URLs.
Backend API remains at http://localhost:5000.

Admin role:
  UPDATE users SET role='admin' WHERE email='your-admin-email@example.com';

SEPARATE CLIENT / ADMIN PASSWORDS
--------------------------------
users.password_hash is the CLIENT password.
users.admin_password_hash is the ADMIN password. They are independent.

Normal login endpoint:
  POST /api/auth/login
  - validates only password_hash
  - never grants admin session access

Admin login endpoint:
  POST /api/admin/login
  - requires role='admin'
  - validates only admin_password_hash
  - returns a separate admin token

Grant or remove admin access interactively:
  python make_admin.py

The helper asks for the email and a new admin password. The existing client password is not changed.

