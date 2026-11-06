from google.adk.tools import FunctionTool, ToolContext


async def request_new_goal(tool_context: ToolContext) -> str:
    """Signals that the runner wants to set up a new training goal and trigger re-onboarding."""
    tool_context.state["reonboard_requested"] = True
    return "Re-onboarding initiated. Transitioning to onboarding agent to set up your new goal."


request_new_goal_tool = FunctionTool(request_new_goal)
