import re

with open("core/agent_engine.py", "r") as f:
    content = f.read()

new_tool_json = """    {
        "type": "function",
        "function": {
            "name": "gitops_propose_change",
            "description": "Propose a configuration change via Pull Request. Instead of mutating the cluster directly, modify the declarative manifest. Requires approval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string"},
                    "file_path": {"type": "string"},
                    "content": {"type": "string"},
                    "branch_name": {"type": "string"},
                    "commit_message": {"type": "string"},
                    "pr_title": {"type": "string"},
                    "pr_body": {"type": "string"}
                },
                "required": ["repo_path", "file_path", "content", "branch_name", "commit_message", "pr_title", "pr_body"],
                "additionalProperties": False,
            },
        },
    },"""

if "gitops_propose_change" not in content:
    content = content.replace("DEVOPS_ACTION_TOOLS = [\n", f"DEVOPS_ACTION_TOOLS = [\n{new_tool_json}\n")


dispatch_code = """    if name == "gitops_propose_change":
        if "DevOpsWrite" not in allowed_tools:
            raise PermissionError(f"Tool is not allowed: {name}")
        from domains.devops.git_actions import resolve_gitops_route, create_change_pr
        policy_decision = resolve_gitops_route("gitops", "propose_change")
        if policy_decision.decision == "DENY":
            raise PermissionError(policy_decision.reason)
        if policy_decision.decision == "REQUIRE_APPROVAL":
            approved = await request_approval(
                action_id=action_id,
                description=f"gitops.propose_change PR: {arguments.get('pr_title')}",
                risk_tier=policy_decision.risk_tier,
            )
            if not approved:
                raise PermissionError("Human approval denied this action")
            policy_decision = PolicyDecision.model_validate(
                policy_decision.model_copy(
                    update={"decision": "ALLOW", "approved_by": get_approver(action_id)}
                )
            )
        try:
            result = create_change_pr(
                repo_path=arguments["repo_path"],
                branch_name=arguments["branch_name"],
                file_path=arguments["file_path"],
                content=arguments["content"],
                commit_message=arguments["commit_message"],
                pr_title=arguments["pr_title"],
                pr_body=arguments["pr_body"]
            )
        except Exception as e:
            result = str(e)
            
        return result, _action_record(
            policy_decision,
            result,
        )
"""

if "name == \"gitops_propose_change\"" not in content:
    content = content.replace("    if name == \"kubectl_restart_pod\":", dispatch_code + "\n    if name == \"kubectl_restart_pod\":")

with open("core/agent_engine.py", "w") as f:
    f.write(content)
