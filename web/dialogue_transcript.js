// Shared, local-only transcript controls. No inference or graph changes here.
const requests = new Map();
const element = (tag, props = {}, text = '') => Object.assign(document.createElement(tag), props, {textContent: text});
export const wordsInRange = (words, range) => words.filter(w => w.end > range[0] + .001 && w.start < range[1] - .001);

export async function transcriptWords(fetchApi, source, identity) {
  const key = JSON.stringify([source, identity]);
  if (!requests.has(key)) {
    const request = (async () => {
      const response = await fetchApi('/zura/audio-dialogue/transcribe', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({source})});
      const data = await response.json();
      if (!response.ok) throw Error(data.error || 'Parakeet could not transcribe this clip.');
      if (!Array.isArray(data.words) || !data.words.length) throw Error('No speech recognised. You can still use the waveform and type the phrase.');
      return data.words;
    })();
    requests.set(key, request);
    request.catch(() => requests.delete(key));
  }
  return requests.get(key);
}

export function updatePhrase(state, key, original, force = false) {
  state.original = original;
  state.transcriptKey = key;
  if (!original.trim()) return false;
  if (force || !state.edited || !state.sentence.trim()) {
    state.sentence = original;
    state.sourceKey = key;
    state.edited = false;
    return true;
  }
  return false;
}

export function changedTokens(before, after) {
  const a = before.trim().split(/\s+/).filter(Boolean), b = after.trim().split(/\s+/).filter(Boolean);
  // Spoken reference clips are short. Bound the diff for manually pasted scripts.
  if (a.length * b.length > 90000) return b.map(text => ({text, added: true}));
  const table = Array.from({length: a.length + 1}, () => new Uint16Array(b.length + 1));
  for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--)
    table[i][j] = a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
  const result = []; let i = 0, j = 0;
  while (j < b.length) {
    if (i < a.length && a[i] === b[j]) {result.push({text: b[j++], added: false}); i++;}
    else if (i < a.length && table[i + 1][j] >= table[i][j + 1]) i++;
    else result.push({text: b[j++], added: true});
  }
  return result;
}

export function transcriptStyle() {
  const style = element('style');
  style.textContent = `
    .zura-transcript{font:13px/1.5 system-ui;color:#e5edf5;min-width:0}
    .zura-transcript h3{font-size:16px;margin:18px 0 7px}.zura-transcript p{margin:8px 0;color:#b7c8d9;font-size:12px}
    .zura-transcript button{font:inherit;border:1px solid #52677b;background:#263547;color:#edf4fa;border-radius:5px;padding:6px 9px;cursor:pointer}
    .zura-transcript button:hover{background:#33495b}.zura-transcript button:disabled{opacity:.55;cursor:wait}
    .zura-transcript :is(button,textarea):focus-visible{outline:2px solid #a4f0d6;outline-offset:3px}
    .zura-transcript ::selection{background:#4a7569;color:#fff}
    .zura-transcript textarea{width:100%;box-sizing:border-box;padding:12px;font:16px/1.6 system-ui;min-height:130px;resize:vertical;border:1px solid #849eaf;border-radius:6px;background:#101923;color:#f0f5fa;caret-color:#a4f0d6}
    .zura-transcript textarea::placeholder{color:#a1b4c5}
    .zura-transcript label{display:grid;gap:7px;font-weight:600;font-size:14px}
    .zura-word-list{display:flex;align-content:start;flex-wrap:wrap;gap:5px;max-height:145px;overflow:auto;padding:4px 3px 8px;touch-action:pan-y;user-select:none}
    .zura-word-list button{min-height:32px;padding:4px 8px;white-space:normal;overflow-wrap:anywhere}
    .zura-word-list button[aria-pressed=true]{background:#28584d;border-color:#9de8cf;color:#fff}
    .zura-word-list button.is-playing{text-decoration:underline;text-underline-offset:4px}
    .zura-original-line,.zura-change-preview{background:#101923;border:1px solid #3d5264;border-radius:5px;padding:10px;line-height:1.7;overflow-wrap:anywhere;white-space:pre-wrap}
    .zura-transcript mark{background:#335c50;color:#eafff5;padding:1px 2px;border-radius:2px}
    .zura-change-preview mark{background:#614b25;color:#fff0ca}
    .zura-transcript .zura-transcript-status{min-height:20px;color:#b6e8d5}
    .zura-transcript .zura-transcript-error{color:#ffc1b8}
    .zura-transcript .zura-phrase-actions{display:flex;gap:10px;align-items:center;margin:8px 0 14px}
    .zura-transcript .zura-phrase-actions span{font-size:12px;color:#b7c8d9}
  `;
  return style;
}

export function wordSelector(words, getRange, select, seek = () => {}) {
  const root = element('div', {className: 'zura-transcript'}), list = element('div', {className: 'zura-word-list', role: 'group', ariaLabel: 'Recognised words'});
  root.append(element('h3', {}, 'Select words'), element('p', {}, 'Click a word. Drag across words or Shift-click to select a phrase.'), list);
  const buttons = []; let anchor = null, dragging = false;
  function choose(index, extend = false) {
    if (!extend || anchor === null) anchor = index;
    const lo = Math.min(anchor, index), hi = Math.max(anchor, index);
    select([words[lo].start, words[hi].end]); seek(words[lo].start); update();
  }
  for (const [index, word] of words.entries()) {
    const button = element('button', {type: 'button', title: `${word.start.toFixed(3)}–${word.end.toFixed(3)} s`}, word.text);
    button.dataset.wordIndex = index;
    button.onpointerdown = event => {
      if (event.button !== 0) return;
      event.preventDefault(); button.focus(); dragging = true; choose(index, event.shiftKey);
      list.setPointerCapture?.(event.pointerId);
    };
    button.onclick = event => {if (event.detail === 0) choose(index, event.shiftKey);};
    button.onkeydown = event => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault(); const next = Math.max(0, Math.min(words.length - 1, index + (event.key === 'ArrowLeft' ? -1 : 1)));
      buttons[next].focus(); if (event.shiftKey) choose(next, true);
    };
    buttons.push(button); list.append(button);
  }
  list.onpointermove = event => {
    if (!dragging) return;
    const target = document.elementFromPoint(event.clientX, event.clientY)?.closest('[data-word-index]');
    if (target && list.contains(target)) choose(Number(target.dataset.wordIndex), true);
  };
  list.onpointerup = list.onpointercancel = event => {dragging = false; if (list.hasPointerCapture?.(event.pointerId)) list.releasePointerCapture(event.pointerId);};
  const caption = element('p', {className: 'zura-transcript-status', role: 'status'}); root.append(caption);
  function update(time = -1) {
    const range = getRange(), selected = wordsInRange(words, range);
    buttons.forEach((button, i) => {button.setAttribute('aria-pressed', words[i].end > range[0] + .001 && words[i].start < range[1] - .001); button.classList.toggle('is-playing', words[i].start <= time && time < words[i].end);});
    caption.textContent = selected.length ? 'Replacing: “' + selected.map(w => w.text).join(' ') + '”' : 'Drag the waveform handles to select speech.';
  }
  update(); return {element: root, update};
}

export function phraseEditor(state, onChange, title = 'Phrase to speak') {
  const root = element('section', {className: 'zura-transcript'});
  const original = element('div', {className: 'zura-original-line', ariaLabel: 'Original reference phrase'});
  const status = element('p', {className: 'zura-transcript-status', role: 'status'}, 'Choose a clip. Parakeet fills the phrase automatically.');
  const label = element('label', {}, title), input = element('textarea', {value: state.sentence, rows: 5, ariaLabel: title, placeholder: 'The recognised phrase appears here. You can also type the full phrase.'}); label.append(input);
  const reset = element('button', {type: 'button', disabled: true}, 'Use recognised phrase');
  const actions = element('div', {className: 'zura-phrase-actions'}); actions.append(reset, element('span', {}, 'Resets your edits to the original words.'));
  const diff = element('div', {className: 'zura-change-preview', ariaLabel: 'Edited phrase preview'});
  root.append(element('h3', {}, 'Original phrase'), original, status, label, actions, element('h3', {}, 'Your edited phrase'), diff,
    element('p', {}, 'Amber words are your changes. Only the selected section is inserted into the original. Keep the full phrase for natural delivery.'));
  let data = null;
  function paint() {
    diff.replaceChildren();
    for (const token of changedTokens(state.original || '', state.sentence)) diff.append(element(token.added ? 'mark' : 'span', {}, token.text), document.createTextNode(' '));
    if (!state.sentence.trim()) diff.textContent = 'Edit the phrase above to see your changes.';
  }
  input.oninput = () => {state.sentence = input.value; state.edited = true; status.textContent = 'Your edits are saved. Green words above mark the original selection.'; onChange(); paint();};
  reset.onclick = () => {if (!data) return; updatePhrase(state, data.key, data.text, true); input.value = state.sentence; onChange(); paint(); status.textContent = 'Original words restored. Edit any words in the box below.';};
  function update(next) {
    data = next; original.replaceChildren();
    for (const word of next.words) original.append(element(word.end > next.range[0] + .001 && word.start < next.range[1] - .001 ? 'mark' : 'span', {}, word.text), document.createTextNode(' '));
    if (!next.words.length) original.textContent = 'No recognised words inside this reference range. Adjust Reference IN/OUT or type the phrase.';
    reset.disabled = !next.text.trim();
    if (updatePhrase(state, next.key, next.text)) {input.value = state.sentence; onChange();}
    status.textContent = state.sourceKey && state.sourceKey !== next.key && state.edited ? 'Reference changed. Your edit is kept. Use recognised phrase to start from the new reference.' : state.edited ? 'Your edits are saved. Green words above mark the original selection.' : 'Filled by Parakeet. Edit any words below.';
    paint();
  }
  paint(); return {element: root, update, input, status};
}
