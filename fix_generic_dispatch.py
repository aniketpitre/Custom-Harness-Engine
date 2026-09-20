with open("core/agent_engine.py", "r") as f:
    text = f.read()

# Remove the incorrectly placed block
bad_block = '''
    if name in {"grep", "glob", "edit", "web_fetch", "web_search"}:
        if "Generic" not in allowed_tools:
            raise PermissionError(f"Tool is not allowed: {name}")
        import domains.generic.tools as gt
        if name == "grep":
            result = gt.tool_grep(arguments["pattern"], arguments.get("path", "."))
        elif name == "glob":
            result = gt.tool_glob(arguments["pattern"])
        elif name == "edit":
            result = gt.tool_edit(arguments["path"], arguments["new_content"])
        elif name == "web_fetch":
            result = gt.tool_web_fetch(arguments["url"])
        elif name == "web_search":
            result = gt.tool_web_search(arguments["query"])
        
        # Policy is generic R1
        policy_decision = PolicyDecision(tool="generic", action=name, decision="ALLOW", risk_tier="R1", reason="")
        result_spilled = _spill_if_needed(result, session_id, name)
        return result_spilled, _action_record(policy_decision, result_spilled)
        
'''

text = text.replace(bad_block, "")

# Insert it gracefully in _dispatch_tool, let's say before the catch-all read_directory
insert_point = '''    if name != "read_directory" or "Read" not in allowed_tools:
        raise PermissionError(f"Tool is not allowed: {name}")'''

good_block = '''    if name in {"grep", "glob", "edit", "web_fetch", "web_search"}:
        if "Generic" not in allowed_tools:
            raise PermissionError(f"Tool is not allowed: {name}")
        import domains.generic.tools as gt
        if name == "grep":
            result = gt.tool_grep(arguments["pattern"], arguments.get("path", "."))
        elif name == "glob":
            result = gt.tool_glob(arguments["pattern"])
        elif name == "edit":
            result = gt.tool_edit(arguments["path"], arguments["new_content"])
        elif name == "web_fetch":
            result = gt.tool_web_fetch(arguments["url"])
        elif name == "web_search":
            result = gt.tool_web_search(arguments["query"])
        
        # Policy is generic R1
        policy_decision = PolicyDecision(tool="generic", action=name, decision="ALLOW", risk_tier="R1", reason="")
        result_spilled = _spill_if_needed(result, session_id, name)
        return result_spilled, _action_record(policy_decision, result_spilled)
        
'''

text = text.replace(insert_point, good_block + insert_point)

with open("core/agent_engine.py", "w") as f:
    f.write(text)
