# adams-search

Search NRC ADAMS public documents from the command line or from any MCP client. Python standard library only.

Built from the NRC's *ADAMS Public Search API Developer's Guide v1.0*.

## 1. Get a free key (one time, you do this)

1. Go to https://adams-api-developer.nrc.gov/ and click **Sign up**.
2. Confirm your email, sign in, open **Products**, pick **ADAMS Public Search API**.
3. Type a subscription name, click **Subscribe**, and copy the key.
4. In PowerShell:

```powershell
[Environment]::SetEnvironmentVariable('ADAMS_API_KEY', '<paste key>', 'User')
```

Open a new terminal after that.

## 2. Use it

```powershell
python adams.py search microreactor --since 2026-01-01
python adams.py search --preset part57
python adams.py search --preset inspections --filter "DocketNumber:starts:05000373"
python adams.py get ML24017A120
python adams.py text ML26155A114            # save the full indexed text to ML26155A114.txt
```

The key is read from `ADAMS_API_KEY`. On Windows a key saved for your user is found even before you open a new terminal, and stray spaces, quotes or `< >` around it are ignored.

Presets: `part53`, `part57`, `microreactor`, `part21`, `topical`, `inspections`.
Filters are `FIELD:OPERATOR:VALUE`. The operators are contains, notcontains, starts, notstarts, equals and notequals.

## 3. Use it as an MCP server

Add this to your MCP client's server config:

```json
{
  "mcpServers": {
    "adams": {
      "command": "python",
      "args": ["/path/to/adams-search/mcp_server.py"],
      "env": { "ADAMS_API_KEY": "<key>" }
    }
  }
}
```

Tools: `adams_search`, `adams_get`.

## Tests

```powershell
python -m unittest -v test_adams
```
