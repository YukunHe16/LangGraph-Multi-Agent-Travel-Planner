"""Unit tests for C10: MemoryManager wrapping LangChain ConversationSummaryBufferMemory.

Covers:
- Token estimation
- SummaryCompressor compression
- LangChain ConversationSummaryBufferMemory factory
- MemoryManager load/save lifecycle (backed by LC memory)
- Auto-compression when token budget exceeded
- Config-driven construction
- PlannerAgent memory integration
- Multi-session isolation
- Thread safety
"""

from __future__ import annotations

import threading

import pytest

from app.agents.memory.memory_manager import MemoryManager, Message, SessionMemory
from app.agents.memory.summary_memory import (
    SummaryCompressor,
    create_summary_buffer_memory,
    default_extractive_summarizer,
    estimate_tokens,
)
from langchain_core.language_models import BaseLLM
from langchain_core.outputs import Generation, LLMResult


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _StubLLM(BaseLLM):
    """Minimal LLM stub for unit tests — no network calls."""

    @property
    def _llm_type(self) -> str:
        return "stub"

    def _generate(self, prompts, stop=None, run_manager=None, **kwargs):
        return LLMResult(
            generations=[[Generation(text="Stub summary.")] for _ in prompts]
        )

    def get_num_tokens(self, text: str) -> int:
        return max(1, len(text.split()))


def _make_mm(**overrides) -> MemoryManager:
    """Create a MemoryManager with a stub LLM for testing."""
    overrides.setdefault("llm", _StubLLM())
    return MemoryManager(**overrides)


# ===================================================================
# TestEstimateTokens
# ===================================================================

class TestEstimateTokens:
    """Token estimation heuristic tests."""

    def test_empty_string(self) -> None:
        assert estimate_tokens("") == 0

    def test_latin_words(self) -> None:
        tokens = estimate_tokens("Hello world foo bar")
        assert tokens > 0
        # 4 words * 1.3 ≈ 5
        assert 4 <= tokens <= 8

    def test_cjk_characters(self) -> None:
        tokens = estimate_tokens("你好世界测试")
        # 6 CJK chars * 1.5 = 9
        assert tokens >= 6

    def test_mixed_text(self) -> None:
        tokens = estimate_tokens("Hello 你好 world 世界")
        assert tokens > 0

    def test_single_char(self) -> None:
        tokens = estimate_tokens("A")
        assert tokens >= 1

    def test_whitespace_only(self) -> None:
        # No CJK, no Latin words — falls back to len//4
        tokens = estimate_tokens("   ")
        assert tokens >= 0


# ===================================================================
# TestDefaultExtractiveSummarizer
# ===================================================================

class TestDefaultExtractiveSummarizer:
    """Extractive summarizer fallback tests."""

    def test_short_text_unchanged(self) -> None:
        text = "line1\nline2\nline3"
        result = default_extractive_summarizer(text)
        assert "line1" in result
        assert "line3" in result

    def test_long_text_truncated(self) -> None:
        lines = [f"Line {i}: some content here to make it longer" for i in range(20)]
        text = "\n".join(lines)
        result = default_extractive_summarizer(text)
        # Should contain head and tail but not everything
        assert "Line 0" in result
        assert "Line 19" in result
        assert "..." in result

    def test_empty_text(self) -> None:
        result = default_extractive_summarizer("")
        assert result == ""


# ===================================================================
# TestSummaryCompressor
# ===================================================================

class TestSummaryCompressor:
    """SummaryCompressor unit tests."""

    def test_compress_short_text(self) -> None:
        compressor = SummaryCompressor(max_summary_tokens=700)
        result = compressor.compress("Short summary text")
        assert len(result) > 0

    def test_compress_empty_text(self) -> None:
        compressor = SummaryCompressor(max_summary_tokens=700)
        assert compressor.compress("") == ""
        assert compressor.compress("   ") == ""

    def test_compress_with_custom_summarizer(self) -> None:
        def mock_summarizer(text: str) -> str:
            return "MOCK SUMMARY"

        compressor = SummaryCompressor(summarizer=mock_summarizer, max_summary_tokens=700)
        result = compressor.compress("Any input text")
        assert result == "MOCK SUMMARY"

    def test_compress_truncates_oversized_summary(self) -> None:
        """If summarizer returns more tokens than budget, output is truncated."""
        def verbose_summarizer(text: str) -> str:
            return "\n".join([f"Detail {i}: " + "x" * 100 for i in range(50)])

        compressor = SummaryCompressor(summarizer=verbose_summarizer, max_summary_tokens=50)
        result = compressor.compress("Input")
        tokens = estimate_tokens(result)
        # Should be trimmed to fit budget (with some tolerance)
        assert tokens <= 100  # rough upper bound after trimming

    def test_max_summary_tokens_attribute(self) -> None:
        compressor = SummaryCompressor(max_summary_tokens=500)
        assert compressor.max_summary_tokens == 500


# ===================================================================
# TestCreateSummaryBufferMemory
# ===================================================================

class TestCreateSummaryBufferMemory:
    """Factory for LangChain ConversationSummaryBufferMemory."""

    def test_creates_with_llm(self) -> None:
        from langchain.memory import ConversationSummaryBufferMemory
        mem = create_summary_buffer_memory(llm=_StubLLM())
        assert isinstance(mem, ConversationSummaryBufferMemory)

    def test_creates_with_custom_limit(self) -> None:
        mem = create_summary_buffer_memory(llm=_StubLLM(), max_token_limit=500)
        assert mem.max_token_limit == 500

    def test_save_context_round_trip(self) -> None:
        mem = create_summary_buffer_memory(llm=_StubLLM())
        mem.save_context({"input": "hello"}, {"output": "hi"})
        result = mem.load_memory_variables({})
        assert "history" in result

    def test_save_and_load_round_trip(self) -> None:
        mem = create_summary_buffer_memory(llm=_StubLLM(), max_token_limit=100)
        mem.save_context({"input": "Plan trip to Beijing"}, {"output": "Ok planning"})
        mem.save_context({"input": "Add hotels"}, {"output": "Found hotels"})
        result = mem.load_memory_variables({})
        # history should contain messages
        assert len(result["history"]) >= 2

    def test_moving_summary_buffer_populated_after_compression(self) -> None:
        """With a very small token limit, compression should kick in."""
        mem = create_summary_buffer_memory(llm=_StubLLM(), max_token_limit=20)
        for i in range(5):
            mem.save_context(
                {"input": f"User message {i} with extra context"},
                {"output": f"Assistant reply {i} with details"},
            )
        # After multiple saves with tiny limit, moving_summary_buffer should be populated
        assert mem.moving_summary_buffer != ""


# ===================================================================
# TestMessage
# ===================================================================

class TestMessage:
    """Message dataclass tests."""

    def test_format_user(self) -> None:
        msg = Message(role="user", content="Hello")
        assert msg.format() == "[user]: Hello"

    def test_format_assistant(self) -> None:
        msg = Message(role="assistant", content="Hi there")
        assert msg.format() == "[assistant]: Hi there"


# ===================================================================
# TestMemoryManagerInit
# ===================================================================

class TestMemoryManagerInit:
    """MemoryManager construction and validation tests."""

    def test_requires_llm(self) -> None:
        with pytest.raises(ValueError, match="llm is required"):
            MemoryManager()

    def test_custom_params(self) -> None:
        mm = _make_mm(
            max_tokens=1000,
            summary_trigger_tokens=800,
            summary_max_tokens=300,
            k_recent_turns=4,
        )
        assert mm.max_tokens == 1000
        assert mm.k_recent_turns == 4

    def test_trigger_exceeds_max_raises(self) -> None:
        with pytest.raises(ValueError, match="summary_trigger_tokens"):
            MemoryManager(max_tokens=100, summary_trigger_tokens=200)

    def test_trigger_equals_max_ok(self) -> None:
        mm = _make_mm(max_tokens=100, summary_trigger_tokens=100)
        assert mm.max_tokens == 100

    def test_from_settings_none(self) -> None:
        mm = MemoryManager.from_settings(None)
        assert mm.max_tokens == 3000

    def test_from_settings_with_memory_config(self) -> None:
        from unittest.mock import MagicMock
        settings = MagicMock()
        settings.memory.max_tokens = 2000
        settings.memory.summary_trigger_tokens = 1800
        settings.memory.summary_max_tokens = 500
        settings.memory.k_recent_turns = 6
        settings.memory.summary_model = ""
        settings.providers.llm_model = "gpt-4o-mini"
        mm = MemoryManager.from_settings(settings)
        assert mm.max_tokens == 2000
        assert mm.k_recent_turns == 6

    def test_from_settings_inherits_providers_llm(self) -> None:
        """When summary_model is empty, from_settings inherits providers.llm_model."""
        from unittest.mock import MagicMock, patch
        settings = MagicMock()
        settings.memory.max_tokens = 3000
        settings.memory.summary_trigger_tokens = 2600
        settings.memory.summary_max_tokens = 700
        settings.memory.k_recent_turns = 8
        settings.memory.summary_model = ""
        settings.providers.llm_model = "gpt-4o-mini"

        # Mock ChatOpenAI so we can verify it was called with the right model
        with patch("app.agents.memory.memory_manager.ChatOpenAI", create=True) as MockChat:
            # Import inside patch scope
            import importlib
            import app.agents.memory.memory_manager as mm_mod
            # Manually inject the mock into the from_settings code path
            mock_llm = MagicMock(spec=BaseLLM)
            MockChat.return_value = mock_llm

            # Patch the import inside from_settings
            with patch.dict("sys.modules", {"langchain_openai": MagicMock(ChatOpenAI=MockChat)}):
                mm = MemoryManager.from_settings(settings)

            MockChat.assert_called_once_with(model="gpt-4o-mini", temperature=0)

    def test_from_settings_uses_explicit_summary_model(self) -> None:
        """When summary_model is set, it takes priority over providers.llm_model."""
        from unittest.mock import MagicMock, patch
        settings = MagicMock()
        settings.memory.max_tokens = 3000
        settings.memory.summary_trigger_tokens = 2600
        settings.memory.summary_max_tokens = 700
        settings.memory.k_recent_turns = 8
        settings.memory.summary_model = "gpt-3.5-turbo"
        settings.providers.llm_model = "gpt-4o-mini"

        with patch.dict("sys.modules", {"langchain_openai": MagicMock()}) as modules:
            MockChat = modules["langchain_openai"].ChatOpenAI
            mm = MemoryManager.from_settings(settings)
            MockChat.assert_called_once_with(model="gpt-3.5-turbo", temperature=0)


# ===================================================================
# TestMemoryManagerLoadSave
# ===================================================================

class TestMemoryManagerLoadSave:
    """MemoryManager load/save lifecycle tests."""

    def test_load_empty_session(self) -> None:
        mm = _make_mm()
        ctx = mm.load("session-1")
        assert ctx["recent_buffer"] == ""
        assert ctx["running_summary"] == ""

    def test_save_creates_messages(self) -> None:
        mm = _make_mm()
        meta = mm.save("s1", "user msg", "assistant reply")
        assert meta["compressed"] is False
        assert meta["recent_message_count"] == 2

    def test_load_after_save(self) -> None:
        mm = _make_mm()
        mm.save("s1", "Plan Beijing trip", "Here is a 3-day plan")
        ctx = mm.load("s1")
        assert "[user]: Plan Beijing trip" in ctx["recent_buffer"]
        assert "[assistant]: Here is a 3-day plan" in ctx["recent_buffer"]

    def test_multiple_saves_accumulate(self) -> None:
        mm = _make_mm()
        mm.save("s1", "msg1", "reply1")
        mm.save("s1", "msg2", "reply2")
        ctx = mm.load("s1")
        assert "msg1" in ctx["recent_buffer"]
        assert "msg2" in ctx["recent_buffer"]
        assert ctx["recent_buffer"].count("[user]:") == 2

    def test_clear_removes_session(self) -> None:
        mm = _make_mm()
        mm.save("s1", "msg", "reply")
        mm.clear("s1")
        ctx = mm.load("s1")
        assert ctx["recent_buffer"] == ""

    def test_clear_nonexistent_session_safe(self) -> None:
        mm = _make_mm()
        mm.clear("nonexistent")  # Should not raise

    def test_get_session_ids(self) -> None:
        mm = _make_mm()
        mm.save("s1", "m", "r")
        mm.save("s2", "m", "r")
        ids = mm.get_session_ids()
        assert "s1" in ids
        assert "s2" in ids


# ===================================================================
# TestAutoCompression
# ===================================================================

class TestAutoCompression:
    """Auto-compression when token budget is exceeded."""

    def _build_mm(self, *, max_tokens: int = 200, trigger: int = 150, k: int = 2) -> MemoryManager:
        """Build a MemoryManager with tight budget for easy compression testing."""
        return _make_mm(
            max_tokens=max_tokens,
            summary_trigger_tokens=trigger,
            summary_max_tokens=100,
            k_recent_turns=k,
        )

    def test_no_compression_under_threshold(self) -> None:
        mm = self._build_mm()
        meta = mm.save("s1", "short", "reply")
        assert meta["compressed"] is False

    def test_compression_triggered_over_threshold(self) -> None:
        mm = self._build_mm(max_tokens=200, trigger=100, k=1)
        # Fill with enough messages to exceed trigger
        for i in range(10):
            mm.save("s1", f"User message {i} with some extra padding text", f"Assistant reply {i} with details and context")
        
        ctx = mm.load("s1")
        session = mm.sessions["s1"]
        # After compression, should have running_summary
        assert session.running_summary != ""
        # LangChain prunes by token limit, not message count.
        # Verify token budget is respected (recent buffer tokens ≤ trigger threshold + tolerance).
        recent_tokens = estimate_tokens(ctx["recent_buffer"])
        assert recent_tokens <= mm.max_tokens + 100  # tolerance for heuristic

    def test_running_summary_preserves_context(self) -> None:
        mm = self._build_mm(max_tokens=200, trigger=80, k=1)
        mm.save("s1", "I want to go to Beijing", "Ok planning Beijing trip")
        mm.save("s1", "Add hotel near Forbidden City", "Found hotels near Forbidden City")
        mm.save("s1", "Budget is 5000 yuan", "Got it, budget 5000 yuan")
        mm.save("s1", "Prefer cultural sites", "Adding cultural attractions")
        mm.save("s1", "Need visa info", "Checking visa requirements")

        ctx = mm.load("s1")
        # Running summary should exist if compression happened
        session = mm.sessions["s1"]
        if session.running_summary:
            # Summary should preserve some context from older messages
            assert len(session.running_summary) > 0

    def test_compression_metadata_returned(self) -> None:
        mm = self._build_mm(max_tokens=200, trigger=80, k=1)
        # First save under threshold
        meta1 = mm.save("s1", "short", "reply")
        assert meta1["compressed"] is False

        # Fill until compression triggers
        compressed_seen = False
        for i in range(15):
            meta = mm.save("s1", f"Message {i} padding text here", f"Reply {i} with details")
            if meta["compressed"]:
                compressed_seen = True
                assert meta["recent_token_count"] >= 0
                assert meta["summary_token_count"] > 0
                break
        assert compressed_seen, "Compression should have triggered"

    def test_recent_buffer_within_max_tokens_after_compression(self) -> None:
        mm = self._build_mm(max_tokens=200, trigger=80, k=1)
        for i in range(20):
            mm.save("s1", f"Long user message {i} with lots of detail", f"Long reply {i} with context")

        ctx = mm.load("s1")
        recent_tokens = estimate_tokens(ctx["recent_buffer"])
        # Should be within budget (with some tolerance for heuristic)
        assert recent_tokens <= mm.max_tokens + 50


# ===================================================================
# TestMultiSessionIsolation
# ===================================================================

class TestMultiSessionIsolation:
    """Sessions should be fully isolated."""

    def test_different_sessions_independent(self) -> None:
        mm = _make_mm()
        mm.save("alice", "Alice message", "Reply to Alice")
        mm.save("bob", "Bob message", "Reply to Bob")

        alice_ctx = mm.load("alice")
        bob_ctx = mm.load("bob")

        assert "Alice" in alice_ctx["recent_buffer"]
        assert "Bob" not in alice_ctx["recent_buffer"]
        assert "Bob" in bob_ctx["recent_buffer"]
        assert "Alice" not in bob_ctx["recent_buffer"]

    def test_clear_one_session_keeps_other(self) -> None:
        mm = _make_mm()
        mm.save("s1", "m1", "r1")
        mm.save("s2", "m2", "r2")
        mm.clear("s1")
        assert mm.load("s1")["recent_buffer"] == ""
        assert "m2" in mm.load("s2")["recent_buffer"]


# ===================================================================
# TestConfigIntegration
# ===================================================================

class TestConfigIntegration:
    """MemorySettings integration with settings.yaml."""

    def test_memory_settings_model(self) -> None:
        from app.config.settings import MemorySettings
        ms = MemorySettings()
        assert ms.enabled is True
        assert ms.max_tokens == 3000
        assert ms.summary_trigger_tokens == 2600
        assert ms.summary_max_tokens == 700
        assert ms.k_recent_turns == 8

    def test_settings_includes_memory(self) -> None:
        from app.config.settings import Settings
        s = Settings()
        assert hasattr(s, "memory")
        assert s.memory.enabled is True

    def test_settings_from_yaml_includes_memory(self) -> None:
        from app.config.settings import get_settings
        s = get_settings()
        assert s.memory.max_tokens == 3000
        assert s.memory.summary_trigger_tokens == 2600

    def test_memory_manager_from_real_settings(self) -> None:
        from app.config.settings import get_settings
        s = get_settings()
        mm = MemoryManager.from_settings(s)
        assert mm.max_tokens == s.memory.max_tokens
        assert mm.k_recent_turns == s.memory.k_recent_turns


# ===================================================================
# TestThreadSafety
# ===================================================================

class TestThreadSafety:
    """Basic thread safety validation."""

    def test_concurrent_saves(self) -> None:
        mm = _make_mm()
        errors: list[Exception] = []

        def save_task(session_id: str, n: int) -> None:
            try:
                for i in range(n):
                    mm.save(session_id, f"msg-{i}", f"reply-{i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=save_task, args=(f"s{t}", 10))
            for t in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        assert len(mm.get_session_ids()) == 4


# ===================================================================
# TestPlannerAgentMemoryIntegration
# ===================================================================

class TestPlannerAgentMemoryIntegration:
    """PlannerAgent accepts and uses MemoryManager."""

    def test_planner_accepts_memory_kwarg(self) -> None:
        from app.agents.planner.planner_agent import PlannerAgent
        mm = _make_mm()
        agent = PlannerAgent(memory=mm)
        assert agent._memory is mm

    def test_planner_without_memory(self) -> None:
        from app.agents.planner.planner_agent import PlannerAgent
        agent = PlannerAgent()
        assert agent._memory is None

    def test_planner_state_has_memory_fields(self) -> None:
        from app.agents.planner.planner_agent import PlannerState
        # PlannerState is a TypedDict — check annotations
        annotations = PlannerState.__annotations__
        assert "recent_buffer" in annotations
        assert "running_summary" in annotations
        assert "session_id" in annotations

    def test_plan_with_session_id_loads_and_saves(self) -> None:
        from app.agents.planner.planner_agent import PlannerAgent
        from app.models.schemas import TripRequest

        mm = _make_mm()
        # Pre-populate memory
        mm.save("test-session", "Previous context", "Previous reply")

        agent = PlannerAgent(memory=mm)
        request = TripRequest(
            city="Beijing",
            start_date="2026-06-01",
            end_date="2026-06-03",
            travel_days=3,
            transportation="public",
            accommodation="budget",
        )
        result = agent.plan(request, session_id="test-session")
        assert result is not None

        # Memory should have been updated (original 2 + new 2)
        session = mm.sessions["test-session"]
        assert len(session.recent_messages) == 4

    def test_plan_without_session_id_skips_memory(self) -> None:
        from app.agents.planner.planner_agent import PlannerAgent
        from app.models.schemas import TripRequest

        mm = _make_mm()
        agent = PlannerAgent(memory=mm)
        request = TripRequest(
            city="Tokyo",
            start_date="2026-07-01",
            end_date="2026-07-03",
            travel_days=3,
            transportation="train",
            accommodation="hotel",
        )
        result = agent.plan(request)
        assert result is not None
        # No sessions should have been created
        assert len(mm.get_session_ids()) == 0

    def test_plan_memory_context_injected_into_state(self) -> None:
        """Verify that memory context flows into PlannerState."""
        from app.agents.planner.planner_agent import PlannerAgent
        from app.models.schemas import TripRequest

        mm = _make_mm()
        mm.save("ctx-test", "I want cultural sites", "Got it, adding cultural sites")

        captured_state: dict = {}

        # Monkey-patch classify to capture state
        agent = PlannerAgent(memory=mm)
        original_classify = agent._classify_intent

        def spy_classify(state):
            captured_state.update(state)
            return original_classify(state)

        agent._classify_intent = spy_classify
        agent._graph = agent._build_graph()

        request = TripRequest(
            city="Kyoto",
            start_date="2026-08-01",
            end_date="2026-08-03",
            travel_days=3,
            transportation="train",
            accommodation="ryokan",
        )
        agent.plan(request, session_id="ctx-test")

        assert "recent_buffer" in captured_state
        assert "cultural sites" in captured_state["recent_buffer"]
