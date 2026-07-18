from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from harmonia_scheduler.cli import main
from harmonia_scheduler.scheduler import Scheduler, annotate, load_manifest, simulate


MANIFEST_ITEMS = [
    {
        "track": "001",
        "title": "First Song",
        "displayTitle": "Track 001 - First Song",
        "path": "01 - First Song.flac",
        "url": "/originals/01 - First Song.flac",
    },
    {
        "track": "002",
        "title": "Second Song",
        "displayTitle": "Track 002 - Second Song",
        "path": "02 - Second Song.flac",
        "url": "/originals/02 - Second Song.flac",
    },
    {
        "track": "003",
        "title": "Quote Song",
        "displayTitle": "Track 003 - A \"Quoted\" Song",
        "path": "03 - Quote Song.flac",
        "url": "/originals/03 - Quote Song.flac",
    },
]


def write_manifest(directory: Path) -> Path:
    manifest_path = directory / "manifest.json"
    _ = manifest_path.write_text(json.dumps(MANIFEST_ITEMS, ensure_ascii=False), encoding="utf-8")
    return manifest_path


class SchedulerTests(unittest.TestCase):
    def test_annotate_matches_liquidsoap_playlist_format(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            track = load_manifest(write_manifest(Path(temp_dir)))[0]

        self.assertEqual(
            annotate(track),
            'annotate:radio_track="001",tracknumber="001",title="Track 001 - First Song":/music/01 - First Song.flac',
        )

    def test_annotate_escapes_liquidsoap_metadata_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            track = load_manifest(write_manifest(Path(temp_dir)))[2]

        self.assertEqual(
            annotate(track),
            'annotate:radio_track="003",tracknumber="003",title="Track 003 - A \\"Quoted\\" Song":/music/03 - Quote Song.flac',
        )

    def test_manifest_has_no_repeats_before_cycle_exhaustion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tracks = load_manifest(write_manifest(Path(temp_dir)))
        selected = simulate(tracks, len(tracks), seed="test-cycle")

        self.assertEqual(len(selected), 3)
        self.assertEqual(len({track.track for track in selected}), 3)

    def test_next_persists_state_under_configured_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            manifest_path = write_manifest(temp_path)
            tracks = load_manifest(manifest_path)
            state_path = temp_path / "state.json"
            scheduler = Scheduler(tracks, seed="persisted")
            first = scheduler.next_track()
            scheduler.save(state_path)

            resumed = Scheduler.from_paths(manifest_path, state_path)
            second = resumed.next_track()
            resumed.save(state_path)

            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertNotEqual(first.track, second.track)
        self.assertEqual(state["position"], 2)
        self.assertEqual(state["played_in_cycle"], [first.track, second.track])

    def test_cli_reset_and_next_use_default_annotate_shape_with_custom_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            manifest_path = write_manifest(temp_path)
            state_path = temp_path / "state.json"
            reset_code = main(["--manifest", str(manifest_path), "--state", str(state_path), "reset", "--seed", "cli"])
            next_code = main(["--manifest", str(manifest_path), "--state", str(state_path), "next"])

        self.assertEqual(reset_code, 0)
        self.assertEqual(next_code, 0)


if __name__ == "__main__":
    unittest.main()
