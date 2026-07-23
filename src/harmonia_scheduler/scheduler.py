from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


DEFAULT_MANIFEST_PATH = Path("data/library/manifest.json")
DEFAULT_STATE_PATH = Path("data/scheduler/state.json")
STATE_VERSION = 1


@dataclass(frozen=True)
class Track:
    track: str
    title: str
    display_title: str
    path: str
    url: str


def load_manifest(path: Path = DEFAULT_MANIFEST_PATH) -> list[Track]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SchedulerError(f"manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SchedulerError(f"manifest is not valid JSON: {path}: {exc}") from exc

    if not isinstance(raw, list) or not raw:
        raise SchedulerError("manifest must be a non-empty JSON list")

    tracks: list[Track] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise SchedulerError(f"manifest item {index} is not an object")
        try:
            track = str(item["track"])
            title = str(item["title"])
            display_title = str(item["displayTitle"])
            rel_path = str(item["path"])
            url = str(item["url"])
        except KeyError as exc:
            raise SchedulerError(f"manifest item {index} is missing {exc.args[0]!r}") from exc
        _validate_track_id(track, index)
        _validate_text(title, f"manifest item {index} title")
        _validate_text(display_title, f"manifest item {index} displayTitle")
        _validate_track_path(rel_path, index)
        _validate_text(url, f"manifest item {index} url")
        if track in seen:
            raise SchedulerError(f"manifest contains duplicate track id {track!r}")
        seen.add(track)
        tracks.append(Track(track=track, title=title, display_title=display_title, path=rel_path, url=url))

    return tracks


def manifest_fingerprint(tracks: list[Track]) -> str:
    payload = json.dumps(
        [track.__dict__ for track in tracks],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def annotate(track: Track) -> str:
    display_title = _liq_escape(track.display_title)
    return (
        f'annotate:radio_track="{track.track}",tracknumber="{track.track}",'
        f'title="{display_title}":/music/{track.path}'
    )


def build_library_tracks(music_root: Path) -> list[Track]:
    if not music_root.exists():
        raise SchedulerError(f"music root not found: {music_root}")
    if not music_root.is_dir():
        raise SchedulerError(f"music root is not a directory: {music_root}")

    paths = sorted(path for path in music_root.rglob("*") if path.is_file() and path.suffix.lower() == ".flac")
    if not paths:
        raise SchedulerError(f"music root contains no FLAC files: {music_root}")

    tracks: list[Track] = []
    for index, path in enumerate(paths, start=1):
        rel_path = path.relative_to(music_root).as_posix()
        _validate_track_path(rel_path, index)
        title = _clean_track_title(path.name)
        track = f"{index:03d}"
        display_title = f"Track {track} - {title}"
        tracks.append(
            Track(
                track=track,
                title=title,
                display_title=display_title,
                path=rel_path,
                url=f"/originals/{rel_path}",
            )
        )

    return tracks


def write_manifest(path: Path, tracks: list[Track]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "track": track.track,
            "title": track.title,
            "displayTitle": track.display_title,
            "path": track.path,
            "url": track.url,
        }
        for track in tracks
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class SchedulerError(RuntimeError):
    pass


class Scheduler:
    def __init__(self, tracks: list[Track], state: dict[str, Any] | None = None, seed: str | None = None) -> None:
        self.tracks = tracks
        self._tracks_by_id = {track.track: track for track in tracks}
        self.fingerprint = manifest_fingerprint(tracks)
        self.state = self._normalize_state(state, seed)

    @classmethod
    def from_paths(cls, manifest_path: Path, state_path: Path) -> "Scheduler":
        tracks = load_manifest(manifest_path)
        return cls(tracks, load_state(state_path))

    def reset(self, seed: str | None = None) -> None:
        self.state = self._new_state(seed=seed, cycle=0)

    def next_track(self) -> Track:
        if self.state["position"] >= len(self.state["order"]):
            self.state = self._new_state(seed=self.state.get("seed"), cycle=int(self.state["cycle"]) + 1)

        track_id = self.state["order"][self.state["position"]]
        self.state["position"] += 1
        self.state["played_in_cycle"].append(track_id)
        return self._tracks_by_id[track_id]

    def start_next_cycle(self) -> None:
        self.state = self._new_state(seed=self.state.get("seed"), cycle=int(self.state["cycle"]) + 1)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _normalize_state(self, state: dict[str, Any] | None, seed: str | None) -> dict[str, Any]:
        if state is None:
            return self._new_state(seed=seed, cycle=0)

        if state.get("version") != STATE_VERSION or state.get("manifest_fingerprint") != self.fingerprint:
            return self._new_state(seed=seed if seed is not None else _string_or_none(state.get("seed")), cycle=0)

        order = state.get("order")
        position = state.get("position")
        played = state.get("played_in_cycle")
        if not isinstance(order, list) or not all(isinstance(item, str) for item in order):
            return self._new_state(seed=seed if seed is not None else _string_or_none(state.get("seed")), cycle=0)
        if sorted(order) != sorted(self._tracks_by_id):
            return self._new_state(seed=seed if seed is not None else _string_or_none(state.get("seed")), cycle=0)
        if not isinstance(position, int) or position < 0 or position > len(order):
            return self._new_state(seed=seed if seed is not None else _string_or_none(state.get("seed")), cycle=0)
        if not isinstance(played, list) or played != order[:position]:
            return self._new_state(seed=seed if seed is not None else _string_or_none(state.get("seed")), cycle=0)

        normalized = dict(state)
        normalized["seed"] = seed if seed is not None else _string_or_none(state.get("seed"))
        return normalized

    def _new_state(self, seed: str | None, cycle: int) -> dict[str, Any]:
        order = [track.track for track in self.tracks]
        rng = random.Random(f"harmonia-scheduler:{self.fingerprint}:{seed or ''}:{cycle}")
        rng.shuffle(order)
        return {
            "version": STATE_VERSION,
            "manifest_fingerprint": self.fingerprint,
            "seed": seed,
            "cycle": cycle,
            "position": 0,
            "order": order,
            "played_in_cycle": [],
        }


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SchedulerError(f"state is not valid JSON: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SchedulerError(f"state must be a JSON object: {path}")
    return raw


def generate_playlist(scheduler: Scheduler, count: int) -> list[str]:
    if count < 1:
        raise SchedulerError("playlist count must be positive")
    return [annotate(scheduler.next_track()) for _ in range(count)]


def write_playlist(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_playlist(lines), encoding="utf-8")


def format_playlist(lines: list[str]) -> str:
    return "#EXTM3U\n# Harmonia scheduler managed playlist\n" + "".join(f"{line}\n" for line in lines)


def simulate(tracks: list[Track], count: int, seed: str | None = None) -> list[Track]:
    if count < 0:
        raise SchedulerError("simulation count must be non-negative")
    scheduler = Scheduler(tracks, seed=seed)
    selected: list[Track] = []
    seen_in_cycle: set[str] = set()
    cycle_size = len(tracks)

    for index in range(count):
        track = scheduler.next_track()
        if track.track in seen_in_cycle:
            raise SchedulerError(
                f"premature repeat at selection {index + 1}: track {track.track} repeated before cycle exhaustion"
            )
        selected.append(track)
        seen_in_cycle.add(track.track)
        if len(seen_in_cycle) == cycle_size:
            seen_in_cycle.clear()

    return selected


def _liq_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _clean_track_title(filename: str) -> str:
    title = re.sub(r"\.[Ff][Ll][Aa][Cc]$", "", filename)
    title = re.sub(r"^[0-9]+([._ -]+)?", "", title)
    return title.replace("_", " ")


def _validate_track_id(value: str, index: int) -> None:
    _validate_text(value, f"manifest item {index} track")
    if any(char in value for char in ('"', "'", ",", ":")):
        raise SchedulerError(f"manifest item {index} track contains invalid playlist metadata characters")


def _validate_text(value: str, label: str) -> None:
    if _has_control_char(value):
        raise SchedulerError(f"{label} contains control characters")


def _validate_track_path(value: str, index: int) -> None:
    _validate_text(value, f"manifest item {index} path")
    if "\\" in value:
        raise SchedulerError(f"manifest item {index} path must use POSIX separators")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "" in path.parts:
        raise SchedulerError(f"manifest item {index} path must stay inside the music library")
    if path.suffix.lower() != ".flac":
        raise SchedulerError(f"manifest item {index} path must point to a FLAC file")


def _has_control_char(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
