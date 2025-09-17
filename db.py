# db.py
import sqlite3
import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "classroom.db")

def get_connection():
    # wait up to 5 seconds for a lock before failing
    conn = sqlite3.connect(DB_PATH, timeout=5, detect_types=sqlite3.PARSE_DECLTYPES, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(seed: bool = False):
    """Create schema and optionally seed with basic admin/tutor/student and sample data."""
    conn = get_connection()
    conn.execute("PRAGMA journal_mode=WAL;")  # Better read/write concurrency
    cur = conn.cursor()
    # Users
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      email TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL,
      role TEXT NOT NULL CHECK(role IN ('admin','tutor','student')),
      created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS classes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      title TEXT NOT NULL,
      description TEXT,
      tutor_id INTEGER NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(tutor_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS enrollments (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      class_id INTEGER NOT NULL,
      user_id INTEGER NOT NULL,
      enrolled_at TEXT NOT NULL,
      FOREIGN KEY(class_id) REFERENCES classes(id) ON DELETE CASCADE,
      FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
      UNIQUE(class_id, user_id)
    );

    CREATE TABLE IF NOT EXISTS quizzes (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      class_id INTEGER NOT NULL,
      title TEXT NOT NULL,
      description TEXT,
      created_by INTEGER NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(class_id) REFERENCES classes(id) ON DELETE CASCADE,
      FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS questions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      quiz_id INTEGER NOT NULL,
      question_text TEXT NOT NULL,
      choices TEXT NOT NULL, -- JSON array
      answer_index INTEGER NOT NULL,
      points INTEGER NOT NULL DEFAULT 1,
      FOREIGN KEY(quiz_id) REFERENCES quizzes(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS submissions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      quiz_id INTEGER NOT NULL,
      student_id INTEGER NOT NULL,
      answers TEXT NOT NULL, -- JSON array of chosen index or null
      score REAL NOT NULL,
      submitted_at TEXT NOT NULL,
      FOREIGN KEY(quiz_id) REFERENCES quizzes(id) ON DELETE CASCADE,
      FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS attendance (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      class_id INTEGER NOT NULL,
      student_id INTEGER NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('present','absent','justified')),
      reason TEXT,
      marked_by INTEGER NOT NULL, -- tutor id
      marked_at TEXT NOT NULL,
      FOREIGN KEY(class_id) REFERENCES classes(id) ON DELETE CASCADE,
      FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE,
      FOREIGN KEY(marked_by) REFERENCES users(id) ON DELETE CASCADE
    );
    """)
    conn.commit()

    if seed:
        # check if admin exists
        cur.execute("SELECT id FROM users WHERE role='admin' LIMIT 1;")
        if cur.fetchone():
            conn.close()
            return
        ts = datetime.utcnow().isoformat()
        # basic password hashes will be inserted by app CLI in practice; placeholder required
        # To seed properly via script, we accept password hashes passed from caller.
        # But for convenience we'll place empty string for now and instruct user to use CLI to set admin.
        cur.execute("INSERT INTO users (name,email,password_hash,role,created_at) VALUES (?,?,?,?,?)",
                    ("Admin User","admin@example.com","", "admin", ts))
        # We will not create other sample rows with empty password_hash.
        conn.commit()
    conn.close()

# helper functions used by app.py
def create_user(name, email, password_hash, role):
    conn = get_connection()
    try:
        cur = conn.cursor()
        ts = datetime.utcnow().isoformat()
        cur.execute(
            "INSERT INTO users (name,email,password_hash,role,created_at) VALUES (?,?,?,?,?)",
            (name, email, password_hash, role, ts)
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_user_by_email(email: str) -> Optional[sqlite3.Row]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    conn.close()
    return row

def get_user_by_id(uid: int) -> Optional[sqlite3.Row]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (uid,))
    r = cur.fetchone()
    conn.close()
    return r

def create_class(title: str, description: str, tutor_id: int) -> int:
    conn = get_connection()
    cur = conn.cursor()
    ts = datetime.utcnow().isoformat()
    cur.execute("INSERT INTO classes (title,description,tutor_id,created_at) VALUES (?,?,?,?)",
                (title, description, tutor_id, ts))
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    return cid

def enroll_student(class_id: int, student_id: int) -> None:
    conn = get_connection()
    cur = conn.cursor()
    ts = datetime.utcnow().isoformat()
    try:
        cur.execute("INSERT INTO enrollments (class_id,user_id,enrolled_at) VALUES (?,?,?)",
                    (class_id, student_id, ts))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    finally:
        conn.close()

def get_classes_for_tutor(tutor_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM classes WHERE tutor_id = ?", (tutor_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def get_students_in_class(class_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
      SELECT u.* FROM users u
      JOIN enrollments e ON e.user_id = u.id
      WHERE e.class_id = ? AND u.role = 'student'
    """, (class_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def create_quiz(class_id: int, title: str, description: str, created_by: int, questions: List[Dict[str,Any]]):
    conn = get_connection()
    cur = conn.cursor()
    ts = datetime.utcnow().isoformat()
    cur.execute("INSERT INTO quizzes (class_id,title,description,created_by,created_at) VALUES (?,?,?,?,?)",
                (class_id, title, description, created_by, ts))
    qid = cur.lastrowid
    for q in questions:
        cur.execute("INSERT INTO questions (quiz_id,question_text,choices,answer_index,points) VALUES (?,?,?,?,?)",
                    (qid, q["question_text"], json.dumps(q["choices"]), q["answer_index"], q.get("points",1)))
    conn.commit()
    conn.close()
    return qid

def get_quizzes_for_class(class_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM quizzes WHERE class_id = ?", (class_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def get_quiz(quiz_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM quizzes WHERE id = ?", (quiz_id,))
    quiz = cur.fetchone()
    if not quiz:
        conn.close()
        return None
    cur.execute("SELECT * FROM questions WHERE quiz_id = ?", (quiz_id,))
    questions = cur.fetchall()
    conn.close()
    return {"quiz": quiz, "questions": questions}

def update_quiz(quiz_id: int, title: str, description: str, questions: List[Dict[str,Any]]):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE quizzes SET title=?, description=? WHERE id=?", (title, description, quiz_id))
    # naive approach: delete existing questions and re-insert; simple and safe for demo
    cur.execute("DELETE FROM questions WHERE quiz_id = ?", (quiz_id,))
    for q in questions:
        cur.execute("INSERT INTO questions (quiz_id,question_text,choices,answer_index,points) VALUES (?,?,?,?,?)",
                    (quiz_id, q["question_text"], json.dumps(q["choices"]), q["answer_index"], q.get("points",1)))
    conn.commit()
    conn.close()

def save_submission(quiz_id: int, student_id: int, answers: List[Optional[int]], score: float):
    conn = get_connection()
    cur = conn.cursor()
    ts = datetime.utcnow().isoformat()
    cur.execute("INSERT INTO submissions (quiz_id, student_id, answers, score, submitted_at) VALUES (?,?,?,?,?)",
                (quiz_id, student_id, json.dumps(answers), score, ts))
    conn.commit()
    conn.close()

def get_submissions_for_quiz(quiz_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
      SELECT s.*, u.name as student_name, u.email as student_email
      FROM submissions s JOIN users u ON u.id = s.student_id
      WHERE s.quiz_id = ?
      ORDER BY s.score DESC
    """, (quiz_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def mark_attendance(class_id: int, student_id: int, status: str, reason: Optional[str], marked_by: int):
    conn = get_connection()
    cur = conn.cursor()
    ts = datetime.utcnow().isoformat()
    # remove previous attendance for same student/class on same day? For simplicity we just insert
    cur.execute("INSERT INTO attendance (class_id,student_id,status,reason,marked_by,marked_at) VALUES (?,?,?,?,?,?)",
                (class_id, student_id, status, reason, marked_by, ts))
    conn.commit()
    conn.close()

def get_attendance_for_class(class_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
      SELECT a.*, u.name as student_name FROM attendance a
      JOIN users u ON u.id = a.student_id
      WHERE a.class_id = ?
      ORDER BY a.marked_at DESC
    """, (class_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def get_classes_for_student(student_id: int):
    """Return all classes a student is enrolled in with tutor info."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
      SELECT c.*, u.name AS tutor_name, u.email AS tutor_email
      FROM classes c
      JOIN enrollments e ON e.class_id = c.id
      JOIN users u ON u.id = c.tutor_id
      WHERE e.user_id = ?
    """, (student_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_student_attendance_summary(student_id: int):
    """Summarize attendance counts for a student across all classes."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
      SELECT c.title AS class_title,
             SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) AS presents,
             SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) AS absents,
             SUM(CASE WHEN a.status='justified' THEN 1 ELSE 0 END) AS justified
      FROM attendance a
      JOIN classes c ON c.id = a.class_id
      WHERE a.student_id = ?
      GROUP BY c.id
    """, (student_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_quizzes_for_student(student_id: int):
    """List quizzes for all classes the student is enrolled in, with submission info."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
      SELECT q.*, c.title AS class_title, c.id AS class_id, s.score AS score
      FROM quizzes q
      JOIN classes c ON c.id = q.class_id
      JOIN enrollments e ON e.class_id = c.id
      LEFT JOIN submissions s ON s.quiz_id = q.id AND s.student_id = ?
      WHERE e.user_id = ?
      ORDER BY q.created_at DESC
    """, (student_id, student_id))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_all_classes_with_students_and_quizzes():
    """Admin convenience: all classes with tutors, enrolled students count, and quiz count."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
      SELECT c.id, c.title, c.description,
             u.name AS tutor_name,
             (SELECT COUNT(*) FROM enrollments e WHERE e.class_id = c.id) AS student_count,
             (SELECT COUNT(*) FROM quizzes q WHERE q.class_id = c.id) AS quiz_count
      FROM classes c
      JOIN users u ON u.id = c.tutor_id
      ORDER BY c.created_at DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def export_submissions_csv(quiz_id: int) -> str:
    rows = get_submissions_for_quiz(quiz_id)
    lines = ["student_name,student_email,score,submitted_at"]
    for r in rows:
        lines.append(f"{r['student_name']},{r['student_email']},{r['score']},{r['submitted_at']}")
    return "\n".join(lines)

def export_attendance_csv(class_id: int) -> str:
    rows = get_attendance_for_class(class_id)
    lines = ["student_name,status,reason,marked_by,marked_at"]
    for r in rows:
        lines.append(f"{r['student_name']},{r['status']},{(r['reason'] or '')},{r['marked_by']},{r['marked_at']}")
    return "\n".join(lines)
