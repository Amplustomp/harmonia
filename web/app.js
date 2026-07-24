const player = document.querySelector('#player');
const playButton = document.querySelector('#playButton');
const statusText = document.querySelector('#status');
const nowPlayingTitle = document.querySelector('#nowPlayingTitle');
const sticker = document.querySelector('#sticker');
const shuffleSticker = document.querySelector('#shuffleSticker');
const volumeSlider = document.querySelector('#volumeSlider');
const volumeValue = document.querySelector('#volumeValue');
const playerPanel = document.querySelector('.player-panel');

const currentStream = '/aac';
const debugMode = new URLSearchParams(location.search).get('debug') === '1';
const debugLogLimit = 16;
const debugEntries = [];
const fallbackSticker = '/fastfetch/lain.jpg';
let userWantsPlayback = false;
let reconnectTimer;
let debugState;
let debugList;

const audioErrorMessages = {
  1: 'MEDIA_ERR_ABORTED',
  2: 'MEDIA_ERR_NETWORK',
  3: 'MEDIA_ERR_DECODE',
  4: 'MEDIA_ERR_SRC_NOT_SUPPORTED',
};

function formatAudioTime(value) {
  if (!Number.isFinite(value)) return '0.0';
  return value.toFixed(1);
}

function getAudioSnapshot(eventName, detail = '') {
  const error = player.error;

  return {
    eventName,
    detail,
    timestamp: new Date().toLocaleTimeString('es-CL', { hour12: false }),
    networkState: player.networkState,
    readyState: player.readyState,
    paused: player.paused,
    currentTime: formatAudioTime(player.currentTime),
    errorCode: error ? error.code : '',
    errorMessage: error ? error.message || audioErrorMessages[error.code] || 'Unknown media error' : '',
  };
}

function renderDebugPanel() {
  if (!debugState || !debugList) return;

  const latest = debugEntries[0] || getAudioSnapshot('idle');
  debugState.textContent = `network ${latest.networkState} · ready ${latest.readyState} · paused ${latest.paused} · t ${latest.currentTime}s`;

  debugList.replaceChildren(...debugEntries.map((entry) => {
    const item = document.createElement('li');
    item.className = 'debug-entry';

    const title = document.createElement('div');
    title.className = 'debug-entry-title';

    const name = document.createElement('span');
    name.className = 'debug-entry-name';
    name.textContent = entry.eventName;

    const time = document.createElement('time');
    time.className = 'debug-entry-time';
    time.textContent = entry.timestamp;

    title.append(name, time);

    const metrics = document.createElement('p');
    metrics.className = 'debug-entry-metrics';
    metrics.textContent = `network=${entry.networkState} ready=${entry.readyState} paused=${entry.paused} current=${entry.currentTime}s`;

    item.append(title, metrics);

    if (entry.detail) {
      const detail = document.createElement('p');
      detail.className = 'debug-entry-detail';
      detail.textContent = entry.detail;
      item.append(detail);
    }

    if (entry.errorCode) {
      const error = document.createElement('p');
      error.className = 'debug-entry-error';
      error.textContent = `error ${entry.errorCode}: ${entry.errorMessage}`;
      item.append(error);
    }

    return item;
  }));
}

function logDebugEvent(eventName, detail = '') {
  if (!debugMode) return;

  debugEntries.unshift(getAudioSnapshot(eventName, detail));
  debugEntries.splice(debugLogLimit);
  renderDebugPanel();
}

function setupDebugPanel() {
  if (!debugMode) return;

  const panel = document.createElement('section');
  panel.className = 'debug-panel';
  panel.setAttribute('aria-label', 'Diagnóstico del reproductor');

  const header = document.createElement('div');
  header.className = 'debug-header';

  const title = document.createElement('p');
  title.className = 'debug-title';
  title.textContent = 'Audio debug';

  debugState = document.createElement('p');
  debugState.className = 'debug-state';

  header.append(title, debugState);

  debugList = document.createElement('ol');
  debugList.className = 'debug-list';

  panel.append(header, debugList);
  playerPanel.append(panel);
  logDebugEvent('debug-enabled');
}

async function setRandomSticker() {
  try {
    const response = await fetch('/image-manifest.json', { cache: 'no-cache' });
    if (!response.ok) throw new Error(`Image manifest HTTP ${response.status}`);
    const images = await response.json();
    if (!Array.isArray(images) || images.length === 0) throw new Error('Image manifest is empty or invalid');

    const image = images[Math.floor(Math.random() * images.length)];
    if (typeof image !== 'string' || image.trim() === '') throw new Error('Image manifest selected an invalid filename');

    sticker.src = `/fastfetch/${encodeURIComponent(image)}`;
  } catch (error) {
    sticker.src = fallbackSticker;
    console.warn('Image manifest unavailable; using fallback sticker.', error);
  }
}

function formatVolume(value) {
  return `${Math.round(Number(value) * 100)}%`;
}

function setPlayerVolume(value) {
  player.volume = Number(value);
  volumeValue.textContent = formatVolume(value);
  volumeSlider.setAttribute('aria-valuetext', formatVolume(value));
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
  } catch (error) {
    nowPlayingTitle.textContent = 'Esperando metadata del stream...';
    console.warn('Now-playing metadata unavailable.', error);
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
    } catch (error) {
      console.warn('Audio playback could not start.', error);
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

function scheduleReconnect(reason = 'audio event') {
  if (!userWantsPlayback) {
    logDebugEvent('reconnect skipped', `${reason}; userWantsPlayback=false`);
    return;
  }

  clearTimeout(reconnectTimer);
  setStatus('Reconectando stream...');
  logDebugEvent('reconnect scheduled', `${reason}; retry in 3000ms`);

  reconnectTimer = setTimeout(async () => {
    try {
      logDebugEvent('reconnect attempt', 'refreshing stream URL');
      player.src = `${currentStream}?t=${Date.now()}`;
      await player.play();
      setStatus('Transmitiendo Harmonia');
      logDebugEvent('reconnect success');
    } catch (error) {
      logDebugEvent('reconnect failure', error.message || 'play() rejected');
      scheduleReconnect('reconnect failure');
    }
  }, 3000);
}

playButton.addEventListener('click', togglePlayback);
shuffleSticker.addEventListener('click', setRandomSticker);
volumeSlider.addEventListener('input', () => setPlayerVolume(volumeSlider.value));

if (debugMode) {
  ['loadstart', 'play', 'pause', 'waiting', 'stalled', 'error', 'ended', 'playing', 'canplay', 'canplaythrough', 'suspend', 'abort', 'emptied'].forEach((eventName) => {
    player.addEventListener(eventName, () => logDebugEvent(eventName));
  });
}

player.addEventListener('waiting', () => setStatus('Buffering... la radio está juntando ki'));
player.addEventListener('error', () => scheduleReconnect('audio error'));
player.addEventListener('ended', () => scheduleReconnect('audio ended'));
player.addEventListener('stalled', () => setStatus('Buffering... la radio está juntando ki'));
player.addEventListener('pause', () => { playButton.classList.remove('is-playing'); });
player.addEventListener('playing', () => {
  clearTimeout(reconnectTimer);
  playButton.classList.add('is-playing');
  setStatus('Transmitiendo Harmonia');
});

setupDebugPanel();
setPlayerVolume(volumeSlider.value);
updateNowPlaying();
setRandomSticker();
setInterval(updateNowPlaying, 15000);
