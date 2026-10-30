"""Client and CLI for the NRC ADAMS Public Search (APS) API.

Spec: ADAMS Public Search API Developer's Guide v1.0
(https://adams-search.nrc.gov/assets/APS-API-Guide.pdf).

Needs a free subscription key from https://adams-api-developer.nrc.gov/
in the ADAMS_API_KEY environment variable. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "https://adams-api.nrc.gov/aps/api/search"
KEY_HEADER = "Ocp-Apim-Subscription-Key"
TEXT_OPERATORS = {"contains", "notcontains", "starts", "notstarts", "equals", "notequals"}
DATE_FIELDS = {"DocumentDate", "DateAddedTimestamp"}
ACCESSION_RE = re.compile(r"^ML\d{5}[A-Z]\d{3,4}$", re.IGNORECASE)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AdamsError(RuntimeError):
    pass


def text_filter(field: str, value: str, operator: str = "equals") -> dict:
    if operator not in TEXT_OPERATORS:
        raise ValueError(f"operator must be one of {sorted(TEXT_OPERATORS)}")
    if field in DATE_FIELDS:
        raise ValueError(f"{field} is a date field; use date_filter")
    return {"field": field, "value": value, "operator": operator}


def date_filter(field: str, op: str, date: str) -> dict:
    """op is ge (on or after), le (on or before) or eq. date is YYYY-MM-DD."""
    if field not in DATE_FIELDS:
        raise ValueError(f"date field must be one of {sorted(DATE_FIELDS)}")
    if op not in {"ge", "le", "eq"}:
        raise ValueError("date op must be ge, le or eq")
    if not _DATE_RE.match(date):
        raise ValueError("dates must be YYYY-MM-DD")
    return {"field": field, "value": f"({field} {op} '{date}')"}


def build_search_body(
    q: str = "",
    filters: list[dict] | None = None,
    any_filters: list[dict] | None = None,
    *,
    legacy: bool = False,
    main: bool = True,
    sort: str = "DocumentDate",
    descending: bool = True,
    skip: int = 0,
    content: bool = False,
) -> dict:
    body = {
        "q": q,
        "filters": filters or [],
        "anyFilters": any_filters or [],
        "legacyLibFilter": legacy,
        "mainLibFilter": main,
        "sort": sort,
        "sortDirection": 1 if descending else 0,
        "skip": skip,
    }
    if content:
        body["content"] = True
    return body


def clean_key(raw: str | None) -> str:
    """Drop whitespace, quotes and <> that often get pasted around a key."""
    return (raw or "").strip().strip("<>\"' ")


def _windows_user_env(name: str) -> str:
    # a key saved with SetEnvironmentVariable(..., 'User') is not seen until a new terminal opens
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return winreg.QueryValueEx(k, name)[0]
    except (ImportError, OSError):
        return ""


def find_key() -> str:
    return clean_key(os.environ.get("ADAMS_API_KEY") or _windows_user_env("ADAMS_API_KEY"))


class AdamsClient:
    def __init__(self, api_key: str | None = None, base_url: str = BASE_URL, timeout: float = 30.0, opener=None):
        self.api_key = clean_key(api_key) or find_key()
        if not self.api_key:
            raise AdamsError(
                "No subscription key. Get one free at https://adams-api-developer.nrc.gov/ "
                "and set ADAMS_API_KEY."
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._open = opener or urllib.request.urlopen

    def _request(self, url: str, body: dict | None = None) -> dict:
        headers = {KEY_HEADER: self.api_key, "Accept": "application/json", "Cache-Control": "no-cache"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers=headers, method="POST" if body is not None else "GET")
        try:
            with self._open(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise AdamsError(f"ADAMS API HTTP {e.code}: {detail}") from e

    def search(self, **kwargs) -> dict:
        return self._request(self.base_url, build_search_body(**kwargs))

    def newest(self, limit: int = 20, **kwargs) -> tuple[int, list[dict]]:
        """(total, rows) with the most recent documents first.

        The API returns pages oldest-first and ignores sortDirection (checked 2026-10-30),
        so jump to the last page and sort on our side.
        """
        res = self.search(**kwargs)
        total, page = res.get("count") or 0, len(res.get("results") or [])
        if page and total > page:
            res = self.search(**dict(kwargs, skip=total - page))
        rows = sorted(summarize(res), key=lambda r: r["date"], reverse=True)
        return total, rows[:limit]

    def get(self, accession: str) -> dict:
        accession = accession.strip().upper()
        if not ACCESSION_RE.match(accession):
            raise AdamsError(f"Not an ADAMS accession number: {accession!r} (expected like ML24017A120)")
        return self._request(f"{self.base_url}/{accession}")


def _first(v):
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return v or ""


def summarize(result: dict) -> list[dict]:
    """Flatten a search response into short rows."""
    rows = []
    for item in result.get("results", []) or []:
        d = item.get("document", {}) or {}
        # fields can be present but null, so coerce everything to str
        rows.append(
            {
                "accession": d.get("AccessionNumber") or "",
                "date": d.get("DocumentDate") or "",
                "type": _first(d.get("DocumentType")) or "",
                "docket": _first(d.get("DocketNumber")) or "",
                "title": d.get("DocumentTitle") or d.get("Name") or "",
                "url": d.get("Url") or "",
            }
        )
    return rows


# Ready-made searches for advanced and micro reactor work.
PRESETS = {
    "part53": {"q": "\"Part 53\""},
    "part57": {"q": "\"Part 57\" microreactor"},
    "microreactor": {"q": "microreactor"},
    "part21": {"filters": [text_filter("DocumentType", "Part 21 Correspondence")]},
    "topical": {"q": "advanced reactor", "filters": [text_filter("DocumentType", "Topical Report", "starts")]},
    "inspections": {
        "filters": [
            text_filter("DocumentType", "inspection report", "starts"),
            text_filter("DocketNumber", "05000", "starts"),
        ]
    },
}


def document_text(doc: dict) -> str:
    """Indexed text of a document. Package entries come back as an HTML list of their parts."""
    text = doc.get("content") or ""
    if text.lstrip().startswith("<!DOCTYPE html") or text.lstrip().startswith("<html"):
        text = re.sub(r"<li>", "\n- ", text)
        text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def _parse_filter(spec: str) -> dict:
    # FIELD:OPERATOR:VALUE, e.g. DocketNumber:starts:05000
    parts = spec.split(":", 2)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("filter must be FIELD:OPERATOR:VALUE")
    return text_filter(*[parts[0], parts[2], parts[1]])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="adams", description="Search NRC ADAMS public documents.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="search the public library")
    s.add_argument("q", nargs="?", default="")
    s.add_argument("--preset", choices=sorted(PRESETS))
    s.add_argument("--filter", action="append", type=_parse_filter, default=[], help="FIELD:OPERATOR:VALUE")
    s.add_argument("--since", help="DocumentDate on or after YYYY-MM-DD")
    s.add_argument("--until", help="DocumentDate on or before YYYY-MM-DD")
    s.add_argument("--legacy", action="store_true", help="include pre-1999 legacy library")
    s.add_argument("--skip", type=int, default=0)
    s.add_argument("--newest", type=int, metavar="N", help="show only the N most recent matches")
    s.add_argument("--json", action="store_true", help="print raw JSON")

    g = sub.add_parser("get", help="fetch one document by accession number")
    g.add_argument("accession")
    g.add_argument("--json", action="store_true")

    t = sub.add_parser("text", help="save a document's indexed full text to a file")
    t.add_argument("accession")
    t.add_argument("--out", help="default: <accession>.txt")

    a = p.parse_args(argv)
    try:
        client = AdamsClient()
        if a.cmd == "text":
            d = client.get(a.accession).get("document", {})
            text = document_text(d)
            if not text:
                raise AdamsError(f"{a.accession} has no indexed text; open {d.get('Url', 'the PDF')}")
            out = Path(a.out or f"{a.accession.upper()}.txt")
            out.write_text(text, encoding="utf-8")
            print(f"wrote {out.resolve()} ({len(text):,} chars) {d.get('DocumentTitle') or ''}")
            return 0
        if a.cmd == "get":
            doc = client.get(a.accession)
            if a.json:
                print(json.dumps(doc, indent=2))
            else:
                d = doc.get("document", doc)
                print(f"{d.get('AccessionNumber')}  {d.get('DocumentDate')}  {_first(d.get('DocumentType'))}")
                print(d.get("DocumentTitle", ""))
                print(d.get("Url", ""))
            return 0

        kwargs = dict(PRESETS.get(a.preset, {})) if a.preset else {}
        if a.q:
            kwargs["q"] = a.q
        filters = list(kwargs.get("filters", [])) + a.filter
        if a.since:
            filters.append(date_filter("DocumentDate", "ge", a.since))
        if a.until:
            filters.append(date_filter("DocumentDate", "le", a.until))
        kwargs["filters"] = filters
        if a.newest:
            total, rows = client.newest(a.newest, legacy=a.legacy, **kwargs)
            print(f"{total} matches, newest {len(rows)}:")
            for r in rows:
                print(f"{r['accession']:<13} {r['date']:<10} {r['type'][:28]:<28} {r['title'][:90]}")
            return 0
        res = client.search(legacy=a.legacy, skip=a.skip, **kwargs)
        if a.json:
            print(json.dumps(res, indent=2))
            return 0
        rows = summarize(res)
        print(f"{res.get('count', len(rows))} matches (showing {len(rows)})")
        for r in rows:
            print(f"{r['accession']:<13} {r['date']:<10} {r['type'][:28]:<28} {r['title'][:90]}")
        return 0
    except (AdamsError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
