# Lyftr AI Full-Stack Assignment: LLM Chatbot with Key Failover & Response Caching

A production-grade, resilient full-stack conversational AI application built with **React**, **FastAPI**, **SQLite**, and **LiteLLM Gateway**. Features automatic API key failover, deterministic sub-millisecond response caching, and isolated per-request token usage tracking.

---

## 1. Live URLs

| Service | Deployment Platform | URL / Link |
| :--- | :--- | :--- |
| **Frontend UI** | Vercel / Render | *[To be updated upon deployment]* (e.g., `https://lyftr-ai-chatbot.vercel.app`) |
| **Backend API** | Render / Railway | *[To be updated upon deployment]* (e.g., `https://lyftr-backend.onrender.com`) |
| **Backend Health** | Direct Health Check | *[To be updated upon deployment]* (e.g., `https://lyftr-backend.onrender.com/health`) |
| **GitHub Repository** | GitHub | [https://github.com/ambujyadav19/lyftr-ai-fullstack-chatbot](https://github.com/ambujyadav19/lyftr-ai-fullstack-chatbot) |
| **Demo Video** | Loom / Drive | *[2–3 min walk-through recording]* |

---

## 2. Run locally: with Docker and without

### Option A: Running with Docker (Recommended)

The entire application stack (FastAPI backend + React frontend + SQLite persistent volume) can be spun up with a single command:

```bash
# 1. Clone repository
git clone https://github.com/ambujyadav19/lyftr-ai-fullstack-chatbot.git
cd lyftr-ai-fullstack-chatbot

# 2. Configure environment variables
cp .env.example .env
# Edit .env and supply your LLM_API_KEYS (e.g. Gemini, OpenAI, or Groq keys)

# 3. Start containers using Makefile or docker-compose
make up
# Or: docker compose up -d --build
```

- **Frontend:** [http://localhost:3000](http://localhost:3000)
- **Backend:** [http://localhost:8000](http://localhost:8000)
- **Interactive API Docs (Swagger):** [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Check:** [http://localhost:8000/health](http://localhost:8000/health)

To stop the containers:
```bash
make down
# Or: docker compose down
```

---

### Option B: Running without Docker

#### 1. Backend Setup (FastAPI)

```bash
cd backend

# Create and activate virtual environment
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
# (Create .env or export variables)
export LLM_API_KEYS="your_key_1,your_key_2"
export DATABASE_URL="sqlite:///./data/app.db"
export ALLOWED_ORIGINS="http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173"
export ENABLE_FAILURE_SIMULATION="true"
export MODEL_NAME="gemini/gemini-2.0-flash"

# Run the backend server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

#### 2. Frontend Setup (React + Vite)

In a separate terminal:

```bash
cd frontend

# Install npm dependencies
npm install

# Run the development server
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) or [http://localhost:5173](http://localhost:5173) in your browser.

#### 3. Run Backend Tests

```bash
# From repository root or backend folder:
pytest -v backend/tests
```

---

## 3. Design decisions: key fallback, caching, SQLite session storage

### 1. Key Fallback & Auto-Failover
- **Pool Management:** Multiple API keys (`key_1`, `key_2`, ...) are parsed from `LLM_API_KEYS` in order.
- **Resilience Strategy:** Calls are orchestrated through LiteLLM. When a provider returns an HTTP 429 (rate-limit), quota exhaustion, or 5xx server error, the gateway automatically intercepts the exception, increments `fallback_attempts`, and transparently routes the request to the next available key in the pool.
- **Failover Hook (`X-Simulate-Failure`):** A request header can simulate failure on demand (`key_1=429`, `key_1=500`, `*=429`) without exhausting real API quotas. This hook is active only when `ENABLE_FAILURE_SIMULATION=true`.
- **Graceful Error Handling:** If every configured key fails, the endpoint returns a clean `503 {"detail": "all providers unavailable"}`. Under no circumstances is an unhandled exception or stack trace exposed to the user, and failed requests are never added to the SQLite history.

### 2. Response Caching
- **Deterministic Cache Key:** The cache key is a SHA-256 hash computed over `model` + the complete ordered sequence of messages sent to the LLM (including system prompt, history, and the new prompt):
  $$\text{CacheKey} = \text{SHA256}(\text{JSON}(\text{model}, \text{messages}))$$
- **LiteLLM Built-in Cache Integration:** Uses LiteLLM's local in-memory cache mechanism.
- **Hit vs. Miss Behavior:**
  - A repeated first message in a new session hits the cache and returns `resolution_source: "LLM_CACHE"`, `key_id: null`, and `fallback_attempts: 0` in sub-5ms latency.
  - A modified or new message triggers a cache miss, proceeding to live inference (`LIVE_INFERENCE`).
  - Cache hits preserve and report the original per-request token usage recorded during live generation.

### 3. SQLite Session Storage
- **Zero External Dependencies:** Built solely on SQLite as specified—no Redis or Postgres required.
- **Persistence Across Restarts:** The SQLite database file resides on a Docker volume (mounted at `/data/app.db`) configured through `DATABASE_URL`.
- **Multi-turn History Isolation:** Messages are partitioned by `session_id`. Each request loads prior conversation history for that session and appends the new exchange only upon a successful inference (status 200).
- **History Endpoint:** `GET /sessions/{session_id}/messages` returns chronological message history without the system prompt. Unknown sessions cleanly return `404 {"detail": "session not found"}`.

---

## 4. Verification: how to see failover, cache hits and per-message token usage

### 1. Verify Cache Hits (`LLM_CACHE`)
1. In the UI or via curl, send:
   ```bash
   curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"session_id": "s-test-1", "message": "What is the capital of France?"}'
   ```
   **Result:** `resolution_source` is `LIVE_INFERENCE`, `key_id` is `"key_1"`, `fallback_attempts: 0`.
2. Start a new session or send the identical prompt in session `s-test-2`:
   ```bash
   curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"session_id": "s-test-2", "message": "What is the capital of France?"}'
   ```
   **Result:** `resolution_source` is `LLM_CACHE`, `key_id` is `null`, `fallback_attempts: 0`, and latency is significantly lower (e.g. 1–4 ms vs 800+ ms).

### 2. Verify Key Failover (`X-Simulate-Failure: key_1=429`)
1. Send a request simulating key 1 exhaustion:
   ```bash
   curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -H "X-Simulate-Failure: key_1=429" \
     -d '{"session_id": "s-failover-1", "message": "Explain quantum computing in one sentence."}'
   ```
   **Result:** Status 200, `key_id` is `"key_2"`, `fallback_attempts: 1`.

2. Test all keys failing:
   ```bash
   curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -H "X-Simulate-Failure: *=429" \
     -d '{"session_id": "s-failover-2", "message": "Hello"}'
   ```
   **Result:** Status 503 with `{"detail": "all providers unavailable"}`. Session `s-failover-2` has nothing stored in SQLite.

### 3. Verify Per-Message Token Usage
- In the UI, each assistant message displays:
  - Input tokens (`meta-input-tokens`): Prompt tokens for that turn only (system prompt + history + current message).
  - Output tokens (`meta-output-tokens`): Completion tokens for that response only.
- Two equal-length first messages in two separate sessions report the exact same input token count, demonstrating that tokens are measured per request rather than as a running cumulative total.

---

## 5. Setup Used: your editor and AI tools

- **Editor & IDE:** Visual Studio Code / Antigravity IDE
- **Operating System:** Windows 11 / Linux container runtime
- **AI Tooling & Coding Assistants:** Google DeepMind Antigravity Agent, Gemini 2.0 Flash / Pro models
- **Python Environment:** Python 3.12, FastAPI, Uvicorn, LiteLLM, Pytest, HTTPX
- **Frontend Environment:** Node.js v20+, Vite, React 18/19, TypeScript, Lucide Icons

---

## 6. Bonus features (if any): what you added beyond the requirements and why

1. **Interactive Failover & Simulation Control in UI:**
   - Added an on-screen **Failover Test Hook** selector in the sidebar allowing evaluators to inject `X-Simulate-Failure: key_1=429`, `key_1=500`, or `*=429` directly from the browser UI without needing Postman or terminal curl commands.
2. **Real-time Backend Health Indicator:**
   - The UI automatically pings `GET /health` on mount, displaying an active status badge showing the number of configured keys and caching readiness.
3. **One-Click Session Reset (`New Session`):**
   - Built a sleek session management card in the sidebar that allows users to instantly generate a new session ID and test fresh conversation trees.
4. **Visual Badging for Resolution Source & Latency:**
   - Cache hits are styled with an energetic blue lightning badge (`LLM_CACHE`) and sub-millisecond response tag, while live inference shows an emerald badge (`LIVE_INFERENCE`).
5. **Comprehensive Automated Test Suite:**
   - 7 automated unit and integration tests covering contract compliance, input validation, multi-turn state preservation, fallback mechanics, and caching behavior.
