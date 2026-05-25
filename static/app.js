const BASE = "/privacydecoder";

// ── DOM refs ──────────────────────────────────────────────────────────────
const form        = document.getElementById("analyze-form");
const urlInput    = document.getElementById("url-input");
const btn         = document.getElementById("analyze-btn");
const loading     = document.getElementById("loading");
const errorBanner = document.getElementById("error-banner");
const errorMsg    = document.getElementById("error-message");
const results     = document.getElementById("results");
const popularSec  = document.getElementById("popular-section");
const popularList = document.getElementById("popular-list");

// ── Tab switching ─────────────────────────────────────────────────────────
const tabUrl      = document.getElementById("tab-url");
const tabPdf      = document.getElementById("tab-pdf");
const urlPanel    = form;
const uploadPanel = document.getElementById("upload-panel");

tabUrl.addEventListener("click", () => {
  tabUrl.classList.add("active");
  tabPdf.classList.remove("active");
  urlPanel.classList.remove("hidden");
  uploadPanel.classList.add("hidden");
});

tabPdf.addEventListener("click", () => {
  tabPdf.classList.add("active");
  tabUrl.classList.remove("active");
  uploadPanel.classList.remove("hidden");
  urlPanel.classList.add("hidden");
});

// ── PDF upload wiring ─────────────────────────────────────────────────────
const dropZone   = document.getElementById("drop-zone");
const pdfInput   = document.getElementById("pdf-input");
const browseBtn  = document.getElementById("browse-btn");
const fileChosen = document.getElementById("file-chosen");
const fileName   = document.getElementById("file-name");
const clearBtn   = document.getElementById("clear-file-btn");
const uploadBtn  = document.getElementById("upload-btn");

let selectedFile = null;

browseBtn.addEventListener("click", () => pdfInput.click());
dropZone.addEventListener("click", (e) => { if (e.target !== browseBtn) pdfInput.click(); });

pdfInput.addEventListener("change", () => {
  if (pdfInput.files[0]) setFile(pdfInput.files[0]);
});

dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("drag-over");
});
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("drag-over");
  const f = e.dataTransfer.files[0];
  if (f && f.type === "application/pdf") setFile(f);
  else showError("Please drop a PDF file.");
});

clearBtn.addEventListener("click", clearFile);
uploadBtn.addEventListener("click", async () => { if (selectedFile) await runPdfAnalysis(selectedFile); });

function setFile(f) {
  selectedFile = f;
  fileName.textContent = f.name;
  fileChosen.classList.remove("hidden");
  uploadBtn.classList.remove("hidden");
  dropZone.style.display = "none";
}

function clearFile() {
  selectedFile = null;
  pdfInput.value = "";
  fileChosen.classList.add("hidden");
  uploadBtn.classList.add("hidden");
  dropZone.style.display = "";
}

// ── Inline scorecard (expands below the grid on card click) ──────────────
const policyDetail = document.getElementById("policy-detail");

// Short labels for the 3×4 category grid
const CAT_SHORT = {
  "Data Collection":               "Collection",
  "Data Selling":                  "Selling",
  "Third-Party Sharing":           "3rd-Pty Sharing",
  "User Profiling":                "User Profiling",
  "Third-Party Profile Access":    "Profile Access",
  "Targeted Advertising":          "Targeted Ads",
  "Data Retention":                "Data Retention",
  "Right to Delete":               "Right to Delete",
  "Government & Legal Disclosure": "Gov. Disclosure",
  "Policy Change Rights":          "Policy Changes",
  "Children's Data":               "Children's Data",
  "Sensitive Data":                "Sensitive Data",
};

let _activeCell = null;

function toggleCellDetail(cellEl, entry) {
  // Same card clicked again — collapse matrix and hide analysis
  if (_activeCell === cellEl) {
    policyDetail.classList.add("hidden");
    policyDetail.innerHTML = "";
    cellEl.classList.remove("cell-active");
    results.classList.add("hidden");
    _activeCell = null;
    return;
  }

  // Switch to new card — deactivate previous
  _activeCell?.classList.remove("cell-active");
  _activeCell = cellEl;
  cellEl.classList.add("cell-active");

  const gc = (entry.grade ?? "f").toLowerCase();

  // Build scorecard panel with loading grid
  const panel = document.createElement("div");
  panel.className = "detail-panel";

  const scoreRow = document.createElement("div");
  scoreRow.className = "detail-score-row";

  const gb = document.createElement("div");
  gb.className = `grade-badge grade-${gc}`;
  gb.style.cssText = "width:44px;height:44px;font-size:1.5rem;flex-shrink:0";
  gb.textContent = entry.grade ?? "?";

  const si = document.createElement("div");
  si.className = "detail-score-info";
  si.innerHTML = `<div class="privacy-score-num" style="font-size:1.05rem">${
    entry.privacy_score != null ? entry.privacy_score + " / 100" : "—"
  }</div><div class="privacy-score-label">${riskLabel(entry.overall_risk)}</div>`;

  const companyLabel = document.createElement("div");
  companyLabel.style.cssText = "margin-left:auto;font-weight:700;font-size:.95rem";
  companyLabel.textContent = entry.company;

  scoreRow.appendChild(gb);
  scoreRow.appendChild(si);
  scoreRow.appendChild(companyLabel);
  panel.appendChild(scoreRow);

  const grid = document.createElement("div");
  grid.className = "detail-grid";
  grid.innerHTML = '<p class="sb-loading">Loading scorecard…</p>';
  panel.appendChild(grid);

  policyDetail.innerHTML = "";
  policyDetail.appendChild(panel);
  policyDetail.classList.remove("hidden");

  // Hide any stale full analysis while the new one loads
  results.classList.add("hidden");

  // Fetch (near-instant from cache) — populate grid AND full analysis together
  fetch(`${BASE}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: entry.url }),
  })
    .then(r => r.ok ? r.json() : Promise.reject())
    .then(data => {
      // Fill category grid
      grid.innerHTML = "";
      for (const cat of data.categories) {
        const cell = document.createElement("div");
        cell.className = `sb-cell ${riskClass(cat.risk)}`;
        cell.innerHTML = `<span class="sb-cell-name">${CAT_SHORT[cat.name] ?? cat.name}</span>`;
        grid.appendChild(cell);
      }
      // Show full analysis below (renderResults scrolls it into view)
      renderResults(data);
    })
    .catch(() => {
      grid.innerHTML = '<p class="sb-loading">Could not load scorecard.</p>';
    });
}

// ── Data Collection Matrix ────────────────────────────────────────────────
const DC_CATEGORY_ICONS = {
  "Photos":       "📷",
  "Video":        "🎥",
  "Audio":        "🎙️",
  "Location":     "📍",
  "Social Graph": "👥",
  "Behavior":     "🧠",
  "Health":       "🏥",
  "Financial":    "💳",
  "Device":       "📱",
};

// Preserve insertion order from the questions list
const DC_CATEGORY_ORDER = [
  "Photos","Video","Audio","Location","Social Graph",
  "Behavior","Health","Financial","Device"
];

function dcBadge(rating) {
  const cls = { Yes:"dc-yes", No:"dc-no", Likely:"dc-likely",
                Unlikely:"dc-unlikely", Unknown:"dc-unknown" }[rating] ?? "dc-unknown";
  return `<span class="dc-badge ${cls}">${rating}</span>`;
}

function buildDataCollectionMatrix(answers) {
  const wrapper = document.createElement("div");
  wrapper.className = "dc-matrix";

  wrapper.innerHTML = `
    <div class="dc-matrix-heading">Detailed Data Collection Analysis</div>
    <p class="dc-matrix-subtext">What this company can collect and share about you, based on their stated policy</p>`;

  // Group by category, preserving order
  const groups = {};
  for (const a of answers) {
    if (!groups[a.category]) groups[a.category] = [];
    groups[a.category].push(a);
  }

  const orderedKeys = DC_CATEGORY_ORDER.filter(k => groups[k]);
  // Append any unexpected categories at the end
  for (const k of Object.keys(groups)) {
    if (!orderedKeys.includes(k)) orderedKeys.push(k);
  }

  for (const cat of orderedKeys) {
    const items = groups[cat];
    const icon  = DC_CATEGORY_ICONS[cat] ?? "";

    const groupEl = document.createElement("div");
    groupEl.className = "dc-group";

    const label = document.createElement("div");
    label.className = "dc-group-label";
    label.textContent = `${icon} ${cat}`;
    groupEl.appendChild(label);

    const table = document.createElement("table");
    table.className = "dc-table";
    table.innerHTML = `<thead><tr>
      <th class="dc-question">Question</th>
      <th class="dc-rating">Can do?</th>
      <th class="dc-rating">3rd Parties?</th>
      <th class="dc-basis">Basis</th>
    </tr></thead>`;

    const DC_ROW_CLASS = {
      Yes:"dc-row-yes", Likely:"dc-row-likely",
      Unlikely:"dc-row-unlikely", No:"dc-row-no", Unknown:"dc-row-unknown"
    };
    const tbody = document.createElement("tbody");
    for (const a of items) {
      const tr = document.createElement("tr");
      tr.className = DC_ROW_CLASS[a.can_do] ?? "dc-row-unknown";
      tr.innerHTML = `
        <td class="dc-question">${a.question}</td>
        <td class="dc-rating">${dcBadge(a.can_do)}</td>
        <td class="dc-rating">${dcBadge(a.third_party)}</td>
        <td class="dc-basis">${a.basis}</td>`;
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    groupEl.appendChild(table);
    wrapper.appendChild(groupEl);
  }

  return wrapper;
}

// ── Helpers ───────────────────────────────────────────────────────────────
function getDomain(url) {
  try { return new URL(url).hostname; }
  catch { return null; }
}

function truncate(str, n) {
  return str.length > n ? str.slice(0, n) + "…" : str;
}

// Truncate at a word boundary — never cuts mid-word
function truncateWords(str, n) {
  if (str.length <= n) return str;
  const cut = str.lastIndexOf(" ", n);
  // If no space found (first word is already longer than n), hard-cut
  return cut > 0 ? str.slice(0, cut) + "…" : str.slice(0, n) + "…";
}

function gradeClass(grade) {
  return `grade-${(grade ?? "f").toLowerCase()}`;
}

// ── Boot ──────────────────────────────────────────────────────────────────
loadPopular();

// ── URL form submit ───────────────────────────────────────────────────────
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const url = urlInput.value.trim();
  if (!url) return;
  await runAnalysis(url);
});

// ── URL Analysis ──────────────────────────────────────────────────────────
async function runAnalysis(url) {
  showLoading();
  try {
    const res = await fetch(`${BASE}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      showError(res.status === 429
        ? "Too many requests. Please wait a moment and try again."
        : data.detail || "Analysis failed. Please try again in a moment.");
      return;
    }

    const data = await res.json();
    renderResults(data);
    loadPopular();
  } catch {
    showError("We couldn't reach that URL. Check that it's correct and publicly accessible.");
  }
}

// ── PDF Analysis ──────────────────────────────────────────────────────────
async function runPdfAnalysis(file) {
  showLoading(true);
  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch(`${BASE}/analyze/upload`, {
      method: "POST",
      body: formData,
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      showError(data.detail || "Analysis failed. Please try again in a moment.");
      return;
    }

    const data = await res.json();
    renderResults(data, true);
  } catch {
    showError("Upload failed. Please try again.");
  }
}

// ── Render full analysis results ──────────────────────────────────────────
function renderResults(data, isPdf = false) {
  hideAll();
  urlInput.value = "";
  clearFile();

  document.getElementById("company-name").textContent = data.company;

  const policyLink = document.getElementById("policy-url");
  if (isPdf || (data.url && data.url.startsWith("pdf:"))) {
    policyLink.textContent = data.url.replace("pdf:", "") + " (PDF upload)";
    policyLink.removeAttribute("href");
    policyLink.style.cursor = "default";
  } else {
    policyLink.textContent = data.url;
    policyLink.href = data.url;
    policyLink.style.cursor = "";
  }

  // Document date
  const docDateRow = document.getElementById("doc-date-row");
  const docDateEl  = document.getElementById("doc-date");
  if (data.document_date) {
    docDateEl.textContent = data.document_date;
    docDateRow.classList.remove("hidden");
  } else {
    docDateRow.classList.add("hidden");
  }

  document.getElementById("analyzed-at").textContent = formatDate(data.analyzed_at);
  document.getElementById("version-num").textContent  = data.version ?? "—";
  document.getElementById("cached-badge").classList.toggle("hidden", !data.from_cache);

  // Grade + score
  const gradeBadge = document.getElementById("grade-badge");
  gradeBadge.textContent = data.grade ?? "?";
  gradeBadge.className   = `grade-badge ${gradeClass(data.grade)}`;
  document.getElementById("privacy-score").textContent =
    data.privacy_score != null ? `${data.privacy_score} / 100` : "—";
  document.getElementById("risk-label").textContent = riskLabel(data.overall_risk);

  document.getElementById("overall-summary").textContent = data.overall_summary;

  // Changes banner
  const hasChanges = data.changes_from_previous?.some(c => c.risk_changed || c.summary_changed);
  document.getElementById("changes-banner").classList.toggle("hidden", !hasChanges);

  const changeMap = {};
  if (data.changes_from_previous) {
    for (const ch of data.changes_from_previous) changeMap[ch.name] = ch;
  }

  // Category cards — collapsed accordion by default
  const container = document.getElementById("categories");
  container.innerHTML = "";

  for (const cat of data.categories) {
    const change  = changeMap[cat.name];
    const changed = change && (change.risk_changed || change.summary_changed);

    const card = document.createElement("div");
    card.className = `category-card${changed ? " changed" : ""}`;

    // Colored header bar (accordion trigger)
    const header = document.createElement("div");
    header.className = `category-header ${riskClass(cat.risk)}`;
    header.setAttribute("role", "button");
    header.setAttribute("tabindex", "0");
    header.setAttribute("aria-expanded", "false");

    const dot = document.createElement("span");
    dot.className = "risk-dot";

    const name = document.createElement("span");
    name.className = "category-name";
    name.textContent = cat.name;

    const chevron = document.createElement("span");
    chevron.className = "accordion-chevron";
    chevron.textContent = "▸";

    header.appendChild(dot);
    header.appendChild(name);

    // Show previous risk if it changed
    if (change?.risk_changed) {
      const badgeRow = document.createElement("div");
      badgeRow.className = "badge-row";
      const prev = document.createElement("span");
      prev.className = "prev-risk";
      prev.textContent = riskLabel(change.previous_risk);
      const arrow = document.createElement("span");
      arrow.className = "changed-arrow";
      arrow.textContent = "→";
      badgeRow.appendChild(prev);
      badgeRow.appendChild(arrow);
      header.appendChild(badgeRow);
    }

    header.appendChild(chevron);
    card.appendChild(header);

    // Body — hidden by default
    const body = document.createElement("div");
    body.className = "category-body hidden";

    const summary = document.createElement("p");
    summary.className = "category-summary";
    summary.textContent = cat.summary;
    body.appendChild(summary);

    if (cat.quote) {
      const toggle = document.createElement("button");
      toggle.className = "quote-toggle";
      toggle.textContent = "Show source quote ▾";

      const quoteBlock = document.createElement("blockquote");
      quoteBlock.className = "quote-block hidden";
      quoteBlock.textContent = `"${cat.quote}"`;

      toggle.addEventListener("click", () => {
        const open = !quoteBlock.classList.contains("hidden");
        quoteBlock.classList.toggle("hidden", open);
        toggle.textContent = open ? "Show source quote ▾" : "Hide source quote ▴";
      });

      body.appendChild(toggle);
      body.appendChild(quoteBlock);
    }

    // Data Collection gets the full 39-question matrix
    if (cat.name === "Data Collection" && data.data_collection_matrix?.length) {
      body.appendChild(buildDataCollectionMatrix(data.data_collection_matrix));
    }

    card.appendChild(body);

    // Accordion toggle handler
    const toggleBody = () => {
      const willOpen = body.classList.contains("hidden");
      body.classList.toggle("hidden", !willOpen);
      chevron.textContent = willOpen ? "▾" : "▸";
      header.setAttribute("aria-expanded", String(willOpen));
    };
    header.addEventListener("click", toggleBody);
    header.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleBody(); }
    });

    container.appendChild(card);
  }

  results.classList.remove("hidden");
  results.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ── Popular grid ──────────────────────────────────────────────────────────
async function loadPopular() {
  try {
    const res = await fetch(`${BASE}/popular`);
    if (!res.ok) return;
    const data = await res.json();
    if (!data.entries?.length) { popularSec.classList.add("hidden"); return; }

    // Reset any open detail panel
    _activeCell = null;
    policyDetail.classList.add("hidden");
    policyDetail.innerHTML = "";

    // Sort worst → best by privacy score (descending)
    const riskOrder = { high: 0, medium: 1, low: 2 };
    const sorted = [...data.entries].sort((a, b) => {
      if (a.privacy_score != null && b.privacy_score != null)
        return b.privacy_score - a.privacy_score;
      return (riskOrder[a.overall_risk] ?? 1) - (riskOrder[b.overall_risk] ?? 1);
    });

    popularList.innerHTML = "";
    const gridEl = document.createElement("div");
    gridEl.className = "policy-grid";

    sorted.forEach(entry => {
      const gc = (entry.grade ?? "f").toLowerCase();
      const cell = document.createElement("button");
      cell.className = `policy-cell grade-${gc}`;
      cell.title = entry.is_pdf ? entry.company + " (PDF upload)" : entry.url;
      cell.innerHTML = `
        <span class="cell-name">${truncateWords(entry.company, 12)}</span>
        <span class="cell-grade">${entry.grade ?? "?"}</span>
        <span class="cell-score">${entry.privacy_score ?? "—"}/100</span>`;

      cell.addEventListener("click", () => toggleCellDetail(cell, entry));
      gridEl.appendChild(cell);
    });

    popularList.appendChild(gridEl);
    popularSec.classList.remove("hidden");
  } catch (_) { /* non-critical */ }
}

// ── UI state helpers ──────────────────────────────────────────────────────
function showLoading(isPdf = false) {
  hideAll();
  btn.disabled = true;
  uploadBtn.disabled = true;
  loading.querySelector("p").textContent = isPdf
    ? "Extracting text from your PDF…"
    : "Reading the fine print so you don't have to…";
  loading.classList.remove("hidden");
  loading.scrollIntoView({ behavior: "smooth", block: "center" });
}

function showError(msg) {
  hideAll();
  errorMsg.textContent = msg;
  errorBanner.classList.remove("hidden");
}

function hideAll() {
  btn.disabled = false;
  uploadBtn.disabled = false;
  loading.classList.add("hidden");
  errorBanner.classList.add("hidden");
  results.classList.add("hidden");
}

function riskLabel(risk) {
  return { low: "Low Risk", medium: "Medium Risk", high: "High Risk" }[risk] ?? risk;
}

function riskClass(risk) {
  return { low: "risk-low", medium: "risk-med", high: "risk-high" }[risk] ?? "";
}

function formatDate(iso) {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch (_) { return iso; }
}
