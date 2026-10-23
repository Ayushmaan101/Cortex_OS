# CortexOS

A knowledge-graph workspace: a Next.js canvas (React Flow) on top of a FastAPI backend that uses Supabase (Postgres + pgvector), Groq for LLM synthesis, local sentence-transformer embeddings, and an RSS harvester with emailed digests via Resend.

```
CortexOS/
├── backend/    FastAPI API (main.py), harvester, digest emails, embeddings
└── frontend/   Next.js 16 + React 19 + Tailwind 4 + React Flow
```

## System requirements

- Windows, macOS or Linux
- [Anaconda / Miniconda](https://docs.conda.io/en/latest/miniconda.html)
- Python 3.10 (installed through conda)
- Node.js 20+ and npm
- ~2 GB free disk (PyTorch + the `all-MiniLM-L6-v2` model, downloaded on first run)
- Accounts and keys: Supabase, Groq, Resend (Resend is only needed for digest emails)

## API keys

Create `backend/.env` from the template and fill in each value:

```bash
cp backend/.env.example backend/.env      # PowerShell: Copy-Item backend\.env.example backend\.env
```

| Variable | Required | Where to get it |
|---|---|---|
| `SUPABASE_URL` | yes | Supabase dashboard → Project Settings → API |
| `SUPABASE_KEY` | yes | Same page (the key your backend should use) |
| `GROQ_API_KEY` | yes | https://console.groq.com/keys |
| `RESEND_API_KEY` | for emails | https://resend.com/api-keys |
| `DIGEST_EMAIL` | for emails | Address that receives digests |
| `DIGEST_FROM` | for emails | Sender, e.g. `CortexOS <onboarding@resend.dev>` |
| `CORTEX_URL` | no | Frontend URL used in email links (default `http://localhost:3000`) |

The Supabase project needs the tables the backend queries (e.g. `nodes`, `edges`, `sessions`, `profiles`) and the `match_nodes` RPC (pgvector, 1536-dim embedding column).

## Setup

### 1. Backend (conda)

```bash
conda env create -f environment.yml
conda activate cortex-env
```

Or, if the env already exists:

```bash
conda activate cortex-env
pip install -r backend/requirements.txt
```

Run the API (from `backend/`):

```bash
cd backend
uvicorn main:app --reload --port 8000
```

API: http://localhost:8000 (interactive docs at `/docs`).

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

App: http://localhost:3000 (it talks to the backend at `http://localhost:8000`).

## Notes

- `backend/database.py` disables TLS verification for Supabase to work around antivirus TLS interception on a dev machine. Do not use that in production.
- Never commit `.env`; only `.env.example` is tracked.
