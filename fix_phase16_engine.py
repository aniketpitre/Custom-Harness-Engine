import re

with open("core/agent_engine.py", "r") as f:
    text = f.read()

# Add standard tools to schema
generic_schemas = '''
GENERIC_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Find text in files using regular expressions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string"}
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "Find files by shell wildcard pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"}
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit",
            "description": "Write or overwrite a file with new content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "new_content": {"type": "string"}
                },
                "required": ["path", "new_content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch text from a URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"}
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    }
]

'''

# Inject GENERIC_TOOLS
text = text.replace("DEVOPS_ACTION_TOOLS = [", generic_schemas + "DEVOPS_ACTION_TOOLS = [")

# Inject Spilling helper
spilling_helper = '''
def _spill_if_needed(result: str, session_id: str | None, tag: str) -> str:
    MAX_LEN = 100_000
    if len(result) <= MAX_LEN:
        return result
    
    workspace = Path(".workspace/spill")
    workspace.mkdir(parents=True, exist_ok=True)
    filename = f"{session_id or 'anon'}_{tag}_{int(datetime.now().timestamp())}.txt"
    filepath = workspace / filename
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(result)
        
    preview = result[:MAX_LEN // 2]
    return f"{preview}\\n\\n...[TRUNCATED. Full output saved to {filepath}]"
'''
text = text.replace("async def run_agent_generator(", spilling_helper + "\nasync def run_agent_generator(")


# Update run loops for generic tools
text = text.replace(
'''        if "DevOpsWrite" in allowed_tools:
            tools.extend(DEVOPS_ACTION_TOOLS)''',
'''        if "DevOpsWrite" in allowed_tools:
            tools.extend(DEVOPS_ACTION_TOOLS)
        if "Generic" in allowed_tools:
            tools.extend(GENERIC_TOOLS)'''
)

# Update budget inside generator and track tokens
generator_loop = '''
        conn = init_db() if session_id else None
        try:
            for _ in range(8):
                span.add_event(f"llm_completion_turn_{_}", {"turn_number": _})'''

new_generator_loop = '''
        conn = init_db() if session_id else None
        token_budget = 200_000 # default
        total_tokens = 0
        turn_count = 0
        try:
            while turn_count < 30 and total_tokens < token_budget:
                span.add_event(f"llm_completion_turn_{turn_count}", {"turn_number": turn_count})
                turn_count += 1'''

text = text.replace(generator_loop, new_generator_loop)

# Capture token usage
acompletion = '''                response = await litellm.acompletion(
                    model=model,
                    api_key=api_key,
                    messages=messages,
                    tools=tools or None,
                    tool_choice="auto" if tools else None,
                )
                events.append(response)'''

acompletion_new = '''                response = await litellm.acompletion(
                    model=model,
                    api_key=api_key,
                    messages=messages,
                    tools=tools or None,
                    tool_choice="auto" if tools else None,
                )
                events.append(response)
                
                # Phase 16.2 Token tracking
                if hasattr(response, "usage") and response.usage:
                    total_tokens += getattr(response.usage, "total_tokens", 0)
                
                if total_tokens >= token_budget:
                    yield {"type": "message", "content": "Token budget exceeded."}
                    yield {
                        "type": "final_receipt",
                        "receipt": {
                            "events": events.copy(),
                            "final_text": "Execution blocked: Token budget exceeded",
                            "model_used": model,
                            "actions": actions,
                            "verification": None,
                        }
                    }
                    return
'''
text = text.replace(acompletion, acompletion_new)

# Update _dispatch_tool and apply SPILL mechanism
dispatch_sig = '''async def _dispatch_tool(
    action_id: str,
    name: str,
    arguments: dict[str, Any],
    allowed_tools: list[str],
) -> tuple[str, ActionRecord]:'''

new_dispatch_sig = '''async def _dispatch_tool(
    action_id: str,
    name: str,
    arguments: dict[str, Any],
    allowed_tools: list[str],
    session_id: str | None = None,
) -> tuple[str, ActionRecord]:'''
text = text.replace(dispatch_sig, new_dispatch_sig)

call_dispatch = '''_dispatch_tool(
                        tool_call.id,
                        tool_call.function.name,
                        arguments,
                        allowed_tools,
                    )'''
new_call_dispatch = '''_dispatch_tool(
                        tool_call.id,
                        tool_call.function.name,
                        arguments,
                        allowed_tools,
                        session_id,
                    )'''
text = text.replace(call_dispatch, new_call_dispatch)

dispatch_generic = '''def _dispatch_devops_read_tool('''

generic_dispatch_block = '''
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
        from core.primitives.policy import PolicyDecision
        policy_decision = PolicyDecision(tool="generic", action=name, decision="ALLOW", risk_tier="R1", reason="")
        result_spilled = _spill_if_needed(result, session_id, name)
        return result_spilled, _action_record(policy_decision, result_spilled)
        
'''

text = text.replace(dispatch_generic, generic_dispatch_block + dispatch_generic)

# Find where we return results from _dispatch_devops_read_tool and _spill_if_needed
text = text.replace(
'''        result, policy_decision = _dispatch_devops_read_tool(name, arguments)
        return result, _action_record(policy_decision, result)''',
'''        result, policy_decision = _dispatch_devops_read_tool(name, arguments)
        result = _spill_if_needed(result, session_id, name)
        return result, _action_record(policy_decision, result)'''
)

text = text.replace(
'''        try:
            from domains.devops.tools.argocd_tools import argocd_app_sync
            result = argocd_app_sync(arguments["app_name"])
        except Exception as e:
            result = str(e)
        return result, _action_record(''',
'''        try:
            from domains.devops.tools.argocd_tools import argocd_app_sync
            result = argocd_app_sync(arguments["app_name"])
        except Exception as e:
            result = str(e)
        result = _spill_if_needed(result, session_id, name)
        return result, _action_record('''
)

with open("core/agent_engine.py", "w") as f:
    f.write(text)

