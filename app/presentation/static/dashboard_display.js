(() => {
  const frameImage = document.getElementById("dashboard-display-frame");
  if (!frameImage) {
    return;
  }

  const frameUrl = frameImage.dataset.frameUrl;
  const metaUrl = frameImage.dataset.metaUrl;
  const wsPath = frameImage.dataset.wsUrl;
  let currentVersion = Number(frameImage.dataset.version || "-1");

  const refreshFrame = (version) => {
    if (!Number.isFinite(version)) {
      return;
    }
    if (version === currentVersion) {
      return;
    }

    currentVersion = version;
    frameImage.src = `${frameUrl}?v=${version}`;
  };

  const pollMeta = async () => {
    try {
      const response = await fetch(metaUrl, {
        cache: "no-store",
        headers: {
          Accept: "application/json",
        },
      });
      if (!response.ok) {
        return;
      }

      const payload = await response.json();
      refreshFrame(Number(payload.version));
    } catch {
      // Polling intentionally keeps silent when network hiccups occur.
    }
  };

  const connectWebSocket = () => {
    if (!wsPath || !window.WebSocket) {
      return;
    }

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const wsUrl = `${protocol}://${window.location.host}${wsPath}`;
    const socket = new WebSocket(wsUrl);

    socket.addEventListener("message", (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.event === "frame_updated") {
          refreshFrame(Number(payload.version));
        }
      } catch {
        // Ignore malformed payloads and keep polling fallback active.
      }
    });

    socket.addEventListener("close", () => {
      window.setTimeout(connectWebSocket, 2000);
    });

    socket.addEventListener("error", () => {
      socket.close();
    });
  };

  pollMeta();
  window.setInterval(pollMeta, 400);
  connectWebSocket();
})();
