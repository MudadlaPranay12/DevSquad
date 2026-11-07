// Registers the DEV-SQUAD panel inside Chrome DevTools.
// The panel hosts the same React bundle as the toolbar popup.
chrome.devtools.panels.create(
  "DEV-SQUAD",
  "",
  "dist/index.html",
  () => {
    // Panel created. No further setup required: the React app reads the
    // inspected page URL from its own form and talks to the local bridge.
  },
);
