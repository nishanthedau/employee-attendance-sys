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
    });
    showToast("Settings saved", "ok");
  } catch (err) {
    showAlert(msgEl, "err", err.message);
  } finally {
    btn.disabled = false;
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
    document.getElementById("history-count").textContent = `${data.marked} marked`;
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
document.getElementById("refresh-btn").addEventListener("click", async (ev) => {
  const btn = ev.currentTarget;
  btn.disabled = true;
  try {
    await Promise.all([loadStats(), loadSessions(), loadSubjects(), loadFaculties(), loadStudents(), loadSettings()]);
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
    await Promise.all([loadStats(), loadSessions(), loadSubjects(), loadFaculties(), loadStudents(), loadSettings()]);
  } catch (err) {
    showToast(err.message, "err");
  }
})();
