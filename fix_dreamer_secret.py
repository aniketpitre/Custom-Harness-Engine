with open("core/memory/dreamer.py", "r") as f:
    code = f.read()

code = code.replace(
    'api_key = get_secret("groq", "api_key")',
    'try:\n            api_key = get_secret("llm", "api_key")\n        except KeyError:\n            try:\n                api_key = get_secret("groq", "api_key")\n            except KeyError:\n                api_key = None'
)

with open("core/memory/dreamer.py", "w") as f:
    f.write(code)
