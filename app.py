import json, sqlite3, hashlib, random, string, io
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from openpyxl import Workbook

app = Flask(__name__)
app.secret_key = "kg-academy-arabic-2026"
DB_PATH = "cefr_test.db"

CENTERS = [
    "KG Academy - Al-Khuwair", "KG Academy - Galah", "KG Academy - Salalah",
    "KG Academy - Nimr", "KG Academy - Sohar", "KG Academy - Sur",
    "KG Academy - Suwaiq", "KG Academy - Rima", "KG Academy - Marmul", "KG Academy - Fahud",
]

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(pw): return hashlib.sha256(pw.encode()).hexdigest()

def generate_user_id():
    year = datetime.now().year
    while True:
        suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
        uid = f"KG-AR-{year}-{suffix}"
        conn = get_db()
        if not conn.execute("SELECT id FROM users WHERE user_id=?", (uid,)).fetchone():
            conn.close()
            return uid
        conn.close()

def get_cefr_mapping(score):
    mapping = [
        (0, 2, "A1", "Module 1: Beginners - 1"), (3, 4, "A1", "Module 2: Beginners - 2"),
        (5, 6, "A2", "Module 3: Elementary - 1"), (7, 8, "A2", "Module 4: Elementary - 2"),
        (9, 10, "B1", "Module 5: Pre-Intermediate - 1"), (11, 12, "B1", "Module 6: Pre-Intermediate - 2"),
        (13, 14, "B2", "Module 7: Intermediate - 1"), (15, 17, "B2", "Module 8: Intermediate - 2"),
        (18, 20, "C1", "Module 9: Upper-Intermediate - 1"), (21, 25, "C2", "Module 10: Upper-Intermediate - 2"),
    ]
    for low, high, level, module in mapping:
        if low <= score <= high: return level, module
    return "N/A", "N/A"

def get_questions():
    conn = get_db()
    rows = conn.execute("SELECT * FROM questions ORDER BY question_number").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.template_filter('format_time')
def format_time_filter(seconds):
    if not seconds: return "-"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}h {m}m" if h > 0 else f"{m}m {s}s"

# --- Student Routes ---
@app.route("/")
def index():
    return render_template("index.html", centers=CENTERS)

@app.route("/start", methods=["POST"])
def start():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    center = request.form.get("center", "").strip()

    if not name or not email or not phone or not center:
        flash("يرجى ملء جميع الحقول المطلوبة.", "error")
        return redirect(url_for("index"))

    user_id = generate_user_id()
    conn = get_db()
    conn.execute("INSERT INTO users (user_id, name, email, phone, center) VALUES (?, ?, ?, ?, ?)",
                 (user_id, name, email, phone, center))
    conn.commit()
    conn.close()

    session["user_id"] = user_id
    session["user_name"] = name
    session["user_email"] = email
    session["user_phone"] = phone
    session["user_center"] = center
    session["test_started_at"] = datetime.now().isoformat()
    return redirect(url_for("test"))

@app.route("/test")
def test():
    if "user_id" not in session: return redirect(url_for("index"))
    return render_template("test.html", questions=get_questions(), user_name=session["user_name"], user_id=session["user_id"])

@app.route("/submit", methods=["POST"])
def submit():
    if "user_id" not in session: return redirect(url_for("index"))
    questions = get_questions()
    answers, score = {}, 0
    s1 = s2 = s3 = s4 = 0

    for q in questions:
        qid = str(q["question_number"])
        selected = request.form.get(f"q{qid}", "").upper()
        answers[qid] = selected
        if selected == q["correct_answer"]:
            score += 1
            if q["section"] == 1: s1 += 1
            elif q["section"] == 2: s2 += 1
            elif q["section"] == 3: s3 += 1
            else: s4 += 1

    level, module = get_cefr_mapping(score)
    started_at = datetime.fromisoformat(session.get("test_started_at", datetime.now().isoformat()))
    time_taken = int((datetime.now() - started_at).total_seconds())

    conn = get_db()
    conn.execute("""INSERT INTO attempts (user_id, user_name, user_email, user_phone, center,
        total_score, cefr_level, module_assigned, section1_score, section2_score, section3_score, section4_score,
        answers, started_at, time_taken_seconds)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (session["user_id"], session["user_name"], session["user_email"], session["user_phone"],
         session["user_center"], score, level, module, s1, s2, s3, s4, json.dumps(answers),
         started_at.isoformat(), time_taken))
    conn.commit()
    conn.close()
    session.clear()
    return render_template("results.html", score=score, total=len(questions), level=level, module=module, s1=s1, s2=s2, s3=s3, s4=s4)

# --- Admin Routes ---
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = get_db()
        admin = conn.execute("SELECT * FROM admins WHERE email=? AND password_hash=?", (email, hash_password(password))).fetchone()
        conn.close()
        if admin:
            session["admin_email"] = email
            session["admin_name"] = admin["full_name"] or email
            flash("تم تسجيل الدخول بنجاح.", "success")
            return redirect(url_for("admin"))
        flash("البريد الإلكتروني أو كلمة المرور غير صحيحة.", "error")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_email", None)
    return redirect(url_for("admin_login"))

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "admin_email" not in session: return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/admin")
@admin_required
def admin():
    conn = get_db()
    attempts = conn.execute("SELECT * FROM attempts ORDER BY completed_at DESC").fetchall()
    conn.close()
    return render_template("admin.html", attempts=[dict(a) for a in attempts])

@app.route("/admin/view/<int:attempt_id>")
@admin_required
def view_attempt(attempt_id):
    conn = get_db()
    attempt = conn.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
    conn.close()
    if not attempt: return redirect(url_for("admin"))
    answers = json.loads(attempt["answers"]) if attempt["answers"] else {}
    review = []
    for q in get_questions():
        qid = str(q["question_number"])
        user_ans = answers.get(qid, "-")
        review.append({"number": q["question_number"], "text": q["question_text"], "user_answer": user_ans, "correct_answer": q["correct_answer"], "is_correct": user_ans == q["correct_answer"]})
    return render_template("admin_view.html", attempt=dict(attempt), review=review)

@app.route("/admin/enroll/<int:attempt_id>", methods=["POST"])
@admin_required
def enroll_student(attempt_id):
    conn = get_db()
    conn.execute("UPDATE attempts SET enrolled = 1 WHERE id = ?", (attempt_id,))
    conn.commit()
    conn.close()
    flash("تم تسجيل الطالب بنجاح.", "success")
    return redirect(url_for("admin"))

@app.route("/admin/export")
@admin_required
def export_excel():
    conn = get_db()
    attempts = conn.execute("SELECT * FROM attempts ORDER BY completed_at DESC").fetchall()
    conn.close()
    wb = Workbook()
    ws = wb.active
    ws.title = "النتائج"
    ws.append(["التاريخ", "رقم المستخدم", "الاسم", "البريد", "الهاتف", "الفرع", "النتيجة", "المستوى", "الوحدة", "الوقت", "مسجل"])
    for a in attempts:
        ws.append([a["completed_at"], a["user_id"], a["user_name"], a["user_email"], a["user_phone"], a["center"], a["total_score"], a["cefr_level"], a["module_assigned"], format_time_filter(a["time_taken_seconds"]), "نعم" if a["enrolled"] else "لا"])
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", as_attachment=True, download_name=f"KG_Arabic_Results_{datetime.now().strftime('%Y%m%d')}.xlsx")

@app.route("/admin/reset-data", methods=["POST"])
@admin_required
def reset_data():
    conn = get_db()
    conn.execute("DELETE FROM attempts")
    conn.execute("DELETE FROM users")
    conn.commit()
    conn.close()
    flash("تم مسح جميع سجلات الطلاب.", "success")
    return redirect(url_for("admin"))

@app.route("/admin/change-password", methods=["POST"])
@admin_required
def admin_change_password():
    current = request.form.get("current_password", "")
    new_pw = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    if new_pw != confirm:
        flash("كلمات المرور الجديدة غير متطابقة.", "error")
        return redirect(url_for("admin"))
    if len(new_pw) < 6:
        flash("يجب أن تكون كلمة المرور 6 أحرف على الأقل.", "error")
        return redirect(url_for("admin"))

    conn = get_db()
    admin = conn.execute(
        "SELECT * FROM admins WHERE email=? AND password_hash=?",
        (session["admin_email"], hash_password(current))
    ).fetchone()
    
    if not admin:
        flash("كلمة المرور الحالية غير صحيحة.", "error")
    else:
        conn.execute(
            "UPDATE admins SET password_hash=? WHERE email=?",
            (hash_password(new_pw), session["admin_email"])
        )
        conn.commit()
        flash("تم تحديث كلمة المرور بنجاح.", "success")
    conn.close()
    return redirect(url_for("admin"))

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001) # Changed port to 5001 so it doesn't conflict with English app