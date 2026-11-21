import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Set test environment variables before importing app
os.environ["LLM_API_KEYS"] = "test_key_1,test_key_2"
os.environ["DATABASE_URL"] = "sqlite:///./test_app.db"
os.environ["ENABLE_FAILURE_SIMULATION"] = "true"
os.environ["MODEL_NAME"] = "gemini/gemini-2.0-flash"

from main import app
from database import init_db, get_connection
import llm_gateway

client = TestClient(app)

@pytest.fixture(autouse=True)
def clean_db():
    # Initialize fresh database before each test
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM messages;")
    conn.commit()
    conn.close()
    # Reset gateway cache
    if hasattr(llm_gateway.litellm_cache, "cache") and hasattr(llm_gateway.litellm_cache.cache, "flush_cache"):
        llm_gateway.litellm_cache.cache.flush_cache()
    elif hasattr(llm_gateway.litellm_cache, "cache") and hasattr(llm_gateway.litellm_cache.cache, "cache_dict"):
        llm_gateway.litellm_cache.cache.cache_dict.clear()
    yield

def create_mock_completion_response(content="Paris is the capital of France.", prompt_tokens=15, completion_tokens=8):
    mock_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_resp.choices = [mock_choice]
    
    mock_usage = MagicMock()
    mock_usage.prompt_tokens = prompt_tokens
    mock_usage.completion_tokens = completion_tokens
    mock_resp.usage = mock_usage
    mock_resp._hidden_params = {"is_cache_hit": False}
    return mock_resp

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["keys_configured"] == 2
    assert data["cache_enabled"] is True

def test_chat_validation_errors():
    # Empty message
    resp = client.post("/chat", json={"session_id": "s-1", "message": "   "})
    assert resp.status_code == 422
    assert "detail" in resp.json()

    # Message exceeding 4000 chars
    long_msg = "x" * 4001
    resp = client.post("/chat", json={"session_id": "s-1", "message": long_msg})
    assert resp.status_code == 422
    assert "detail" in resp.json()

    # Missing session_id
    resp = client.post("/chat", json={"message": "hello"})
    assert resp.status_code == 422
    assert "detail" in resp.json()

@patch("litellm.completion")
def test_chat_live_inference_and_caching(mock_litellm):
    mock_litellm.return_value = create_mock_completion_response("Paris is the capital of France.", 20, 8)

    # 1. First call in session 1 -> LIVE_INFERENCE
    payload = {"session_id": "session-1", "message": "What is the capital of France?"}
    resp1 = client.post("/chat", json=payload)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["session_id"] == "session-1"
    assert data1["reply"] == "Paris is the capital of France."
    assert data1["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert data1["metadata"]["key_id"] == "key_1"
    assert data1["metadata"]["fallback_attempts"] == 0
    assert data1["metadata"]["input_tokens"] == 20
    assert data1["metadata"]["output_tokens"] == 8
    assert data1["metadata"]["latency_ms"] >= 1
    assert mock_litellm.call_count == 1

    # 2. Second call with identical message in a NEW session -> LLM_CACHE
    payload_new_session = {"session_id": "session-2", "message": "What is the capital of France?"}
    resp2 = client.post("/chat", json=payload_new_session)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["session_id"] == "session-2"
    assert data2["reply"] == "Paris is the capital of France."
    assert data2["metadata"]["resolution_source"] == "LLM_CACHE"
    assert data2["metadata"]["key_id"] is None
    assert data2["metadata"]["fallback_attempts"] == 0
    assert data2["metadata"]["input_tokens"] == 20
    assert data2["metadata"]["output_tokens"] == 8
    # LiteLLM was NOT called again because cache hit!
    assert mock_litellm.call_count == 1

    # 3. Third call with DIFFERENT message -> LIVE_INFERENCE
    mock_litellm.return_value = create_mock_completion_response("Berlin is the capital of Germany.", 22, 7)
    payload_diff = {"session_id": "session-3", "message": "What is the capital of Germany?"}
    resp3 = client.post("/chat", json=payload_diff)
    assert resp3.status_code == 200
    data3 = resp3.json()
    assert data3["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert data3["metadata"]["key_id"] == "key_1"
    assert mock_litellm.call_count == 2

@patch("litellm.completion")
def test_failover_single_key(mock_litellm):
    mock_litellm.return_value = create_mock_completion_response("Failover successful answer.", 25, 5)

    # Request with X-Simulate-Failure: key_1=429
    headers = {"X-Simulate-Failure": "key_1=429"}
    payload = {"session_id": "failover-test-1", "message": "Test failover"}
    
    resp = client.post("/chat", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["metadata"]["key_id"] == "key_2"
    assert data["metadata"]["fallback_attempts"] == 1
    assert data["metadata"]["resolution_source"] == "LIVE_INFERENCE"

@patch("litellm.completion")
def test_failover_all_keys_503(mock_litellm):
    # Request with X-Simulate-Failure: *=429 (all keys fail)
    headers = {"X-Simulate-Failure": "*=429"}
    payload = {"session_id": "failover-all-fail", "message": "This request should fail"}
    
    resp = client.post("/chat", json=payload, headers=headers)
    assert resp.status_code == 503
    assert resp.json() == {"detail": "all providers unavailable"}

    # Verify that failed request was NOT added to session history
    session_resp = client.get("/sessions/failover-all-fail/messages")
    assert session_resp.status_code == 404

@patch("litellm.completion")
def test_session_messages_history(mock_litellm):
    mock_litellm.return_value = create_mock_completion_response("The capital of France is Paris.", 42, 9)

    # Unknown session returns 404
    resp_404 = client.get("/sessions/unknown-session-123/messages")
    assert resp_404.status_code == 404
    assert resp_404.json() == {"detail": "session not found"}

    # Send message to create session
    client.post("/chat", json={"session_id": "s-7f3a", "message": "What is the capital of France?"})

    # Query history
    resp_history = client.get("/sessions/s-7f3a/messages")
    assert resp_history.status_code == 200
    data = resp_history.json()
    assert data["session_id"] == "s-7f3a"
    assert len(data["messages"]) == 2
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][0]["content"] == "What is the capital of France?"
    assert data["messages"][1]["role"] == "assistant"
    assert data["messages"][1]["content"] == "The capital of France is Paris."
    assert data["messages"][1]["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert data["messages"][1]["metadata"]["input_tokens"] == 42
    assert data["messages"][1]["metadata"]["output_tokens"] == 9

@patch("litellm.completion")
def test_multi_turn_context_sent_to_llm(mock_litellm):
    mock_litellm.return_value = create_mock_completion_response("Answer 1", 10, 5)

    # Message 1
    client.post("/chat", json={"session_id": "multi-turn-1", "message": "Hello"})
    
    # Message 2
    mock_litellm.return_value = create_mock_completion_response("Answer 2", 20, 5)
    client.post("/chat", json={"session_id": "multi-turn-1", "message": "My name is Alice"})

    # Inspect the messages passed to litellm in the second call
    call_args = mock_litellm.call_args_list[-1]
    messages_passed = call_args[1]["messages"]
    
    # Check messages sequence: system prompt, user (Hello), assistant (Answer 1), user (My name is Alice)
    assert messages_passed[0]["role"] == "system"
    assert messages_passed[1]["role"] == "user"
    assert messages_passed[1]["content"] == "Hello"
    assert messages_passed[2]["role"] == "assistant"
    assert messages_passed[2]["content"] == "Answer 1"
    assert messages_passed[3]["role"] == "user"
    assert messages_passed[3]["content"] == "My name is Alice"
