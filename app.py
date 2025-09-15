#!/usr/bin/env python3
"""
Classroom Management System - Single-file Flask App (app.py)

Features:
- Single-file Flask app with inline HTML templates using render_template_string
- SQLite3 backend with schema creation & seed data
- Tutor and Student roles (simple session-based login for demo)
- Create quizzes via form or JSON upload (upload saved to ./uploads)
- Students can take quizzes and submit answers
- Tutor dashboard shows analytics with Chart.js (average scores, completion)
- Uses Tailwind CSS & Chart.js via CDN
- Secure DB access using parameterized queries (to prevent SQL injection)
- Well-documented, easy to extend

How to run:
1. Create a venv (optional):
   python3 -m venv venv
   source venv/bin/activate

2. Install requirements:
   pip install -r requirements.txt

3. Run:
   python app.py

4. Open http://127.0.0.1:5000

This file is intentionally a single-file demo for portfolio purposes.
"""
from flask import (
    Flask, g, render_template_string, request, redirect, url_for,
    flash, session, send_from_directory, abort, jsonify
)
import sqlite3
import os
import json
from datetime import datetime
from werkzeug.utils import secure_filename

# -----------------------
# Configuration
# -----------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "classroom.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"json"}  # quiz upload format: JSON

SECRET_KEY = "replace-with-a-secure-random-key-for-production"

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    DATABASE=DB_PATH,
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    MAX_CONTENT_LENGTH=2 * 1024 * 1024  # 2MB max file upload for quizzes
)

# -----------------------
# Database helpers
# -----------------------
def get_db():
    """Return a sqlite3 connection stored on the flask.g object."""
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(app.config["DATABASE"])
        db.row_factory = sqlite3.Row  # rows accessible as dicts
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

def query_db(query, args=(), one=False):
    """Utility to execute a query and return rows."""
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def execute_db(statement, args=()):
    """Execute a write statement and commit."""
    db = get_db()
    cur = db.execute(statement, args)
    db.commit()
    return cur.lastrowid

# -----------------------
# DB Schema & Seed Data
# -----------------------
def init_db(seed=True):
    """Create all tables and optionally seed with sample data."""
    db = get_db()
    with app.open_resource(None) as f:  # no resource; kept for compatibility
        pass
    # Create tables
    execute_db("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT UNIQUE,
        role TEXT CHECK(role IN ('tutor','student')) NOT NULL
    );
    """)
    execute_db("""
    CREATE TABLE IF NOT EXISTS classes (
        class_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT
    );
    """)
    execute_db("""
    CREATE TABLE IF NOT EXISTS enrollments (
        enrollment_id INTEGER PRIMARY KEY,
        class_id INTEGER,
        user_id INTEGER,
        FOREIGN KEY(class_id) REFERENCES classes(class_id),
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    );
    """)
    execute_db("""
    CREATE TABLE IF NOT EXISTS quizzes (
        quiz_id INTEGER PRIMARY KEY,
        class_id INTEGER,
        title TEXT NOT NULL,
        description TEXT,
        created_by INTEGER,
        created_at TEXT,
        FOREIGN KEY(class_id) REFERENCES classes(class_id),
        FOREIGN KEY(created_by) REFERENCES users(user_id)
    );
    """)
    execute_db("""
    CREATE TABLE IF NOT EXISTS questions (
        question_id INTEGER PRIMARY KEY,
        quiz_id INTEGER,
        question_text TEXT NOT NULL,
        choices TEXT,   -- JSON array of choices
        answer_index INTEGER, -- index of correct choice (0-based)
        points INTEGER DEFAULT 1,
        FOREIGN KEY(quiz_id) REFERENCES quizzes(quiz_id)
    );
    """)
    execute_db("""
    CREATE TABLE IF NOT EXISTS submissions (
        submission_id INTEGER PRIMARY KEY,
        quiz_id INTEGER,
        student_id INTEGER,
        submitted_at TEXT,
        answers TEXT,   -- JSON array of chosen indexes
        score REAL,
        FOREIGN KEY(quiz_id) REFERENCES quizzes(quiz_id),
        FOREIGN KEY(student_id) REFERENCES users(user_id)
    );
    """)

    if seed:
        # Check if we already seeded
        existing = query_db("SELECT user_id FROM users LIMIT 1")
        if existing:
            return

        # Seed simple data: one tutor, three students, one class
        tutor_id = execute_db(
            "INSERT INTO users (name,email,role) VALUES (?,?,?)",
            ("Priya Patel", "priya.tutor@example.com", "tutor")
        )
        s1 = execute_db(
            "INSERT INTO users (name,email,role) VALUES (?,?,?)",
            ("Alice Johnson", "alice.student@example.com", "student")
        )
        s2 = execute_db(
            "INSERT INTO users (name,email,role) VALUES (?,?,?)",
            ("Bob Smith", "bob.student@example.com", "student")
        )
        s3 = execute_db(
            "INSERT INTO users (name,email,role) VALUES (?,?,?)",
            ("Carlos Vega", "carlos.student@example.com", "student")
        )
        class_id = execute_db(
            "INSERT INTO classes (name,description) VALUES (?,?)",
            ("Intro to Databases", "Foundations of SQL and data modeling")
        )
        # Enroll students
        for uid in (s1, s2, s3, tutor_id):
            execute_db(
                "INSERT INTO enrollments (class_id,user_id) VALUES (?,?)",
                (class_id, uid)
            )
        # Create a sample quiz
        quiz_id = execute_db(
            "INSERT INTO quizzes (class_id,title,description,created_by,created_at) VALUES (?,?,?,?,?)",
            (class_id, "SQL Basics Quiz", "Basic SQL questions", tutor_id, datetime.utcnow().isoformat())
        )
        questions = [
            {
                "question_text": "Which SQL command is used to remove a record?",
                "choices": ["SELECT", "DELETE", "INSERT", "UPDATE"],
                "answer_index": 1,
                "points": 1
            },
            {
                "question_text": "Which clause is used to filter groups?",
                "choices": ["WHERE", "GROUP BY", "HAVING", "ORDER BY"],
                "answer_index": 2,
                "points": 2
            },
            {
                "question_text": "What is a primary key?",
                "choices": ["Column with duplicates", "Unique identifier for rows", "A type of JOIN", "A SQL function"],
                "answer_index": 1,
                "points": 1
            }
        ]
        for q in questions:
            execute_db(
                "INSERT INTO questions (quiz_id,question_text,choices,answer_index,points) VALUES (?,?,?,?,?)",
                (quiz_id, q["question_text"], json.dumps(q["choices"]), q["answer_index"], q["points"])
            )

# Initialize DB on first run
with app.app_context():
    init_db(seed=True)

# -----------------------
# Auth (very simple for demo)
# -----------------------
# NOTE: This is a demo: in production, use secure password hashing, proper auth flows.
@app.route("/login", methods=["GET", "POST"])
def login():
    """
    Very light login: choose a user from drop-down for demo purposes.
    This keeps the app single-file and easy to demo to an interviewer.
    """
    if request.method == "POST":
        user_id = request.form.get("user_id")
        user = query_db("SELECT * FROM users WHERE user_id = ?", (user_id,), one=True)
        if user:
            session["user_id"] = user["user_id"]
            session["user_name"] = user["name"]
            session["user_role"] = user["role"]
            flash(f"Logged in as {user['name']}", "success")
            return redirect(url_for("index"))
        flash("Invalid user selection", "danger")
    users = query_db("SELECT user_id, name, role FROM users ORDER BY role DESC, name ASC")
    return render_template_string(TEMPLATE_LOGIN, users=users)

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out", "info")
    return redirect(url_for("login"))

def login_required(f):
    """Minimal decorator to require login for routes."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# -----------------------
# Utility helpers
# -----------------------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# -----------------------
# Routes - index & dashboards
# -----------------------
@app.route("/")
@login_required
def index():
    """Route to send user to role-specific dashboard."""
    if session.get("user_role") == "tutor":
        return redirect(url_for("tutor_dashboard"))
    else:
        return redirect(url_for("student_dashboard"))

# Tutor dashboard with analytics
@app.route("/tutor")
@login_required
def tutor_dashboard():
    if session.get("user_role") != "tutor":
        abort(403)
    user_id = session["user_id"]
    # Get classes the tutor manages (for demo, tutors are enrolled like students)
    classes = query_db("""
        SELECT c.class_id, c.name, c.description
        FROM classes c
        JOIN enrollments e ON e.class_id = c.class_id
        WHERE e.user_id = ?
    """, (user_id,))
    # For each class pick quizzes and analytics
    class_stats = []
    for c in classes:
        quizzes = query_db("SELECT quiz_id, title, created_at FROM quizzes WHERE class_id = ?", (c["class_id"],))
        quizzes_stats = []
        for q in quizzes:
            # Average score
            avg = query_db("SELECT AVG(score) as avg_score FROM submissions WHERE quiz_id = ?", (q["quiz_id"],), one=True)["avg_score"]
            avg = round(avg or 0, 2)
            # Completion rate = submissions / enrolled students
            enrolled = query_db("SELECT COUNT(*) as cnt FROM enrollments WHERE class_id = ?", (c["class_id"],), one=True)["cnt"]
            submissions = query_db("SELECT COUNT(DISTINCT student_id) as cnt FROM submissions WHERE quiz_id = ?", (q["quiz_id"],), one=True)["cnt"]
            comp_rate = round((submissions or 0) / (enrolled or 1) * 100, 1)
            quizzes_stats.append({
                "quiz_id": q["quiz_id"],
                "title": q["title"],
                "avg_score": avg,
                "completion_rate": comp_rate
            })
        class_stats.append({
            "class_id": c["class_id"],
            "name": c["name"],
            "quizzes": quizzes_stats
        })
    # Overall top students (by average across submissions)
    top_students = query_db("""
        SELECT u.user_id, u.name, AVG(s.score) as avg_score, COUNT(s.submission_id) as attempts
        FROM users u
        JOIN submissions s ON s.student_id = u.user_id
        GROUP BY u.user_id
        ORDER BY avg_score DESC
        LIMIT 10
    """)
    # Prepare chart data for a sample: average per quiz across tutor's classes
    chart_labels = []
    chart_scores = []
    for cs in class_stats:
        for q in cs["quizzes"]:
            chart_labels.append(f"{cs['name']} - {q['title']}")
            chart_scores.append(q["avg_score"])
    return render_template_string(TEMPLATE_TUTOR_DASHBOARD,
                                  class_stats=class_stats,
                                  top_students=top_students,
                                  chart_labels=json.dumps(chart_labels),
                                  chart_scores=json.dumps(chart_scores),
                                  user_name=session.get("user_name"))

# Student dashboard
@app.route("/student")
@login_required
def student_dashboard():
    if session.get("user_role") != "student":
        abort(403)
    user_id = session["user_id"]
    # Classes student enrolled in
    classes = query_db("""
        SELECT c.class_id, c.name
        FROM classes c
        JOIN enrollments e ON e.class_id = c.class_id
        WHERE e.user_id = ?
    """, (user_id,))
    # Available quizzes for these classes
    quizzes = []
    for c in classes:
        qs = query_db("SELECT quiz_id, title, description FROM quizzes WHERE class_id = ?", (c["class_id"],))
        for q in qs:
            # Has the student submitted?
            submitted = query_db("SELECT * FROM submissions WHERE quiz_id = ? AND student_id = ?", (q["quiz_id"], user_id), one=True)
            quizzes.append({
                "class": c["name"],
                "quiz_id": q["quiz_id"],
                "title": q["title"],
                "description": q["description"],
                "submitted": bool(submitted),
                "score": submitted["score"] if submitted else None
            })
    return render_template_string(TEMPLATE_STUDENT_DASHBOARD, quizzes=quizzes, user_name=session.get("user_name"))

# -----------------------
# Quiz creation & upload (Tutor)
# -----------------------
@app.route("/tutor/quiz/new", methods=["GET", "POST"])
@login_required
def create_quiz():
    if session.get("user_role") != "tutor":
        abort(403)
    # For simplicity pick the first class the tutor is enrolled in
    user_id = session["user_id"]
    klass = query_db("SELECT c.class_id, c.name FROM classes c JOIN enrollments e ON e.class_id=c.class_id WHERE e.user_id=? LIMIT 1", (user_id,), one=True)
    if not klass:
        flash("You are not assigned to any class.", "warning")
        return redirect(url_for("tutor_dashboard"))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        # Parse questions posted as JSON string
        questions_json = request.form.get("questions_json", "")
        try:
            questions = json.loads(questions_json)
            if not title or not questions:
                raise ValueError("Title and questions required")
        except Exception as e:
            flash("Invalid questions payload: " + str(e), "danger")
            return redirect(url_for("create_quiz"))
        quiz_id = execute_db(
            "INSERT INTO quizzes (class_id,title,description,created_by,created_at) VALUES (?,?,?,?,?)",
            (klass["class_id"], title, description, user_id, datetime.utcnow().isoformat())
        )
        for q in questions:
            # Ensure choices are JSON-serializable list and answer index exists
            choices = q.get("choices") or []
            answer_index = int(q.get("answer_index", 0))
            points = int(q.get("points", 1))
            execute_db(
                "INSERT INTO questions (quiz_id,question_text,choices,answer_index,points) VALUES (?,?,?,?,?)",
                (quiz_id, q.get("question_text"), json.dumps(choices), answer_index, points)
            )
        flash("Quiz created successfully", "success")
        return redirect(url_for("tutor_dashboard"))
    return render_template_string(TEMPLATE_CREATE_QUIZ, class_name=klass["name"])

@app.route("/tutor/quiz/upload", methods=["GET", "POST"])
@login_required
def upload_quiz():
    """
    Accepts a JSON file with structure:
    {
      "title": "Quiz title",
      "description": "optional",
      "questions": [
         {"question_text": "..", "choices": ["a","b"], "answer_index": 0, "points": 1},
         ...
      ]
    }
    """
    if session.get("user_role") != "tutor":
        abort(403)
    user_id = session["user_id"]
    klass = query_db("SELECT c.class_id, c.name FROM classes c JOIN enrollments e ON e.class_id=c.class_id WHERE e.user_id=? LIMIT 1", (user_id,), one=True)
    if request.method == "POST":
        if "file" not in request.files:
            flash("Missing file", "danger")
            return redirect(url_for("upload_quiz"))
        file = request.files["file"]
        if file.filename == "":
            flash("No file selected", "danger")
            return redirect(url_for("upload_quiz"))
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            saved_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(saved_path)
            # Load JSON
            try:
                with open(saved_path, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
                title = payload.get("title") or "Untitled Quiz"
                description = payload.get("description", "")
                questions = payload.get("questions", [])
                if not questions:
                    raise ValueError("No questions found in JSON")
                quiz_id = execute_db(
                    "INSERT INTO quizzes (class_id,title,description,created_by,created_at) VALUES (?,?,?,?,?)",
                    (klass["class_id"], title, description, user_id, datetime.utcnow().isoformat())
                )
                for q in questions:
                    execute_db(
                        "INSERT INTO questions (quiz_id,question_text,choices,answer_index,points) VALUES (?,?,?,?,?)",
                        (quiz_id, q.get("question_text"), json.dumps(q.get("choices", [])), int(q.get("answer_index", 0)), int(q.get("points", 1)))
                    )
                flash("Quiz uploaded and saved", "success")
                return redirect(url_for("tutor_dashboard"))
            except Exception as e:
                flash("Failed to parse/upload quiz: " + str(e), "danger")
                return redirect(url_for("upload_quiz"))
        else:
            flash("Unsupported file type. Use JSON.", "danger")
            return redirect(url_for("upload_quiz"))
    return render_template_string(TEMPLATE_UPLOAD_QUIZ)

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    # Serves uploads for demo purposes only
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# -----------------------
# Student takes quiz
# -----------------------
@app.route("/quiz/<int:quiz_id>/take", methods=["GET", "POST"])
@login_required
def take_quiz(quiz_id):
    if session.get("user_role") != "student":
        abort(403)
    user_id = session["user_id"]
    quiz = query_db("SELECT * FROM quizzes WHERE quiz_id = ?", (quiz_id,), one=True)
    if not quiz:
        abort(404)
    questions = query_db("SELECT * FROM questions WHERE quiz_id = ?", (quiz_id,))
    if request.method == "POST":
        # Collect answers: expected as form fields 'q_{question_id}'
        answers = []
        total_score = 0
        max_score = 0
        for q in questions:
            key = f"q_{q['question_id']}"
            val = request.form.get(key)
            try:
                chosen = int(val) if val is not None else None
            except:
                chosen = None
            answers.append(chosen)
            correct = int(q["answer_index"])
            points = int(q["points"])
            max_score += points
            if chosen is not None and chosen == correct:
                total_score += points
        # Normalize or keep raw score; keep raw and also compute percent
        percent = round((total_score / max_score) * 100, 2) if max_score > 0 else 0.0
        execute_db("""
            INSERT INTO submissions (quiz_id, student_id, submitted_at, answers, score)
            VALUES (?,?,?,?,?)
        """, (quiz_id, user_id, datetime.utcnow().isoformat(), json.dumps(answers), percent))
        flash(f"Quiz submitted. Score: {percent}%", "success")
        return redirect(url_for("student_dashboard"))
    # Student GET view
    formatted_questions = []
    for q in questions:
        formatted_questions.append({
            "question_id": q["question_id"],
            "text": q["question_text"],
            "choices": json.loads(q["choices"]),
            "points": q["points"]
        })
    return render_template_string(TEMPLATE_TAKE_QUIZ, quiz=quiz, questions=formatted_questions)

# -----------------------
# View quiz results (Tutor & Student)
# -----------------------
@app.route("/quiz/<int:quiz_id>/results")
@login_required
def quiz_results(quiz_id):
    # Tutor can view all submissions; student can view only their submission
    quiz = query_db("SELECT * FROM quizzes WHERE quiz_id = ?", (quiz_id,), one=True)
    if not quiz:
        abort(404)
    if session.get("user_role") == "tutor":
        subs = query_db("""
            SELECT s.*, u.name as student_name
            FROM submissions s
            JOIN users u ON s.student_id = u.user_id
            WHERE s.quiz_id = ?
            ORDER BY s.score DESC
        """, (quiz_id,))
    else:
        subs = query_db("""
            SELECT s.*, u.name as student_name
            FROM submissions s
            JOIN users u ON s.student_id = u.user_id
            WHERE s.quiz_id = ? AND s.student_id = ?
        """, (quiz_id, session["user_id"]))
    # Questions for cross-checking
    questions = query_db("SELECT * FROM questions WHERE quiz_id = ?", (quiz_id,))
    qlist = []
    for q in questions:
        qlist.append({
            "question_id": q["question_id"],
            "text": q["question_text"],
            "choices": json.loads(q["choices"]),
            "answer_index": q["answer_index"],
            "points": q["points"]
        })
    # Compose readable submissions
    results = []
    for s in subs:
        answers = json.loads(s["answers"]) if s["answers"] else []
        results.append({
            "submission_id": s["submission_id"],
            "student_name": s["student_name"],
            "submitted_at": s["submitted_at"],
            "answers": answers,
            "score": s["score"]
        })
    return render_template_string(TEMPLATE_QUIZ_RESULTS, quiz=quiz, questions=qlist, results=results)

# -----------------------
# API endpoints (small, for analytics)
# -----------------------
@app.route("/api/quiz/<int:quiz_id>/stats")
@login_required
def quiz_stats_api(quiz_id):
    """Return basic stats for a quiz in JSON - used by charts if needed."""
    if session.get("user_role") != "tutor":
        abort(403)
    avg = query_db("SELECT AVG(score) as avg FROM submissions WHERE quiz_id = ?", (quiz_id,), one=True)["avg"] or 0
    count = query_db("SELECT COUNT(*) as cnt FROM submissions WHERE quiz_id = ?", (quiz_id,), one=True)["cnt"]
    return jsonify({"quiz_id": quiz_id, "avg": round(avg,2), "submissions": count})

# -----------------------
# TEMPLATES (render_template_string usage)
# -----------------------
# For readability templates are defined here as big multi-line constants.
# In production, use separate template files; here we keep single-file as requested.

TEMPLATE_BASE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Classroom Management System</title>
  <!-- Tailwind via CDN -->
  <script src="https://cdn.tailwindcss.com"></script>
  <!-- Chart.js CDN -->
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body class="bg-slate-50 min-h-screen">
  <nav class="bg-white shadow">
    <div class="max-w-6xl mx-auto px-4">
      <div class="flex justify-between">
        <div class="flex space-x-4 py-4">
          <a href="{{ url_for('index') }}" class="font-semibold text-lg text-sky-600">Classroom</a>
          <div class="hidden md:flex items-center space-x-1">
            {% if session.get('user_role') == 'tutor' %}
              <a href="{{ url_for('tutor_dashboard') }}" class="px-3 py-2 rounded hover:bg-slate-100">Tutor Dashboard</a>
            {% else %}
              <a href="{{ url_for('student_dashboard') }}" class="px-3 py-2 rounded hover:bg-slate-100">Student Dashboard</a>
            {% endif %}
          </div>
        </div>
        <div class="flex items-center space-x-2">
          <span class="text-slate-600 hidden sm:inline">Signed in as <strong>{{ user_name or session.get('user_name') }}</strong></span>
          <a href="{{ url_for('logout') }}" class="inline-block px-3 py-2 text-sm bg-rose-500 text-white rounded hover:opacity-90">Logout</a>
        </div>
      </div>
    </div>
  </nav>
  <main class="max-w-6xl mx-auto p-6">
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        <div class="space-y-2 mb-4">
          {% for cat, msg in messages %}
            <div class="p-3 rounded {{ 'bg-green-100 text-green-800' if cat=='success' else ('bg-yellow-100 text-yellow-800' if cat=='warning' else ('bg-red-100 text-red-800' if cat=='danger' else 'bg-blue-100 text-blue-800')) }}">{{ msg }}</div>
          {% endfor %}
        </div>
      {% endif %}
    {% endwith %}
    {% block content %}{% endblock %}
  </main>
</body>
</html>
"""

TEMPLATE_LOGIN = """
{% extends none %}
{% block body %}
<!doctype html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body class="bg-slate-50 min-h-screen flex items-center">
  <div class="max-w-xl mx-auto p-6">
    <div class="bg-white p-6 rounded shadow">
      <h1 class="text-2xl font-semibold mb-4">Sign in (Demo)</h1>
      <form method="post">
        <label class="block text-sm mb-1">Choose user</label>
        <select name="user_id" class="w-full border rounded p-2 mb-4">
          {% for u in users %}
            <option value="{{ u.user_id }}">{{ u.name }} — {{ u.role }}</option>
          {% endfor %}
        </select>
        <div class="flex gap-2">
          <button class="px-4 py-2 bg-sky-600 text-white rounded">Sign in</button>
          <a href="#" onclick="alert('Demo: pick a user to login.'); return false;" class="px-4 py-2 bg-slate-100 rounded">Help</a>
        </div>
      </form>
      <p class="mt-4 text-sm text-slate-500">This demo uses simple user selection. In production, implement secure auth.</p>
    </div>
    <p class="mt-6 text-center text-slate-500 text-sm">Tip: Login as the tutor to create quizzes and view analytics.</p>
  </div>
</body>
</html>
"""

TEMPLATE_TUTOR_DASHBOARD = """
{% extends none %}
""" + TEMPLATE_BASE + """
{% block content %}
  <div class="grid md:grid-cols-3 gap-4">
    <div class="md:col-span-2">
      <div class="bg-white p-4 rounded shadow">
        <h2 class="text-xl font-semibold mb-2">Analytics Overview</h2>
        <canvas id="avgChart" class="w-full" height="160"></canvas>
        <script>
          const ctx = document.getElementById('avgChart').getContext('2d');
          const labels = {{ chart_labels | safe }};
          const data = {{ chart_scores | safe }};
          new Chart(ctx, {
            type: 'bar',
            data: {
              labels: labels,
              datasets: [{
                label: 'Average Score (%)',
                data: data,
                borderWidth: 1
              }]
            },
            options: { scales: { y: { beginAtZero: true, max: 100 } } }
          });
        </script>
      </div>

      {% for c in class_stats %}
        <div class="bg-white p-4 rounded shadow mt-4">
          <h3 class="font-semibold">{{ c.name }}</h3>
          <div class="mt-2 space-y-2">
            {% if c.quizzes %}
              {% for q in c.quizzes %}
                <div class="flex justify-between items-center border rounded p-2">
                  <div>
                    <div class="font-medium">{{ q.title }}</div>
                    <div class="text-sm text-slate-500">Avg: {{ q.avg_score }}% · Completion: {{ q.completion_rate }}%</div>
                  </div>
                  <div class="flex gap-2">
                    <a href="{{ url_for('quiz_results', quiz_id=q.quiz_id) }}" class="px-3 py-1 bg-slate-100 rounded">View results</a>
                  </div>
                </div>
              {% endfor %}
            {% else %}
              <p class="text-sm text-slate-500">No quizzes for this class yet.</p>
            {% endif %}
          </div>
        </div>
      {% endfor %}
    </div>

    <div>
      <div class="bg-white p-4 rounded shadow">
        <h3 class="font-semibold">Quick Actions</h3>
        <div class="mt-4 flex flex-col gap-2">
          <a href="{{ url_for('create_quiz') }}" class="px-4 py-2 bg-sky-600 text-white rounded text-center">Create Quiz (Form)</a>
          <a href="{{ url_for('upload_quiz') }}" class="px-4 py-2 bg-emerald-600 text-white rounded text-center">Upload Quiz (JSON)</a>
        </div>
      </div>

      <div class="bg-white p-4 rounded shadow mt-4">
        <h3 class="font-semibold">Top Students</h3>
        <ol class="list-decimal list-inside mt-2 space-y-1 text-sm">
          {% for s in top_students %}
            <li>{{ s.name }} — {{ "%.2f"|format(s.avg_score) }}% ({{ s.attempts }} attempts)</li>
          {% else %}
            <li class="text-slate-500">No submissions yet</li>
          {% endfor %}
        </ol>
      </div>
    </div>
  </div>
{% endblock %}
"""

TEMPLATE_STUDENT_DASHBOARD = """
{% extends none %}
""" + TEMPLATE_BASE + """
{% block content %}
  <div class="grid md:grid-cols-3 gap-4">
    <div class="md:col-span-2">
      <div class="bg-white p-4 rounded shadow">
        <h2 class="text-xl font-semibold mb-2">Your Quizzes</h2>
        <div class="space-y-2">
          {% for q in quizzes %}
            <div class="flex justify-between items-center border p-3 rounded">
              <div>
                <div class="font-medium">{{ q.title }}</div>
                <div class="text-sm text-slate-500">{{ q.class }}</div>
                <div class="text-xs text-slate-400">{{ q.description }}</div>
              </div>
              <div class="flex gap-2 items-center">
                {% if q.submitted %}
                  <div class="text-sm text-green-700">Completed — {{ q.score }}%</div>
                  <a href="{{ url_for('quiz_results', quiz_id=q.quiz_id) }}" class="px-3 py-1 bg-slate-100 rounded">View</a>
                {% else %}
                  <a href="{{ url_for('take_quiz', quiz_id=q.quiz_id) }}" class="px-3 py-1 bg-sky-600 text-white rounded">Take Quiz</a>
                {% endif %}
              </div>
            </div>
          {% else %}
            <p class="text-slate-500">No quizzes available. Contact your tutor.</p>
          {% endfor %}
        </div>
      </div>
    </div>
    <div>
      <div class="bg-white p-4 rounded shadow">
        <h3 class="font-semibold">Profile</h3>
        <p class="mt-2 text-sm">Signed in as <strong>{{ user_name }}</strong></p>
      </div>
    </div>
  </div>
{% endblock %}
"""

TEMPLATE_CREATE_QUIZ = """
{% extends none %}
""" + TEMPLATE_BASE + """
{% block content %}
  <div class="bg-white p-6 rounded shadow">
    <h2 class="text-xl font-semibold mb-4">Create Quiz for: {{ class_name }}</h2>
    <form id="createQuizForm" method="post">
      <label class="block mb-2">Title</label>
      <input name="title" class="w-full border p-2 rounded mb-3" required/>
      <label class="block mb-2">Description (optional)</label>
      <textarea name="description" class="w-full border p-2 rounded mb-3"></textarea>

      <div id="questionsWrap" class="space-y-4">
        <!-- dynamic question fields -->
      </div>

      <button type="button" onclick="addQuestion()" class="px-3 py-2 bg-sky-600 text-white rounded">Add Question</button>
      <input type="hidden" name="questions_json" id="questions_json"/>
      <div class="mt-4">
        <button onclick="prepareAndSubmit(event)" class="px-4 py-2 bg-emerald-600 text-white rounded">Create Quiz</button>
        <a href="{{ url_for('tutor_dashboard') }}" class="ml-2 text-sm text-slate-500">Cancel</a>
      </div>
    </form>
  </div>

<script>
let qcount = 0;
function addQuestion(sample) {
  qcount++;
  const defaultQ = sample || {
    question_text: "",
    choices: ["",""],
    answer_index: 0,
    points: 1
  };
  const wrapper = document.getElementById('questionsWrap');
  const div = document.createElement('div');
  div.className = 'p-3 border rounded';
  div.innerHTML = `
    <label class="block mb-1 font-medium">Question ${qcount}</label>
    <input data-q="text" class="w-full border p-2 rounded mb-2" placeholder="Question text" value="${defaultQ.question_text.replace(/"/g,'&quot;')}"/>
    <div class="mb-2" data-choices>
      ${defaultQ.choices.map((c,idx)=>`<div class="flex gap-2 mb-1">
        <input type="radio" name="ans_${qcount}" ${idx===defaultQ.answer_index?'checked':''}/>
        <input data-qchoice class="flex-1 border p-2 rounded" value="${(c||'').replace(/"/g,'&quot;')}" placeholder="Choice ${idx+1}"/>
        <button type="button" onclick="this.parentElement.remove()" class="px-2">✖</button>
      </div>`).join('')}
      <button type="button" onclick="addChoice(this)" class="px-2 py-1 bg-slate-100 rounded">Add choice</button>
    </div>
    <label class="block text-sm mt-1">Points</label>
    <input data-q="points" type="number" min="1" value="${defaultQ.points}" class="w-24 border p-1 rounded"/>
    <div class="mt-2">
      <button type="button" onclick="this.parentElement.parentElement.remove()" class="px-2 py-1 bg-red-100 rounded">Remove Question</button>
    </div>
  `;
  wrapper.appendChild(div);
}
function addChoice(btn) {
  const container = btn.parentElement;
  const idx = container.querySelectorAll('[data-qchoice]').length + 1;
  const node = document.createElement('div');
  node.className = 'flex gap-2 mb-1';
  node.innerHTML = `<input type="radio" name="ans_${qcount}" />
    <input data-qchoice class="flex-1 border p-2 rounded" placeholder="Choice ${idx}"/>
    <button type="button" onclick="this.parentElement.remove()" class="px-2">✖</button>`;
  container.insertBefore(node, btn);
}
function prepareAndSubmit(e) {
  e.preventDefault();
  const qs = [];
  const qdivs = document.querySelectorAll('#questionsWrap > div');
  for (const div of qdivs) {
    const qtext = div.querySelector('[data-q="text"]').value.trim();
    const choicesEls = Array.from(div.querySelectorAll('[data-qchoice]'));
    const choices = choicesEls.map(i=>i.value.trim()).filter(x=>x!=="");
    // find checked radio among these choices
    let answer_idx = 0;
    const radios = div.querySelectorAll('input[type=radio]');
    radios.forEach((r, idx) => { if (r.checked) answer_idx = idx; });
    const points = parseInt(div.querySelector('[data-q="points"]').value) || 1;
    qs.push({question_text: qtext, choices: choices, answer_index: answer_idx, points: points});
  }
  if (qs.length === 0) { alert('Add at least one question'); return; }
  document.getElementById('questions_json').value = JSON.stringify(qs);
  document.getElementById('createQuizForm').submit();
}

// Add an initial question by default
addQuestion({
  question_text: "Example: What is SQL?",
  choices: ["Structured Query Language", "Simple Query List"],
  answer_index: 0,
  points: 1
});
</script>
"""

TEMPLATE_UPLOAD_QUIZ = """
{% extends none %}
""" + TEMPLATE_BASE + """
{% block content %}
  <div class="bg-white p-6 rounded shadow max-w-2xl">
    <h2 class="text-xl font-semibold mb-4">Upload Quiz (JSON)</h2>
    <p class="text-sm text-slate-500 mb-3">Upload a JSON file with quiz structure. See example below.</p>
    <form method="post" enctype="multipart/form-data">
      <input type="file" name="file" accept=".json" class="mb-3 block"/>
      <div class="flex gap-2">
        <button class="px-4 py-2 bg-emerald-600 text-white rounded">Upload</button>
        <a href="{{ url_for('tutor_dashboard') }}" class="px-4 py-2 bg-slate-100 rounded">Cancel</a>
      </div>
    </form>
    <div class="mt-6 bg-slate-50 p-3 rounded text-xs">
      <pre>{
  "title": "Sample Quiz",
  "description": "Optional description",
  "questions": [
    {
      "question_text": "What's 2+2?",
      "choices": ["3","4","5"],
      "answer_index": 1,
      "points": 1
    }
  ]
}</pre>
    </div>
  </div>
{% endblock %}
"""

TEMPLATE_TAKE_QUIZ = """
{% extends none %}
""" + TEMPLATE_BASE + """
{% block content %}
  <div class="bg-white p-6 rounded shadow max-w-3xl">
    <h2 class="text-xl font-semibold mb-4">{{ quiz.title }}</h2>
    <p class="text-sm text-slate-500 mb-4">{{ quiz.description }}</p>
    <form method="post">
      {% for q in questions %}
        <div class="mb-4 border rounded p-3">
          <div class="font-medium mb-2">{{ loop.index }}. {{ q.text }} <span class="text-sm text-slate-400">({{ q.points }} pt)</span></div>
          <div class="space-y-2">
            {% for choice in q.choices %}
              <label class="flex items-center gap-2">
                <input type="radio" name="q_{{ q.question_id }}" value="{{ loop.index0 }}" />
                <span>{{ choice }}</span>
              </label>
            {% endfor %}
          </div>
        </div>
      {% endfor %}
      <div class="flex gap-2">
        <button class="px-4 py-2 bg-sky-600 text-white rounded">Submit Quiz</button>
        <a href="{{ url_for('student_dashboard') }}" class="px-4 py-2 bg-slate-100 rounded">Cancel</a>
      </div>
    </form>
  </div>
{% endblock %}
"""

TEMPLATE_QUIZ_RESULTS = """
{% extends none %}
""" + TEMPLATE_BASE + """
{% block content %}
  <div class="bg-white p-6 rounded shadow max-w-5xl">
    <h2 class="text-xl font-semibold mb-3">Results — {{ quiz.title }}</h2>
    <div class="mb-4 grid md:grid-cols-3 gap-4">
      <div class="md:col-span-2">
        <div class="space-y-3">
          {% for r in results %}
            <div class="border rounded p-3">
              <div class="flex justify-between items-center">
                <div><strong>{{ r.student_name }}</strong></div>
                <div class="text-sm text-slate-500">{{ r.submitted_at }}</div>
              </div>
              <div class="mt-2 text-sm">Score: <strong>{{ r.score }}%</strong></div>
            </div>
          {% endfor %}
        </div>
      </div>
      <div>
        <h3 class="font-semibold">Answer Key</h3>
        <ol class="list-decimal list-inside mt-2 text-sm space-y-2">
          {% for q in questions %}
            <li>
              <div class="font-medium">{{ q.text }}</div>
              <div class="text-slate-600">Correct: {{ q.choices[q.answer_index] }} ({{ q.points }} pt)</div>
            </li>
          {% endfor %}
        </ol>
      </div>
    </div>
    <a href="{{ url_for('index') }}" class="px-4 py-2 bg-slate-100 rounded">Back</a>
  </div>
{% endblock %}
"""

# -----------------------
# Run (dev server)
# -----------------------
if __name__ == "__main__":
    # For demo use reloader; in production use gunicorn/uwsgi
    app.run(debug=True, port=5000)
