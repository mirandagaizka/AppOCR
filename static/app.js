"use strict";

// ─── Estado ─────────────────────────────────────────────────────────────────
const STATE = {
  accessKey: localStorage.getItem("ocr_access_key") || "",
  currentFile: null,
  lastPdfUrl: null,
  currentInvoiceId: null,
  currentData: null,         // copia de los datos servidor para detectar cambios
  dirty: false,
  view: "scan",              // "scan" | "registry"

  // Vista previa del original en el panel de resultado
  previewBlobUrl: null,

  // Batch
  batch: {
    items: [],               // [{file, status: 'pending'|'processing'|'done'|'error'|'duplicate', id?, pdf_url?, error?}]
    cancelled: false,
    running: false,
  },

  // Registry filters
  invoicesCache: [],
};

// ─── DOM ─────────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const authScreen    = $("auth-screen");
const pinInput      = $("pin-input");
const btnAuthOk     = $("btn-auth-ok");
const mainContent   = $("main-content");
const dropZone      = $("drop-zone");
const fileInput     = $("file-input");
const cameraInput   = $("camera-input");
const btnCamera     = $("btn-camera");
const btnBrowse     = $("btn-browse");
const previewWrap   = $("preview-wrap");
const previewImg    = $("preview-img");
const previewName   = $("preview-name");
const btnProcess    = $("btn-process");
const btnClear      = $("btn-clear");
const statusEl      = $("status");
const statusText    = $("status-text");
const resultEl      = $("result");
const resultFields  = $("result-fields");
const btnDownloadPdf= $("btn-download-pdf");
const btnSaveChanges= $("btn-save-changes");
const btnScanAnother= $("btn-scan-another");
const btnBackToBatch= $("btn-back-to-batch");
const registryEl    = $("registry");
const invList       = $("inv-list");
const btnDownloadXls= $("btn-download-xls");
const navScan       = $("nav-scan");
const navRegistry   = $("nav-registry");
const toast         = $("toast");

// Batch UI
const batchSection      = $("batch-section");
const batchProgressText = $("batch-progress-text");
const batchProgressFill = $("batch-progress-fill");
const batchList         = $("batch-list");
const batchActions      = $("batch-actions");
const btnCancelBatch    = $("btn-cancel-batch");
const btnBatchZip       = $("btn-batch-zip");
const btnBatchExcel     = $("btn-batch-excel");
const btnBatchReset     = $("btn-batch-reset");

// Result preview (split view)
const resultPreviewIframe = $("result-preview-iframe");
const resultPreviewImg    = $("result-preview-img");
const resultPreviewEmpty  = $("result-preview-empty");

// Filters UI
const filterQ    = $("filter-q");
const filterFrom = $("filter-from");
const filterTo   = $("filter-to");
const filterMin  = $("filter-min");
const filterMax  = $("filter-max");
const filterSort = $("filter-sort");
const filterCount= $("filter-count");
const btnClearFilters = $("btn-clear-filters");

// ─── Toast ───────────────────────────────────────────────────────────────────
let toastTimer = null;
function showToast(msg, isError = false) {
  toast.textContent = msg;
  toast.classList.toggle("error", isError);
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 3200);
}

// ─── Auth ────────────────────────────────────────────────────────────────────
async function checkAuth() {
  // Primero verificar si el servidor requiere auth
  try {
    const res = await fetch("/api/health");
    if (res.ok) {
      // Servidor ok — si hay clave guardada úsala, si no, probar sin clave
      if (!STATE.accessKey) {
        // Probar acceso sin clave
        const test = await fetch("/api/invoices");
        if (test.status === 401) {
          showAuthScreen();
          return;
        }
      }
      showMainContent();
    }
  } catch {
    showToast("Sin conexión con el servidor", true);
  }
}

function showAuthScreen() {
  authScreen.style.display = "flex";
  mainContent.classList.add("hidden");
}

function showMainContent() {
  authScreen.style.display = "none";
  mainContent.classList.remove("hidden");
}

btnAuthOk.addEventListener("click", async () => {
  const key = pinInput.value.trim();
  if (!key) return;

  // Verificar clave
  const res = await fetch("/api/invoices", {
    headers: { "X-Access-Key": key },
  });
  if (res.status === 401) {
    showToast("Clave incorrecta", true);
    return;
  }
  STATE.accessKey = key;
  localStorage.setItem("ocr_access_key", key);
  showMainContent();
});

pinInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") btnAuthOk.click();
});

// ─── Selección de archivo ────────────────────────────────────────────────────
function handleFile(file) {
  if (!file) return;
  const allowed = ["image/jpeg", "image/jpg", "image/png", "image/webp", "application/pdf"];
  if (!allowed.includes(file.type)) {
    showToast("Formato no soportado. Usa JPG, PNG, WEBP o PDF.", true);
    return;
  }
  if (file.size > 20 * 1024 * 1024) {
    showToast("El archivo supera los 20 MB.", true);
    return;
  }
  STATE.currentFile = file;
  previewName.textContent = file.name;
  dropZone.style.display = "none";
  previewWrap.style.display = "flex";
  resultEl.style.display = "none";
  statusEl.style.display = "none";

  if (file.type.startsWith("image/")) {
    const reader = new FileReader();
    reader.onload = (e) => { previewImg.src = e.target.result; };
    reader.readAsDataURL(file);
    previewImg.style.display = "block";
  } else {
    previewImg.style.display = "none";
  }
}

fileInput.addEventListener("change", () => {
  const files = Array.from(fileInput.files || []);
  if (files.length === 0) return;
  if (files.length === 1) {
    handleFile(files[0]);
  } else {
    startBatch(files);
  }
});
cameraInput.addEventListener("change", () => handleFile(cameraInput.files[0]));

// Botones explícitos: cámara vs explorador de archivos
btnCamera.addEventListener("click", (e) => {
  e.stopPropagation();
  cameraInput.click();
});
btnBrowse.addEventListener("click", (e) => {
  e.stopPropagation();
  fileInput.click();
});

// Drag & drop (escritorio)
dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("drag-over");
});
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("drag-over");
  handleFile(e.dataTransfer.files[0]);
});

btnClear.addEventListener("click", resetScan);

function resetScan() {
  STATE.currentFile = null;
  STATE.lastPdfUrl = null;
  STATE.currentInvoiceId = null;
  STATE.currentData = null;
  STATE.dirty = false;
  fileInput.value = "";
  cameraInput.value = "";
  previewImg.src = "";
  clearResultPreview();
  dropZone.style.display = "block";
  previewWrap.style.display = "none";
  statusEl.style.display = "none";
  resultEl.style.display = "none";
}

// ─── Preview del original en el panel de resultado ──────────────────────────
function setResultPreview(file) {
  clearResultPreview();
  if (!file) {
    resultPreviewEmpty.style.display = "block";
    return;
  }
  const url = URL.createObjectURL(file);
  STATE.previewBlobUrl = url;

  if (file.type === "application/pdf") {
    resultPreviewIframe.src = url;
    resultPreviewIframe.style.display = "block";
    resultPreviewImg.style.display = "none";
    resultPreviewEmpty.style.display = "none";
  } else if (file.type && file.type.startsWith("image/")) {
    resultPreviewImg.src = url;
    resultPreviewImg.style.display = "block";
    resultPreviewIframe.style.display = "none";
    resultPreviewEmpty.style.display = "none";
  } else {
    resultPreviewEmpty.style.display = "block";
  }
}

function clearResultPreview() {
  if (STATE.previewBlobUrl) {
    try { URL.revokeObjectURL(STATE.previewBlobUrl); } catch {}
    STATE.previewBlobUrl = null;
  }
  resultPreviewIframe.src = "";
  resultPreviewIframe.style.display = "none";
  resultPreviewImg.src = "";
  resultPreviewImg.style.display = "none";
  resultPreviewEmpty.style.display = "block";
}

// ─── Procesar factura ─────────────────────────────────────────────────────────
btnProcess.addEventListener("click", processInvoice);
btnScanAnother.addEventListener("click", resetScan);

async function processInvoice(forceParam = false) {
  if (!STATE.currentFile) return;

  previewWrap.style.display = "none";
  resultEl.style.display = "none";
  statusEl.style.display = "flex";
  statusText.textContent = "Enviando imagen…";
  btnProcess.disabled = true;

  try {
    const result = await scanFile(STATE.currentFile, forceParam, (msg) => {
      statusText.textContent = msg;
    });

    statusEl.style.display = "none";

    if (result.duplicate) {
      const ok = await confirmDuplicate(result);
      if (ok) {
        previewWrap.style.display = "flex";
        return processInvoice(true);   // reintenta con force=true
      }
      // Cancelado → vuelve al estado preview
      previewWrap.style.display = "flex";
      showToast("Procesamiento cancelado", false);
      return;
    }

    renderResult(result.data, result.pdf_url, result.id, STATE.currentFile);

  } catch (err) {
    statusEl.style.display = "none";
    previewWrap.style.display = "flex";
    showToast(err.message || "Error al procesar la factura", true);
    console.error(err);
  } finally {
    btnProcess.disabled = false;
  }
}

/**
 * Sube un archivo al backend y devuelve { data, pdf_url, id } o { duplicate: true, ... }.
 * Lanza Error si la respuesta no es 200 ni 409.
 */
async function scanFile(file, force = false, onProgress = () => {}) {
  const form = new FormData();
  form.append("file", file);

  onProgress("Extrayendo datos con IA…");
  const url = "/api/scan" + (force ? "?force=true" : "");
  const res = await fetch(url, {
    method: "POST",
    headers: STATE.accessKey ? { "X-Access-Key": STATE.accessKey } : {},
    body: form,
  });

  if (res.status === 401) {
    STATE.accessKey = "";
    localStorage.removeItem("ocr_access_key");
    showAuthScreen();
    throw new Error("Sesión caducada");
  }

  const body = await res.json();

  if (res.status === 409 && body.duplicate) {
    return { duplicate: true, ...body };
  }

  if (!res.ok) {
    throw new Error(body.detail || body.message || "Error desconocido");
  }

  return body;
}

function confirmDuplicate(result) {
  const ex = result.existing || {};
  const total = ex.total != null
    ? Number(ex.total).toLocaleString("es-ES", { minimumFractionDigits: 2 }) + " " + (ex.moneda || "EUR")
    : "—";
  const motivo = result.reason === "file_hash"
    ? "Es exactamente el mismo archivo que escaneaste antes."
    : "Coincide emisor + número de factura + fecha con una existente.";
  const msg = `Posible duplicado.\n\n${motivo}\n\nFactura existente:\n` +
              `· N° ${ex.numero_factura || "—"}\n` +
              `· Emisor: ${ex.emisor_nombre || "—"}\n` +
              `· Fecha: ${ex.fecha_factura || "—"}\n` +
              `· Total: ${total}\n` +
              `· ID en el sistema: ${ex.id}\n\n` +
              `¿Procesarla de todas formas?`;
  return Promise.resolve(window.confirm(msg));
}

// ─── Renderizar resultado ─────────────────────────────────────────────────────
const FIELD_LABELS = {
  numero_factura:   "N° Factura",
  fecha_factura:    "Fecha",
  fecha_vencimiento:"Vencimiento",
  emisor_nombre:    "Emisor",
  emisor_nif:       "NIF Emisor",
  emisor_direccion: "Dirección Emisor",
  receptor_nombre:  "Receptor",
  receptor_nif:     "NIF Receptor",
  receptor_direccion:"Dirección Receptor",
  concepto:         "Concepto",
  base_imponible:   "Base imponible",
  porcentaje_iva:   "IVA %",
  cuota_iva:        "Cuota IVA",
  total:            "Total",
  forma_pago:       "Forma de pago",
  iban:             "IBAN",
  moneda:           "Moneda",
};

const AMOUNT_FIELDS = new Set(["base_imponible", "cuota_iva", "total", "porcentaje_iva"]);
const LONG_TEXT_FIELDS = new Set(["emisor_direccion", "receptor_direccion", "concepto"]);

function inputValueFor(key, val) {
  if (val === null || val === undefined) return "";
  if (AMOUNT_FIELDS.has(key) && typeof val === "number") {
    // Mostrar con punto decimal para que el input number lo entienda
    return String(val);
  }
  return String(val);
}

function renderResult(data, pdfUrl, invoiceId, originalFile = null) {
  resultFields.innerHTML = "";
  STATE.currentData = { ...data };
  STATE.currentInvoiceId = invoiceId ?? null;
  STATE.lastPdfUrl = pdfUrl;
  STATE.dirty = false;
  setSaveButtonState();
  setResultPreview(originalFile);

  for (const [key, label] of Object.entries(FIELD_LABELS)) {
    if (key === "moneda") continue;

    const row_ = document.createElement("div");
    row_.className = "field-row";

    const lbl = document.createElement("label");
    lbl.className = "field-label";
    lbl.textContent = label;
    lbl.setAttribute("for", `f-${key}`);

    let input;
    if (LONG_TEXT_FIELDS.has(key)) {
      input = document.createElement("textarea");
      input.rows = 2;
    } else {
      input = document.createElement("input");
      input.type = AMOUNT_FIELDS.has(key) ? "number" : "text";
      if (AMOUNT_FIELDS.has(key)) {
        input.step = "0.01";
        input.inputMode = "decimal";
      }
    }
    input.id = `f-${key}`;
    input.name = key;
    input.className = "field-input";
    input.value = inputValueFor(key, data[key]);
    input.placeholder = "—";
    input.addEventListener("input", onFieldChange);
    if (key === "total") input.classList.add("highlight");

    row_.appendChild(lbl);
    row_.appendChild(input);
    resultFields.appendChild(row_);
  }

  resultEl.style.display = "flex";
  resultEl.scrollIntoView({ behavior: "smooth" });
  showToast("Factura registrada · revisa y edita si hace falta");
}

function onFieldChange() {
  STATE.dirty = true;
  setSaveButtonState();
}

function setSaveButtonState() {
  btnSaveChanges.disabled = !STATE.dirty || !STATE.currentInvoiceId;
  btnSaveChanges.textContent = STATE.dirty ? "Guardar cambios" : "Sin cambios";
}

function collectFields() {
  const out = {};
  for (const key of Object.keys(FIELD_LABELS)) {
    if (key === "moneda") {
      out[key] = STATE.currentData?.moneda || "EUR";
      continue;
    }
    const el = $(`f-${key}`);
    if (!el) continue;
    const raw = el.value.trim();
    if (raw === "") {
      out[key] = null;
    } else if (AMOUNT_FIELDS.has(key)) {
      const n = parseFloat(raw.replace(",", "."));
      out[key] = Number.isFinite(n) ? n : null;
    } else {
      out[key] = raw;
    }
  }
  return out;
}

async function saveChanges() {
  if (!STATE.currentInvoiceId || !STATE.dirty) return;
  const payload = collectFields();
  btnSaveChanges.disabled = true;
  btnSaveChanges.textContent = "Guardando…";

  try {
    const res = await fetch(`/api/invoices/${STATE.currentInvoiceId}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        ...(STATE.accessKey ? { "X-Access-Key": STATE.accessKey } : {}),
      },
      body: JSON.stringify(payload),
    });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || "Error al guardar");

    STATE.currentData = { ...body.data };
    STATE.lastPdfUrl = body.pdf_url;
    STATE.dirty = false;
    setSaveButtonState();

    // Si estamos editando un item del lote, sincroniza la lista
    if (STATE.batch?.items?.length) {
      const it = STATE.batch.items.find((x) => x.id === STATE.currentInvoiceId);
      if (it) {
        it.data = { ...body.data };
        it.pdf_url = body.pdf_url;
        renderBatchList();
      }
    }

    showToast("Cambios guardados · PDF regenerado");
  } catch (err) {
    showToast(err.message || "Error al guardar", true);
    STATE.dirty = true;
    setSaveButtonState();
    console.error(err);
  }
}

function withKey(url) {
  return STATE.accessKey ? `${url}?key=${encodeURIComponent(STATE.accessKey)}` : url;
}

function downloadPdf(url) {
  const a = document.createElement("a");
  a.href = withKey(url);
  a.download = url.split("/").pop();
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

btnSaveChanges.addEventListener("click", saveChanges);
btnBackToBatch.addEventListener("click", backToBatch);

btnDownloadPdf.addEventListener("click", async () => {
  // Si el usuario editó pero no guardó, guardamos primero para que el PDF refleje los cambios
  if (STATE.dirty && STATE.currentInvoiceId) {
    await saveChanges();
    if (STATE.dirty) return;   // saveChanges falló → no descargar
  }
  if (STATE.lastPdfUrl) downloadPdf(STATE.lastPdfUrl);
});

// ─── Registro ─────────────────────────────────────────────────────────────────
navScan.addEventListener("click", () => setView("scan"));
navRegistry.addEventListener("click", () => setView("registry"));

function setView(view) {
  STATE.view = view;
  navScan.classList.toggle("active", view === "scan");
  navRegistry.classList.toggle("active", view === "registry");

  const scanSection = $("scan-section");
  if (view === "scan") {
    scanSection.style.display = "flex";
    registryEl.style.display = "none";
  } else {
    scanSection.style.display = "none";
    registryEl.style.display = "flex";
    loadRegistry();
  }
}

async function loadRegistry() {
  invList.innerHTML = `<span style="color:var(--text-muted);font-size:.9rem">Cargando…</span>`;

  try {
    const res = await fetch("/api/invoices", {
      headers: STATE.accessKey ? { "X-Access-Key": STATE.accessKey } : {},
    });
    const body = await res.json();
    STATE.invoicesCache = body.invoices || [];
    renderRegistry();
  } catch (err) {
    invList.innerHTML = `<span style="color:var(--error);font-size:.9rem">Error cargando el registro.</span>`;
    console.error(err);
  }
}

function renderRegistry() {
  const all = STATE.invoicesCache || [];
  if (all.length === 0) {
    invList.innerHTML = `<span style="color:var(--text-muted);font-size:.9rem">Sin facturas registradas todavía.</span>`;
    filterCount.textContent = "";
    return;
  }

  const q = (filterQ.value || "").trim().toLowerCase();
  const from = filterFrom.value || "";
  const to   = filterTo.value || "";
  const min  = filterMin.value !== "" ? parseFloat(filterMin.value) : null;
  const max  = filterMax.value !== "" ? parseFloat(filterMax.value) : null;
  const sort = filterSort.value || "recent";

  const matchText = (inv) => {
    if (!q) return true;
    const fields = [
      inv.emisor_nombre, inv.emisor_nif, inv.receptor_nombre, inv.receptor_nif,
      inv.numero_factura, inv.concepto, inv.iban,
    ];
    return fields.some((f) => f && String(f).toLowerCase().includes(q));
  };
  const matchDate = (inv) => {
    const d = inv.fecha_factura || "";
    if (from && d < from) return false;
    if (to   && d > to)   return false;
    return true;
  };
  const matchTotal = (inv) => {
    const t = inv.total != null ? Number(inv.total) : null;
    if (min !== null && (t === null || t < min)) return false;
    if (max !== null && (t === null || t > max)) return false;
    return true;
  };

  let filtered = all.filter((inv) => matchText(inv) && matchDate(inv) && matchTotal(inv));

  const cmpNum = (a, b) => (a == null ? 1 : b == null ? -1 : a - b);
  const cmpStr = (a, b) => String(a || "").localeCompare(String(b || ""));
  filtered.sort((a, b) => {
    switch (sort) {
      case "oldest":     return cmpStr(a.timestamp, b.timestamp);
      case "total_desc": return cmpNum(b.total, a.total);
      case "total_asc":  return cmpNum(a.total, b.total);
      case "fecha_desc": return cmpStr(b.fecha_factura, a.fecha_factura);
      case "fecha_asc":  return cmpStr(a.fecha_factura, b.fecha_factura);
      case "recent":
      default:           return cmpStr(b.timestamp, a.timestamp);
    }
  });

  filterCount.textContent = filtered.length === all.length
    ? `${all.length} factura${all.length === 1 ? "" : "s"}`
    : `${filtered.length} de ${all.length}`;

  if (filtered.length === 0) {
    invList.innerHTML = `<span style="color:var(--text-muted);font-size:.9rem">Ninguna factura coincide con los filtros.</span>`;
    return;
  }

  invList.innerHTML = "";
  for (const inv of filtered) {
    const card = document.createElement("div");
    card.className = "inv-card";

    const moneda = inv.moneda || "EUR";
    const total = inv.total != null
      ? Number(inv.total).toLocaleString("es-ES", { minimumFractionDigits: 2 }) + " " + moneda
      : "—";

    card.innerHTML = `
      <div class="inv-card-top">
        <span class="inv-emisor">${escapeHtml(inv.emisor_nombre || "Emisor desconocido")}</span>
        <span class="inv-total">${total}</span>
      </div>
      <div class="inv-meta">
        N° ${escapeHtml(inv.numero_factura || "—")} &nbsp;·&nbsp; ${escapeHtml(inv.fecha_factura || "—")} &nbsp;·&nbsp; ${escapeHtml(inv.timestamp || "")}
      </div>
    `;
    invList.appendChild(card);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// Listeners filtros
[filterQ, filterFrom, filterTo, filterMin, filterMax, filterSort].forEach((el) => {
  el.addEventListener("input", renderRegistry);
  el.addEventListener("change", renderRegistry);
});
btnClearFilters.addEventListener("click", () => {
  filterQ.value = "";
  filterFrom.value = "";
  filterTo.value = "";
  filterMin.value = "";
  filterMax.value = "";
  filterSort.value = "recent";
  renderRegistry();
});

// ─── Batch (lote) ────────────────────────────────────────────────────────────
function startBatch(files) {
  STATE.batch = {
    items: files.map((f) => ({ file: f, status: "pending" })),
    cancelled: false,
    running: true,
  };

  // Ocultar controles individuales y mostrar la sección batch
  dropZone.style.display = "none";
  previewWrap.style.display = "none";
  statusEl.style.display = "none";
  resultEl.style.display = "none";
  batchSection.style.display = "flex";
  batchActions.style.display = "none";
  renderBatchList();
  updateBatchProgress();
  runBatchQueue();
}

async function runBatchQueue() {
  for (let i = 0; i < STATE.batch.items.length; i++) {
    if (STATE.batch.cancelled) {
      // Marca el resto como cancelados
      for (let j = i; j < STATE.batch.items.length; j++) {
        if (STATE.batch.items[j].status === "pending") {
          STATE.batch.items[j].status = "cancelled";
        }
      }
      renderBatchList();
      break;
    }

    const item = STATE.batch.items[i];
    item.status = "processing";
    renderBatchList();

    try {
      const result = await scanFile(item.file, false);
      if (result.duplicate) {
        item.status   = "duplicate";
        item.error    = "Duplicada: ya existía";
        item.id       = result.existing?.id;
        item.data     = result.existing;     // datos completos de la factura existente
        item.pdf_url  = null;                // se regenerará al abrir detalle
      } else {
        item.status   = "done";
        item.id       = result.id;
        item.pdf_url  = result.pdf_url;
        item.data     = result.data;
      }
    } catch (err) {
      item.status = "error";
      item.error  = err.message || "Error";
    }

    renderBatchList();
    updateBatchProgress();
  }

  STATE.batch.running = false;
  // Mostrar acciones finales si hay al menos un éxito
  const anyDone = STATE.batch.items.some((it) => it.status === "done");
  batchActions.style.display = anyDone ? "flex" : "none";
  showToast("Lote terminado");
}

function renderBatchList() {
  batchList.innerHTML = "";
  STATE.batch.items.forEach((item, idx) => {
    const row = document.createElement("div");
    row.className = `batch-item batch-${item.status}`;
    const icon = {
      pending:    "⏳",
      processing: "🔄",
      done:       "✓",
      error:      "✕",
      duplicate:  "⚠",
      cancelled:  "—",
    }[item.status] || "?";
    const navigable = (item.status === "done" || item.status === "duplicate") && item.id;
    const descBase = item.data
      ? `${item.data.emisor_nombre || "—"} · ${item.data.numero_factura || "—"}`
      : (item.error || item.status);
    const desc = navigable ? `${descBase}  ›  abrir y editar` : descBase;
    row.innerHTML = `
      <span class="batch-icon">${icon}</span>
      <span class="batch-name">${escapeHtml(item.file.name)}</span>
      <span class="batch-desc">${escapeHtml(desc)}</span>
    `;
    if (navigable) {
      row.classList.add("batch-clickable");
      row.addEventListener("click", () => openBatchItem(idx));
    }
    batchList.appendChild(row);
  });
}

async function openBatchItem(idx) {
  const item = STATE.batch.items[idx];
  if (!item || !item.id) return;

  // Si es duplicate y no tenemos pdf_url, lo pedimos al servidor
  if (!item.pdf_url) {
    try {
      const res = await fetch(`/api/invoices/${item.id}`, {
        headers: STATE.accessKey ? { "X-Access-Key": STATE.accessKey } : {},
      });
      if (!res.ok) throw new Error("No se pudo cargar la factura");
      const body = await res.json();
      item.data    = body.data;
      item.pdf_url = body.pdf_url;
    } catch (err) {
      showToast(err.message || "Error abriendo la factura", true);
      return;
    }
  }

  // Mostramos el panel de resultado, ocultamos el batch
  batchSection.style.display = "none";
  btnBackToBatch.style.display = "";
  btnScanAnother.style.display = "none";
  renderResult(item.data, item.pdf_url, item.id, item.file || null);
}

function backToBatch() {
  // Si quedó algo dirty sin guardar, avisar
  if (STATE.dirty) {
    if (!window.confirm("Tienes cambios sin guardar. ¿Volver al lote y descartarlos?")) return;
  }
  resultEl.style.display = "none";
  clearResultPreview();
  btnBackToBatch.style.display = "none";
  btnScanAnother.style.display = "";
  batchSection.style.display = "flex";
  STATE.dirty = false;
  setSaveButtonState();
}

function updateBatchProgress() {
  const total = STATE.batch.items.length;
  const done  = STATE.batch.items.filter((it) => ["done", "error", "duplicate", "cancelled"].includes(it.status)).length;
  batchProgressText.textContent = `${done}/${total} procesadas`;
  batchProgressFill.style.width = total ? `${(done / total) * 100}%` : "0%";
}

btnCancelBatch.addEventListener("click", () => {
  STATE.batch.cancelled = true;
  showToast("Cancelando pendientes…");
});

btnBatchReset.addEventListener("click", () => {
  STATE.batch = { items: [], cancelled: false, running: false };
  batchSection.style.display = "none";
  resetScan();
});

btnBatchExcel.addEventListener("click", () => {
  window.open(withKey("/api/excel"), "_blank");
});

btnBatchZip.addEventListener("click", async () => {
  const ids = STATE.batch.items.filter((it) => it.status === "done" && it.id).map((it) => it.id);
  if (ids.length === 0) {
    showToast("No hay PDFs para descargar", true);
    return;
  }
  try {
    btnBatchZip.disabled = true;
    btnBatchZip.textContent = "Generando ZIP…";
    const res = await fetch("/api/pdfs/zip", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(STATE.accessKey ? { "X-Access-Key": STATE.accessKey } : {}),
      },
      body: JSON.stringify({ ids }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error generando ZIP");
    }
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `facturas_${Date.now()}.zip`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (err) {
    showToast(err.message || "Error generando ZIP", true);
    console.error(err);
  } finally {
    btnBatchZip.disabled = false;
    btnBatchZip.textContent = "Descargar todos los PDFs (ZIP)";
  }
});

btnDownloadXls.addEventListener("click", () => {
  window.open(withKey("/api/excel"), "_blank");
});

// ─── Service Worker ───────────────────────────────────────────────────────────
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(console.error);
}

// ─── Init ─────────────────────────────────────────────────────────────────────
checkAuth();
