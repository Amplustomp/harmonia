const player = document.querySelector('#player');
const playButton = document.querySelector('#playButton');
const statusText = document.querySelector('#status');
const sticker = document.querySelector('#sticker');
const shuffleSticker = document.querySelector('#shuffleSticker');
const volumeSlider = document.querySelector('#volumeSlider');
const volumeValue = document.querySelector('#volumeValue');
const volumeControl = document.querySelector('.volume-control');
const volumeToggle = document.querySelector('#volumeToggle');
const playerPanel = document.querySelector('.player-panel');
const radioInfoCurrent = document.querySelector('#radioInfoCurrent');
const radioInfoCurrentMeta = document.querySelector('#radioInfoCurrentMeta');
const radioInfoPrevious = document.querySelector('#radioInfoPrevious');
const radioInfoPreviousMeta = document.querySelector('#radioInfoPreviousMeta');
const radioInfoUpcoming = document.querySelector('#radioInfoUpcoming');
const radioInfoUpcomingMeta = document.querySelector('#radioInfoUpcomingMeta');
const listenerCount = document.querySelector('#listenerCount');
const listenerLabel = document.querySelector('#listenerLabel');

const currentStream = '/aac';
const debugMode = new URLSearchParams(location.search).get('debug') === '1';
const debugLogLimit = 16;
const debugEntries = [];
const fallbackSticker = '/fastfetch/lain.jpg';
let userWantsPlayback = false;
let reconnectTimer;
let debugState;
let debugList;
let liveCurrentTrack = null;
let hasLiveCurrentTrack = false;
let volumePanelPinned = false;
let volumePanelSuppressFocus = false;

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

function isVolumePanelVisible() {
  return volumePanelPinned || (volumeControl.matches(':focus-within') && !volumeControl.classList.contains('is-dismissed'));
}

function syncVolumePanelState() {
  const isVisible = isVolumePanelVisible();
  volumeToggle.setAttribute('aria-expanded', String(isVisible));
  volumeToggle.setAttribute('aria-label', isVisible ? 'Cerrar control de volumen' : 'Abrir control de volumen');
}

function setVolumePanelPinned(isPinned) {
  volumePanelPinned = isPinned;
  volumeControl.classList.toggle('is-open', volumePanelPinned);
  if (volumePanelPinned) volumeControl.classList.remove('is-dismissed');
  syncVolumePanelState();
}

function setStatus(text) {
  statusText.textContent = text;
}

function cleanPublicValue(value) {
  if (value === null || value === undefined) return '';
  return String(value).trim();
}

function normalizePublicTrack(track) {
  if (!track || typeof track !== 'object') return null;

  const normalized = {
    track: cleanPublicValue(track.track || track.tracknumber || track.radio_track),
    title: cleanPublicValue(track.title),
    displayTitle: cleanPublicValue(track.displayTitle || track.display_title),
    artist: cleanPublicValue(track.artist),
    album: cleanPublicValue(track.album),
  };

  return Object.values(normalized).some(Boolean) ? normalized : null;
}

function getTrackKey(track) {
  const normalized = normalizePublicTrack(track);
  if (!normalized) return '';
  if (normalized.track) return `track:${normalized.track}`;

  return [normalized.displayTitle, normalized.title, normalized.artist, normalized.album]
    .filter(Boolean)
    .join('|')
    .toLocaleLowerCase('es-CL');
}

function formatPublicTrack(track) {
  const normalized = normalizePublicTrack(track);
  if (!normalized) return '';
  return normalized.displayTitle || normalized.title || (normalized.track ? `Track ${normalized.track}` : 'Sin metadata pública');
}

function formatPublicMeta(track) {
  const normalized = normalizePublicTrack(track);
  if (!normalized) return '';
  const details = [normalized.artist, normalized.album].filter(Boolean);
  return details.length ? details.join(' · ') : 'Harmonia está transmitiendo sin ficha completa';
}

function renderCurrentTrack(track) {
  radioInfoCurrent.textContent = formatPublicTrack(track) || 'Esperando señal pública...';
  radioInfoCurrentMeta.textContent = formatPublicMeta(track) || 'Metadata pública en camino';
}

function renderPreviousTrack(track) {
  radioInfoPrevious.textContent = formatPublicTrack(track) || 'Sin historial público aún';
  radioInfoPreviousMeta.textContent = track ? formatPublicMeta(track) : 'Esperando historial público';
}

function renderUpcomingTrack(track) {
  radioInfoUpcoming.textContent = formatPublicTrack(track) || 'Candidato por calcular';
  radioInfoUpcomingMeta.textContent = track ? formatPublicMeta(track) : 'No es promesa, es candidato';
}

function renderListenerCount(listeners) {
  const count = Number(listeners && listeners.current);
  if (!Number.isInteger(count) || count < 0) {
    listenerCount.textContent = '?';
    listenerLabel.textContent = 'oyentes';
    return;
  }

  listenerCount.textContent = String(count);
  listenerLabel.textContent = count === 1 ? 'oyente' : 'oyentes';
}

function seedRadioInfo(info) {
  const current = normalizePublicTrack(info && info.current);
  const previous = normalizePublicTrack(info && info.previous);
  const upcoming = normalizePublicTrack(info && info.upcoming);
  renderListenerCount(info && info.listeners);

  if (previous) {
    renderPreviousTrack(previous);
  }

  if (upcoming) {
    renderUpcomingTrack(upcoming);
  }

  if (current && !hasLiveCurrentTrack) {
    renderCurrentTrack(current);
  }
}

async function updateRadioInfo() {
  try {
    const response = await fetch('/radio-info.json', { cache: 'no-store' });
    if (!response.ok) throw new Error(`radio info HTTP ${response.status}`);
    seedRadioInfo(await response.json());
  } catch (error) {
    console.warn('Public radio info unavailable.', error);
  }
}

async function updateNowPlaying() {
  try {
    const response = await fetch('/now-playing.json', { cache: 'no-store' });
    if (!response.ok) throw new Error(`now playing HTTP ${response.status}`);

    const nextCurrentTrack = normalizePublicTrack(await response.json());
    if (!nextCurrentTrack) return;

    if (hasLiveCurrentTrack && getTrackKey(nextCurrentTrack) !== getTrackKey(liveCurrentTrack)) {
      renderPreviousTrack(liveCurrentTrack);
    }

    liveCurrentTrack = nextCurrentTrack;
    hasLiveCurrentTrack = true;
    renderCurrentTrack(liveCurrentTrack);
  } catch (error) {
    console.warn('Live now-playing metadata unavailable.', error);
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
volumeToggle.addEventListener('click', () => {
  if (volumePanelPinned) {
    volumeControl.classList.add('is-dismissed');
    setVolumePanelPinned(false);
    return;
  }

  setVolumePanelPinned(true);
});

volumeControl.addEventListener('focusin', () => {
  if (!volumePanelSuppressFocus) volumeControl.classList.remove('is-dismissed');
  syncVolumePanelState();
});

volumeControl.addEventListener('focusout', () => {
  setTimeout(() => {
    if (!volumeControl.matches(':focus-within')) volumeControl.classList.remove('is-dismissed');
    syncVolumePanelState();
  });
});

volumeSlider.addEventListener('input', () => setPlayerVolume(volumeSlider.value));

document.addEventListener('click', (event) => {
  if (volumeControl.contains(event.target)) return;
  setVolumePanelPinned(false);
  volumeControl.classList.remove('is-dismissed');
});

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape' || !isVolumePanelVisible()) return;
  volumePanelSuppressFocus = true;
  volumeControl.classList.add('is-dismissed');
  setVolumePanelPinned(false);
  volumeToggle.focus();
  setTimeout(() => { volumePanelSuppressFocus = false; });
});

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
updateRadioInfo();
updateNowPlaying();
setRandomSticker();
setInterval(updateNowPlaying, 15000);
setInterval(updateRadioInfo, 15000);
