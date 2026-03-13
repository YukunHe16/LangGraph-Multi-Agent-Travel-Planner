"""Summary-buffer memory wrapping LangChain ConversationSummaryBufferMemory.

Implements §3.6 of DEV_SPEC:
- Uses ``ConversationSummaryBufferMemory`` from LangChain as the core component.
- ``recent_buffer``: verbatim recent messages kept within ``max_token_limit``.
- ``running_summary`` (``moving_summary_buffer``): compressed historical context.
- Auto-summarization via real LLM (``ChatOpenAI``) when token count exceeds the limit.
- Preserves structured key-points: user preferences, selected flights,
  visa status, hotel constraints, and pending items.

The LLM used for summarization is inherited from ``providers.llm_model``
(default gpt-4o-mini) or explicitly set via ``memory.summary_model``.
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from langchain.memory import ConversationSummaryBufferMemory
from langchain_core.language_models import BaseLLM


# ---------------------------------------------------------------------------
# Token estimator (used for budget checks independent of LLM tokenizer)
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Estimate token count for mixed CJK / Latin text.

    Heuristic:
    - Each CJK character counts as ~1.5 tokens (conservative).
    - Each Latin word counts as ~1.3 tokens.
    - Punctuation / whitespace is free.

    This avoids a hard dependency on ``tiktoken`` while still being
    reasonably accurate for planning-phase budget decisions.
    """
    if not text:
        return 0

    cjk_chars = len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", text))
    latin_words = len(re.findall(r"[a-zA-Z0-9]+", text))
    return int(cjk_chars * 1.5 + latin_words * 1.3) or max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Summarizer protocol (for custom injection in tests)
# ---------------------------------------------------------------------------

@runtime_checkable
class SummarizerFn(Protocol):
    """Callable that compresses a block of conversation text into a summary."""

    def __call__(self, text: str) -> str: ...  # pragma: no cover


def default_extractive_summarizer(text: str) -> str:
    """Cheap extractive fallback when no LLM is available.

    Keeps the first and last 30% of lines, joining them with an ellipsis.
    This is intentionally lossy — the real summarizer should be an LLM call.
    """
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    if len(lines) <= 6:
        return text.strip()

    keep = max(2, len(lines) * 3 // 10)
    head = lines[:keep]
    tail = lines[-keep:]
    return "\n".join(head) + "\n...\n" + "\n".join(tail)


SUMMARY_SYSTEM_PROMPT = (
    "你是一个对话摘要器。请将以下对话历史压缩为结构化要点摘要，"
    "必须保留：用户偏好、已选航班、签证状态、酒店约束、未完成事项。"
    "输出纯文本，不要加 Markdown 标题。"
)
"""System prompt used when compressing conversation history with an LLM."""


# ---------------------------------------------------------------------------
# SummaryCompressor — thin wrapper for direct text compression
# ---------------------------------------------------------------------------

class SummaryCompressor:
    """Compress conversation text into a concise running summary.

    This is a thin adapter: when a ``summarizer`` callable is provided it
    is used directly; otherwise it delegates to
    :func:`default_extractive_summarizer`.

    Args:
        summarizer: Callable ``(text) -> summary_text``.
        max_summary_tokens: Hard cap on summary length (token estimate).
    """

    def __init__(
        self,
        *,
        summarizer: SummarizerFn | None = None,
        max_summary_tokens: int = 700,
    ) -> None:
        self._summarize = summarizer or default_extractive_summarizer
        self.max_summary_tokens = max_summary_tokens

    def compress(self, text: str) -> str:
        """Compress *text* into a summary within the token budget."""
        if not text or not text.strip():
            return ""

        summary = self._summarize(text)

        # Hard-truncate if summarizer exceeds budget
        while estimate_tokens(summary) > self.max_summary_tokens and len(summary) > 100:
            lines = summary.split("\n", 1)
            if len(lines) <= 1:
                summary = summary[len(summary) // 4 :]
                break
            summary = lines[1]

        return summary.strip()


# ---------------------------------------------------------------------------
# Factory for ConversationSummaryBufferMemory
# ---------------------------------------------------------------------------

def create_summary_buffer_memory(
    *,
    llm: BaseLLM,
    max_token_limit: int = 2000,
    human_prefix: str = "用户",
    ai_prefix: str = "助手",
) -> ConversationSummaryBufferMemory:
    """Create a LangChain ``ConversationSummaryBufferMemory`` instance.

    Args:
        llm: Language model for summarization (required). Use ``ChatOpenAI``
            or any ``BaseLLM`` subclass.
        max_token_limit: Token limit before triggering summary compression.
        human_prefix: Display prefix for human messages.
        ai_prefix: Display prefix for AI messages.

    Returns:
        Configured ``ConversationSummaryBufferMemory`` instance.
    """
    return ConversationSummaryBufferMemory(
        llm=llm,
        max_token_limit=max_token_limit,
        human_prefix=human_prefix,
        ai_prefix=ai_prefix,
        return_messages=True,
    )
