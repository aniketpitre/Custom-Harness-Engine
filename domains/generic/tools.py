import subprocess
import glob
import re
import urllib.request
import json
from typing import Any
from pathlib import Path

def tool_grep(pattern: str, path: str = ".") -> str:
    """Find text in files using grep."""
    try:
        # Use recursion and line numbers
        res = subprocess.run(
            ["grep", "-rnI", pattern, path],
            capture_output=True,
            text=True,
            timeout=10
        )
        return res.stdout if res.stdout else (res.stderr or "No matches found.")
    except Exception as e:
        return str(e)

def tool_glob(pattern: str) -> str:
    """Find files matching shell pattern."""
    files = glob.glob(pattern, recursive=True)
    return "\n".join(files) if files else "No files matched."

def tool_edit(path: str, new_content: str) -> str:
    """Write/overwrite a file entirely."""
    try:
        filepath = Path(path)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(new_content)
        return f"File {path} successfully written."
    except Exception as e:
        return str(e)

def tool_web_fetch(url: str) -> str:
    """Fetch raw text from a given URL."""
    try:
        if not url.startswith("http"):
            url = "http://" + url
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8')
            return html[:100000] # Return up to 100k roughly
    except Exception as e:
        return f"Error fetching URL: {str(e)}"
        
def tool_web_search(query: str) -> str:
    """Mock web search for isolated tests without api keys."""
    # Since we can't reliably call a real search engine in test contexts without API keys, we return a mock or duckduckgo html parse fallback.
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8')
            # very naive extraction of links
            links = re.findall(r'class="result__url"[^>]*>([^<]*)', html)
            snippets = re.findall(r'class="result__snippet[^>]*>([^<]*)', html)
            if not links:
                return "No search results found or blocked."
            out = []
            for l, s in zip(links, snippets):
                out.append(f"URL: {l.strip()}\nSummary: {s.strip()}\n")
            return "\n".join(out)
    except Exception as e:
        return f"Search engine unreachable: {str(e)}"
import urllib.parse
