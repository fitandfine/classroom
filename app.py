import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, g
import os

app = Flask(__name__)
app.secret_key = "super-secret-key"
DATABASE = os.path.join(app.root_path, "classroom.db")

# ----------- DB CONNECTION ----------- #
def get_db():
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()

# ----------- INITIALIZE DATABASE ----------- #
def init_db(seed=False):
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                role TEXT CHECK(role IN ('tutor','student')) NOT NULL
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS quizzes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                tutor_id INTEGER,
                FOREIGN KEY(tutor_id) REFERENCES users(id)
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS questions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quiz_id INTEGER,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                FOREIGN KEY(quiz_id) REFERENCES quizzes(id)
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS submissions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quiz_id INTEGER,
                student_id INTEGER,
                score INTEGER,
                FOREIGN KEY(quiz_id) REFERENCES quizzes(id),
                FOREIGN KEY(student_id) REFERENCES users(id)
            );
        """)
        db.commit()

        if seed:
            cursor.execute("INSERT INTO users (name, role) VALUES ('Alice','tutor'),('Bob','student'),('Carol','student');")
            cursor.execute("INSERT INTO quizzes (title, tutor_id) VALUES ('Intro to SQL',1);")
            cursor.execute("INSERT INTO questions (quiz_id,question,answer) VALUES (1,'What is a PRIMARY KEY?','A unique identifier for rows');")
            db.commit()

# ----------- ROUTES ----------- #
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/tutor/<int:tutor_id>")
def dashboard_tutor(tutor_id):
    db = get_db()
    quizzes = db.execute("SELECT * FROM quizzes WHERE tutor_id=?;", (tutor_id,)).fetchall()
    stats = db.execute("""
        SELECT q.title, AVG(s.score) as avg_score
        FROM submissions s
        JOIN quizzes q ON s.quiz_id=q.id
        WHERE q.tutor_id=?
        GROUP BY q.id;
    """, (tutor_id,)).fetchall()
    return render_template("dashboard_tutor.html", quizzes=quizzes, stats=stats)

@app.route("/student/<int:student_id>")
def dashboard_student(student_id):
    db = get_db()
    submissions = db.execute("""
        SELECT q.title, s.score
        FROM submissions s
        JOIN quizzes q ON s.quiz_id=q.id
        WHERE s.student_id=?;
    """, (student_id,)).fetchall()
    return render_template("dashboard_student.html", submissions=submissions)

@app.route("/upload_quiz/<int:tutor_id>", methods=["GET","POST"])
def upload_quiz(tutor_id):
    db = get_db()
    if request.method == "POST":
        title = request.form["title"]
        questions = request.form.getlist("questions")
        answers = request.form.getlist("answers")
        cursor = db.cursor()
        cursor.execute("INSERT INTO quizzes (title,tutor_id) VALUES (?,?);", (title,tutor_id))
        quiz_id = cursor.lastrowid
        for q,a in zip(questions,answers):
            cursor.execute("INSERT INTO questions (quiz_id,question,answer) VALUES (?,?,?);",(quiz_id,q,a))
        db.commit()
        flash("Quiz uploaded successfully!", "success")
        return redirect(url_for("dashboard_tutor", tutor_id=tutor_id))
    return render_template("upload_quiz.html")

if __name__ == "__main__":
    if not os.path.exists(DATABASE):
        init_db(seed=True)
    app.run(debug=True)
