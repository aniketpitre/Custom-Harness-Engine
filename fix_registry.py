with open("core/plugins/registry.py", "r") as f:
    text = f.read()

fixed = text.replace(
    '            dynamic_tool_schemas.append(schema)',
    '''            if "type" not in schema:
                schema = {"type": "function", "function": schema}
            dynamic_tool_schemas.append(schema)'''
)

with open("core/plugins/registry.py", "w") as f:
    f.write(fixed)
