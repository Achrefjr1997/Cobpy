# Stage 1 — Foundation & Connectivity

## Purpose

Establish the structural foundation for the entire project: two services that can communicate in real-time. This stage contains zero intelligence—no LLMs, no database, no business logic. Its sole purpose is to prove that a user action in the browser can trigger a response from the backend that streams back live. Everything else is plumbing validation.

Think of this stage as building the empty house before moving in furniture. If the walls aren't straight now, nothing fits later.

## What Success Looks Like

A user opens the frontend in a browser, clicks a button, and watches three events appear one-by-one in the UI—streamed live from the backend. The connection closes cleanly. The network tab shows an EventSource that received data and terminated gracefully.

That's it. If that works, the foundation is solid.

## Core Decisions

**Backend**: FastAPI handles HTTP and SSE naturally. The package structure should anticipate where the agent, database, and validators will eventually live, even though they're empty placeholders now.

**Frontend**: Vite + React + TypeScript with Tailwind for styling and React Query for server state. Monaco Editor gets installed now (it's large and lazy-loading needs setup) but won't be used until Stage 5.

**Communication**: Server-Sent Events (SSE) for the streaming channel. The frontend subscribes, the backend yields JSON events, heartbeats keep the connection alive through proxies.

## Key Capabilities to Build

The backend needs a health endpoint (for connectivity checks) and a stub SSE endpoint that yields a few demo events with delays between them. CORS must be configured since frontend and backend run on different ports during development.

The frontend needs a typed API client that wraps fetch calls and an SSE subscription helper. The UI itself is minimal: display health status and render events as they arrive.

Configuration lives in environment variables loaded through Pydantic settings. The `.env.example` file documents what will eventually be needed (API keys), even though nothing requires them yet.

## Verification Criteria

- Health endpoint responds correctly to curl
- SSE endpoint streams multiple events with visible delays
- Frontend displays health status on load
- Clicking a demo button renders streamed events progressively
- No console errors, no failed requests, clean EventSource lifecycle

## Boundary

Do not add any LLM calls, database operations, or real migration logic. The temptation to "start on the real stuff" leads to debugging plumbing problems while also debugging agent problems. Separate concerns.
