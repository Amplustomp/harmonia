from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .scheduler import DEFAULT_MANIFEST_PATH, DEFAULT_STATE_PATH, Scheduler, SchedulerError, Track, load_manifest, load_state

DEFAULT_HISTORY_PATH = Path("data/played-history.jsonl")
RECENT_PLAY_LIMIT = 10
TOP_LIMIT = 10


def build_stats(
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    history_path: Path = DEFAULT_HISTORY_PATH,
    recent_limit: int = RECENT_PLAY_LIMIT,
    top_limit: int = TOP_LIMIT,
) -> dict[str, Any]:
    if recent_limit < 0:
        raise SchedulerError("recent limit must be non-negative")
    if top_limit < 0:
        raise SchedulerError("top limit must be non-negative")

    tracks = load_manifest(manifest_path)
    scheduler = Scheduler(tracks, load_state(state_path))
    history = load_played_history(history_path)
    tracks_by_id = {track.track: track for track in tracks}
    playback_cycle = _playback_cycle_stats(history, tracks, scheduler.state["order"], tracks_by_id)

    return {
        "track_count": len(tracks),
        "scheduler": _scheduler_stats(scheduler, tracks_by_id),
        "playback_cycle": playback_cycle,
        "pending_tracks": playback_cycle["pending_tracks"],
        "recently_played": _recently_played(history, tracks_by_id, recent_limit),
        "top_tracks": _top_tracks(history, tracks_by_id, top_limit),
        "top_artists": _top_artists(history, top_limit),
    }


def load_played_history(path: Path = DEFAULT_HISTORY_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    entries: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SchedulerError(f"played history line {line_number} is not valid JSON: {path}: {exc}") from exc
        if not isinstance(entry, dict):
            raise SchedulerError(f"played history line {line_number} must be a JSON object: {path}")
        _validate_history_entry(entry, line_number, path)
        entries.append(entry)
    return entries


def write_stats(path: Path, stats: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_stats(stats), encoding="utf-8")


def format_stats(stats: dict[str, Any]) -> str:
    return json.dumps(stats, ensure_ascii=False, indent=2) + "\n"


def _scheduler_stats(scheduler: Scheduler, tracks_by_id: dict[str, Track]) -> dict[str, Any]:
    order = scheduler.state["order"]
    position = scheduler.state["position"]
    total = len(order)
    pending = total - position
    return {
        "cycle": scheduler.state["cycle"],
        "position": position,
        "total": total,
        "progress": {
            "played": position,
            "pending": pending,
            "percent": round((position / total) * 100, 2) if total else 0.0,
        },
        "played_in_cycle": _track_summaries(scheduler.state["played_in_cycle"], tracks_by_id),
    }


def _recently_played(entries: list[dict[str, Any]], tracks_by_id: dict[str, Track], limit: int) -> list[dict[str, Any]]:
    if limit == 0:
        return []
    return [_history_summary(entry, tracks_by_id) for entry in reversed(entries[-limit:])]


def _top_tracks(entries: list[dict[str, Any]], tracks_by_id: dict[str, Track], limit: int) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for entry in entries:
        track_id = _string_or_empty(entry.get("tracknumber"))
        if track_id:
            counts[track_id] += 1

    top: list[dict[str, Any]] = []
    for track_id, count in counts.most_common(limit):
        summary = _track_summary(track_id, tracks_by_id)
        summary["plays"] = count
        top.append(summary)
    return top


def _top_artists(entries: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for entry in entries:
        artist = _string_or_empty(entry.get("artist")) or "Unknown Artist"
        counts[artist] += 1
    return [{"artist": artist, "plays": count} for artist, count in counts.most_common(limit)]


def _playback_cycle_stats(
    entries: list[dict[str, Any]],
    tracks: list[Track],
    scheduler_order: list[str],
    tracks_by_id: dict[str, Track],
) -> dict[str, Any]:
    played_ids = _current_playback_cycle_ids(entries, tracks_by_id)
    played_set = set(played_ids)
    all_ids = [track.track for track in tracks]
    ordered_ids = [track_id for track_id in scheduler_order if track_id in tracks_by_id]
    pending_ids = [track_id for track_id in ordered_ids if track_id not in played_set]
    pending_ids.extend(track_id for track_id in all_ids if track_id not in played_set and track_id not in ordered_ids)
    total = len(tracks)

    return {
        "played": len(played_ids),
        "pending": len(pending_ids),
        "total": total,
        "percent": round((len(played_ids) / total) * 100, 2) if total else 0.0,
        "played_tracks": _track_summaries(played_ids, tracks_by_id),
        "pending_tracks": _track_summaries(pending_ids, tracks_by_id),
    }


def _current_playback_cycle_ids(entries: list[dict[str, Any]], tracks_by_id: dict[str, Track]) -> list[str]:
    seen: set[str] = set()
    cycle_reversed: list[str] = []
    for entry in reversed(entries):
        track_id = _string_or_empty(entry.get("tracknumber"))
        if not track_id or track_id not in tracks_by_id:
            continue
        if track_id in seen:
            break
        seen.add(track_id)
        cycle_reversed.append(track_id)
    return list(reversed(cycle_reversed))


def _history_summary(entry: dict[str, Any], tracks_by_id: dict[str, Track]) -> dict[str, Any]:
    track_id = _string_or_empty(entry.get("tracknumber"))
    summary = _track_summary(track_id, tracks_by_id) if track_id else {"track": None, "title": _string_or_empty(entry.get("title"))}
    summary.update(
        {
            "played_at": _string_or_empty(entry.get("played_at")),
            "played_at_epoch": entry.get("played_at_epoch"),
            "artist": _string_or_empty(entry.get("artist")),
            "album": _string_or_empty(entry.get("album")),
            "genre": _string_or_empty(entry.get("genre")),
        }
    )
    return summary


def _track_summaries(track_ids: list[str], tracks_by_id: dict[str, Track]) -> list[dict[str, Any]]:
    return [_track_summary(track_id, tracks_by_id) for track_id in track_ids]


def _track_summary(track_id: str, tracks_by_id: dict[str, Track]) -> dict[str, Any]:
    track = tracks_by_id.get(track_id)
    if track is None:
        return {"track": track_id, "title": None, "displayTitle": None, "path": None, "url": None}
    return {
        "track": track.track,
        "title": track.title,
        "displayTitle": track.display_title,
        "path": track.path,
        "url": track.url,
    }


def _validate_history_entry(entry: dict[str, Any], line_number: int, path: Path) -> None:
    for field in ("played_at", "played_at_epoch", "artist", "title", "tracknumber", "album", "genre"):
        if field not in entry:
            raise SchedulerError(f"played history line {line_number} is missing {field!r}: {path}")
    if not isinstance(entry["played_at"], str):
        raise SchedulerError(f"played history line {line_number} field 'played_at' must be a string: {path}")
    if not isinstance(entry["played_at_epoch"], int | float):
        raise SchedulerError(f"played history line {line_number} field 'played_at_epoch' must be a number: {path}")
    for field in ("artist", "title", "tracknumber", "album", "genre"):
        if not isinstance(entry[field], str):
            raise SchedulerError(f"played history line {line_number} field {field!r} must be a string: {path}")


def _string_or_empty(value: object) -> str:
    return value if isinstance(value, str) else ""
