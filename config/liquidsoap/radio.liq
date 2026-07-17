#!/usr/bin/liquidsoap

source_password = environment.get("ICECAST_SOURCE_PASSWORD")

music = playlist(
  id="harmonia-flac-playlist",
  mode="randomize",
  "/tmp/radio.m3u"
)

radio = mksafe(music)

def add_unique(acc, item) =
  item = string.trim(item)
  if item == "" or list.mem(item, acc) then
    acc
  else
    list.append(acc, [item])
  end
end

def dedupe_csv(value) =
  parts = string.split(separator=",", value)
  unique = list.fold(add_unique, [], parts)
  string.concat(separator=", ", unique)
end

def clean_metadata(m) =
  artist = m["artist"]
  if artist == "" then
    []
  else
    [("artist", dedupe_csv(artist))]
  end
end

radio = metadata.map(clean_metadata, radio)

def write_metadata(m) =
  clean = metadata.cover.remove(m)
  file.write(data=metadata.json.stringify(clean), "/state/now-playing.json")

  entry = {
    played_at = time.string("%Y-%m-%dT%H:%M:%S%z"),
    played_at_epoch = time(),
    artist = m["artist"],
    title = m["title"],
    tracknumber = m["tracknumber"],
    album = m["album"],
    genre = m["genre"]
  }
  file.write(data="#{json.stringify(compact=true, entry)}\n", append=true, "/state/played-history.jsonl")
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
