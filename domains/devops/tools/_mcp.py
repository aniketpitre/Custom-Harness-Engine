try:
    from mcp.server.fastmcp import FastMCP  # noqa: F401
except ModuleNotFoundError:  # mcp 2.x renamed FastMCP to MCPServer
    from mcp.server.mcpserver import MCPServer as FastMCP  # noqa: F401
