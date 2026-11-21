import hashlib
import json
import logging
import time
from typing import List, Dict, Any, Optional, Tuple
from fastapi import HTTPException
import litellm
from litellm.caching.caching import Cache
from config import settings

logger = logging.getLogger("llm_gateway")
logging.basicConfig(level=logging.INFO)

# Initialize LiteLLM's built-in local cache
litellm_cache = Cache(type="local")
litellm.cache = litellm_cache
try:
    litellm.enable_cache()
except Exception:
    pass

def set_in_cache(key: str, value: Any):
    if hasattr(litellm_cache, "cache") and hasattr(litellm_cache.cache, "set_cache"):
        litellm_cache.cache.set_cache(key, value)
    elif hasattr(litellm_cache, "set_cache"):
        litellm_cache.set_cache(key, value)

def get_from_cache(key: str) -> Optional[Any]:
    if hasattr(litellm_cache, "cache") and hasattr(litellm_cache.cache, "get_cache"):
        return litellm_cache.cache.get_cache(key)
    elif hasattr(litellm_cache, "get_cache"):
        return litellm_cache.get_cache(key)
    return None

def generate_cache_key(model: str, messages: List[Dict[str, str]]) -> str:
    """
    Cache key: model + the full message list sent to the LLM (system prompt + history + new message).
    """
    normalized_messages = [{"role": m["role"], "content": m["content"]} for m in messages]
    payload = json.dumps({"model": model, "messages": normalized_messages}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def parse_simulation_header(header_value: Optional[str]) -> Dict[str, int]:
    """
    Parses comma-separated <key_id>=<status> pairs; * means every key.
    Statuses: 429, 500, 502, 503.
    """
    if not header_value:
        return {}
    
    simulations: Dict[str, int] = {}
    pairs = [p.strip() for p in header_value.split(",") if p.strip()]
    for pair in pairs:
        if "=" in pair:
            key_id, status_str = pair.split("=", 1)
            key_id = key_id.strip()
            status_str = status_str.strip()
            try:
                status = int(status_str)
                simulations[key_id] = status
            except ValueError:
                continue
    return simulations

def execute_chat_completion(
    messages: List[Dict[str, str]],
    simulate_failure_header: Optional[str] = None
) -> Dict[str, Any]:
    """
    Orchestrates LiteLLM call with key pool, fallback, caching, and failure simulation.
    """
    start_time = time.perf_counter()
    model = settings.MODEL_NAME
    keys = settings.api_keys
    cache_key = generate_cache_key(model, messages)

    # Parse simulation header if enabled
    simulations = {}
    if settings.enable_failure_simulation and simulate_failure_header:
        simulations = parse_simulation_header(simulate_failure_header)

    # 1. Check Cache
    # If failure simulation is requested for all keys or specific keys, simulate behavior directly on keys.
    # When no failure simulation is active, check the cache first.
    is_simulation_active = bool(simulations)
    if not is_simulation_active:
        cached_result = get_from_cache(cache_key)
        if cached_result:
            latency_ms = max(1, int(round((time.perf_counter() - start_time) * 1000)))
            return {
                "reply": cached_result["reply"],
                "resolution_source": "LLM_CACHE",
                "model": cached_result.get("model", model),
                "latency_ms": latency_ms,
                "input_tokens": cached_result["input_tokens"],
                "output_tokens": cached_result["output_tokens"],
                "key_id": None,
                "fallback_attempts": 0
            }

    # 2. Iterate through Key Pool for Live Inference
    fallback_attempts = 0
    last_error = None

    for key_info in keys:
        key_id = key_info["id"]
        api_key = key_info["key"]

        # Check for simulated failure
        simulated_status = None
        if "*" in simulations:
            simulated_status = simulations["*"]
        elif key_id in simulations:
            simulated_status = simulations[key_id]

        if simulated_status in (429, 500, 502, 503):
            logger.info(f"Simulating failure HTTP {simulated_status} for {key_id}")
            fallback_attempts += 1
            last_error = f"Simulated {simulated_status}"
            continue

        # Execute Live Inference
        try:
            response = litellm.completion(
                model=model,
                messages=messages,
                api_key=api_key,
                caching=True
            )

            reply = response.choices[0].message.content or ""
            
            # Extract tokens
            usage = getattr(response, "usage", None)
            if usage:
                input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                output_tokens = getattr(usage, "completion_tokens", 0) or 0
            else:
                input_tokens = 0
                output_tokens = 0

            # Fallback estimation if provider returns 0
            if input_tokens == 0:
                try:
                    input_tokens = litellm.token_counter(model=model, messages=messages)
                except Exception:
                    input_tokens = sum(len(m.get("content", "").split()) for m in messages)
            if output_tokens == 0:
                try:
                    output_tokens = litellm.token_counter(model=model, text=reply)
                except Exception:
                    output_tokens = len(reply.split())

            # Check if LiteLLM itself served it from cache
            hidden_params = getattr(response, "_hidden_params", {}) or {}
            is_cache_hit = hidden_params.get("is_cache_hit", False)

            if is_cache_hit:
                resolution_source = "LLM_CACHE"
                final_key_id = None
                final_fallback = 0
            else:
                resolution_source = "LIVE_INFERENCE"
                final_key_id = key_id
                final_fallback = fallback_attempts

            # Store in cache for subsequent calls
            set_in_cache(
                cache_key,
                {
                    "reply": reply,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "model": model
                }
            )

            latency_ms = max(1, int(round((time.perf_counter() - start_time) * 1000)))

            return {
                "reply": reply,
                "resolution_source": resolution_source,
                "model": model,
                "latency_ms": latency_ms,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "key_id": final_key_id,
                "fallback_attempts": final_fallback
            }

        except Exception as e:
            fallback_attempts += 1
            last_error = str(e)
            logger.warning(f"Key {key_id} failed with error: {e}. Falling back to next key...")
            continue

    # 3. Every key failed
    logger.error(f"All keys failed. Last error: {last_error}")
    raise HTTPException(status_code=503, detail="all providers unavailable")
