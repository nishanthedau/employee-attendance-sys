const SELFIE_BLOB = "_selfieBlob";

let employees = [];
let session = null;
let verifyMode = "none";

let scanner = null;
let selfieStream = null;

function showStep(name) {
  ["scan-step", "form-step", "verify-step", "done-step"].forEach((id) => {
    document.getElementById(id).classList.toggle("hidden", id !== name);
  });
}

function showLanding() {
  document.getElementById("scan-landing").classList.remove("hidden");
  document.getElementById("scan-camera").classList.add("hidden");
}

function showCamera() {
  document.getElementById("scan-landing").classList.add("hidden");
  document.getElementById("scan-camera").classList.remove("hidden");
}

function modeLabel(mode) {
  return {
    none: "Location will be checked.",
    selfie: "A quick selfie will be required.",
    code: "Your personal code will be required.",
    both: "A selfie and your personal code will be required.",
  }[mode] || "Location will be checked.";
}

async function loadRoster() {
  const sel = document.getElementById("who");
  sel.innerHTML = '<option value="">Who are you?</option>';
  try {
    const data = await API.get("/api/employee/roster");
    employees = data.employees || [];
    sel.innerHTML = '<option value="">Who are you?</option>';
    for (const e of employees) {
      const opt = document.createElement("option");
      opt.value = e.id;
      opt.textContent = e.name;
      sel.appendChild(opt);
    }
    if (!employees.length) {
      showToast("No employees added yet. Ask the admin to add people first.", "err");
    }
  } catch (err) {
    sel.innerHTML = '<option value="">Couldn\'t load employees — retry</option>';
    showToast(err.message, "err");
  }
}

function cameraError(e, msgEl) {
  console.error("Camera start failed:", e);
  const name = (e && (e.name || (e.error && e.error.name))) || "";
  let msg = "Could not start the camera.";
  if (name === "NotAllowedError") {
    msg = "Camera permission denied. Allow camera for this site: tap the aA/lock icon by the URL → Camera → Allow, then retry.";
  } else if (name === "NotFoundError") {
    msg = "No camera found on this device.";
  } else if (name === "NotReadableError") {
    msg = "Camera is busy or unavailable (another app may be using it).";
  }
  showAlert(msgEl, "err", msg);
}

async function stopScanner() {
  if (scanner) {
    const s = scanner;
    scanner = null;
    try {
      await s.stop();
    } catch {}
  }
}

function stopSelfieStream() {
  if (selfieStream) {
    selfieStream.getTracks().forEach((t) => t.stop());
    selfieStream = null;
  }
  const video = document.getElementById("selfie-video");
  video.srcObject = null;
}

async function startScanner() {
  const msgEl = document.getElementById("scan-msg");
  showAlert(msgEl, "blank", "");
  if (!window.Html5Qrcode || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    showAlert(msgEl, "err", "QR scanner isn't available here (needs HTTPS + a modern browser). Reload and try again.");
    return;
  }
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
    await new Promise((r) => setTimeout(r, 120));
    const region = document.getElementById("qr-reader");
    scanner = new Html5Qrcode("qr-reader");
    await scanner.start(
      { facingMode: "environment" },
      {
        fps: 10,
        qrbox: { width: 220, height: 220 },
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
  await stopScanner();
  try {
    const data = await API.post("/api/employee/resolve", payload);
    session = data.session;
    session.qr_token = payload.qr_token;
    verifyMode = data.verification_mode || "none";
    document.getElementById("session-title").textContent = session.subject;
    document.getElementById("session-meta").textContent =
      `${session.faculty} · ${session.start_time} – ${session.end_time}`;
    document.getElementById("mode-hint").textContent = modeLabel(verifyMode);
    document.getElementById("form-msg").classList.add("hidden");
    showStep("form-step");
  } catch (err) {
    showToast(err.message, "err");
    showStep("scan-step");
    showCamera();
    startScanner();
  }
}

// ---------- Verification ----------

function resetSelfieUi() {
  delete window[SELFIE_BLOB];
  stopSelfieStream();
  const video = document.getElementById("selfie-video");
  video.classList.remove("hidden");
  document.getElementById("selfie-preview").classList.add("hidden");
  document.getElementById("selfie-canvas").classList.add("hidden");
  document.getElementById("selfie-preview").removeAttribute("src");
  document.getElementById("capture-btn").classList.remove("hidden");
  document.getElementById("retake-btn").classList.add("hidden");
  document.getElementById("confirm-selfie-btn").classList.add("hidden");
}

async function openSelfie() {
  const msgEl = document.getElementById("verify-msg");
  showAlert(msgEl, "blank", "");
  const video = document.getElementById("selfie-video");
  try {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
    } catch {
      stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
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
  canvas.toBlob((blob) => {
    window[SELFIE_BLOB] = blob;
    const preview = document.getElementById("selfie-preview");
    preview.src = canvas.toDataURL("image/jpeg", 0.85);
    video.classList.add("hidden");
    preview.classList.remove("hidden");
    document.getElementById("capture-btn").classList.add("hidden");
    document.getElementById("retake-btn").classList.remove("hidden");
    document.getElementById("confirm-selfie-btn").classList.remove("hidden");
  }, "image/jpeg", 0.85);
}

function needsSelfie() {
  return verifyMode === "selfie" || verifyMode === "both";
}
function needsCode() {
  return verifyMode === "code" || verifyMode === "both";
}

function openVerify() {
  const msgEl = document.getElementById("verify-msg");
  showAlert(msgEl, "blank", "");
  document.getElementById("verify-hint").textContent = modeLabel(verifyMode);
  document.getElementById("selfie-box-wrap").classList.toggle("hidden", !needsSelfie());
  document.getElementById("code-box-wrap").classList.toggle("hidden", !needsCode());
  if (needsCode()) document.getElementById("verify-code").value = "";
  showStep("verify-step");
  resetSelfieUi();
  if (needsSelfie()) openSelfie();
  else document.getElementById("verify-code").focus();
}

function retakeSelfie() {
  const video = document.getElementById("selfie-video");
  video.classList.remove("hidden");
  document.getElementById("selfie-preview").classList.add("hidden");
  document.getElementById("capture-btn").classList.remove("hidden");
  document.getElementById("retake-btn").classList.add("hidden");
  document.getElementById("confirm-selfie-btn").classList.add("hidden");
  video.play().catch(() => {});
}

function confirmSelfie() {
  if (!window[SELFIE_BLOB]) {
    showAlert(document.getElementById("verify-msg"), "err", "Capture a selfie first.");
    return;
  }
  submitMark();
}

async function submitMark() {
  const btn = document.getElementById("submit-mark-btn");
  const msgEl = document.getElementById("verify-msg");
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="small">Marking…</span>';
  try {
    if (needsSelfie() && !window[SELFIE_BLOB]) {
      throw new Error("A selfie is required for this class. Capture one above.");
    }
    const code = needsCode() ? document.getElementById("verify-code").value.trim() : null;
    if (needsCode() && !/^\d{4,6}$/.test(code || "")) {
      throw new Error("Your code is 4 to 6 digits. Check it and try again.");
    }
    btn.innerHTML = '<span class="small">Checking location…</span>';
    let lat = null;
    let lng = null;
    try {
      const loc = await getLocation();
      lat = loc.lat;
      lng = loc.lng;
    } catch {
      showToast("Location unavailable — marking without GPS.", "err");
    }
    const fd = new FormData();
    fd.append("session_id", String(session.id));
    fd.append("qr_token", session.qr_token);
    fd.append("employee_id", document.getElementById("who").value);
    fd.append("status", document.getElementById("status").value);
    if (lat !== null) fd.append("latitude", String(lat));
    if (lng !== null) fd.append("longitude", String(lng));
    if (code) fd.append("code", code);
    if (window[SELFIE_BLOB]) fd.append("selfie", window[SELFIE_BLOB], "selfie.jpg");
    const result = await API.postForm("/api/employee/attendance/mark", fd);
    document.getElementById("done-title").textContent = "Marked";
    document.getElementById("done-detail").textContent =
      `${session.subject} · ${result.record.status.toUpperCase()} at ${new Date(result.record.scan_time).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}`;
    showStep("done-step");
  } catch (err) {
    showAlert(msgEl, "err", err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = original;
  }
}

function resetAll() {
  session = null;
  delete window[SELFIE_BLOB];
  stopSelfieStream();
  stopScanner();
  showStep("scan-step");
  showLanding();
  document.getElementById("qr-reader").innerHTML = "";
}

document.getElementById("scan-cta-btn").addEventListener("click", () => {
  showCamera();
  startScanner();
});
document.getElementById("scan-btn").addEventListener("click", startScanner);
document.getElementById("back-scan-btn").addEventListener("click", resetAll);
document.getElementById("done-btn").addEventListener("click", () => {
  if (!document.getElementById("who").value) {
    showAlert(document.getElementById("form-msg"), "err", "Pick who you are first.");
    return;
  }
  openVerify();
});
document.getElementById("capture-btn").addEventListener("click", captureSelfie);
document.getElementById("retake-btn").addEventListener("click", retakeSelfie);
document.getElementById("confirm-selfie-btn").addEventListener("click", confirmSelfie);
document.getElementById("submit-mark-btn").addEventListener("click", submitMark);
document.getElementById("verify-code").addEventListener("keydown", (e) => {
  if (e.key === "Enter") submitMark();
});
document.getElementById("again-btn").addEventListener("click", resetAll);

(async () => {
  await loadRoster();
})();
