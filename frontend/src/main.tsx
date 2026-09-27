import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

// A tab opened before a rebuild still asks for the old hashed chunks, which are gone.
// Reload once to pick up the new build; the flag stops a loop if the chunk is truly missing.
window.addEventListener("vite:preloadError", (e) => {
  try {
    if (sessionStorage.getItem("nts.reloaded")) return;
    sessionStorage.setItem("nts.reloaded", "1");
  } catch {
    return;
  }
  e.preventDefault();
  window.location.reload();
});
window.addEventListener("load", () => {
  // a page that got this far loaded fine; allow the next rebuild to reload again
  setTimeout(() => {
    try {
      sessionStorage.removeItem("nts.reloaded");
    } catch {
      /* ignore */
    }
  }, 10000);
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
