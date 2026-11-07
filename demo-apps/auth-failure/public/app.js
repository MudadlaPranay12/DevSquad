/**
 * DEV-SQUAD Demo App A: auth-failure — frontend logic.
 *
 * Behavior simulated for evidence collection:
 * 1. On page load, an auth initialization console error is emitted (simulated backend init failure).
 * 2. Clicking "Sign in" puts the button into a stuck loading state (never resolves).
 * 3. A fetch to /api/user returns HTTP 401.
 * 4. No session cookie is ever set.
 * 5. The browser also requests favicon.ico which the server does not serve -> 404 red herring.
 *
 * SECURITY NOTE: This demo never handles real passwords. The password field value is
 * intentionally never logged or transmitted anywhere except to the same-origin demo server,
 * which discards it. The Playwright collector redacts form input values before saving.
 */

(function () {
  const form = document.getElementById("loginForm");
  const btn = document.getElementById("loginBtn");
  const loading = document.getElementById("loading");
  const errorBox = document.getElementById("error");

  // Simulate an authentication initialization failure at page load.
  // This produces a console.error that the collector captures as evidence E001.
  console.error("Authentication initialization failed");

  form.addEventListener("submit", async function (event) {
    event.preventDefault();

    // Stick the button in a loading state — never resolves.
    btn.disabled = true;
    btn.textContent = "Signing in…";
    loading.classList.remove("hidden");
    errorBox.classList.add("hidden");
    errorBox.textContent = "";

    try {
      // This request intentionally returns 401 from the server.
      // The collector captures the network response as evidence.
      const response = await fetch("/api/user", {
        method: "GET",
        // Do NOT send Authorization headers or credentials intentionally.
        credentials: "omit",
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      errorBox.textContent = "Unexpected success: " + JSON.stringify(data);
      errorBox.classList.remove("hidden");
    } catch (err) {
      // Deliberately not re-thrown to the global handler — we want the 401
      // to appear only as a network response, not an uncaught JS exception.
      console.error(`Login request failed: ${err.message}`);
      errorBox.textContent = "Authentication failed (401). Please try again.";
      errorBox.classList.remove("hidden");
    }

    // Button stays stuck in loading state — never re-enabled.
  });
})();
