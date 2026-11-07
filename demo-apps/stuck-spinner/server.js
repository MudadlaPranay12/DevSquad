/**
 * DEV-SQUAD Demo App B: stuck-spinner
 * Infinite loading spinner with no JavaScript exception, no failed network request,
 * and no obvious state error.
 *
 * This scenario demonstrates that DEV-SQUAD can report insufficient evidence
 * instead of inventing a root cause.
 *
 * Run:  cd E:\DevSquad\demo-apps\stuck-spinner && npm install && npm start
 * Then open: http://localhost:3002
 */

const express = require("express");
const path = require("path");

const app = express();
const PORT = 3002;

app.use(express.static(path.join(__dirname, "public")));

// No /api routes, no failing endpoints, no cookies — just a static page.
app.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

app.listen(PORT, () => {
  console.log(`stuck-spinner demo running at http://localhost:${PORT}`);
});
