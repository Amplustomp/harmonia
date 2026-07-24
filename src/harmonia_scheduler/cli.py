from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .stats import DEFAULT_HISTORY_PATH, DEFAULT_NOW_PLAYING_PATH, build_public_info, build_stats, format_stats, write_public_info, write_stats

from .scheduler import (
    DEFAULT_MANIFEST_PATH,
    DEFAULT_STATE_PATH,
    Scheduler,
    SchedulerError,
    annotate,
    build_library_tracks,
    format_playlist,
    generate_playlist,
    load_manifest,
    load_state,
    simulate,
    write_manifest,
    write_playlist,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harmonia-scheduler")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH, help="manifest JSON path")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH, help="scheduler state JSON path")
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY_PATH, help="played history JSONL path")
    parser.add_argument("--now-playing", type=Path, default=DEFAULT_NOW_PLAYING_PATH, help="now-playing JSON path")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("next", help="persist and print the next annotated URI")

    simulate_parser = subparsers.add_parser("simulate", help="simulate selections without writing scheduler state")
    simulate_parser.add_argument("--count", type=int, required=True, help="number of selections to simulate")
    simulate_parser.add_argument("--seed", help="deterministic simulation seed")

    reset_parser = subparsers.add_parser("reset", help="reset scheduler state")
    reset_parser.add_argument("--seed", help="deterministic seed for future persisted selections")

    playlist_parser = subparsers.add_parser("playlist", help="write or print a scheduler-managed annotated playlist")
    playlist_parser.add_argument(
        "--count",
        type=int,
        help="number of playlist entries to generate; defaults to the manifest size",
    )
    playlist_parser.add_argument("--output", type=Path, help="playlist output path; when set, scheduler state is advanced and saved")
    playlist_parser.add_argument("--seed", help="deterministic seed for dry-run output or new persisted state")

    library_parser = subparsers.add_parser("library", help="write manifest and v1 fallback playlist from a music directory")
    library_parser.add_argument("--music-root", type=Path, required=True, help="mounted music directory to scan")
    library_parser.add_argument("--manifest-output", type=Path, required=True, help="manifest JSON output path")
    library_parser.add_argument("--playlist-output", type=Path, required=True, help="fallback annotated playlist output path")

    stats_parser = subparsers.add_parser("stats", help="print read-only playback stats as JSON")
    stats_parser.add_argument("--output", type=Path, help="stats JSON output path; stdout is used when omitted")
    stats_parser.add_argument("--recent-limit", type=int, default=10, help="number of recent plays to include")
    stats_parser.add_argument("--top-limit", type=int, default=10, help="number of top tracks and artists to include")

    public_info_parser = subparsers.add_parser("public-info", help="print sanitized public radio info as JSON")
    public_info_parser.add_argument("--output", type=Path, help="public radio info JSON output path; stdout is used when omitted")
    public_info_parser.add_argument("--icecast-status-url", help="Icecast status-json.xsl URL used to include sanitized listener counts")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "next":
            scheduler = Scheduler.from_paths(args.manifest, args.state)
            track = scheduler.next_track()
            scheduler.save(args.state)
            print(annotate(track))
            return 0

        if args.command == "simulate":
            tracks = load_manifest(args.manifest)
            selected = simulate(tracks, args.count, seed=args.seed)
            for track in selected:
                print(annotate(track))
            return 0

        if args.command == "reset":
            scheduler = Scheduler(load_manifest(args.manifest), seed=args.seed)
            scheduler.reset(seed=args.seed)
            scheduler.save(args.state)
            print(f"reset scheduler state: {args.state}")
            return 0

        if args.command == "playlist":
            tracks = load_manifest(args.manifest)
            count = args.count if args.count is not None else len(tracks)
            if args.output is None:
                scheduler = Scheduler(tracks, seed=args.seed)
                print(format_playlist(generate_playlist(scheduler, count)), end="")
                return 0

            scheduler = Scheduler(tracks, load_state(args.state), seed=args.seed)
            if args.count is None and scheduler.state["position"] > 0:
                scheduler.start_next_cycle()
            write_playlist(args.output, generate_playlist(scheduler, count))
            scheduler.save(args.state)
            print(f"wrote scheduler playlist: {args.output}")
            return 0

        if args.command == "library":
            tracks = build_library_tracks(args.music_root)
            write_manifest(args.manifest_output, tracks)
            write_playlist(args.playlist_output, [annotate(track) for track in tracks])
            print(f"indexed {len(tracks)} tracks: {args.manifest_output}")
            return 0

        if args.command == "stats":
            stats = build_stats(
                manifest_path=args.manifest,
                state_path=args.state,
                history_path=args.history,
                recent_limit=args.recent_limit,
                top_limit=args.top_limit,
            )
            if args.output is None:
                print(format_stats(stats), end="")
            else:
                write_stats(args.output, stats)
                print(f"wrote scheduler stats: {args.output}")
            return 0

        if args.command == "public-info":
            info = build_public_info(
                manifest_path=args.manifest,
                state_path=args.state,
                history_path=args.history,
                now_playing_path=args.now_playing,
                icecast_status_url=args.icecast_status_url,
            )
            if args.output is None:
                print(format_stats(info), end="")
            else:
                write_public_info(args.output, info)
                print(f"wrote public radio info: {args.output}")
            return 0
    except SchedulerError as exc:
        print(f"harmonia-scheduler: {exc}", file=sys.stderr)
        return 1

    parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
