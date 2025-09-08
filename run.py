import os
import sqlite3
import importlib.util
import sys
import io
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)
SANDBOX_DIR = os.path.expanduser("~/sandbox")
os.makedirs(SANDBOX_DIR, exist_ok=True)

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

# Run user code
@app.route("/run", methods=["POST"])
def run_code():
    data = request.get_json()
    if not data or "code" not in data or "problem_id" not in data:
        return jsonify({"error": "Missing key 'code' or 'problem_id'"}), 400

    code = data["code"]
    problem_id = data["problem_id"]

    # Save user code
    file_path = os.path.join(SANDBOX_DIR, "temp.py")
    with open(file_path, "w") as f:
        f.write(code)

    # Load the user's function
    try:
        spec = importlib.util.spec_from_file_location("temp", file_path)
        temp_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(temp_module)
        user_func = getattr(temp_module, "solution")  # assumes function name 'solution'
    except Exception as e:
        print(str(e))
        return jsonify({"error": "Error loading code", "traceback": str(e)}), 400

    # Fetch test cases from DB
    conn = get_db_connection()
    test_cases = conn.execute(
        "SELECT input, expected FROM test_cases WHERE problem_id=?", (problem_id,)
    ).fetchall()
    conn.close()

    results = []

    for case in test_cases:
        try:
            args = eval(case["input"])  # convert stored string to tuple/list

            # Capture printed output
            buffer = io.StringIO()
            old_stdout = sys.stdout
            sys.stdout = buffer

            try:
                output = user_func(*args)   # call the function
            finally:
                sys.stdout = old_stdout

            printed_output = buffer.getvalue().strip()
            verdict = "Correct!" if output == eval(case["expected"]) else "Wrong!"

            results.append({
                "input": args,
                "expected": eval(case["expected"]),
                "output": output,
                "printed": printed_output,
                "verdict": verdict
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
