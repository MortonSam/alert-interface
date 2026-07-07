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
