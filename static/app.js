"use strict";

// ─── Estado ─────────────────────────────────────────────────────────────────
const STATE = {
  accessKey: localStorage.getItem("ocr_access_key") || "",
  currentFile: null,
  lastPdfUrl: null,
  view: "scan",          // "scan" | "registry"
};

// ─── DOM ─────────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const authScreen    = $("auth-screen");
const pinInput      = $("pin-input");
const btnAuthOk     = $("btn-auth-ok");
const mainContent   = $("main-content");
const dropZone      = $("drop-zone");
const fileInput     = $("file-input");
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
const btnScanAnother= $("btn-scan-another");
const registryEl    = $("registry");
const invList       = $("inv-list");
const btnDownloadXls= $("btn-download-xls");
const navScan       = $("nav-scan");
const navRegistry   = $("nav-registry");
const toast         = $("toast");

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

fileInput.addEventListener("change", () => handleFile(fileInput.files[0]));

// Drag & drop
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
  fileInput.value = "";
  previewImg.src = "";
  dropZone.style.display = "block";
  previewWrap.style.display = "none";
  statusEl.style.display = "none";
  resultEl.style.display = "none";
}

// ─── Procesar factura ─────────────────────────────────────────────────────────
btnProcess.addEventListener("click", processInvoice);
btnScanAnother.addEventListener("click", resetScan);

async function processInvoice() {
  if (!STATE.currentFile) return;

  // Mostrar estado
  previewWrap.style.display = "none";
  resultEl.style.display = "none";
  statusEl.style.display = "flex";
  statusText.textContent = "Enviando imagen…";
  btnProcess.disabled = true;

  try {
    const form = new FormData();
    form.append("file", STATE.currentFile);

    statusText.textContent = "Extrayendo datos con IA…";
    const res = await fetch("/api/scan", {
      method: "POST",
      headers: STATE.accessKey ? { "X-Access-Key": STATE.accessKey } : {},
      body: form,
    });

    if (res.status === 401) {
      STATE.accessKey = "";
      localStorage.removeItem("ocr_access_key");
      showAuthScreen();
      return;
    }

    const body = await res.json();
    if (!res.ok) {
      throw new Error(body.detail || "Error desconocido");
    }

    statusEl.style.display = "none";
    renderResult(body.data, body.pdf_url, body.row);

  } catch (err) {
    statusEl.style.display = "none";
    previewWrap.style.display = "flex";
    showToast(err.message || "Error al procesar la factura", true);
    console.error(err);
  } finally {
    btnProcess.disabled = false;
  }
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

const AMOUNT_FIELDS = new Set(["base_imponible", "cuota_iva", "total"]);

function fmtValue(key, val, moneda) {
  if (val === null || val === undefined || val === "") return null;
  if (AMOUNT_FIELDS.has(key) && typeof val === "number") {
    return val.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " " + (moneda || "EUR");
  }
  if (key === "porcentaje_iva" && typeof val === "number") {
    return val + "%";
  }
  return String(val);
}

function renderResult(data, pdfUrl, row) {
  const moneda = data.moneda || "EUR";
  resultFields.innerHTML = "";

  for (const [key, label] of Object.entries(FIELD_LABELS)) {
    if (key === "moneda") continue;
    const val = fmtValue(key, data[key], moneda);
    const row_ = document.createElement("div");
    row_.className = "field-row";

    const lbl = document.createElement("span");
    lbl.className = "field-label";
    lbl.textContent = label;

    const vl = document.createElement("span");
    vl.className = "field-value";
    if (val === null) {
      vl.classList.add("null-val");
      vl.textContent = "—";
    } else {
      vl.textContent = val;
      if (key === "total") vl.classList.add("highlight");
    }

    row_.appendChild(lbl);
    row_.appendChild(vl);
    resultFields.appendChild(row_);
  }

  STATE.lastPdfUrl = pdfUrl;
  resultEl.style.display = "flex";
  resultEl.scrollIntoView({ behavior: "smooth" });
  showToast(`Factura registrada correctamente (fila ${row})`);

  // Descarga automática del PDF
  if (pdfUrl) downloadPdf(pdfUrl);
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

btnDownloadPdf.addEventListener("click", () => {
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

    if (!body.invoices || body.invoices.length === 0) {
      invList.innerHTML = `<span style="color:var(--text-muted);font-size:.9rem">Sin facturas registradas todavía.</span>`;
      return;
    }

    invList.innerHTML = "";
    // Más recientes primero
    const invoices = [...body.invoices].reverse();
    for (const inv of invoices) {
      const card = document.createElement("div");
      card.className = "inv-card";

      const moneda = inv.moneda || "EUR";
      const total = inv.total != null
        ? Number(inv.total).toLocaleString("es-ES", { minimumFractionDigits: 2 }) + " " + moneda
        : "—";

      card.innerHTML = `
        <div class="inv-card-top">
          <span class="inv-emisor">${inv.emisor_nombre || "Emisor desconocido"}</span>
          <span class="inv-total">${total}</span>
        </div>
        <div class="inv-meta">
          N° ${inv.numero_factura || "—"} &nbsp;·&nbsp; ${inv.fecha_factura || "—"} &nbsp;·&nbsp; ${inv.timestamp || ""}
        </div>
      `;
      invList.appendChild(card);
    }
  } catch (err) {
    invList.innerHTML = `<span style="color:var(--error);font-size:.9rem">Error cargando el registro.</span>`;
    console.error(err);
  }
}

btnDownloadXls.addEventListener("click", () => {
  window.open(withKey("/api/excel"), "_blank");
});

// ─── Service Worker ───────────────────────────────────────────────────────────
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(console.error);
}

// ─── Init ─────────────────────────────────────────────────────────────────────
checkAuth();
