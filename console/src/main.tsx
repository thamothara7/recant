import React from "react";
import ReactDOM from "react-dom/client";

// Self-hosted fonts (offline, no CDN). Material 3 roles: Roboto 400/500/700
// for the type scale, Roboto Mono 400/500 for database data (hashes,
// timestamps, SQL), Material Symbols Rounded for icons.
import "@fontsource/roboto/400.css";
import "@fontsource/roboto/500.css";
import "@fontsource/roboto/700.css";
import "@fontsource/roboto-mono/400.css";
import "@fontsource/roboto-mono/500.css";
import "material-symbols/rounded.css";

import "@xyflow/react/dist/style.css";
import "./index.css";
import { App } from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
