import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The backend (app/main.py) is frozen and has no CORS middleware configured. Rather than
// touch it, both the dev server and the production preview proxy every backend call under
// one `/api` prefix, stripped before forwarding — the browser only ever talks to this
// origin, so CORS never enters the picture and zero backend files are touched.
//
// The prefix is required, not cosmetic: the frontend's own client-side routes are `/cases`
// and `/cases/:id` (spec-mandated — see Page 1/Case List routes), which are exactly the same
// paths the backend's REST resources use. Proxying those bare paths directly intercepts the
// SPA's own page navigation/refresh (e.g. a hard refresh on /cases/<id> would hit the
// backend and render raw JSON instead of the app shell) — confirmed by hitting it before
// this fix. `/api/*` never collides with a page route, so this is the only sound way to
// reach the backend from the same origin. BRIDGE_AI_API_URL lets this point at a
// non-default backend host/port.
const backendTarget = process.env.BRIDGE_AI_API_URL ?? 'http://127.0.0.1:8000'
const proxy = {
  '/api': {
    target: backendTarget,
    rewrite: (path: string) => path.replace(/^\/api/, ''),
  },
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy },
  preview: { proxy },
})
