/* Zura nodes · source picker for the Zura Load Video node.
 *
 * Adds upload + "Find video options" buttons to the node.  The YouTube search
 * dialog previews candidates and writes the chosen window into the node's
 * video_url / start_seconds / duration_seconds widgets. */
import { app } from '/scripts/app.js';
import { api } from '/scripts/api.js';
import { fetchJsonWithTimeout } from './v2_requests.js';

// Class ID of Zura Load Video; kept from before the Zura rename so graphs saved
// earlier keep resolving.
const NODE_TYPE = 'TrendStudioV2DrivingClip';

function element(tag, text, parent) {
  const el = document.createElement(tag);
  if (text) el.textContent = text;
  if (tag === 'button') Object.assign(el.style, {
    padding: '8px 12px', margin: '4px 4px 4px 0', borderRadius: '6px',
    border: '1px solid #526478', background: '#34465c', color: 'white', cursor: 'pointer',
  });
  parent?.append(el);
  return el;
}

function set(node, name, value) {
  const w = node?.widgets?.find(w => w.name === name);
  if (!w) throw Error(`Missing control ${name}`);
  w.value = value;
  w.callback?.(value);
}

async function chooseVideo(node) {
  const value = (name, fallback) => node.widgets?.find(w => w.name === name)?.value ?? fallback;
  const duration = Number(value('duration_seconds', 10));
  const query = {
    keyword: String(value('search_keyword', '') || 'live dance'),
    hint: String(value('search_hint', '') || 'live dance'),
    minimum_views: Number(value('minimum_views', 10000)),
    youtube_mode: String(value('youtube_mode', 'Any YouTube video')),
    duration,
    source_max_side: Number(value('source_max_side', 1280)),
  };
  const dialog = element('dialog');
  Object.assign(dialog.style, {
    width: 'min(1100px,94vw)', maxHeight: '90vh', padding: '24px',
    border: '1px solid #566', borderRadius: '12px', background: '#171b20', color: '#f1f5f9',
  });
  element('h2', 'Choose a source video', dialog);
  element('p', 'Preview a source before selecting it. View counts indicate popularity, not live trend growth. Selecting fills the URL and clip window on the Driving clip node.', dialog);
  const requestController = new AbortController();
  let closed = false;
  const close = element('button', 'Close', dialog);
  close.onclick = () => dialog.close();
  const status = element('p', 'Finding video options…', dialog);
  const retry = element('button', 'Retry search', dialog);
  retry.hidden = true;
  const grid = element('div', '', dialog);
  Object.assign(grid.style, { display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(260px,1fr))', gap: '18px' });
  document.body.append(dialog);
  dialog.showModal();
  dialog.onclose = () => { closed = true; requestController.abort(); dialog.remove(); };
  const loadCandidates = async () => {
    retry.hidden = true;
    grid.replaceChildren();
    status.textContent = 'Finding video options… 0s elapsed';
    const started = Date.now();
    const elapsedTimer = setInterval(() => {
      if (!closed) status.textContent = `Finding video options… ${Math.floor((Date.now() - started) / 1000)}s elapsed`;
    }, 1000);
    try {        const receipt = await fetchJsonWithTimeout(api.fetchApi.bind(api), '/zura/video_candidates', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(query), signal: requestController.signal,
      }, 90000);
      if (closed) return;
      clearInterval(elapsedTimer);
      status.textContent = `${receipt.candidates.length} options. Nothing will be generated until you choose a video and run the workflow.`;
      for (const candidate of receipt.candidates) {
        const id = new URL(candidate.url).searchParams.get('v');
        if (!/^[A-Za-z0-9_-]{11}$/.test(id || '')) continue;
        const card = element('article', '', grid);
        Object.assign(card.style, { padding: '12px', background: '#252c35', borderRadius: '8px' });
        const image = element('img', '', card);
        image.src = `https://i.ytimg.com/vi/${id}/hqdefault.jpg`;
        image.alt = candidate.title;
        image.style.width = '100%';
        element('h3', candidate.title, card);
        element('p', `${candidate.channel || ''} · ${Number(candidate.view_count).toLocaleString()} views · ${Math.round(candidate.duration)} seconds`, card);
        let preview = null;
        const windowControls = element('div', '', card);
        const startLabel = element('label', 'Start time (seconds) ', windowControls);
        const startInput = element('input', '', startLabel);
        startInput.type = 'number';
        startInput.min = '0';
        startInput.max = String(Math.max(0, candidate.duration - duration));
        startInput.step = '0.1';
        startInput.value = String(value('start_seconds', 0));
        startInput.style.width = '75px';
        const autoLabel = element('label', ' Suggest a section ', windowControls);
        const autoInput = element('input', '', autoLabel);
        autoInput.type = 'checkbox';
        autoInput.checked = true;
        startInput.disabled = autoInput.checked;
        const previewArea = element('div', '', card);
        const invalidate = () => { preview = null; use.disabled = true; use.style.opacity = '.45'; };
        startInput.oninput = invalidate;
        autoInput.onchange = () => { startInput.disabled = autoInput.checked; invalidate(); };
        const watch = element('button', `Preview ${duration}-second clip`, card);
        watch.onclick = async () => {
          watch.disabled = true;
          watch.textContent = 'Preparing preview…';
          try {
            invalidate();
            startInput.disabled = true; autoInput.disabled = true;
            const data = await fetchJsonWithTimeout(api.fetchApi.bind(api), '/zura/preview_video', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                url: candidate.url, start: Number(startInput.value), automatic: autoInput.checked,
                youtube_mode: query.youtube_mode, duration, source_max_side: query.source_max_side,
              }), signal: requestController.signal,
            }, 180000);
            if (closed) return;
            preview = data;
            previewArea.replaceChildren();
            startInput.value = String(data.start);
            const video = element('video', '', previewArea);
            video.src = api.apiURL('/view?' + new URLSearchParams(data));
            video.controls = true;
            video.style.width = '100%';
            video.preload = 'metadata';
            element('p', `Selected window: ${data.start}–${data.start + data.duration} seconds.`, previewArea);
            use.disabled = false; use.style.opacity = '1';
            watch.textContent = 'Update preview';
          } catch (error) {
            if (!closed) { watch.textContent = 'Retry preview'; element('p', String(error), previewArea); }
          } finally {
            watch.disabled = false; autoInput.disabled = false; startInput.disabled = autoInput.checked;
          }
        };
        const link = element('a', 'Open on YouTube', card);
        link.href = candidate.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.style.margin = '0 12px';
        const use = element('button', `Use this ${duration}-second clip`, card);
        use.disabled = true; use.style.opacity = '.45';
        use.onclick = () => {
          if (!preview) return;
          set(node, 'video_url', candidate.url);
          set(node, 'start_seconds', preview.start);
          app.graph.setDirtyCanvas(true, true);
          dialog.close();
        };
      }
    } catch (error) {
      clearInterval(elapsedTimer);
      if (!closed) { status.textContent = `Search failed: ${String(error.message || error)}`; retry.hidden = false; }
    }
  };
  retry.onclick = () => loadCandidates();
  await loadCandidates();
}

/* Core ComfyUI on many builds registers only /upload/image (which accepts any
 * file type and writes it to the input directory); /upload/video exists only on
 * builds with the newer comfy_api video IO type.  Try the dedicated route first,
 * then fall back, and always report the real HTTP status instead of a bare
 * "Upload failed". */
const UPLOAD_ROUTES = [
  { path: '/upload/video', field: 'video' },
  { path: '/upload/image', field: 'image' },
];

async function uploadVideoFile(file) {
  const failures = [];
  for (const route of UPLOAD_ROUTES) {
    const form = new FormData();
    form.append(route.field, file, file.name);
    form.append('type', 'input');
    let response;
    try {
      response = await api.fetchApi(route.path, { method: 'POST', body: form });
    } catch (error) {
      failures.push(`${route.path}: ${error?.message || error}`);
      continue;
    }
    if (response.ok) {
      const result = await response.json();
      if (!result?.name) throw Error(`${route.path} accepted the file but returned no filename`);
      return result;
    }
    const detail = (await response.text().catch(() => '')).slice(0, 200).trim();
    failures.push(`${route.path}: HTTP ${response.status}${detail ? ' — ' + detail : ''}`);
    // 404/405 mean the route does not exist here; anything else is a real error.
    if (response.status !== 404 && response.status !== 405) break;
  }
  throw Error(`Upload failed. ${failures.join(' | ')}`);
}

function addClipChoice(host, name) {
  const widget = host.widgets?.find(w => w.name === 'clip');
  const values = widget?.options?.values;
  if (Array.isArray(values) && !values.includes(name)) values.push(name);
}

function chooseLocalVideo(host, button) {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'video/*';
  input.onchange = async () => {
    const file = input.files?.[0];
    if (!file) return;
    const label = button.label;
    button.disabled = true;
    button.label = `Uploading ${file.name}…`;
    try {
      const result = await uploadVideoFile(file);
      const name = (result.subfolder ? result.subfolder + '/' : '') + result.name;
      addClipChoice(host, name);
      set(host, 'clip', name);
      set(host, 'video_url', '');
      app.graph.setDirtyCanvas(true, true);
    } catch (error) {
      alert(String(error?.message || error));
    } finally {
      button.disabled = false;
      button.label = label;
    }
  };
  input.click();
}

function attach(host) {
  if (host.type !== NODE_TYPE || host.__zuraPickerAttached) return;
  host.__zuraPickerAttached = true;
  if (!host.widgets?.find(w => w.name === 'find_video_options')) {
    const button = host.addWidget('button', 'find_video_options', 'Find video options',
      () => chooseVideo(host).catch(e => alert(String(e))), { serialize: false });
    button.serialize = false;
    button.label = 'Find video options';
  }
  if (!host.widgets?.find(w => w.name === 'Choose local video')) {
    const upload = host.addWidget('button', 'Choose local video', 'Choose local video',
      () => chooseLocalVideo(host, upload), { serialize: false });
    upload.serialize = false;
    upload.label = 'Choose local video';
  }
}

app.registerExtension({
  name: 'Zura.MediaPicker',
  nodeCreated(node) { queueMicrotask(() => attach(node)); },
  loadedGraphNode(node) { queueMicrotask(() => attach(node)); },
  afterConfigureGraph() { for (const node of app.graph.nodes) attach(node); },
});
