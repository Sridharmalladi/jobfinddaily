<div align="center">

# jobfinddaily

**Find relevant remote AI and ML roles, then keep your application pipeline in view.**

</div>

A local MCP server for discovering startup roles, checking requirements, finding verified hiring contacts, and tracking applications. Filtering and scoring are deterministic; no LLM is used to rank jobs.

## Tools

- **Discover:** find, filter, and score jobs from Hacker News, RemoteOK, and startup job boards
- **Research:** extract a role's skills and AI stack; find hiring contacts with confirmed roles
- **Track:** save jobs and move applications through stages with follow-up reminders

The default filters emphasize junior-friendly remote AI/ML roles and sponsorship details. Adjust the scoring weights in `tools/scoring.py`. Search results cache for 24 hours; contact lookups cache for 7 days.

## Set up

Requires Python 3.11+ and a Tavily API key.

```bash
git clone https://github.com/Sridharmalladi/jobfinddaily.git
cd jobfinddaily
pip install -r requirements.txt
cp .env.example .env  # add your Tavily key
```

Add the server to your MCP client's configuration (example for Claude Desktop):

```json
{
  "mcpServers": {
    "jobfinddaily": {
      "command": "python",
      "args": ["/full/path/to/jobfinddaily/mcp_server.py"]
    }
  }
}
```

Job data and application history are stored locally in SQLite. Network calls go to job sources and configured search services.
