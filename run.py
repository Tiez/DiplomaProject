import os
import sqlite3
from functools import wraps
from flask import Flask, flash, redirect, url_for, render_template, request, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length
from collections import defaultdict
from datetime import datetime
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



def make_user_object(row):
    """Convert DB row to Flask-Login compatible object."""
    if not row:
        return None

    # Build a dynamic object
    user_obj = type("UserObj", (), {})()
    for key in row.keys():
        setattr(user_obj, key, row[key])

    # Flask-Login required methods
    user_obj.get_id = lambda: str(user_obj.id)
    user_obj.is_authenticated = property(lambda self: True)
    user_obj.is_active = property(lambda self: True)
    user_obj.is_anonymous = property(lambda self: False)

    return user_obj


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
    return make_user_object(row)

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

@app.route("/")
def dashboard():

    if current_user.is_authenticated:
        conn = get_db_connection()
        articles = conn.execute("SELECT * FROM news").fetchall()
        conn.close()
        return render_template("Dashboard.html", articles=articles)
    else:
        return render_template("Homepage.html")



# ---------------------- Auth Routes ----------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE email=?", (form.email.data,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], form.password.data):
            user_obj = make_user_object(user)
            login_user(user_obj)
            flash("Logged in successfully!", "success")
            return redirect(url_for("dashboard"))
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

@login_required
@app.route("/contributions/<int:id>")
def getContributions(id):
    conn = get_db_connection()
    contributions = conn.execute("SELECT contribution_date, count FROM contributions WHERE user_id = ? AND contribution_date >= '2025-01-01' AND contribution_date <= '2025-12-31' ORDER BY contribution_date;", (id,)).fetchall()
    conn.close()
    contributions_dict = defaultdict(list)
    for contribution in contributions:
        date_str, count = contribution
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        month_index = date_obj.month - 1  # 0=Jan, 11=Dec
        contributions_dict[month_index].append({"dateData": [date_obj.day, count]})
    return json.dumps(dict(contributions_dict))

@login_required
@app.route("/profile_data/<int:id>")
def profile_data(id):
    conn = get_db_connection()
    data = conn.execute("SELECT id, username, email FROM users WHERE id = ?;", (id,)).fetchone()
    conn.close()

    
    print({"userData": dict(data)})
    return jsonify({"userData": dict(data)})

@login_required
@app.route("/profile/<int:id>")
def profile(id):
    return render_template("UserProfile.html", userID={"id":id, "username":current_user.username})

@login_required
@app.route("/problemsheet")
def problemsheet():
    return render_template("ProblemSheet.html")

@app.route("/api/problems")
@login_required
def api_problems():
    # Server-side pagination and search for problemsheet
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get("per_page", 10))
    except ValueError:
        per_page = 10

    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    topics = request.args.getlist("topics")  # may be multiple

    conn = get_db_connection()
    params = []
    where_clauses = []

    # Use case-insensitive searching by lowercasing fields and parameters
    if q:
        qparam = f"%{q.lower()}%"
        where_clauses.append("(LOWER(title) LIKE ? OR LOWER(description) LIKE ?)")
        params.extend([qparam, qparam])

    # difficulty filter (case-insensitive, allow partial matches)
    if category and category.lower() != "all":
        where_clauses.append("LOWER(TRIM(diff)) LIKE ?")
        params.append(f"%{category.lower()}%")

    # detect if problems table has a 'tags' column
    cols_info = conn.execute("PRAGMA table_info(problems)").fetchall()
    cols = [c["name"] for c in cols_info]
    has_tags = "tags" in cols

    # topics filter: if tags column exists, match against it; otherwise fallback to searching title/description
    if topics:
        # normalize and remove empty
        topics = [t.strip() for t in topics if t.strip()]
        if topics:
            if has_tags:
                topic_clauses = []
                for _ in topics:
                    topic_clauses.append("LOWER(tags) LIKE ?")
                    params.append(f"%{_.lower()}%")
                where_clauses.append("(" + " OR ".join(topic_clauses) + ")")
            else:
                # fallback: search topics in LOWER(title) or LOWER(description)
                topic_clauses = []
                for _ in topics:
                    topic_clauses.append("(LOWER(title) LIKE ? OR LOWER(description) LIKE ?)")
                    params.extend([f"%{_.lower()}%", f"%{_.lower()}%"])
                where_clauses.append("(" + " OR ".join(topic_clauses) + ")")

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    # total count
    count_row = conn.execute(f"SELECT COUNT(*) as cnt FROM problems {where_sql}", params).fetchone()
    total = count_row["cnt"] if count_row else 0

    offset = (page - 1) * per_page

    # build select columns dynamically if tags exists
    select_cols = "id, title, description, diff"
    if has_tags:
        select_cols += ", tags"

    rows = conn.execute(
        f"SELECT {select_cols} FROM problems {where_sql} ORDER BY id LIMIT ? OFFSET ?",
        params + [per_page, offset]
    ).fetchall()
    conn.close()

    problems = []
    for r in rows:
        desc = r["description"] or ""
        snippet = desc if len(desc) <= 250 else desc[:247] + "..."
        problem_obj = {
            "id": r["id"],
            "title": r["title"],
            "diff": r["diff"],
            "description": snippet
        }
        if has_tags:
            problem_obj["tags"] = r["tags"] or ""
        problems.append(problem_obj)

    return jsonify({
        "total": total,
        "page": page,
        "per_page": per_page,
        "problems": problems
    })




# ---------------------- Home ----------------------

@app.route("/problem")
@login_required
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

@app.route('/admin/news', methods=['GET', 'POST'])
@admin_required
def adminNews():
    conn = get_db_connection()
    if request.method == 'POST':
        # Delete action if delete_id provided
        delete_id = request.form.get('delete_id')
        if delete_id:
            conn.execute('DELETE FROM news WHERE rowid = ?', (delete_id,))
            conn.commit()
            conn.close()
            return redirect(url_for('adminNews'))

        # Otherwise treat as create
        title = request.form.get('title')
        desc = request.form.get('desc')
        link = request.form.get('link', '')
        if title and desc:
            conn.execute('INSERT INTO news (title, desc, link) VALUES (?, ?, ?)', (title, desc, link))
            conn.commit()
            conn.close()
            return redirect(url_for('adminNews'))
    articles = conn.execute('SELECT rowid as id, title, desc, time, link FROM news ORDER BY time DESC').fetchall()
    conn.close()
    return render_template('admin/adminNews.html', articles=articles)

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
        tags = request.form.get('tags', '')
        conn = get_db_connection()
        conn.execute('INSERT INTO problems (title, description, examples, prefix, constraints, diff, tags) VALUES (?, ?, ?, ?, ?, ?, ?)',
                     (title, description, examples, prefix, constraints, diff, tags))
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
                tags = request.form.get('tags', '')
                conn.execute('UPDATE problems SET title=? , description=?, examples=?, prefix=?, constraints=?, diff=?, tags=? WHERE id=?',
                             (request.form['title'], request.form['description'], request.form['example'], request.form['prefix'],
                              request.form['constraints'], request.form['diff'], tags, id))
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

# Submission testcase answer 
@app.route("/admin/<string:subId>/testCases", methods=['GET']) 
@admin_required
def admin_SubTC(subId): 
    conn = get_db_connection() 
    tC = conn.execute('SELECT * FROM testcaseSub WHERE subID=? ', (subId,)).fetchall() 
    conn.close() 
    tC = [dict(row) for row in tC] 
    return render_template("admin/adminSubTC.html", subId=subId, subTC=tC)


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

@app.route("/admin/problem/<int:problem_id>/update_all_testcases", methods=["POST"]) 
@admin_required
def update_all_testcases(problem_id): 
    print("====================================") 
    conn = get_db_connection() 
    tcs = conn.execute("SELECT id FROM test_cases WHERE problem_id = ?", (problem_id,)).fetchall() 
    for tc in tcs: 
        tc_id = tc["id"] 
        input_data = request.form.get(f"input_{tc_id}") 
        expected_output = request.form.get(f"expected_{tc_id}") 
        if input_data is not None and expected_output is not None: 
            conn.execute( "UPDATE test_cases SET input = ?, expected = ? WHERE id = ?", (input_data, expected_output, tc_id) ) 
            conn.commit() 
            conn.close() 
            return redirect(url_for("admin_testcases", problem_id=problem_id))


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


@app.route("/userHistory/<int:userID>")
@login_required
def userHistory(userID):
    # if userID == current_user.id:
    conn = get_db_connection()
    fetchedData = conn.execute("SELECT * FROM submissions WHERE userID=? ORDER BY subTime DESC LIMIT 20", (userID,)).fetchall()
    conn.close()



    return jsonify({
        "userID": userID,
        "data": [dict(fd) for fd in fetchedData]
    })
    # return jsonify({
    #     "error": f"user ID miss match. Target id {userID}, current id {current_user.id}",

    # })


# ---------------------- Worker & Submission Queue ----------------------
NUM_WORKERS = 3
results_map = {}
submission_queue = queue.Queue()
worker_status = {}

SANDBOX_DIR = "/home/lenovo/sandbox"
DOCKER_IMAGE = "python-sandbox"

def worker(worker_id,):
    while True:
        worker_status[worker_id] = "idle"
        submission_id, user_code, problem_id, user_id = submission_queue.get()
        worker_status[worker_id] = f"{submission_id}"
        try:
            result = run_submission(user_code, problem_id, submission_id, user_id)
            results_map[submission_id] = result
        except Exception as e:
            results_map[submission_id] = [{"verdict": "Error", "error": str(e)}]
        finally:
            submission_queue.task_done()

for i in range(NUM_WORKERS):
    threading.Thread(target=worker, args=(i,), daemon=True).start()

# ---------------------- Run Submission Logic ----------------------


def run_submission(user_code, problem_id, submission_id, user_id):
    temp_file = os.path.join(SANDBOX_DIR, f"temp_{submission_id}.py")

    wrapped_code = f"""
{user_code}
if __name__ == "__main__":
        import sys, json, io, contextlib, tracemalloc, time, traceback
        start_time = time.perf_counter()
        tracemalloc.start()
        try:
            args = json.loads(sys.argv[1])
            
            with io.StringIO() as buf, contextlib.redirect_stdout(buf):
                returned_value = solution(*args)
                printed_output = buf.getvalue()
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            end_time = time.perf_counter()
            elapsed_time = end_time - start_time
            print(json.dumps({{"return": returned_value, "printed": printed_output, "memory": peak // 1024, "runtime": round(elapsed_time*1000,1)}}))
        except Exception as e:
            end_time = time.perf_counter()
            elapsed_time = end_time - start_time

            error_msg = traceback.format_exc()[250:]
            
            

            print(json.dumps({{"error": error_msg, "runtime": round(elapsed_time*1000,1)}}))
    """

    with open(temp_file, "w") as f:
        f.write(wrapped_code)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    test_cases = conn.execute(
        "SELECT input, expected FROM test_cases WHERE problem_id=?", (problem_id,)
    ).fetchall()
    conn.close()

    results = []


    conn = get_db_connection()


    conn.execute("""
    INSERT INTO contributions (user_id, contribution_date, count)
    VALUES (?, ?, 1)
    ON CONFLICT(user_id, contribution_date)
    DO UPDATE SET count = count + 1;
    """, (user_id, datetime.today().strftime('%Y-%m-%d')))
    print("=======================")
    conn.commit()
    conn.close()

    for case in test_cases:
        try:
            args = json.loads(case["input"])
            docker_cmd = [
                "docker", "run", "--memory=100m",  "--rm",
                "-v", f"{SANDBOX_DIR}:/app",
                DOCKER_IMAGE,
                "python3", f"/app/{os.path.basename(temp_file)}",
                json.dumps(args)
            ]
            completed = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=5)

            if completed.stdout:
                stdout_lines = completed.stdout.strip().splitlines()
            else:
                stdout_lines = completed.stderr.strip().splitlines()
            
            
            output_json = None

            for line in stdout_lines:
                try:
                    output_json = json.loads(line)
                    break
                except json.JSONDecodeError:


                    continue
            print("=====================")
            print(completed)

            #Memory Limit Error
            if completed.returncode == 137:
                results.append({
                    "input": args,
                    "expected": json.loads(case["expected"]),
                    "output": None,
                    "printed": "",
                    "verdict": "Memory Limit",
                    "error": ""
                })

                databaseInsert = {"memory": "Exceeded", "runtime": 0.0}

                conn = get_db_connection()
                conn.execute(
                    "UPDATE submissions SET status=?, memory=?, runtime=? WHERE UniqID = ?",
                    ( "Memory Limit", databaseInsert["memory"], databaseInsert["runtime"], submission_id ))
                
                for submissionTestCase in results:
                    print(submissionTestCase)
                    conn.execute(
                    "INSERT INTO testcaseSub (subID, input, expected, printed, output, verdict, error) VALUES(?, ?, ?, ?, ?, ?, ?)",
                    ( submission_id, str(submissionTestCase["input"]), submissionTestCase["expected"], submissionTestCase["printed"], submissionTestCase["output"], submissionTestCase["verdict"],  submissionTestCase["error"])
                    )


                conn.commit()
                conn.close()
                return results


            if not output_json:
               
                stdout_lines = " \n".join(stdout_lines)
                output_json = {"error":stdout_lines[58:]}

                
            print(output_json)

            if output_json is None:
                results.append({
                    "input": args,
                    "expected": json.loads(case["expected"]),
                    "output": "",
                    "printed": "",
                    "verdict": "Error",
                    "error": "No JSON output"
                })
                continue

            if "error" in output_json:
                verdict = "Error"
                returned_value = None
                printed_output = ""
                error_message = output_json["error"]
                results.append({
                    "input": args,
                    "expected": json.loads(case["expected"]),
                    "output": returned_value,
                    "printed": printed_output,
                    "verdict": verdict,
                    "error": error_message
                })


                databaseInsert = {"status": f'RunTime Error:\n{error_message}', "memory": 0, "runtime": 0.0}

                conn = get_db_connection()
                conn.execute(
                    "UPDATE submissions SET status=?, memory=?, runtime=?, error=? WHERE UniqID = ?",
                    ( "Error", databaseInsert["memory"], databaseInsert["runtime"], databaseInsert["status"], submission_id ))
                
                for submissionTestCase in results:
                    print(submissionTestCase)
                    conn.execute(
                    "INSERT INTO testcaseSub (subID, input, expected, printed, output, verdict, error) VALUES(?, ?, ?, ?, ?, ?, ?)",
                    ( submission_id, str(submissionTestCase["input"]), submissionTestCase["expected"], submissionTestCase["printed"], submissionTestCase["output"], submissionTestCase["verdict"],  submissionTestCase["error"])
                    )


                conn.commit()
                conn.close()


                file_to_delete = "../sandbox/temp_" + submission_id + ".py"
                try:
                    os.remove(file_to_delete)
                    print(f"File '{file_to_delete}' deleted successfully.")
                except FileNotFoundError:
                    print(f"Error: File '{file_to_delete}' not found.")
                except PermissionError:
                    print(f"Error: Permission denied to delete '{file_to_delete}'.")
                except Exception as e:
                    print(f"An unexpected error occurred: {e}")
                    # print(jsonify(results))

                return results
            else:
                returned_value = output_json.get("return")
                printed_output = output_json.get("printed", "")
                expected_value = json.loads(case["expected"])
                verdict = "correct" if returned_value == expected_value else "wrong"

                error_message = ""

            results.append({
                "input": args,
                "expected": json.loads(case["expected"]),
                "output": returned_value,
                "printed": printed_output,
                "verdict": verdict,
                "error": error_message
            })
        except subprocess.TimeoutExpired:

            results.append({
                "input": args,
                "expected": json.loads(case["expected"]),
                "output": "",
                "printed": "",
                "verdict": "Time Limit Exceeded",
                "error": ""
            })
            print("===================================================")
            print(results)
            conn = get_db_connection()

            conn.execute(
            "UPDATE submissions SET status=?, memory=?, runtime=? WHERE UniqID = ?",
            ( "Time Limit", "0.0", "", submission_id ))

            for submissionTestCase in results:
                conn.execute(
                "INSERT INTO testcaseSub (subID, input, expected, printed, output, verdict, error) VALUES(?, ?, ?, ?, ?, ?, ?)",
                ( submission_id, str(submissionTestCase["input"]), submissionTestCase["expected"], submissionTestCase["printed"], submissionTestCase["output"], submissionTestCase["verdict"],  submissionTestCase["error"])
                )
            

            conn.commit()
            conn.close()

            file_to_delete = "../sandbox/temp_" + submission_id + ".py"
            try:
                os.remove(file_to_delete)
                print(f"File '{file_to_delete}' deleted successfully.")
            except FileNotFoundError:
                print(f"Error: File '{file_to_delete}' not found.")
            except PermissionError:
                print(f"Error: Permission denied to delete '{file_to_delete}'.")
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                # print(jsonify(results))

            return results

    databaseInsert = {"status": 'correct', "memory": 0, "runtime": 0.0}

    for result in results:
        if result["error"] != '':
            databaseInsert["status"] = "Error"
        elif result["verdict"] == "Time Limit Exceeded":
            databaseInsert["status"] = "Time Limit"
        elif result["verdict"] == "wrong":
            databaseInsert["status"] = "wrong"


            
    # if databaseInsert["error"] == "Time Limit" or databaseInsert["error"] == "Error":
    databaseInsert["memory"] = output_json["memory"]
    databaseInsert["runtime"] = output_json["runtime"]
        # ...

    conn = get_db_connection()



    
    conn.execute(
        "UPDATE submissions SET status=?, memory=?, runtime=? WHERE UniqID = ?",
        ( databaseInsert["status"], databaseInsert["memory"], databaseInsert["runtime"], submission_id ))
    

    


    for submissionTestCase in results:
        print(submissionTestCase)
        conn.execute(
        "INSERT INTO testcaseSub (subID, input, expected, printed, output, verdict, error) VALUES(?, ?, ?, ?, ?, ?, ?)",
        ( submission_id, str(submissionTestCase["input"]), submissionTestCase["expected"], submissionTestCase["printed"], submissionTestCase["output"], submissionTestCase["verdict"],  submissionTestCase["error"])
        )

    
    conn.commit()
    conn.close()

    


    # Deleting used submission file 
    file_to_delete = "../sandbox/temp_" + submission_id + ".py"
    try:
        os.remove(file_to_delete)
        print(f"File '{file_to_delete}' deleted successfully.")
    except FileNotFoundError:
        print(f"Error: File '{file_to_delete}' not found.")
    except PermissionError:
        print(f"Error: Permission denied to delete '{file_to_delete}'.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        # print(jsonify(results))
    return results

# ---------------------- Submission Routes ----------------------
@login_required
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
        "INSERT INTO submissions (problem_id, code, UniqID, userID) VALUES (?, ?, ?, ?)",
        (problem_id, user_code , submission_id , current_user.id))
    
    conn.commit()
    conn.close()
    submission_queue.put((submission_id, user_code, problem_id, current_user.id))
    return jsonify({"submission_id": submission_id})

@app.route("/result/<submission_id>")
def get_result(submission_id):
    if submission_id not in results_map:
        return jsonify({"status": "pending"})
    return jsonify({"status": "done", "results": results_map[submission_id]})

# ---------------------- Main ----------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
