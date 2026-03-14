# API Reference

Base URL (local): `http://127.0.0.1:8010`

Interactive docs:
- Swagger UI: `GET /docs`
- OpenAPI JSON: `GET /openapi.json`

## Core Endpoints

### `GET /`

Service metadata.

Sample response:

```json
{
  "name": "Project1 Travel Planner API",
  "status": "running",
  "docs": "/docs"
}
```

### `GET /api/health`

Backend health check.

Sample response:

```json
{
  "status": "ok",
  "app": "Project1 Travel Planner API",
  "env": "dev"
}
```

### `POST /api/graph/bootstrap`

Minimal planner-graph bootstrap endpoint.

Request:

```json
{
  "user_input": "from-api"
}
```

Response:

```json
{
  "result": {
    "message": "from-api"
  }
}
```

## Trip Planning

### `POST /api/trip/plan`

Generate a trip plan through `PlannerAgent`.

Request schema:

```json
{
  "city": "北京",
  "start_date": "2026-06-01",
  "end_date": "2026-06-03",
  "travel_days": 3,
  "transportation": "公共交通",
  "accommodation": "舒适型酒店",
  "preferences": ["美食", "历史文化"],
  "free_text_input": ""
}
```

Response schema (abridged):

```json
{
  "success": true,
  "message": "旅行计划生成成功",
  "data": {
    "city": "北京",
    "start_date": "2026-06-01",
    "end_date": "2026-06-03",
    "days": [],
    "weather_info": [],
    "overall_suggestions": "...",
    "budget": {
      "total_attractions": 0,
      "total_hotels": 0,
      "total_meals": 0,
      "total_transportation": 0,
      "total": 0
    },
    "flight_plan": null,
    "visa_summary": {},
    "source_links": [],
    "conflicts": []
  }
}
```

Notes:
- Dates must be `YYYY-MM-DD`.
- `travel_days` range: `1..30`.
- The frontend may send extra fields (for UI compatibility). Backend focuses on the validated trip schema.

### `GET /api/trip/health`

Trip route group health check.

## Map Endpoints

### `GET /api/map/poi`

Query params:
- `keywords` (required)
- `city` (required)
- `citylimit` (optional, default `true`)

### `GET /api/map/weather`

Query params:
- `city` (required)

### `POST /api/map/route`

Request schema:

```json
{
  "origin_address": "天安门",
  "destination_address": "故宫博物院",
  "origin_city": "北京",
  "destination_city": "北京",
  "route_type": "walking"
}
```

### `GET /api/map/health`

Map route group health check.

## POI Endpoints

### `GET /api/poi/search`

Query params:
- `keywords` (required)
- `city` (optional, default `北京`)

### `GET /api/poi/detail/{poi_id}`

Path param:
- `poi_id` (required)

### `GET /api/poi/photo`

Query params:
- `name` (required)

## Error Contract

On server-side failures, routes return:

```json
{
  "detail": "错误描述..."
}
```

For response-model wrapped errors (where defined), `ErrorResponse` schema is:

```json
{
  "success": false,
  "message": "错误消息",
  "error_code": "OPTIONAL_CODE"
}
```

