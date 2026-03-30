const $ = (id) => document.getElementById(id);

async function runBuilder() {
  const base = $("bridge").value.trim();
  const payload = {
    builder_executable: $("exe").value.trim(),
    config_path: $("config").value.trim(),
    run_mode: $("mode").value,
  };
  const res = await fetch(`${base}/api/builder/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  $("status").textContent = data.message || "已启动";
}

async function refreshStatus() {
  const base = $("bridge").value.trim();
  const res = await fetch(`${base}/api/builder/status`);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  $("status").textContent = data.running ? "运行中" : `已结束（exit_code=${data.exit_code}）`;
  $("log").textContent = (data.logs || []).join("\n");
}

$("runBtn").addEventListener("click", async () => {
  try {
    await runBuilder();
    await refreshStatus();
  } catch (e) {
    $("status").textContent = `错误：${e.message}`;
  }
});

$("refreshBtn").addEventListener("click", async () => {
  try {
    await refreshStatus();
  } catch (e) {
    $("status").textContent = `错误：${e.message}`;
  }
});
