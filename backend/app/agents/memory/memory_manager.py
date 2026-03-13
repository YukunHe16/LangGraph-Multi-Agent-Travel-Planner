"""ConversationBufferSummaryMemory manager for multi-turn planning.

Wraps LangChain ``ConversationSummaryBufferMemory`` per DEV_SPEC §3.6:
- ``recent_buffer``: verbatim recent conversation turns (within ``max_token_limit``).
- ``running_summary`` (``moving_summary_buffer``): compressed historical context
  produced by LLM summarization.
- Auto-summarization triggered by ``ConversationSummaryBufferMemory`` when the
  buffer exceeds ``max_token_limit``.
- Preserves structured key-points across summary compression cycles.

Thread-safe for single-process usage (dict-based session store).
Each session owns its own ``ConversationSummaryBufferMemory`` instance.

Integration points:
- ``load()`` returns ``{"recent_buffer": str, "running_summary": str}``
  for injection into PlannerAgent context.
- ``save()`` appends a new turn via ``save_context()``, which internally
  triggers LLM-based compression when the buffer exceeds the token limit.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from langchain.memory import ConversationSummaryBufferMemory
from langchain_core.language_models import BaseLLM
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from .summary_memory import (
    SummarizerFn,
    SummaryCompressor,
    create_summary_buffer_memory,
    estimate_tokens,
)


# ---------------------------------------------------------------------------
# Message dataclass (kept for backward compat & format utility)
# ---------------------------------------------------------------------------

@dataclass
class Message:
    """A single conversation message."""

    role: str  # "user" | "assistant" | "system"
    content: str

    def format(self) -> str:
        """Render as ``[role]: content`` for context injection."""
        return f"[{self.role}]: {self.content}"


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

@dataclass
class SessionMemory:
    """In-memory state for a single conversation session.

    Wraps a ``ConversationSummaryBufferMemory`` instance and mirrors its
    state via convenience attributes for backward-compatible test access.
    """

    lc_memory: ConversationSummaryBufferMemory
    """The underlying LangChain memory instance."""

    @property
    def recent_messages(self) -> list[Message]:
        """Convert LangChain message buffer to Message list."""
        messages: list[Message] = []
        for msg in self.lc_memory.chat_memory.messages:
            if isinstance(msg, HumanMessage):
                messages.append(Message(role="user", content=msg.content))
            elif isinstance(msg, AIMessage):
                messages.append(Message(role="assistant", content=msg.content))
        return messages

    @property
    def running_summary(self) -> str:
        """Return the current moving summary buffer."""
        return self.lc_memory.moving_summary_buffer or ""


# ---------------------------------------------------------------------------
# MemoryManager
# ---------------------------------------------------------------------------

class MemoryManager:
    """ConversationBufferSummaryMemory for LangGraph planner integration.

    Wraps LangChain ``ConversationSummaryBufferMemory`` (one per session).

    Lifecycle per turn:
    1. ``load(session_id)`` → dict with ``recent_buffer`` + ``running_summary``
    2. PlannerAgent processes request …
    3. ``save(session_id, user_msg, assistant_msg)`` → persists turn via
       ``ConversationSummaryBufferMemory.save_context()``, which auto-triggers
       LLM-based summary compression when the buffer exceeds ``max_token_limit``.

    Configuration (from ``settings.yaml > memory.*``):
        max_tokens: Upper bound for recent_buffer tokens (default 3000).
        summary_trigger_tokens: Threshold mapped to ``max_token_limit`` (default 2600).
        summary_max_tokens: Max tokens for running_summary (default 700).
        k_recent_turns: Number of recent turns to keep verbatim (default 8).

    Args:
        max_tokens: Token budget for recent buffer.
        summary_trigger_tokens: Maps to ``ConversationSummaryBufferMemory.max_token_limit``.
        summary_max_tokens: Advisory cap on summary length.
        k_recent_turns: Number of recent user+assistant turn pairs to keep.
        llm: LLM for summarization (required). Use ``ChatOpenAI`` or any
            ``BaseLLM`` subclass.
        summarizer: Legacy — ignored when ``llm`` is provided.
    """

    def __init__(
        self,
        *,
        max_tokens: int = 3000,
        summary_trigger_tokens: int = 2600,
        summary_max_tokens: int = 700,
        k_recent_turns: int = 8,
        llm: BaseLLM | None = None,
        summarizer: SummarizerFn | None = None,
    ) -> None:
        if summary_trigger_tokens > max_tokens:
            raise ValueError(
                f"summary_trigger_tokens ({summary_trigger_tokens}) "
                f"must be <= max_tokens ({max_tokens})"
            )
        if llm is None:
            raise ValueError(
                "llm is required. Pass a ChatOpenAI instance or use "
                "MemoryManager.from_settings() to auto-configure from settings."
            )

        self.max_tokens = max_tokens
        self.summary_trigger_tokens = summary_trigger_tokens
        self._summary_max_tokens = summary_max_tokens
        self.k_recent_turns = k_recent_turns
        self._llm = llm

        # Thread-safe session store
        self._sessions: dict[str, SessionMemory] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, session_id: str) -> dict[str, str]:
        """Load memory context for a session.

        Returns:
            dict with ``recent_buffer`` (formatted recent messages) and
            ``running_summary`` (compressed history from LangChain memory).
        """
        session = self._get_or_create(session_id)

        # Format recent messages for PlannerAgent context injection
        messages = session.recent_messages
        recent_text = "\n".join(m.format() for m in messages)

        return {
            "recent_buffer": recent_text,
            "running_summary": session.running_summary,
        }

    def save(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
    ) -> dict[str, Any]:
        """Persist a user+assistant turn and auto-compress if needed.

        Delegates to ``ConversationSummaryBufferMemory.save_context()``,
        which internally triggers LLM-based summary compression when the
        buffer exceeds ``max_token_limit``.

        Args:
            session_id: Conversation session identifier.
            user_message: User input text.
            assistant_message: Assistant response text.

        Returns:
            dict with compression metadata:
            - ``compressed``: bool — whether compression was triggered.
            - ``recent_token_count``: int — tokens in recent buffer after save.
            - ``summary_token_count``: int — tokens in running summary.
            - ``recent_message_count``: int — number of messages kept.
        """
        session = self._get_or_create(session_id)

        # Capture pre-save summary to detect compression
        old_summary = session.running_summary

        # Delegate to LangChain ConversationSummaryBufferMemory
        session.lc_memory.save_context(
            {"input": user_message},
            {"output": assistant_message},
        )

        # Detect compression
        new_summary = session.running_summary
        compressed = new_summary != old_summary and new_summary != ""

        # Compute metadata
        messages = session.recent_messages
        recent_text = "\n".join(m.format() for m in messages)
        return {
            "compressed": compressed,
            "recent_token_count": estimate_tokens(recent_text),
            "summary_token_count": estimate_tokens(new_summary),
            "recent_message_count": len(messages),
        }

    def clear(self, session_id: str) -> None:
        """Clear all memory for a session."""
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].lc_memory.clear()
                del self._sessions[session_id]

    def get_session_ids(self) -> list[str]:
        """Return list of active session identifiers."""
        with self._lock:
            return list(self._sessions.keys())

    @property
    def sessions(self) -> dict[str, SessionMemory]:
        """Read-only access to session store (for testing)."""
        return dict(self._sessions)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_or_create(self, session_id: str) -> SessionMemory:
        """Thread-safe session lookup / creation."""
        with self._lock:
            if session_id not in self._sessions:
                lc_mem = create_summary_buffer_memory(
                    llm=self._llm,
                    max_token_limit=self.summary_trigger_tokens,
                )
                self._sessions[session_id] = SessionMemory(lc_memory=lc_mem)
            return self._sessions[session_id]

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_settings(cls, settings: Any | None = None) -> "MemoryManager":
        """Create MemoryManager from application settings.

        Reads ``memory.*`` keys from settings object or uses defaults.

        LLM resolution order:
        1. ``memory.summary_model`` — if explicitly configured, use it.
        2. ``providers.llm_model`` — inherit the project-wide LLM (default: gpt-4o-mini).

        Raises ``RuntimeError`` if no LLM can be created (missing ``langchain-openai``
        or no model name configured).
        """
        if settings is None:
            from app.config.settings import get_settings
            settings = get_settings()

        memory_cfg = getattr(settings, "memory", None)
        if memory_cfg is None:
            return cls()

        # Resolve the model name: explicit summary_model → providers.llm_model
        summary_model = getattr(memory_cfg, "summary_model", "") or ""
        if not summary_model:
            providers_cfg = getattr(settings, "providers", None)
            summary_model = getattr(providers_cfg, "llm_model", "") if providers_cfg else ""

        # Create real LLM for summarization
        if not summary_model:
            raise RuntimeError(
                "No LLM model configured for memory summarization. "
                "Set providers.llm_model or memory.summary_model in settings.yaml."
            )

        from langchain_openai import ChatOpenAI
        llm: BaseLLM = ChatOpenAI(model=summary_model, temperature=0)  # type: ignore[assignment]

        return cls(
            max_tokens=getattr(memory_cfg, "max_tokens", 3000),
            summary_trigger_tokens=getattr(memory_cfg, "summary_trigger_tokens", 2600),
            summary_max_tokens=getattr(memory_cfg, "summary_max_tokens", 700),
            k_recent_turns=getattr(memory_cfg, "k_recent_turns", 8),
            llm=llm,
        )
