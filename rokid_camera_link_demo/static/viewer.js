const $ = (selector) => document.querySelector(selector);

const state = {
  sequence: 0,
  previousSequence: 0,
  previousSampleAt: performance.now(),
  fps: 0,
  requestRunning: false,
};

function guessCaptureUrl() {
  return `${location.protocol}//${location.host}/capture.html`;
}

async function loadServerConfig() {
  try {
    const response = await fetch("/api/config", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const config = await response.json();
    $("#captureUrl").value = config.capture_url || guessCaptureUrl();
  } catch {
    $("#captureUrl").value = guessCaptureUrl();
    $("#copyFeedback").textContent = "无法读取局域网地址，当前显示页面同源地址。";
  }
}

function formatTime(timestampMs) {
  if (!timestampMs) return "—";
  return new Date(timestampMs).toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function setConnection(kind, text) {
  const badge = $("#connectionBadge");
  badge.className = `connection-badge ${kind}`;
  $("#connectionText").textContent = text;
}

function updateFps(sequence) {
  const now = performance.now();
  const elapsedSeconds = (now - state.previousSampleAt) / 1000;
  if (elapsedSeconds < 1) return;
  const frameDelta = Math.max(0, sequence - state.previousSequence);
  const instantFps = frameDelta / elapsedSeconds;
  state.fps = state.fps ? state.fps * 0.55 + instantFps * 0.45 : instantFps;
  state.previousSequence = sequence;
  state.previousSampleAt = now;
  $("#fpsValue").textContent = state.fps.toFixed(1);
}

function renderStatus(payload) {
  if (!payload.has_frame) {
    setConnection("waiting", "等待眼镜画面");
    $("#diagnosticText").textContent = "服务器已就绪，正在等待第一张 JPEG 图片。";
    return;
  }

  const frame = payload.frame;
  const isFresh = payload.age_ms < 3000;
  setConnection(isFresh ? "live" : "waiting", isFresh ? "光学链路在线" : "画面已暂停");

  $("#latencyValue").textContent = String(payload.age_ms ?? "—");
  $("#sizeValue").textContent = frame.size_bytes
    ? (frame.size_bytes / 1024).toFixed(1)
    : "—";
  $("#frameCounter").textContent = `FRAME ${String(frame.sequence).padStart(6, "0")}`;
  $("#resolutionValue").textContent =
    frame.width && frame.height ? `${frame.width} × ${frame.height}` : "尺寸未上报";
  $("#deviceValue").textContent = frame.device_name || "unknown-device";
  $("#ipValue").textContent = frame.client_ip || "—";
  $("#receivedValue").textContent = formatTime(frame.received_at_ms);
  $("#diagnosticText").textContent = isFresh
    ? "JPEG 接收正常。当前页面仅负责显示，不会运行识别算法。"
    : "超过 3 秒未收到新画面，请检查采集端是否仍在传输。";

  updateFps(frame.sequence);

  if (frame.sequence !== state.sequence) {
    state.sequence = frame.sequence;
    const image = $("#liveFrame");
    image.onload = () => {
      image.hidden = false;
      $("#emptyState").hidden = true;
    };
    image.src = `/api/frame.jpg?sequence=${frame.sequence}`;
  }
}

async function pollStatus() {
  if (state.requestRunning) return;
  state.requestRunning = true;
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderStatus(await response.json());
  } catch (error) {
    setConnection("error", "电脑服务异常");
    $("#diagnosticText").textContent = `状态读取失败：${error.message}`;
  } finally {
    state.requestRunning = false;
  }
}

async function copyCaptureUrl() {
  const value = $("#captureUrl").value;
  try {
    await navigator.clipboard.writeText(value);
    $("#copyFeedback").textContent = "采集地址已复制。";
  } catch {
    $("#captureUrl").select();
    document.execCommand("copy");
    $("#copyFeedback").textContent = "采集地址已复制。";
  }
}

$("#captureUrl").value = guessCaptureUrl();
$("#copyButton").addEventListener("click", copyCaptureUrl);

window.setInterval(() => {
  $("#clockValue").textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
}, 500);
window.setInterval(pollStatus, 350);
loadServerConfig();
pollStatus();
