from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # API Keys for LLM providers
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""
    xai_api_key: str = ""  # Grok
    fireworks_api_key: str = ""  # Fireworks AI

    # Primary provider selection
    llm_provider: Literal["openai", "anthropic", "google", "xai", "fireworks"] = "openai"

    # Model identifiers per task (provider-specific)
    # OpenAI models
    openai_translate_model: str = "gpt-4o"
    openai_judge_model: str = "gpt-4o"
    openai_planner_model: str = "gpt-4o"
    openai_analyze_model: str = "gpt-4o-mini"
    openai_reflect_model: str = "gpt-4o-mini"

    # Anthropic models
    anthropic_translate_model: str = "claude-sonnet-4-20250514"
    anthropic_judge_model: str = "claude-sonnet-4-20250514"
    anthropic_planner_model: str = "claude-sonnet-4-20250514"
    anthropic_analyze_model: str = "claude-haiku-4-20250514"
    anthropic_reflect_model: str = "claude-haiku-4-20250514"

    # Google models
    google_translate_model: str = "gemini-2.0-flash"
    google_judge_model: str = "gemini-2.0-flash"
    google_planner_model: str = "gemini-2.0-flash"
    google_analyze_model: str = "gemini-2.0-flash"
    google_reflect_model: str = "gemini-2.0-flash"

    # xAI/Grok models
    xai_translate_model: str = "grok-2"
    xai_judge_model: str = "grok-2"
    xai_planner_model: str = "grok-2"
    xai_analyze_model: str = "grok-2"
    xai_reflect_model: str = "grok-2"

    # Fireworks AI models
    fireworks_translate_model: str = "accounts/fireworks/models/llama-v3p1-405b-instruct"
    fireworks_judge_model: str = "accounts/fireworks/models/llama-v3p1-405b-instruct"
    fireworks_planner_model: str = "accounts/fireworks/models/llama-v3p1-405b-instruct"
    fireworks_analyze_model: str = "accounts/fireworks/models/llama-v3p1-405b-instruct"
    fireworks_reflect_model: str = "accounts/fireworks/models/llama-v3p1-405b-instruct"

    # CORS
    cors_origins: list[str] = ["http://localhost:5173"]

    # Database
    database_path: str = "data/migrations.db"

    # Data directory (for ZIP job extraction, logs, etc.)
    data_dir: str = "data"

    def get_model(
        self, task: Literal["translate", "judge", "planner", "analyze", "reflect"]
    ) -> str:
        """Get the model name for a specific task based on current provider."""
        return getattr(self, f"{self.llm_provider}_{task}_model")

    def get_api_key(self) -> str:
        """Get the API key for the current provider."""
        key_map = {
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
            "google": self.google_api_key,
            "xai": self.xai_api_key,
            "fireworks": self.fireworks_api_key,
        }
        return key_map[self.llm_provider]


settings = Settings()
