# Share-of-wallet frontend

Minimal React (Vite) app that proves the frontend <-> backend connection works.
On load it fetches `http://localhost:4000/api/clients` and renders the data in
a plain HTML table (`entity_id`, `entity_name`, `sector`,
`estimated_total_wallet_zar`, `syn_bank_share_pct`, `opportunity_score`).
No styling yet.

## Setup

```bash
cd frontend
npm install
```

## Run

Make sure the backend is running first (in a separate terminal):

```bash
cd ../backend
npm start
```

Then start the frontend dev server:

```bash
npm run dev
```

Opens on `http://localhost:5173` by default. The page fetches directly from
`http://localhost:4000/api/clients` — the backend has CORS enabled so this
works across ports.
