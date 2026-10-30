"""Minimal stdio MCP server exposing NRC ADAMS search. Standard library only.

Run from any MCP client as: python <path>/mcp_server.py  (with ADAMS_API_KEY set)
"""

from __future__ import annotations

import json
import sys

import adams

PROTOCOL_VERSION = "2025-06-18"

TOOLS = [
    {
        "name": "adams_search",
        "description": (
            "Search NRC ADAMS public documents (inspection reports, licensing letters, topical reports, "
            "Part 53/57 rulemaking material). Returns accession number, date, type, docket, title and PDF URL."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Boolean search text, e.g. \"microreactor AND transport\""},
                "preset": {"type": "string", "enum": sorted(adams.PRESETS)},
                "filters": {
                    "type": "array",
                    "description": "Text filters, all must match",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string", "description": "e.g. DocumentType, DocketNumber, AuthorAffiliation"},
                            "operator": {"type": "string", "enum": sorted(adams.TEXT_OPERATORS)},
                            "value": {"type": "string"},
                        },
                        "required": ["field", "value"],
                    },
                },
                "since": {"type": "string", "description": "DocumentDate on or after YYYY-MM-DD"},
                "until": {"type": "string", "description": "DocumentDate on or before YYYY-MM-DD"},
                "skip": {"type": "integer", "minimum": 0},
            },
        },
    },
    {
        "name": "adams_get",
        "description": "Get one ADAMS document's metadata and indexed text by accession number (e.g. ML24017A120).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "accession": {"type": "string"},
                "max_chars": {"type": "integer", "description": "truncate content (default 20000)"},
            },
            "required": ["accession"],
        },
    },
]


def call_tool(name: str, args: dict, client_factory=adams.AdamsClient) -> str:
    client = client_factory()
    if name == "adams_search":
        kwargs = dict(adams.PRESETS.get(args.get("preset", ""), {}))
        if args.get("q"):
            kwargs["q"] = args["q"]
        filters = list(kwargs.get("filters", []))
        for f in args.get("filters", []) or []:
            filters.append(adams.text_filter(f["field"], f["value"], f.get("operator", "equals")))
        if args.get("since"):
            filters.append(adams.date_filter("DocumentDate", "ge", args["since"]))
        if args.get("until"):
            filters.append(adams.date_filter("DocumentDate", "le", args["until"]))
        kwargs["filters"] = filters
        res = client.search(skip=int(args.get("skip", 0)), **kwargs)
        return json.dumps({"count": res.get("count"), "results": adams.summarize(res)}, indent=2)
    if name == "adams_get":
        doc = client.get(args["accession"])
        d = dict(doc.get("document", doc))
        limit = int(args.get("max_chars", 20000))
        if isinstance(d.get("content"), str) and len(d["content"]) > limit:
            d["content"] = d["content"][:limit] + f"\n...[truncated at {limit} chars]"
        return json.dumps(d, indent=2)
    raise ValueError(f"unknown tool {name}")


def handle(msg: dict, client_factory=adams.AdamsClient) -> dict | None:
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None  # notification
    if method == "initialize":
        result = {
            "protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL_VERSION),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "nrc-adams", "version": "0.1.0"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        p = msg.get("params", {})
        try:
            text = call_tool(p.get("name", ""), p.get("arguments", {}) or {}, client_factory)
            result = {"content": [{"type": "text", "text": text}], "isError": False}
        except (adams.AdamsError, ValueError, KeyError) as e:
            result = {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        out = handle(msg)
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
