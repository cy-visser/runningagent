import sys
import os
sys.path.insert(0, "/usr/local/google/home/cyvisser/source")

from running_coach.agent import app
import inspect

print("app attributes:")
for name, member in inspect.getmembers(app):
    if not name.startswith("__"):
        print(f"  {name}: {member}")
