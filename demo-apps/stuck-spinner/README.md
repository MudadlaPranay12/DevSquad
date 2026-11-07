# Demo App B: stuck-spinner

## Purpose

Simulates an infinite loading spinner with no JavaScript exception, no failed network
request, and no obvious state error. Used to demonstrate that DEV-SQUAD reports
"insufficient evidence" instead of inventing a root cause.

## What it demonstrates

- Infinite CSS-driven spinner.
- No `console.error`, no uncaught exceptions.
- No network requests at all (no successes, no failures).
- No cookies set or read.
- No DOM error state.

## How to run

Open a terminal in this folder:

```powershell
cd E:\DevSquad\demo-apps\stuck-spinner
npm install
npm start
```

Then open `http://localhost:3002` in a browser.

## Port

This app runs on `http://localhost:3002`.
