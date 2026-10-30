📌 Project Overview

StudyAI is a full-stack web application designed to make learning and study management easier and more organized. It provides a platform where users can access AI-powered study features, manage their profiles, track their learning progress, and organize their academic activities.

The application includes a user interface, backend services, authentication-related pages, and an administrative dashboard.

✨ Features

👤 User Management

1.  User registration and login pages
2.  OTP verification page
3.  Forgot-password page
4.  User profile page

User Profile Management

🤖 AI-Powered Learning

1.  AI study-plan page
2.  AI question-generation page

Personalized Learning Assistance

📊 Study Management

1.  Student dashboard
2.  Learning progress page
3.  Notifications page
4.  Help page

🔐 Admin Panel

Admin Login

1.  Separate admin login page
2.  Admin dashboard page

🛠️ Technologies Used

 Technology / Component              Purpose
  ----------------------------------- -----------------------------------
  Python                              Backend development

  HTML5                               Frontend page structure

  CSS3                                Styling and layout

  JavaScript                          Frontend interactions

  Python packages                     Backend dependencies (see
                                      requirements.txt)

  Database                            Data storage; confirm the specific
                                      database from the project
                                      configuration

📂 Project Structure

StudyAI/
│
├── backend/
│   ├── routes/
│   ├── services/
│   ├── app.py
│   ├── config.py
│   ├── db.py
│   ├── make_admin.py
│   └── requirements.txt
│
├── frontend/
│   ├── admin.html
│   ├── admin-login.html
│   ├── aiplan.html
│   ├── aiquest6.html
│   ├── dashboard.html
│   ├── login.html
│   ├── register.html
│   ├── profile.html
│   └── Other frontend pages
│
├── .gitignore
└── README.md

⚙️ Installation & Setup

Prerequisites

1.  Python 3.x
2.  pip (Python package manager)
3.  Git
4.  A modern web browser
5.  A code editor such as Visual Studio Code (recommended)

Step 1: Clone the Repository

git clone https://github.com/YOUR_USERNAME/StudyAI.git

Step 2: Navigate to Project Directory

cd StudyAI

Step 3: Set Up Virtual Environment

python -m venv venv

Activate the environment:

Windows:

venv\Scripts\activate

Step 4: Install Dependencies

cd backend
pip install -r requirements.txt

Step 5: Configure Environment Variables

Create a .env file inside the backend directory and configure the required environment variables according to your local setup.

Never upload passwords, API keys, or secret credentials to GitHub.

Step 6: Run the Backend

python app.py

Use the local address displayed by the application to access the web interface. Database and frontend configuration may be required depending on the project setup.

📸 Screenshots

Application screenshots can be added here to demonstrate the user interface and project functionality.

🎯 Project Objective

The main objective of StudyAI is to provide an organized and interactive learning environment by combining study management features with AI-powered learning assistance.

🚀 Future Enhancements

Improved AI-based recommendations

Advanced learning analytics

Enhanced user experience

Additional study management tools

More personalized learning features

👨‍💻 Project Information

Project Name: StudyAI
Project Type: Full Stack Web Application
Backend: Python
Frontend: HTML, CSS, JavaScript

📄 License

This project is developed for educational purposes.
