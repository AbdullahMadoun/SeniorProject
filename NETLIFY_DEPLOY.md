# Netlify Deployment (Skylink2 Frontend)

This deploys only the static frontend (`src/static`) to Netlify.

## 1. Deploy

1. Push this branch to GitHub.
2. In Netlify: **Add new site** -> **Import from Git**.
3. Select repo and branch.
4. Build settings:
   - Base directory: `Skylink2`
   - Build command: *(leave empty)*
   - Publish directory: `src/static`

`netlify.toml` is already included, so default settings should be auto-detected.

## 2. Configure Runtime

Edit `src/static/config.js` before deploy or in future commits:

```js
window.APP_CONFIG = {
  BRIDGE_BASE_URL: "https://your-bridge-backend.example.com"
};
```

- If `BRIDGE_BASE_URL` is set:
  - Frontend uses `${BRIDGE_BASE_URL}/api/analyze`, `/api/sync`, `/api/history`.
  - Supabase sync and server-side history work.
- If `BRIDGE_BASE_URL` is empty:
  - Frontend calls your hosted model endpoint directly from browser using API URL + key inputs.
  - History falls back to browser `localStorage`.
  - Supabase sync call is skipped.

## 3. Required for Full Functionality

For "analyze + save annotated image + sync to Supabase", you must deploy the `Skylink2/src/server.py` bridge to a backend host (Render/Railway/Fly/etc.) and set `BRIDGE_BASE_URL` to that backend URL.
