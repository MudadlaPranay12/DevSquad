# Demo App A: auth-failure

## Purpose

Simulates an authentication initialization failure for DEV-SQUAD evidence collection testing.

## What it demonstrates

- `console.error("Authentication initialization failed")` on page load — captured as a console error.
- `GET /api/user` returns HTTP 401 — captured as a failed network response.
- Login button gets stuck in a loading state (never resolves) — observable DOM state.
- No session cookie is issued — cookie metadata can be observed but no values are collected.
- The browser requests `favicon.ico`, which the server does not serve — produces a 404 red herring (not a real bug).

## How to run

Open a terminal in this folder:

```powershell
cd E:\DevSquad\demo-apps\auth-failure
npm install
npm start
```

Then open `http://localhost:3001` in a browser.

## Port

This app runs on `http://localhost:3001`.
