"""Ollama provider — LangChain-backed :class:`LLMProvider` implementation.

Inference is delegated to ``langchain_ollama.ChatOllama``.  The native Ollama
HTTP API is retained only for provider metadata endpoints that LangChain does
not expose:

* ``GET /api/tags``    — installed model listing
* ``GET /api/version`` — health probe

The provider boundary remains Gabriel-native: callers send and receive Gabriel
provider models, never LangChain messages or result objects.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
from collections.abc import AsyncIterator
from typing import Any, cast
from uuid import uuid4

import httpx
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import Runnable
from langchain_ollama import ChatOllama

from gabriel.gateway.providers.base import (
    ChatCompletionResult,
    ChatMessage,
    ModelInfo,
    ModelNotFoundError,
    ProviderConnectionError,
    ProviderError,
    ProviderHealth,
    StreamChunk,
    TokenUsage,
    ToolCallRequest,
)

DEFAULT_BASE_URL = "http://localhost:11434"


class OllamaProvider:
    """Gabriel provider adapter backed by LangChain's ``ChatOllama``.

    Tool schemas are bound to the model through ``ChatOllama.bind_tools()``.
    The provider only exposes tool-call requests; execution remains exclusively
    owned by Gabriel's governed ``ToolExecutor`` and PEEL pipeline.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout_seconds: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

        # Retained solely for /api/tags and /api/version.  It is intentionally
        # not used for inference because ChatOllama owns inference transport.
        self._transport = transport

    # ------------------------------------------------------------------
    # LLMProvider protocol
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def base_url(self) -> str:
        return self._base_url

    def _metadata_client(self) -> httpx.AsyncClient:
        """Return an HTTP client for native Ollama metadata endpoints only."""
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
        )

    def _client(
        self,
        *,
        model: str,
        temperature: float,
        max_tokens: int | None,
    ) -> ChatOllama:
        """Build a configured LangChain Ollama chat model.

        ``num_predict`` is Ollama's generation-length setting and corresponds
        to Gabriel's provider-neutral ``max_tokens`` argument.

        ``client_kwargs`` configures the underlying Ollama Python client's
        transport timeout without manually constructing an HTTP request.
        """
        if not model:
            raise ProviderError("Ollama chat requires a model name")

        kwargs: dict[str, Any] = {
            "model": model,
            "base_url": self._base_url,
            "temperature": temperature,
            "client_kwargs": {"timeout": self._timeout},
        }

        if max_tokens is not None:
            kwargs["num_predict"] = max_tokens

        return ChatOllama(**kwargs)

    async def chat_completion(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
    ) -> ChatCompletionResult:
        """Generate one complete model response through LangChain."""
        llm = self._client(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        logger.debug("chat_completion: %d tool spec(s) bound", len(tools or []))

        runnable = self._bind_runtime_options(
            llm,
            tools=tools,
            options=options,
        )
        langchain_messages = self._to_langchain_messages(messages)

        try:
            response = await runnable.ainvoke(langchain_messages)
        except Exception as exc:  # mapped at the provider boundary
            self._raise_langchain_error(exc, model)

        if not isinstance(response, AIMessage):
            raise ProviderError(
                "Ollama returned an unexpected LangChain response type: "
                f"{type(response).__name__}"
            )

        return ChatCompletionResult(
            content=self._message_content(response),
            model=self._response_model(response, fallback=model),
            usage=self._usage_from_message(response),
            tool_calls=self._tool_calls_from_message(response),
            finish_reason=self._finish_reason(response),
            raw=self._response_raw(response),
        )

    async def stream_chat_completion(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        options: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a completion through LangChain's ``astream`` API."""
        llm = self._client(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        logger.debug("stream_chat_completion: %d tool spec(s) bound", len(tools or []))

        runnable = self._bind_runtime_options(
            llm,
            tools=tools,
            options=options,
        )
        langchain_messages = self._to_langchain_messages(messages)

        gathered: AIMessageChunk | None = None
        try:
            async for chunk in runnable.astream(langchain_messages):
                if not isinstance(chunk, AIMessageChunk):
                    continue

                # Accumulate chunks so that streamed tool-call argument
                # fragments merge into complete tool calls. When Ollama streams
                # a tool call, each chunk carries only a partial ``args``
                # fragment, so ``chunk.tool_calls`` on any single chunk has
                # empty/incomplete arguments. Complete tool calls are only
                # available from the aggregated message.
                gathered = chunk if gathered is None else gathered + chunk

                # Stream text deltas immediately for responsive output, but do
                # not emit partial tool calls here; they are surfaced once fully
                # merged in the terminal chunk below.
                yield StreamChunk(
                    delta=self._message_content(chunk),
                    done=False,
                    model=self._response_model(chunk, fallback=model),
                    usage=None,
                    tool_calls=(),
                    finish_reason=None,
                )
        except Exception as exc:  # mapped at the provider boundary
            self._raise_langchain_error(exc, model)

        # LangChain does not guarantee that every provider emits a distinct
        # terminal chunk. Gabriel's stream contract does require one. The fully
        # merged tool calls are emitted here so callers receive complete
        # arguments in a single, well-formed batch.
        yield StreamChunk(
            delta="",
            done=True,
            model=model,
            usage=None,
            tool_calls=(
                self._tool_calls_from_message(gathered) if gathered is not None else ()
            ),
            finish_reason="stop",
        )

    async def list_models(self) -> list[ModelInfo]:
        """List locally installed Ollama models via its metadata API."""
        try:
            async with self._metadata_client() as client:
                response = await client.get("/api/tags")
        except (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
        ) as exc:
            raise ProviderConnectionError(
                f"Cannot reach Ollama at {self._base_url}: {exc}"
            ) from exc

        self._raise_for_status(response, model=None)

        models = response.json().get("models") or []
        return [
            ModelInfo(
                name=item.get("name", ""),
                provider=self.name,
                metadata={
                    "size": item.get("size"),
                    "modified_at": item.get("modified_at"),
                    "details": item.get("details", {}),
                },
            )
            for item in models
        ]

    async def health_check(self) -> ProviderHealth:
        """Check native Ollama daemon health without running inference."""
        try:
            async with self._metadata_client() as client:
                response = await client.get("/api/version")
        except httpx.HTTPError as exc:
            return ProviderHealth(
                provider=self.name,
                healthy=False,
                detail=f"Cannot reach Ollama at {self._base_url}: {exc}",
            )

        if response.status_code == 200:
            version = response.json().get("version", "unknown")
            return ProviderHealth(
                provider=self.name,
                healthy=True,
                detail=f"ollama {version} at {self._base_url}",
            )

        return ProviderHealth(
            provider=self.name,
            healthy=False,
            detail=f"HTTP {response.status_code} from {self._base_url}",
        )

    # ------------------------------------------------------------------
    # LangChain binding and Gabriel ↔ LangChain conversion
    # ------------------------------------------------------------------

    def _bind_runtime_options(
        self,
        llm: ChatOllama,
        *,
        tools: list[dict[str, Any]] | None,
        options: dict[str, Any] | None,
    ) -> Runnable[list[BaseMessage], AIMessage]:
        """Bind generation options and tool schemas to an Ollama model.

        ``bind_tools`` exposes schemas to the model, but it does not execute
        tools. Gabriel's ``ChatRuntimeService`` remains responsible for
        authorization, PEEL evaluation, approval, auditing, and execution.
        """
        runnable: Runnable[list[BaseMessage], AIMessage] = cast(
            Runnable[list[BaseMessage], AIMessage],
            llm,
        )

        if options:
            runnable = cast(
                Runnable[list[BaseMessage], AIMessage],
                runnable.bind(**options),
            )

        if tools:
            runnable = cast(
                Runnable[list[BaseMessage], AIMessage],
                llm.bind_tools(tools),
            )

            # Preserve additional runtime options after binding tools.
            if options:
                runnable = cast(
                    Runnable[list[BaseMessage], AIMessage],
                    runnable.bind(**options),
                )

        return runnable

    def _to_langchain_messages(
        self,
        messages: list[ChatMessage],
    ) -> list[BaseMessage]:
        """Convert Gabriel's neutral message history to LangChain messages."""
        return [self._to_langchain_message(message) for message in messages]

    def _to_langchain_message(self, message: ChatMessage) -> BaseMessage:
        """Convert one Gabriel message to its concrete LangChain equivalent."""
        if message.role == "system":
            return SystemMessage(content=message.content)

        if message.role == "user":
            return HumanMessage(content=message.content)

        if message.role == "assistant":
            return AIMessage(
                content=message.content,
                tool_calls=[
                    {
                        "id": call.id,
                        "name": call.name,
                        "args": call.arguments,
                        "type": "tool_call",
                    }
                    for call in message.tool_calls
                ],
            )

        if message.role == "tool":
            if not message.tool_call_id:
                raise ProviderError(
                    "Gabriel tool messages require a tool_call_id before "
                    "they can be sent to Ollama."
                )

            return ToolMessage(
                content=message.content,
                tool_call_id=message.tool_call_id,
                name=message.name,
            )

        raise ProviderError(f"Unsupported Gabriel message role: {message.role!r}")

    @staticmethod
    def _message_content(message: AIMessage | AIMessageChunk) -> str:
        """Normalize LangChain's string-or-content-block response content."""
        content = message.content

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            text_parts: list[str] = []
            for block in content:
                if isinstance(block, str):
                    text_parts.append(block)
                elif isinstance(block, dict) and isinstance(block.get("text"), str):
                    text_parts.append(block["text"])
            return "".join(text_parts)

        return str(content)

    @staticmethod
    def _tool_calls_from_message(
        message: AIMessage | AIMessageChunk,
    ) -> tuple[ToolCallRequest, ...]:
        """Normalize LangChain tool calls into Gabriel tool-call requests."""
        calls: list[ToolCallRequest] = []

        for call in message.tool_calls:
            name = call.get("name")
            if not isinstance(name, str) or not name:
                continue

            raw_arguments = call.get("args") or {}
            arguments = raw_arguments if isinstance(raw_arguments, dict) else {}

            call_id = call.get("id")
            calls.append(
                ToolCallRequest(
                    id=str(call_id or uuid4()),
                    name=name,
                    arguments=arguments,
                )
            )

        return tuple(calls)

    @staticmethod
    def _usage_from_message(message: AIMessage) -> TokenUsage:
        """Extract usage metadata when Ollama/LangChain makes it available."""
        usage = message.usage_metadata or {}

        return TokenUsage(
            prompt_tokens=int(usage.get("input_tokens") or 0),
            completion_tokens=int(usage.get("output_tokens") or 0),
        )

    @staticmethod
    def _response_model(
        message: AIMessage | AIMessageChunk,
        *,
        fallback: str,
    ) -> str:
        """Extract model metadata without leaking LangChain response types."""
        metadata = message.response_metadata or {}

        model = (
            metadata.get("model")
            or metadata.get("model_name")
            or metadata.get("model_id")
        )
        return str(model) if model else fallback

    @staticmethod
    def _finish_reason(message: AIMessage) -> str:
        """Map LangChain/Ollama completion metadata to Gabriel's contract."""
        metadata = message.response_metadata or {}

        return str(
            metadata.get("done_reason") or metadata.get("finish_reason") or "stop"
        )

    @staticmethod
    def _response_raw(message: AIMessage) -> dict[str, Any]:
        """Return serializable provider metadata for Gabriel observability."""
        return {
            "response_metadata": dict(message.response_metadata or {}),
            "usage_metadata": dict(message.usage_metadata or {}),
            "additional_kwargs": dict(message.additional_kwargs or {}),
        }

    # ------------------------------------------------------------------
    # Error mapping
    # ------------------------------------------------------------------

    def _raise_langchain_error(self, exc: Exception, model: str) -> None:
        """Map LangChain and underlying Ollama transport errors to Gabriel."""
        message = str(exc)
        lowered = message.lower()

        if any(
            marker in lowered
            for marker in (
                "connection refused",
                "connecterror",
                "connect timeout",
                "read timeout",
                "timed out",
                "cannot connect",
            )
        ):
            raise ProviderConnectionError(
                f"Cannot reach Ollama at {self._base_url}: {message}"
            ) from exc

        if "not found" in lowered and ("model" in lowered or model.lower() in lowered):
            raise ModelNotFoundError(
                f"Model '{model}' is not available on Ollama ({message})"
            ) from exc

        raise ProviderError(f"Ollama inference failed: {message}") from exc

    @staticmethod
    def _raise_for_status(
        response: httpx.Response,
        model: str | None,
    ) -> None:
        """Preserve existing native-HTTP error semantics for metadata calls."""
        if response.status_code < 400:
            return

        detail = ""
        try:
            detail = response.json().get("error", "")
        except ValueError:
            detail = response.text[:200]

        if response.status_code == 404 and model and "not found" in detail.lower():
            raise ModelNotFoundError(
                f"Model '{model}' is not available on Ollama ({detail})"
            )

        raise ProviderError(
            f"Ollama request failed with HTTP {response.status_code}: {detail}"
        )
