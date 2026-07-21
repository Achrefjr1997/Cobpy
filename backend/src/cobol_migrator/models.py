from __future__ import annotations

import logging
from typing import Literal, TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel

from cobol_migrator.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

TaskType = Literal["translate", "judge", "planner", "analyze", "reflect"]


def get_chat_model(task: TaskType) -> BaseChatModel:
    """
    Get a chat model for the specified task based on current provider configuration.
    
    Returns a LangChain chat model configured for the task.
    """
    provider = settings.llm_provider
    model_name = settings.get_model(task)

    logger.info(f"Creating {provider} model '{model_name}' for task '{task}'")

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model_name,
            api_key=settings.openai_api_key,
            temperature=0.0 if task in ("translate", "judge") else 0.2,
        )

    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model_name,
            api_key=settings.anthropic_api_key,
            temperature=0.0 if task in ("translate", "judge") else 0.2,
        )

    elif provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=settings.google_api_key,
            temperature=0.0 if task in ("translate", "judge") else 0.2,
        )

    elif provider == "xai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model_name,
            api_key=settings.xai_api_key,
            base_url="https://api.x.ai/v1",
            temperature=0.0 if task in ("translate", "judge") else 0.2,
        )

    elif provider == "fireworks":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model_name,
            api_key=settings.fireworks_api_key,
            base_url="https://api.fireworks.ai/inference/v1",
            temperature=0.0 if task in ("translate", "judge") else 0.2,
            max_tokens=65536 if task == "translate" else None,
        )

    else:
        raise ValueError(f"Unsupported provider: {provider}")


def get_structured_model(task: TaskType, output_schema: type[T]) -> BaseChatModel:
    """
    Get a chat model configured for structured output.
    
    Args:
        task: The task type (translate, judge, planner, analyze, reflect)
        output_schema: Pydantic model class for structured output
    
    Returns:
        A LangChain chat model with structured output configured
    """
    model = get_chat_model(task)
    return model.with_structured_output(output_schema)
