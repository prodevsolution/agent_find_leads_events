import sys
import traceback

try:
    with open("trace.txt", "w", encoding="utf-8") as f:
        sys.stdout = f
        sys.stderr = f
        import app
except Exception as e:
    with open("trace.txt", "a", encoding="utf-8") as f:
        traceback.print_exc(file=f)
finally:
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
