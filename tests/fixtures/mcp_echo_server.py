try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # mcp 2.x renamed FastMCP
    from mcp.server.mcpserver import MCPServer as FastMCP

mcp = FastMCP("echo")


@mcp.tool()
def get_greeting(name: str) -> str:
    """Read-only greeting."""
    return f"hello {name}"


@mcp.tool()
def set_flag(name: str) -> str:
    """Mutating tool."""
    return f"flag {name} set"


if __name__ == "__main__":
    mcp.run()
