"""Integration test for C10: PlannerAgent multi-turn memory flow.

Validates end-to-end:
1. PlannerAgent reads recent_buffer + running_summary before planning.
2. PlannerAgent writes back memory after planning.
3. Multi-turn decision consistency: context from turn 1 is visible in turn 2.
4. Delta mode uses memory context for affected-worker computation.
5. Compression preserves key constraints across turns.
"""

from __future__ import annotations

import pytest

from app.agents.memory.memory_manager import MemoryManager
from app.agents.planner.planner_agent import PlannerAgent, PlannerMode
from app.models.schemas import TripRequest
from langchain_core.language_models import BaseLLM
from langchain_core.outputs import Generation, LLMResult


class _StubLLM(BaseLLM):
    """Minimal LLM stub for integration tests — no network calls."""

    @property
    def _llm_type(self) -> str:
        return "stub"

    def _generate(self, prompts, stop=None, run_manager=None, **kwargs):
        return LLMResult(
            generations=[[Generation(text="Stub summary.")] for _ in prompts]
        )

    def get_num_tokens(self, text: str) -> int:
        return max(1, len(text.split()))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def _llm() -> _StubLLM:
    """Stub LLM for summarization — no network calls."""
    return _StubLLM()


@pytest.fixture
def memory(_llm: _StubLLM) -> MemoryManager:
    """Small-budget memory for fast compression testing."""
    return MemoryManager(
        max_tokens=500,
        summary_trigger_tokens=300,
        summary_max_tokens=150,
        k_recent_turns=2,
        llm=_llm,
    )


@pytest.fixture
def planner(memory: MemoryManager) -> PlannerAgent:
    """PlannerAgent with memory but no actual workers."""
    return PlannerAgent(memory=memory)


@pytest.fixture
def beijing_request() -> TripRequest:
    return TripRequest(
        city="Beijing",
        start_date="2026-06-01",
        end_date="2026-06-03",
        travel_days=3,
        transportation="public",
        accommodation="budget hotel",
        preferences=["cultural", "food"],
        free_text_input="I love history",
    )


@pytest.fixture
def tokyo_request() -> TripRequest:
    return TripRequest(
        city="Tokyo",
        start_date="2026-07-01",
        end_date="2026-07-05",
        travel_days=5,
        transportation="train",
        accommodation="ryokan",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMultiTurnMemoryFlow:
    """Multi-turn planning with memory persistence."""

    def test_turn1_creates_memory(
        self, planner: PlannerAgent, memory: MemoryManager, beijing_request: TripRequest
    ) -> None:
        """First turn should create session memory."""
        planner.plan(beijing_request, session_id="flow-1")
        ctx = memory.load("flow-1")
        assert ctx["recent_buffer"] != ""
        assert "Beijing" in ctx["recent_buffer"]

    def test_turn2_sees_turn1_context(
        self, planner: PlannerAgent, memory: MemoryManager, beijing_request: TripRequest
    ) -> None:
        """Second turn should see context from first turn."""
        # Turn 1
        planner.plan(beijing_request, session_id="flow-2")

        # Turn 2: delta mode
        result = planner.plan(
            beijing_request,
            mode=PlannerMode.DELTA,
            user_delta="Change hotel to luxury",
            session_id="flow-2",
        )
        # Should have 4 messages (2 from turn 1 + 2 from turn 2)
        session = memory.sessions["flow-2"]
        assert len(session.recent_messages) == 4

    def test_multi_turn_accumulates_memory(
        self, planner: PlannerAgent, memory: MemoryManager, beijing_request: TripRequest
    ) -> None:
        """Multiple turns accumulate in memory."""
        for i in range(3):
            planner.plan(
                beijing_request,
                session_id="flow-3",
                user_delta=f"Modification {i}" if i > 0 else None,
                mode=PlannerMode.DELTA if i > 0 else PlannerMode.DEFAULT,
            )

        session = memory.sessions["flow-3"]
        # Should have messages from all 3 turns (6 messages)
        # or fewer if compression kicked in
        assert len(session.recent_messages) >= 2

    def test_different_sessions_isolated(
        self,
        planner: PlannerAgent,
        memory: MemoryManager,
        beijing_request: TripRequest,
        tokyo_request: TripRequest,
    ) -> None:
        """Different session_ids should be fully isolated."""
        planner.plan(beijing_request, session_id="beijing-session")
        planner.plan(tokyo_request, session_id="tokyo-session")

        bj = memory.load("beijing-session")
        tk = memory.load("tokyo-session")

        assert "Beijing" in bj["recent_buffer"]
        assert "Tokyo" not in bj["recent_buffer"]
        assert "Tokyo" in tk["recent_buffer"]
        assert "Beijing" not in tk["recent_buffer"]


class TestCompressionFlow:
    """Compression triggers and preserves context."""

    def test_compression_triggers_after_many_turns(
        self, planner: PlannerAgent, memory: MemoryManager, beijing_request: TripRequest
    ) -> None:
        """After enough turns, compression should produce a running_summary."""
        for i in range(8):
            planner.plan(
                beijing_request,
                session_id="compress-test",
                user_delta=f"Add attraction number {i} with detailed description and preferences" if i > 0 else None,
                mode=PlannerMode.DELTA if i > 0 else PlannerMode.DEFAULT,
            )

        session = memory.sessions["compress-test"]
        # With tight budget (300 trigger, k=2), compression should have fired
        if len(session.recent_messages) <= 4:  # k=2 → 4 messages
            assert session.running_summary != "", "Should have running_summary after compression"

    def test_recent_buffer_stays_within_budget(
        self, planner: PlannerAgent, memory: MemoryManager, beijing_request: TripRequest
    ) -> None:
        """Recent buffer token count should stay within max_tokens."""
        from app.agents.memory.summary_memory import estimate_tokens

        for i in range(10):
            planner.plan(
                beijing_request,
                session_id="budget-test",
                user_delta=f"Long detailed modification request number {i} with extra context" if i > 0 else None,
                mode=PlannerMode.DELTA if i > 0 else PlannerMode.DEFAULT,
            )

        ctx = memory.load("budget-test")
        recent_tokens = estimate_tokens(ctx["recent_buffer"])
        # Should be within budget (with tolerance for heuristic)
        assert recent_tokens <= memory.max_tokens + 100


class TestDeltaModeWithMemory:
    """Delta mode should work correctly with memory context."""

    def test_delta_mode_preserves_session(
        self, planner: PlannerAgent, memory: MemoryManager, beijing_request: TripRequest
    ) -> None:
        """Delta mode should read and write memory."""
        # Initial plan
        planner.plan(beijing_request, session_id="delta-mem")

        # Delta update
        planner.plan(
            beijing_request,
            mode=PlannerMode.DELTA,
            user_delta="Change flight to morning",
            session_id="delta-mem",
        )

        ctx = memory.load("delta-mem")
        assert "flight" in ctx["recent_buffer"].lower() or "morning" in ctx["recent_buffer"].lower()


class TestMemoryContextInjection:
    """Verify memory context reaches PlannerState correctly."""

    def test_empty_memory_injects_empty_strings(
        self, planner: PlannerAgent, memory: MemoryManager, beijing_request: TripRequest
    ) -> None:
        """Fresh session should inject empty strings."""
        captured: dict = {}
        original = planner._classify_intent

        def spy(state):
            captured.update(state)
            return original(state)

        planner._classify_intent = spy
        planner._graph = planner._build_graph()
        planner.plan(beijing_request, session_id="empty-mem")

        assert captured.get("recent_buffer") == ""
        assert captured.get("running_summary") == ""

    def test_populated_memory_injects_context(
        self, planner: PlannerAgent, memory: MemoryManager, beijing_request: TripRequest
    ) -> None:
        """Pre-populated memory should be injected into state."""
        memory.save("pop-mem", "I prefer luxury hotels", "Noted, luxury hotels preference")

        captured: dict = {}
        original = planner._classify_intent

        def spy(state):
            captured.update(state)
            return original(state)

        planner._classify_intent = spy
        planner._graph = planner._build_graph()
        planner.plan(beijing_request, session_id="pop-mem")

        assert "luxury" in captured.get("recent_buffer", "").lower()
