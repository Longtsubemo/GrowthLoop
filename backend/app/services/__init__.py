"""Shared business logic.

This package is the single source of truth for GrowthLoop operations.
Both the FastAPI endpoints (``app.api``) and the MCP tools
(``mcp_server``) must call into these services; neither may implement
business rules or talk to the database on its own.
"""
