import re

with open("core/agent_engine.py", "r") as f:
    code = f.read()

# Replace `api_key = get_secret("groq", "api_key")`
# With fetching the actual provider API key, or leaving it entirely to litellm environment vars

code = code.replace(
    'api_key = get_secret("groq", "api_key")',
    'try:\n        api_key = get_secret("llm", "api_key")\n    except KeyError:\n        try:\n            api_key = get_secret("groq", "api_key")\n        except KeyError:\n            api_key = None'
)

with open("core/agent_engine.py", "w") as f:
    f.write(code)
