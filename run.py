import os
import sqlite3
from functools import wraps
from flask import Flask, flash, redirect, url_for, render_template, request, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length
import psutil
import subprocess
import json
import queue
import threading
import uuid

# ---------------------- Flask App ----------------------
app = Flask(__name__)
app.secret_key = 'andir'
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates/ProblemDB.db")

# ---------------------- Login Manager ----------------------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# ---------------------- Admin Protection ----------------------
def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not getattr(current_user, "is_admin", 0):
            flash("Admin access only!", "danger")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated_function

@app.before_request
def require_admin_for_admin_prefix():
    if request.path.startswith("/admin"):
        if not current_user.is_authenticated:
            return redirect(url_for("login", next=request.path))
        if not getattr(current_user, "is_admin", 0):
            flash("Admin access only!", "danger")
            return redirect(url_for("index"))

# ---------------------- DB Connection ----------------------
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ---------------------- User Loader ----------------------
@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    if row:
        return type("UserObj", (), dict(row))()
    return None

# ---------------------- Forms ----------------------
class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")

class RegistrationForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(3, 20)])
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired(), Length(6)])
    confirm_password = PasswordField("Confirm Password", validators=[DataRequired(), EqualTo("password")])
    submit = SubmitField("Register")

# ---------------------- Auth Routes ----------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE email=?", (form.email.data,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], form.password.data):
            user_obj = type("UserObj", (), dict(user))()
            user_obj.is_authenticated = True
            user_obj.is_active = True
            user_obj.is_anonymous = False
            user_obj.get_id = lambda: str(user_obj.id)
            login_user(user_obj)
            flash("Logged in successfully!", "success")
            return redirect(url_for("index"))
        flash("Invalid credentials", "danger")
    return render_template("Auth/Login.html", form=form)

@app.route("/register", methods=["GET", "POST"])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        conn = get_db_connection()
        existing = conn.execute("SELECT * FROM users WHERE email=?", (form.email.data,)).fetchone()
        if existing:
            flash("Email already registered!", "danger")
            conn.close()
            return redirect(url_for("register"))
        password_hash = generate_password_hash(form.password.data)
        conn.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
            (form.username.data, form.email.data, password_hash)
        )
        conn.commit()
        conn.close()
        flash("Registration successful! Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("Auth/Registeration.html", form=form)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out", "info")
    return redirect(url_for("login"))

# ---------------------- Home ----------------------
@app.route("/")
def index():
    return render_template("index.html")

# ---------------------- Admin Routes ----------------------
@app.route("/admin/problems")
@admin_required
def adminProblem():
    conn = get_db_connection()
    problems = conn.execute('SELECT * FROM problems').fetchall()
    conn.close()
    return render_template("admin/adminProblems.html", problems=problems)

@app.route('/admin/problems/add', methods=['GET', 'POST'])
@admin_required
def add_problem():
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        examples = request.form['example']
        prefix = request.form['prefix']
        constraints = request.form['constraints']
        diff = request.form['diff']
        conn = get_db_connection()
        conn.execute('INSERT INTO problems (title, description, examples, prefix, constraints, diff) VALUES (?, ?, ?, ?, ?, ?)',
                     (title, description, examples, prefix, constraints, diff))
        conn.commit()
        conn.close()
        return redirect(url_for('adminProblem'))
    return render_template('admin/adminProblems.html', problems=[], add=True)

@app.route('/admin/problems/edit/<int:id>', methods=["GET", "POST"])
@admin_required
def edit_problem(id):
    conn = get_db_connection()
    problems = [dict(row) for row in conn.execute('SELECT * FROM problems WHERE id = ?', (id,)).fetchall()]
    testcases = [dict(row) for row in conn.execute('SELECT * FROM test_cases WHERE problem_id = ?', (id,)).fetchall()]
    if request.method == "POST":
        for problem in problems:
            if problem['id'] == id:
                conn.execute('UPDATE problems SET title=? , description=?, examples=?, prefix=?, constraints=?, diff=? WHERE id=?',
                             (request.form['title'], request.form['description'], request.form['example'], request.form['prefix'],
                              request.form['constraints'], request.form['diff'], id))
                conn.commit()
                conn.close()
                return redirect(url_for('adminProblem'))
    return render_template('admin/adminProblems.html', testcases=testcases, problem_id=id, edits=True)

@app.route('/admin/problems/delete/<int:id>')
@admin_required
def delete_problem(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM problems WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('adminProblem'))

@app.route('/admin/submissions')
@admin_required
def adminSubmissions():
    conn = get_db_connection()
    submissions = conn.execute('SELECT * FROM submissions ORDER BY subTime DESC').fetchall()
    conn.close()
    submissions = [dict(row) for row in submissions]
    return render_template('admin/adminSub.html', submissions=submissions)

@app.route('/admin/system')
@admin_required
def adminSystem():
    return render_template('admin/adminMonitoring.html', worker_count=NUM_WORKERS)

@app.route('/admin/system_data')
@admin_required
def adminsystemupdate():
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory().percent
    return jsonify({
        "cpu": cpu,
        "mem": mem,
        "workerStats": worker_status,
        "queue": submission_queue.qsize(),
        "pending_submissions": list(submission_queue.queue)[:10]
    })

@app.route("/admin/problem/<int:problem_id>/testcases")
@admin_required
def admin_testcases(problem_id):
    conn = get_db_connection()
    problem = conn.execute("SELECT * FROM problems WHERE id = ?", (problem_id,)).fetchone()
    testcases = conn.execute("SELECT * FROM test_cases WHERE problem_id = ?", (problem_id,)).fetchall()
    conn.close()
    if problem is None:
        return f"⚠️ Problem with id {problem_id} not found", 404
    return render_template("admin/adminTestcases.html", problem=problem, testcases=testcases, id=problem_id)

@app.route("/admin/problem/<int:problem_id>/testcases/add", methods=["POST"])
@admin_required
def add_testcase(problem_id):
    input_data = request.form["input_data"]
    expected_output = request.form["expected_output"]
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO test_cases (problem_id, input, expected) VALUES (?, ?, ?)",
        (problem_id, input_data, expected_output)
    )
    conn.commit()
    conn.close()
    return redirect(url_for("admin_testcases", problem_id=problem_id))

@app.route("/admin/problem/<int:problem_id>/testcases/<int:testcase_id>/edit", methods=["POST"])
@admin_required
def edit_testcase(problem_id, testcase_id):
    input_data = request.form["input_data"]
    expected_output = request.form["expected_output"]
    conn = get_db_connection()
    conn.execute(
        "UPDATE test_cases SET input = ?, expected = ? WHERE id = ?",
        (input_data, expected_output, testcase_id)
    )
    conn.commit()
    conn.close()
    return redirect(url_for("admin_testcases", problem_id=problem_id))

@app.route("/admin/problem/<int:problem_id>/testcases/<int:testcase_id>/delete", methods=["POST"])
@admin_required
def delete_testcase(problem_id, testcase_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM test_cases WHERE id = ?", (testcase_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_testcases", problem_id=problem_id))

# ---------------------- User & Problem APIs ----------------------
@app.route("/problems")
def get_problems():
    conn = get_db_connection()
    problems = conn.execute("SELECT * FROM problems").fetchall()
    conn.close()
    return jsonify([dict(row) for row in problems])

@app.route("/problem/<int:id>")
def get_problem(id):
    conn = get_db_connection()
    problem = conn.execute("SELECT * FROM problems WHERE id=?", (id,)).fetchone()
    test_cases = conn.execute("SELECT * FROM test_cases WHERE problem_id=?", (id,)).fetchall()
    conn.close()
    return jsonify({
        "problem": dict(problem),
        "test_cases": [dict(tc) for tc in test_cases]
    })

# ---------------------- Worker & Submission Queue ----------------------
NUM_WORKERS = 3
results_map = {}
submission_queue = queue.Queue()
worker_status = {}

SANDBOX_DIR = "/home/lenovo/sandbox"
DOCKER_IMAGE = "python-sandbox"

def worker(worker_id):
    while True:
        worker_status[worker_id] = "idle"
        submission_id, user_code, problem_id = submission_queue.get()
        worker_status[worker_id] = f"{submission_id}"
        try:
            result = run_submission(user_code, problem_id, submission_id)
            results_map[submission_id] = result
        except Exception as e:
            results_map[submission_id] = [{"verdict": "Error", "error": str(e)}]
        finally:
            submission_queue.task_done()

for i in range(NUM_WORKERS):
    threading.Thread(target=worker, args=(i,), daemon=True).start()

# ---------------------- Run Submission Logic ----------------------
def run_submission(user_code, problem_id, submission_id):
    # Your existing run_submission code here
    # Including writing temp file, docker execution, result parsing, database inserts
    pass  # For brevity, insert all of your original run_submission logic here

# ---------------------- Submission Routes ----------------------
@app.route("/run", methods=["POST"])
def run_code():
    data = request.get_json()
    if not data or "code" not in data or "problem_id" not in data:
        return jsonify({"error": "Missing 'code' or 'problem_id'"}), 400
    submission_id = str(uuid.uuid4())
    user_code = data["code"]
    problem_id = data["problem_id"]
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO submissions (problem_id, code, UniqID) VALUES (?, ?, ?)",
        (problem_id, user_code , submission_id ))
    conn.commit()
    conn.close()
    submission_queue.put((submission_id, user_code, problem_id))
    return jsonify({"submission_id": submission_id})

@app.route("/result/<submission_id>")
def get_result(submission_id):
    if submission_id not in results_map:
        return jsonify({"status": "pending"})
    return jsonify({"status": "done", "results": results_map[submission_id]})

# ---------------------- Main ----------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
