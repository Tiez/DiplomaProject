import os
import sqlite3
import importlib.util
import sys
import io
from flask import Flask, request, jsonify, render_template, redirect, url_for
import psutil
import time
import subprocess
import json
import resource
import tracemalloc
import math
from timeout_decorator import timeout, TimeoutError
from concurrent.futures import ThreadPoolExecutor, TimeoutError




app = Flask(__name__)
SANDBOX_DIR = os.path.expanduser("~/sandbox")
os.makedirs(SANDBOX_DIR, exist_ok=True)
TIME_LIMIT = 3


DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates/ProblemDB.db")

# Connect to DB
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Home page
@app.route("/")
def index():
    return render_template("index.html")

# Admin Page Problems
@app.route("/admin/problems")
def adminProblem():
    conn = get_db_connection()
    problems = conn.execute('SELECT * FROM problems').fetchall()
    conn.close()
    return render_template("admin/adminProblems.html", problems=problems)


# admin add problem
@app.route('/admin/problems/add', methods=['GET', 'POST'])
def add_problem():
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        conn = get_db_connection()
        conn.execute('INSERT INTO problems (title, description) VALUES (?, ?)',
                     (title, description))
        conn.commit()
        conn.close()
        return redirect(url_for('adminProblem'))
    return render_template('admin/adminProblems.html', problems=[], add=True)

# admin edit problem
@app.route('/admin/problems/edit/<int:id>', methods=["GET", "POST"])
def edit_problem(id):

    conn = get_db_connection()
    problems = [dict(row) for row in conn.execute('SELECT * FROM problems WHERE id = ?', (id,)).fetchall()]
    testcases = [dict(row) for row in conn.execute('SELECT * FROM test_cases WHERE problem_id = ?', (id,)).fetchall()]

    if request.method == "POST":


         for problem in problems:
             if problem['id'] == id:

                 title = request.form['title']
                 description = request.form['description']
                 conn.execute('UPDATE problems SET title = ?, description = ? WHERE id = ?', ( title, description, id))

                 conn.commit()
                 conn.close()
                 return(redirect(url_for('adminProblem')))
                 break

    return render_template('admin/adminProblems.html',testcases=testcases,problem_id=id, edit=True)

# admin delete problem
@app.route('/admin/problems/delete/<int:id>')
def delete_problem(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM problems WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('adminProblem'))

# admin submission
@app.route('/admin/submissions')
def adminSubmissions():
    conn = get_db_connection()
    submissions = conn.execute('SELECT * FROM submissions ORDER BY subTime DESC').fetchall()
    conn.close()
    submissions = [dict(row) for row in submissions]
    return render_template('admin/adminSub.html', submissions=submissions)


# admin system monitoring
@app.route('/admin/system')
def adminSystem():

   

    return render_template('admin/adminMonitoring.html')
# admin system update
@app.route('/admin/system_data')
def adminsystemupdate():

    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory().percent

    return jsonify({
        "cpu": cpu,
        "mem": mem,
    })



# Get all problems
@app.route("/problems")
def get_problems():
    conn = get_db_connection()
    problems = conn.execute("SELECT * FROM problems").fetchall()
    conn.close()
    return jsonify([dict(row) for row in problems])

# Get a single problem and its test cases
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


# --- List testcases for a problem ---
@app.route("/admin/problem/<int:problem_id>/testcases")
def admin_testcases(problem_id):
    conn = get_db_connection()
    conn.commit()
    problem = conn.execute("SELECT * FROM problems WHERE id = ?", (problem_id,)).fetchone()
    testcases = conn.execute("SELECT * FROM test_cases WHERE problem_id = ?", (problem_id,)).fetchall()

    conn.close()

    if problem is None:
        return f"⚠️ Problem with id {problem_id} not found", 404
    return render_template("admin/adminTestcases.html", problem=problem, testcases=testcases, id=problem_id)

# --- Add testcase ---
@app.route("/admin/problem/<int:problem_id>/testcases/add", methods=["POST"])
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

# --- Edit testcase ---
@app.route("/admin/problem/<int:problem_id>/testcases/<int:testcase_id>/edit", methods=["POST"])
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

# --- Delete testcase ---
@app.route("/admin/problem/<int:problem_id>/testcases/<int:testcase_id>/delete", methods=["POST"])
def delete_testcase(problem_id, testcase_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM test_cases WHERE id = ?", (testcase_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_testcases", problem_id=problem_id))




# Run user code
@app.route("/run", methods=["POST"])
def run_code():
    data = request.get_json()
    if not data or "code" not in data or "problem_id" not in data:
        return jsonify({"error": "Missing key 'code' or 'problem_id'"}), 400

    code = data["code"]
    problem_id = data["problem_id"]

    # Save user code
    user_file = os.path.join(SANDBOX_DIR, "temp.py")
    with open(user_file, "w") as f:
        f.write(code)

    # Fetch test cases from DB
    conn = get_db_connection()
    test_cases = conn.execute(
        "SELECT input, expected FROM test_cases WHERE problem_id=?", (problem_id,)
    ).fetchall()
    conn.close()

    results = []

    for case in test_cases:
        args = eval(case["input"])

        try:
            # Clear cached module to reload fresh code
            if "temp" in sys.modules:
                del sys.modules["temp"]

            spec = importlib.util.spec_from_file_location("temp", user_file)
            temp_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(temp_module)
            user_func = getattr(temp_module, "solution")

            # Capture printed output
            buffer = io.StringIO()
            old_stdout = sys.stdout
            sys.stdout = buffer

            # Measure runtime and memory
            tracemalloc.start()
            start_time = time.perf_counter()

            try:
                if isinstance(args, (tuple, list)):
                    output = user_func(*args)
                else:
                    output = user_func(args)
                verdict = "Correct!" if output == eval(case["expected"]) else "Wrong!"
            except Exception as e:
                output = None
                verdict = f"Runtime Error: {str(e)}"

            end_time = time.perf_counter()
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            memory_kb = round(peak / 1024)
            runtime = round((end_time - start_time)*1000)


            printed_output = buffer.getvalue().strip()
            sys.stdout = old_stdout

        except Exception as e:
            output = None
            printed_output = ""
            runtime = 0
            memory_kb = 0
            verdict = f"Runtime Error: {str(e)}"
            sys.stdout = old_stdout

        # Append result for this test case
        results.append({
            "input": args,
            "expected": eval(case["expected"]),
            "output": output,
            "printed": printed_output,
            "verdict": verdict,
            "runtime": math.floor(runtime*1000),
            "memory_kb": math.floor(memory_kb)
        })
        # Insert into DB
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO submissions (code, runtime, memory, status, problem_id) VALUES (?, ?, ?, ?, ?)",
            (code, runtime, memory_kb, verdict, problem_id)
        )
        conn.commit()
        conn.close()

    return jsonify(results)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
