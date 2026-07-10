from google.adk.apps import App
from google.adk import Workflow
import inspect

print("App methods:")
for name, member in inspect.getmembers(App):
    if not name.startswith("__"):
        print(f"  {name}: {member}")
