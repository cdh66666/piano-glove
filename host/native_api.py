"""In-process transport for the existing bridge routes, without an HTTP server.

pywebview calls ``request(path, method, body, raw, headers)``. With ``raw=True``,
body is either a JavaScript byte array or a base64 string. Otherwise objects are
JSON encoded and strings are sent verbatim (including form-encoded strings).
Replies contain ``status``, lower-case ``headers``, ``body`` and ``binary``;
binary reply bodies are base64, JSON replies remain objects, and text stays text.
Internal fetch callers may opt into UTF-8 JSON text for successful review-check
and export responses with X-Piano-Json-Text: 1; other routes and default callers
keep the object contract.
"""
import base64
from email.message import Message
import io
import json
from types import FunctionType, SimpleNamespace

import bridge


class NativeAPI:
    def __init__(self, session):
        # Keep this class/closure for the lifetime of the window: the real
        # SoftwareConsole owns chunk uploads and controller tokens across calls.
        routes = bridge.make_handler(session)

        class MemoryHandler(routes):
            def __init__(self, path, method, payload, headers):
                self.path = path
                self.command = method
                self.headers = headers
                self.rfile = io.BytesIO(payload)
                self.wfile = io.BytesIO()
                # Compatibility values for maintenance guards; no server or
                # socket is constructed, bound or listened on.
                self.server = SimpleNamespace(server_port=0, server_address=('127.0.0.1', 0))
                self.response_status = 500
                self.response_headers = {}

            def send_response(self, code, message=None):
                self.response_status = int(code)

            def send_header(self, name, value):
                self.response_headers[name.lower()] = str(value)

            def end_headers(self):
                pass

        # The HTTP connect route can look for another HTTP console before
        # selecting a port. A native window has no peer HTTP console. Give just
        # that function its own globals rather than patching the shared module
        # or duplicating any connection/motor logic.
        post = routes.do_POST
        MemoryHandler.do_POST = FunctionType(
            post.__code__, dict(post.__globals__, peer_console_url=lambda *_: None),
            post.__name__, post.__defaults__, post.__closure__)
        self._handler = MemoryHandler

    def check_project(self, project):
        """Native read-only validation without re-encoding a faux HTTP body.

        The ordinary route remains available. The shared validator owns the
        defensive copy, timing propagation and all manual-field protections.
        """
        from score_automatic import check_project
        return dict(ok=True, **check_project(project))

    def request(self, path, method='GET', body=None, raw=False, headers=None):
        try:
            if not isinstance(path, str) or not path.startswith('/') or path.startswith('//'):
                raise ValueError('接口地址须使用本程序的相对路径')
            method = str(method).upper()
            if method not in ('GET', 'POST', 'OPTIONS'):
                return self._error(405, '不支持的请求方法')
            incoming = Message()
            for name, value in (headers or {}).items():
                incoming[str(name)] = str(value)
            if raw:
                payload = base64.b64decode(body, validate=True) if isinstance(body, str) else bytes(body or [])
                content_type = 'application/octet-stream'
            elif body is None:
                payload, content_type = b'', 'application/json'
            elif isinstance(body, str):
                payload, content_type = body.encode('utf-8'), 'application/x-www-form-urlencoded'
            else:
                payload = json.dumps(body, ensure_ascii=False).encode('utf-8')
                content_type = 'application/json'
            if incoming.get('Content-Type') is None:
                incoming['Content-Type'] = content_type
            if incoming.get('Content-Length') is not None:
                del incoming['Content-Length']
            incoming['Content-Length'] = str(len(payload))
            handler = self._handler(path, method, payload, incoming)
            getattr(handler, 'do_' + method)()
            data = handler.wfile.getvalue()
            mime = handler.response_headers.get('content-type', '').split(';', 1)[0].lower()
            is_json = mime == 'application/json' or mime.endswith('+json')
            binary = bool(data) and not (is_json or mime.startswith('text/') or mime in ('application/javascript', 'image/svg+xml'))
            json_text = (path.split('?',1)[0] in ('/api/software/check','/api/software/export')
                         and is_json and bool(data) and 200 <= handler.response_status < 300
                         and incoming.get('X-Piano-Json-Text') == '1')
            value = (data.decode('utf-8') if json_text else json.loads(data) if is_json else base64.b64encode(data).decode('ascii')
                     if binary else data.decode('utf-8'))
            reply = dict(status=handler.response_status, headers=handler.response_headers,
                         body=value, binary=binary)
            if json_text:
                reply['body_encoding'] = 'json-text'
            return reply
        except (ValueError, TypeError) as error:
            return self._error(400, str(error))
        except Exception as error:
            return self._error(500, str(error))

    @staticmethod
    def _error(status, message):
        return dict(status=status, headers={'content-type': 'application/json; charset=utf-8'},
                    body={'ok': False, 'error': message}, binary=False)
