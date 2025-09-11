import sys
import json

def solution(a, b):
    return a + b

if __name__ == "__main__":
    try:
        args = json.loads(sys.argv[1])
        result = solution(*args)
        # Only print exactly one JSON line
        print(json.dumps({"return": result, "printed": ""}))
    except Exception as e:
        # If something goes wrong, print JSON error object
        print(json.dumps({"error": str(e)}))
