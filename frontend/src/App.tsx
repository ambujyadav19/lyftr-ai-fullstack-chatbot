import React, { useState, useEffect, useRef } from 'react';
import { 
  Send, 
  RotateCcw, 
  Zap, 
  Database, 
  Server, 
  ShieldAlert, 
  Layers, 
  CheckCircle2, 
  AlertTriangle,
  Cpu,
  Clock,
  Coins
} from 'lucide-react';
import './App.css';

interface AssistantMetadata {
  resolution_source: 'LIVE_INFERENCE' | 'LLM_CACHE';
  model: string;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  key_id?: string | null;
  fallback_attempts?: number;
}

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  metadata?: AssistantMetadata;
}

interface HealthStatus {
  status: string;
  keys_configured: number;
  cache_enabled: boolean;
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

function generateSessionId(): string {
  return 's-' + Math.random().toString(36).substring(2, 10);
}

export const App: React.FC = () => {
  // A new session starts on each page load
  const [sessionId, setSessionId] = useState<string>(() => generateSessionId());
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState<string>('');
  const [systemPrompt, setSystemPrompt] = useState<string>('');
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  
  // Failure simulation selector for manual testing
  const [simulateFailureHeader, setSimulateFailureHeader] = useState<string>('none');
  const [customSimulateHeader, setCustomSimulateHeader] = useState<string>('');

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading, errorMessage]);

  // Check backend health on mount
  useEffect(() => {
    const checkHealth = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/health`);
        if (res.ok) {
          const data: HealthStatus = await res.json();
          setHealth(data);
        } else {
          setHealth(null);
        }
      } catch (err) {
        setHealth(null);
      }
    };
    checkHealth();
  }, []);

  const handleNewSession = () => {
    setSessionId(generateSessionId());
    setMessages([]);
    setErrorMessage(null);
  };

  const getEffectiveSimulateHeader = (): string | null => {
    if (simulateFailureHeader === 'custom') {
      return customSimulateHeader.trim() || null;
    }
    if (simulateFailureHeader !== 'none') {
      return simulateFailureHeader;
    }
    return null;
  };

  const handleSendMessage = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const trimmed = inputValue.trim();
    if (!trimmed || isLoading) return;

    // Clear input field immediately after sending
    setInputValue('');
    setErrorMessage(null);

    // Add user message to UI
    const userMsg: Message = {
      id: 'msg-' + Date.now() + '-user',
      role: 'user',
      content: trimmed
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);

    try {
      const headers: Record<string, string> = {
        'Content-Type': 'application/json'
      };

      const simulateHeader = getEffectiveSimulateHeader();
      if (simulateHeader) {
        headers['X-Simulate-Failure'] = simulateHeader;
      }

      const payload: { session_id: string; message: string; system_prompt?: string } = {
        session_id: sessionId,
        message: trimmed
      };

      if (systemPrompt.trim()) {
        payload.system_prompt = systemPrompt.trim();
      }

      const response = await fetch(`${API_BASE_URL}/chat`, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        let errorDetail = 'Unknown error occurred';
        try {
          const errData = await response.json();
          if (errData && errData.detail) {
            errorDetail = typeof errData.detail === 'string' 
              ? errData.detail 
              : JSON.stringify(errData.detail);
          }
        } catch {
          errorDetail = `Request failed with status ${response.status} (${response.statusText})`;
        }
        setErrorMessage(`HTTP ${response.status}: ${errorDetail}`);
        return;
      }

      const data = await response.json();
      const assistantMsg: Message = {
        id: 'msg-' + Date.now() + '-assistant',
        role: 'assistant',
        content: data.reply,
        metadata: data.metadata
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: any) {
      setErrorMessage(`Network Error: ${err.message || 'Could not connect to backend server'}`);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const activeSimulateHeader = getEffectiveSimulateHeader();

  return (
    <div className="app-container">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <div className="brand-title">
            <Zap size={22} color="#4f46e5" />
            <span>Lyftr AI</span>
            <span className="brand-badge">PRO</span>
          </div>
          {health ? (
            <div className="health-status-badge status-online" title={`${health.keys_configured} keys active, cache enabled`}>
              <span className="status-dot"></span>
              Online
            </div>
          ) : (
            <div className="health-status-badge status-offline" title="Backend not reachable">
              <span className="status-dot"></span>
              Offline
            </div>
          )}
        </div>

        <div className="sidebar-content">
          {/* Session Details */}
          <div className="sidebar-section">
            <span className="section-label">
              <Database size={14} /> Active Session
            </span>
            <div className="session-card">
              <span className="session-id-text">{sessionId}</span>
              <button 
                type="button" 
                className="btn-new-chat" 
                onClick={handleNewSession}
                title="Start a new chat session"
              >
                <RotateCcw size={14} /> New
              </button>
            </div>
          </div>

          {/* System Prompt Field */}
          <div className="sidebar-section">
            <span className="section-label">
              <Layers size={14} /> System Prompt (Optional)
            </span>
            <textarea
              data-testid="system-prompt-input"
              className="system-prompt-box"
              placeholder="e.g. You are a senior software architect..."
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
            />
          </div>

          {/* Key Failover Simulation Panel */}
          <div className="sidebar-section">
            <span className="section-label">
              <ShieldAlert size={14} /> Failover Test Hook
            </span>
            <div className="simulation-card">
              <label style={{ fontSize: '0.8rem', color: '#475569' }}>
                Simulate Header (X-Simulate-Failure):
              </label>
              <select 
                value={simulateFailureHeader} 
                onChange={(e) => setSimulateFailureHeader(e.target.value)}
              >
                <option value="none">None (Standard Operation)</option>
                <option value="key_1=429">key_1=429 (Rate Limit Key 1 → Fallback Key 2)</option>
                <option value="key_1=500">key_1=500 (500 Error Key 1 → Fallback Key 2)</option>
                <option value="*=429">*=429 (All Keys Fail → 503 Unavailable)</option>
                <option value="custom">Custom Header Value...</option>
              </select>

              {simulateFailureHeader === 'custom' && (
                <input
                  type="text"
                  placeholder="e.g. key_1=429,key_2=500"
                  value={customSimulateHeader}
                  onChange={(e) => setCustomSimulateHeader(e.target.value)}
                />
              )}
            </div>
          </div>

          {/* Architecture highlights */}
          <div className="sidebar-section" style={{ marginTop: 'auto' }}>
            <span className="section-label">
              <Server size={14} /> Gateway Info
            </span>
            <div style={{ fontSize: '0.78rem', color: '#64748b', lineHeight: 1.6 }}>
              <div>• <b>LiteLLM Gateway</b> with Key Pool</div>
              <div>• <b>In-Memory Caching</b> with exact SHA-256 keys</div>
              <div>• <b>Automatic Key Fallover</b> on 429/5xx</div>
              <div>• <b>SQLite Multi-turn</b> session storage</div>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Chat View */}
      <main className="chat-main">
        {/* Header */}
        <header className="chat-header">
          <div className="chat-header-info">
            <span className="chat-header-title">LLM Chatbot with Key Failover & Response Caching</span>
          </div>
          <div style={{ fontSize: '0.8rem', color: '#64748b' }}>
            Target Backend: <code style={{ color: '#4f46e5' }}>{API_BASE_URL}</code>
          </div>
        </header>

        {/* Message Feed */}
        <div className="chat-messages">
          {messages.length === 0 ? (
            <div className="welcome-screen">
              <div style={{ padding: 12, background: '#eef2ff', borderRadius: '50%' }}>
                <Zap size={32} color="#4f46e5" />
              </div>
              <h2 className="welcome-title">Lyftr AI Full-Stack Assistant</h2>
              <p className="welcome-desc">
                Test multi-turn conversational AI with automatic key failover resilience, 
                instant response caching, and granular per-request token tracking.
              </p>
              <div className="welcome-features">
                <div className="feature-pill">
                  <CheckCircle2 size={16} color="#10b981" />
                  <span>Dual Key Fallback</span>
                </div>
                <div className="feature-pill">
                  <Zap size={16} color="#0284c7" />
                  <span>Sub-millisecond Caching</span>
                </div>
                <div className="feature-pill">
                  <Database size={16} color="#8b5cf6" />
                  <span>SQLite Multi-turn State</span>
                </div>
                <div className="feature-pill">
                  <Coins size={16} color="#f59e0b" />
                  <span>Per-request Token Metrics</span>
                </div>
              </div>
            </div>
          ) : (
            messages.map((msg) => (
              <div 
                key={msg.id} 
                className={`message-row ${msg.role === 'user' ? 'message-user' : 'message-assistant'}`}
              >
                {msg.role === 'user' ? (
                  <div className="user-bubble">
                    {msg.content}
                  </div>
                ) : (
                  <div data-testid="assistant-message" className="assistant-container">
                    <div className="assistant-text">
                      {msg.content}
                    </div>

                    {msg.metadata && (
                      <div className="metadata-card">
                        {/* Resolution Source: LIVE_INFERENCE or LLM_CACHE */}
                        <span 
                          data-testid="meta-source" 
                          className={`meta-badge ${msg.metadata.resolution_source === 'LLM_CACHE' ? 'badge-cache' : 'badge-live'}`}
                        >
                          <Zap size={12} />
                          {msg.metadata.resolution_source}
                        </span>

                        {/* Model */}
                        <span className="meta-item">
                          <Cpu size={13} />
                          Model: <span data-testid="meta-model" className="meta-val">{msg.metadata.model}</span>
                        </span>

                        {/* Latency */}
                        <span className="meta-item">
                          <Clock size={13} />
                          Latency: <span data-testid="meta-latency" className="meta-val">{msg.metadata.latency_ms} ms</span>
                        </span>

                        {/* Input Tokens */}
                        <span className="meta-item">
                          <Coins size={13} />
                          In: <span data-testid="meta-input-tokens" className="meta-val">{msg.metadata.input_tokens}</span>
                        </span>

                        {/* Output Tokens */}
                        <span className="meta-item">
                          Out: <span data-testid="meta-output-tokens" className="meta-val">{msg.metadata.output_tokens}</span>
                        </span>

                        {/* Key Info & Fallbacks */}
                        {msg.metadata.key_id && (
                          <span className="meta-item" style={{ color: '#4f46e5' }}>
                            Key: <span className="meta-val">{msg.metadata.key_id}</span>
                          </span>
                        )}

                        {typeof msg.metadata.fallback_attempts === 'number' && msg.metadata.fallback_attempts > 0 && (
                          <span className="meta-item" style={{ color: '#d97706' }}>
                            Fallbacks: <span className="meta-val">{msg.metadata.fallback_attempts}</span>
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))
          )}

          {/* Loading Indicator */}
          {isLoading && (
            <div className="message-row message-assistant">
              <div className="loading-row">
                <div className="loading-dot"></div>
                <div className="loading-dot"></div>
                <div className="loading-dot"></div>
              </div>
            </div>
          )}

          {/* Error Message Display */}
          {errorMessage && (
            <div className="chat-error-card">
              <AlertTriangle size={18} />
              <span>{errorMessage}</span>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input Bar */}
        <div className="chat-input-container">
          {activeSimulateHeader && (
            <div className="active-simulation-indicator">
              <ShieldAlert size={14} />
              <span>Active Hook: <code>X-Simulate-Failure: {activeSimulateHeader}</code></span>
            </div>
          )}
          <form className="input-row" onSubmit={handleSendMessage}>
            <textarea
              data-testid="chat-input"
              className="chat-input-field"
              placeholder="Type your message... (Enter to send, Shift+Enter for new line)"
              rows={1}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isLoading}
            />
            <button
              type="submit"
              data-testid="send-button"
              className="btn-send"
              disabled={!inputValue.trim() || isLoading}
            >
              <Send size={18} />
              <span>Send</span>
            </button>
          </form>
        </div>
      </main>
    </div>
  );
};

export default App;
