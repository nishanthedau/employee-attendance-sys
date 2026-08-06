const API = {
  token() {
    return localStorage.getItem("att_token");
  },
  user() {
    try {
      return JSON.parse(localStorage.getItem("att_user") || "null");
    } catch {
      return null;
    }
  },
  setSession(token, user) {
    localStorage.setItem("att_token", token);
    localStorage.setItem("att_user", JSON.stringify(user));
  },
  clear() {
    localStorage.removeItem("att_token");
    localStorage.removeItem("att_user");
  },
  async request(method, path, body) {
    const headers = { "Content-Type": "application/json" };
    if (this.token()) headers.Authorization = `Bearer ${this.token()}`;
    const res = await fetch(path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (res.status === 401) {
      this.clear();
      window.location.href = "/login";
      throw new Error("Session expired");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const msg =
        typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || "Request failed");
      throw new Error(msg);
    }
    return data;
  },
  get(path) {
    return this.request("GET", path);
  },
  post(path, body) {
    return this.request("POST", path, body);
  },
};

async function logout() {
  try {
    await API.post("/api/auth/logout");
  } catch {}
  API.clear();
  window.location.href = "/login";
}

function showAlert(el, type, message) {
  el.className = `alert ${type}`;
  el.textContent = message;
  el.classList.remove("hidden");
}

function showToast(message, type = "ok") {
  const el = document.getElementById("toast");
  if (!el) return;
  showAlert(el, type, message);
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add("hidden"), 4000);
}

function esc(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  return div.innerHTML;
}

function getLocation() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error("Geolocation not supported by this browser"));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) =>
        resolve({
          lat: Number(pos.coords.latitude.toFixed(7)),
          lng: Number(pos.coords.longitude.toFixed(7)),
        }),
      (err) =>
        reject(new Error(err.code === 1 ? "Location access denied. Allow location to mark attendance." : "Unable to get location.")),
      { enableHighAccuracy: true, timeout: 10000 }
    );
  });
}

function fmtDate(iso) {
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

// <img> tags can't send the Authorization header, so fetch the QR as a blob
// (blob is revoked on next load to avoid leaking memory).
async function loadQrImage(sessionId, imgEl) {
  const res = await fetch(`/api/admin/attendance/qr?session_id=${sessionId}`, {
    headers: { Authorization: `Bearer ${API.token()}` },
  });
  if (!res.ok) throw new Error("Failed to load QR code");
  const blob = await res.blob();
  if (imgEl._objUrl) URL.revokeObjectURL(imgEl._objUrl);
  imgEl._objUrl = URL.createObjectURL(blob);
  imgEl.src = imgEl._objUrl;
}
