# APIForge AI — Autonomous Local API Workflow Platform

[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![React Flow](https://img.shields.io/badge/@xyflow/react-12.4+-ff0072.svg)](https://reactflow.dev/)
[![Ollama](https://img.shields.io/badge/Ollama-qwen2.5:7b--instruct-black.svg)](https://ollama.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**APIForge AI** converts natural-language instructions into structured, executable API workflows using locally hosted AI. It delivers enterprise-grade API orchestration, multi-agent planning with LangGraph, visual DAG canvases with React Flow, and zero-trust human-in-the-loop authorization gates without reliance on paid cloud LLMs or third-party AI APIs.

---

## 1. System Architecture

```text
                                  ┌───────────────────────────────┐
                                  │      Local Ollama Engine      │
                                  │  • Chat: qwen2.5:7b-instruct   │
                                  │  • Embed: nomic-embed-text    │
                                  └───────────────▲───────────────┘
                                                  │
                                                  ▼
┌───────────────────────┐         ┌───────────────────────────────┐         ┌───────────────────────┐
│   React + TS Frontend │ ◄─────► │   FastAPI Python 3.11 Backend │ ◄─────► │   SQLite (WAL Mode)   │
│  • Visual React Flow  │         │  • LangGraph Multi-Agent      │         │  • Cascade Deletes    │
│  • Approval Modals    │         │  • NetworkX DAG Engine        │         │  • Foreign Keys ON    │
│  • AI Recovery UI     │         │  • Secure HTTP Client (SSRF)  │         │  • Fernet Encryption  │
└───────────────────────┘         └───────────────────────────────┘         └───────────────────────┘
```

---

## 2. Non-Negotiable Engineering Principles

1. **Local-Only AI (Zero Cloud Dependencies):** Powered entirely by locally hosted Ollama (`http://localhost:11434`) using `qwen2.5:7b-instruct` for reasoning and `nomic-embed-text` for 768-dimensional vector embeddings.
2. **Plans Only, Never Code (Rule 1):** The LLM generates structured JSON plans exclusively. No arbitrary Python scripts, shell commands, or dynamically executed strings are produced.
3. **Rigorous Static Validation:** Every generated plan is statically validated via Pydantic v2 schemas and NetworkX DAG acyclicity analysis before persisting or executing.
4. **Single Hardened HTTP Client (SSRF Protection):** All outgoing HTTP requests pass through a centralized client that verifies IP address ranges, blocks cloud metadata hosts (`169.254.169.254`, `metadata.google.internal`), and masks sensitive headers in telemetry.
5. **Human-in-the-Loop Authorization Gate (Rule 8):** Any state-modifying operation (`POST`, `PUT`, `PATCH`, `DELETE`) **strictly pauses execution** in `waiting_approval` state until explicit human authorization is granted.
6. **AI Error Recovery with Confirmation (Rule 9):** When an API fails, local AI analyzes error payloads and proposes candidate fixes. Fixes are **never applied automatically**; explicit user confirmation is mandatory.
7. **Safe Data Transformation:** Zero Python `eval()` or `exec()`. Data calculations use `simpleeval` with strict symbol sandboxing and regex token replacement.
8. **User-Level Data Isolation:** Every query enforces user ownership checks across all database tables.

---

## 3. Technology Stack

- **Backend:** Python 3.11, FastAPI, SQLAlchemy 2.0, Pydantic v2, HTTPX, SQLite (WAL mode).
- **Orchestration & Graph:** LangGraph, NetworkX, SimpleEval, JSONSchema, JSONPath-ng.
- **Security:** Fernet symmetric encryption (`cryptography`), bcrypt, JWT (`python-jose`).
- **AI Models:** Ollama `qwen2.5:7b-instruct` (Chat & Reasoning), `nomic-embed-text` (Vector Embeddings).
- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS, `@xyflow/react` (React Flow), Lucide Icons, React Router v6.

---

## 4. Quickstart Guide

### Prerequisites
- Python 3.11+
- Node.js 20+
- [Ollama](https://ollama.com/) installed and running locally

### Step 1: Pull Local AI Models
```bash
ollama pull qwen2.5:7b-instruct
ollama pull nomic-embed-text
```

### Step 2: Configure Backend Environment
```bash
cd backend
cp .env.example .env
```
Key configuration in `.env`:
```env
DATABASE_URL=sqlite:///./apiforge.db
OLLAMA_URL=http://localhost:11434
CHAT_MODEL=qwen2.5:7b-instruct
EMBED_MODEL=nomic-embed-text
JWT_SECRET=apiforge-super-secret-jwt-key-change-in-production-min-32-chars
FERNET_KEY=J6Q20w8l6l_vG2g7yXJ1T-0t0lY9L8A2k8g7h5d4s3E=
DEBUG=True
DEV_ALLOWED_HOSTS=localhost,127.0.0.1
```

### Step 3: Install Backend Dependencies & Start
```bash
python -m venv .venv
.\.venv\Scripts\activate      # Windows
source .venv/bin/activate    # Linux/macOS
pip install -r requirements.txt

# Start FastAPI backend
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

### Step 4: Install Frontend Dependencies & Start
```bash
cd frontend
npm install
npm run dev
```

Navigate to `http://localhost:5173`.

---

## 5. Docker Deployment

Deploy with Docker Compose:
```bash
docker-compose up --build -d
```
- Frontend UI: `http://localhost:5173`
- Backend API Docs: `http://localhost:8000/docs`
- Health Endpoint: `http://localhost:8000/health`

---

## 6. Core Demonstration Walkthrough

APIForge AI is pre-configured with a local Mock Store API (`/mock/api/v1`) and OpenAPI specification to test the primary target scenario:

> **"Fetch product 5, calculate a 10% discount using SimpleEval, and create an order using the discounted price."**

### Execution Steps:
1. **Sign In:** Use demo account `demo@apiforge.ai` / `DemoSecurePass123!`.
2. **Setup Mock Connection:** In **API Connections** (`/connections`), click **"Connect Mock Store"** to import and embed endpoints.
3. **Generate Workflow:** In **AI Generator** (`/generator`), submit the prompt. The LangGraph multi-agent system extracts intent, links endpoints, validates formulas, and flags `POST /orders` for mandatory user approval.
4. **Visual Canvas:** Open in **Workflow Builder** (`/builder`) to inspect the connected React Flow nodes.
5. **Run Execution:** Start execution. Steps 1 & 2 finish instantly:
   - Step 1: Fetches Product 5 (`price: 1000.0`).
   - Step 2: SimpleEval calculates `1000.0 * 0.9 = 900.0`.
   - **Step 3 pauses with status `waiting_approval` (Rule 8)!**
6. **Human Authorization:** Review the computed final price `900.0` in the approval modal and click **"Authorize Step & Resume DAG"**.
7. **Order Confirmed:** Step 3 executes and returns `ORD-5001` with `final_price: 900.0`. Status updates to `completed`.
8. **AI Error Recovery:** If an API returns HTTP 404/422, click **"Diagnose with AI Agent"** to receive candidate fixes. Confirming applies the patch and resumes the pipeline (Rule 9).

For full step-by-step logs and screenshots, see [`demo/DEMO.md`](demo/DEMO.md).

---

## 7. API Endpoints Reference

| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/health` | Application, database & Ollama status | No |
| `POST` | `/auth/register` | Register new user account | No |
| `POST` | `/auth/token` | OAuth2 password login (JWT) | No |
| `GET` | `/auth/me` | Current authenticated user profile | Yes |
| `GET` | `/connections` | List user's API connections | Yes |
| `POST` | `/connections` | Create connection with encrypted credentials | Yes |
| `POST` | `/connections/{id}/import-openapi` | Import OpenAPI 3.0 / Swagger JSON | Yes |
| `POST` | `/connections/{id}/embed-all` | Batch embed endpoints with Ollama | Yes |
| `GET` | `/endpoints/search/semantic` | Vector similarity search for APIs | Yes |
| `POST` | `/workflows/generate` | Generate workflow plan via Ollama | Yes |
| `POST` | `/workflows/generate-multi-agent` | Generate via LangGraph multi-agent pipeline | Yes |
| `POST` | `/workflows/{id}/execute` | Launch topological DAG execution | Yes |
| `GET` | `/executions/{id}` | Inspect execution state and logs | Yes |
| `POST` | `/executions/{id}/approve` | **Rule 8:** Authorize pending step & resume DAG | Yes |
| `POST` | `/executions/{id}/reject` | Reject pending step & cancel execution | Yes |
| `POST` | `/executions/{id}/diagnose` | **Rule 9:** AI diagnostic root-cause recovery | Yes |
| `POST` | `/executions/{id}/apply-fix` | Apply user-confirmed candidate repair patch | Yes |
| `GET` | `/dashboard/summary` | Dashboard metrics and success counters | Yes |
| `GET` | `/admin/stats` | Global system metrics | Admin Only |
| `GET` | `/admin/audit-logs` | Comprehensive compliance audit trail | Admin Only |

---

## 8. Test Suite & Verification

The test suite covers unit, integration, SSRF security, and end-to-end DAG execution:

```bash
# Run all tests
.\.venv\Scripts\pytest.exe backend\tests -v
```

### Test Coverage Highlights:
- `test_db.py`: SQLite WAL mode, foreign keys, cascade deletes (16 passed).
- `test_auth.py`: Password hashing, Fernet symmetric encryption, JWT claims (11 passed).
- `test_connections.py`: API connection CRUD, OpenAPI dereferencing (6 passed).
- `test_openapi.py`: OpenAPI 3.0 parser, component resolution, mock store (6 passed).
- `test_embeddings.py`: Cosine similarity, Ollama vector embeddings (6 passed).
- `test_generator.py`: Plan Pydantic validation, DAG acyclicity, Rule 8 gates (6 passed).
- `test_ssrf.py`: SSRF prevention, cloud metadata blocking, IP ranges (4 passed).
- `test_executor.py`: SimpleEval safe math, DAG topological sort, Rule 8 flow (5 passed).
- `test_validation.py`: JSONSchema response validation, error classifier (5 passed).
- `test_errors.py`: AI error diagnosis, candidate fix generation, apply-fix recovery (3 passed).
- `test_agents.py`: LangGraph multi-agent orchestrator, intent detection (3 passed).
- `test_dashboard_admin.py`: Summary metrics, admin RBAC, audit log queries (3 passed).
- `test_security.py`: Secret masking, Fernet key integrity, SQL injection safety (6 passed).

---

## 9. Evaluation Benchmark

Run the automated evaluation benchmark:
```bash
.\.venv\Scripts\python.exe eval\run_eval.py
```
Benchmark outputs are persisted to [`eval/results.md`](eval/results.md):
- **Pydantic Schema Validity:** 100.0%
- **DAG Acyclicity (NetworkX):** 100.0%
- **Rule 8 Approval Adherence:** 100.0%
- **Zero-Code Verification:** 100.0% JSON plans only, 0% raw code execution.

---

## 10. License

This project is licensed under the MIT License.
