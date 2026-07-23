# Harmonia 2.0 Roadmap

Harmonia 1.0 is the stable baseline: public AAC/Opus streams, local FLAC library, generated `Track XXX` metadata, persistent play history, fairer Liquidsoap shuffle, and a mobile web player with debug diagnostics.

Harmonia 2.0 should turn the radio into a programmable and observable station without replacing the streaming stack that already works.

## Product Goal

Harmonia 2.0 lets the operator understand what played, influence what plays next, and prevent boring repetition while keeping the self-hosted stream stable.

## Non-Goals

- Do not replace Icecast/Liquidsoap unless the scheduler integration proves impossible.
- Do not implement the AI DJ as part of the first 2.0 milestone.
- Do not add cloud-only dependencies.
- Do not make the public player depend on experimental scheduler APIs to keep streaming.
- Do not optimize for multi-user radio operations yet.

## V2.0 Scope

### 1. Scheduler Foundation

Build a small scheduler layer that can decide what should play next.

Required capabilities:

- Track cycle state: which tracks have played in the current round.
- No-repeat behavior until the current cycle is exhausted.
- Track cooldown after play.
- Optional artist cooldown when metadata is reliable.
- Manual boost and ban primitives.
- Explanation logging: why a track was selected or skipped.
- Safe fallback to the v1.0 playlist behavior.

### 2. Playback State and Stats

Use the existing generated manifest and played history as the initial data source.

Required views:

- Current cycle progress.
- Recently played tracks.
- Most played tracks.
- Most played artists.
- Tracks not yet played in the current cycle.
- Repetition/cooldown violations.

### 3. Internal API

Expose a minimal local API for scheduler state and operator controls.

Candidate endpoints:

- `GET /health`
- `GET /tracks`
- `GET /history`
- `GET /stats`
- `GET /queue`
- `POST /tracks/:id/boost`
- `POST /tracks/:id/ban`
- `POST /scheduler/rebuild`

Authentication can stay local-only for the first implementation. Public exposure is out of scope until the API is stable.

### 4. Dashboard

Add a small operator dashboard after the scheduler API exists.

Initial dashboard sections:

- Now playing.
- Recent plays.
- Cycle progress.
- Top tracks/artists.
- Pending tracks in current cycle.
- Basic boost/ban actions.

## Deferred V2.x Ideas

### AI DJ Inserts

Future work can reuse `https://github.com/Amplustomp/npc-ia-agent` for text-to-MP3 dialogue generation. The useful pieces are the working TTS dialogue flow, dual-LLM integration, and prior voice study.

V2.0 should only prepare insertion points:

- A folder or queue for generated MP3 capsules.
- Scheduler support for short interstitial items.
- Metadata labels for DJ inserts.
- Rules like "insert every N tracks" or "insert before a boosted track".

Actual AI dialogue generation belongs in V2.1 or later.

### Smarter Programming

Later milestones can add:

- Time-of-day blocks.
- Mood/genre blocks.
- Requests like "play more Ado" or "avoid repeats from this artist".
- Weighted recommendations.
- Voice announcements based on play history.

## Architecture Direction

Keep Icecast and Liquidsoap as the streaming layer.

Add a separate service, tentatively named `harmonia-scheduler`, responsible for:

- Reading `data/library/manifest.json`.
- Reading and appending scheduler state.
- Inspecting `data/played-history.jsonl`.
- Producing the next playable item or a generated queue.
- Exposing the internal scheduler API.

Candidate integration strategies with Liquidsoap:

1. Generate a managed playlist file and let Liquidsoap consume it.
2. Use a Liquidsoap dynamic request source that asks the scheduler for the next track.
3. Generate a queue file and trigger controlled reloads only at safe boundaries.

Chosen path for the safe runtime slice: generate a managed playlist file at `data/scheduler/radio.m3u` (container path `/state/scheduler/radio.m3u`) and let Liquidsoap consume it in normal order. Liquidsoap keeps `/tmp/radio.m3u` as the v1 fallback and uses it whenever the managed playlist is missing or empty.

## Milestones

### Milestone 1: Technical Spike

- Verify Liquidsoap dynamic queue/request options.
- Decide the scheduler integration strategy.
- Document failure modes and fallback behavior.
- Produce a small simulation using the current 128-track manifest.

Read-only scheduler spike commands:

```bash
uv run harmonia-scheduler reset --seed local-spike
uv run harmonia-scheduler next
uv run harmonia-scheduler simulate --count 128 --seed local-spike
uv run harmonia-scheduler playlist --output data/scheduler/radio.m3u
uv run python -m unittest discover -s tests
```

The scheduler reads `data/library/manifest.json`, writes only `data/scheduler/state.json` and generated playlist files under `data/scheduler/`, and prints Liquidsoap-compatible annotated URI lines without touching source music, Caddy, the web player, or `data/played-history.jsonl`. Without `--output`, `playlist` is a dry run and does not update scheduler state; with `--output`, it advances and saves state after writing the playlist. When `--count` is omitted, `playlist` emits one full manifest cycle.

Exit criteria:

- Generated-playlist integration selected and documented.
- A working local prototype or proof that the path is not viable.
- No changes to production streaming behavior.

### Milestone 2: Scheduler MVP

- Implement cycle state and no-repeat selection.
- Persist scheduler state.
- Add boost/ban primitives.
- Add selection explanation logs.
- Run simulation tests against the current manifest.

Exit criteria:

- No track repeats before cycle exhaustion in simulation.
- Cooldown behavior is deterministic and testable.
- Fallback to v1.0 behavior is documented: remove or empty `data/scheduler/radio.m3u` and restart Liquidsoap to use `/tmp/radio.m3u`.

### Milestone 3: Runtime Integration

- Connect the scheduler to Liquidsoap using the chosen strategy.
- Run side-by-side or dry-run mode first.
- Promote to active mode after validation.

Exit criteria:

- Multiple hours of playback without unexpected repeats.
- Stream remains stable through scheduler decisions.
- Manual rollback path works.

### Milestone 4: Operator Dashboard

- Add local dashboard for stats and controls.
- Show cycle progress, history, top tracks, and pending tracks.
- Add simple boost/ban UI.

Exit criteria:

- Operator can understand and influence playback without editing files manually.

### Milestone 5: AI DJ Prep

- Define MP3 insert format.
- Define scheduler rules for interstitial inserts.
- Document integration plan with `npc-ia-agent`.

Exit criteria:

- Harmonia can schedule non-music audio items without generating them yet.

## Open Decisions

- Scheduler language and runtime: Python/FastAPI, Node, or another small service.
- Persistence format: JSON files, SQLite, or something else.
- Whether the public web player should show dashboard-like stats or keep them operator-only.
- Whether boost/ban should affect the current cycle immediately or only future cycles.
- How strict artist cooldown should be when artist metadata is inconsistent.

## Recommended First Task

Start with a read-only technical spike:

1. Research Liquidsoap dynamic request/playlist patterns.
2. Prototype scheduler selection in isolation using `data/library/manifest.json`.
3. Simulate at least one full 128-track cycle.
4. Choose the runtime integration strategy.

Do this before editing the live streaming path. The v1.0 stream works; do not poke the goblin with a fork unless the fork has tests.
