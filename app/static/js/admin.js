const user = API.user();

async function guard() {
  if (!API.token() || !user) {
    window.location.href = "/login";
    return;
  }
  if (user.role !== "admin") {
    window.location.href = "/student";
    return;
  }
  document.getElementById("nav-user").textContent = user.name;
  document.getElementById("avatar").textContent = user.name.slice(0, 1).toUpperCase();
  document.getElementById("today-line").textContent = `Today · ${new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}`;
}

const overlays = {
  open: (id) => document.getElementById(id).classList.add("open"),
  close: (id) => document.getElementById(id).classList.remove("open"),
};
function closeOverlay(id) { overlays.close(id); }

function openDrawer() {
  document.getElementById("create-msg").classList.add("hidden");
  overlays.open("create-drawer");
  overlays.open("create-backdrop");
}
function closeDrawer() {
  overlays.close("create-drawer");
  overlays.close("create-backdrop");
}
document.getElementById("create-backdrop").addEventListener("click", closeDrawer);

async function loadStats() {
  const s = await API.get("/api/admin/dashboard");
  const t = s.today;
  const pct = Math.min(t.percentage, 100);
  document.getElementById("metrics").innerHTML = `
    <div class="metric accent"><div class="value">${t.enrolled}</div><div class="label">Enrolled</div></div>
    <div class="metric green"><div class="value">${t.present}<small> / ${t.enrolled}</small></div><div class="label">Present today</div></div>
    <div class="metric red"><div class="value">${t.absent}</div><div class="label">Absent today</div></div>
    <div class="metric">
      <div class="value">${t.percentage}<small>%</small></div>
      <div class="label">Attendance today</div>
      <div class="bar mt-8"><i style="width: ${pct}%"></i></div>
    </div>
    <div class="metric"><div class="value">${t.sessions}</div><div class="label">Sessions today</div></div>
  `;
}

async function loadSessions() {
  const date = document.getElementById("filter-date").value;
  const subject = document.getElementById("filter-subject").value;
  const faculty = document.getElementById("filter-faculty").value;
  const params = new URLSearchParams();
  if (date) params.set("session_date", date);
  if (subject) params.set("subject", subject);
  if (faculty) params.set("faculty", faculty);
  const data = await API.get(`/api/admin/sessions?${params.toString()}`);
  const sessions = data.sessions || [];
  const body = document.getElementById("sessions-body");
  body.innerHTML = sessions.length
    ? ""
    : `<tr><td colspan="7" class="center muted">No sessions found</td></tr>`;
  for (const s of sessions) {
    const live = s.live === true;
    const status = live ? `<span class="pill-live">live</span>` : `<span class="pill-dead">expired</span>`;
    body.insertAdjacentHTML(
      "beforeend",
      `<tr>
        <td style="font-weight:600;">${esc(s.subject)}</td>
        <td class="muted">${esc(s.faculty)}</td>
        <td>${fmtDate(s.date)}</td>
        <td class="num">${s.start_time} – ${s.end_time}</td>
        <td class="num">${s.marked}</td>
        <td>${status}</td>
        <td class="actions">
          <button class="btn ghost sm" onclick="showQr(${s.id}, '${esc(s.subject)}')">QR</button>
          <button class="btn ghost sm" onclick="showHistory(${s.id})">View</button>
        </td>
      </tr>`
    );
  }
}

async function loadSubjects() {
  try {
    const data = await API.get("/api/admin/subjects");
    const sel = document.getElementById("filter-subject");
    for (const s of data.subjects) {
      const opt = document.createElement("option");
      opt.value = s;
      opt.textContent = s;
      sel.appendChild(opt);
    }
  } catch {}
}

async function loadFaculties() {
  try {
    const data = await API.get("/api/admin/faculties");
    const sel = document.getElementById("filter-faculty");
    for (const f of data.faculties) {
      const opt = document.createElement("option");
      opt.value = f;
      opt.textContent = f;
      sel.appendChild(opt);
    }
  } catch {}
}

async function loadStudents() {
  const q = document.getElementById("student-search").value.trim();
  const students = await API.get(`/api/admin/students?q=${encodeURIComponent(q)}`);
  const el = document.getElementById("students-list");
  document.getElementById("students-count").textContent = `${students.length} employee${students.length === 1 ? "" : "s"}`;
  el.innerHTML = students.length
    ? students
        .map(
          (s) =>
            `<div class="flex between" style="padding: 6px 0;">
              <span><span style="font-weight:600;">${esc(s.name)}</span> <span class="faint small">${esc(s.email)}</span></span>
              <span class="flex">
                <button class="btn ghost sm" onclick="showCode(${s.id}, '${esc(s.name)}')">Code</button>
                <button class="icon-btn sm" title="Remove ${esc(s.name)}" onclick="removeStudent(${s.id}, this)">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </button>
              </span>
            </div>`
        )
        .join("")
    : "No employees found";
}

async function addStudent(e) {
  e.preventDefault();
  const form = e.target;
  const msgEl = document.getElementById("students-msg");
  msgEl.classList.add("hidden");
  try {
    await API.post("/api/admin/students", {
      name: form.name.value.trim(),
      email: form.email.value.trim(),
      password: form.password.value,
    });
    form.reset();
    showToast("Employee added", "ok");
    await loadStudents();
  } catch (err) {
    showAlert(msgEl, "err", err.message);
  }
}

async function removeStudent(id, btn) {
  if (!confirm("Remove this employee? Their attendance records will be deleted.")) return;
  btn.disabled = true;
  try {
    await API.request("DELETE", `/api/admin/students/${id}`);
    showToast("Employee removed", "ok");
    await loadStudents();
  } catch (err) {
    showToast(err.message, "err");
    btn.disabled = false;
  }
}

async function loadSettings() {
  try {
    const s = await API.get("/api/admin/settings");
    document.getElementById("settings-mode").value = s.verification_mode;
    document.getElementById("settings-radius").value = s.default_radius_meters;
    document.getElementById("settings-sheets").checked = !!s.sheets_enabled;
  } catch {}
}

async function saveSettings() {
  const btn = document.getElementById("save-settings-btn");
  const msgEl = document.getElementById("settings-msg");
  msgEl.classList.add("hidden");
  btn.disabled = true;
  try {
    await API.put("/api/admin/settings", {
      verification_mode: document.getElementById("settings-mode").value,
      default_radius_meters: parseInt(document.getElementById("settings-radius").value, 10),
      sheets_enabled: document.getElementById("settings-sheets").checked,
    });
    showToast("Settings saved", "ok");
  } catch (err) {
    showAlert(msgEl, "err", err.message);
  } finally {
    btn.disabled = false;
  }
}

async function syncSheetsNow() {
  const btn = document.getElementById("sheets-sync-btn");
  btn.disabled = true;
  try {
    const r = await API.post("/api/admin/sheets/sync");
    const s = r.summary;
    showToast(`Sheets: ${s.synced} synced, ${s.retryable} retrying, ${s.failed} failed`, "ok");
  } catch (err) {
    showToast(err.message, "err");
  } finally {
    btn.disabled = false;
  }
}

async function loadSheetsQueue() {
  const body = document.getElementById("sheets-queue-body");
  const empty = document.getElementById("sheets-queue-empty");
  const rows = (await API.get("/api/admin/sheets/queue")).entries;
  body.innerHTML = "";
  empty.classList.toggle("hidden", rows.length > 0);
  for (const e of rows) {
    const tr = document.createElement("tr");
    const statusBadge = `<span class="pill ${e.status === "synced" ? "ok" : e.status === "failed" ? "err" : "off"}">${esc(e.status)}</span>`;
    tr.innerHTML = [
      `<td>${esc(e.subject)}</td>`,
      `<td>${fmtDate(e.date)}</td>`,
      `<td>${statusBadge}</td>`,
      `<td>${e.attempts}</td>`,
      `<td>${e.next_attempt_at ? new Date(e.next_attempt_at).toLocaleString("en-IN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}</td>`,
      `<td class="faint small">${esc(e.last_error || "—")}</td>`,
    ].join("");
    body.appendChild(tr);
  }
}

// ---------- Verification codes ----------
let codeStudent = null;

async function showCode(id, name) {
  document.getElementById("code-view-name").textContent = name;
  document.getElementById("code-msg").classList.add("hidden");
  document.getElementById("code-input").value = "";
  overlays.open("code-overlay");
  try {
    const data = await API.get(`/api/admin/students/${id}/code`);
    codeStudent = { id, name };
    document.getElementById("code-current").textContent =
      data.code ? `Current code: ${data.code}` : "No code assigned yet.";
  } catch (err) {
    showAlert(document.getElementById("code-msg"), "err", err.message);
  }
}

async function saveCode() {
  const btn = document.getElementById("code-save-btn");
  const msgEl = document.getElementById("code-msg");
  msgEl.classList.add("hidden");
  if (!codeStudent) return;
  btn.disabled = true;
  try {
    const code = document.getElementById("code-input").value.trim();
    const data = await API.put(`/api/admin/students/${codeStudent.id}/code`, { code });
    document.getElementById("code-input").value = "";
    document.getElementById("code-current").textContent = `Current code: ${data.code}`;
    showToast(`Code for ${codeStudent.name} updated`, "ok");
  } catch (err) {
    showAlert(msgEl, "err", err.message);
  } finally {
    btn.disabled = false;
  }
}

async function regenerateCode() {
  if (!codeStudent) return;
  const msgEl = document.getElementById("code-msg");
  msgEl.classList.add("hidden");
  const btn = document.getElementById("code-regenerate-btn");
  btn.disabled = true;
  try {
    const data = await API.put(`/api/admin/students/${codeStudent.id}/code`, {});
    document.getElementById("code-input").value = "";
    document.getElementById("code-current").textContent = `Current code: ${data.code}`;
    showToast(`New code for ${codeStudent.name}: ${data.code}`, "ok");
  } catch (err) {
    showAlert(msgEl, "err", err.message);
  } finally {
    btn.disabled = false;
  }
}

// ---------- QR ----------
let qrTimer = null;

function showQr(id, subject) {
  clearInterval(qrTimer);
  const img = document.getElementById("qr-image");
  const meta = document.getElementById("qr-meta");
  const status = document.getElementById("qr-status");
  const countdown = document.getElementById("qr-countdown");
  meta.textContent = `Session #${id} · ${subject}`;

  const paint = (live, deadline) => {
    loadQrImage(id, img).catch((e) => {
      status.className = "pill-dead";
      status.textContent = "unavailable";
      countdown.textContent = e.message;
    });
    if (live && deadline && new Date(deadline) > new Date()) {
      status.className = "pill-live";
      status.textContent = "live";
      qrTimer = setInterval(() => {
        const left = new Date(deadline) - Date.now();
        if (left <= 0) {
          clearInterval(qrTimer);
          status.className = "pill-dead";
          status.textContent = "expired";
          countdown.textContent = "Session closed — create a new session";
          return;
        }
        const m = Math.floor(left / 60000);
        const s = Math.floor((left % 60000) / 1000);
        countdown.textContent = `Expires in ${m}m ${s}s`;
      }, 1000);
    } else {
      status.className = "pill-dead";
      status.textContent = "expired";
      countdown.textContent = "Session closed — create a new session";
    }
  };

  // Re-query the session so live/deadline are fresh when reopening a row.
  // NOTE: never send empty query params — FastAPI 422s on empty date strings.
  API.get("/api/admin/sessions").then((data) => {
    const sessions = data.sessions || [];
    const s = sessions.find((x) => x.id === id);
    paint(s ? s.live === true : false, s ? s.deadline : null);
  }).catch(() => paint(false, null));

  overlays.open("qr-overlay");
}

// ---------- History ----------
function showHistory(id) {
  API.get(`/api/admin/attendance/history?session_id=${id}`).then((data) => {
    document.getElementById("history-title").textContent = `${data.session.subject} · ${data.session.faculty}`;
    document.getElementById("history-count").textContent = `${data.marked} marked · ${data.absent_count} absent of ${data.enrolled}`;
    const body = document.getElementById("history-body");
    body.innerHTML = data.records.length
      ? ""
      : `<tr><td colspan="4" class="center muted">No attendance marked yet</td></tr>`;
    for (const r of data.records) {
      const selfie = r.has_selfie
        ? `<button class="btn ghost sm" onclick="viewSelfie(${r.id}, '${esc(r.student_name)}')">View</button>`
        : `<span class="faint small">—</span>`;
      body.insertAdjacentHTML(
        "beforeend",
        `<tr>
          <td style="font-weight:600;">${esc(r.student_name)}</td>
          <td class="num muted">${r.scan_time}</td>
          <td><span class="pill ok">${r.status}</span></td>
          <td>${selfie}</td>
        </tr>`
      );
    }
    const absentBody = document.getElementById("history-absent-body");
    absentBody.innerHTML = data.absent.length
      ? ""
      : `<tr><td colspan="2" class="center muted">Everyone is present</td></tr>`;
    for (const a of data.absent) {
      absentBody.insertAdjacentHTML(
        "beforeend",
        `<tr><td style="font-weight:600;">${esc(a.name)}</td><td class="muted small">${esc(a.email)}</td></tr>`
      );
    }
    document.getElementById("history-qr-btn").onclick = () => showQr(id, data.session.subject);
    overlays.open("history-overlay");
  }).catch((e) => showToast(e.message, "err"));
}

function viewSelfie(recordId, name) {
  document.getElementById("selfie-view-name").textContent = name;
  const img = document.getElementById("selfie-view-img");
  API.fetchBlob(`/api/admin/selfie/${recordId}`).then((blob) => {
    if (img._objUrl) URL.revokeObjectURL(img._objUrl);
    img._objUrl = URL.createObjectURL(blob);
    img.src = img._objUrl;
    overlays.open("selfie-overlay");
  }).catch((e) => showToast(e.message, "err"));
}

// ---------- Geofence map ----------
let geofenceMap = null;
let geofenceLayer = null;

function initGeofenceMap() {
  if (geofenceMap || typeof L === "undefined") return;
  geofenceMap = L.map("geofence-map", { zoomControl: true }).setView([20, 78], 5);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(geofenceMap);
  geofenceLayer = L.layerGroup().addTo(geofenceMap);
}

function scoreColor(score) {
  if (score <= 0) return "#22c55e";
  if (score < 40) return "#f59e0b";
  return "#ef4444";
}

async function loadGeofence() {
  initGeofenceMap();
  const status = document.getElementById("geofence-status");
  try {
    const data = await API.get("/api/admin/geofence/live");
    const n = (x) => (x === 1 ? "" : "s");
    status.textContent = `Last ${data.cutoff_minutes} min · ${data.sessions.length} session${n(data.sessions.length)} · ${data.scans.length} scan${n(data.scans.length)} · ${data.rejections.length} rejection${n(data.rejections.length)}`;
    if (!geofenceMap) {
      status.textContent = "Map library blocked — geofence disabled (check network/CDN)";
      return;
    }
    geofenceLayer.clearLayers();
    const bounds = [];
    for (const s of data.sessions) {
      const circle = L.circle([s.latitude, s.longitude], {
        radius: s.radius_meters,
        color: s.live ? "#6366f1" : "#9ca3af",
        weight: 1.5,
        fillColor: s.live ? "#6366f1" : "#9ca3af",
        fillOpacity: s.live ? 0.12 : 0.05,
      }).addTo(geofenceLayer);
      circle.bindPopup(
        `<h4>${esc(s.subject)}</h4><span class="lbl">${esc(s.faculty)}</span><br>` +
          `${esc(s.start_time)}–${esc(s.end_time)} · ${s.marked} marked<br>${s.live ? "● Live" : "Closed"}`
      );
      bounds.push([s.latitude, s.longitude]);
    }
    for (const r of data.scans) {
      const color = scoreColor(r.anomaly_score);
      const icon = L.divIcon({
        className: "",
        html: `<div style="width:16px;height:16px;border-radius:50%;background:${color};border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4);"></div>`,
        iconSize: [16, 16],
        iconAnchor: [8, 8],
      });
      const m = L.marker([r.latitude, r.longitude], { icon }).addTo(geofenceLayer);
      const flags = Object.keys(r.flags).length
        ? Object.entries(r.flags).map(([k, v]) => `${k}: ${esc(v)}`).join("<br>")
        : "—";
      const scoreCls = r.anomaly_score <= 0 ? "ok" : r.anomaly_score < 40 ? "warn" : "";
      m.bindPopup(
        `<h4>${esc(r.employee)}</h4><span class="lbl">${esc(r.session_subject)}</span><br>` +
          `${esc(r.scan_time)}${r.os ? " · " + esc(r.os) : ""}<br>` +
          `Anomaly: <b class="score ${scoreCls}">${r.anomaly_score}</b><br><span class="lbl">${flags}</span>`
      );
      bounds.push([r.latitude, r.longitude]);
    }
    for (const a of data.rejections) {
      const icon = L.divIcon({
        className: "",
        html: `<div style="width:14px;height:14px;border-radius:50%;background:transparent;border:2px solid #ef4444;color:#ef4444;font-weight:800;font-size:10px;line-height:12px;text-align:center;">✕</div>`,
        iconSize: [14, 14],
        iconAnchor: [7, 7],
      });
      const m = L.marker([a.latitude, a.longitude], { icon }).addTo(geofenceLayer);
      m.bindPopup(
        `<h4>${esc(a.employee)}</h4><span class="lbl">Rejected</span><br>${esc(a.reason || "—")}<br>${esc(a.attempted_at)}`
      );
      bounds.push([a.latitude, a.longitude]);
    }
    if (bounds.length) geofenceMap.fitBounds(bounds, { padding: [30, 30], maxZoom: 15 });
    else geofenceMap.setView([20, 78], 5);
  } catch (err) {
    status.textContent = "Geofence data unavailable";
  }
}

// ---------- Audit ----------
function scorePill(score) {
  if (score <= 0) return `<span class="pill ok">0</span>`;
  if (score < 40) return `<span class="pill warn">${score}</span>`;
  return `<span class="pill bad">${score}</span>`;
}

function flagList(flags) {
  return flags && Object.keys(flags).length
    ? Object.entries(flags).map(([k, v]) => `${k}: ${esc(v)}`).join("<br>")
    : "—";
}

async function loadAudit() {
  const params = new URLSearchParams();
  if (document.getElementById("audit-flagged").checked) params.set("min_anomaly", "1");
  if (document.getElementById("audit-unreviewed").checked) params.set("unreviewed_only", "true");
  const rows = await API.get(`/api/admin/audit/records?${params.toString()}`);
  const body = document.getElementById("audit-body");
  body.innerHTML = rows.length ? "" : `<tr><td colspan="8" class="center muted">No records</td></tr>`;
  for (const r of rows) {
    const loc = [r.city, r.region, r.country].filter(Boolean).join(", ") || "—";
    const verify = r.verification_method_used || "—";
    const device = [r.os, r.browser, r.device_model].filter(Boolean).join(" · ") || "—";
    const status = r.reviewed
      ? `<span class="pill info">reviewed</span>`
      : `<button class="btn ghost sm" onclick="reviewRecord(${r.id})">Review</button>`;
    body.insertAdjacentHTML(
      "beforeend",
      `<tr>
        <td class="num muted small">${esc(r.scan_time)}</td>
        <td style="font-weight:600;">${esc(r.employee.name)}</td>
        <td class="muted small">${esc(r.session.subject)} · ${fmtDate(r.session.date)}</td>
        <td class="small">${esc(verify)}${r.code_verified ? " ✓" : ""}</td>
        <td class="small">${esc(device)}</td>
        <td class="small muted" title="${esc(r.ip || "")}${r.isp ? " · " + esc(r.isp) : ""}">${esc(loc)}</td>
        <td>${scorePill(r.anomaly_score)}</td>
        <td class="small">${status}
          <div class="faint" style="font-size:11px;">${flagList(r.anomaly_flags)}</div>
        </td>
      </tr>`
    );
  }
}

async function loadAttempts() {
  const rows = await API.get("/api/admin/audit/attempts?limit=50");
  const body = document.getElementById("attempts-body");
  body.innerHTML = rows.length ? "" : `<tr><td colspan="6" class="center muted">No attempts yet</td></tr>`;
  for (const a of rows) {
    const outcome =
      a.outcome === "success"
        ? `<span class="pill ok">ok</span>`
        : `<span class="pill bad">${esc(a.outcome)}</span>`;
    const reason = a.fail_reason ? `<span class="muted small">${esc(a.fail_reason)}</span>` : "—";
    body.insertAdjacentHTML(
      "beforeend",
      `<tr>
        <td class="num muted small">${esc(a.attempted_at)}</td>
        <td>${esc(a.employee.name)}</td>
        <td>${outcome}</td>
        <td>${reason}</td>
        <td class="muted small">${esc(a.method || "—")}</td>
        <td class="muted small">${esc(a.ip || "—")}</td>
      </tr>`
    );
  }
}

async function loadActivity() {
  const rows = await API.get("/api/admin/audit/log?limit=50");
  const body = document.getElementById("activity-body");
  body.innerHTML = rows.length ? "" : `<tr><td colspan="5" class="center muted">No activity yet</td></tr>`;
  for (const e of rows) {
    const detail = e.details ? JSON.stringify(e.details) : "";
    body.insertAdjacentHTML(
      "beforeend",
      `<tr>
        <td class="num muted small">${esc(e.created_at)}</td>
        <td>${esc(e.actor || "—")}</td>
        <td class="small">${esc(e.action)}</td>
        <td class="muted small">${esc(detail)}</td>
        <td class="muted small">${esc(e.ip || "—")}</td>
      </tr>`
    );
  }
}

async function reviewRecord(id) {
  try {
    await API.post(`/api/admin/audit/records/${id}/review`);
    showToast("Marked as reviewed", "ok");
    await loadAudit();
  } catch (err) {
    showToast(err.message, "err");
  }
}

// ---------- Create ----------
async function handleCreate(e) {
  e.preventDefault();
  const msgEl = document.getElementById("create-msg");
  msgEl.classList.add("hidden");
  const btn = document.getElementById("create-submit");
  btn.disabled = true;
  const f = e.target;
  const payload = {
    subject: f.subject.value.trim(),
    faculty: f.faculty.value.trim(),
    date: f.date.value,
    start_time: f.start_time.value + ":00",
    end_time: f.end_time.value + ":00",
    latitude: parseFloat(f.latitude.value),
    longitude: parseFloat(f.longitude.value),
    radius_meters: parseInt(f.radius_meters.value, 10),
    qr_expiry_minutes: parseInt(f.qr_expiry_minutes.value, 10),
  };
  try {
    const session = await API.post("/api/admin/attendance/create", payload);
    closeDrawer();
    f.reset();
    f.latitude.value = "";
    f.longitude.value = "";
    await Promise.all([loadStats(), loadSessions(), loadSubjects()]);
    showQr(session.id, session.subject);
    showToast(`Session "${session.subject}" created`, "ok");
  } catch (err) {
    showAlert(msgEl, "err", err.message);
  } finally {
    btn.disabled = false;
  }
}

async function useCurrentLocation() {
  try {
    const loc = await getLocation();
    document.querySelector('[name="latitude"]').value = loc.lat;
    document.querySelector('[name="longitude"]').value = loc.lng;
  } catch (err) {
    showAlert(document.getElementById("create-msg"), "err", err.message);
  }
}

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

document.getElementById("create-btn").addEventListener("click", openDrawer);
document.getElementById("save-settings-btn").addEventListener("click", saveSettings);
document.getElementById("sheets-sync-btn").addEventListener("click", syncSheetsNow);
document.getElementById("sheets-queue-refresh-btn").addEventListener("click", loadSheetsQueue);
document.getElementById("refresh-btn").addEventListener("click", async (ev) => {
  const btn = ev.currentTarget;
  btn.disabled = true;
  try {
    await Promise.all([loadStats(), loadSessions(), loadSubjects(), loadFaculties(), loadStudents(), loadSettings(), loadAudit(), loadAttempts(), loadActivity(), loadGeofence(), loadSheetsQueue()]);
    showToast("Refreshed", "ok");
  } catch (err) {
    showToast(err.message, "err");
  } finally {
    btn.disabled = false;
  }
});
document.getElementById("create-form").addEventListener("submit", handleCreate);
document.getElementById("add-student-form").addEventListener("submit", addStudent);
document.getElementById("filter-btn").addEventListener("click", loadSessions);
document.getElementById("audit-refresh-btn").addEventListener("click", () =>
  Promise.all([loadAudit(), loadAttempts(), loadActivity()])
);
document.getElementById("geofence-refresh-btn").addEventListener("click", loadGeofence);
["audit-flagged", "audit-unreviewed"].forEach((id) =>
  document.getElementById(id).addEventListener("change", loadAudit)
);
document.getElementById("export-btn").addEventListener("click", async (ev) => {
  const btn = ev.currentTarget;
  btn.disabled = true;
  try {
    const date = document.getElementById("filter-date").value;
    const subject = document.getElementById("filter-subject").value;
    const faculty = document.getElementById("filter-faculty").value;
    const params = new URLSearchParams();
    if (date) params.set("session_date", date);
    if (subject) params.set("subject", subject);
    if (faculty) params.set("faculty", faculty);
    const blob = await API.fetchBlob(`/api/admin/export?${params.toString()}`);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "attendance_export.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showToast("Export downloaded", "ok");
  } catch (err) {
    showToast(err.message, "err");
  } finally {
    btn.disabled = false;
  }
});
document.getElementById("student-search").addEventListener("input", debounce(loadStudents, 300));

(async () => {
  await guard();
  try {
    await Promise.all([loadStats(), loadSessions(), loadSubjects(), loadFaculties(), loadStudents(), loadSettings(), loadAudit(), loadAttempts(), loadActivity(), loadGeofence(), loadSheetsQueue()]);
  } catch (err) {
    showToast(err.message, "err");
  }
})();

setInterval(loadGeofence, 30000);
