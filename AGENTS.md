# Project Instructions

<!-- knowledge-graph:codex begin -->
## Knowledge Graph

- Use the bundled MCP server in .mcp.json when available: start with kg_status, then kg_query or kg_read_node before editing unfamiliar modules.
- Durable module knowledge lives in canonical CLAUDE.md and SKILL.md files. AGENTS.md is only the Codex adapter that tells Codex to read those canonical nodes through MCP.
- Runtime data lives under .knowledge-graph/ and should stay uncommitted.
- If running scripts outside Claude Code, set KG_PROJECT_DIR to this project root; Claude Code may set CLAUDE_PROJECT_DIR instead.
- Before reporting success, include concrete evidence: tests run, files checked, or MCP resources consulted.
<!-- knowledge-graph:codex end -->
