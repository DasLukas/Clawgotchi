(() => {
  const frameImage = document.getElementById("display-frame");
  if (!frameImage) {
    return;
  }

  const versionElement = document.getElementById("display-version");
  const updatedElement = document.getElementById("display-updated");
  const statusElement = document.getElementById("display-status");
  const scaleInput = document.getElementById("display-scale");
  const scaleValue = document.getElementById("display-scale-value");

  const frameUrl = frameImage.dataset.frameUrl;
  const metaUrl = frameImage.dataset.metaUrl;
  const wsPath = frameImage.dataset.wsUrl;
  const baseWidth = Number(frameImage.getAttribute("width")) || 264;
  const baseHeight = Number(frameImage.getAttribute("height")) || 176;

  let currentVersion = Number(frameImage.dataset.version || "-1");

  const setStatus = (message) => {
    if (statusElement) {
      statusElement.textContent = message;
    }
  };

  const setScale = (scale) => {
    const resolvedScale = Math.min(4, Math.max(1, Number(scale) || 1));
    frameImage.style.width = `${baseWidth * resolvedScale}px`;
    frameImage.style.height = `${baseHeight * resolvedScale}px`;
    if (scaleValue) {
      scaleValue.textContent = `${resolvedScale}x`;
    }
  };

  const updateMeta = (meta) => {
    if (versionElement) {
      versionElement.textContent = String(meta.version);
    }
    if (updatedElement && Number.isFinite(meta.updated_at_ms)) {
      const formatted = new Date(meta.updated_at_ms).toLocaleTimeString();
      updatedElement.textContent = formatted;
    }
  };

  const refreshFrame = (meta) => {
    if (!meta || typeof meta.version !== "number") {
      return;
    }
    if (meta.version === currentVersion) {
      return;
    }

    currentVersion = meta.version;
    updateMeta(meta);
    frameImage.src = `${frameUrl}?v=${meta.version}`;
  };

  const fetchMeta = async () => {
    const response = await fetch(metaUrl, {
      cache: "no-store",
      headers: {
        Accept: "application/json",
      },
    });

    if (!response.ok) {
      throw new Error(`Meta endpoint returned status ${response.status}`);
    }

    return response.json();
  };

  const pollMeta = async () => {
    try {
      const meta = await fetchMeta();
      refreshFrame(meta);
      setStatus("Live updates active");
    } catch (error) {
      setStatus("Retrying mirror sync...");
    }
  };

  const connectWebSocket = () => {
    if (!wsPath || !window.WebSocket) {
      return;
    }

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const wsUrl = `${protocol}://${window.location.host}${wsPath}`;
    const socket = new WebSocket(wsUrl);

    socket.addEventListener("open", () => {
      setStatus("Live updates active (WebSocket)");
    });

    socket.addEventListener("message", (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.event === "frame_updated") {
          refreshFrame(payload);
        }
      } catch (error) {
        setStatus("WebSocket payload error");
      }
    });

    socket.addEventListener("close", () => {
      setStatus("WebSocket disconnected, polling remains active");
      window.setTimeout(connectWebSocket, 2000);
    });

    socket.addEventListener("error", () => {
      socket.close();
    });
  };

  if (scaleInput) {
    scaleInput.addEventListener("input", (event) => {
      const target = event.target;
      setScale(target.value);
    });
  }

  setScale(scaleInput ? scaleInput.value : 2);
  pollMeta();
  window.setInterval(pollMeta, 400);
  connectWebSocket();
})();
