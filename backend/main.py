from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, field_validator

from config import settings
from database import init_db, check_db_health, get_session_messages, get_session_history_for_llm, save_message
from llm_gateway import execute_chat_completion

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite database on startup
    init_db()
    yield

app = FastAPI(
    title="Lyftr AI Chatbot Backend",
    description="LLM Chatbot with Key Failover and Response Caching",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins if "*" not in settings.allowed_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom exception handler for 500 errors to ensure JSON response with detail
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"}
    )

# Models
class ChatRequest(BaseModel):
    session_id: str
    message: str
    system_prompt: Optional[str] = None

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        if not isinstance(v, str) or not (1 <= len(v) <= 128):
            raise ValueError("session_id must be a string between 1 and 128 characters")
        return v

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("message must be a string")
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("message cannot be empty after trimming whitespace")
        if len(trimmed) > 4000:
            raise ValueError("message cannot exceed 4000 characters")
        return trimmed

# Endpoints

@app.get("/health")
def health_check():
    """
    Returns 200 once the app is running, the database is reachable and the key pool is loaded.
    { "status": "ok", "keys_configured": 2, "cache_enabled": true }
    """
    db_ok = check_db_health()
    if not db_ok:
        raise HTTPException(status_code=500, detail="Database unreachable")

    keys_count = len(settings.api_keys)
    return {
        "status": "ok",
        "keys_configured": keys_count,
        "cache_enabled": True
    }

@app.post("/chat")
def chat_endpoint(
    req: ChatRequest,
    x_simulate_failure: Optional[str] = Header(None, alias="X-Simulate-Failure")
):
    """
    POST /chat
    Multi-turn conversation endpoint with LiteLLM gateway, caching, and failover.
    """
    # 1. Fetch multi-turn history from SQLite
    history = get_session_history_for_llm(req.session_id)

    # 2. Build full message list (system prompt + history + new user message)
    effective_system_prompt = req.system_prompt if req.system_prompt is not None else settings.DEFAULT_SYSTEM_PROMPT
    messages_payload: List[Dict[str, str]] = []
    
    if effective_system_prompt:
        messages_payload.append({"role": "system", "content": effective_system_prompt})
        
    messages_payload.extend(history)
    messages_payload.append({"role": "user", "content": req.message})

    # 3. Call LiteLLM Gateway (handles caching, fallback, tokens, latency, simulation)
    # If every key fails, execute_chat_completion raises HTTPException(status_code=503, detail="all providers unavailable")
    # A failed request is NOT added to session history.
    completion_result = execute_chat_completion(
        messages=messages_payload,
        simulate_failure_header=x_simulate_failure
    )

    # 4. Save to session history on success
    # User message
    save_message(
        session_id=req.session_id,
        role="user",
        content=req.message,
        metadata=None
    )

    # Assistant message metadata
    assistant_metadata = {
        "resolution_source": completion_result["resolution_source"],
        "input_tokens": completion_result["input_tokens"],
        "output_tokens": completion_result["output_tokens"]
    }
    save_message(
        session_id=req.session_id,
        role="assistant",
        content=completion_result["reply"],
        metadata=assistant_metadata
    )

    # 5. Build and return response
    return {
        "session_id": req.session_id,
        "reply": completion_result["reply"],
        "metadata": {
            "resolution_source": completion_result["resolution_source"],
            "model": completion_result["model"],
            "latency_ms": completion_result["latency_ms"],
            "input_tokens": completion_result["input_tokens"],
            "output_tokens": completion_result["output_tokens"],
            "key_id": completion_result["key_id"],
            "fallback_attempts": completion_result["fallback_attempts"]
        }
    }

@app.get("/sessions/{session_id}/messages")
def get_session_messages_endpoint(session_id: str):
    """
    Returns the stored history of one session from SQLite, oldest first, without the system prompt.
    Returns 404 {"detail": "session not found"} if unknown session.
    """
    messages = get_session_messages(session_id)
    if messages is None:
        raise HTTPException(status_code=404, detail="session not found")

    return {
        "session_id": session_id,
        "messages": messages
    }
