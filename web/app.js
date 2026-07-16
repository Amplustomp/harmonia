const player = document.querySelector('#player');
const playButton = document.querySelector('#playButton');
const statusText = document.querySelector('#status');
const nowPlayingTitle = document.querySelector('#nowPlayingTitle');
const mascot = document.querySelector('#mascot');
const shuffleMascot = document.querySelector('#shuffleMascot');

const currentStream = '/aac';
let userWantsPlayback = false;
let reconnectTimer;

async function setRandomMascot() {
  try {
    const response = await fetch('/image-manifest.json', { cache: 'no-cache' });
    const images = await response.json();
    const image = images[Math.floor(Math.random() * images.length)];
    mascot.src = `/fastfetch/${encodeURIComponent(image)}`;
  } catch {
    mascot.src = '/fastfetch/lain.jpg';
  }
}

function setStatus(text) {
  statusText.textContent = text;
}

function cleanTrackName(value) {
  if (!value) return '';
  const withoutPath = String(value).split('/').pop();
  return decodeURIComponent(withoutPath).replace(/\.[a-z0-9]+$/i, '').replaceAll('_', ' ');
}

function formatMetadata(metadata) {
  const artist = metadata.artist || metadata.album_artist || metadata.albumartist || '';
  const title = metadata.title || cleanTrackName(metadata.filename || metadata.initial_uri || metadata.source || '');

  if (artist && title) return `${artist} — ${title}`;
  if (title) return title;
  return 'Harmonia está sonando, pero el track vino sin carnet.';
}

async function updateNowPlaying() {
  try {
    const response = await fetch('/now-playing.json', { cache: 'no-store' });
    if (!response.ok) throw new Error('metadata not ready');
    const metadata = await response.json();
    nowPlayingTitle.textContent = formatMetadata(metadata);
  } catch {
    nowPlayingTitle.textContent = 'Esperando metadata del stream...';
  }
}

async function togglePlayback() {
  if (player.paused) {
    if (!player.src) player.src = currentStream;
    userWantsPlayback = true;
    try {
      await player.play();
      playButton.classList.add('is-playing');
      setStatus('Transmitiendo Harmonia');
    } catch {
      setStatus('No pude iniciar el audio. Prueba AAC u Opus.');
    }
  } else {
    userWantsPlayback = false;
    clearTimeout(reconnectTimer);
    player.pause();
    playButton.classList.remove('is-playing');
    setStatus('Pausada');
  }
}

function scheduleReconnect() {
  if (!userWantsPlayback) return;
  clearTimeout(reconnectTimer);
  setStatus('Reconectando stream...');
  reconnectTimer = setTimeout(async () => {
    try {
      player.src = `${currentStream}?t=${Date.now()}`;
      await player.play();
      setStatus('Transmitiendo Harmonia');
    } catch {
      scheduleReconnect();
    }
  }, 3000);
}

playButton.addEventListener('click', togglePlayback);
shuffleMascot.addEventListener('click', setRandomMascot);

player.addEventListener('waiting', () => setStatus('Buffering... la radio está juntando ki'));
player.addEventListener('error', scheduleReconnect);
player.addEventListener('stalled', scheduleReconnect);
player.addEventListener('pause', () => { playButton.classList.remove('is-playing'); });
player.addEventListener('playing', () => { playButton.classList.add('is-playing'); });

setRandomMascot();
updateNowPlaying();
setInterval(updateNowPlaying, 15000);
