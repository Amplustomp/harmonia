# Harmonia

Cozy self-hosted web radio for a small homelab: Liquidsoap builds the stream, Icecast serves it, Caddy publishes a tiny web player, and the browser gets the boring-compatible AAC endpoint by default.

Harmonia is intentionally simple: point it at a folder of FLAC files, start Docker Compose, and you get a private radio station with a soft little web UI.

## What it does

- streams a local FLAC library through Icecast
- serves a minimal web player backed by AAC for broad browser/mobile compatibility
- keeps optional higher-quality stream mounts available for player apps such as VLC
- writes a small `now-playing.json` file for widgets or other personal sites
- serves a random visual/mascot from a local image folder
- keeps music files mounted read-only, because mutating the library would be goblin crime

## Stack

```text
Liquidsoap -> Icecast -> Caddy -> browser / player apps
```

Services:

- `liquidsoap`: reads local FLAC files and pushes stream mounts to Icecast
- `icecast`: serves the audio streams
- `caddy`: serves the static web player and proxies stream routes

The Liquidsoap service builds a small local image (`harmonia-liquidsoap:local`) so the Python scheduler can run inside the same container before Liquidsoap starts.

## Public player behavior

The web UI is deliberately normal-person friendly:

```text
/      -> static web player
/aac   -> default browser/mobile stream
```

The page does not advertise advanced stream URLs. If you enable additional mounts, keep them for your own player apps, LAN usage, or trusted listeners. Bandwidth is not a charity event unless you choose violence.

## Optional technical mounts

The default Liquidsoap config also defines:

```text
/opus  -> efficient high-quality stream for compatible clients
/flac  -> lossless stream for VLC / desktop players / LAN goblins
```

These are useful for personal listening, but the public web player only embeds `/aac`.

## Now playing metadata

Liquidsoap writes the current track metadata to:

```text
data/now-playing.json
```

Caddy can expose it as:

```text
/now-playing.json
```

The metadata writer removes embedded cover art before writing JSON, so the endpoint stays small instead of becoming a cursed base64 brick.

## Requirements

- Docker or Podman with Compose support
- a local folder containing `.flac` files
- optional: a folder of images for the random visual/mascot

## Quick start

Clone the repo and create your environment file:

```bash
cp .env.example .env
```

Edit `.env` and set at least:

```env
ICECAST_SOURCE_PASSWORD=change-this
ICECAST_RELAY_PASSWORD=change-this-too
ICECAST_ADMIN_PASSWORD=change-this-also
MUSIC_DIR=/path/to/your/music
```

Start everything:

```bash
docker compose up -d
```

Check services:

```bash
docker compose ps
docker compose logs -f caddy liquidsoap icecast
```

Stop everything:

```bash
docker compose down
```

## Music source

By default, `.env.example` points to:

```text
/mnt/ssd-data/Music/mp3
```

Yes, that directory name says `mp3` while the project reads FLAC files. Infrastructure is archaeology with a startup hoodie.

On container start, Liquidsoap generates a temporary v1 playlist from all `*.flac` files under `MUSIC_DIR`, then the scheduler writes a managed playlist:

```text
data/scheduler/radio.m3u
```

Liquidsoap uses that managed playlist in normal order. If scheduler generation fails or the managed playlist is missing/empty, Liquidsoap falls back to the temporary v1 playlist at `/tmp/radio.m3u`.

Scheduler state lives in:

```text
data/scheduler/state.json
```

That state tracks generated playlist position, not confirmed playback. The authoritative record of what actually played remains `data/played-history.jsonl`.

To pick up newly added albums:

```bash
docker compose restart liquidsoap
```

## Web player assets

The web player lives in:

```text
web/
```

It uses `web/image-manifest.json` to choose a random image from the mounted visual folder. Regenerate the manifest after adding or removing images:

```bash
python - <<'PY'
import json
from pathlib import Path

src = Path('/path/to/your/images')
allowed = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
images = sorted(p.name for p in src.iterdir() if p.is_file() and p.suffix.lower() in allowed)
Path('web/image-manifest.json').write_text(json.dumps(images, ensure_ascii=False, indent=2) + '\n')
print(len(images), 'images')
PY
```

Update the image mount in `docker-compose.yml` if your folder is somewhere else.

## Publishing behind a tunnel or reverse proxy

This repo binds the public player frontend to localhost by default:

```text
127.0.0.1:8090
```

That makes it easy to publish through Cloudflare Tunnel, another Caddy instance, Nginx, Traefik, or whatever reverse-proxy beast you already feed.

Example route:

```text
radio.example.com -> http://localhost:8090
```

## Private library UI through Cloudflare Access

The library UI is prepared for `library.admethius.quest` behind Cloudflare Tunnel and Cloudflare Access. The intended public route is:

```text
library.admethius.quest -> http://caddy:8091
```

`8091` is the private library surface. Caddy still allows direct requests from localhost, private LAN ranges, Docker bridge networks, and Tailscale CGNAT (`100.64.0.0/10`). Everyone else gets a boring `403`, as they should.

Docker port publishing cannot express "LAN-only" generically across hosts. For that reason the default is deliberately local-only:

```env
LIBRARY_BIND=127.0.0.1
LIBRARY_PORT=8091
```

If you want direct LAN access, opt in on a trusted LAN/firewall:

```env
LIBRARY_BIND=0.0.0.0
```

Cloudflare Access remains the internet-facing gate. Do not add custom JWT code here; Access already does that job, and duplicating it would be premium-grade yak shaving.

Tomorrow's Cloudflare setup:

1. Use the dedicated `harmonia-library` tunnel.
2. Keep its credentials JSON outside git and point `.env` at it with `CLOUDFLARED_CREDENTIALS_FILE=...`.
3. Route `library.admethius.quest` to the `harmonia-library` tunnel.
4. Create a Cloudflare Access self-hosted app for `library.admethius.quest`.
5. Add an Access policy that only allows the explicit trusted email addresses Sergio chooses.
6. Do not configure JWT custom validation in Harmonia.

Start or restart the stack after adding the token:

```bash
docker compose --profile tunnel up -d
docker compose logs -f cloudflared caddy
```

Verify the local and tunnel paths:

```bash
curl -I http://127.0.0.1:8091/
docker compose ps cloudflared
```

Without the `tunnel` profile, `cloudflared` stays off and the regular radio stack keeps starting normally.

Then open `https://library.admethius.quest` from outside the LAN and confirm Cloudflare Access asks for an allowed email before showing the library UI. Also confirm a non-allowed email is rejected, because otherwise the gate is cosplay.

## Repository hygiene

Runtime state and secrets are intentionally ignored:

```text
.env
data/
```

Do not commit real passwords, generated metadata, logs, cache files, or playlist state. Public repos remember sins better than family.

## License

MIT. See [`LICENSE`](LICENSE).
