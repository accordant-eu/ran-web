/* ran-web frontend — app.js
 * Extracted from index.html to enable strict script-src 'self' CSP.
 * No external dependencies beyond marked.min.js (loaded before this file).
 */

// ── Language ──────────────────────────────────────────────────────────────────
document.getElementById('lang-toggle').addEventListener('click', () => {
  const es = document.body.classList.toggle('lang-es');
  document.body.classList.toggle('lang-en', !es);
  document.documentElement.lang = es ? 'es' : 'en';
  document.getElementById('lang-field').value = es ? 'es' : 'en';
});

// ── File drop ─────────────────────────────────────────────────────────────────
const fileInput = document.getElementById('pdfs');
const dropZone  = document.getElementById('drop-zone');
const dropFiles = document.getElementById('drop-files');
const dropInner = document.getElementById('drop-inner');
let selectedFiles = []; // mutable array — FileList is read-only

fileInput.addEventListener('change', () => {
  mergeFiles(Array.from(fileInput.files));
});
['dragover','dragenter'].forEach(e => dropZone.addEventListener(e, ev => { ev.preventDefault(); dropZone.classList.add('over'); }));
['dragleave','drop'].forEach(e => dropZone.addEventListener(e, ev => { ev.preventDefault(); dropZone.classList.remove('over'); }));
dropZone.addEventListener('drop', ev => { mergeFiles(Array.from(ev.dataTransfer.files)); });

function mergeFiles(newFiles) {
  // Add only PDFs, deduplicate by name, cap at 2
  for (const f of newFiles) {
    if (f.type !== 'application/pdf' && !f.name.endsWith('.pdf')) continue;
    if (!selectedFiles.find(e => e.name === f.name)) selectedFiles.push(f);
  }
  if (selectedFiles.length > 2) selectedFiles = selectedFiles.slice(0, 2);
  syncInput();
  renderFiles();
}

function removeFile(name) {
  selectedFiles = selectedFiles.filter(f => f.name !== name);
  syncInput();
  renderFiles();
}

function syncInput() {
  // Rebuild the FileList from our mutable array
  const dt = new DataTransfer();
  selectedFiles.forEach(f => dt.items.add(f));
  fileInput.files = dt.files;
}

function renderFiles() {
  if (!selectedFiles.length) {
    dropInner.hidden = false;
    dropFiles.hidden = true;
    dropFiles.innerHTML = '';
    return;
  }
  dropInner.hidden = true;
  dropFiles.hidden = false;
  // data-filename avoids inline onclick; click handled by delegation below
  dropFiles.innerHTML = selectedFiles.map(f =>
    `<span class="file-chip">
      📄 <span class="file-name">${f.name}</span>
      <button type="button" class="file-remove" data-filename="${f.name.replace(/"/g, '&quot;')}"
        aria-label="Remove ${f.name}">✕</button>
    </span>`
  ).join('');
}

// Delegated listener — replaces inline onclick="removeFile(...)" in chips
dropFiles.addEventListener('click', e => {
  const btn = e.target.closest('.file-remove');
  if (btn) removeFile(btn.dataset.filename);
});

// ── Marked config ─────────────────────────────────────────────────────────────
marked.use({ gfm: true, breaks: false });

// ── State machine ─────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const uploadSection    = $('upload-section');
const processingSection= $('processing-section');
const reportSection    = $('report-section');
const reportBody       = $('report-body');
const streamingBar     = $('streaming-bar');
const codesSection     = $('codes-section');
const codeList         = $('code-list');
const errorBox         = $('error-box');
const progressFill     = $('progress-fill');

function setState(state) {
  uploadSection.hidden     = state !== 'upload';
  processingSection.hidden = state !== 'processing';
  reportSection.hidden     = state !== 'report';
  // Scroll the active section into view immediately
  if (state === 'processing') {
    processingSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } else if (state === 'report') {
    reportSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

// ── Step animation ────────────────────────────────────────────────────────────
const STEP_TIMINGS = [0, 700, 1500, 2300, 3200]; // ms each step activates
let stepTimers = [];
let currentStep = -1;

function startProgress() {
  // Reset progress bar
  progressFill.style.transition = 'none';
  progressFill.style.width = '0%';
  // Reset all steps
  currentStep = -1;
  document.querySelectorAll('.step').forEach(s => {
    s.classList.remove('active', 'done');
  });
  // Animate through steps
  STEP_TIMINGS.forEach((delay, i) => {
    const t = setTimeout(() => {
      // Mark previous step as done
      if (i > 0) {
        document.querySelector(`.step[data-step="${i-1}"]`).classList.replace('active', 'done');
      }
      // Activate current step
      const el = document.querySelector(`.step[data-step="${i}"]`);
      el.classList.add('active');
      currentStep = i;
      // Advance progress bar proportionally (steps 0-3 fill to 80%)
      if (i < 4) {
        progressFill.style.transition = 'width 0.6s ease';
        progressFill.style.width = ((i + 1) / 4 * 80) + '%';
      }
    }, delay);
    stepTimers.push(t);
  });
}

function doneProgress() {
  stepTimers.forEach(t => clearTimeout(t));
  stepTimers = [];
  // Complete all steps instantly
  document.querySelectorAll('.step').forEach((s, i) => {
    if (i < 4) s.classList.add('done');
    else s.classList.add('active'); // last step stays active while streaming
  });
  progressFill.style.transition = 'width 0.3s ease';
  progressFill.style.width = '100%';
}

// ── Form submit ───────────────────────────────────────────────────────────────
$('ran-form').addEventListener('submit', async e => {
  e.preventDefault();
  errorBox.hidden = true;

  const code  = $('invite-code').value.trim().toUpperCase();
  const files = fileInput.files;

  if (!code)          return showError('Introduce un código. / Enter a code.');
  if (!files.length)  return showError('Selecciona un PDF. / Select a PDF.');
  if (files.length>2) return showError('Máximo 2 PDFs. / Max 2 PDFs.');

  // Immediate feedback — user knows the click registered
  const btn = document.getElementById('submit-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="show-es">Analizando…</span><span class="show-en">Analysing…</span>';

  setState('processing');
  startProgress();

  const fd = new FormData();
  fd.append('invite_code', code);
  fd.append('language', document.getElementById('lang-field').value || 'es');
  for (const f of files) fd.append('pdfs', f);

  try {
    const res = await fetch('/process', { method: 'POST', body: fd });

    if (!res.ok) {
      let msg = 'Error desconocido / Unknown error';
      try { msg = (await res.json()).detail || msg; } catch(_) {}
      throw new Error(msg);
    }

    // Switch to report — streaming starts
    doneProgress();
    streamingBar.hidden = false;
    setTimeout(() => setState('report'), 400);

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '', codesFound = false;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buf += decoder.decode(value, { stream: true });

      const MARK = '__CODES__:';
      const idx  = buf.indexOf(MARK);

      if (idx !== -1 && !codesFound) {
        reportBody.innerHTML = marked.parse(buf.slice(0, idx));
        try {
          renderCodes(JSON.parse(buf.slice(idx + MARK.length).trim()));
          codesFound = true;
        } catch(_) {}
      } else if (!codesFound) {
        reportBody.innerHTML = marked.parse(buf);
      }
    }

    streamingBar.hidden = true;

  } catch(err) {
    setState('upload');
    btn.disabled = false;
    btn.innerHTML = '<span class="show-es">Analizar mi declaración</span><span class="show-en">Analyse my return</span><span class="btn-arrow">→</span>';
    showError(err.message);
  }
});

// ── Codes section ─────────────────────────────────────────────────────────────
function renderCodes(codes) {
  // data-code avoids inline onclick; click handled by delegation below
  codeList.innerHTML = codes.map(c =>
    `<li class="chip" title="Click to copy" data-code="${c}">${c}</li>`
  ).join('');
  codesSection.hidden = false;
}

// Delegated listener — replaces inline onclick="copyCode(this,'...')" in chips
codeList.addEventListener('click', e => {
  const chip = e.target.closest('.chip');
  if (chip && chip.dataset.code) copyCode(chip, chip.dataset.code);
});

function copyCode(el, code) {
  navigator.clipboard.writeText(code).then(() => {
    el.classList.add('copied');
    setTimeout(() => el.classList.remove('copied'), 1500);
  });
}

function showError(msg) {
  errorBox.textContent = msg;
  errorBox.hidden = false;
}

// ── Print button ──────────────────────────────────────────────────────────────
// Replaces inline onclick="window.print()" on the print button
const printBtn = document.querySelector('.btn-outline[data-action="print"]');
if (printBtn) printBtn.addEventListener('click', () => window.print());
