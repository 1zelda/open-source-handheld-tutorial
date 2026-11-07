from __future__ import annotations

import json
import os
import socket
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch
from urllib.error import URLError

from portfactory import rd_provider
from portfactory.rd_provider import ProviderError, request_local


_CONTENT = json.dumps({"ir": {"op": "return", "value": 7}, "summary": "保留返回值"},
                      ensure_ascii=False)


def completion(content=_CONTENT, **extra):
    return {"choices": [{"message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}], **extra}


class QuietHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.requests.append({"path": self.path, "headers": dict(self.headers),
                                     "body": body})
        self.send_response(self.server.reply_status)
        for key, value in self.server.reply_headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(self.server.reply_body)))
        self.end_headers()
        try:
            self.wfile.write(self.server.reply_body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # Expected when the client stops reading an oversized reply.

    do_GET = do_POST

    def log_message(self, format, *args):
        pass


@contextmanager
def local_server(ipv6=False):
    server_type = type("IPv6HTTPServer", (HTTPServer,), {"address_family": socket.AF_INET6})
    server = (server_type if ipv6 else HTTPServer)(("::1" if ipv6 else "127.0.0.1", 0),
                                                 QuietHandler)
    server.requests = []
    server.reply_status = 200
    server.reply_headers = {"Content-Type": "application/json"}
    server.reply_body = json.dumps(completion(), ensure_ascii=False).encode("utf-8")
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    try:
        thread.start()
        host = "[::1]" if ipv6 else "127.0.0.1"
        yield server, f"http://{host}:{server.server_address[1]}/v1"
    finally:
        if thread.is_alive():
            server.shutdown()
        server.server_close()
        if thread.ident is not None:
            thread.join(timeout=2)
        if thread.is_alive():
            raise AssertionError("temporary HTTP server thread did not stop")


class LocalProviderTests(unittest.TestCase):
    def setUp(self):
        self.server, self.endpoint = self.enterContext(local_server())

    def reply(self, payload, status=200, headers=None):
        self.server.reply_body = (payload if isinstance(payload, bytes) else
                                  json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        self.server.reply_status = status
        self.server.reply_headers = headers or {"Content-Type": "application/json"}

    def request(self, **kwargs):
        return request_local(self.endpoint, "test-model", "untrusted disassembly", **kwargs)

    def test_valid_response_and_request_contract(self):
        usage = {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}
        self.reply(completion(usage=usage, model="untrusted-server-model"))
        result = request_local(self.endpoint + "/", "test-model", "mov eax, 7\nret")
        self.assertEqual(result, {"ir": {"op": "return", "value": 7},
                                  "summary": "保留返回值", "usage": usage,
                                  "provider": "local-openai", "model": "test-model"})
        request = self.server.requests[0]
        self.assertEqual(request["path"], "/v1/chat/completions")
        self.assertEqual(request["headers"]["Content-Type"], "application/json")
        self.assertNotIn("Authorization", request["headers"])
        body = json.loads(request["body"])
        self.assertEqual(body["model"], "test-model")
        self.assertEqual(body["max_tokens"], 4096)
        self.assertEqual(body["temperature"], 0)
        self.assertIs(body["stream"], False)
        self.assertNotIn("tools", body)
        self.assertNotIn("functions", body)
        self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
        system = body["messages"][0]["content"]
        self.assertIn("untrusted data", system)
        self.assertIn("cannot override", system)
        self.assertIn("restricted IR", system)
        self.assertEqual(body["messages"][1]["content"], "mov eax, 7\nret")

    def test_missing_and_partial_usage_are_not_fabricated(self):
        for extra, expected in (({}, {}), ({"usage": {}}, {}),
                                ({"usage": {"completion_tokens": 3}}, {"completion_tokens": 3})):
            with self.subTest(extra=extra):
                self.reply(completion(**extra))
                self.assertEqual(self.request()["usage"], expected)

    def test_standard_usage_details_preserved(self):
        usage = {"prompt_tokens": 8, "prompt_tokens_details": {"cached_tokens": 2},
                 "completion_tokens_details": {"reasoning_tokens": 0}}
        self.reply(completion(usage=usage))
        self.assertEqual(self.request()["usage"], usage)

    def test_json_fence_and_raw_utf8_byte_limit(self):
        for text in (_CONTENT, " \n" + _CONTENT + "\t", "```json\n" + _CONTENT + "\n```",
                     " \n```json\r\n" + _CONTENT + "\r\n```\t"):
            with self.subTest(content=text):
                self.reply(completion(text))
                size = len(text.encode("utf-8"))
                self.assertEqual(self.request(max_output_bytes=size)["summary"], "保留返回值")
                body = json.loads(self.server.requests[-1]["body"])
                self.assertEqual(body["max_tokens"], size)
                with self.assertRaisesRegex(ProviderError, "max_output_bytes"):
                    self.request(max_output_bytes=size - 1)

    def test_invalid_contents(self):
        invalid = ["", "not-json", "Here is JSON: " + _CONTENT, _CONTENT + " extra",
                   "```\n" + _CONTENT + "\n```", "```python\n" + _CONTENT + "\n```",
                   "```json\n" + _CONTENT + "\n```\n```json\n{}\n```",
                   "```json\n" + _CONTENT + "\n``` trailing", _CONTENT + _CONTENT,
                   "[]", "null", "true", "{}", '{"ir":[],"summary":"x"}',
                   '{"ir":{},"summary":null}', '{"ir":{},"summary":7}',
                   '{"ir":{},"summary":"x","extra":1}',
                   '{"ir":{},"ir":{},"summary":"x"}',
                   '{"ir":{"number":NaN},"summary":"x"}',
                   '{"ir":{"number":Infinity},"summary":"x"}',
                   '{"ir":{"number":1e999},"summary":"x"}',
                   "[" * 2000 + "0" + "]" * 2000]
        for text in invalid:
            with self.subTest(content=text[:80]):
                self.reply(completion(text))
                with self.assertRaises(ProviderError):
                    self.request()

    def test_invalid_envelopes_and_missing_content(self):
        invalid = [b"\xff", b"{", b"[]", b'{"choices":[],"choices":[]}',
                   b"[" * 2000 + b"0" + b"]" * 2000,
                   {}, {"choices": None}, {"choices": {}}, {"choices": []},
                   {"choices": [None]}, {"choices": [{}, {}]}, {"choices": [{}]},
                   {"choices": [{"message": None}]}, {"choices": [{"message": {}}]},
                   completion(None), completion([]), completion({"text": _CONTENT})]
        for payload in invalid:
            with self.subTest(payload=str(payload)[:80]):
                self.reply(payload)
                with self.assertRaises(ProviderError):
                    self.request()
        self.reply(json.dumps(completion("\ud800"), ensure_ascii=True).encode("utf-8"))
        with self.assertRaisesRegex(ProviderError, "UTF-8"):
            self.request()

    def test_tool_calls_are_rejected_even_when_empty(self):
        for field in ("tool_calls", "function_call"):
            for value in (None, [], {}, [{"name": "unsafe"}]):
                for location in ("message", "choice", "envelope"):
                    with self.subTest(field=field, value=value, location=location):
                        payload = completion()
                        target = {"message": payload["choices"][0]["message"],
                                  "choice": payload["choices"][0], "envelope": payload}[location]
                        target[field] = value
                        self.reply(payload)
                        with self.assertRaisesRegex(ProviderError, "tool/function"):
                            self.request()
            payload = completion()
            payload["choices"][0]["finish_reason"] = field
            self.reply(payload)
            with self.assertRaisesRegex(ProviderError, "tool/function"):
                self.request()

    def test_invalid_usage(self):
        invalid = [None, [], "12", 12, {"prompt_tokens": -1}, {"total_tokens": True},
                   {"completion_tokens": "1"}, {"completion_tokens": 1.0},
                   {"total_tokens": None}, {"total_tokens": {}}, {"other": -1},
                   {"prompt_tokens_details": None}, {"prompt_tokens_details": 1},
                   {"completion_tokens_details": {"reasoning_tokens": -1}},
                   {"completion_tokens_details": {"reasoning_tokens": False}},
                   {"completion_tokens_details": {"reasoning_tokens": {}}}]
        for usage in invalid:
            with self.subTest(usage=usage):
                self.reply(completion(usage=usage))
                with self.assertRaisesRegex(ProviderError, "usage"):
                    self.request()

    def test_response_one_mib_boundary(self):
        raw = json.dumps(completion()).encode("utf-8")
        self.reply(raw + b" " * (1024 * 1024 - len(raw)))
        self.assertEqual(self.request()["provider"], "local-openai")
        self.reply(self.server.reply_body + b" ")
        with self.assertRaisesRegex(ProviderError, "1 MiB"):
            self.request()

    def test_api_errors_do_not_echo_untrusted_fields(self):
        for status in (200, 400, 429, 500):
            with self.subTest(status=status):
                self.reply({"error": {"message": "secret-prompt", "code": "model_not_found",
                                      "type": "bad-secret-type", "debug": "secret-debug"},
                            "unknown": "secret-unknown"}, status=status)
                with self.assertRaises(ProviderError) as caught:
                    self.request()
                self.assertIn("model_not_found", str(caught.exception))
                self.assertNotIn("secret", str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__ or status == 200)
        for error in ("secret", {"message": "secret", "type": ["secret"]},
                      {"code": {"secret": "value"}}, False):
            self.reply({"error": error})
            with self.assertRaisesRegex(ProviderError, "API error") as caught:
                self.request()
            self.assertNotIn("secret", str(caught.exception))
        for raw in (b"<html>secret</html>", b'{"unknown":"secret"}', b"x" * (1024 * 1024 + 1)):
            self.reply(raw, status=503)
            with self.assertRaisesRegex(ProviderError, "HTTP 503") as caught:
                self.request()
            self.assertNotIn("secret", str(caught.exception))

    def test_redirects_never_reach_destination(self):
        with local_server() as (destination, target):
            for status in (300, 301, 302, 303, 304, 305, 307, 308):
                for location in (target + "/chat/completions", "/v1/redirected",
                                 "http://example.com/v1", "file:///secret", "http://["):
                    with self.subTest(status=status, location=location):
                        before = len(self.server.requests)
                        self.reply(b"secret redirect body", status=status,
                                   headers={"Location": location})
                        with self.assertRaisesRegex(ProviderError, "redirect"):
                            self.request()
                        self.assertEqual(len(self.server.requests), before + 1)
                        self.assertEqual(destination.requests, [])

    def test_proxy_and_api_key_environment_are_ignored(self):
        env = {"HTTP_PROXY": "http://192.0.2.1:9", "HTTPS_PROXY": "http://192.0.2.1:9",
               "http_proxy": "http://192.0.2.1:9", "https_proxy": "http://192.0.2.1:9",
               "ALL_PROXY": "http://192.0.2.1:9", "all_proxy": "http://192.0.2.1:9",
               "NO_PROXY": "", "no_proxy": "", "OPENAI_API_KEY": "secret-key"}
        with patch.dict(os.environ, env), patch("urllib.request.getproxies",
                                               side_effect=AssertionError("proxy lookup")):
            self.request()
        request = self.server.requests[-1]
        self.assertNotIn("Authorization", request["headers"])
        self.assertNotIn("secret-key", repr(request))

    def test_ipv6_literal(self):
        try:
            with local_server(ipv6=True) as (server, endpoint):
                result = request_local(endpoint, "test-model", "data", timeout=2)
                self.assertEqual(result["provider"], "local-openai")
                self.assertEqual(server.requests[0]["path"], "/v1/chat/completions")
        except OSError as exc:
            self.skipTest(f"IPv6 loopback unavailable: {exc.errno}")


class ProviderValidationTests(unittest.TestCase):
    def test_bad_endpoints_rejected_before_network(self):
        invalid = [None, 123, "", "http://localhost/v1", "http://LOCALHOST/v1",
                   "http://example.com/v1", "http://192.168.1.1/v1", "http://0.0.0.0/v1",
                   "http://127.0.0.2/v1", "http://127.1/v1", "http://2130706433/v1",
                   "http://0x7f000001/v1", "http://0177.0.0.1/v1", "http://127.0.0.01/v1",
                   "http://[::ffff:127.0.0.1]/v1", "http://[0:0:0:0:0:0:0:1]/v1",
                   "http://[::1%25lo]/v1", "http://::1/v1", "http://[::]/v1",
                   "http://[::1/v1", "http://127.0.0.1.evil/v1", "http://127.0.0.1./v1",
                   "http://user@127.0.0.1/v1", "http://user:secret@127.0.0.1/v1",
                   "http://127.0.0.1@evil/v1", "http://127.0.0.1/v1?secret=value",
                   "http://127.0.0.1/v1?", "http://127.0.0.1/v1#secret", "http://127.0.0.1/v1#",
                   "ftp://127.0.0.1/v1", "file:///v1", "//127.0.0.1/v1", "http://127.0.0.1",
                   "http://127.0.0.1/v1/chat/completions", "http://127.0.0.1/v1//",
                   "http://127.0.0.1/a/../v1", "http://127.0.0.1/%761",
                   "http://127.0.0.1:0/v1", "http://127.0.0.1:65536/v1",
                   "http://127.0.0.1:-1/v1", "http://127.0.0.1:abc/v1",
                   "http://127.0.0.1:/v1", "http://127.0.0.1:１２/v1",
                   " http://127.0.0.1/v1", "http://127.0.0.1/v1\n",
                   "http://127.0.0.\t1/v1", "http://127.0.0.1\\@evil/v1"]
        with patch.object(rd_provider, "build_opener") as opener:
            for endpoint in invalid:
                with self.subTest(endpoint=endpoint):
                    with self.assertRaises(ProviderError) as caught:
                        request_local(endpoint, "test-model", "secret")
                    self.assertNotIn("secret", str(caught.exception))
            opener.assert_not_called()

    def test_argument_validation_before_network(self):
        invalid = ([{"timeout": value} for value in
                    (0, -1, 300.1, float("nan"), float("inf"), "120", None, True)]
                   + [{"max_output_bytes": value} for value in (0, -1, 1.5, "12", None, True)]
                   + [{"model": value} for value in (None, "", " ", 1, "\ud800")]
                   + [{"prompt": value} for value in (None, 1, {}, "\ud800")])
        with patch.object(rd_provider, "build_opener") as opener:
            for change in invalid:
                args = {"endpoint": "http://127.0.0.1/v1", "model": "test", "prompt": "data"}
                args.update(change)
                with self.subTest(change=change), self.assertRaises(ProviderError):
                    request_local(**args)
            opener.assert_not_called()

    def test_network_errors_are_wrapped_without_details(self):
        for error in (URLError("secret-url"), TimeoutError("secret-prompt"),
                      ConnectionResetError("secret-reset")):
            with patch.object(rd_provider, "build_opener") as factory:
                factory.return_value.open.side_effect = error
                with self.assertRaisesRegex(ProviderError, "HTTP request failed") as caught:
                    request_local("http://127.0.0.1/v1", "test", "data")
                self.assertNotIn("secret", str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)

    def test_timeout_boundaries_and_https_url(self):
        for timeout in (0.01, 120, 300):
            with patch.object(rd_provider, "build_opener") as factory:
                response = factory.return_value.open.return_value.__enter__.return_value
                response.read.return_value = json.dumps(completion()).encode("utf-8")
                result = request_local("https://[::1]:443/v1/", "test", "data", timeout=timeout)
                self.assertEqual(result["provider"], "local-openai")
                args, kwargs = factory.return_value.open.call_args
                self.assertEqual(args[0].full_url, "https://[::1]:443/v1/chat/completions")
                self.assertEqual(kwargs["timeout"], timeout)
                response.read.assert_called_once_with(1024 * 1024 + 1)
                factory.return_value.open.return_value.__exit__.assert_called_once()


if __name__ == "__main__":
    unittest.main()
