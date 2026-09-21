/* PaddleOCR Studio - client logic
   Documents -> pages -> lines, with live background-job progress. */

document.addEventListener('DOMContentLoaded', () => {
  // ---------------------------------------------------------------- state
  let documents = [];
  let currentDoc = null;
  let currentRunId = null;
  let currentRunData = null;
  let currentScope = 'page'; // 'page' | 'all'
  let currentTab = 'plainTextTab';
  let currentZoom = 1;
  let annotatedPanelWidth = 0;
  // Structured reports, keyed by document and its last-modified time so a
  // re-run page is rebuilt rather than served stale.
  const structuredReports = new Map();
  let imageMode = 'annotated';
  let textFilter = '';
  let jsonFilter = '';
  let tableFilter = '';
  let selectedFile = null;
  let activeJobId = null;

  const $ = (id) => document.getElementById(id);

  // ------------------------------------------------------------- elements
  const docSelect = $('docSelect');
  const prevPageBtn = $('prevPageBtn');
  const nextPageBtn = $('nextPageBtn');
  const pageSelect = $('pageSelect');
  const totalPagesLabel = $('totalPagesLabel');
  const btnScopePage = $('btnScopePage');
  const btnScopeAll = $('btnScopeAll');
  const refreshRunsBtn = $('refreshRunsBtn');
  const engineBadgeText = $('engineBadgeText');

  const openRunModalBtn = $('openRunModalBtn');
  const closeRunModalBtn = $('closeRunModalBtn');
  const cancelRunBtn = $('cancelRunBtn');
  const executeRunBtn = $('executeRunBtn');
  const runModal = $('runModal');
  const dropZone = $('dropZone');
  const fileInput = $('fileInput');
  const selectedFileCard = $('selectedFileCard');
  const selectedFileName = $('selectedFileName');
  const selectedFileSize = $('selectedFileSize');
  const removeFileBtn = $('removeFileBtn');
  const imagePathInput = $('imagePathInput');
  const modalStartPage = $('modalStartPage');
  const modalEndPage = $('modalEndPage');
  const runProgress = $('runProgress');
  const runProgressText = $('runProgressText');
  const runProgressCount = $('runProgressCount');
  const runProgressTrack = $('runProgressTrack');
  const runProgressFill = $('runProgressFill');
  const runError = $('runError');

  const statLines = $('statLines');
  const statWords = $('statWords');
  const statAvgConf = $('statAvgConf');
  const statHighConf = $('statHighConf');
  const statPagesInfo = $('statPagesInfo');
  const statFilepath = $('statFilepath');

  const imageViewport = $('imageViewport');
  const imageStage = $('imageStage');
  const imageEmptyState = $('imageEmptyState');
  const emptyStateText = $('emptyStateText');
  const imageWrapper = $('imageWrapper');
  const annotatedImage = $('annotatedImage');
  const originalImage = $('originalImage');
  const boxesOverlay = $('boxesOverlay');
  const imagePaneTitle = $('imagePaneTitle');
  const zoomInBtn = $('zoomInBtn');
  const zoomOutBtn = $('zoomOutBtn');
  const zoomFitBtn = $('zoomFitBtn');
  const zoomLevel = $('zoomLevel');
  const btnModeAnnotated = $('btnModeAnnotated');
  const btnModeOriginal = $('btnModeOriginal');

  const tabButtons = document.querySelectorAll('.tab-btn');
  const tabPanes = document.querySelectorAll('.tab-pane');
  const copyCurrentBtn = $('copyCurrentBtn');
  const copyBtnText = $('copyBtnText');
  const downloadCurrentBtn = $('downloadCurrentBtn');
  const plainTextView = $('plainTextView');
  const jsonView = $('jsonView');
  const ocrTableBody = $('ocrTableBody');
  const tableFilterCount = $('tableFilterCount');

  const plainTextSearch = $('plainTextSearch');
  const jsonSearch = $('jsonSearch');
  const tableSearch = $('tableSearch');

  // ================================================================ utils

  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function escapeRegExp(str) {
    return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  /** Escape for HTML, then wrap occurrences of `term` in <mark>. */
  function escapeAndHighlight(text, term) {
    const safe = escapeHtml(text);
    if (!term) return safe;
    const safeTerm = escapeHtml(term);
    if (!safeTerm) return safe;
    return safe.replace(new RegExp(escapeRegExp(safeTerm), 'gi'), (m) => `<mark class="hit">${m}</mark>`);
  }

  function formatBytes(bytes) {
    if (!bytes) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function isTypingTarget(el) {
    return el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable);
  }

  async function copyToClipboard(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (err) {
      // Clipboard API needs a secure context; fall back to a hidden textarea.
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        return ok;
      } catch (fallbackErr) {
        return false;
      }
    }
  }

  /** Read a fetch Response, surfacing the server's JSON error message. */
  async function readJson(res) {
    let payload = null;
    try {
      payload = await res.json();
    } catch (err) {
      payload = null;
    }
    if (!res.ok) {
      throw new Error((payload && payload.error) || `${res.status} ${res.statusText}`);
    }
    return payload;
  }

  // ================================================================ toasts

  function showToast(message, type = 'default') {
    const container = $('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type === 'error' ? 'toast-error' : type === 'success' ? 'toast-success' : ''}`;
    const icon =
      type === 'error'
        ? '<circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line>'
        : '<polyline points="20 6 9 17 4 12"></polyline>';
    toast.innerHTML = `
      <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round">${icon}</svg>
      <span>${escapeHtml(message)}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
      toast.classList.add('leaving');
      setTimeout(() => toast.remove(), 300);
    }, 3000);
  }

  // ======================================================== stats counters

  /** Count a number up to its new value so metric changes are legible. */
  function animateNumber(el, target, suffix = '') {
    const from = parseFloat(String(el.textContent).replace(/[^\d.-]/g, '')) || 0;
    const to = Number(target) || 0;
    el.classList.remove('value-flash');
    void el.offsetWidth; // restart the flash animation
    el.classList.add('value-flash');

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || from === to) {
      el.textContent = to.toLocaleString() + suffix;
      return;
    }

    const duration = 520;
    const start = performance.now();
    const decimals = String(target).includes('.') ? 2 : 0;

    function step(now) {
      const p = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      const value = from + (to - from) * eased;
      el.textContent = (decimals ? value.toFixed(decimals) : Math.round(value).toLocaleString()) + suffix;
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function updateStats(stats, inputPath, pageNum, totalPages) {
    if (!stats) return;
    animateNumber(statLines, stats.total_lines ?? 0);
    animateNumber(statWords, stats.word_count ?? 0);
    animateNumber(statAvgConf, stats.avg_score ?? 0, '%');
    if (stats.high_conf_count === undefined) {
      statHighConf.textContent = '—';
    } else {
      animateNumber(statHighConf, stats.high_conf_count);
    }
    statPagesInfo.textContent = pageNum === 'All' ? `All ${totalPages}` : `${pageNum} / ${totalPages}`;

    const label = inputPath || (currentRunId ? `output/${currentRunId}` : '—');
    statFilepath.textContent = label;
    statFilepath.title = label;
  }

  // ===================================================== loading skeletons

  function showSkeletons() {
    const bars = Array.from({ length: 9 }, () => '<div class="skeleton-line"></div>').join('');
    plainTextView.innerHTML = bars;
    jsonView.innerHTML = bars;
    ocrTableBody.innerHTML = `<tr><td colspan="5" style="padding:16px">${bars}</td></tr>`;
  }

  // ================================================== documents & pages

  async function loadDocumentsList({ silent = false } = {}) {
    const keepDocId = currentDoc && currentDoc.doc_id;
    const keepRunId = currentRunId;
    const keepScope = currentScope;

    try {
      const data = await readJson(await fetch('/api/documents'));
      documents = (data && data.documents) || [];
      docSelect.innerHTML = '';

      if (documents.length === 0) {
        docSelect.innerHTML = '<option value="">No OCR documents yet</option>';
        currentDoc = null;
        currentRunId = null;
        currentRunData = null;
        emptyStateText.textContent = 'No documents yet — click “Run New OCR” to extract your first one.';
        imageEmptyState.style.display = 'flex';
        imageStage.style.display = 'none';
        plainTextView.innerHTML = '<code>Nothing extracted yet.</code>';
        jsonView.innerHTML = '<code>Nothing extracted yet.</code>';
        ocrTableBody.innerHTML = '<tr><td colspan="5" class="table-loading">Nothing extracted yet.</td></tr>';
        return;
      }

      documents.forEach((doc) => {
        const opt = document.createElement('option');
        opt.value = doc.doc_id;
        const pages = doc.total_pages > 1 ? `${doc.total_pages} pages` : '1 page';
        opt.textContent = `${doc.doc_id}  ·  ${doc.is_pdf ? 'PDF' : 'Image'} · ${pages}`;
        docSelect.appendChild(opt);
      });

      // Stay where the user was, if it still exists.
      const stillThere = keepDocId && documents.some((d) => d.doc_id === keepDocId);
      const targetDocId = stillThere ? keepDocId : documents[0].doc_id;
      docSelect.value = targetDocId;

      const targetDoc = documents.find((d) => d.doc_id === targetDocId);
      currentDoc = targetDoc;
      buildPageSelect(targetDoc);

      const keepPage = stillThere && keepRunId && targetDoc.pages.some((p) => p.run_id === keepRunId);
      const runId = keepPage ? keepRunId : targetDoc.pages[0] && targetDoc.pages[0].run_id;

      if (keepPage && keepScope === 'all') {
        currentRunId = runId;
        await loadCombinedDocument(targetDocId);
      } else if (runId) {
        await loadRunDetails(runId);
      }
    } catch (err) {
      console.error('Failed to load documents:', err);
      if (!silent) showToast(`Could not load documents: ${err.message}`, 'error');
    }
  }

  function buildPageSelect(doc) {
    pageSelect.innerHTML = '';
    doc.pages.forEach((p) => {
      const opt = document.createElement('option');
      opt.value = p.run_id;
      opt.textContent = String(p.page_num);
      pageSelect.appendChild(opt);
    });
    totalPagesLabel.textContent = `of ${doc.total_pages}`;
    pageSelect.disabled = doc.total_pages <= 1;
  }

  function selectDocument(docId) {
    const doc = documents.find((d) => d.doc_id === docId);
    if (!doc) return;
    currentDoc = doc;
    buildPageSelect(doc);
    const firstRunId = doc.pages[0] && doc.pages[0].run_id;
    if (firstRunId) loadRunDetails(firstRunId);
  }

  async function loadRunDetails(runId) {
    try {
      currentRunId = runId;
      currentScope = 'page';
      btnScopePage.classList.add('active');
      btnScopeAll.classList.remove('active');
      showSkeletons();

      const data = await readJson(await fetch(`/api/output/${encodeURIComponent(runId)}`));
      currentRunData = data;

      pageSelect.value = runId;
      if (currentDoc) {
        const idx = currentDoc.pages.findIndex((p) => p.run_id === runId);
        prevPageBtn.disabled = idx <= 0;
        nextPageBtn.disabled = idx < 0 || idx >= currentDoc.pages.length - 1;
      }
      imagePaneTitle.textContent =
        data.total_pages > 1 ? `Page ${data.page_num} of ${data.total_pages}` : 'Document & Bounding Boxes';

      updateStats(data.stats, data.input_path, data.page_num, data.total_pages);
      renderAll();
      renderImage({
        imageUrl: data.annotated_image_url,
        inputPath: data.input_path,
        sourceReadable: data.source_readable,
        pageIndex: data.page_index,
        overlayLines: data.lines,
      });
    } catch (err) {
      console.error('Failed to load run details:', err);
      showToast(`Could not load page: ${err.message}`, 'error');
    }
  }

  async function loadCombinedDocument(docId) {
    try {
      currentScope = 'all';
      btnScopePage.classList.remove('active');
      btnScopeAll.classList.add('active');
      showSkeletons();

      const data = await readJson(await fetch(`/api/document-combined/${encodeURIComponent(docId)}`));

      currentRunData = {
        id: data.doc_id,
        doc_id: data.doc_id,
        input_path: data.input_path,
        source_readable: data.source_readable,
        page_num: 'All',
        total_pages: data.total_pages,
        plain_text: data.plain_text,
        lines: data.lines,
        stats: data.stats,
        pages: data.pages,
        raw_json: data,
      };

      imagePaneTitle.textContent = `All ${data.total_pages} pages — showing page 1`;
      updateStats(data.stats, data.input_path, 'All', data.total_pages);
      renderAll();

      // The viewport can only show one page: use page 1 and scope its boxes
      // to the combined line ids so clicks still land on the right row.
      const first = data.first_page;
      if (first) {
        renderImage({
          imageUrl: first.annotated_image_url,
          inputPath: data.input_path,
          sourceReadable: data.source_readable,
          pageIndex: first.page_index,
          overlayLines: data.lines.filter((l) => l.run_id === first.run_id),
        });
      } else {
        renderImage({ imageUrl: null });
      }
    } catch (err) {
      console.error('Failed to load combined document:', err);
      showToast(`Could not combine document: ${err.message}`, 'error');
    }
  }

  function setScope(scope) {
    if (scope === currentScope) return;
    if (scope === 'all') {
      if (currentDoc) loadCombinedDocument(currentDoc.doc_id);
    } else if (currentRunId) {
      loadRunDetails(currentRunId);
    }
  }

  function stepPage(delta) {
    if (!currentDoc || !currentRunId) return;
    const idx = currentDoc.pages.findIndex((p) => p.run_id === currentRunId);
    const next = idx + delta;
    if (idx < 0 || next < 0 || next >= currentDoc.pages.length) return;
    loadRunDetails(currentDoc.pages[next].run_id);
  }

  // ============================================================= rendering

  /** Lines currently visible, honouring the active tab's filter. */
  function filteredLines(filter) {
    const lines = (currentRunData && currentRunData.lines) || [];
    if (!filter) return lines;
    return lines.filter((l) => String(l.text).toLowerCase().includes(filter));
  }

  function renderAll() {
    renderPlainText();
    renderJsonView();
    renderTable();
  }

  function lineLabel(l) {
    return l.page ? `P${l.page}:${l.page_line_id || l.id}` : String(l.id);
  }

  function renderPlainText() {
    if (!currentRunData || !currentRunData.lines) return;
    const format = document.querySelector('input[name="textFormat"]:checked')?.value || 'numbered';
    const lines = filteredLines(textFilter);

    if (lines.length === 0) {
      plainTextView.innerHTML = '<code>No matching text.</code>';
      return;
    }

    if (format === 'numbered') {
      const html = lines
        .map(
          (l) =>
            `<span class="line-numbered" data-line-id="${l.id}">` +
            `<span class="line-number-prefix">${escapeHtml(lineLabel(l))}</span>` +
            `${escapeAndHighlight(l.text, textFilter)}</span>`
        )
        .join('');
      plainTextView.innerHTML = `<code>${html}</code>`;
    } else {
      const joiner = format === 'raw' ? '\n' : ' ';
      const text = lines.map((l) => l.text).join(joiner);
      plainTextView.innerHTML = `<code>${escapeAndHighlight(text, textFilter)}</code>`;
    }
  }

  /** The structured payload shown in the JSON tab - also what gets copied
   *  and downloaded, so the three never drift apart. */
  function buildStructuredJson() {
    return {
      run_id: currentRunData.id,
      document_id: currentRunData.doc_id,
      page_number: currentRunData.page_num,
      total_pages: currentRunData.total_pages,
      input_path: currentRunData.input_path,
      statistics: currentRunData.stats,
      // Geometry is deliberately absent here. This is the data view: what the
      // document says, not where on the page it says it. The polygons are
      // still carried on currentRunData.lines for the image overlay and
      // click-to-locate, and the Raw PaddleOCR view still has every
      // coordinate the engine produced.
      extracted_lines: currentRunData.lines.map((l) => ({
        id: l.id,
        page: l.page || currentRunData.page_num,
        text: l.text,
        confidence_percent: l.score,
      })),
    };
  }

  function selectedJsonType() {
    return document.querySelector('input[name="jsonType"]:checked')?.value || 'report';
  }

  function structuredKey() {
    if (!currentRunData) return null;
    const docId = currentRunData.doc_id || currentRunData.id;
    const stamp = currentDoc && currentDoc.doc_id === docId ? currentDoc.latest_modified : '';
    return `${docId}@${stamp}`;
  }

  /* The structured report is built on the server by the extraction pipeline -
   * table detection, column roles, arithmetic checks - so it is fetched once
   * per document rather than assembled here from the OCR line list. */
  function ensureStructuredReport() {
    const key = structuredKey();
    if (!key) return null;
    if (structuredReports.has(key)) return structuredReports.get(key);
    const docId = key.slice(0, key.lastIndexOf('@'));
    const entry = { state: 'loading', data: null, error: null };
    structuredReports.set(key, entry);
    fetch(`/api/structured/${encodeURIComponent(docId)}`)
      .then(readJson)
      .then((data) => {
        entry.state = 'ready';
        entry.data = data;
      })
      .catch((err) => {
        entry.state = 'error';
        entry.error = err.message;
      })
      .finally(() => {
        if (structuredKey() === key && selectedJsonType() === 'report') renderJsonView();
      });
    return entry;
  }

  function currentJsonObject() {
    const jsonType = selectedJsonType();
    if (jsonType === 'report') {
      const entry = ensureStructuredReport();
      return entry && entry.state === 'ready' ? entry.data : null;
    }
    return jsonType === 'clean' ? buildStructuredJson() : currentRunData.raw_json;
  }

  function renderJsonView() {
    if (!currentRunData) return;
    if (selectedJsonType() === 'report') {
      const entry = ensureStructuredReport();
      if (!entry || entry.state === 'loading') {
        jsonView.innerHTML = '<code>Building the structured report for this document…</code>';
        return;
      }
      if (entry.state === 'error') {
        jsonView.innerHTML = `<code>${escapeHtml(`Structured report unavailable: ${entry.error}`)}</code>`;
        return;
      }
    }
    let jsonString = JSON.stringify(currentJsonObject(), null, 2);

    if (jsonFilter) {
      const matched = jsonString.split('\n').filter((line) => line.toLowerCase().includes(jsonFilter));
      jsonString = matched.length ? matched.join('\n') : '// no matching lines';
    }
    jsonView.innerHTML = `<code>${highlightJson(jsonString)}</code>`;
  }

  function highlightJson(json) {
    if (!json) return '';
    return escapeHtml(json).replace(
      /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
      (match) => {
        let cls = 'json-number';
        if (/^&quot;|^"/.test(match)) {
          cls = /:$/.test(match) ? 'json-key' : 'json-string';
        } else if (/^(true|false)$/.test(match)) {
          cls = 'json-boolean';
        } else if (match === 'null') {
          cls = 'json-null';
        }
        return `<span class="${cls}">${match}</span>`;
      }
    );
  }

  function confClass(score) {
    if (score === null || score === undefined) return 'conf-med';
    if (score < 70) return 'conf-low';
    if (score < 90) return 'conf-med';
    return 'conf-high';
  }

  function renderTable() {
    if (!currentRunData || !currentRunData.lines) return;
    const lines = filteredLines(tableFilter);
    const total = currentRunData.lines.length;

    tableFilterCount.textContent = tableFilter
      ? `${lines.length} of ${total} lines`
      : `${total} line${total === 1 ? '' : 's'}`;

    if (lines.length === 0) {
      ocrTableBody.innerHTML = '<tr><td colspan="5" class="table-loading">No matching rows.</td></tr>';
      return;
    }

    ocrTableBody.innerHTML = lines
      .map((l, i) => {
        let boxSummary = 'N/A';
        if (Array.isArray(l.poly) && l.poly.length >= 3) {
          const xs = l.poly.map((p) => p[0]);
          const ys = l.poly.map((p) => p[1]);
          const minX = Math.round(Math.min(...xs));
          const minY = Math.round(Math.min(...ys));
          const w = Math.round(Math.max(...xs) - minX);
          const h = Math.round(Math.max(...ys) - minY);
          boxSummary = `${minX},${minY} · ${w}×${h}`;
        }
        // Cap the entry animation so huge tables do not stagger forever.
        const delay = Math.min(i, 24) * 12;
        return `
          <tr data-line-id="${l.id}" style="animation-delay:${delay}ms">
            <td class="row-index">${escapeHtml(lineLabel(l))}</td>
            <td class="text-cell">${escapeAndHighlight(l.text, tableFilter)}</td>
            <td><span class="badge-confidence ${confClass(l.score)}">${l.score !== null && l.score !== undefined ? l.score + '%' : 'N/A'}</span></td>
            <td class="coords-cell" title="${escapeHtml(JSON.stringify(l.poly))}">${escapeHtml(boxSummary)}</td>
            <td>
              <button class="icon-btn btn-sm copy-line-btn" data-text="${escapeHtml(l.text)}" title="Copy this line">
                <svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                </svg>
              </button>
            </td>
          </tr>`;
      })
      .join('');
  }

  // Delegated table interactions - survives every re-render.
  ocrTableBody.addEventListener('click', async (e) => {
    const btn = e.target.closest('.copy-line-btn');
    if (!btn) return;
    e.stopPropagation();
    const text = btn.getAttribute('data-text') || '';
    showToast((await copyToClipboard(text)) ? `Copied “${text.slice(0, 48)}”` : 'Copy failed', 'success');
  });

  ocrTableBody.addEventListener('mouseover', (e) => {
    const row = e.target.closest('tr[data-line-id]');
    if (row) highlightPolygon(row.getAttribute('data-line-id'), true);
  });

  ocrTableBody.addEventListener('mouseout', (e) => {
    const row = e.target.closest('tr[data-line-id]');
    if (row) highlightPolygon(row.getAttribute('data-line-id'), false);
  });

  // ============================================================== viewport

  function renderImage({ imageUrl, inputPath, sourceReadable, pageIndex, overlayLines }) {
    if (!imageUrl) {
      emptyStateText.textContent = 'No annotated image was saved for this page.';
      imageEmptyState.style.display = 'flex';
      imageStage.style.display = 'none';
      boxesOverlay.innerHTML = '';
      return;
    }

    imageEmptyState.style.display = 'none';
    imageStage.style.display = 'flex';
    annotatedImage.src = imageUrl;

    // "Original" view: PDFs get re-rendered crisply, images are served raw.
    if (inputPath && sourceReadable) {
      const idx = pageIndex === null || pageIndex === undefined ? 0 : pageIndex;
      originalImage.src = inputPath.toLowerCase().endsWith('.pdf')
        ? `/api/pdf-page-image?path=${encodeURIComponent(inputPath)}&page=${idx}`
        : `/api/raw-image?path=${encodeURIComponent(inputPath)}`;
      btnModeOriginal.disabled = false;
      btnModeOriginal.title = 'Show the crisp original page';
    } else {
      originalImage.removeAttribute('src');
      btnModeOriginal.disabled = true;
      btnModeOriginal.title = inputPath
        ? 'Source file is outside the allowed folders (set OCR_ALLOWED_DIRS to view it)'
        : 'No source file recorded';
      if (imageMode === 'original') setImageMode('annotated');
    }

    annotatedImage.onload = () => {
      annotatedPanelWidth = photoPanelWidth(annotatedImage, overlayLines);
      setupSvgOverlay(overlayLines, annotatedPanelWidth, annotatedImage.naturalHeight);
      fitImageToViewport();
    };
    originalImage.onload = () => {
      if (imageMode === 'original') fitImageToViewport();
    };
    annotatedImage.onerror = () => {
      emptyStateText.textContent = 'The annotated image could not be loaded.';
      imageEmptyState.style.display = 'flex';
      imageStage.style.display = 'none';
    };
  }

  /* PaddleOCR saves its annotated image side by side: the page with boxes on
   * the left, and on the right a white panel re-drawing the recognised text at
   * the same size - so the file is exactly twice the page's width (a 4096 px
   * photo becomes an 8192 px image). The right panel repeats the Text and Table
   * tabs, and showing the whole thing shrank the page to a sliver. Only the
   * left panel is shown.
   *
   * The file does not say which kind it is, so the boxes decide: every box OCR
   * drew lies on the page, so if they all fit inside the left half and reach
   * well into it, the right half is the text panel. A page whose text happens
   * to sit in its left quarter is left whole rather than cut.
   */
  function photoPanelWidth(img, lines) {
    const full = img.naturalWidth;
    const xs = (lines || [])
      .filter((l) => Array.isArray(l.poly))
      .flatMap((l) => l.poly.map((pt) => pt[0]));
    if (!xs.length) return full;
    const maxX = Math.max(...xs);
    const half = full / 2;
    return maxX <= half + 2 && maxX > half * 0.5 ? Math.round(half) : full;
  }

  function setupSvgOverlay(lines, imgW, imgH) {
    boxesOverlay.setAttribute('viewBox', `0 0 ${imgW || 1} ${imgH || 1}`);
    boxesOverlay.innerHTML = '';
    if (!lines || !lines.length) return;

    const frag = document.createDocumentFragment();
    lines.forEach((l, i) => {
      if (!Array.isArray(l.poly) || l.poly.length < 3) return;
      const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
      poly.setAttribute('points', l.poly.map((p) => `${p[0]},${p[1]}`).join(' '));
      poly.setAttribute('data-line-id', l.id);
      let cls = 'bbox-polygon';
      if (l.score !== null && l.score !== undefined) {
        if (l.score < 70) cls += ' conf-bad';
        else if (l.score < 90) cls += ' conf-warn';
      }
      poly.setAttribute('class', cls);
      poly.style.animationDelay = `${Math.min(i, 60) * 8}ms`;

      const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
      title.textContent = `#${lineLabel(l)} — ${l.text} (${l.score ?? '?'}%)`;
      poly.appendChild(title);
      frag.appendChild(poly);
    });
    boxesOverlay.appendChild(frag);
  }

  // Delegated so re-rendering the overlay never loses its handlers.
  boxesOverlay.addEventListener('mouseover', (e) => {
    const poly = e.target.closest('.bbox-polygon');
    if (!poly) return;
    poly.classList.add('highlighted');
    highlightTableRow(poly.getAttribute('data-line-id'), true);
  });

  boxesOverlay.addEventListener('mouseout', (e) => {
    const poly = e.target.closest('.bbox-polygon');
    if (!poly) return;
    poly.classList.remove('highlighted');
    highlightTableRow(poly.getAttribute('data-line-id'), false);
  });

  boxesOverlay.addEventListener('click', (e) => {
    const poly = e.target.closest('.bbox-polygon');
    if (!poly) return;
    const id = poly.getAttribute('data-line-id');
    // Clear any filter that would hide the row we are about to jump to.
    if (tableFilter) {
      tableFilter = '';
      tableSearch.value = '';
      renderTable();
    }
    switchTab('tableTab');
    scrollTableRowIntoView(id);
  });

  function highlightPolygon(lineId, active) {
    const poly = boxesOverlay.querySelector(`polygon[data-line-id="${CSS.escape(String(lineId))}"]`);
    if (poly) poly.classList.toggle('highlighted', active);
  }

  function highlightTableRow(lineId, active) {
    const row = ocrTableBody.querySelector(`tr[data-line-id="${CSS.escape(String(lineId))}"]`);
    if (row) row.classList.toggle('row-highlighted', active);
  }

  function scrollTableRowIntoView(lineId) {
    const row = ocrTableBody.querySelector(`tr[data-line-id="${CSS.escape(String(lineId))}"]`);
    if (!row) return;
    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    row.classList.add('row-highlighted');
    setTimeout(() => row.classList.remove('row-highlighted'), 2200);
  }

  // ---------------------------------------------------------- zoom & pan

  /* Zoom sets real sizes, not a CSS transform. A transform only changes how an
   * element looks, never the space it takes, so the page kept laying the image
   * out at full size: a wide scan overflowed, the wrapper clipped it to the
   * panel width, and zooming out merely shrank that clipped strip. With real
   * sizes the scrollbars and panning always cover the whole image.
   */
  function shownSize() {
    const img = imageMode === 'original' ? originalImage : annotatedImage;
    if (!img.naturalWidth) return null;
    const width = img === annotatedImage && annotatedPanelWidth ? annotatedPanelWidth : img.naturalWidth;
    return { img, width, height: img.naturalHeight };
  }

  function setZoom(val) {
    currentZoom = Math.min(Math.max(val, 0.02), 6);
    zoomLevel.textContent = `${Math.round(currentZoom * 100)}%`;
    const size = shownSize();
    if (size) {
      imageWrapper.style.width = `${Math.round(size.width * currentZoom)}px`;
      imageWrapper.style.height = `${Math.round(size.height * currentZoom)}px`;
      // The image keeps its full width, so the wrapper crops away the text panel.
      size.img.style.width = `${Math.round(size.img.naturalWidth * currentZoom)}px`;
      size.img.style.height = `${Math.round(size.height * currentZoom)}px`;
    }
    const scrollable = imageViewport.scrollWidth > imageViewport.clientWidth + 1
      || imageViewport.scrollHeight > imageViewport.clientHeight + 1;
    imageViewport.classList.toggle('can-pan', scrollable);
  }

  function fitImageToViewport() {
    const size = shownSize();
    if (!size) return;
    const vpW = imageViewport.clientWidth - 56;
    const vpH = imageViewport.clientHeight - 56;
    setZoom(Math.min(vpW / size.width, vpH / size.height));
  }

  function setImageMode(mode) {
    if (mode === 'original' && btnModeOriginal.disabled) return;
    imageMode = mode;
    btnModeAnnotated.classList.toggle('active', mode === 'annotated');
    btnModeOriginal.classList.toggle('active', mode === 'original');
    annotatedImage.style.display = mode === 'annotated' ? 'block' : 'none';
    originalImage.style.display = mode === 'original' ? 'block' : 'none';
    boxesOverlay.style.display = mode === 'annotated' ? 'block' : 'none';
    // The two views differ in size (a PDF original is re-rendered crisper).
    fitImageToViewport();
  }

  // Ctrl/Cmd + wheel zooms; plain wheel keeps scrolling the viewport.
  imageViewport.addEventListener(
    'wheel',
    (e) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      setZoom(currentZoom * (e.deltaY < 0 ? 1.12 : 1 / 1.12));
    },
    { passive: false }
  );

  let panning = false;
  let panStart = { x: 0, y: 0, left: 0, top: 0 };

  imageViewport.addEventListener('mousedown', (e) => {
    if (e.button !== 0 || e.target.closest('.bbox-polygon')) return;
    panning = true;
    panStart = {
      x: e.clientX,
      y: e.clientY,
      left: imageViewport.scrollLeft,
      top: imageViewport.scrollTop,
    };
    imageViewport.classList.add('is-panning');
  });

  window.addEventListener('mousemove', (e) => {
    if (!panning) return;
    imageViewport.scrollLeft = panStart.left - (e.clientX - panStart.x);
    imageViewport.scrollTop = panStart.top - (e.clientY - panStart.y);
  });

  window.addEventListener('mouseup', () => {
    panning = false;
    imageViewport.classList.remove('is-panning');
  });

  // ================================================================= tabs

  function switchTab(tabId) {
    currentTab = tabId;
    tabButtons.forEach((btn) => btn.classList.toggle('active', btn.getAttribute('data-tab') === tabId));
    tabPanes.forEach((pane) => pane.classList.toggle('active', pane.id === tabId));
    copyBtnText.textContent =
      tabId === 'plainTextTab' ? 'Copy Text' : tabId === 'jsonTab' ? 'Copy JSON' : 'Copy Rows';
  }

  // ==================================================== copy & download

  function activeExportPayload() {
    if (currentTab === 'plainTextTab') {
      const format = document.querySelector('input[name="textFormat"]:checked')?.value || 'numbered';
      const lines = filteredLines(textFilter);
      let content;
      if (format === 'numbered') content = lines.map((l) => `${lineLabel(l)}. ${l.text}`).join('\n');
      else if (format === 'raw') content = lines.map((l) => l.text).join('\n');
      else content = lines.map((l) => l.text).join(' ');
      return { content, filename: 'text.txt', type: 'text/plain;charset=utf-8', label: 'text' };
    }

    if (currentTab === 'jsonTab') {
      const jsonType = selectedJsonType();
      const payload = currentJsonObject();
      return {
        content: payload === null ? null : JSON.stringify(payload, null, 2),
        filename: jsonType === 'report' ? 'structured-report.json' : `${jsonType}.json`,
        type: 'application/json;charset=utf-8',
        label: 'JSON',
      };
    }

    const lines = filteredLines(tableFilter);
    const header = 'ID\tPage\tText\tConfidence\n';
    const body = lines
      .map((l) => `${l.id}\t${l.page || currentRunData.page_num}\t${String(l.text).replace(/\t/g, ' ')}\t${l.score}`)
      .join('\n');
    return { content: header + body, filename: 'lines.tsv', type: 'text/tab-separated-values;charset=utf-8', label: 'rows' };
  }

  function reportNotReady() {
    const entry = ensureStructuredReport();
    showToast(entry && entry.state === 'error'
      ? `Structured report unavailable: ${entry.error}`
      : 'The structured report is still being built', entry && entry.state === 'error' ? 'error' : 'default');
  }

  async function handleCopyCurrent() {
    if (!currentRunData) return;
    const { content, label } = activeExportPayload();
    if (content === null) return reportNotReady();
    showToast((await copyToClipboard(content)) ? `Copied ${label} to clipboard` : 'Copy failed', 'success');
  }

  function handleDownloadCurrent() {
    if (!currentRunData) return;
    const { content, filename, type } = activeExportPayload();
    if (content === null) return reportNotReady();
    // The structured report always covers the whole document.
    const wholeDocument = currentTab === 'jsonTab' && selectedJsonType() === 'report';
    const base = wholeDocument
      ? currentRunData.doc_id || currentRunData.id || 'ocr'
      : currentRunData.id || currentRunData.doc_id || 'ocr';
    const suffix = wholeDocument ? ''
      : currentRunData.page_num === 'All' ? '_all-pages' : `_page${currentRunData.page_num}`;
    const fullName = `${base}${suffix}_${filename}`;

    const url = URL.createObjectURL(new Blob([content], { type }));
    const a = document.createElement('a');
    a.href = url;
    a.download = fullName;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast(`Downloaded ${fullName}`, 'success');
  }

  // ================================================================ modal

  function openModal() {
    runError.style.display = 'none';
    runProgress.style.display = 'none';
    runModal.classList.remove('closing');
    runModal.style.display = 'flex';
    setTimeout(() => imagePathInput.focus(), 120);
  }

  function closeModal() {
    runModal.classList.add('closing');
    setTimeout(() => {
      runModal.style.display = 'none';
      runModal.classList.remove('closing');
    }, 180);
  }

  function handleFileSelected(file) {
    selectedFile = file;
    selectedFileName.textContent = file.name;
    selectedFileSize.textContent = formatBytes(file.size);
    selectedFileCard.style.display = 'flex';
    dropZone.style.display = 'none';
    runError.style.display = 'none';
  }

  function clearSelectedFile() {
    selectedFile = null;
    fileInput.value = '';
    selectedFileCard.style.display = 'none';
    dropZone.style.display = 'flex';
  }

  function showRunError(message) {
    runError.textContent = message;
    runError.style.display = 'block';
    runProgress.style.display = 'none';
    executeRunBtn.disabled = false;
  }

  // ======================================================== job progress

  function updateProgressUI(job) {
    runProgress.style.display = 'flex';
    runProgressText.textContent = job.message || job.status;

    const done = job.pages_done || 0;
    const expected = job.pages_expected;

    if (expected) {
      runProgressTrack.classList.remove('indeterminate');
      runProgressFill.style.width = `${Math.min(100, Math.round((done / expected) * 100))}%`;
      runProgressCount.textContent = `${done} / ${expected}`;
    } else {
      runProgressTrack.classList.add('indeterminate');
      runProgressCount.textContent = done ? `${done} page${done === 1 ? '' : 's'}` : '';
    }
  }

  async function pollJob(jobId) {
    let lastPagesDone = 0;
    activeJobId = jobId;

    while (activeJobId === jobId) {
      let job;
      try {
        job = await readJson(await fetch(`/api/job/${encodeURIComponent(jobId)}`));
      } catch (err) {
        showRunError(`Lost track of the job: ${err.message}`);
        return;
      }

      updateProgressUI(job);
      engineBadgeText.textContent = job.status === 'running' ? 'Working…' : 'PP-OCRv6 medium';

      // Refresh the document list as soon as new pages hit disk.
      if (job.pages_done > lastPagesDone) {
        lastPagesDone = job.pages_done;
        await loadDocumentsList({ silent: true });
      }

      if (job.status === 'done') {
        engineBadgeText.textContent = 'PP-OCRv6 medium';
        executeRunBtn.disabled = false;
        runProgress.style.display = 'none';
        clearSelectedFile();
        closeModal();
        showToast(`OCR finished — ${job.pages_done} page(s) processed`, 'success');
        await loadDocumentsList({ silent: true });
        if (job.first_run_id) {
          const target = documents.find((d) => d.pages.some((p) => p.run_id === job.first_run_id));
          if (target) {
            currentDoc = target;
            docSelect.value = target.doc_id;
            buildPageSelect(target);
          }
          await loadRunDetails(job.first_run_id);
        }
        activeJobId = null;
        return;
      }

      if (job.status === 'error') {
        engineBadgeText.textContent = 'PP-OCRv6 medium';
        showRunError(job.error || 'OCR failed');
        activeJobId = null;
        return;
      }

      await sleep(900);
    }
  }

  async function executeNewOcr() {
    let imgPath = imagePathInput.value.trim();
    runError.style.display = 'none';
    executeRunBtn.disabled = true;

    if (selectedFile) {
      runProgress.style.display = 'flex';
      runProgressTrack.classList.add('indeterminate');
      runProgressText.textContent = `Uploading ${selectedFile.name}…`;
      runProgressCount.textContent = formatBytes(selectedFile.size);
      try {
        const uploadData = await readJson(
          await fetch('/api/upload', {
            method: 'POST',
            headers: { 'X-Filename': encodeURIComponent(selectedFile.name) },
            body: selectedFile,
          })
        );
        imgPath = uploadData.filepath;
      } catch (err) {
        showRunError(`Upload failed: ${err.message}`);
        return;
      }
    }

    if (!imgPath) {
      showRunError('Choose a file to upload, or type an absolute path.');
      return;
    }

    const pageMode = document.querySelector('input[name="modalPageMode"]:checked')?.value || 'first';
    runProgress.style.display = 'flex';
    runProgressText.textContent = 'Queuing job…';
    runProgressCount.textContent = '';

    try {
      const data = await readJson(
        await fetch('/api/run-ocr', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            image_path: imgPath,
            page_mode: pageMode,
            start_page: parseInt(modalStartPage.value, 10) || 1,
            end_page: parseInt(modalEndPage.value, 10) || 1,
          }),
        })
      );
      pollJob(data.job_id);
    } catch (err) {
      showRunError(err.message);
    }
  }

  // ======================================================= event wiring

  docSelect.addEventListener('change', (e) => {
    if (e.target.value) selectDocument(e.target.value);
  });

  pageSelect.addEventListener('change', (e) => {
    if (e.target.value) loadRunDetails(e.target.value);
  });

  prevPageBtn.addEventListener('click', () => stepPage(-1));
  nextPageBtn.addEventListener('click', () => stepPage(1));
  btnScopePage.addEventListener('click', () => setScope('page'));
  btnScopeAll.addEventListener('click', () => setScope('all'));

  refreshRunsBtn.addEventListener('click', async () => {
    refreshRunsBtn.classList.add('spinning');
    await loadDocumentsList();
    setTimeout(() => refreshRunsBtn.classList.remove('spinning'), 700);
    showToast('Documents refreshed');
  });

  tabButtons.forEach((btn) => btn.addEventListener('click', () => switchTab(btn.getAttribute('data-tab'))));
  copyCurrentBtn.addEventListener('click', handleCopyCurrent);
  downloadCurrentBtn.addEventListener('click', handleDownloadCurrent);

  document.querySelectorAll('input[name="textFormat"]').forEach((r) => r.addEventListener('change', renderPlainText));
  document.querySelectorAll('input[name="jsonType"]').forEach((r) => r.addEventListener('change', renderJsonView));

  plainTextSearch.addEventListener('input', (e) => {
    textFilter = e.target.value.toLowerCase().trim();
    renderPlainText();
  });

  jsonSearch.addEventListener('input', (e) => {
    jsonFilter = e.target.value.toLowerCase().trim();
    renderJsonView();
  });

  tableSearch.addEventListener('input', (e) => {
    tableFilter = e.target.value.toLowerCase().trim();
    renderTable();
  });

  zoomInBtn.addEventListener('click', () => setZoom(currentZoom * 1.25));
  zoomOutBtn.addEventListener('click', () => setZoom(currentZoom / 1.25));
  zoomFitBtn.addEventListener('click', fitImageToViewport);
  btnModeAnnotated.addEventListener('click', () => setImageMode('annotated'));
  btnModeOriginal.addEventListener('click', () => setImageMode('original'));

  openRunModalBtn.addEventListener('click', openModal);
  closeRunModalBtn.addEventListener('click', closeModal);
  cancelRunBtn.addEventListener('click', closeModal);

  // Click the dimmed area to dismiss.
  runModal.addEventListener('mousedown', (e) => {
    if (e.target === runModal) closeModal();
  });

  dropZone.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', (e) => {
    if (e.target.files && e.target.files.length) handleFileSelected(e.target.files[0]);
  });
  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
  });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    if (e.dataTransfer.files && e.dataTransfer.files.length) handleFileSelected(e.dataTransfer.files[0]);
  });
  removeFileBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    clearSelectedFile();
  });
  executeRunBtn.addEventListener('click', executeNewOcr);

  // Dropping a file anywhere opens the dialog with it pre-filled.
  window.addEventListener('dragover', (e) => e.preventDefault());
  window.addEventListener('drop', (e) => {
    e.preventDefault();
    if (runModal.style.display === 'flex') return;
    if (e.dataTransfer.files && e.dataTransfer.files.length) {
      openModal();
      handleFileSelected(e.dataTransfer.files[0]);
    }
  });

  // ---------------------------------------------------------- shortcuts

  document.addEventListener('keydown', (e) => {
    const modalOpen = runModal.style.display === 'flex';

    if (e.key === 'Escape' && modalOpen) {
      closeModal();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'n') {
      e.preventDefault();
      openModal();
      return;
    }
    if (modalOpen || isTypingTarget(e.target)) return;

    switch (e.key) {
      case 'ArrowLeft': stepPage(-1); break;
      case 'ArrowRight': stepPage(1); break;
      case '+': case '=': setZoom(currentZoom * 1.25); break;
      case '-': case '_': setZoom(currentZoom / 1.25); break;
      case '0': fitImageToViewport(); break;
      case '1': switchTab('plainTextTab'); break;
      case '2': switchTab('jsonTab'); break;
      case '3': switchTab('tableTab'); break;
      default: break;
    }
  });

  window.addEventListener('resize', () => {
    if (imageStage.style.display !== 'none') fitImageToViewport();
  });

  // ================================================================= init

  setImageMode('annotated');
  loadDocumentsList();
});
