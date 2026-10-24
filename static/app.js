'use strict';
const $ = (id) => document.getElementById(id);
let activeJob = null;
let pollGeneration = 0;
let installPrompt = null;
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function remember(id) {
  activeJob = id;
  try {
    if (id) sessionStorage.setItem('active-job', id);
    else sessionStorage.removeItem('active-job');
  } catch (_) { /* Storage may be disabled; downloading still works. */ }
}

function showStatus(message, {busy = false, error = false} = {}) {
  $('status').hidden = false;
  $('status-text').textContent = message;
  $('status').classList.toggle('error', error);
  $('spinner').hidden = !busy;
}

function setBusy(busy) {
  $('submit').disabled = busy;
  $('paste').disabled = busy;
  $('video-url').disabled = busy;
  $('submit').querySelector('span').textContent = busy ? 'Đang xử lý…' : 'Lấy âm thanh';
  $('download-form').setAttribute('aria-busy', String(busy));
}

async function api(url, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(url, {...options, signal: controller.signal, cache: 'no-store'});
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(data.error || 'Không thực hiện được yêu cầu. Hãy thử lại.');
      error.httpStatus = response.status;
      throw error;
    }
    return data;
  } finally {
    clearTimeout(timer);
  }
}

function showResult(job) {
  $('file-title').textContent = job.title;
  const seconds = Math.round(job.duration);
  const duration = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
  const size = job.size < 1024 * 1024 ? `${Math.round(job.size / 1024)} KB` : `${(job.size / 1024 / 1024).toFixed(1)} MB`;
  $('file-details').textContent = `MP3 · ${duration} · ${size}`;
  // Download path comes from the fixed same-origin API, never from TikTok metadata.
  $('download').href = `/api/jobs/${encodeURIComponent(job.id)}/download`;
  $('download').download = job.filename;
  $('result').hidden = false;
  showStatus('Đã lấy âm thanh. Tệp MP3 sẵn sàng tải.');
}

async function poll(id) {
  const generation = ++pollGeneration;
  const deadline = Date.now() + 10 * 60 * 1000;
  setBusy(true);
  $('reconnect').hidden = true;
  while (Date.now() < deadline && generation === pollGeneration) {
    try {
      const job = await api(`/api/jobs/${encodeURIComponent(id)}`);
      if (generation !== pollGeneration) return;
      if (job.status === 'ready') {
        showResult(job);
        remember(job.id);
        setBusy(false);
        return;
      }
      if (job.status === 'error') {
        showStatus(job.error, {error: true});
        remember(null);
        setBusy(false);
        return;
      }
      showStatus(job.status === 'queued' ? 'Đang chờ đến lượt. Bạn cứ giữ trang này mở.' : 'Đang lấy và chuyển âm thanh sang MP3…', {busy: true});
    } catch (error) {
      if (generation !== pollGeneration) return;
      if (error.httpStatus === 404) {
        remember(null);
        showStatus(error.message, {error: true});
      } else {
        showStatus('Mất kết nối khi kiểm tra. Bạn có thể kiểm tra lại lượt tải đang chạy.', {error: true});
        $('reconnect').hidden = false;
      }
      setBusy(false);
      return;
    }
    await wait(1500);
  }
  if (generation === pollGeneration) {
    showStatus('Lượt tải đang chờ lâu. Bấm kiểm tra lại để xem kết quả.', {error: true});
    $('reconnect').hidden = false;
    setBusy(false);
  }
}

$('download-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const url = $('video-url').value.trim();
  if (!url) return;
  ++pollGeneration;
  $('result').hidden = true;
  $('reconnect').hidden = true;
  setBusy(true);
  showStatus('Đang kiểm tra link video…', {busy: true});
  try {
    const job = await api('/api/jobs', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({url}),
    });
    remember(job.id);
    await poll(job.id);
  } catch (error) {
    showStatus(error.httpStatus ? error.message : 'Chưa kết nối được máy chủ. Hãy kiểm tra mạng và thử lại.', {error: true});
    if (activeJob) $('reconnect').hidden = false;
    setBusy(false);
  }
});

$('paste').addEventListener('click', async () => {
  try {
    const text = await navigator.clipboard.readText();
    if (!text) throw new Error('empty');
    $('video-url').value = text.slice(0, 4096);
    $('video-url').focus();
    $('status').hidden = true;
  } catch (_) {
    $('video-url').focus();
    showStatus('Nhấn giữ ô link rồi chọn Dán, hoặc bấm Ctrl+V trên máy tính.');
  }
});

$('reconnect').addEventListener('click', () => { if (activeJob) poll(activeJob); });
window.addEventListener('beforeinstallprompt', (event) => {
  event.preventDefault();
  installPrompt = event;
  $('install').hidden = false;
});
$('install').addEventListener('click', async () => {
  if (!installPrompt) return;
  await installPrompt.prompt();
  await installPrompt.userChoice;
  installPrompt = null;
  $('install').hidden = true;
});
window.addEventListener('appinstalled', () => { $('install').hidden = true; installPrompt = null; });
window.addEventListener('offline', () => showStatus('Đang mất mạng. Kết nối lại để tải âm thanh.', {error: true}));

if ('serviceWorker' in navigator && window.isSecureContext) {
  navigator.serviceWorker.register('/sw.js').catch(() => {
    // The main downloader works even when PWA registration is unavailable.
  });
}
try {
  const saved = sessionStorage.getItem('active-job');
  if (saved && /^[A-Za-z0-9_-]{32}$/.test(saved)) {
    remember(saved);
    showStatus('Đang kiểm tra lại lượt tải…', {busy: true});
    poll(saved);
  }
} catch (_) { /* No persistent storage is required. */ }

if (!window.isSecureContext) {
  $('connection-note').textContent = 'Bạn đang mở qua HTTP. Tải MP3 vẫn dùng được; cần HTTPS để cài ứng dụng đầy đủ trên Android.';
}
