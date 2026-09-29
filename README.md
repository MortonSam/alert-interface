# Alert Interface

Personal finance research tool — work in progress.

## Status
Early development. Summer 2026 build.

## Admin mode

When `ADMIN_TOKEN` is set on the backend, AI-powered endpoints (thesis drafting, research notes, options reads) require authentication. To unlock them in the browser, open the console and run:

```js
localStorage.setItem("admin_token", "your-token-here");
```

This enables AI thesis drafts, research note generation/verification, and fresh options reads.

## Reviewer key

`REVIEWER_TOKENS` on the backend is a comma-separated list of reviewer keys. A request carrying one
reads the ledger (Ivy home, the desk, Ivy trades) while `LEDGER_PUBLIC` is false, exactly as the admin
token does, and nothing else: no theses, no watchlists, no note generation, no admin endpoints, no
writes, and it is never attributed to admin-local. The key travels in the same header and the same
browser slot as the admin token.

To enter a key, in the browser on the site:

1. Open the developer tools console (macOS: Cmd+Option+J in Chrome or Edge, Cmd+Option+K in Firefox,
   Cmd+Option+C in Safari after enabling the Develop menu; Windows/Linux: Ctrl+Shift+J or Ctrl+Shift+K).
2. Run, with the key in place of the placeholder:

   ```js
   localStorage.setItem("admin_token", "the-reviewer-key");
   ```

3. Reload the page. Ivy home, the desk and Ivy trades show the ledger with a "Private preview" label.
   My Trades and Watchlists still show the sign-in notice, and Build a Trade refuses a save with the
   same notice.

To remove it: `localStorage.removeItem("admin_token")` in the same console, then reload.
