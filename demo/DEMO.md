# APIForge AI — Core Demonstration Walkthrough

This guide documents the complete end-to-end execution of the core APIForge AI demonstration scenario:

> **"Fetch product 5, calculate a 10% discount using SimpleEval, and create an order using the discounted price."**

---

## 1. Architecture Flow

```text
[User Prompt] 
      │
      ▼
[Ollama qwen2.5:7b-instruct]
      │
      ▼
[Structured JSON DAG Plan]
      │
      ├───────────────────────┬────────────────────────┐
      ▼                       ▼                        ▼
[Step 1: GET Product 5]  [Step 2: SimpleEval Math]  [Step 3: POST /orders]
price: 1000.0             price * 0.9 = 900.0       requires_approval: TRUE
      │                       │                        │
      └───────────────────────┴────────────────────────┘
                                                       │
                                        [Rule 8 Approval Gate]
                                                       │
                                    ┌──────────────────┴──────────────────┐
                                    ▼                                     ▼
                             [User Approves]                       [User Rejects]
                                    │                                     │
                                    ▼                                     ▼
                       [Order Confirmed: ORD-5001]              [Execution Cancelled]
```

---

## 2. Step-by-Step Walkthrough

### Step 1: Start Services

Ensure Ollama is running locally:
```bash
ollama run qwen2.5:7b-instruct
```

Start the FastAPI backend:
```bash
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Start the React frontend:
```bash
cd frontend && npm run dev
```

Navigate to: `http://localhost:5173`

---

### Step 2: Sign In

Sign in using the pre-seeded demo account:
- **Email:** `demo@apiforge.ai`
- **Password:** `DemoSecurePass123!`

---

### Step 3: Connect Mock Store API & Import OpenAPI Spec

1. Navigate to **API Connections** (`/connections`).
2. Click **"Connect Mock Store"** (or Add Connection: `http://127.0.0.1:8000/mock/api/v1`).
3. Click **"Embed"** to generate 768-dimensional vector representations with `nomic-embed-text`.
4. Inspect the imported endpoints in **API Explorer** (`/explorer`):
   - `GET /products/{id}` — Fetches product details (price, stock).
   - `POST /discounts/calculate` — Computes promotional savings.
   - `POST /orders` — Creates order with product ID and final price.

---

### Step 4: Generate Workflow Plan via AI

1. Navigate to **AI Generator** (`/generator`).
2. Select **Multi-Agent Mode (LangGraph)**.
3. Input the prompt:
   ```text
   Fetch product 5, calculate a 10% discount using SimpleEval, and create an order with the discounted price.
   ```
4. Click **Generate Workflow Plan**.
5. Observe the multi-agent trace:
   - `IntentDetectionAgent`: Identified read product, calculate discount, and state-modifying order creation.
   - `EndpointDiscoveryAgent`: Matched `/products/{id}` and `/orders` via cosine similarity.
   - `DataMappingAgent`: **Enforced Non-Negotiable Rule 8: Auto-flagged Step 3 (`POST /orders`) as `requires_approval=True`**.
   - `ValidationAgent`: Checked acyclicity via NetworkX and generated visual React Flow layout.

---

### Step 5: Visual DAG Inspection

1. Click **Open in Visual Builder** (`/builder`).
2. Observe the React Flow visual canvas:
   - **Node 1 (GET /products/{id}):** Parameter `id = 5`. Output: `{"id": 5, "price": 1000.0, "name": "Mechanical Gaming Keyboard"}`.
   - **Node 2 (Transform):** SimpleEval formula `price * 0.9` referencing `{{step_1.output.price}}`. Computed: `900.0`.
   - **Node 3 (POST /orders):** Body payload:
     ```json
     {
       "product_id": "{{step_1.output.id}}",
       "final_price": "{{step_2.output}}",
       "quantity": 1
     }
     ```
     **Gold Shield Badge:** `Approval Required` (Non-Negotiable Rule 8).

---

### Step 6: Execute Workflow & Observe Rule 8 Approval Gate

1. Click **Run Workflow** in the builder.
2. The UI navigates to `/executions/{id}`.
3. **Execution Execution Status: `waiting_approval`**:
   - Step 1 completes in ~12ms (fetched Product 5, price = 1000.0).
   - Step 2 completes in ~2ms (SimpleEval calculated 1000.0 * 0.9 = 900.0).
   - **Step 3 pauses!** The engine pauses before executing `POST /orders`.
4. **Approval Gate UI Card Appears**:
   > *"Rule 8 Human-in-the-Loop Approval Required: Step 'Create Order with Discount' requires explicit user authorization before sending POST request with payload `final_price: 900.0`."*
5. Click **"Authorize Step & Resume DAG"**.

---

### Step 7: Completed State & Telemetry

1. The DAG execution resumes immediately.
2. The secure HTTP client sends the authorized request to `POST http://127.0.0.1:8000/mock/api/v1/orders`.
3. Order confirmed:
   ```json
   {
     "order_id": "ORD-5001",
     "product_id": 5,
     "final_price": 900.0,
     "quantity": 1,
     "status": "confirmed"
   }
   ```
4. Status transitions to **COMPLETED**.
5. Audit log is updated with `action="step_approved"`.

---

### Step 8: AI Error Recovery (Rule 9 Verification)

To test the AI error recovery system:
1. Edit a node in Workflow Builder to request invalid product ID `999`.
2. Run execution: The workflow halts with status **FAILED** (HTTP 404).
3. Click **"Diagnose with AI Agent"**:
   - `qwen2.5:7b-instruct` analyzes the error details and execution context.
   - Diagnoses root cause: *"Resource with ID 999 does not exist in mock store database."*
   - Proposes Candidate Fix: *"Update parameter `id` to 5."*
4. Click **"Confirm & Apply Fix"** (Rule 9: human confirmation required).
5. The workflow node is patched, the failure cleared, and the workflow resumes to completion!
