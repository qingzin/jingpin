const $ = (id) => document.getElementById(id);

async function api(path, method = "GET", body) {
  const base = $("base").value.trim();
  const res = await fetch(`${base}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function appendFilter(filters, field, op, value) {
  if (value === undefined || value === null || value === "") return;
  filters.push({ field, op, value });
}

function buildPresetFilters() {
  const filters = [];
  const weightMin = $("weightMin").value;
  const weightMax = $("weightMax").value;
  if (weightMin !== "") appendFilter(filters, "weight_kg", ">=", Number(weightMin));
  if (weightMax !== "") appendFilter(filters, "weight_kg", "<=", Number(weightMax));

  const rangeFields = [
    ["length_mm", "lengthMin", "lengthMax"],
    ["width_mm", "widthMin", "widthMax"],
    ["height_mm", "heightMin", "heightMax"],
    ["depth_mm", "depthMin", "depthMax"],
  ];
  for (const [field, minId, maxId] of rangeFields) {
    const minVal = $(minId).value;
    const maxVal = $(maxId).value;
    if (minVal !== "") appendFilter(filters, field, ">=", Number(minVal));
    if (maxVal !== "") appendFilter(filters, field, "<=", Number(maxVal));
  }

  return filters;
}

function parseExtraFilters() {
  const raw = $("filters").value.trim();
  if (!raw) return [];
  const parsed = JSON.parse(raw);
  return Array.isArray(parsed) ? parsed : [];
}

function renderRows(rows = []) {
  const tbody = $("tbody");
  tbody.innerHTML = "";
  rows.forEach((r) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.rank ?? ""}</td>
      <td>${r.score ?? ""}</td>
      <td>${r.part_name ?? ""}</td>
      <td>${r.vehicle_name ?? ""}</td>
      <td>${r.weight_kg ?? ""}</td>
      <td>${r.length_mm ?? ""}</td>
      <td>${r.width_mm ?? ""}</td>
      <td>${r.height_mm ?? ""}</td>
      <td>${r.depth_mm ?? ""}</td>
      <td>${r.level_path ?? ""}</td>
      <td>${r.pointcloud_download_url ? `<a href="${r.pointcloud_download_url}" target="_blank">下载</a>` : ""}</td>
    `;
    tbody.appendChild(tr);
  });
}

async function runSearch(path) {
  const payload = {
    query: $("query").value.trim(),
    top_k: Number($("topk").value || 20),
    filters: [...buildPresetFilters(), ...parseExtraFilters()],
  };

  const data = await api(path, "POST", payload);
  $("meta").textContent = JSON.stringify({
    mode: data.mode,
    strategy: data.strategy,
    total: data.total,
    elapsed_ms: data.elapsed_ms,
    candidate_count: data.candidate_count,
    notes: data.notes,
    request_filters: payload.filters,
  }, null, 2);
  renderRows(data.results);
}

$("healthBtn").addEventListener("click", async () => {
  try {
    const data = await api("/health");
    $("meta").textContent = JSON.stringify(data, null, 2);
    $("nlBtn").disabled = !data.nl_enabled;
  } catch (e) {
    $("meta").textContent = `错误：${e.message}`;
  }
});

$("fieldsBtn").addEventListener("click", async () => {
  try {
    const data = await api("/fields");
    $("meta").textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    $("meta").textContent = `错误：${e.message}`;
  }
});

$("searchBtn").addEventListener("click", async () => {
  try { await runSearch("/search"); } catch (e) { $("meta").textContent = `错误：${e.message}`; }
});

$("nlBtn").addEventListener("click", async () => {
  try { await runSearch("/search/nl"); } catch (e) { $("meta").textContent = `错误：${e.message}`; }
});
