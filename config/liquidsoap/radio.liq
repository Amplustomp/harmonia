#!/usr/bin/liquidsoap

source_password = environment.get("ICECAST_SOURCE_PASSWORD")

music = playlist(
  id="harmonia-flac-playlist",
  mode="randomize",
  reload=600,
  "/tmp/radio.m3u"
)

radio = mksafe(music)

def write_metadata(m) =
  file.write(data=metadata.json.stringify(metadata.cover.remove(m)), "/state/now-playing.json")
end

radio.on_metadata(synchronous=true, write_metadata)

output.icecast(
  %opus(bitrate=192, application="audio"),
  host="icecast",
  port=8000,
  password=source_password,
  mount="opus",
  name="Harmonia",
  description="Admethius local self-hosted radio",
  genre="music",
  url="https://radio.admethius.quest/opus",
  public=false,
  radio
)

output.icecast(
  %fdkaac(bitrate=192, transmux="adts"),
  host="icecast",
  port=8000,
  password=source_password,
  mount="aac",
  name="Harmonia AAC",
  description="Admethius local self-hosted radio - mobile/browser AAC stream",
  genre="music",
  url="https://radio.admethius.quest/aac",
  public=false,
  radio
)

output.icecast(
  %ogg(%flac(compression=5)),
  host="icecast",
  port=8000,
  password=source_password,
  mount="flac",
  name="Harmonia FLAC",
  description="Admethius local self-hosted radio - hi-fi FLAC stream",
  genre="music",
  url="https://radio.admethius.quest/flac",
  public=false,
  radio
)
