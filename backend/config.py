import os
from typing import List
from dotenv import load_dotenv

load_dotenv()

class Settings:
    LLM_API_KEYS_RAW: str = os.getenv("LLM_API_KEYS", "dummy_key_1,dummy_key_2")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")
    ALLOWED_ORIGINS_RAW: str = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,*")
    ENABLE_FAILURE_SIMULATION_RAW: str = os.getenv("ENABLE_FAILURE_SIMULATION", "true")
    MODEL_NAME: str = os.getenv("MODEL_NAME", "gemini/gemini-2.0-flash")
    DEFAULT_SYSTEM_PROMPT: str = os.getenv("DEFAULT_SYSTEM_PROMPT", "You are a helpful and concise AI assistant.")

    @property
    def api_keys(self) -> List[dict]:
        """
        Parses comma-separated key pool.
        Key IDs are key_1, key_2, ... in this order.
        """
        keys = [k.strip() for k in self.LLM_API_KEYS_RAW.split(",") if k.strip()]
        if not keys:
            keys = ["dummy_key_1", "dummy_key_2"]
        return [{"id": f"key_{i + 1}", "key": k} for i, k in enumerate(keys)]

    @property
    def allowed_origins(self) -> List[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS_RAW.split(",") if origin.strip()]

    @property
    def enable_failure_simulation(self) -> bool:
        return self.ENABLE_FAILURE_SIMULATION_RAW.lower() in ("true", "1", "yes")

    @property
    def sqlite_db_path(self) -> str:
        """
        Extracts sqlite file path from DATABASE_URL.
        Supports sqlite:////data/app.db, sqlite:///data/app.db, or sqlite:///./app.db
        """
        url = self.DATABASE_URL
        if url.startswith("sqlite:////"):
            return "/" + url[11:].lstrip("/")
        elif url.startswith("sqlite:///"):
            return url[10:]
        elif url.startswith("sqlite://"):
            return url[9:]
        return url

settings = Settings()
