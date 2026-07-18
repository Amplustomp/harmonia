from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .scheduler import DEFAULT_MANIFEST_PATH, DEFAULT_STATE_PATH, Scheduler, SchedulerError, annotate, load_manifest, simulate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harmonia-scheduler")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH, help="manifest JSON path")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH, help="scheduler state JSON path")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("next", help="persist and print the next annotated URI")

    simulate_parser = subparsers.add_parser("simulate", help="simulate selections without writing scheduler state")
    simulate_parser.add_argument("--count", type=int, required=True, help="number of selections to simulate")
    simulate_parser.add_argument("--seed", help="deterministic simulation seed")

    reset_parser = subparsers.add_parser("reset", help="reset scheduler state")
    reset_parser.add_argument("--seed", help="deterministic seed for future persisted selections")

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
    except SchedulerError as exc:
        print(f"harmonia-scheduler: {exc}", file=sys.stderr)
        return 1

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
