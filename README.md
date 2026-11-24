# APIForge AI

> Autonomous, AI-powered platform that converts natural-language instructions into deterministic, executable API workflows using locally hosted AI.

---

## 1. Overview & Technology Stack

APIForge AI is a full-stack developer platform designed to generate, inspect, approve, and execute multi-step API workflows entirely locally without paid cloud LLM dependencies.

### Technology Stack

- **Backend**: Python 3.11, FastAPI, Pydantic v2, HTTPX
- **Database**: SQLite (SQLAlchemy 2.0, WAL mode, foreign keys enforced)
- **Local AI / LLM**: Ollama (`http://localhost:11434`)
  - **Workflow Planning & Chat**: `qwen2.5:7b-instruct` (fallback: `qwen2.5:3b`)
  - **Semantic Search & Embeddings**: `nomic-embed-text`
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, React Flow (`@xyflow/react`), React Router
- **Security & Execution**: NetworkX (DAG execution), Cryptography (Fernet credential encryption), JWT authentication (HS256)

---

## 2. Monorepo Project Structure

```text
APIForge AI/
│
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py          # FastAPI application & /health endpoint
│   │   ├── config.py        # Pydantic Settings & environment validation
│   │   ├── db.py            # SQLite engine, WAL mode, session factory
│   │   ├── models.py        # SQLAlchemy models (Phase 1)
│   │   ├── schemas.py       # Pydantic request/response schemas
│   │   ├── security.py      # JWT & encryption (Phase 2)
│   │   ├── routers/         # API route handlers
│   │   ├── services/        # Business logic & Ollama client
│   │   ├── agents/          # Multi-agent LangGraph workflow
│   │   └── mock_server/     # Local mock API server
│   ├── tests/               # Pytest automated test suites
│   ├── samples/             # Sample OpenAPI specs & payloads
│   ├── requirements.txt     # Pinned Python dependencies
│   └── .env.example         # Environment template
│
├── frontend/
│   ├── src/
│   │   ├── components/      # UI components
│   │   ├── pages/           # Application views
│   │   ├── api/             # API client & health queries
│   │   ├── context/         # React Context providers
│   │   ├── hooks/           # Custom React hooks
│   │   ├── types/           # TypeScript interfaces & types
│   │   ├── App.tsx          # Main diagnostics & dashboard view
│   │   └── main.tsx         # React DOM entrypoint
│   ├── index.html           # HTML template
│   ├── package.json         # Frontend dependencies & scripts
│   └── vite.config.ts       # Vite configuration with backend proxy
│
├── eval/                    # LLM workflow evaluation benchmarks
├── demo/                    # Interactive walkthroughs
├── docker-compose.yml       # Containerized deployment
├── README.md                # System documentation
└── .gitignore               # Ignored files and artifacts
```

---

## 3. Environment Configuration

Copy `backend/.env.example` to `backend/.env`:

```env
# Database (SQLite with WAL mode)
DATABASE_URL=sqlite:///./apiforge.db

# Ollama Local AI
OLLAMA_URL=http://localhost:11434
CHAT_MODEL=qwen2.5:7b-instruct
EMBED_MODEL=nomic-embed-text

# Security & Encryption
JWT_SECRET=change-this-secret-to-a-secure-random-string-min-32-chars
FERNET_KEY=generate-a-valid-fernet-key
ALLOWED_DOMAINS=
DEV_ALLOWED_HOSTS=localhost,127.0.0.1

# Server Settings
HOST=0.0.0.0
PORT=8000
CORS_ORIGINS=http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173
```

---

## 4. Ollama Setup

Ensure Ollama is installed and running locally:

```bash
# Verify Ollama service is active
ollama list

# Pull required local AI models
ollama pull qwen2.5:7b-instruct
ollama pull nomic-embed-text

# Optional lightweight fallback model:
ollama pull qwen2.5:3b
```

Verify that Ollama responds at:
```text
http://localhost:11434/api/tags
```

---

## 5. Backend Startup & Testing

### 1. Create and Activate Virtual Environment

```bash
# From repository root
cd backend
python -m venv .venv

# Windows PowerShell:
.\.venv\Scripts\Activate.ps1

# Linux / macOS:
source .venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run Backend Verification Tests

```bash
pytest -v
```

### 4. Start FastAPI Backend

```bash
# Using uvicorn from backend directory
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The API documentation is accessible at:
- Swagger UI: `http://localhost:8000/docs`
- Health Endpoint: `http://localhost:8000/health`

---

## 6. Frontend Startup

```bash
# From repository root
cd frontend

# Install dependencies
npm install

# Start Vite development server
npm run dev
```

The frontend will start at `http://localhost:5173` and automatically proxy `/health` and `/api` requests to the FastAPI backend running on port 8000.
