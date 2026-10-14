const $ = (id) => document.getElementById(id);
let toastTimer;
function toast(message) {
  const el = $("toast"); el.textContent = message; el.classList.add("show");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove("show"), 3500);
}
async function api(url, options={}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok && !data.message) throw new Error("Request failed");
  return {response, data};
}
function showMessage(message) { $("sourceMessage").textContent = message; }
async function refreshStatus() {
  try {
    const {data} = await api("/api/status");
    $("systemStatus").textContent = data.running ? "Monitoring active" : "System ready";
    $("sourceTag").textContent = data.running ? data.source.toUpperCase() : "STANDBY";
    $("vehicleCount").textContent = data.vehicles ?? 0;
    $("fps").textContent = data.fps ?? 0;
    showMessage(data.message || "Ready.");
    $("videoPlaceholder").classList.toggle("hidden", !!data.running || !!data.vehicles);
    if (data.candidate) {
      $("candidateStatus").innerHTML = '<div class="event-symbol">!</div><strong>Possible event indicator</strong><span>Unverified visual heuristic. Review the video before taking any action.</span>';
    }
  } catch(e) { showMessage("Could not reach backend. Is Flask running?"); }
}
async function refreshIncidents() {
  try {
    const {data} = await api("/api/incidents");
    $("incidentCount").textContent = data.length;
    $("unverifiedCount").textContent = data.filter(x => x.status === "Unverified").length;
    if (!data.length) {
      $("incidentRows").innerHTML = '<tr><td colspan="7" class="empty-cell">No events logged yet. Use “Create demo incident” to test the workflow.</td></tr>';
      return;
    }
    $("incidentRows").innerHTML = data.map(row => {
      const score = row.confidence == null ? "—" : (Number(row.confidence)*100).toFixed(0)+"%";
      const statusClass = row.status === "Reviewed" || row.status === "Confirmed by human" ? "reviewed" : row.status === "False alarm" ? "false" : "";
      return `<tr><td>#${row.id}</td><td>${escapeHtml(row.created_at || "")}</td><td>${escapeHtml(row.source || "")}</td><td>${escapeHtml(row.event_type || "")}</td><td>${score}</td><td><span class="tag ${statusClass}">${escapeHtml(row.status || "")}</span></td><td><select class="review-select" data-id="${row.id}"><option ${row.status==="Unverified"?"selected":""}>Unverified</option><option ${row.status==="Reviewed"?"selected":""}>Reviewed</option><option ${row.status==="False alarm"?"selected":""}>False alarm</option><option ${row.status==="Confirmed by human"?"selected":""}>Confirmed by human</option></select></td></tr>`;
    }).join("");
    document.querySelectorAll(".review-select").forEach(sel => sel.addEventListener("change", async e => {
      try {
        await api(`/api/incidents/${e.target.dataset.id}/status`, {
          method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({status:e.target.value})
        });
        toast("Incident review status updated."); refreshIncidents();
      } catch(err) { toast("Could not update status."); }
    }));
  } catch(e) { $("incidentRows").innerHTML = '<tr><td colspan="7" class="empty-cell">Could not load incidents.</td></tr>'; }
}
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
}
$("startCamera").addEventListener("click", async () => {
  try {
    const {data} = await api("/api/start-camera", {method:"POST"});
    toast(data.message); if (data.ok) { $("videoPlaceholder").classList.add("hidden"); $("videoFeed").src = "/video_feed?t="+Date.now(); }
    refreshStatus();
  } catch(e) { toast(e.message); }
});
$("videoFile").addEventListener("change", async (event) => {
  const file = event.target.files[0]; if (!file) return;
  const form = new FormData(); form.append("video", file); form.append("loop", $("loopVideo").checked ? "true" : "false");
  showMessage("Uploading video…");
  try {
    const {data} = await api("/api/upload-video", {method:"POST", body:form});
    toast(data.message);
    if (data.ok) { $("videoPlaceholder").classList.add("hidden"); $("videoFeed").src = "/video_feed?t="+Date.now(); }
    refreshStatus();
  } catch(e) { toast(e.message); }
  event.target.value = "";
});
$("stopSource").addEventListener("click", async () => {
  try { const {data} = await api("/api/stop", {method:"POST"}); toast(data.message); }
  catch(e) { toast(e.message); }
});
$("testIncident").addEventListener("click", async () => {
  try { const {data} = await api("/api/test-incident", {method:"POST"}); toast(data.message); refreshIncidents(); }
  catch(e) { toast(e.message); }
});
$("refreshIncidents").addEventListener("click", refreshIncidents);
$("testEmail").addEventListener("click", async () => {
  $("emailMessage").textContent = "Checking notification configuration…";
  try {
    const {data} = await api("/api/test-notification", {method:"POST"});
    $("emailMessage").textContent = data.message; toast(data.message);
  } catch(e) { $("emailMessage").textContent = e.message; toast(e.message); }
});
refreshStatus(); refreshIncidents();
setInterval(refreshStatus, 1500);
setInterval(refreshIncidents, 10000);
