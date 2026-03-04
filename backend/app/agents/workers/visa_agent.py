"""VisaAgent — LangGraph worker that queries visa requirements via pluggable provider.

Implemented for C7. Key behaviour:
- **Cross-border** trips trigger ``ProviderRegistry.visa.get_requirements()``.
- **Domestic** trips (same-country) skip the external call entirely and
  return ``visa_required=False`` with ``not_required`` status immediately.
- All results include ``source_url`` for traceability.
- ``as_worker()`` returns ``{"visa_summary": {...}}`` for PlannerAgent.

Acceptance:
  1. 跨国触发外部签证查询
  2. 国内不触发外部查询且返回 not_required
  3. 结果可解释且附来源链接
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from app.models.schemas import TripRequest, VisaRequirement
from app.prompts.trip_prompts import VISA_AGENT_PROMPT

if TYPE_CHECKING:
    from app.providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# City → Country code mapping (ISO 3166-1 alpha-2)
# ---------------------------------------------------------------------------

CITY_COUNTRY: dict[str, str] = {
    # China (domestic)
    "北京": "CN", "上海": "CN", "广州": "CN", "深圳": "CN",
    "成都": "CN", "杭州": "CN", "西安": "CN", "南京": "CN",
    "重庆": "CN", "武汉": "CN", "长沙": "CN", "昆明": "CN",
    "厦门": "CN", "青岛": "CN", "大连": "CN", "三亚": "CN",
    "海口": "CN", "哈尔滨": "CN", "贵阳": "CN", "桂林": "CN",
    "拉萨": "CN", "乌鲁木齐": "CN", "天津": "CN", "郑州": "CN",
    "济南": "CN", "福州": "CN", "合肥": "CN", "太原": "CN",
    "沈阳": "CN", "长春": "CN", "南昌": "CN", "南宁": "CN",
    "兰州": "CN", "银川": "CN", "西宁": "CN", "呼和浩特": "CN",
    "石家庄": "CN",
    # Japan
    "东京": "JP", "大阪": "JP", "京都": "JP", "名古屋": "JP",
    "札幌": "JP", "福冈": "JP", "冲绳": "JP", "奈良": "JP",
    # South Korea
    "首尔": "KR", "釜山": "KR", "济州": "KR",
    # Southeast Asia
    "曼谷": "TH", "清迈": "TH", "普吉": "TH",
    "新加坡": "SG",
    "吉隆坡": "MY", "槟城": "MY",
    "河内": "VN", "胡志明市": "VN",
    "马尼拉": "PH", "宿务": "PH",
    "巴厘岛": "ID", "雅加达": "ID",
    "金边": "KH", "暹粒": "KH",
    # Special Administrative Regions
    "香港": "HK", "澳门": "MO", "台北": "TW", "高雄": "TW",
    # Europe
    "巴黎": "FR", "伦敦": "GB", "罗马": "IT", "米兰": "IT",
    "柏林": "DE", "慕尼黑": "DE", "巴塞罗那": "ES", "马德里": "ES",
    "阿姆斯特丹": "NL", "维也纳": "AT", "布拉格": "CZ", "苏黎世": "CH",
    # Americas
    "纽约": "US", "洛杉矶": "US", "旧金山": "US", "芝加哥": "US",
    "温哥华": "CA", "多伦多": "CA",
    # Oceania
    "悉尼": "AU", "墨尔本": "AU", "奥克兰": "NZ",
    # Middle East
    "迪拜": "AE", "阿布扎比": "AE",
}

# Default nationality when not provided
_DEFAULT_NATIONALITY = "CN"

# Domestic not-required source URL template
_DOMESTIC_SOURCE_URL = (
    "https://www.gov.cn/banshi/travel"
)


class VisaAgent:
    """Check visa requirements for a trip destination.

    For **cross-border** trips (origin country ≠ destination country),
    uses ``ProviderRegistry.visa.get_requirements()`` to fetch real
    visa data from the configured provider (e.g. Sherpa).

    For **domestic** trips (same country), returns ``not_required``
    immediately without any external API call.

    Args:
        registry: Optional pre-built ``ProviderRegistry``. When *None*,
            the module-level singleton is resolved lazily on first call.
        default_nationality: Default traveler nationality ISO 3166-1 alpha-2.
    """

    prompt: str = VISA_AGENT_PROMPT

    def __init__(
        self,
        registry: "ProviderRegistry | None" = None,
        default_nationality: str = _DEFAULT_NATIONALITY,
    ) -> None:
        self._registry = registry
        self._default_nationality = default_nationality.upper()

    # ------------------------------------------------------------------
    # Provider access (lazy)
    # ------------------------------------------------------------------

    @property
    def _reg(self) -> "ProviderRegistry":
        """Lazy-resolve the provider registry."""
        if self._registry is None:
            from app.providers.registry import get_provider_registry

            self._registry = get_provider_registry()
        return self._registry

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def run(
        self,
        request: TripRequest,
        *,
        nationality: str | None = None,
    ) -> dict:
        """Check visa requirements for the trip destination.

        Args:
            request: A ``TripRequest`` with ``city`` and ``travel_days``.
            nationality: Override traveler nationality (ISO 3166-1 alpha-2).

        Returns:
            A dict conforming to the planner's ``visa_summary`` schema::

                {
                    "visa_required": bool,
                    "requirements": [...],
                    "nationality": "CN",
                    "destination_country": "JP",
                    "is_domestic": False,
                    "source_url": "...",
                    "explanation": "...",
                }
        """
        nat = (nationality or self._default_nationality).upper()
        dest_country = self._city_to_country(request.city)

        is_domestic = self._is_domestic(nat, dest_country)

        logger.info(
            "VisaAgent.run: nationality=%s dest=%s(%s) domestic=%s",
            nat, request.city, dest_country, is_domestic,
        )

        if is_domestic:
            return self._build_domestic_result(nat, dest_country, request.city)

        # Cross-border: query the visa provider
        return self._query_provider(nat, dest_country, request)

    # ------------------------------------------------------------------
    # Domestic result (no external call)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_domestic_result(
        nationality: str,
        dest_country: str,
        city: str,
    ) -> dict:
        """Build a ``not_required`` result for domestic travel."""
        return {
            "visa_required": False,
            "requirements": [],
            "nationality": nationality,
            "destination_country": dest_country,
            "is_domestic": True,
            "source_url": _DOMESTIC_SOURCE_URL,
            "explanation": f"国内旅行（{city}），无需签证。",
        }

    # ------------------------------------------------------------------
    # Cross-border query
    # ------------------------------------------------------------------

    def _query_provider(
        self,
        nationality: str,
        dest_country: str,
        request: TripRequest,
    ) -> dict:
        """Query the visa provider for cross-border requirements."""
        try:
            requirements = self._reg.visa.get_requirements(
                nationality=nationality,
                destination=dest_country,
                travel_duration_days=request.travel_days,
            )
        except Exception:
            logger.warning(
                "Visa provider query failed, returning unknown",
                exc_info=True,
            )
            requirements = []

        visa_required = any(r.visa_required for r in requirements)
        serialized = [r.model_dump() for r in requirements]
        source_url = self._pick_source_url(requirements, nationality, dest_country)
        explanation = self._build_explanation(
            requirements, nationality, dest_country, request.city,
        )

        return {
            "visa_required": visa_required,
            "requirements": serialized,
            "nationality": nationality,
            "destination_country": dest_country,
            "is_domestic": False,
            "source_url": source_url,
            "explanation": explanation,
        }

    # ------------------------------------------------------------------
    # Explanation builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_explanation(
        requirements: list[VisaRequirement],
        nationality: str,
        dest_country: str,
        city: str,
    ) -> str:
        """Build a human-readable explanation of visa requirements."""
        if not requirements:
            return (
                f"从 {nationality} 前往 {city}（{dest_country}）的签证信息暂无数据，"
                f"建议查阅目的地官方签证网站。"
            )

        required_list = [r for r in requirements if r.visa_required]
        if not required_list:
            return (
                f"从 {nationality} 前往 {city}（{dest_country}）无需签证或已免签。"
            )

        # Summarize required visa types
        types = [r.visa_type or "签证" for r in required_list]
        docs_all = []
        for r in required_list:
            docs_all.extend(r.documents)
        unique_docs = list(dict.fromkeys(docs_all))  # deduplicate preserving order

        parts = [
            f"从 {nationality} 前往 {city}（{dest_country}）需要办理：{', '.join(types)}。"
        ]
        if unique_docs:
            parts.append(f"所需材料：{', '.join(unique_docs[:5])}。")
        if required_list[0].processing_time:
            parts.append(f"办理时效：{required_list[0].processing_time}。")

        return " ".join(parts)

    # ------------------------------------------------------------------
    # Source URL helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pick_source_url(
        requirements: list[VisaRequirement],
        nationality: str,
        dest_country: str,
    ) -> str:
        """Pick a representative source URL from the requirements."""
        for r in requirements:
            if r.source_url:
                return r.source_url
        return (
            f"https://apply.joinsherpa.com/travel-restrictions"
            f"?nationality={nationality}&destination={dest_country}"
        )

    # ------------------------------------------------------------------
    # City → Country mapping
    # ------------------------------------------------------------------

    @staticmethod
    def _city_to_country(city: str) -> str:
        """Convert a city name to its ISO 3166-1 alpha-2 country code.

        Returns ``"XX"`` for unknown cities (triggers cross-border path
        to be safe — better to over-check than miss a visa requirement).
        """
        return CITY_COUNTRY.get(city, "XX")

    # ------------------------------------------------------------------
    # Domestic detection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_domestic(nationality: str, dest_country: str) -> bool:
        """Determine if the trip is domestic (same country).

        Special handling: HK/MO/TW are treated as cross-border for CN
        nationals (different visa/travel document requirements).
        """
        if dest_country == "XX":
            return False  # Unknown destination → treat as cross-border
        # HK, MO, TW require special travel documents for CN nationals
        if nationality == "CN" and dest_country in ("HK", "MO", "TW"):
            return False
        return nationality == dest_country

    # ------------------------------------------------------------------
    # WorkerFn protocol adapter
    # ------------------------------------------------------------------

    def as_worker(self) -> Callable[..., dict]:
        """Return a ``WorkerFn``-compatible callable for PlannerAgent.

        The returned function takes ``PlannerState`` and returns a dict
        with key ``visa_summary`` containing the structured visa data.
        """

        def _worker(state: dict) -> dict:
            request = TripRequest(**state["request"])
            summary = self.run(request)
            return {
                "visa_summary": summary,
            }

        return _worker
