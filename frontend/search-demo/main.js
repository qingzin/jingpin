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
      <td>${r.level_path ?? ""}</td>
      <td>${r.pointcloud_download_url ? `<a href="${r.pointcloud_download_url}" target="_blank">下载</a>` : ""}</td>
    `;
    tbody.appendChild(tr);
  });
}

async function runSearch(path) {
  const rawFilters = $("filters").value.trim();
  let filters = [];
  if (rawFilters) filters = JSON.parse(rawFilters);

  const payload = {
    query: $("query").value.trim(),
    top_k: Number($("topk").value || 20),
    filters,
  };
  const data = await api(path, "POST", payload);
  $("meta").textContent = JSON.stringify({
    mode: data.mode,
    strategy: data.strategy,
    total: data.total,
    elapsed_ms: data.elapsed_ms,
    notes: data.notes,
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
