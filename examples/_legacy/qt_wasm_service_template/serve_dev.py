#!/usr/bin/env python3
"""
serve_dev.py — Dev server for Qt WASM service template.

Serves the WASM build output AND provides an HTTP→RabbitMQ bridge so the
Qt WASM GUI can call the running MyQtWasmService.exe backend.

Uses MicroserviceBase.adapters.transport for RabbitMQ communication —
the same transport layer used by the Python microservices.

Usage:
    python serve_dev.py [port] [build_dir]
    python serve_dev.py 8090 build/wasm

Prerequisites:
  - MicroserviceBase package installed (pip install MicroserviceBase)
  - RabbitMQ running on localhost:5672
  - MyQtWasmService.exe running
"""

import http.server
import json
import os
import sys

# ---------------------------------------------------------------------------
# RabbitMQ transport via MicroserviceBase
# ---------------------------------------------------------------------------
try:
    from MicroserviceBase.adapters.config.rabbitmq_config import RabbitMQConfig
    from MicroserviceBase.adapters.transport.rabbitmq_adapter import RabbitMQTransportAdapter
    from MicroserviceBase.domain.service_base import ServiceBase
    HAS_TRANSPORT = True
except ImportError as e:
    HAS_TRANSPORT = False
    _import_error = str(e)

REQUEST_EXCHANGE = "services_request"

# ---------------------------------------------------------------------------
# JavaScript bridge — injected into the HTML page before </head>
# ---------------------------------------------------------------------------
BRIDGE_SCRIPT = """
<script>
// HTTP→RabbitMQ bridge provided by serve_dev.py
window.callMicroservice = async function(serviceName, method, args) {
    const resp = await fetch('/api/request', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({service: serviceName, method: method, args: args})
    });
    if (!resp.ok) {
        const text = await resp.text();
        throw new Error('HTTP ' + resp.status + ': ' + text);
    }
    return resp.json();
};
console.log('[serve_dev] callMicroservice bridge ready');
</script>
"""


def load_broker_config(script_dir):
    """Load broker config from service_config.json, fall back to defaults."""
    config_path = os.path.join(script_dir, "service_config.json")
    host, port, vhost, user, pwd = "localhost", 5672, "/", "guest", "guest"

    if os.path.isfile(config_path):
        try:
            with open(config_path, "r") as f:
                cfg = json.load(f)
            host = cfg.get("broker_host", host)
            port = cfg.get("broker_port", port)
            vhost = cfg.get("broker_vhost", vhost)
            user = cfg.get("broker_user", user)
            pwd = cfg.get("broker_pass", pwd)
        except Exception:
            pass

    return RabbitMQConfig(
        host=host, port=port, virtual_host=vhost,
        username=user, password=pwd,
    )


def rpc_call(config, service_name, method, args, timeout=10):
    """Send an RPC request via MicroserviceBase transport and return the response."""
    if not HAS_TRANSPORT:
        return {
            "request": method,
            "result": "exception",
            "result_data": f"MicroserviceBase not installed: {_import_error}",
        }

    transport = None
    try:
        transport = RabbitMQTransportAdapter(config)
        transport.connect()

        request_data = ServiceBase.create_request_data(method, args)
        response = transport.rpc_call(
            request_data, REQUEST_EXCHANGE, service_name, timeout=timeout
        )
        return response

    except Exception as e:
        return {
            "request": method,
            "result": "exception",
            "result_data": str(e),
        }
    finally:
        if transport:
            try:
                transport.disconnect()
            except Exception:
                pass


class DevHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler: static files + RabbitMQ bridge."""

    broker_config = None  # set by main()

    def do_GET(self):
        if self.path.endswith(".html") or self.path == "/":
            self._serve_html_with_bridge()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/request":
            self._handle_api_request()
        else:
            self.send_error(404, "Not Found")

    def guess_type(self, path):
        if path.endswith(".wasm"):
            return "application/wasm"
        return super().guess_type(path)

    def _serve_html_with_bridge(self):
        """Serve HTML with the callMicroservice bridge injected."""
        path = self.path
        if path == "/":
            path = "/myqtwasmservice.html"

        file_path = os.path.realpath(
            os.path.join(self.directory, path.lstrip("/"))
        )
        if not file_path.startswith(os.path.realpath(self.directory)):
            self.send_error(403, "Forbidden")
            return
        if not os.path.isfile(file_path):
            self.send_error(404, "File not found")
            return

        with open(file_path, "r", encoding="utf-8") as f:
            html = f.read()

        if "</head>" in html:
            html = html.replace("</head>", BRIDGE_SCRIPT + "</head>")
        else:
            html = BRIDGE_SCRIPT + html

        content = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.end_headers()
        self.wfile.write(content)

    def _handle_api_request(self):
        """POST /api/request → RabbitMQ RPC → JSON response."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, ValueError) as e:
            self.send_error(400, f"Invalid JSON: {e}")
            return

        service = body.get("service", "")
        method = body.get("method", "")
        args = body.get("args", [])

        if not service or not method:
            self.send_error(400, "Missing 'service' or 'method'")
            return

        print(f"  >> {service}.{method}({json.dumps(args, default=str)[:80]})")

        result = rpc_call(DevHandler.broker_config, service, method, args)

        status = result.get("result", "?")
        data_preview = json.dumps(result.get("result_data", ""), default=str)[:80]
        print(f"  << {status}: {data_preview}")

        resp_body = json.dumps(result).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        self.wfile.write(resp_body)

    def log_message(self, fmt, *args):
        """Only log API calls and errors, not every static file."""
        msg = fmt % args
        if "POST /api/" in msg or "error" in msg.lower():
            print(f"  {msg}")


def find_build_dir(script_dir):
    """Auto-detect WASM build output directory."""
    for sub in ["build/wasm", "build/Qt_WASM-Release", "build"]:
        d = os.path.join(script_dir, sub)
        if os.path.isfile(os.path.join(d, "myqtwasmservice.wasm")):
            return d
    return None


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    build_dir = sys.argv[2] if len(sys.argv) > 2 else None

    script_dir = os.path.dirname(os.path.abspath(__file__))

    if build_dir is None:
        build_dir = find_build_dir(script_dir)
    if build_dir is None:
        print("ERROR: No WASM build output found. Run build_wasm.bat first.")
        sys.exit(1)

    build_dir = os.path.abspath(build_dir)

    # Load broker config from service_config.json
    if HAS_TRANSPORT:
        DevHandler.broker_config = load_broker_config(script_dir)
        broker_info = (f"{DevHandler.broker_config.username}@"
                       f"{DevHandler.broker_config.host}:{DevHandler.broker_config.port}")
    else:
        broker_info = f"NOT AVAILABLE ({_import_error})"

    print("=" * 60)
    print("  Qt WASM Dev Server")
    print("=" * 60)
    print(f"  Serving:  {build_dir}")
    print(f"  URL:      http://localhost:{port}/myqtwasmservice.html")
    print(f"  Broker:   {broker_info}")
    print()
    print("  Press Ctrl+C to stop.")
    print("=" * 60)
    print()

    handler = lambda *a, **kw: DevHandler(*a, directory=build_dir, **kw)
    server = http.server.HTTPServer(("", port), handler)
    server.timeout = 1

    try:
        while True:
            server.handle_request()
    except KeyboardInterrupt:
        print("\nServer stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
