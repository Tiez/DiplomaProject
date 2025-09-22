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
import queue
import threading
import uuid

from timeout_decorator import timeout, TimeoutError
from concurrent.futures import ThreadPoolExecutor, TimeoutError

NUM_WORKERS = 3
results_map = {}
submission_queue = queue.Queue()
queue_info = {}


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


    return render_template('admin/adminMonitoring.html', worker_count=NUM_WORKERS)



# admin system update
@app.route('/admin/system_data')
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

# List testcases for a problem
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

# Add testcase
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

# Edit testcase 
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

# Delete testcase 
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

worker_status = {}

def worker(worker_id):
    while True:
        worker_status[worker_id] = "idle"
        submission_id, user_code, problem_id = submission_queue.get()
        # print(f"[Worker] {worker_id}  Recieved submission ID: {submission_id}")
        worker_status[worker_id] = f"{submission_id}"
        try:
            result = run_submission(user_code, problem_id, submission_id)
            results_map[submission_id] = result
            # print(f"[Worker] {worker_id}  Stored result for submission IDL {submission_id}")
        except Exception as e:
            results_map[submission_id] = [{"verdict": "Error", "error": str(e)}]
            # print(f"[Worker] {worker_id}  Error in submission ID: {submission_id}: {e}")

        finally:
            submission_queue.task_done()
            # print(f"[Worker] {worker_id}  Finished submission ID: {submission_id}")
            


for i in range(NUM_WORKERS):
    threading.Thread(target=worker, args=(i,), daemon=True).start()

# ---------------- Run Submission ----------------
def run_submission(user_code, problem_id, submission_id):
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

    for case in test_cases:
        try:
            args = json.loads(case["input"])
            docker_cmd = [
                "docker", "run", "--rm",
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
            if not output_json:
               
                stdout_lines = " \n".join(stdout_lines)
                output_json = {"error":stdout_lines[58:]}
                print(stdout_lines)
                
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
                
                conn.commit()
                conn.close()




                return results
            else:
                returned_value = output_json.get("return")
                printed_output = output_json.get("printed", "")
                expected_value = json.loads(case["expected"])
                verdict = "Correct!" if returned_value == expected_value else "Wrong!"

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
            return results

    databaseInsert = {"status": 'Correct', "memory": 0, "runtime": 0.0}

    for result in results:
        if result["error"] != '':
            databaseInsert["status"] = "Error"
        elif result["verdict"] == "Time Limit Exceeded":
            databaseInsert["status"] = "Time Limit"
        elif result["verdict"] == "Wrong!":
            databaseInsert["status"] = "Wrong"


            
    # if databaseInsert["error"] == "Time Limit" or databaseInsert["error"] == "Error":
    databaseInsert["memory"] = output_json["memory"]
    databaseInsert["runtime"] = output_json["runtime"]
        # ...

    conn = get_db_connection()



    
    conn.execute(
        "UPDATE submissions SET status=?, memory=?, runtime=? WHERE UniqID = ?",
        ( databaseInsert["status"], databaseInsert["memory"], databaseInsert["runtime"], submission_id ))
    
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

# ---------------- API Route ----------------
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
        ( problem_id, user_code , submission_id ))
    
    conn.commit()
    conn.close()

    submission_queue.put((submission_id, user_code, problem_id))
    return jsonify({"submission_id": submission_id})

@app.route("/result/<submission_id>")
def get_result(submission_id):
    if submission_id not in results_map:
        return jsonify({"status": "pending"})
    return jsonify({"status": "done", "results": results_map[submission_id]})



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)