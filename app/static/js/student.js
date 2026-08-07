const user = API.user();
const SELFIE_PAYLOAD = "_scanPayload";
const SELFIE_BLOB = "_selfieBlob";

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
  showStep("qr");
  overlaysOpen("scan-overlay");
  startScanner();
}
function openSelfieOnly() {
  showStep("pick");
  overlaysOpen("scan-overlay");
  loadLiveSessions();
}
function closeScan() {
  overlaysClose("scan-overlay");
  stopScanner();
  stopSelfieStream();
  resetSelfieUi();
}

function overlaysOpen(id) { document.getElementById(id).classList.add("open"); }
function overlaysClose(id) { document.getElementById(id).classList.remove("open"); }

async function stopScanner() {
  if (scanner) {
    const s = scanner;
    scanner = null;
    try {
      await s.stop();
    } catch {}
  }
}

function showStep(step) {
  const titles = { qr: "Scan QR", pick: "Mark with Selfie", selfie: "Confirm identity" };
  document.getElementById("scan-title").textContent = titles[step] || "Confirm";
  document.getElementById("qr-step").classList.toggle("hidden", step !== "qr");
  document.getElementById("pick-step").classList.toggle("hidden", step !== "pick");
  document.getElementById("selfie-step").classList.toggle("hidden", step !== "selfie");
}

async function loadLiveSessions() {
  const list = document.getElementById("live-sessions-list");
  const msgEl = document.getElementById("pick-msg");
  msgEl.classList.add("hidden");
  list.innerHTML = "";
  try {
    const data = await API.get("/api/student/attendance/live-sessions");
    const sessions = data.sessions || [];
    if (!sessions.length) {
      showAlert(msgEl, "info", "No classes are open right now. Use Scan QR or try again during class time.");
      return;
    }
    for (const s of sessions) {
      const b = document.createElement("button");
      b.type = "button";
      b.innerHTML = `
        <span><span class="s-subject">${esc(s.subject)}</span>
        <div class="s-meta">${esc(s.faculty)} · ${s.start_time} – ${s.end_time}</div></span>
        <span class="faint small">Mark</span>`;
      b.addEventListener("click", () => {
        window[SELFIE_PAYLOAD] = { session_id: s.id, qr_token: null };
        openSelfie();
      });
      list.appendChild(b);
    }
  } catch (err) {
    showAlert(msgEl, "err", err.message);
  }
}

function cameraError(e, msgEl) {
  console.error("Camera start failed:", e);
  const name = (e && (e.name || (e.error && e.error.name))) || "";
  const detail = (e && (e.message || (e.error && e.error.message))) || "";
  const raw = detail || name || (e ? JSON.stringify(e) : "");
  let msg = `Could not start the camera${raw ? ` (${raw})` : ""}.`;
  if (name === "NotAllowedError") {
    msg = "Camera permission denied. Allow camera for this site: tap the aA/lock icon by the URL → Camera → Allow, then retry.";
  } else if (name === "NotFoundError") {
    msg = "No camera found on this device. Use the manual payload box instead.";
  } else if (name === "NotReadableError") {
    msg = "Camera is busy or unavailable (another app may be using it).";
  } else if (name === "OverconstrainedError") {
    msg = "Your camera doesn't match the requested mode. Try a fresh reload and tap Scan again.";
  }
  showAlert(msgEl, "err", msg);
}

async function startScanner() {
  const msgEl = document.getElementById("scan-msg");
  showAlert(msgEl, "blank", "");
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
    cameraError(e, msgEl);
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
      {
        fps: 10,
        qrbox: { width: 220, height: 220 },
        // Use the bundled JS decoder everywhere. The native BarcodeDetector
        // path is only present on some Android phones and behaves
        // differently (hard to verify remotely); the JS path is the one
        // covered by the tests.
        experimentalFeatures: { useBarCodeDetectorIfSupported: false },
      },
      (text) => processPayload(text),
      () => {}
    );
  } catch (err) {
    cameraError(err, msgEl);
    stopScanner();
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
  window[SELFIE_PAYLOAD] = payload;
  await stopScanner();
  await openSelfie();
}

// ---------- Selfie capture ----------
let selfieStream = null;

function stopSelfieStream() {
  if (selfieStream) {
    selfieStream.getTracks().forEach((t) => t.stop());
    selfieStream = null;
  }
  const video = document.getElementById("selfie-video");
  video.srcObject = null;
  video.classList.remove("hidden");
}

function resetSelfieUi() {
  delete window[SELFIE_PAYLOAD];
  delete window[SELFIE_BLOB];
  const video = document.getElementById("selfie-video");
  video.classList.remove("hidden");
  document.getElementById("selfie-preview").classList.add("hidden");
  document.getElementById("selfie-canvas").classList.add("hidden");
  document.getElementById("selfie-preview").removeAttribute("src");
  document.getElementById("selfie-msg").classList.add("hidden");
  showSelfieButtons("capture");
}

function showSelfieButtons(mode) {
  document.getElementById("capture-btn").classList.toggle("hidden", mode !== "capture");
  document.getElementById("retake-btn").classList.toggle("hidden", mode !== "confirm");
  document.getElementById("confirm-btn").classList.toggle("hidden", mode !== "confirm");
}

async function openSelfie() {
  const msgEl = document.getElementById("selfie-msg");
  showAlert(msgEl, "blank", "");
  showStep("selfie");
  const video = document.getElementById("selfie-video");
  const requestCamera = (constraints) =>
    navigator.mediaDevices.getUserMedia(constraints);
  try {
    let stream;
    try {
      stream = await requestCamera({
        video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
    } catch (e) {
      // Some devices reject the constrained request (no matching camera or a
      // stale permission state). Fall back to whatever camera the browser
      // picks rather than giving up.
      stream = await requestCamera({ video: true, audio: false });
    }
    selfieStream = stream;
    video.srcObject = stream;
    await video.play();
  } catch (e) {
    cameraError(e, msgEl);
  }
}

function captureSelfie() {
  const video = document.getElementById("selfie-video");
  const canvas = document.getElementById("selfie-canvas");
  const w = video.videoWidth || 640;
  const h = video.videoHeight || 480;
  canvas.width = w;
  canvas.height = h;
  canvas.getContext("2d").drawImage(video, 0, 0, w, h);
  canvasToBlob(canvas).then((blob) => {
    window[SELFIE_BLOB] = blob;
    const preview = document.getElementById("selfie-preview");
    preview.src = canvas.toDataURL("image/jpeg", 0.85);
    video.classList.add("hidden");
    preview.classList.remove("hidden");
    showSelfieButtons("confirm");
  });
}

function canvasToBlob(canvas) {
  return new Promise((resolve) => {
    if (typeof canvas.toBlob === "function") {
      canvas.toBlob(resolve, "image/jpeg", 0.85);
    } else {
      // Older Safari: fall back to a data-URL conversion.
      const data = canvas.toDataURL("image/jpeg", 0.85);
      const bin = atob(data.split(",")[1]);
      const arr = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
      resolve(new Blob([arr], { type: "image/jpeg" }));
    }
  });
}

function retakeSelfie() {
  const video = document.getElementById("selfie-video");
  video.classList.remove("hidden");
  document.getElementById("selfie-preview").classList.add("hidden");
  document.getElementById("selfie-msg").classList.add("hidden");
  showSelfieButtons("capture");
  video.play().catch(() => {});
}

async function submitWithSelfie() {
  const btn = document.getElementById("confirm-btn");
  const msgEl = document.getElementById("selfie-msg");
  const original = btn.innerHTML;
  btn.disabled = true;
  const busy = (label) => (btn.innerHTML = `<span class="small">${label}…</span>`);
  try {
    busy("Getting location");
    const loc = await getLocation();
    busy("Marking attendance");
    const payload = window[SELFIE_PAYLOAD];
    const viaQr = Boolean(payload.qr_token);
    const fd = new FormData();
    fd.append("session_id", String(payload.session_id));
    if (viaQr) fd.append("qr_token", payload.qr_token);
    fd.append("latitude", String(loc.lat));
    fd.append("longitude", String(loc.lng));
    fd.append("selfie", window[SELFIE_BLOB], "selfie.jpg");
    const result = await API.postForm(viaQr ? "/api/student/attendance/scan" : "/api/student/attendance/selfie", fd);
    closeScan();
    showToast(result.message, "ok");
    await loadWeek();
  } catch (err) {
    showAlert(msgEl, "err", err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = original;
  }
}

document.getElementById("scan-btn").addEventListener("click", openScan);
document.getElementById("selfie-only-btn").addEventListener("click", openSelfieOnly);
document.getElementById("manual-btn").addEventListener("click", () => {
  const raw = document.getElementById("manual-payload").value.trim();
  if (!raw) return;
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
