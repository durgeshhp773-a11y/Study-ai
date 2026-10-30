"""Gemini-powered study plan, question generator and support routes."""

from flask import Blueprint, jsonify, request
from mysql.connector import Error
import json
import os
import traceback
from google import genai

from db import get_db
from config import GEMINI_MODEL, get_gemini_client, get_selected_material, clean_ai_json, generate_from_local_pdf

bp=Blueprint("ai", __name__)

@bp.route(
    "/api/study-plans/generate",
    methods=["POST"]
)
def generate_study_plan():
    db = None
    cursor = None

    try:
        data = request.get_json(silent=True) or {}

        user_email = (
            data.get("user_email") or ""
        ).strip().lower()

        goal = (
            data.get("goal") or ""
        ).strip()

        preference = (
            data.get("preference") or "Balanced"
        ).strip()

        material_id = data.get("material_id")

        try:
            hours_per_day = float(
                data.get("hours_per_day", 0)
            )
        except (TypeError, ValueError):
            hours_per_day = 0

        if not user_email:
            return jsonify({
                "message": "User email is required."
            }), 400

        if not goal:
            return jsonify({
                "message": "Study goal is required."
            }), 400

        if hours_per_day <= 0 or hours_per_day > 24:
            return jsonify({
                "message": (
                    "Daily study time must be greater than 0 "
                    "and cannot exceed 24 hours."
                )
            }), 400

        if material_id in (None, "", "null"):
            return jsonify({
                "message": (
                    "Please select a PDF before generating "
                    "an AI study plan."
                )
            }), 400

        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT id, name, email
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

        try:
            material, pdf_path = get_selected_material(
                cursor,
                user["id"],
                material_id
            )
        except (ValueError, LookupError, FileNotFoundError) as error:
            return jsonify({
                "message": str(error)
            }), 400

        total_minutes = max(
            30,
            int(hours_per_day * 60)
        )

        client = get_gemini_client()

        prompt = f"""
You are StudyAI, an intelligent personalized study planner.

You are given the student's ACTUAL SELECTED PDF as a document.
Read the PDF carefully and build the plan from the topics,
chapters, concepts and structure that are actually present in it.

STUDENT NAME:
{user["name"]}

SELECTED PDF:
{material["name"]}

STUDY GOAL:
{goal}

DAILY STUDY TIME:
{hours_per_day} hours ({total_minutes} minutes)

STUDY PREFERENCE:
{preference}

STRICT PDF RULES:
1. Use the selected PDF as the primary source.
2. Do not invent chapters, topics or concepts that are not supported
   by the PDF.
3. Prioritize the actual topics/sections in the PDF.
4. If the PDF has chapters or sections, use them naturally.
5. If the PDF is short, do not artificially invent extra syllabus.
6. If something is unclear or absent from the PDF, say so in the plan
   rather than pretending it exists.

PLAN RULES:
1. Create exactly 7 days.
2. Every day must contain at least one study session.
3. Keep the total duration per day at or below {total_minutes} minutes.
4. Include learning, revision, practice and self-testing where useful.
5. Do not make every day identical.
6. Make the sequence progressively useful across the week.
7. Use realistic session times and durations.
8. Keep descriptions concise and actionable.
9. Every session must contain:
   time, title, description, duration_minutes, priority.
10. priority must be exactly High, Medium, or Low.
11. Return ONLY valid JSON. No Markdown. No code fences.

Return exactly this structure:
{{
  "type": "personalized_study_plan",
  "generated_by": "StudyAI Gemini AI",
  "summary": "short personalized summary based on the selected PDF",
  "goal": "{goal}",
  "preference": "{preference}",
  "hours_per_day": {hours_per_day},
  "material_id": {int(material_id)},
  "material": "{material["name"]}",
  "days": [
    {{
      "day": "Day 1",
      "sessions": [
        {{
          "time": "09:00 AM",
          "title": "PDF topic/session",
          "description": "Short practical description",
          "duration_minutes": 60,
          "priority": "High"
        }}
      ]
    }}
  ]
}}
"""

        response = generate_from_local_pdf(
            client,
            GEMINI_MODEL,
            pdf_path,
            prompt,
            max_output_tokens=1800
        )

        ai_text = clean_ai_json(
            response.text
        )

        if not ai_text:
            raise RuntimeError(
                "Gemini returned an empty study plan."
            )

        try:
            plan_data = json.loads(ai_text)
        except json.JSONDecodeError as error:
            print(
                "\n================ GEMINI PLAN JSON ERROR ================\n"
            )
            print(ai_text)
            print(
                "\n==========================================================\n"
            )
            raise RuntimeError(
                "Gemini returned invalid study-plan JSON."
            ) from error

        if not isinstance(plan_data, dict):
            raise RuntimeError(
                "Gemini plan must be a JSON object."
            )

        days = plan_data.get("days")

        if not isinstance(days, list):
            raise RuntimeError(
                "Gemini response is missing a valid days list."
            )

        normalized_days = []

        for index, day in enumerate(
            days[:7],
            start=1
        ):
            if not isinstance(day, dict):
                continue

            sessions = day.get("sessions", [])

            if not isinstance(sessions, list):
                sessions = []

            normalized_sessions = []

            day_total = 0

            for session in sessions:
                if not isinstance(session, dict):
                    continue

                try:
                    duration = int(
                        session.get(
                            "duration_minutes",
                            0
                        )
                    )
                except (TypeError, ValueError):
                    duration = 0

                if duration <= 0:
                    continue

                # Enforce daily limit server-side.
                remaining = total_minutes - day_total
                if remaining <= 0:
                    break

                duration = min(
                    duration,
                    remaining
                )

                priority = (
                    session.get("priority")
                    or "Medium"
                )

                if priority not in (
                    "High",
                    "Medium",
                    "Low"
                ):
                    priority = "Medium"

                normalized_sessions.append({
                    "time": str(
                        session.get("time") or ""
                    ),
                    "title": str(
                        session.get("title")
                        or "Study Session"
                    ),
                    "description": str(
                        session.get("description")
                        or "Study the selected PDF topic."
                    ),
                    "duration_minutes": duration,
                    "priority": priority
                })

                day_total += duration

            if not normalized_sessions:
                normalized_sessions.append({
                    "time": "Flexible",
                    "title": "PDF Revision",
                    "description": (
                        "Review the selected PDF and revise "
                        "the most important concepts."
                    ),
                    "duration_minutes": min(
                        30,
                        total_minutes
                    ),
                    "priority": "Medium"
                })

            normalized_days.append({
                "day": str(
                    day.get("day")
                    or f"Day {index}"
                ),
                "sessions": normalized_sessions
            })

        if len(normalized_days) < 7:
            raise RuntimeError(
                "Gemini did not generate all 7 study days."
            )

        plan_data["days"] = normalized_days
        plan_data["type"] = "personalized_study_plan"
        plan_data["generated_by"] = "StudyAI Gemini AI"
        plan_data["goal"] = goal
        plan_data["preference"] = preference
        plan_data["hours_per_day"] = hours_per_day
        plan_data["material_id"] = int(material_id)
        plan_data["material"] = material["name"]

        if not plan_data.get("summary"):
            plan_data["summary"] = (
                "A personalized 7-day plan generated from "
                "the selected PDF."
            )

        cursor.execute(
            """
            INSERT INTO study_plans
            (
                user_id,
                user_email,
                goal,
                hours_per_day,
                plan_data,
                created_at,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
            """,
            (
                user["id"],
                user["email"],
                goal,
                hours_per_day,
                json.dumps(
                    plan_data,
                    ensure_ascii=False
                )
            )
        )

        db.commit()

        return jsonify({
            "message":
                "AI study plan generated successfully.",
            "plan":
                plan_data
        }), 201

    except Error as error:
        if db:
            try:
                db.rollback()
            except Exception:
                pass

        print(
            "\n================ AI PLAN DATABASE ERROR ================\n"
        )
        print(error)

        return jsonify({
            "message":
                "Database error while generating study plan.",
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
        traceback.print_exc()

        return jsonify({
            "message":
                "Unable to generate AI study plan.",
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
    "/api/question-generator/generate",
    methods=["POST"]
)
def generate_ai_questions():
    db = None
    cursor = None

    try:
        data = request.get_json(silent=True) or {}

        user_email = (
            data.get("user_email") or ""
        ).strip().lower()

        question_type = (
            data.get("question_type")
            or data.get("type")
            or "mcq"
        ).strip().lower()

        difficulty = (
            data.get("difficulty")
            or "medium"
        ).strip().lower()

        material_id = data.get("material_id")

        try:
            count = int(
                data.get("count", 5)
            )
        except (TypeError, ValueError):
            count = 5

        topic = (
            data.get("topic") or ""
        ).strip()

        if not user_email:
            return jsonify({
                "message": "User email is required."
            }), 400

        if material_id in (None, "", "null"):
            return jsonify({
                "message": (
                    "Please select a PDF before generating "
                    "questions."
                )
            }), 400

        allowed_types = [
            "mcq",
            "truefalse",
            "short",
            "mixed"
        ]

        if question_type not in allowed_types:
            return jsonify({
                "message": "Invalid question type."
            }), 400

        allowed_difficulties = [
            "easy",
            "medium",
            "hard"
        ]

        if difficulty not in allowed_difficulties:
            return jsonify({
                "message": "Invalid difficulty."
            }), 400

        if count < 1 or count > 20:
            return jsonify({
                "message":
                    "Question count must be between 1 and 20."
            }), 400

        db = get_db()
        cursor = db.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT id, name, email
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

        try:
            material, pdf_path = get_selected_material(
                cursor,
                user["id"],
                material_id
            )
        except (ValueError, LookupError, FileNotFoundError) as error:
            return jsonify({
                "message": str(error)
            }), 400

        if question_type == "mcq":
            type_instruction = """
Generate multiple-choice questions.
Each question MUST have exactly 4 options:
A, B, C and D.
Each question must have:
question, type, options, correct_answer, explanation.
"""

        elif question_type == "truefalse":
            type_instruction = """
Generate True/False questions.
Each question MUST have:
question, type, options ["True", "False"],
correct_answer, explanation.
"""

        elif question_type == "short":
            type_instruction = """
Generate short-answer questions.
Each question MUST have:
question, type, correct_answer, explanation.
Do NOT generate options.
"""

        else:
            type_instruction = """
Generate a mixed set of MCQ, True/False and Short Answer.
For MCQ use exactly 4 options.
For True/False use True and False.
For Short Answer do not use options.
Every question must have:
question, type, correct_answer, explanation.
"""

        client = get_gemini_client()

        prompt = f"""
You are StudyAI Question Generator.

The user selected the PDF "{material["name"]}".
Read the ACTUAL PDF carefully and generate questions ONLY
from information supported by that PDF.

QUESTION COUNT:
{count}

QUESTION TYPE:
{question_type}

DIFFICULTY:
{difficulty}

OPTIONAL TOPIC:
{topic if topic else "Use the whole selected PDF."}

STRICT PDF RULES:
1. The selected PDF is the primary and authoritative study source.
2. Do not invent facts, chapters, formulas, definitions or examples
   that are not supported by the PDF.
3. Questions must be answerable from the selected PDF.
4. If an optional topic is provided, focus on that topic only when
   the topic exists in the PDF.
5. Avoid duplicate questions.
6. Use clear educational wording.
7. Match the requested difficulty.
8. Every question must have a correct answer and useful explanation.
9. Return ONLY valid JSON. No Markdown. No code fences.
10. Return exactly {count} questions.

QUESTION TYPE INSTRUCTIONS:
{type_instruction}

RETURN EXACTLY THIS JSON STRUCTURE:
{{
  "questions": [
    {{
      "number": 1,
      "type": "mcq",
      "question": "Question text",
      "options": [
        "A. Option 1",
        "B. Option 2",
        "C. Option 3",
        "D. Option 4"
      ],
      "correct_answer": "A. Option 1",
      "explanation": "Explanation based on the PDF"
    }}
  ]
}}
"""

        response = generate_from_local_pdf(
            client,
            GEMINI_MODEL,
            pdf_path,
            prompt,
            max_output_tokens=1400
        )

        ai_text = clean_ai_json(
            response.text
        )

        if not ai_text:
            raise RuntimeError(
                "Gemini returned an empty question response."
            )

        try:
            result = json.loads(ai_text)
        except json.JSONDecodeError as error:
            print(
                "\n================ QUESTION JSON ERROR ================\n"
            )
            print(ai_text)
            print(
                "\n=======================================================\n"
            )
            raise RuntimeError(
                "Gemini returned invalid question JSON."
            ) from error

        questions = result.get(
            "questions",
            []
        )

        if not isinstance(questions, list):
            raise RuntimeError(
                "Invalid questions format."
            )

        normalized_questions = []

        for index, question in enumerate(
            questions[:count],
            start=1
        ):
            if not isinstance(question, dict):
                continue

            q_type = (
                question.get(
                    "type",
                    question_type
                )
                or question_type
            ).strip().lower()

            q_text = (
                question.get(
                    "question",
                    ""
                )
                or ""
            ).strip()

            answer = (
                question.get(
                    "correct_answer",
                    ""
                )
                or ""
            ).strip()

            explanation = (
                question.get(
                    "explanation",
                    ""
                )
                or ""
            ).strip()

            if not q_text or not answer:
                continue

            options = question.get(
                "options",
                []
            )

            if not isinstance(
                options,
                list
            ):
                options = []

            normalized_questions.append({
                "number": index,
                "type": q_type,
                "question": q_text,
                "options": [
                    str(option)
                    for option in options
                ],
                "correct_answer": answer,
                "explanation": explanation
            })

        if len(normalized_questions) < count:
            raise RuntimeError(
                "Gemini did not return the requested number "
                "of valid questions."
            )

        return jsonify({
            "message":
                "AI questions generated successfully.",
            "questions":
                normalized_questions,
            "count":
                len(normalized_questions),
            "type":
                question_type,
            "difficulty":
                difficulty,
            "topic":
                topic,
            "material_id":
                int(material_id),
            "material":
                material["name"]
        }), 201

    except Error as error:
        if db:
            try:
                db.rollback()
            except Exception:
                pass

        print(
            "\n================ QUESTION DATABASE ERROR ================\n"
        )
        print(error)

        return jsonify({
            "message":
                "Database error while generating questions.",
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
        traceback.print_exc()

        return jsonify({
            "message":
                "Unable to generate AI questions.",
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
    "/api/support/ask",
    methods=["POST"]
)
def ai_support():

    try:

        data = request.get_json(
            silent=True
        ) or {}


        message = (
            data.get("message")
            or ""
        ).strip()


        if not message:

            return jsonify({

                "message":
                    "Please enter your question."

            }), 400


        if len(message) > 2000:

            return jsonify({

                "message":
                    "Question is too long. Please keep it under 2000 characters."

            }), 400


        # -------------------------------------------------
        # GEMINI API KEY
        # -------------------------------------------------

        gemini_api_key = os.environ.get(
            "GEMINI_API_KEY"
        )


        if not gemini_api_key:

            return jsonify({

                "message":
                    "Gemini API key is not configured."

            }), 500


        # -------------------------------------------------
        # STUDYAI SUPPORT PROMPT
        # -------------------------------------------------

        prompt = f"""
You are StudyAI's official AI Help & Support assistant.

StudyAI is an educational platform with these features:

1. User Login / Registration
2. Forgot Password with email OTP
3. Study Dashboard
4. Study Timer
5. Study Materials
6. AI Study Planner
7. AI Question Generator
8. Progress Tracker
9. Notifications / Reminders
10. User Profile

Your job is to help users understand and troubleshoot StudyAI.

USER QUESTION:
{message}

RULES:

- Give a clear and friendly answer.
- Keep the answer concise but useful.
- Explain steps in numbered form when appropriate.
- Never claim that you performed an action that you cannot actually perform.
- Never ask for the user's password.
- Never ask for their OTP.
- Never expose API keys, database credentials or internal secrets.
- If the issue appears to be a server/database problem, explain what the user should check and suggest contacting support.
- If the question is unrelated to StudyAI, politely say that you are the StudyAI support assistant and ask them to ask about StudyAI.
- Do not invent StudyAI features that are not listed above.

Return ONLY the support response text.
"""


        # -------------------------------------------------
        # GEMINI
        # -------------------------------------------------

        client = genai.Client(
            api_key=gemini_api_key
        )


        response = client.models.generate_content(

            model="gemini-3.6-flash",

            contents=prompt

        )


        answer = (
            response.text
            or ""
        ).strip()


        if not answer:

            raise Exception(
                "Gemini returned an empty support response."
            )


        return jsonify({

            "message":
                "Support response generated.",

            "answer":
                answer

        }), 200


    except Exception as error:

        import traceback

        print(
            "\n================ AI SUPPORT ERROR ================\n"
        )

        traceback.print_exc()

        print(
            "\n===================================================\n"
        )


        return jsonify({

            "message":
                "Unable to generate support response.",

            "error":
                str(error)

        }), 500

