import re

with open("core/agent_engine.py", "r") as f:
    code = f.read()

# 1. Add tool definition to load_skill_tool definition area
write_and_register_tool_def = """
WRITE_AND_REGISTER_TOOL = {
    "type": "function",
    "function": {
        "name": "write_and_register_tool",
        "description": "RISK TIER 3: Write a Python tool dynamically and hot-swap it into the Harness Engine. The new tool is available on the next turn. Requires human approval. Provide the schema definition and the execute(args: dict) -> str function body as python code.",
        "parameters": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string"
                },
                "python_code": {
                    "type": "string",
                    "description": "Valid Python code defining `TOOL_SCHEMA: dict` and `async def execute(arguments: dict) -> str:`"
                }
            },
            "required": ["tool_name", "python_code"],
            "additionalProperties": False
        }
    }
}
"""

if "WRITE_AND_REGISTER_TOOL =" not in code:
    code = code.replace("LOAD_SKILL_TOOL = {", write_and_register_tool_def + "\nLOAD_SKILL_TOOL = {")

# 2. Automatically grant `write_and_register_tool` if they have "Generic" or "SelfEdit" capabilities.
# In `run_agent_generator`
if "tools = [LOAD_SKILL_TOOL]" in code and "write_and_register_tool" not in code.split("tools = [LOAD_SKILL_TOOL]")[1][:200]:
    new_tools_assignment = """            from core.plugins.registry import load_dynamic_tools, dynamic_tool_schemas
            load_dynamic_tools()
            tools = [LOAD_SKILL_TOOL, WRITE_AND_REGISTER_TOOL]
            tools.extend(dynamic_tool_schemas)"""
    code = code.replace("tools = [LOAD_SKILL_TOOL]", new_tools_assignment)
    
with open("core/agent_engine.py", "w") as f:
    f.write(code)
