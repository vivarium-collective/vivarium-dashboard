"""vivarium-dashboard CLI - serve a workspace via the dashboard."""
from __future__ import annotations
import argparse
import json
import os
import socket
import sys
from pathlib import Path


def _pick_free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def cmd_serve(args: argparse.Namespace) -> int:
    """Render the workspace dashboard once and start the HTTP server."""
    workspace = Path(args.workspace).resolve()
    if not (workspace / "workspace.yaml").is_file():
        print(f"ERROR: not a workspace (no workspace.yaml): {workspace}", file=sys.stderr)
        return 2

    # Make the workspace's own package importable for the render step
    # (e.g. pbg_chromosome_rep1.core.build_core), and register the workspace
    # root for lib helpers.
    ws_str = str(workspace)
    if ws_str not in sys.path:
        sys.path.insert(0, ws_str)
    from vivarium_dashboard.lib._root import set_workspace_root
    set_workspace_root(workspace)

    # Render the dashboard HTML once before serving.
    try:
        from vivarium_dashboard.lib.report import render_dashboard
        render_dashboard(workspace, write_all=True)
    except Exception as e:
        print(f"warning: dashboard render failed: {e}", file=sys.stderr)

    # Pick port + write server-info ahead of boot (server.serve() also writes
    # one, but writing it here ensures the URL is printed below correctly).
    port = args.port or _pick_free_port()
    server_dir = workspace / ".pbg" / "server"
    server_dir.mkdir(parents=True, exist_ok=True)
    info = {
        "port": port,
        "host": "127.0.0.1",
        "url": f"http://127.0.0.1:{port}",
        "pid": os.getpid(),
        "screen_dir": str(server_dir / "content"),
        "state_dir": str(server_dir / "state"),
    }
    (server_dir / "server-info").write_text(json.dumps(info))
    print(f"\nWorkspace dashboard: http://127.0.0.1:{port}")
    print("   (Ctrl-C to stop)\n")

    # Boot the HTTP server.
    from vivarium_dashboard.server import serve as serve_dashboard
    return serve_dashboard(workspace=workspace, port=port)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vivarium-dashboard")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_serve = sub.add_parser("serve", help="Serve the dashboard for a workspace")
    p_serve.add_argument("--workspace", default=".", help="Path to workspace root (default: cwd)")
    p_serve.add_argument("--port", type=int, default=0, help="Port (default: pick a free port)")
    p_serve.set_defaults(func=cmd_serve)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
