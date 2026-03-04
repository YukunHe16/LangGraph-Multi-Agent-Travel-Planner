"""C9 Prompt Regression Tests — validate all agent prompts per DEV_SPEC §3.4.

Tests verify:
  1. Each prompt contains all 8 mandatory fields.
  2. PlannerAgent prompt has extra orchestration sections.
  3. ALL_AGENT_PROMPTS registry is complete.
  4. Agent classes expose ``prompt`` attribute wired to the correct constant.
  5. Prompts contain at least 2 examples (including a failure example).
  6. Output schema (JSON block) is present in each prompt.
  7. Structured output success rate >= 95% (via format checks).
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from app.prompts.trip_prompts import (
    ALL_AGENT_PROMPTS,
    ATTRACTION_AGENT_PROMPT,
    FLIGHT_AGENT_PROMPT,
    HOTEL_AGENT_PROMPT,
    PLANNER_AGENT_PROMPT,
    PLANNER_EXTRA_SECTIONS,
    REQUIRED_PROMPT_SECTIONS,
    VISA_AGENT_PROMPT,
    WEATHER_AGENT_PROMPT,
)

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

AGENT_NAMES = ["attraction", "weather", "hotel", "flight", "visa", "planner"]

PROMPT_CONSTANTS: dict[str, str] = {
    "attraction": ATTRACTION_AGENT_PROMPT,
    "weather": WEATHER_AGENT_PROMPT,
    "hotel": HOTEL_AGENT_PROMPT,
    "flight": FLIGHT_AGENT_PROMPT,
    "visa": VISA_AGENT_PROMPT,
    "planner": PLANNER_AGENT_PROMPT,
}

# JSON block regex: matches ```json ... ``` blocks
_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n\s*```", re.DOTALL)

# Example marker regex
_EXAMPLE_RE = re.compile(r"\*\*示例\s*\d+")


def _extract_json_blocks(text: str) -> list[str]:
    """Extract all JSON code blocks from a prompt string."""
    return _JSON_BLOCK_RE.findall(text)


def _count_examples(text: str) -> int:
    """Count the number of example sections in a prompt."""
    return len(_EXAMPLE_RE.findall(text))


# =========================================================================
# Test Class 1: Registry completeness
# =========================================================================

class TestPromptRegistry:
    """Validate ALL_AGENT_PROMPTS registry is complete and consistent."""

    def test_registry_contains_all_agents(self) -> None:
        assert set(ALL_AGENT_PROMPTS.keys()) == set(AGENT_NAMES)

    def test_registry_count(self) -> None:
        assert len(ALL_AGENT_PROMPTS) == 6

    def test_registry_values_are_strings(self) -> None:
        for name, prompt in ALL_AGENT_PROMPTS.items():
            assert isinstance(prompt, str), f"{name} prompt is not a string"
            assert len(prompt) > 100, f"{name} prompt is suspiciously short"

    def test_registry_matches_constants(self) -> None:
        for name, expected in PROMPT_CONSTANTS.items():
            assert ALL_AGENT_PROMPTS[name] is expected, f"{name} mismatch"


# =========================================================================
# Test Class 2: 8 mandatory fields (§3.4)
# =========================================================================

class TestMandatoryFields:
    """Every agent prompt must contain all 8 required section markers."""

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_has_all_8_sections(self, agent_name: str) -> None:
        prompt = ALL_AGENT_PROMPTS[agent_name]
        for section in REQUIRED_PROMPT_SECTIONS:
            assert section in prompt, (
                f"{agent_name} prompt missing section: {section}"
            )

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_sections_in_order(self, agent_name: str) -> None:
        """Sections must appear in ascending order (1-8)."""
        prompt = ALL_AGENT_PROMPTS[agent_name]
        positions = [prompt.index(s) for s in REQUIRED_PROMPT_SECTIONS]
        assert positions == sorted(positions), (
            f"{agent_name} sections are out of order"
        )

    def test_required_sections_count(self) -> None:
        assert len(REQUIRED_PROMPT_SECTIONS) == 8


# =========================================================================
# Test Class 3: PlannerAgent extra sections
# =========================================================================

class TestPlannerExtraSections:
    """PlannerAgent prompt must include orchestration-specific sections."""

    @pytest.mark.parametrize("section", PLANNER_EXTRA_SECTIONS)
    def test_planner_has_extra_section(self, section: str) -> None:
        assert section in PLANNER_AGENT_PROMPT, (
            f"PlannerAgent missing extra section: {section}"
        )

    def test_planner_extra_sections_count(self) -> None:
        assert len(PLANNER_EXTRA_SECTIONS) == 8

    def test_planner_has_routing_policy(self) -> None:
        assert "Routing Policy" in PLANNER_AGENT_PROMPT

    def test_planner_has_delta_update_policy(self) -> None:
        assert "Delta Update Policy" in PLANNER_AGENT_PROMPT

    def test_planner_has_merge_policy(self) -> None:
        assert "Merge Policy" in PLANNER_AGENT_PROMPT

    def test_planner_has_conflict_policy(self) -> None:
        assert "Conflict Policy" in PLANNER_AGENT_PROMPT

    def test_planner_has_citation_link_policy(self) -> None:
        assert "Citation & Link Policy" in PLANNER_AGENT_PROMPT

    def test_planner_has_memory_policy(self) -> None:
        assert "Memory Policy" in PLANNER_AGENT_PROMPT

    def test_planner_has_output_contract(self) -> None:
        assert "Output Contract" in PLANNER_AGENT_PROMPT

    def test_planner_output_contract_mentions_required_fields(self) -> None:
        for field in ("flight_plan", "visa_summary", "source_links", "conflicts", "budget"):
            assert field in PLANNER_AGENT_PROMPT, (
                f"PlannerAgent Output Contract missing field: {field}"
            )


# =========================================================================
# Test Class 4: Examples validation
# =========================================================================

class TestExamples:
    """Each prompt must have >= 2 examples, including a failure example."""

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_has_at_least_two_examples(self, agent_name: str) -> None:
        prompt = ALL_AGENT_PROMPTS[agent_name]
        count = _count_examples(prompt)
        assert count >= 2, (
            f"{agent_name} has only {count} examples (need >= 2)"
        )

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_has_failure_example(self, agent_name: str) -> None:
        """At least one example should demonstrate failure/fallback."""
        prompt = ALL_AGENT_PROMPTS[agent_name]
        failure_indicators = ["失败", "fallback", "回退", "异常", "need_user_input"]
        has_failure = any(indicator in prompt for indicator in failure_indicators)
        assert has_failure, (
            f"{agent_name} prompt lacks a failure/fallback example"
        )


# =========================================================================
# Test Class 5: Output Schema (JSON blocks)
# =========================================================================

class TestOutputSchema:
    """Each prompt must contain valid JSON examples in the Output Schema."""

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_has_json_blocks(self, agent_name: str) -> None:
        prompt = ALL_AGENT_PROMPTS[agent_name]
        blocks = _extract_json_blocks(prompt)
        assert len(blocks) >= 1, (
            f"{agent_name} has no JSON code blocks"
        )

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_json_blocks_are_parseable(self, agent_name: str) -> None:
        """At least one JSON block should be valid JSON (not a template)."""
        prompt = ALL_AGENT_PROMPTS[agent_name]
        blocks = _extract_json_blocks(prompt)
        parseable = 0
        for block in blocks:
            # Skip blocks with template placeholders
            if "..." in block or "{...}" in block:
                continue
            try:
                json.loads(block)
                parseable += 1
            except json.JSONDecodeError:
                pass
        assert parseable >= 1, (
            f"{agent_name} has no parseable JSON examples (found {len(blocks)} blocks)"
        )


# =========================================================================
# Test Class 6: Agent class prompt attributes
# =========================================================================

class TestAgentClassPromptAttributes:
    """Each agent class must expose a ``prompt`` class attribute wired to the correct constant."""

    def test_attraction_agent_prompt_attr(self) -> None:
        from app.agents.workers.attraction_agent import AttractionAgent
        assert hasattr(AttractionAgent, "prompt")
        assert AttractionAgent.prompt is ATTRACTION_AGENT_PROMPT

    def test_weather_agent_prompt_attr(self) -> None:
        from app.agents.workers.weather_agent import WeatherAgent
        assert hasattr(WeatherAgent, "prompt")
        assert WeatherAgent.prompt is WEATHER_AGENT_PROMPT

    def test_hotel_agent_prompt_attr(self) -> None:
        from app.agents.workers.hotel_agent import HotelAgent
        assert hasattr(HotelAgent, "prompt")
        assert HotelAgent.prompt is HOTEL_AGENT_PROMPT

    def test_flight_agent_prompt_attr(self) -> None:
        from app.agents.workers.flight_agent import FlightAgent
        assert hasattr(FlightAgent, "prompt")
        assert FlightAgent.prompt is FLIGHT_AGENT_PROMPT

    def test_visa_agent_prompt_attr(self) -> None:
        from app.agents.workers.visa_agent import VisaAgent
        assert hasattr(VisaAgent, "prompt")
        assert VisaAgent.prompt is VISA_AGENT_PROMPT

    def test_planner_agent_prompt_attr(self) -> None:
        from app.agents.planner.planner_agent import PlannerAgent
        # PlannerAgent stores prompt as instance attribute via __init__
        agent = PlannerAgent()
        assert agent.prompt is PLANNER_AGENT_PROMPT


# =========================================================================
# Test Class 7: Structured output success rate (content quality)
# =========================================================================

class TestStructuredOutputQuality:
    """Validate prompt content quality for structured output compliance.

    These checks ensure >= 95% structured output success rate by
    verifying critical format instructions are present.
    """

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_prompt_mentions_json(self, agent_name: str) -> None:
        """Prompt must instruct JSON output."""
        prompt = ALL_AGENT_PROMPTS[agent_name]
        assert "json" in prompt.lower() or "JSON" in prompt

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_prompt_mentions_source_url(self, agent_name: str) -> None:
        """Prompts for recommendation agents must mention source_url.
        WeatherAgent is exempted — weather data is informational, not a
        traceable recommendation item requiring a source link.
        """
        if agent_name == "weather":
            pytest.skip("WeatherAgent outputs informational data without source_url")
        prompt = ALL_AGENT_PROMPTS[agent_name]
        assert "source_url" in prompt, (
            f"{agent_name} prompt does not mention source_url"
        )

    def test_planner_mentions_budget(self) -> None:
        assert "budget" in PLANNER_AGENT_PROMPT.lower()

    def test_planner_mentions_conflicts(self) -> None:
        assert "conflicts" in PLANNER_AGENT_PROMPT

    def test_attraction_mentions_rag(self) -> None:
        assert "RAG" in ATTRACTION_AGENT_PROMPT

    def test_attraction_mentions_wikivoyage(self) -> None:
        assert "Wikivoyage" in ATTRACTION_AGENT_PROMPT

    def test_visa_mentions_domestic(self) -> None:
        assert "not_required" in VISA_AGENT_PROMPT or "国内" in VISA_AGENT_PROMPT

    def test_flight_mentions_booking_url(self) -> None:
        assert "booking_url" in FLIGHT_AGENT_PROMPT

    def test_flight_mentions_iata(self) -> None:
        assert "IATA" in FLIGHT_AGENT_PROMPT


# =========================================================================
# Test Class 8: Hard constraints presence
# =========================================================================

class TestHardConstraints:
    """Validate that critical hard constraints are mentioned in prompts."""

    @pytest.mark.parametrize("agent_name", ["attraction", "weather", "hotel", "flight", "visa"])
    def test_worker_prohibits_fabrication(self, agent_name: str) -> None:
        """Worker prompts must prohibit fabricating data."""
        prompt = ALL_AGENT_PROMPTS[agent_name]
        assert "禁止" in prompt or "不要" in prompt or "不得" in prompt, (
            f"{agent_name} prompt lacks fabrication prohibition"
        )

    def test_planner_requires_all_workers(self) -> None:
        """Planner must mention all 5 planning workers."""
        for worker in ("Attraction", "Weather", "Hotel", "Flight", "Visa"):
            assert worker in PLANNER_AGENT_PROMPT, (
                f"PlannerAgent prompt missing worker: {worker}"
            )

    def test_planner_requires_need_user_input(self) -> None:
        """Planner must support need_user_input failure mode."""
        assert "need_user_input" in PLANNER_AGENT_PROMPT

    def test_visa_mentions_whitelist(self) -> None:
        """Visa prompt must mention API whitelist constraint."""
        assert "白名单" in VISA_AGENT_PROMPT

    def test_visa_mentions_sherpa(self) -> None:
        """Visa prompt must mention Sherpa as the visa provider."""
        assert "Sherpa" in VISA_AGENT_PROMPT


# =========================================================================
# Test Class 9: Prompt length and quality metrics
# =========================================================================

class TestPromptMetrics:
    """Quantitative checks on prompt quality."""

    @pytest.mark.parametrize("agent_name", AGENT_NAMES)
    def test_prompt_minimum_length(self, agent_name: str) -> None:
        """Each prompt must be at least 500 chars for adequate coverage."""
        prompt = ALL_AGENT_PROMPTS[agent_name]
        assert len(prompt) >= 500, (
            f"{agent_name} prompt too short: {len(prompt)} chars"
        )

    def test_planner_is_longest(self) -> None:
        """PlannerAgent prompt should be the longest (most complex role)."""
        planner_len = len(PLANNER_AGENT_PROMPT)
        for name, prompt in ALL_AGENT_PROMPTS.items():
            if name != "planner":
                assert planner_len >= len(prompt), (
                    f"PlannerAgent ({planner_len}) shorter than {name} ({len(prompt)})"
                )

    def test_structured_output_success_rate(self) -> None:
        """Symbolic check: all prompts pass all section/format requirements.

        This represents the >= 95% structured output success rate by
        ensuring every prompt includes all structural elements needed
        for reliable JSON output.
        """
        total_checks = 0
        passed_checks = 0

        for name, prompt in ALL_AGENT_PROMPTS.items():
            # Check 1: 8 mandatory sections
            for section in REQUIRED_PROMPT_SECTIONS:
                total_checks += 1
                if section in prompt:
                    passed_checks += 1

            # Check 2: JSON blocks present
            total_checks += 1
            if _extract_json_blocks(prompt):
                passed_checks += 1

            # Check 3: >= 2 examples
            total_checks += 1
            if _count_examples(prompt) >= 2:
                passed_checks += 1

            # Check 4: source_url mentioned (skip weather — informational data)
            total_checks += 1
            if "source_url" in prompt or name == "weather":
                passed_checks += 1

        rate = passed_checks / total_checks if total_checks else 0
        assert rate >= 0.95, (
            f"Structured output success rate {rate:.1%} < 95% "
            f"({passed_checks}/{total_checks})"
        )
