import React from "react";
import ReactDOM from "react-dom/client";

// Self-hosted fonts (offline, no CDN). Weights chosen per role:
// Source Serif 4 600 (display), IBM Plex Sans 400/500/600 (UI),
// IBM Plex Mono 400/500 (data).
import "@fontsource/source-serif-4/600.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";

import "@xyflow/react/dist/style.css";
import "./index.css";
import { App } from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
