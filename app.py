# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from io import BytesIO
import json
import db as DB
import os

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("CLASSROOM_SECRET", "dev-secret-change-me")
login_manager = LoginManager(app)
login_manager.login_view = "login"

# -----------------------
# Flask-Login User object
# -----------------------
class User(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.name = row["name"]
        self.email = row["email"]
        self.role = row["role"]

@login_manager.user_loader
def load_user(user_id):
    row = DB.get_user_by_id(int(user_id))
    if row:
        return User(row)
    return None

# -----------------------
# Public routes
# -----------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        row = DB.get_user_by_email(email)
        if not row:
            flash("Invalid credentials", "danger")
            return redirect(url_for("login"))
        if not row["password_hash"]:
            flash("Account exists but no password set. Ask admin to reset.", "danger")
            return redirect(url_for("login"))
        if check_password_hash(row["password_hash"], password):
            user = User(row)
            login_user(user)
            flash("Logged in", "success")
            return redirect(url_for("index"))
        flash("Invalid credentials", "danger")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out", "info")
    return redirect(url_for("login"))

# -----------------------
# Registration endpoints (admin & tutor flows)
# -----------------------
@app.route("/register", methods=["GET","POST"])
@login_required
def register():
    # only admin or tutors can register users:
    if current_user.role not in ("admin", "tutor"):
        flash("Forbidden", "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        role = request.form.get("role", "student").strip()
        password = request.form["password"]

        # Validate role
        if role not in ("student", "tutor"):
            flash("Invalid role selection", "danger")
            return redirect(url_for("register"))

        # Only admin may create tutors
        if role == "tutor" and current_user.role != "admin":
            flash("Only admin can create tutors", "danger")
            return redirect(url_for("register"))

        # Prevent creating admin via UI
        if role == "admin":
            flash("Creating admin via UI is disabled", "danger")
            return redirect(url_for("register"))

        pw_hash = generate_password_hash(password)
        try:
            uid = DB.create_user(name, email, pw_hash, role)
            flash(f"User {name} ({role}) created with id {uid}", "success")

            # If tutor created a student (or admin created a student), optionally enroll into class
            if role == "student" and request.form.get("class_id"):
                try:
                    class_id = int(request.form["class_id"])
                    DB.enroll_student(class_id, uid)
                except Exception:
                    pass

            return redirect(url_for("index"))
        except Exception as e:
            flash(f"Failed to create user: {e}", "danger")
            return redirect(url_for("register"))

    # GET: show registration form
    classes = []
    if current_user.role == "tutor":
        classes = DB.get_classes_for_tutor(current_user.id)

    # If admin is calling this page, offer tutor creation as well (dropdown)
    admin_create_tutor = (current_user.role == "admin")
    return render_template("register.html", classes=classes, admin_create_tutor=admin_create_tutor, default_role=None)

# -----------------------
# Admin-only: register tutors (convenience)
# -----------------------
@app.route("/admin/register_tutor", methods=["GET", "POST"])
@login_required
def admin_register_tutor():
    if current_user.role != "admin":
        flash("Forbidden", "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        # Force role to tutor (safety)
        uid = DB.create_user(name, email, generate_password_hash(password), "tutor")
        flash(f"Tutor {name} created (id: {uid})", "success")
        return redirect(url_for("index"))

    # Render the shared register template but force role to tutor (hidden field)
    return render_template("register.html", admin_create_tutor=True, default_role="tutor")

# -----------------------
# Tutor dashboard & features
# -----------------------
@app.route("/tutor")
@login_required
def tutor_dashboard():
    if current_user.role != "tutor":
        flash("Forbidden","danger")
        return redirect(url_for("index"))

    classes = DB.get_classes_for_tutor(current_user.id)
    class_data = []
    for c in classes:
        students = DB.get_students_in_class(c["id"])
        quizzes = DB.get_quizzes_for_class(c["id"])
        attendance_summary = DB.get_attendance_summary(c["id"])
        quiz_stats = [
            {
                "quiz": q,
                "avg_score": DB.get_average_score(q["id"]),
                "num_submissions": DB.count_submissions(q["id"])
            }
            for q in quizzes
        ]
        class_data.append({
            "class": c,
            "students": students,
            "attendance": attendance_summary,
            "quizzes": quiz_stats
        })
    return render_template("tutor_dashboard.html", class_data=class_data)

@app.route("/tutor/create_class", methods=["GET","POST"])
@login_required
def create_class():
    if current_user.role != "tutor":
        flash("Forbidden", "danger"); return redirect(url_for("index"))
    if request.method == "POST":
        title = request.form["title"]; desc = request.form.get("description", "")
        cid = DB.create_class(title, desc, current_user.id)
        flash("Class created", "success")
        return redirect(url_for("tutor_dashboard"))
    return render_template("create_class.html")

@app.route("/tutor/<int:class_id>/enroll", methods=["POST"])
@login_required
def tutor_enroll_student(class_id):
    if current_user.role != "tutor": flash("Forbidden","danger"); return redirect(url_for("index"))
    student_id = int(request.form["student_id"])
    DB.enroll_student(class_id, student_id)
    flash("Student enrolled", "success")
    return redirect(url_for("tutor_dashboard"))

# Quiz creation (upload JSON) and editing
@app.route("/tutor/<int:class_id>/upload_quiz", methods=["GET","POST"])
@login_required
def tutor_upload_quiz(class_id):
    if current_user.role != "tutor": flash("Forbidden","danger"); return redirect(url_for("index"))
    if request.method == "POST":
        # expects form fields or JSON textarea
        title = request.form["title"]
        description = request.form.get("description", "")
        questions_json = request.form.get("questions_json", "")
        if questions_json:
            payload = json.loads(questions_json)
        else:
            # build from simple fields
            payload = []
            q_texts = request.form.getlist("question_text")
            for idx, qt in enumerate(q_texts):
                choices = request.form.getlist(f"choices_{idx}") or []
                answer_index = int(request.form.get(f"answer_{idx}", 0))
                pts = int(request.form.get(f"points_{idx}", 1))
                payload.append({"question_text": qt, "choices": choices, "answer_index": answer_index, "points": pts})
        DB.create_quiz(class_id, title, description, current_user.id, payload)
        flash("Quiz created", "success")
        return redirect(url_for("tutor_dashboard"))
    return render_template("upload_quiz.html", class_id=class_id)

@app.route("/tutor/quiz/<int:quiz_id>/edit", methods=["GET","POST"])
@login_required
def edit_quiz(quiz_id):
    if current_user.role != "tutor": flash("Forbidden","danger"); return redirect(url_for("index"))
    data = DB.get_quiz(quiz_id)
    if not data:
        flash("Quiz not found", "danger"); return redirect(url_for("tutor_dashboard"))
    quiz = data["quiz"]; questions = data["questions"]
    if request.method == "POST":
        title = request.form["title"]; desc = request.form.get("description","")
        # incoming questions as JSON in textarea for simplicity
        questions_json = request.form["questions_json"]
        try:
            qlist = json.loads(questions_json)
            DB.update_quiz(quiz_id, title, desc, qlist)
            flash("Quiz updated", "success")
            return redirect(url_for("tutor_dashboard"))
        except Exception as e:
            flash(f"Invalid JSON: {e}", "danger")
    # prepare questions for textarea
    qlist = []
    for q in questions:
        qlist.append({
            "question_text": q["question_text"],
            "choices": json.loads(q["choices"]),
            "answer_index": q["answer_index"],
            "points": q["points"]
        })
    return render_template("edit_quiz.html", quiz=quiz, questions_json=json.dumps(qlist, indent=2))

@app.route("/tutor/quiz/<int:quiz_id>/export_csv")
@login_required
def export_quiz_csv(quiz_id):
    if current_user.role != "tutor": flash("Forbidden","danger"); return redirect(url_for("index"))
    csv = DB.export_submissions_csv(quiz_id)
    return send_file(BytesIO(csv.encode()), download_name=f"quiz_{quiz_id}_submissions.csv", as_attachment=True)

# Attendance
@app.route("/tutor/<int:class_id>/attendance", methods=["GET","POST"])
@login_required
def tutor_attendance(class_id):
    if current_user.role != "tutor": flash("Forbidden","danger"); return redirect(url_for("index"))
    students = DB.get_students_in_class(class_id)
    if request.method == "POST":
        # expected form fields: status_<student_id> and reason_<student_id> optionally
        for s in students:
            sid = s["id"]
            status = request.form.get(f"status_{sid}")
            reason = request.form.get(f"reason_{sid}", "").strip() if status == "justified" else None
            if status:
                DB.mark_attendance(class_id, sid, status, reason, current_user.id)
        flash("Attendance recorded", "success")
        return redirect(url_for("tutor_dashboard"))
    attendance = DB.get_attendance_for_class(class_id)
    return render_template("attendance.html", students=students, attendance=attendance, class_id=class_id)

@app.route("/tutor/<int:class_id>/attendance/export")
@login_required
def export_attendance(class_id):
    if current_user.role != "tutor": flash("Forbidden","danger"); return redirect(url_for("index"))
    csv = DB.export_attendance_csv(class_id)
    return send_file(BytesIO(csv.encode()), download_name=f"attendance_class_{class_id}.csv", as_attachment=True)

# -----------------------
# Student features
# -----------------------
@app.route("/student")
@login_required
def student_dashboard():
    if current_user.role != "student":
        flash("Forbidden","danger")
        return redirect(url_for("index"))

    classes = DB.get_classes_for_student(current_user.id)
    attendance = DB.get_student_attendance(current_user.id)
    quizzes = DB.get_student_quizzes(current_user.id)
    return render_template(
        "student_dashboard.html",
        classes=classes,
        attendance=attendance,
        quizzes=quizzes
    )

@app.route("/quiz/<int:quiz_id>/take", methods=["GET","POST"])
@login_required
def take_quiz(quiz_id):
    if current_user.role != "student": flash("Forbidden","danger"); return redirect(url_for("index"))
    data = DB.get_quiz(quiz_id)
    if not data: flash("Quiz not found", "danger"); return redirect(url_for("student_dashboard"))
    quiz = data["quiz"]; questions = data["questions"]
    if request.method == "POST":
        answers = []
        total_points = 0
        earned = 0
        for q in questions:
            qid = q["id"]
            choice = request.form.get(f"q_{qid}")
            ch_index = int(choice) if choice is not None else None
            answers.append(ch_index)
            total_points += q["points"]
            if ch_index is not None and ch_index == q["answer_index"]:
                earned += q["points"]
        score_percent = round((earned / total_points) * 100, 2) if total_points else 0.0
        DB.save_submission(quiz_id, current_user.id, answers, score_percent)
        flash(f"Submitted. Score: {score_percent}%", "success")
        return redirect(url_for("student_dashboard"))
    # format questions with choices
    qlist = []
    for q in questions:
        qlist.append({
            "id": q["id"],
            "text": q["question_text"],
            "choices": json.loads(q["choices"]),
            "points": q["points"]
        })
    return render_template("quiz_take.html", quiz=quiz, questions=qlist)

@app.route("/quiz/<int:quiz_id>/results")
@login_required
def quiz_results(quiz_id):
    data = DB.get_quiz(quiz_id)
    if not data: flash("Quiz not found", "danger"); return redirect(url_for("index"))
    # tutors can see all, students only their own
    subs = DB.get_submissions_for_quiz(quiz_id) if current_user.role == "tutor" else [s for s in DB.get_submissions_for_quiz(quiz_id) if s["student_id"] == current_user.id]
    return render_template("quiz_results.html", quiz=data["quiz"], questions=data["questions"], submissions=subs)

# -----------------------
# CLI command to init DB
# -----------------------
@app.cli.command("init-db")
def init_db_cmd():
    # create DB and optionally seed admin with password from env
    DB.init_db(seed=True)
    # if ADMIN_PASSWORD env set, update admin user with password
    admin_pw = os.environ.get("CLASSROOM_ADMIN_PW")
    if admin_pw:
        # set first admin's password (simple approach)
        conn = DB.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE role='admin' LIMIT 1")
        r = cur.fetchone()
        if r:
            from werkzeug.security import generate_password_hash
            cur.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(admin_pw), r["id"]))
            conn.commit()
        conn.close()
    print("DB initialized. If you provided CLASSROOM_ADMIN_PW environment variable, admin password set.")

if __name__ == "__main__":
    # create DB file if not exists (for quick dev)
    if not os.path.exists(DB.DB_PATH):
        DB.init_db(seed=True)
    app.run(debug=True, port=5000)
