/**
 * DEV-SQUAD Demo App A: auth-failure
 * Simulated authentication initialization failure.
 *
 * Run:  cd E:\DevSquad\demo-apps\auth-failure && npm install && npm start
 * Then open: http://localhost:3001
 */

const express = require("express");
const path = require("path");

const app = express();
const PORT = 3001;

// Serve static files from /public
app.use(express.static(path.join(__dirname, "public")));

// Deliberately do NOT serve favicon.ico -> produces a 404 red herring in the console.

// Simulated protected endpoint that always returns 401 Unauthorized.
// No Authorization headers are echoed back. No session cookie is issued.
app.get("/api/user", (_req, res) => {
  res.status(401).json({ error: "unauthorized", code: 401 });
});

// Health check
app.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

app.listen(PORT, () => {
  console.log(`auth-failure demo running at http://localhost:${PORT}`);
});
