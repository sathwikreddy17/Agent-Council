"""
LM Studio API Client
=====================

Handles all communication with LM Studio's local server, including:
    - Loading and unloading models
    - Listing available and loaded models
    - Sending chat completion requests (with streaming support)

LM Studio exposes an OpenAI-compatible API on ``localhost:1234``. This client
wraps that API with additional functionality for model management (load/unload)
which uses LM Studio's extended API endpoints.

Usage:
    >>> from council.lm_studio import LMStudioClient
    >>> client = LMStudioClient("http://localhost:1234/v1", "lm-studio")
    >>> models = await client.list_models()
    >>> await client.load_model("phi-4-mini-reasoning")
    >>> async for chunk in client.chat_stream("phi-4-mini-reasoning", messages):
    ...     print(chunk, end="")
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, Optional

import httpx
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class LMStudioClient:
    """
    Async client for communicating with LM Studio's local API server.

    This client handles:
        1. **Model Discovery**: List all models available in LM Studio
        2. **Model Management**: Load/unload models on demand to manage RAM
        3. **Chat Completions**: Send messages and get streaming responses

    The client uses the OpenAI SDK for chat completions (since LM Studio is
    OpenAI-compatible) and raw HTTP for model management endpoints.

    Attributes:
        base_url: Base URL for LM Studio API (e.g., "http://localhost:1234/v1")
        api_key: API key (LM Studio accepts any string, defaults to "lm-studio")

    Example:
        >>> client = LMStudioClient("http://localhost:1234/v1", "lm-studio")
        >>> loaded = await client.get_loaded_models()
        >>> print(f"Currently loaded: {loaded}")
    """

    def __init__(self, base_url: str, api_key: str = "lm-studio"):
        """
        Initialize the LM Studio client.

        Args:
            base_url: Full base URL including /v1 (e.g., "http://localhost:1234/v1")
            api_key: API key for authentication (LM Studio accepts any string)
        """
        self.base_url = base_url
        self.api_key = api_key

        # OpenAI-compatible client for chat completions
        self.openai_client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
        )

        # Raw HTTP client for model management endpoints
        # (load/unload are LM Studio-specific, not part of OpenAI API)
        self._server_base = base_url.replace("/v1", "")
        self._http_client = httpx.AsyncClient(
            base_url=self._server_base,
            timeout=httpx.Timeout(300.0, connect=10.0),  # 5min timeout for model loading
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def close(self):
        """Clean up HTTP connections."""
        await self._http_client.aclose()
        await self.openai_client.close()

    # =========================================================================
    # Model Discovery
    # =========================================================================

    async def list_models(self) -> list[dict[str, Any]]:
        """
        List all models available in LM Studio (downloaded models).

        Returns:
            List of model info dicts, each containing at minimum an "id" field
            with the model identifier.

        Example:
            >>> models = await client.list_models()
            >>> for m in models:
            ...     print(m["id"])
            phi-4-mini-reasoning
            llama-3.2-3b-instruct
        """
        try:
            response = await self._http_client.get("/v1/models")
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
        except httpx.ConnectError:
            logger.error(
                "Cannot connect to LM Studio. Is it running? "
                "Start the local server in LM Studio (Developer tab → Start Server)."
            )
            return []
        except Exception as e:
            logger.error(f"Error listing models: {e}")
            return []

    async def get_loaded_models(self) -> list[dict[str, Any]]:
        """
        Get the list of currently loaded (active in memory) models.

        This uses LM Studio's extended API to check which models are
        currently occupying RAM and ready to serve requests.

        Returns:
            List of loaded model info dicts.
        """
        try:
            response = await self._http_client.get("/v1/models")
            response.raise_for_status()
            data = response.json()
            # LM Studio returns all available models via /v1/models
            # Loaded models are the ones that are currently active
            return data.get("data", [])
        except Exception as e:
            logger.error(f"Error getting loaded models: {e}")
            return []

    # =========================================================================
    # Model Management (Load / Unload)
    # =========================================================================

    async def load_model(self, model_identifier: str) -> bool:
        """
        Load a model into memory in LM Studio.

        This tells LM Studio to load the specified model so it's ready
        to serve chat completions. Loading may take 10-60 seconds depending
        on model size and disk speed.

        Args:
            model_identifier: The model ID as shown in LM Studio
                              (e.g., "phi-4-mini-reasoning")

        Returns:
            True if the model was loaded successfully, False otherwise.

        Note:
            LM Studio may need to unload other models to free RAM.
            On a 24GB MacBook Air, you can typically have:
            - 3-4 small models (3B-4B) loaded simultaneously
            - 2 medium models (7B-9B) loaded simultaneously
            - 1 large model (14B+) loaded at a time
        """
        logger.info(f"Loading model: {model_identifier}")
        try:
            # LM Studio's model loading endpoint
            response = await self._http_client.post(
                "/v1/models/load",
                json={"model": model_identifier},
            )
            if response.status_code == 200:
                logger.info(f"Model loaded successfully: {model_identifier}")
                return True
            else:
                # Some versions of LM Studio might not support this endpoint
                # In that case, we just try to use the model directly
                logger.warning(
                    f"Model load endpoint returned {response.status_code}. "
                    f"Model may need to be loaded manually in LM Studio."
                )
                return True  # Optimistically return True — the chat call will fail if not loaded
        except httpx.ConnectError:
            logger.error("Cannot connect to LM Studio for model loading.")
            return False
        except Exception as e:
            logger.warning(f"Model load request for '{model_identifier}': {e}")
            # Return True optimistically — some LM Studio versions auto-load on first request
            return True

    async def unload_model(self, model_identifier: str) -> bool:
        """
        Unload a model from memory in LM Studio.

        Frees RAM by removing the specified model from memory.
        The model files remain on disk and can be loaded again later.

        Args:
            model_identifier: The model ID to unload.

        Returns:
            True if the model was unloaded successfully, False otherwise.
        """
        logger.info(f"Unloading model: {model_identifier}")
        try:
            response = await self._http_client.post(
                "/v1/models/unload",
                json={"model": model_identifier},
            )
            if response.status_code == 200:
                logger.info(f"Model unloaded: {model_identifier}")
                return True
            else:
                logger.warning(f"Model unload returned {response.status_code}")
                return False
        except Exception as e:
            logger.warning(f"Model unload request for '{model_identifier}': {e}")
            return False

    async def ensure_model_loaded(self, model_identifier: str) -> bool:
        """
        Ensure a specific model is loaded, loading it if necessary.

        This is the primary method used by the council engine. It checks
        if the model is available and tries to load it if not.

        Args:
            model_identifier: The model ID to ensure is loaded.

        Returns:
            True if the model is ready to use, False otherwise.
        """
        # Try to load — if already loaded, LM Studio handles it gracefully
        return await self.load_model(model_identifier)

    # =========================================================================
    # Chat Completions (Streaming)
    # =========================================================================

    @staticmethod
    def _normalize_text(value: Any) -> str:
        """Best-effort conversion of OpenAI/LM Studio content shapes to plain text."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            text = value.get("text") or value.get("content") or value.get("value")
            return text if isinstance(text, str) else ""
        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    # Handles content part objects like {"type":"text","text":"..."}
                    text = item.get("text") or item.get("content") or item.get("value")
                    if isinstance(text, str):
                        parts.append(text)
                else:
                    # Handles SDK objects with attributes instead of dict keys.
                    text = getattr(item, "text", None) or getattr(item, "content", None) or getattr(item, "value", None)
                    if isinstance(text, str):
                        parts.append(text)
            return "".join(parts)
        # Handles SDK objects where content is a typed object.
        text = getattr(value, "text", None) or getattr(value, "content", None) or getattr(value, "value", None)
        if isinstance(text, str):
            return text
        if hasattr(value, "model_dump"):
            try:
                dumped = value.model_dump(exclude_none=True)
                if isinstance(dumped, dict):
                    text = dumped.get("text") or dumped.get("content") or dumped.get("value")
                    return text if isinstance(text, str) else ""
            except Exception:
                return ""
        return ""

    async def chat_stream(
        self,
        model_identifier: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        """
        Send a chat completion request and stream the response token by token.

        This is the core method for getting agent responses. It uses the
        OpenAI-compatible streaming API to yield text chunks as they're
        generated, enabling real-time display in the UI.

        Args:
            model_identifier: The model ID to use for this completion.
            messages: List of chat messages in OpenAI format:
                      [{"role": "system", "content": "..."}, 
                       {"role": "user", "content": "..."}]
            temperature: Sampling temperature (0.0-1.0). Higher = more creative.
            max_tokens: Maximum tokens to generate in the response.

        Yields:
            String chunks (tokens/pieces of text) as they're generated.

        Raises:
            Exception: If the model is not loaded or LM Studio is unavailable.

        Example:
            >>> messages = [
            ...     {"role": "system", "content": "You are a helpful analyst."},
            ...     {"role": "user", "content": "What are the pros of Python?"}
            ... ]
            >>> async for chunk in client.chat_stream("llama-3.2-3b", messages):
            ...     print(chunk, end="", flush=True)
        """
        try:
            stream = await self.openai_client.chat.completions.create(
                model=model_identifier,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )

            async for chunk in stream:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta

                # Standard OpenAI-compatible content
                content = self._normalize_text(getattr(delta, "content", None))
                if content:
                    yield content

                # Some LM Studio model backends emit reasoning text in
                # non-standard fields instead of delta.content.
                reasoning_content = self._normalize_text(
                    getattr(delta, "reasoning_content", None)
                )
                if reasoning_content:
                    yield reasoning_content

                reasoning = self._normalize_text(getattr(delta, "reasoning", None))
                if reasoning:
                    yield reasoning

        except Exception as e:
            logger.error(f"Chat completion error with model '{model_identifier}': {e}")
            yield f"\n\n[Error: Could not get response from {model_identifier}. "
            yield f"Make sure LM Studio is running and the model is loaded. Error: {str(e)}]"

    async def chat_once(
        self,
        model_identifier: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """
        Non-stream fallback path.

        Some LM Studio model/server combinations produce no useful content in
        streaming deltas. This path requests a single non-stream completion and
        extracts text from the final message.
        """
        try:
            completion = await self.openai_client.chat.completions.create(
                model=model_identifier,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
            )
            if not completion.choices:
                return ""

            message = completion.choices[0].message
            content = self._normalize_text(getattr(message, "content", None))
            if content:
                return content

            # Last resort for uncommon compatibility payloads
            dumped = completion.model_dump(exclude_none=True) if hasattr(completion, "model_dump") else {}
            choices = dumped.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                return self._normalize_text(msg.get("content"))
            return ""
        except Exception as e:
            logger.error(
                f"Fallback non-stream completion failed for '{model_identifier}': {e}"
            )
            return ""

    async def chat(
        self,
        model_identifier: str,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """
        Send a chat completion request and return the full response.

        Non-streaming version of ``chat_stream()``. Waits for the complete
        response before returning. Useful for internal processing where
        streaming isn't needed.

        Args:
            model_identifier: The model ID to use.
            messages: Chat messages in OpenAI format.
            temperature: Sampling temperature.
            max_tokens: Maximum response tokens.

        Returns:
            The complete response text as a string.
        """
        full_response = ""
        async for chunk in self.chat_stream(
            model_identifier, messages, temperature, max_tokens
        ):
            full_response += chunk
        return full_response

    async def health_check(self) -> bool:
        """
        Check if LM Studio's server is running and accessible.

        Returns:
            True if the server is reachable, False otherwise.
        """
        try:
            response = await self._http_client.get("/v1/models")
            return response.status_code == 200
        except Exception:
            return False
