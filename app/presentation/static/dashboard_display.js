(() => {
  const frameImage = document.getElementById("dashboard-display-frame");
  if (!frameImage) {
    return;
  }

  const frameUrl = frameImage.dataset.frameUrl;
  const metaUrl = frameImage.dataset.metaUrl;
  const wsPath = frameImage.dataset.wsUrl;
  const screenWindow = document.querySelector(".tamagotchi-screen-window");
  let currentVersion = Number(frameImage.dataset.version || "-1");

  const applyResolution = (width, height) => {
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
      return;
    }

    frameImage.setAttribute("width", String(width));
    frameImage.setAttribute("height", String(height));
    if (screenWindow) {
      screenWindow.style.aspectRatio = `${width} / ${height}`;
    }
  };

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

  const applyMeta = (meta) => {
    if (!meta || typeof meta !== "object") {
      return;
    }
    applyResolution(Number(meta.width), Number(meta.height));
    refreshFrame(Number(meta.version));
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
      applyMeta(payload);
    } catch {
      // Polling keeps running through short network failures.
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
          applyMeta(payload);
        }
      } catch {
        // Ignore malformed payloads.
      }
    });

    socket.addEventListener("close", () => {
      window.setTimeout(connectWebSocket, 2000);
    });

    socket.addEventListener("error", () => {
      socket.close();
    });
  };

  const postButton = async (button) => {
    try {
      await fetch("/api/input/button", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({ button }),
      });
    } catch {
      // Input errors are ignored to keep UI responsive.
    }
  };

  document.querySelectorAll(".virtual-control-button").forEach((element) => {
    element.addEventListener("click", () => {
      const button = element.dataset.button;
      if (!button) {
        return;
      }
      void postButton(button);
    });
  });

  window.addEventListener("keydown", (event) => {
    const keyMap = {
      ArrowDown: "NEXT",
      ArrowUp: "BACK",
      Enter: "CONFIRM",
      " ": "SPECIAL",
    };

    const mapped = keyMap[event.key];
    if (!mapped) {
      return;
    }

    event.preventDefault();
    void postButton(mapped);
  });

  applyResolution(
    Number(frameImage.getAttribute("width")),
    Number(frameImage.getAttribute("height")),
  );
  pollMeta();
  window.setInterval(pollMeta, 400);
  connectWebSocket();
})();
