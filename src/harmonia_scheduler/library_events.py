from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .scheduler import SchedulerError, Track, load_manifest


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8092
DEFAULT_HISTORY_PATH = Path("data/played-history.jsonl")
MAX_BODY_BYTES = 4096


class LibraryEventError(ValueError):
    pass


def append_library_play(
    payload: dict[str, Any],
    *,
    manifest_path: Path,
    history_path: Path = DEFAULT_HISTORY_PATH,
) -> dict[str, Any]:
    track_id = _payload_track(payload)
    tracks_by_id = {track.track: track for track in load_manifest(manifest_path)}
    track = tracks_by_id.get(track_id)
    if track is None:
        raise LibraryEventError(f"unknown track: {track_id}")

    entry = library_play_entry(track, payload)
    append_history_entry(history_path, entry)
    return entry


def library_play_entry(track: Track, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    played_at_epoch = time.time()
    metadata = metadata or {}
    return {
        "played_at": datetime.fromtimestamp(played_at_epoch, UTC).strftime("%Y-%m-%dT%H:%M:%S%z"),
        "played_at_epoch": played_at_epoch,
        "source": "library",
        "artist": _metadata_string(metadata, "artist"),
        "title": _metadata_string(metadata, "title") or track.display_title,
        "tracknumber": track.track,
        "album": _metadata_string(metadata, "album"),
        "genre": _metadata_string(metadata, "genre"),
    }


def append_history_entry(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    fd = os.open(path, flags, 0o644)
    try:
        _ = os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def run_server(host: str, port: int, manifest_path: Path, history_path: Path) -> None:
    handler = make_handler(manifest_path, history_path)
    server = ThreadingHTTPServer((host, port), handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def make_handler(manifest_path: Path, history_path: Path) -> type[BaseHTTPRequestHandler]:
    class LibraryEventHandler(BaseHTTPRequestHandler):
        server_version = "HarmoniaLibraryEvents/1.0"

        def do_POST(self) -> None:
            if self.path != "/library-play":
                self._send_json(404, {"error": "not found"})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                self._send_json(415, {"error": "content type must be application/json"})
                return

            try:
                payload = self._read_payload()
                entry = append_library_play(payload, manifest_path=manifest_path, history_path=history_path)
            except LibraryEventError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            except SchedulerError as exc:
                self.log_error("scheduler error while recording library play: %s", exc)
                self._send_json(503, {"error": "library event service unavailable"})
                return
            except OSError as exc:
                self.log_error("I/O error while recording library play: %s", exc)
                self._send_json(500, {"error": "could not record library play"})
                return

            self._send_json(201, {"ok": True, "track": entry["tracknumber"]})

        def do_GET(self) -> None:
            if self.path == "/healthz":
                self._send_json(200, {"ok": True})
                return
            self._send_json(404, {"error": "not found"})

        def log_message(self, format: str, *args: object) -> None:
            return

        def _read_payload(self) -> dict[str, Any]:
            length_header = self.headers.get("Content-Length")
            try:
                length = int(length_header or "0")
            except ValueError as exc:
                raise LibraryEventError("invalid content length") from exc
            if length <= 0:
                raise LibraryEventError("empty request body")
            if length > MAX_BODY_BYTES:
                raise LibraryEventError("request body too large")

            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise LibraryEventError("request body must be valid JSON") from exc
            if not isinstance(payload, dict):
                raise LibraryEventError("request body must be a JSON object")
            return payload

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return LibraryEventHandler


def _payload_track(payload: dict[str, Any]) -> str:
    track = payload.get("track")
    if not isinstance(track, str) or not track.strip():
        raise LibraryEventError("track must be a non-empty string")
    track = track.strip()
    if not track.isdigit():
        raise LibraryEventError("track must contain only digits")
    return track.zfill(3)


def _metadata_string(metadata: dict[str, Any], field: str) -> str:
    value = metadata.get(field)
    if not isinstance(value, str):
        return ""
    return value.strip()[:300]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harmonia-library-events")
    parser.add_argument("--host", default=DEFAULT_HOST, help="host to bind")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="port to bind")
    parser.add_argument("--manifest", type=Path, required=True, help="library manifest JSON path")
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY_PATH, help="played history JSONL path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_server(args.host, args.port, args.manifest, args.history)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
