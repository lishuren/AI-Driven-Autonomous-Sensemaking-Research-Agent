#!/usr/bin/env python3
"""
Simple HTTP forwarding proxy to log requests and responses to Ollama.
Writes logs to D:/mainstreamGraphRAG/logs/ollama_proxy_requests.log

Usage:
    python tools/ollama_proxy.py [--host HOST] [--port PORT]

Default listens on 127.0.0.1:11435 and forwards to http://127.0.0.1:11434
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urljoin
import urllib.request
import urllib.error
import sys
import os
import argparse
import time
import json

TARGET_DEFAULT = os.environ.get("OLLAMA_TARGET", "http://127.0.0.1:11434")
LOG_DIR = r"D:\mainstreamGraphRAG\logs"
LOG_FILE = os.path.join(LOG_DIR, "ollama_proxy_requests.log")

if not os.path.isdir(LOG_DIR):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except Exception:
        pass


def _safe_decode(b: bytes) -> str:
    try:
        return b.decode("utf-8")
    except Exception:
        try:
            return b.decode("latin-1")
        except Exception:
            return repr(b)


def _log(entry: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {entry}\n"
    print(line, end="")
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        print(f"Failed to write proxy log: {e}")


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _forward(self, target_url: str, body: bytes):
        req = urllib.request.Request(target_url, data=body, method="POST")
        # copy most headers except hop-by-hop
        hop_by_hop = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade", 'host'}
        for k, v in self.headers.items():
            if k.lower() in hop_by_hop:
                continue
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                resp_body = resp.read()
                status = resp.getcode()
                headers = resp.getheaders()
                return status, headers, resp_body
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
            except Exception:
                body = b""
            return e.code, list(e.headers.items()) if e.headers else [], body
        except Exception as e:
            return None, [], str(e).encode("utf-8")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length > 0 else b""
        body_text = _safe_decode(body)
        _log(f"REQUEST {self.command} {self.path} headers={dict(self.headers)} body={body_text}")

        target_url = urljoin(TARGET_DEFAULT, self.path)
        _log(f"Forwarding to {target_url}")
        status, headers, resp_body = self._forward(target_url, body)

        if status is None:
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(resp_body)
            _log(f"Proxy error when forwarding: {resp_body!r}")
            return

        try:
            self.send_response(status)
            # copy response headers except hop-by-hop and content-length (we set it)
            hop_by_hop = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade"}
            content_length_set = False
            for k, v in headers:
                if k.lower() in hop_by_hop:
                    continue
                if k.lower() == 'content-length':
                    # we'll set content-length to resp_body length
                    continue
                try:
                    self.send_header(k, v)
                except Exception:
                    pass
            self.send_header('Content-Length', str(len(resp_body)))
            self.end_headers()
            self.wfile.write(resp_body)
            _log(f"RESPONSE status={status} body={_safe_decode(resp_body)[:1000]}")
        except BrokenPipeError:
            pass

    def do_GET(self):
        # Simple GET forward
        target_url = urljoin(TARGET_DEFAULT, self.path)
        _log(f"GET {self.path} -> {target_url}")
        try:
            with urllib.request.urlopen(target_url, timeout=30) as resp:
                resp_body = resp.read()
                status = resp.getcode()
                headers = resp.getheaders()
                self.send_response(status)
                for k, v in headers:
                    if k.lower() == 'transfer-encoding':
                        continue
                    try:
                        self.send_header(k, v)
                    except Exception:
                        pass
                self.send_header('Content-Length', str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)
        except Exception as e:
            self.send_response(502)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            msg = f"Error proxying GET: {e}".encode('utf-8')
            self.wfile.write(msg)
            _log(msg.decode('utf-8'))


def main():
    global TARGET_DEFAULT
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', default=11435, type=int)
    parser.add_argument('--target', default=TARGET_DEFAULT)
    args = parser.parse_args()
    # update target if provided
    if args.target:
        TARGET_DEFAULT = args.target
    server = ThreadingHTTPServer((args.host, args.port), ProxyHandler)
    _log(f"Starting Ollama proxy on {args.host}:{args.port} forwarding to {TARGET_DEFAULT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _log('Shutting down proxy')
        server.server_close()

if __name__ == '__main__':
    main()
