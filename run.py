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
SANDBOX_DIR = "/home/lenovo/sandbox"  # updated folder
DOCKER_IMAGE = "python-sandbox"       # Docker image name you built

@app.route("/run", methods=["POST"])
def run_code():
    import subprocess, json, time, os
    data = request.get_json()
    if not data or "code" not in data or "problem_id" not in data:
        return jsonify({"error": "Missing key 'code' or 'problem_id'"}), 400

    code = "import sys\nimport json\n"+ data["code"] +"\n    return 4\n\n\nif __name__ == \"__main__\":\n    try:\n        args = json.loads(sys.argv[1])\n        result = solution(*args)\n        print(json.dumps({\"return\": result, \"printed\": \"\"}))\n    except Exception as e:\n        print(json.dumps({\"error\": str(e)}))"



    problem_id = data["problem_id"]

    # Save user code to sandbox folder
    file_path = os.path.join(SANDBOX_DIR, "temp.py")
    with open(file_path, "w") as f:
        f.write(code)

    # Fetch test cases from DB
    conn = get_db_connection()
    test_cases = conn.execute(
        "SELECT input, expected FROM test_cases WHERE problem_id=?", (problem_id,)
    ).fetchall()
    conn.close()

    results = []

    for case in test_cases:

        try:
            args = json.loads(case["input"])  # parse test case input

            docker_cmd = [
                "docker", "run", "--rm",
                "-v", f"{SANDBOX_DIR}:/app",
                "--cpuset-cpus=0-3",          # limit to 25% of each core per container
                "--cpu-period=100000",
                "--cpu-quota=25000",
                "--memory=100m",              # limit memory to 100MB
                "--memory-swap=100m",         # no swap beyond 100MB
                "python-sandbox",
                "python3", "-u", "/app/temp.py",
                json.dumps(args)
            ]



            start_time = time.perf_counter()
            completed = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=4  # 2-second limit per test
            )
            end_time = time.perf_counter()
            runtime = round((end_time - start_time) * 1000)

            # Robust JSON parsing: ignore lines that aren't valid JSON
            stdout_lines = completed.stdout.strip().splitlines()
            output_json = None
            for line in stdout_lines:
                try:
                    output_json = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue

            if output_json is None:
                raise ValueError(f"No valid JSON output from user code. Stdout:\n{completed.stdout}")

            returned_value = output_json.get("return")
            printed_output = output_json.get("printed", "")


            expected_value = json.loads(case["expected"])
            verdict = "Correct!" if returned_value == expected_value else "Wrong!"
            # Insert submission into DB
            conn = get_db_connection()
            conn.execute(
                "INSERT INTO submissions (code, runtime, memory, status, problem_id) VALUES (?, ?, ?, ?, ?)",
                (code, runtime, 0, verdict, problem_id)
            )
            conn.commit()
            conn.close()

            results.append({
                "input": args,
                "expected": expected_value,
                "output": returned_value,
                "printed": printed_output,
                "verdict": verdict,
                "runtime": runtime
            })

        except subprocess.TimeoutExpired:
            results.append({
                "input": args,
                "expected": case["expected"],
                "output": "",
                "printed": "",
                "verdict": "Time Limit Exceeded",
                "runtime": 2
            })
        except Exception as e:
            results.append({
                "input": case["input"],
                "expected": case["expected"],
                "output": "",
                "printed": "",
                "verdict": "Error",
                "error": str(e)
            })
    return jsonify(results)




if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
