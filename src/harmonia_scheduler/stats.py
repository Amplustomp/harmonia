from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .scheduler import DEFAULT_MANIFEST_PATH, DEFAULT_STATE_PATH, Scheduler, SchedulerError, Track, load_manifest, load_state

DEFAULT_HISTORY_PATH = Path("data/played-history.jsonl")
DEFAULT_NOW_PLAYING_PATH = Path("data/now-playing.json")
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
    radio_history = [entry for entry in history if entry.get("source") != "library"]
    tracks_by_id = {track.track: track for track in tracks}
    metadata_by_track = _track_history_metadata(history)
    playback_cycle = _playback_cycle_stats(radio_history, tracks, scheduler.state["order"], tracks_by_id)

    return {
        "track_count": len(tracks),
        "tracks": _track_catalog(tracks, metadata_by_track),
        "scheduler": _scheduler_stats(scheduler, tracks_by_id),
        "playback_cycle": playback_cycle,
        "pending_tracks": playback_cycle["pending_tracks"],
        "recently_played": _recently_played(history, tracks_by_id, recent_limit),
        "top_tracks": _top_tracks(history, tracks_by_id, metadata_by_track, top_limit),
        "top_artists": _top_artists(history, top_limit),
    }


def build_public_info(
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    history_path: Path = DEFAULT_HISTORY_PATH,
    now_playing_path: Path = DEFAULT_NOW_PLAYING_PATH,
    icecast_status_url: str | None = None,
) -> dict[str, Any]:
    tracks = load_manifest(manifest_path)
    scheduler = Scheduler(tracks, load_state(state_path))
    history = load_played_history(history_path)
    now_playing = load_now_playing(now_playing_path)
    radio_history = [entry for entry in history if entry.get("source") != "library"]
    tracks_by_id = {track.track: track for track in tracks}
    radio_metadata_by_track = _track_history_metadata(radio_history)
    current = _current_public_summary(now_playing, radio_history, tracks_by_id)

    return {
        "current": current,
        "previous": _previous_public_summary(radio_history, current, tracks_by_id),
        "upcoming": _upcoming_public_summary(radio_history, tracks, scheduler.state["order"], tracks_by_id, radio_metadata_by_track, current),
        "listeners": {"current": _icecast_listener_count(icecast_status_url)},
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _icecast_listener_count(status_url: str | None) -> int | None:
    if not status_url:
        return None

    try:
        with urllib.request.urlopen(status_url, timeout=5) as response:
            status = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    return _listener_count_from_icecast_status(status)


def _listener_count_from_icecast_status(status: dict[str, Any], mounts: tuple[str, ...] = ("/aac",)) -> int | None:
    sources = status.get("icestats", {}).get("source") if isinstance(status.get("icestats"), dict) else None
    if isinstance(sources, dict):
        source_entries = [sources]
    elif isinstance(sources, list):
        source_entries = [source for source in sources if isinstance(source, dict)]
    else:
        return None

    matching_counts = [_source_listener_count(source) for source in source_entries if _source_matches_mount(source, mounts)]
    counts = [count for count in matching_counts if count is not None]
    if counts:
        return sum(counts)

    return None


def _source_matches_mount(source: dict[str, Any], mounts: tuple[str, ...]) -> bool:
    mount = _string_or_empty(source.get("mount"))
    listen_url = _string_or_empty(source.get("listenurl"))
    listen_path = urllib.parse.urlparse(listen_url).path if listen_url else ""
    return any(value in mounts for value in (mount, listen_path))


def _source_listener_count(source: dict[str, Any]) -> int | None:
    value = source.get("listeners")
    if isinstance(value, bool) or value is None:
        return None
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None


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


def load_now_playing(path: Path = DEFAULT_NOW_PLAYING_PATH) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SchedulerError(f"now-playing JSON is not valid: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SchedulerError(f"now-playing JSON must be an object: {path}")
    return raw


def write_stats(path: Path, stats: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_stats(stats), encoding="utf-8")


def write_public_info(path: Path, info: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_stats(info), encoding="utf-8")


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


def _top_tracks(
    entries: list[dict[str, Any]],
    tracks_by_id: dict[str, Track],
    metadata_by_track: dict[str, dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for entry in entries:
        track_id = _string_or_empty(entry.get("tracknumber"))
        if track_id:
            counts[track_id] += 1

    top: list[dict[str, Any]] = []
    for track_id, count in counts.most_common(limit):
        summary = _track_summary(track_id, tracks_by_id)
        summary.update(metadata_by_track.get(track_id, {}))
        summary["plays"] = count
        top.append(summary)
    return top


def _track_catalog(tracks: list[Track], metadata_by_track: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for track in tracks:
        summary = _track_summary(track.track, {track.track: track})
        summary.update(metadata_by_track.get(track.track, {}))
        catalog.append(summary)
    return catalog


def _track_history_metadata(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    metadata_by_track: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    for entry in entries:
        track_id = _string_or_empty(entry.get("tracknumber"))
        if not track_id:
            continue

        counts[track_id] += 1
        metadata = metadata_by_track.setdefault(track_id, {})
        for source_field, target_field in (("artist", "artist"), ("album", "album"), ("genre", "genre"), ("title", "title")):
            value = _string_or_empty(entry.get(source_field))
            if value:
                metadata[target_field] = value

    for track_id, count in counts.items():
        metadata_by_track.setdefault(track_id, {})["plays"] = count
    return metadata_by_track


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


def _current_public_summary(
    now_playing: dict[str, Any],
    entries: list[dict[str, Any]],
    tracks_by_id: dict[str, Track],
) -> dict[str, Any] | None:
    if now_playing:
        track_id = _string_or_empty(now_playing.get("tracknumber")) or _string_or_empty(now_playing.get("radio_track"))
        summary = _public_track_summary(track_id, tracks_by_id) if track_id else {}
        for field in ("title", "artist", "album"):
            value = _string_or_empty(now_playing.get(field))
            if value:
                summary[field] = value
        if track_id and "track" not in summary:
            summary["track"] = track_id
        if summary:
            return summary

    for entry in reversed(entries):
        return _history_public_summary(entry, tracks_by_id)
    return None


def _previous_public_summary(
    entries: list[dict[str, Any]],
    current: dict[str, Any] | None,
    tracks_by_id: dict[str, Track],
) -> dict[str, Any] | None:
    for entry in reversed(entries):
        if _matches_current(entry, current):
            continue
        return _history_public_summary(entry, tracks_by_id)
    return None


def _upcoming_public_summary(
    entries: list[dict[str, Any]],
    tracks: list[Track],
    scheduler_order: list[str],
    tracks_by_id: dict[str, Track],
    metadata_by_track: dict[str, dict[str, Any]],
    current: dict[str, Any] | None,
) -> dict[str, Any] | None:
    current_track = _string_or_empty(current.get("track")) if current else ""
    pending_tracks = _playback_cycle_stats(entries, tracks, scheduler_order, tracks_by_id)["pending_tracks"]
    for pending in pending_tracks:
        track_id = _string_or_empty(pending.get("track"))
        if track_id:
            if current_track and track_id == current_track:
                continue
            summary = _public_track_summary(track_id, tracks_by_id)
            for field in ("artist", "album"):
                value = _string_or_empty(metadata_by_track.get(track_id, {}).get(field))
                if value:
                    summary[field] = value
            return summary
    return None


def _history_public_summary(entry: dict[str, Any], tracks_by_id: dict[str, Track]) -> dict[str, Any]:
    track_id = _string_or_empty(entry.get("tracknumber"))
    summary: dict[str, Any] = _public_track_summary(track_id, tracks_by_id) if track_id else {"track": None}
    title = _string_or_empty(entry.get("title"))
    if title:
        summary["title"] = title
    for field in ("played_at", "artist", "album"):
        value = _string_or_empty(entry.get(field))
        if value:
            summary[field] = value
    return summary


def _public_track_summary(track_id: str, tracks_by_id: dict[str, Track]) -> dict[str, Any]:
    track = tracks_by_id.get(track_id)
    if track is None:
        return {"track": track_id, "title": None, "displayTitle": None}
    return {"track": track.track, "title": track.title, "displayTitle": track.display_title}


def _matches_current(entry: dict[str, Any], current: dict[str, Any] | None) -> bool:
    if not current:
        return False

    entry_track = _string_or_empty(entry.get("tracknumber"))
    current_track = _string_or_empty(current.get("track"))
    if entry_track and current_track:
        return entry_track == current_track

    entry_title = _string_or_empty(entry.get("title"))
    current_titles = {
        _string_or_empty(current.get("title")),
        _string_or_empty(current.get("displayTitle")),
    }
    return bool(entry_title and entry_title in current_titles)


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
