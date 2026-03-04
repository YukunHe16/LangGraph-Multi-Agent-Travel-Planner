"""Data models for trip planning APIs and agent contracts."""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator


class TripRequest(BaseModel):
    """Trip planning request payload."""

    city: str = Field(..., description="目的地城市", examples=["北京"])
    start_date: str = Field(..., description="开始日期 YYYY-MM-DD", examples=["2026-06-01"])
    end_date: str = Field(..., description="结束日期 YYYY-MM-DD", examples=["2026-06-03"])
    travel_days: int = Field(..., description="旅行天数", ge=1, le=30, examples=[3])
    transportation: str = Field(..., description="交通方式", examples=["公共交通"])
    accommodation: str = Field(..., description="住宿偏好", examples=["经济型酒店"])
    preferences: List[str] = Field(default_factory=list, description="旅行偏好标签")
    free_text_input: Optional[str] = Field(default="", description="额外要求")

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_iso_date(cls, value: str) -> str:
        """Validate date fields in YYYY-MM-DD format."""
        datetime.strptime(value, "%Y-%m-%d")
        return value

    @field_validator("travel_days")
    @classmethod
    def validate_travel_days(cls, value: int) -> int:
        """Validate travel day count is positive and practical."""
        if value < 1:
            raise ValueError("travel_days must be >= 1")
        return value


class POISearchRequest(BaseModel):
    """POI search request."""

    keywords: str = Field(..., description="搜索关键词", examples=["故宫"])
    city: str = Field(..., description="城市", examples=["北京"])
    citylimit: bool = Field(default=True, description="是否限制在城市范围内")


class RouteRequest(BaseModel):
    """Route planning request."""

    origin_address: str = Field(..., description="起点地址")
    destination_address: str = Field(..., description="终点地址")
    origin_city: Optional[str] = Field(default=None, description="起点城市")
    destination_city: Optional[str] = Field(default=None, description="终点城市")
    route_type: Literal["walking", "driving", "transit"] = Field(
        default="walking",
        description="路线类型: walking/driving/transit",
    )


class Location(BaseModel):
    """Geospatial coordinate."""

    longitude: float = Field(..., description="经度")
    latitude: float = Field(..., description="纬度")


class Attraction(BaseModel):
    """Attraction information."""

    name: str = Field(..., description="景点名称")
    address: str = Field(..., description="地址")
    location: Location = Field(..., description="经纬度坐标")
    visit_duration: int = Field(..., description="建议游览时间(分钟)")
    description: str = Field(..., description="景点描述")
    category: Optional[str] = Field(default="景点", description="景点类别")
    rating: Optional[float] = Field(default=None, description="评分")
    photos: List[str] = Field(default_factory=list, description="景点图片URL列表")
    poi_id: Optional[str] = Field(default="", description="POI ID")
    image_url: Optional[str] = Field(default=None, description="图片URL")
    source_url: Optional[str] = Field(default=None, description="来源链接")
    ticket_price: int = Field(default=0, description="门票价格(元)")


class Meal(BaseModel):
    """Meal information."""

    type: str = Field(..., description="餐饮类型: breakfast/lunch/dinner/snack")
    name: str = Field(..., description="餐饮名称")
    address: Optional[str] = Field(default=None, description="地址")
    location: Optional[Location] = Field(default=None, description="经纬度坐标")
    description: Optional[str] = Field(default=None, description="描述")
    estimated_cost: int = Field(default=0, description="预估费用(元)")


class Hotel(BaseModel):
    """Hotel information."""

    name: str = Field(..., description="酒店名称")
    address: str = Field(default="", description="酒店地址")
    location: Optional[Location] = Field(default=None, description="酒店位置")
    price_range: str = Field(default="", description="价格范围")
    rating: str = Field(default="", description="评分")
    distance: str = Field(default="", description="距离景点距离")
    type: str = Field(default="", description="酒店类型")
    source_url: Optional[str] = Field(default=None, description="来源链接")
    estimated_cost: int = Field(default=0, description="预估费用(元/晚)")


class DayPlan(BaseModel):
    """Daily itinerary."""

    date: str = Field(..., description="日期 YYYY-MM-DD")
    day_index: int = Field(..., description="第几天(从0开始)")
    description: str = Field(..., description="当日行程描述")
    transportation: str = Field(..., description="交通方式")
    accommodation: str = Field(..., description="住宿")
    hotel: Optional[Hotel] = Field(default=None, description="推荐酒店")
    attractions: List[Attraction] = Field(default_factory=list, description="景点列表")
    meals: List[Meal] = Field(default_factory=list, description="餐饮列表")


class WeatherInfo(BaseModel):
    """Weather information."""

    date: str = Field(..., description="日期 YYYY-MM-DD")
    day_weather: str = Field(default="", description="白天天气")
    night_weather: str = Field(default="", description="夜间天气")
    day_temp: Union[int, str] = Field(default=0, description="白天温度")
    night_temp: Union[int, str] = Field(default=0, description="夜间温度")
    wind_direction: str = Field(default="", description="风向")
    wind_power: str = Field(default="", description="风力")

    @field_validator("day_temp", "night_temp", mode="before")
    @classmethod
    def parse_temperature(cls, value: Union[int, str]) -> int:
        """Normalize string temperatures like '25°C' to integer."""
        if isinstance(value, str):
            normalized = value.replace("°C", "").replace("℃", "").replace("°", "").strip()
            try:
                return int(normalized)
            except ValueError:
                return 0
        return int(value)


class Budget(BaseModel):
    """Budget breakdown."""

    total_attractions: int = Field(default=0, description="景点门票总费用")
    total_hotels: int = Field(default=0, description="酒店总费用")
    total_meals: int = Field(default=0, description="餐饮总费用")
    total_transportation: int = Field(default=0, description="交通总费用")
    total: int = Field(default=0, description="总费用")


class TripPlan(BaseModel):
    """Generated trip plan."""

    city: str = Field(..., description="目的地城市")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    days: List[DayPlan] = Field(default_factory=list, description="每日行程")
    weather_info: List[WeatherInfo] = Field(default_factory=list, description="天气信息")
    overall_suggestions: str = Field(..., description="总体建议")
    budget: Optional[Budget] = Field(default=None, description="预算信息")


class TripPlanResponse(BaseModel):
    """API response wrapper for trip plans."""

    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: Optional[TripPlan] = Field(default=None, description="旅行计划数据")


class POIInfo(BaseModel):
    """POI item."""

    id: str = Field(..., description="POI ID")
    name: str = Field(..., description="名称")
    type: str = Field(..., description="类型")
    address: str = Field(..., description="地址")
    location: Location = Field(..., description="经纬度坐标")
    tel: Optional[str] = Field(default=None, description="电话")


class POISearchResponse(BaseModel):
    """POI search response."""

    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: List[POIInfo] = Field(default_factory=list, description="POI列表")


class RouteInfo(BaseModel):
    """Route summary."""

    distance: float = Field(..., description="距离(米)")
    duration: int = Field(..., description="时间(秒)")
    route_type: str = Field(..., description="路线类型")
    description: str = Field(..., description="路线描述")


class RouteResponse(BaseModel):
    """Route planning response."""

    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: Optional[RouteInfo] = Field(default=None, description="路线信息")


class WeatherResponse(BaseModel):
    """Weather query response."""

    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: List[WeatherInfo] = Field(default_factory=list, description="天气信息")


class ErrorResponse(BaseModel):
    """Error response payload."""

    success: bool = Field(default=False, description="是否成功")
    message: str = Field(..., description="错误消息")
    error_code: Optional[str] = Field(default=None, description="错误代码")


class POIDetail(BaseModel):
    """POI detail payload."""

    id: str = Field(..., description="POI ID")
    name: str = Field(..., description="POI名称")
    address: str = Field(default="", description="POI地址")
    source: str = Field(default="amap", description="数据来源")


class POIDetailResponse(BaseModel):
    """POI detail response wrapper."""

    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: POIDetail = Field(..., description="POI详情")


class AttractionPhotoData(BaseModel):
    """Attraction photo payload."""

    name: str = Field(..., description="景点名称")
    photo_url: Optional[str] = Field(default=None, description="图片链接")


class AttractionPhotoResponse(BaseModel):
    """Attraction photo response wrapper."""

    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: AttractionPhotoData = Field(..., description="图片信息")


class MapPOISearchInput(BaseModel):
    """Map provider POI search input contract."""

    keywords: str = Field(..., min_length=1, description="搜索关键词")
    city: str = Field(..., min_length=1, description="城市")
    citylimit: bool = Field(default=True, description="是否限制在城市范围内")


class MapPOISearchOutput(BaseModel):
    """Map provider POI search output contract."""

    provider: str = Field(default="amap", description="provider 标识")
    items: List[POIInfo] = Field(default_factory=list, description="POI列表")


class MapWeatherInput(BaseModel):
    """Map provider weather query input contract."""

    city: str = Field(..., min_length=1, description="城市")


class MapWeatherOutput(BaseModel):
    """Map provider weather query output contract."""

    provider: str = Field(default="amap", description="provider 标识")
    items: List[WeatherInfo] = Field(default_factory=list, description="天气列表")


class PhotoSearchInput(BaseModel):
    """Photo provider input contract."""

    query: str = Field(..., min_length=1, description="查询词")
    per_page: int = Field(default=5, ge=1, le=30, description="数量")


class PhotoItem(BaseModel):
    """Photo item output contract."""

    id: Optional[str] = Field(default=None, description="图片ID")
    url: Optional[str] = Field(default=None, description="图片链接")
    thumb: Optional[str] = Field(default=None, description="缩略图链接")
    description: Optional[str] = Field(default=None, description="描述")
    photographer: Optional[str] = Field(default=None, description="摄影师")


class PhotoSearchOutput(BaseModel):
    """Photo provider output contract."""

    provider: str = Field(default="unsplash", description="provider 标识")
    items: List[PhotoItem] = Field(default_factory=list, description="图片列表")


class FlightSearchInput(BaseModel):
    """Flight provider search input contract."""

    origin: str = Field(..., min_length=3, max_length=3, description="出发地 IATA 代码")
    destination: str = Field(..., min_length=3, max_length=3, description="目的地 IATA 代码")
    departure_date: str = Field(..., description="出发日期 YYYY-MM-DD")
    return_date: Optional[str] = Field(default=None, description="返回日期 YYYY-MM-DD（单程可省略）")
    adults: int = Field(default=1, ge=1, le=9, description="成人数")
    max_results: int = Field(default=5, ge=1, le=20, description="最大返回结果数")

    @field_validator("origin", "destination")
    @classmethod
    def validate_iata(cls, value: str) -> str:
        """Ensure IATA codes are uppercase."""
        return value.upper()

    @field_validator("departure_date", "return_date")
    @classmethod
    def validate_flight_date(cls, value: Optional[str]) -> Optional[str]:
        """Validate date fields in YYYY-MM-DD format when provided."""
        if value is not None:
            datetime.strptime(value, "%Y-%m-%d")
        return value


class FlightSegment(BaseModel):
    """A single flight leg within an offer."""

    departure_airport: str = Field(..., description="出发机场 IATA")
    arrival_airport: str = Field(..., description="到达机场 IATA")
    departure_time: str = Field(..., description="出发时间 ISO 8601")
    arrival_time: str = Field(..., description="到达时间 ISO 8601")
    carrier: str = Field(..., description="航空公司代码")
    flight_number: str = Field(..., description="航班号")
    duration: Optional[str] = Field(default=None, description="飞行时长 ISO 8601 duration")


class FlightOffer(BaseModel):
    """A single flight offer returned by a provider."""

    id: str = Field(..., description="报价 ID")
    price: float = Field(..., description="总价")
    currency: str = Field(default="EUR", description="货币")
    outbound_segments: List[FlightSegment] = Field(default_factory=list, description="去程航段")
    return_segments: List[FlightSegment] = Field(default_factory=list, description="回程航段")
    booking_url: Optional[str] = Field(default=None, description="预订链接")
    source_url: Optional[str] = Field(default=None, description="来源链接")
    carrier_name: Optional[str] = Field(default=None, description="主承运航空公司名称")
    total_duration: Optional[str] = Field(default=None, description="总时长")


class FlightSearchOutput(BaseModel):
    """Flight provider output contract."""

    provider: str = Field(default="amadeus", description="provider 标识")
    items: List[FlightOffer] = Field(default_factory=list, description="航班报价列表")


class VisaRequirementsInput(BaseModel):
    """Visa provider input contract."""

    nationality: str = Field(..., min_length=2, max_length=2, description="国籍 ISO 3166-1 alpha-2")
    destination: str = Field(..., min_length=2, max_length=2, description="目的地国家 ISO 3166-1 alpha-2")
    travel_duration_days: int = Field(default=7, ge=1, le=365, description="旅行天数")

    @field_validator("nationality", "destination")
    @classmethod
    def validate_country_code(cls, value: str) -> str:
        """Ensure country codes are uppercase."""
        return value.upper()


class VisaRequirement(BaseModel):
    """Visa requirement details returned by a provider."""

    visa_required: bool = Field(..., description="是否需要签证")
    visa_type: Optional[str] = Field(default=None, description="签证类型（如 tourist, transit）")
    documents: List[str] = Field(default_factory=list, description="所需材料清单")
    processing_time: Optional[str] = Field(default=None, description="办理时效")
    validity: Optional[str] = Field(default=None, description="签证有效期")
    notes: Optional[str] = Field(default=None, description="风险提示或备注")
    source_url: str = Field(..., description="来源链接（强制）")


class VisaRequirementsOutput(BaseModel):
    """Visa provider output contract."""

    provider: str = Field(default="sherpa", description="provider 标识")
    nationality: str = Field(..., description="查询国籍")
    destination: str = Field(..., description="目的地国家")
    requirements: List[VisaRequirement] = Field(default_factory=list, description="签证要求列表")


class WorkerContext(BaseModel):
    """Agent worker context contract."""

    city: str = Field(..., min_length=1, description="目的地城市")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    travel_days: int = Field(..., ge=1, le=30, description="旅行天数")
    preferences: List[str] = Field(default_factory=list, description="偏好")


class AttractionWorkerOutput(BaseModel):
    """Attraction worker intermediate output contract."""

    attractions: List[Attraction] = Field(default_factory=list, description="景点候选")


class WeatherWorkerOutput(BaseModel):
    """Weather worker intermediate output contract."""

    weather_info: List[WeatherInfo] = Field(default_factory=list, description="天气候选")


class HotelWorkerOutput(BaseModel):
    """Hotel worker intermediate output contract."""

    hotel: Hotel = Field(..., description="酒店候选")


class PlannerSynthesisInput(BaseModel):
    """Planner synthesis stage contract."""

    request: TripRequest = Field(..., description="原始请求")
    attractions: List[Attraction] = Field(default_factory=list, description="景点结果")
    weather_info: List[WeatherInfo] = Field(default_factory=list, description="天气结果")
    hotel: Optional[Hotel] = Field(default=None, description="酒店结果")
