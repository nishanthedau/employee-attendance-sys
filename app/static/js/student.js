const user = API.user();

async function guard() {
  if (!API.token() || !user) {
    window.location.href = "/login";
    return;
  }
  if (user.role !== "student") {
    window.location.href = "/admin";
    return;
  }
  document.getElementById("nav-user").textContent = user.name;
  document.getElementById("hello").textContent = user.name.split(" ")[0];
  document.getElementById("avatar").textContent = user.name.slice(0, 1).toUpperCase();
}

async function loadWeek() {
  const data = await API.get("/api/student/attendance/current-week");
  document.getElementById("week-range").textContent =
    `Week of ${data.week_start}`;
  const grid = document.getElementById("week-grid");
  grid.innerHTML = "";
  let total = 0;
  for (const d of data.days) {
    if (d.marked) total += 1;
    const cls = [];
    if (d.is_today) cls.push("today");
    if (d.is_future) cls.push("future");
    if (d.marked) cls.push("present");
    if (!d.is_future && !d.is_today && !d.marked) cls.push("absent");
    grid.insertAdjacentHTML(
      "beforeend",
      `<div class="day ${cls.join(" ")}">
        <div class="dow">${esc(d.weekday.slice(0, 3))}</div>
        <div class="dnum">${new Date(d.date + "T00:00:00").getDate()}</div>
        <div class="mark">${d.is_future ? "–" : d.marked ? "✓" : "✕"}</div>
        <div class="meta">${d.is_future ? "upcoming" : d.marked ? d.count + " marked" : "missed"}</div>
      </div>`
    );
  }
  const past = data.days.filter((d) => !d.is_future);
  document.getElementById("week-total").textContent =
    `${total}/${past.length} sessions marked this week`;
}

let scanner = null;

function openScan() {
  overlaysOpen("scan-overlay");
  startScanner();
}
function closeScan() {
  overlaysClose("scan-overlay");
  if (scanner) {
    scanner.stop().catch(() => {});
    scanner = null;
  }
  document.getElementById("scan-msg").classList.add("hidden");
}

function overlaysOpen(id) { document.getElementById(id).classList.add("open"); }
function overlaysClose(id) { document.getElementById(id).classList.remove("open"); }

function cameraError(e) {
  console.error("Camera start failed:", e);
  const msgEl = document.getElementById("scan-msg");
  const name = (e && (e.name || (e.error && e.error.name))) || "";
  const detail = (e && (e.message || (e.error && e.error.message))) || "";
  const raw = detail || name || (e ? JSON.stringify(e) : "");
  let msg = `Could not start the camera${raw ? ` (${raw})` : ""}.`;
  if (name === "NotAllowedError") {
    msg = "Camera permission denied. Allow camera for this site: tap the aA/lock icon by the URL → Camera → Allow, then retry.";
  } else if (name === "NotFoundError") {
    msg = "No camera found on this device. Use the manual payload box below instead.";
  } else if (name === "NotReadableError") {
    msg = "Camera is busy or unavailable (another app may be using it).";
  } else if (name === "OverconstrainedError") {
    msg = "Your camera doesn't match the requested mode. Try a fresh reload and tap Scan again.";
  }
  showAlert(msgEl, "err", msg);
}

async function startScanner() {
  const msgEl = document.getElementById("scan-msg");
  if (!window.Html5Qrcode) {
    showAlert(msgEl, "err", "QR scanner library failed to load. Use the manual payload box below.");
    return;
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    showAlert(msgEl, "err", "This browser has no camera API (camera needs HTTPS + a modern browser). Use the manual payload box below.");
    return;
  }

  // iOS quirk: the camera permission prompt must be triggered by the tap
  // gesture. html5-qrcode calls getUserMedia too late (after async setup),
  // so Safari rejects it with an anonymous error. Pre-flight the permission
  // prompt right here, inside the click handler.
  try {
    const pre = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } },
    });
    pre.getTracks().forEach((t) => t.stop());
  } catch (e) {
    cameraError(e);
    return;
  }

  try {
    // Let the overlay finish animating so the scanner container has size.
    await new Promise((r) => setTimeout(r, 120));
    const region = document.getElementById("qr-reader");
    if (!region.clientWidth || !region.clientHeight) {
      showAlert(msgEl, "err", "Scanner area has no size — resize or retry. Use the manual payload box if it persists.");
      return;
    }
    scanner = new Html5Qrcode("qr-reader");
    await scanner.start(
      { facingMode: "environment" },
      { fps: 10, qrbox: { width: 220, height: 220 } },
      (text) => processPayload(text),
      () => {}
    );
  } catch (err) {
    cameraError(err);
    if (scanner) {
      scanner.stop().catch(() => {});
      scanner = null;
    }
  }
}

async function processPayload(text) {
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    try {
      const params = new URLSearchParams(text.replace(/^.*\?/, "?"));
      payload = { session_id: Number(params.get("session_id")), qr_token: params.get("qr_token") };
    } catch {
      showToast("Invalid QR payload", "err");
      return;
    }
  }
  if (!payload.session_id || !payload.qr_token) {
    showToast("Invalid QR payload", "err");
    return;
  }
  closeScan();
  await submitScan(payload);
}

async function submitScan(payload) {
  const btn = document.getElementById("scan-btn");
  const original = btn.innerHTML;
  btn.disabled = true;
  const busy = (label) => (btn.innerHTML = `<span class="small">${label}…</span>`);
  try {
    busy("Getting location");
    const loc = await getLocation();
    busy("Marking attendance");
    const result = await API.post("/api/student/attendance/scan", {
      session_id: payload.session_id,
      qr_token: payload.qr_token,
      latitude: loc.lat,
      longitude: loc.lng,
    });
    showToast(result.message, "ok");
    await loadWeek();
  } catch (err) {
    showToast(err.message, "err");
  } finally {
    btn.disabled = false;
    btn.innerHTML = original;
  }
}

document.getElementById("scan-btn").addEventListener("click", openScan);
document.getElementById("manual-btn").addEventListener("click", () => {
  const raw = document.getElementById("manual-payload").value.trim();
  if (!raw) return;
  closeScan();
  processPayload(raw);
});

(async () => {
  await guard();
  try {
    await loadWeek();
  } catch (err) {
    showToast(err.message, "err");
  }
})();
