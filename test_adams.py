import io
import json
import unittest
import urllib.request

import adams
import mcp_server

SAMPLE = {
    "count": 1,
    "results": [
        {
            "score": 12.1,
            "document": {
                "AccessionNumber": "ML24017A120",
                "DocumentTitle": "LaSalle County Station - Biennial PI&R Inspection Report",
                "DocumentDate": "2024-01-18",
                "DocumentType": ["Inspection Report", "Letter"],
                "DocketNumber": ["05000373", "05000374"],
                "Url": "https://www.nrc.gov/docs/ML2401/ML24017A120.pdf",
                "content": "x" * 50,
            },
        }
    ],
    "pageNumber": 1,
}


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Recorder:
    def __init__(self, payload):
        self.payload, self.reqs = payload, []

    def __call__(self, req, timeout=None):
        self.reqs.append(req)
        return FakeResp(json.dumps(self.payload).encode())


class AdamsTests(unittest.TestCase):
    def test_search_request_matches_spec(self):
        rec = Recorder(SAMPLE)
        c = adams.AdamsClient(api_key="k", opener=rec)
        c.search(q="safety valve", filters=[adams.date_filter("DocumentDate", "ge", "2024-01-01")])
        req = rec.reqs[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.full_url, adams.BASE_URL)
        self.assertEqual(req.get_header("Ocp-apim-subscription-key"), "k")
        body = json.loads(req.data)
        self.assertEqual(body["q"], "safety valve")
        self.assertEqual(body["filters"][0]["value"], "(DocumentDate ge '2024-01-01')")
        self.assertEqual(body["sortDirection"], 1)
        self.assertTrue(body["mainLibFilter"])

    def test_get_validates_accession(self):
        rec = Recorder({"document": SAMPLE["results"][0]["document"]})
        c = adams.AdamsClient(api_key="k", opener=rec)
        c.get("ml24017a120")
        self.assertTrue(rec.reqs[0].full_url.endswith("/ML24017A120"))
        self.assertEqual(rec.reqs[0].get_method(), "GET")
        with self.assertRaises(adams.AdamsError):
            c.get("not-a-number")

    def test_filters_validate(self):
        with self.assertRaises(ValueError):
            adams.text_filter("DocumentType", "x", "like")
        with self.assertRaises(ValueError):
            adams.date_filter("DocumentDate", "ge", "01/02/2024")
        with self.assertRaises(ValueError):
            adams.text_filter("DocumentDate", "2024")

    def test_summarize(self):
        rows = adams.summarize(SAMPLE)
        self.assertEqual(rows[0]["docket"], "05000373, 05000374")
        self.assertEqual(rows[0]["type"], "Inspection Report, Letter")

    def test_summarize_null_fields(self):
        rows = adams.summarize({"results": [{"document": {"AccessionNumber": "ML1", "DocumentDate": None,
                                                          "DocumentType": None, "DocumentTitle": None}}]})
        self.assertEqual((rows[0]["date"], rows[0]["type"], rows[0]["title"]), ("", "", ""))

    def test_missing_key(self):
        import os

        old = os.environ.pop("ADAMS_API_KEY", None)
        try:
            with self.assertRaises(adams.AdamsError):
                adams.AdamsClient()
        finally:
            if old:
                os.environ["ADAMS_API_KEY"] = old


class McpTests(unittest.TestCase):
    def factory(self):
        return adams.AdamsClient(api_key="k", opener=Recorder(SAMPLE))

    def test_initialize_and_list(self):
        r = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(r["result"]["serverInfo"]["name"], "nrc-adams")
        r = mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual({t["name"] for t in r["result"]["tools"]}, {"adams_search", "adams_get"})
        self.assertIsNone(mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_call_search(self):
        r = mcp_server.handle(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "adams_search", "arguments": {"preset": "microreactor", "since": "2026-01-01"}}},
            client_factory=self.factory,
        )
        self.assertFalse(r["result"]["isError"])
        out = json.loads(r["result"]["content"][0]["text"])
        self.assertEqual(out["results"][0]["accession"], "ML24017A120")

    def test_call_bad_args_is_tool_error(self):
        r = mcp_server.handle(
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "adams_search", "arguments": {"since": "bad"}}},
            client_factory=self.factory,
        )
        self.assertTrue(r["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
