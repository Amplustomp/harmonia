from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from harmonia_scheduler.cli import main
from harmonia_scheduler.scheduler import Scheduler, SchedulerError, annotate, build_library_tracks, load_manifest, simulate
from harmonia_scheduler.stats import build_stats, load_played_history


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


def touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


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

    def test_manifest_rejects_paths_outside_music_library(self) -> None:
        for bad_path in ("../escape.flac", "/music/absolute.flac", "nested/../../escape.flac", "track.mp3"):
            with self.subTest(path=bad_path), tempfile.TemporaryDirectory() as temp_dir:
                manifest_path = Path(temp_dir) / "manifest.json"
                item = dict(MANIFEST_ITEMS[0])
                item["path"] = bad_path
                manifest_path.write_text(json.dumps([item]), encoding="utf-8")

                with self.assertRaises(SchedulerError):
                    load_manifest(manifest_path)

    def test_manifest_rejects_playlist_control_characters(self) -> None:
        for field in ("track", "title", "displayTitle", "path"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp_dir:
                manifest_path = Path(temp_dir) / "manifest.json"
                item = dict(MANIFEST_ITEMS[0])
                item[field] = f"bad\n{item[field]}"
                manifest_path.write_text(json.dumps([item]), encoding="utf-8")

                with self.assertRaises(SchedulerError):
                    load_manifest(manifest_path)

    def test_manifest_rejects_track_metadata_separators(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.json"
            item = dict(MANIFEST_ITEMS[0])
            item["track"] = "001,bad"
            manifest_path.write_text(json.dumps([item]), encoding="utf-8")

            with self.assertRaises(SchedulerError):
                load_manifest(manifest_path)

    def test_build_library_tracks_matches_manifest_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            music_root = Path(temp_dir)
            touch(music_root / "01 - First Song.flac")
            touch(music_root / "nested" / "02_Second_Song.FLAC")

            tracks = build_library_tracks(music_root)

        self.assertEqual([track.track for track in tracks], ["001", "002"])
        self.assertEqual(tracks[0].title, "First Song")
        self.assertEqual(tracks[1].title, "Second Song")
        self.assertEqual(tracks[1].path, "nested/02_Second_Song.FLAC")
        self.assertEqual(annotate(tracks[1]), 'annotate:radio_track="002",tracknumber="002",title="Track 002 - Second Song":/music/nested/02_Second_Song.FLAC')

    def test_build_library_tracks_rejects_control_chars_in_filenames(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            music_root = Path(temp_dir)
            touch(music_root / "bad\ntrack.flac")

            with self.assertRaises(SchedulerError):
                build_library_tracks(music_root)

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

    def test_cli_playlist_prints_annotated_m3u_without_state_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            manifest_path = write_manifest(temp_path)
            state_path = temp_path / "state.json"
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = main([
                    "--manifest",
                    str(manifest_path),
                    "--state",
                    str(state_path),
                    "playlist",
                    "--count",
                    "2",
                    "--seed",
                    "playlist-dry-run",
                ])

            output = stdout.getvalue().splitlines()

        self.assertEqual(code, 0)
        self.assertEqual(output[0], "#EXTM3U")
        self.assertEqual(output[1], "# Harmonia scheduler managed playlist")
        self.assertEqual(len(output[2:]), 2)
        self.assertTrue(all(line.startswith("annotate:radio_track=") for line in output[2:]))
        self.assertFalse(state_path.exists())

    def test_cli_playlist_defaults_to_full_manifest_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            manifest_path = write_manifest(temp_path)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = main([
                    "--manifest",
                    str(manifest_path),
                    "playlist",
                    "--seed",
                    "full-cycle",
                ])

            output = stdout.getvalue().splitlines()

        self.assertEqual(code, 0)
        self.assertEqual(len(output[2:]), len(MANIFEST_ITEMS))
        self.assertEqual(len(set(output[2:])), len(MANIFEST_ITEMS))

    def test_cli_playlist_output_writes_file_and_persists_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            manifest_path = write_manifest(temp_path)
            state_path = temp_path / "scheduler" / "state.json"
            output_path = temp_path / "scheduler" / "radio.m3u"
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = main([
                    "--manifest",
                    str(manifest_path),
                    "--state",
                    str(state_path),
                    "playlist",
                    "--count",
                    "3",
                    "--output",
                    str(output_path),
                    "--seed",
                    "playlist-file",
                ])

            playlist = output_path.read_text(encoding="utf-8").splitlines()
            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertIn(f"wrote scheduler playlist: {output_path}", stdout.getvalue())
        self.assertEqual(playlist[0], "#EXTM3U")
        self.assertEqual(playlist[1], "# Harmonia scheduler managed playlist")
        self.assertEqual(len(playlist[2:]), 3)
        self.assertEqual(state["position"], 3)
        self.assertEqual(state["played_in_cycle"], state["order"][:3])

    def test_cli_library_writes_manifest_and_fallback_playlist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            music_root = temp_path / "music"
            manifest_path = temp_path / "state" / "manifest.json"
            playlist_path = temp_path / "radio.m3u"
            touch(music_root / "01 - First Song.flac")
            touch(music_root / "02 - Second Song.flac")

            code = main([
                "library",
                "--music-root",
                str(music_root),
                "--manifest-output",
                str(manifest_path),
                "--playlist-output",
                str(playlist_path),
            ])

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            playlist = playlist_path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(code, 0)
        self.assertEqual(len(manifest), 2)
        self.assertEqual(playlist[0], "#EXTM3U")
        self.assertEqual(len([line for line in playlist if line.startswith("annotate:")]), 2)

    def test_cli_playlist_output_full_cycle_starts_new_cycle_from_partial_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            manifest_path = write_manifest(temp_path)
            state_path = temp_path / "scheduler" / "state.json"
            output_path = temp_path / "scheduler" / "radio.m3u"
            scheduler = Scheduler(load_manifest(manifest_path), seed="partial-cycle")
            _ = scheduler.next_track()
            scheduler.save(state_path)

            code = main([
                "--manifest",
                str(manifest_path),
                "--state",
                str(state_path),
                "playlist",
                "--output",
                str(output_path),
            ])

            entries = [line for line in output_path.read_text(encoding="utf-8").splitlines() if line.startswith("annotate:")]
            state = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertEqual(len(entries), len(MANIFEST_ITEMS))
        self.assertEqual(len(set(entries)), len(MANIFEST_ITEMS))
        self.assertEqual(state["cycle"], 1)
        self.assertEqual(state["position"], len(MANIFEST_ITEMS))

    def test_cli_playlist_has_no_repeats_before_cycle_exhaustion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            manifest_path = write_manifest(temp_path)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = main([
                    "--manifest",
                    str(manifest_path),
                    "playlist",
                    "--count",
                    str(len(MANIFEST_ITEMS)),
                    "--seed",
                    "playlist-cycle",
                ])

            track_ids = [line.split('"')[1] for line in stdout.getvalue().splitlines()[2:]]

        self.assertEqual(code, 0)
        self.assertEqual(len(track_ids), len(MANIFEST_ITEMS))
        self.assertEqual(len(set(track_ids)), len(MANIFEST_ITEMS))

    def test_build_stats_reports_cycle_history_and_tops(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            manifest_path = write_manifest(temp_path)
            state_path = temp_path / "scheduler" / "state.json"
            history_path = temp_path / "played-history.jsonl"
            scheduler = Scheduler(load_manifest(manifest_path), seed="stats")
            first = scheduler.next_track()
            second = scheduler.next_track()
            scheduler.save(state_path)
            history_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "played_at": "2026-01-01T00:00:00+0000",
                                "played_at_epoch": 1.0,
                                "artist": "Artist A",
                                "title": first.display_title,
                                "tracknumber": first.track,
                                "album": "Album A",
                                "genre": "Anime",
                            }
                        ),
                        "",
                        json.dumps(
                            {
                                "played_at": "2026-01-01T00:03:00+0000",
                                "played_at_epoch": 2.0,
                                "artist": "Artist B",
                                "title": second.display_title,
                                "tracknumber": second.track,
                                "album": "Album B",
                                "genre": "J-Pop",
                            }
                        ),
                        json.dumps(
                            {
                                "played_at": "2026-01-01T00:06:00+0000",
                                "played_at_epoch": 3.0,
                                "artist": "Artist A",
                                "title": first.display_title,
                                "tracknumber": first.track,
                                "album": "Album A",
                                "genre": "Anime",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            stats = build_stats(manifest_path, state_path, history_path, recent_limit=2, top_limit=2)

        self.assertEqual(stats["track_count"], len(MANIFEST_ITEMS))
        self.assertEqual(stats["scheduler"]["cycle"], 0)
        self.assertEqual(stats["scheduler"]["position"], 2)
        self.assertEqual(stats["scheduler"]["progress"]["played"], 2)
        self.assertEqual(stats["scheduler"]["progress"]["pending"], 1)
        self.assertEqual(len(stats["pending_tracks"]), 1)
        self.assertEqual([item["track"] for item in stats["recently_played"]], [first.track, second.track])
        self.assertEqual(stats["top_tracks"][0]["track"], first.track)
        self.assertEqual(stats["top_tracks"][0]["plays"], 2)
        self.assertEqual(stats["top_artists"][0], {"artist": "Artist A", "plays": 2})

    def test_played_history_rejects_malformed_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir) / "played-history.jsonl"
            history_path.write_text(
                json.dumps(
                    {
                        "played_at": "2026-01-01T00:00:00+0000",
                        "played_at_epoch": 1.0,
                        "artist": "Artist A",
                        "title": "Track 001 - First Song",
                        "tracknumber": "001",
                        "album": "Album A",
                        "genre": "Anime",
                    }
                )
                + "\nnot-json\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SchedulerError, "line 2"):
                load_played_history(history_path)

    def test_played_history_rejects_invalid_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            history_path = Path(temp_dir) / "played-history.jsonl"
            history_path.write_text(json.dumps(["not", "object"]) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(SchedulerError, "line 1"):
                load_played_history(history_path)

    def test_cli_stats_prints_json_without_writing_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            manifest_path = write_manifest(temp_path)
            state_path = temp_path / "state.json"
            history_path = temp_path / "played-history.jsonl"
            history_path.write_text("", encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = main([
                    "--manifest",
                    str(manifest_path),
                    "--state",
                    str(state_path),
                    "--history",
                    str(history_path),
                    "stats",
                ])

            output = json.loads(stdout.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(output["track_count"], len(MANIFEST_ITEMS))
        self.assertEqual(output["scheduler"]["position"], 0)
        self.assertFalse(state_path.exists())

    def test_cli_stats_output_writes_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            manifest_path = write_manifest(temp_path)
            history_path = temp_path / "played-history.jsonl"
            output_path = temp_path / "stats.json"
            history_path.write_text("", encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = main([
                    "--manifest",
                    str(manifest_path),
                    "--history",
                    str(history_path),
                    "stats",
                    "--output",
                    str(output_path),
                ])

            output = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(code, 0)
        self.assertIn(f"wrote scheduler stats: {output_path}", stdout.getvalue())
        self.assertEqual(output["track_count"], len(MANIFEST_ITEMS))


if __name__ == "__main__":
    unittest.main()
