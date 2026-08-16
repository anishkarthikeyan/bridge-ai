# Bridge AI — Frontend

React + TypeScript + Vite. Renders the case dashboard and live case timeline against the
Bridge AI backend's read API — no state of its own beyond what it polls.

See the [repository root README](../README.md) for the full project overview, architecture,
and how to run the backend this depends on.

## Commands

```bash
pnpm install
pnpm dev       # dev server on :5173, proxies /api/* to the backend
pnpm build     # type-check + production build into dist/
pnpm preview   # serve the production build locally
pnpm lint      # oxlint
```

## Talking to the backend

Every backend call goes through the `/api` prefix (see `vite.config.ts`), proxied to
`http://127.0.0.1:8000` by default. Point it at a different backend with:

```bash
BRIDGE_AI_API_URL=http://127.0.0.1:8000 pnpm dev
```

The `/api` prefix isn't cosmetic — the backend's REST paths (`/cases`, `/cases/{id}`) are the
same shape as this app's own client-side routes, so proxying them bare would intercept page
navigation. Everything under `src/lib/api.ts` is the one place that knows this.

## Structure

```
src/
  components/
    layout/     shell, sidebar, wordmark
    cases/      case header, timeline, agent-event/channel-transition rendering, stakeholder
                and health/priority/follow-up panels
    common/     badge, loading/empty/error states
  pages/        Cases, CaseDetail, Overview, Activity
  lib/          API client, types mirroring the backend's DTOs, formatting/presentation helpers
```
