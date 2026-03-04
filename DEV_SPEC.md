# Developer Specification (DEV_SPEC)

> 项目名称：LangGraph Multi-Agent Travel Planner  
> 版本：v1.0  
> 基线项目：`/Users/yukun/hello-agents/code/chapter13/helloagents-trip-planner`  
> RAG 依赖：`/Users/yukun/MODULAR-RAG-MCP-SERVER`

---

## 1. 项目概述

本项目是在 `helloagents-trip-planner` (文件位置：/Users/yukun/hello-agents/code/chapter13/helloagents-trip-planner) 基础上的升级版，目标是从“单一旅行规划 Agent”演进为“可插拔工具 + 多 Agent 协作 + RAG 知识增强 + 导出日历”的工程化系统。

### 1.1 设计理念

- 保留原项目已有价值：前后端页面结构、基本 API 组织、地图展示、预算计算、行程编辑、PDF/图片导出能力尽量复用。
- 重构核心智能体层：全部迁移到 `LangChain + LangGraph`，统一 Agent、工具、状态编排方式。
- 分层迁移策略：前后端与业务服务代码优先“直接迁移+小改”；原 `HelloAgents` 运行时相关 Agent 代码必须“重写为 LangChain/LangGraph 实现后再迁移”。
- 可插拔优先：地图、照片、航班、签证数据源、导出目标都通过 Provider 抽象接入，支持配置切换与 fallback。
- Agent-first：新增 Agent 均必须具备 LLM 推理 + Tool 调用 + 结构化输出能力，能够自主规划下一步。
- 最小化 UI 改动：前后端复杂度不做无谓增加，前端仅做配色降噪（去掉当前过于花哨的混色/紫色主调）。

### 1.2 项目定位

- 定位为“Multi-Agent + RAG”的实战项目，不是重前端视觉项目。
- 重点交付：
  - 能运行的可编排多 Agent 系统。
  - 清晰、可测试、可扩展的工具层抽象。
  - 可落地的开发工作流（skills 驱动）。

### 1.3 范围边界

- In Scope：
  - 新增/增强 `PlannerAgent(兼任Orchestrator)`、`FlightAgent`、`VisaAgent`。
  - 建立 `Wikivoyage` 中国/日本旅游文档爬取与 RAG 入库流水线。
  - `AttractionAgent` 接入 RAG 工具，按用户目的地检索知识库并返回景点推荐。
  - 在 `Project1` 内实现 Wikivoyage 数据接入与 RAG 桥接层；将 `MODULAR-RAG-MCP-SERVER` 作为外部依赖调用，不修改其源码。
  - 地图/照片/航班工具可插拔。
  - Google Calendar 导出。
  - 跨国行程时触发签证查询。
- Out of Scope（当前版本）：
  - 用户自主上传本地文档并触发行程增强。
  - 修改 `MODULAR-RAG-MCP-SERVER` 仓库中的业务代码与架构。
  - 完整 OTA 级别机票下单。
  - 全自动签证办理。
  - 高复杂度权限系统与多租户隔离。

---

## 2. 核心特点

### 2.1 多 Agent 编排（LangGraph）

- 以 `PlannerAgent` 为中枢（兼任 Orchestrator），负责任务分解、路由、结果聚合、最终行程生成。
- Worker Agent 严格限定为且只为：`AttractionAgent`、`WeatherAgent`、`HotelAgent`、`FlightAgent`、`VisaAgent`、`ExportAgent`。
- 其中 `AttractionAgent`、`WeatherAgent`、`HotelAgent` 与 `PlannerAgent` 均来自 hello agent 项目代码复用与改造（`PlannerAgent` 作为中枢而非 worker）。
- 默认规划模式下，`PlannerAgent` 必须综合考虑 `Attraction/Weather/Hotel/Flight/Visa` 后再输出计划（非跨国场景 `Visa` 返回 `not_required` 结论）。
- 景点增强模式下，`AttractionAgent` 必须优先通过 RAG 工具检索 Wikivoyage 中国/日本景点知识库，再结合地图/图片工具输出候选景点。
- 多轮对话模式下，必须采用“增量重算”策略：仅重跑受用户修改影响的 worker（例如更换航班只重跑 `FlightAgent`）。

### 2.2 工具可插拔架构

- 地图 Provider：默认高德，支持切换 Google Maps。
- 照片 Provider：默认 Unsplash，支持切换 Google Places Photo。
- 航班 Provider：统一接口，支持至少一个实时航班 API，实现可替换。
- 导出 Provider：PDF/Image（继承原项目）+ Google Calendar（新增）。

### 2.3 跨国逻辑感知

- 前端新增用户国籍输入。
- 默认规划中纳入签证维度评估；仅在“出发国 != 目的地国”场景触发 `VisaAgent` 外部查询，非跨国返回 `not_required`。

### 2.4 Wikivoyage 知识库与 RAG 增强

- 数据获取采用“全量 Dump 模式（当前版本）”：
  - 数据来源固定为 Wikimedia Dumps `latest` 路径。
  - 当前版本不启用 MediaWiki API 增量拉取，仅支持全量重建索引。
- 在 `Project1` 内完成抓取/清洗/切分/入库编排；通过桥接层调用 `MODULAR-RAG-MCP-SERVER` 现有 ingest/query 能力，不修改其源码。
- 规划时按用户输入的目的地（可多城市）检索知识库，返回可追溯的景点推荐依据。
- RAG 返回内容必须保留来源 URL，供 `AttractionAgent` 和最终回答透传。
- 入库文档必须保留追溯字段：`page_title`、`page_id`、`revision_id`、`source_url`、`retrieved_at`。

### 2.5 Prompt 工程化

- 每个新 Agent 配套结构化 Prompt（角色、约束、工具策略、输出 schema、失败策略）。
- Prompt 设计采用模块化原则（参考 `lec3-prompting-principles.md`）并做回归测试。

### 2.6 短期记忆与摘要压缩

- 系统必须支持会话级短期记忆，保留合理 `max_tokens` 的近期对话原文。
- 当对话超过阈值时，超出部分必须自动压缩为摘要并持久化，避免上下文无限膨胀。
- 记忆能力由 `PlannerAgent` 统一消费，确保默认规划、景点增强、多轮增量更新都具备上下文连续性。

### 2.7 链接可追溯返回（强制）

- 凡 agent 通过外部来源获取信息并返回给用户，必须同时返回可访问的来源链接或深链（deep link）。
- 凡 agent 给出可执行推荐（如航班、酒店、景点），必须返回对应推荐项的跳转链接。
- 若外部服务无法提供 item 级 deep link，必须返回最小可追溯链接（官方来源页或查询结果页）并标注原因。

### 2.8 Skills 驱动开发流程（强制）

- 本项目开发全过程必须由 Skills 编排驱动，不允许跳过阶段：
  - `dev-workflow` -> `spec-sync` -> `progress-tracker` -> `implement` -> `testing-stage` -> `checkpoint`
- 在开始任何 Agent 开发任务前，必须完整阅读并理解 `DEV_SPEC.md` 全文，不允许只读局部章节后直接编码。
- 所有阶段要求的标准输出与用户确认步骤必须完整执行，尤其：
  - Stage 2 后必须等待用户确认任务。
  - Stage 5 必须执行“两次确认”：先确认总结，再确认是否 git commit。

---

## 3. 技术选型

### 3.1 总体技术栈

- 前端：Vue3 + TypeScript + Vite + Ant Design Vue（沿用）
- 后端：FastAPI + Pydantic
- Agent 框架：LangChain + LangGraph（强制）
- 任务编排：LangGraph StateGraph
- 记忆组件：`ConversationBufferSummaryMemory`（LangChain memory，接入 LangGraph 工作流）
- 外部服务：
  - Map：Amap API / Google Maps API
  - Photo：Unsplash API / Google Places Photo API
  - Flight（已选型）：Amadeus Self-Service `Flight Offers Search` API
  - Visa（已选型）：Sherpa `Requirements API`
  - Calendar：Google Calendar API
  - RAG：`Project1` Wikivoyage Ingestion + RAG Bridge -> `MODULAR-RAG-MCP-SERVER`

### 3.2 可插拔 Provider 设计

采用“抽象接口 + 注册中心 + 配置驱动 + fallback”。

```text
IMapProvider / IPhotoProvider / IFlightProvider / IVisaSourceProvider / ICalendarExporter
        ↓
ProviderRegistry (read settings.yaml)
        ↓
SelectedProvider(primary) -> FallbackProvider(secondary)
```

关键要求：

- 禁止在 Agent 里写死 API。
- 所有 Provider 通过统一 DTO 输入输出。
- 失败时输出统一错误码，并可由 `PlannerAgent(Orchestration Mode)` 重试/降级。

### 3.3 Agent 设计（新增与改造）

#### 3.3.1 PlannerAgent（Augmented，兼任 Orchestrator）

- 目标：理解需求、拆分任务、调用 worker、聚合结果并生成最终计划。
- 能力：
  - 意图识别：默认规划 / 景点增强 / 多轮增量修改 / 导出请求。
  - 图状态管理：`request -> classify -> route -> gather -> synthesize -> respond`。
  - 调度覆盖范围：必须可分配所有 worker（`Attraction/Weather/Hotel/Flight/Visa/Export`）。
  - 默认策略：优先并行调用 `Attraction/Weather/Hotel/Flight/Visa`，再做统一汇总。
  - 知识库策略：涉及目的地景点时，必须调用 `AttractionAgent` 的 RAG 检索能力；RAG 检索失败时降级到地图检索。
  - 多轮策略：基于 `plan_state + user_delta` 计算受影响模块，仅对受影响 worker 重算并保留未受影响结果（例如“更换航班”仅重跑 `FlightAgent`；“补充天气”仅重跑 `WeatherAgent`）。
  - 记忆策略：先读取会话短期记忆（recent buffer + summary），再决定路由；响应后写回记忆并在超限时触发摘要压缩。
- 输出：统一 `FinalPlan` schema（行程、预算、地图点位、酒店、天气、航班、签证、提醒、导出链接）。
  - 链接要求：`FinalPlan` 中必须包含 `source_links` 聚合字段，并在 `flight_plan/hotel_plan/attractions/visa_summary` 中保留 item 级链接字段。

#### 3.3.2 AttractionAgent（从 hello agent 搬运）

- 输入：目的地、时间范围、偏好标签。
- 工具：`RAGTool.search_destination_docs()`、`IMapProvider.search_poi()`、`IPhotoProvider.get_place_photo()`。
- 输出：候选景点列表（坐标、开放时间、建议停留时长、图片、`detail_url`/`source_url`）。

#### 3.3.3 WeatherAgent（从 hello agent 搬运）

- 输入：目的地、出行日期。
- 工具：地图天气接口（如 `IMapProvider.get_weather()`）。
- 输出：逐日天气与出行建议（衣物/降雨风险/备选安排）。

#### 3.3.4 HotelAgent（从 hello agent 搬运）

- 输入：预算、住宿偏好、地理位置偏好。
- 工具：地图 POI/酒店检索接口（通过 provider 统一封装）。
- 输出：酒店候选（价格区间、区域、通勤便利度、推荐理由、`booking_url`/`source_url`）。

#### 3.3.5 FlightAgent

- 输入：出发地、目的地、往返日期、预算偏好。
- 工具：`IFlightProvider.search_flights()`。
- 输出：候选航班列表 + 推荐理由 + 价格时间权衡说明 + `booking_url`（必填，若无则回退 `source_url` 并说明）。

#### 3.3.6 VisaAgent

- 触发条件：跨国出行。
- 输入：用户国籍、目的地国家、旅行时长。
- 工具：`IVisaSourceProvider.get_requirements()`（Sherpa Requirements API）。
- 输出：签证是否需要、申请材料、办理时效、来源链接、风险提示。
- 约束：仅允许调用配置中的白名单 API 域名（Sherpa），禁止无来源结论。

#### 3.3.7 ExportAgent（扩展）

- 保留原 PDF/图片导出。
- 新增 Google Calendar 导出：
  - 每日活动映射为 calendar events。
  - 时区、提醒、地点坐标写入事件。

### 3.4 Prompt 设计规范（每个 Agent 必须遵守）

每个 Agent Prompt 必须具备以下结构字段：

1. Role & Mission  
2. Context & Input Schema  
3. Hard Constraints（不可违反）  
4. Tool Usage Policy（何时调用、何时禁止）  
5. Reasoning Policy（内部逐步推理，外部仅返回结论）  
6. Output Schema（JSON）  
7. Failure Policy（信息不足时返回 `need_user_input`）  
8. Examples（至少 2 个，含失败样例）  

Prompt 设计与评审必须通过 skills 流程产出，不得跳过。

针对 `AttractionAgent`、`WeatherAgent`、`HotelAgent`，提示词允许直接照搬并最小改造以下来源文件中的既有定义（仅做框架适配，不改业务语义）：

- `/Users/yukun/hello-agents/code/chapter13/helloagents-trip-planner/backend/app/agents/trip_planner_agent.py`
  - `ATTRACTION_AGENT_PROMPT`
  - `WEATHER_AGENT_PROMPT`
  - `HOTEL_AGENT_PROMPT`

`PlannerAgent` 提示词必须以 `PLANNER_AGENT_PROMPT` 为基线扩展为“编排+生成”双模式，新增以下强制段落：

- Routing Policy：默认规划/景点增强/多轮增量三类路由规则。
- Tool Decision Matrix：何时调用 `Attraction(含RAG)/Flight/Visa/Export`，何时跳过。
- Delta Update Policy：仅重跑受影响 worker，禁止全量重复调用。
- Merge Policy：保留旧计划未受影响部分，替换受影响字段并更新版本号。
- Conflict Policy：当航班、酒店、天气冲突时的优先级与回退策略。
- Memory Policy：如何利用 `ConversationBufferSummaryMemory` 中的近期原文与历史摘要，何时依赖摘要、何时请求用户澄清。
- Citation & Link Policy：所有外部事实与推荐项必须带链接；优先 item 级 deep link。
- Output Contract：`FinalPlan` 必须显式包含 `flight_plan`、`visa_summary` 与 `source_links` 字段。

### 3.5 配置管理

- `backend/config/settings.yaml` 统一管理 provider 选择：
  - `providers.map=amap|google_maps`
  - `providers.photo=unsplash|google_places`
  - `providers.flight=amadeus`
  - `providers.visa=sherpa`
  - `providers.calendar=google_calendar`
- `backend/config/settings.yaml` 增加 RAG 知识库参数：
  - `rag.enabled=true`
  - `rag.source=wikivoyage_cn_jp`
  - `rag.integration_mode=external_mcp_rag`
  - `rag.mcp_rag_project_root=/Users/yukun/MODULAR-RAG-MCP-SERVER`
  - `rag.crawl_seed=https://www.wikivoyage.org/`
  - `rag.allowed_countries=[China,Japan]`
  - `rag.index_name=wikivoyage_cn_jp_attractions`
  - `rag.wikivoyage.bootstrap_source=dump`
  - `rag.wikivoyage.dump_url=https://dumps.wikimedia.org/enwikivoyage/latest/enwikivoyage-latest-pages-articles.xml.bz2`
  - `rag.wikivoyage.update_mode=full_rebuild_only`
  - `rag.wikivoyage.category_roots=[\"China\", \"Cities in China\", \"Regions of China\", \"Japan\", \"Cities in Japan\", \"Regions of Japan\"]`
- `backend/config/settings.yaml` 增加真实 API 参数：
  - `flight.amadeus.base_url=https://test.api.amadeus.com`（生产切到 `https://api.amadeus.com`）
  - `flight.amadeus.client_id=${AMADEUS_CLIENT_ID}`
  - `flight.amadeus.client_secret=${AMADEUS_CLIENT_SECRET}`
  - `visa.sherpa.base_url=<from_sherpa_partner_docs>`（以开通后的官方文档为准）
  - `visa.sherpa.api_key=${SHERPA_API_KEY}`
- `backend/config/settings.yaml` 增加记忆参数：
  - `memory.enabled=true`
  - `memory.max_tokens=3000`（近期原文上限，默认值）
  - `memory.summary_trigger_tokens=2600`（触发摘要压缩阈值，默认值，必须 <= max_tokens）
  - `memory.summary_max_tokens=700`（摘要最大长度，默认值）
  - `memory.k_recent_turns=8`（保留最近轮数，默认值）
  - `memory.summary_model=<same_as_planner_llm_or_cheaper_llm>`（摘要模型，默认同 Planner 模型，可配置为更低成本模型）
- 所有 API key 从 `.env` 注入，代码中禁止硬编码。

### 3.6 会话记忆实现设计（ConversationBufferSummaryMemory）

- 实现定位：
  - 使用 `ConversationBufferSummaryMemory` 作为短期记忆核心组件（该组件来自 LangChain，在 LangGraph 流程中调用）。
- 记忆结构：
  - `recent_buffer`：保留最近对话原文（受 `max_tokens` 控制）。
  - `running_summary`：累计历史摘要（承载超限内容）。
- 运行规则：
  1. 每轮处理前加载 `recent_buffer + running_summary`，注入 `PlannerAgent` 上下文。
  2. 每轮处理后写入新消息；若 token 超过阈值，自动摘要并裁剪原文。
  3. 摘要必须保留结构化要点：用户偏好、已选航班、签证状态、酒店约束、未完成事项。
- 与增量重算的关系：
  - `user_delta` 决策优先使用 recent buffer；
  - 若 recent buffer 信息不足，再回读 running summary；
  - 若 summary 与当前状态冲突，以最新显式用户输入为准。
- 默认参数调优建议（第一版）：
  - 当出现“摘要丢关键约束”时：提高 `summary_max_tokens`（如 700 -> 900）。
  - 当请求上下文仍过长时：降低 `k_recent_turns`（如 8 -> 6）并适度降低 `summary_trigger_tokens`。
  - 当成本压力较高时：将 `memory.summary_model` 切换为低成本模型，但必须通过 `test_planner_memory_flow.py` 回归。

---

## 4. 测试方案

### 4.1 测试理念

- 以 Agent 行为正确性和工具编排正确性为核心。
- 前后端做“够用测试”，重点投入在：
  - Agent 路由正确性
  - 会话记忆正确性（保留原文、超限摘要、跨轮可用）
  - Provider 插拔与 fallback
  - Wikivoyage RAG 检索效果
  - Prompt 输出稳定性

### 4.2 分层测试策略

#### 4.2.1 Unit Tests

- Provider 接口契约测试（统一输入输出）。
- Planner 路由规则测试（跨国触发、景点 RAG 触发、导出触发、增量重算触发）。
- Memory 单测：`max_tokens` 裁剪、summary 触发、摘要字段完整性、recent+summary 合并读取。
- 链接字段单测：推荐项必须包含 `*_url`，且 URL 格式合法。
- Prompt parser/validator 测试（JSON schema 合法性）。

#### 4.2.2 Integration Tests

- `Planner(Orchestration + Synthesis) + Worker + Provider` 链路测试。
- `Planner + ConversationBufferSummaryMemory` 联调测试（长对话下路由与计划一致性）。
- 链接透传联调测试：worker 产出的 item 链接必须透传到 `FinalPlan.source_links`。
- `Wikivoyage Dump Ingestion + RAG Bridge + AttractionAgent` 联调测试（mock + real 两套）。
- `ExportAgent + Google Calendar API` 集成测试（沙箱日历）。

#### 4.2.3 E2E Tests（轻量）

- 典型用户流程：
  - 国内行程生成并导出 PDF。
  - 跨国行程触发签证并导出 Google Calendar。
  - 目的地景点推荐可从 Wikivoyage 知识库检索并合并到行程。
  - 多轮长对话超过 `max_tokens` 后仍可正确执行“仅重跑受影响 agent”。

### 4.3 质量评估与准入门槛

- 测试通过率：主干分支 100%。
- 核心链路覆盖率（backend agent/services）：>= 80%。
- Prompt 结构化输出成功率（回归样本集）：>= 95%。
- 记忆压缩正确率（回归样本集）：>= 95%（关键约束在摘要后不丢失）。
- 链接完整率（回归样本集）：>= 95%（满足“可返回链接”的推荐项必须带链接）。
- 不允许：
  - 单元测试直连真实第三方 API。
  - 未通过测试直接进入 checkpoint。

### 4.4 失败回路

- 严格遵守 `testing-stage` 的 3 次迭代上限。
- 连续失败 3 次必须升级给用户做人工决策。

---

## 5. 系统架构与模块设计

### 5.1 架构图（逻辑）

```mermaid
flowchart LR
  UI[Vue Frontend] --> API[FastAPI Backend]
  API --> MEM[ConversationBufferSummaryMemory]
  API --> PLANNER[LangGraph PlannerAgent (Orchestration + Synthesis)]

  MEM --> PLANNER
  PLANNER --> MEM
  PLANNER --> ATTRACTION[AttractionAgent]
  PLANNER --> WEATHER[WeatherAgent]
  PLANNER --> HOTEL[HotelAgent]
  PLANNER --> FLIGHT[FlightAgent]
  PLANNER --> VISA[VisaAgent]
  PLANNER --> EXPORT[ExportAgent]

  ATTRACTION --> MAP[Map Provider Adapter]
  ATTRACTION --> PHOTO[Photo Provider Adapter]
  ATTRACTION --> RAGKB[Wikivoyage RAG Index]
  WEATHER --> MAP
  HOTEL --> MAP
  FLIGHT --> FP[Flight Provider Adapter]
  VISA --> VS[Visa Whitelist Source Adapter]
  WIKIINGEST[Project1 Wikivoyage Ingestion (Dump Full Rebuild)] --> RAGBRIDGE[Project1 RAG Bridge]
  RAGBRIDGE --> MCRAG[MODULAR-RAG-MCP-SERVER]
  MCRAG --> RAGKB
  EXPORT --> GCAL[Google Calendar API]
```

### 5.2 推荐目录结构

```text
Project1/
├── DEV_SPEC.md
├── frontend/
│   └── src/
│       ├── views/
│       ├── components/
│       ├── services/
│       └── styles/theme.css
├── backend/
│   ├── app/
│   │   ├── api/routes/
│   │   ├── agents/
│   │   │   ├── planner/
│   │   │   │   └── planner_agent.py
│   │   │   ├── memory/
│   │   │   │   ├── memory_manager.py
│   │   │   │   └── summary_memory.py
│   │   │   └── workers/
│   │   │       ├── attraction_agent.py
│   │   │       ├── weather_agent.py
│   │   │       ├── hotel_agent.py
│   │   │       ├── flight_agent.py
│   │   │       ├── visa_agent.py
│   │   │       └── export_agent.py
│   │   ├── rag/
│   │   │   ├── wikivoyage_ingestion/
│   │   │   │   ├── dump_loader.py
│   │   │   │   ├── cleaner.py
│   │   │   │   └── chunk_exporter.py
│   │   │   ├── rag_bridge/
│   │   │   │   ├── ingest_runner.py
│   │   │   │   └── query_client.py
│   │   │   └── retriever.py
│   │   ├── prompts/
│   │   ├── providers/
│   │   │   ├── map/
│   │   │   ├── photo/
│   │   │   ├── flight/
│   │   │   ├── visa/
│   │   │   └── calendar/
│   │   ├── services/
│   │   ├── schemas/
│   │   └── config/
│   └── tests/
│       ├── unit/
│       ├── integration/
│       └── e2e/
└── .github/
    └── skills/
        ├── dev-workflow/
        ├── spec-sync/
        ├── progress-tracker/
        ├── implement/
        ├── testing-stage/
        └── checkpoint/
```

### 5.3 模块职责

- `planner/`：意图识别、任务规划、状态机调度、增量重算、最终计划合成。
- `memory/`：短期记忆读写、token 计量、超限摘要压缩、recent+summary 上下文拼装。
- `workers/`：领域能力执行（`attraction/weather/hotel/flight/visa/export`，且仅包含这 6 类）。
- `rag/`：Wikivoyage Dump 全量数据接入、清洗切分、RAG 桥接调用（外部 mcp-rag）与检索封装。
- `providers/`：外部 API 适配与统一抽象接口。
- `prompts/`：每个 agent 的 prompt 模板和示例库。
- `services/`：预算计算、时间冲突检测、行程组装。
- `schemas/`：Pydantic 输入输出约束。

### 5.4 关键数据流

#### 5.4.1 标准规划流

1. 前端提交旅行需求。  
2. Memory 层读取 `recent_buffer + running_summary` 并注入 `PlannerAgent` 上下文。  
3. `PlannerAgent(Orchestration Mode)` 识别意图并路由。  
4. 默认并行调用 `AttractionAgent` + `WeatherAgent` + `HotelAgent` + `FlightAgent` + `VisaAgent`。  
5. `PlannerAgent(Synthesis Mode)` 聚合结果并生成最终按天行程与预算。  
6. Memory 层写回本轮对话；若超限则自动摘要压缩。  
7. `PlannerAgent` 聚合并返回 item 级链接与 `source_links`。  
8. 需要导出时调 `ExportAgent`，否则直接返回前端。  

#### 5.4.2 Wikivoyage 景点增强流

1. 首次初始化时，`dump_loader` 从 Wikivoyage Dump 导入中国/日本旅游相关页面并完成清洗切分。  
2. 手动或定时触发“全量重建”时，重新执行 Dump -> 清洗切分 -> 入库，不做增量差分。  
3. `rag_bridge.ingest_runner` 调用 `MODULAR-RAG-MCP-SERVER` 既有 ingest 能力写入索引（不改外部仓库源码）。  
4. 用户发起行程规划时，`PlannerAgent` 将目的地路由给 `AttractionAgent`。  
5. `AttractionAgent` 通过 `rag_bridge.query_client` 检索目的地知识，再按需补充地图/图片工具结果。  
6. `PlannerAgent` 聚合增强后的景点候选并输出最终 itinerary（含来源链接）。  

#### 5.4.3 多轮增量更新流

1. 用户在已有计划上提出局部修改（如“更换航班”）。  
2. Memory 层加载 recent+summary，恢复会话上下文与上版计划约束。  
3. `PlannerAgent` 识别 `user_delta` 并计算受影响模块。  
4. 仅调用受影响 worker（如仅 `FlightAgent`）。  
5. 局部回填并生成新版本计划，保留未受影响部分。  
6. 写回新记忆并在需要时执行摘要压缩。  

#### 5.4.4 导出流

1. 用户选择导出类型。  
2. `ExportAgent` 根据目标调用 PDF/Image/Google Calendar exporter。  
3. 返回导出结果（文件/链接/事件数）。  

#### 5.4.5 记忆压缩流

1. 统计当前会话 token 使用量。  
2. 若 `<= memory.max_tokens`，保留原文不压缩。  
3. 若 `> memory.summary_trigger_tokens`，将超出部分摘要写入 `running_summary`。  
4. 保留最近 `k_recent_turns` 原文作为 `recent_buffer`。  
5. 下一轮统一使用 `running_summary + recent_buffer` 参与规划。  

### 5.5 Skills 工作流集成（强制规范）

- 必须将 skills 放在项目路径：`.github/skills/`。
- 若当前仓库不存在，先从参考仓库复制：
  - `/Users/yukun/MODULAR-RAG-MCP-SERVER/.github/skills/*`
- 每次做“下一阶段”时必须执行：
  1. Stage 0：激活虚拟环境  
  2. Stage 1：`spec-sync`  
  3. Stage 1.5：完整阅读 `DEV_SPEC.md` 并输出“理解摘要（目标/约束/当前任务验收标准）”  
  4. Stage 2：`progress-tracker`（必须等待用户确认）  
  5. Stage 3：`implement`  
  6. Stage 4：`testing-stage`（失败最多迭代 3 次）  
  7. Stage 5：`checkpoint`（必须两次用户确认）
- 任何阶段要求的标准化输出文本都不得省略。

---

## 6. 项目排期

### 6.1 执行规则（先于所有任务）

- 本排期中的每个子任务都必须通过 `dev-workflow` 驱动执行。
- 单次流水线只完成一个子任务，不允许跨任务打包提交。
- 任一 Agent 开发前必须先完整通读 `DEV_SPEC.md`，并产出理解摘要后方可进入实现阶段。
- 凡任务可直接复用或借鉴 hello agent 代码，`implement` 阶段必须显式输出“复用清单（源文件路径 + 复用方式 + 改造点）”。
- 任务状态标记：
  - `[ ]` 未开始
  - `[~]` 进行中
  - `[x]` 已完成

### 6.2 总体进度

| 阶段 | 总任务数 | 已完成 | 进度 |
|---|---:|---:|---:|
| Phase A 基础迁移与脚手架 | 4 | 4 | 100% |
| Phase B 可插拔工具层 | 5 | 5 | 100% |
| Phase C 多 Agent 与 Prompt | 10 | 8 | 80% |
| Phase D RAG 知识库与导出 | 4 | 0 | 0% |
| Phase E 前端改造与联调 | 3 | 0 | 0% |
| Phase F 测试与发布准备 | 4 | 0 | 0% |
| 合计 | 30 | 17 | 57% |

### 6.3 分阶段任务与验收标准

#### Phase A：基础迁移与脚手架

- [x] A1：初始化 LangChain/LangGraph 后端骨架  
  - 交付：基础目录、依赖、配置加载。
  - 验收：后端可启动，Graph 可跑通最小样例。
  - 测试方法：`pytest -q tests/unit/test_graph_bootstrap.py`

- [x] A2：迁移 hello agent 的前后端基础代码（分层迁移）  
  - 交付：前后端页面/API/服务层优先直接迁移；`HelloAgents` 相关 Agent 运行时代码改写为 `LangChain/LangGraph` 后迁移；并落地旧核心 agent：`Attraction/Weather/Hotel/Planner`。
  - 验收：原有核心功能在新仓库可运行，且智能体层不再依赖 HelloAgents。
  - 复用来源：`helloagents-trip-planner` 前端页面、后端 API/服务、旧 agent 提示词与工具封装；提示词直接复用 `trip_planner_agent.py` 中四个常量。
  - 测试方法：`pytest -q tests/integration/test_baseline_migration.py`

- [x] A3：建立统一 schema 与 DTO 契约  
  - 交付：请求/响应、provider I/O、agent 中间态 schema。
  - 验收：所有关键 API 通过 pydantic 校验。
  - 测试方法：`pytest -q tests/unit/test_schema_contracts.py`

- [x] A4：接入 `.github/skills` 并验证 `dev-workflow` 可调用  
  - 交付：skills 文件到位，文档链路可执行。
  - 验收：可执行一次 Stage1->Stage2 到等待确认。
  - 测试方法：手动演练 + 日志截图。

#### Phase B：可插拔工具层

- [x] B1：Map Provider 抽象与双实现（Amap/Google Maps）  
  - 验收：配置切换无需改代码；失败可 fallback。
  - 复用来源：hello agent 中的高德地图 API 封装与地图路由调用逻辑。
  - 测试方法：`pytest -q tests/unit/test_map_providers.py`

- [x] B2：Photo Provider 抽象与双实现（Unsplash/Google Places）  
  - 验收：景点图片接口可切换，返回统一格式。
  - 复用来源：hello agent 中已有图片获取与景点展示相关逻辑（若有）。
  - 测试方法：`pytest -q tests/unit/test_photo_providers.py`

- [x] B3：Flight Provider 抽象与至少一个实时实现  
  - 验收：基于 Amadeus `Flight Offers Search` 可按往返日期和目的地返回候选航班。
  - 测试方法：`pytest -q tests/integration/test_flight_provider_live_like.py`

- [x] B4：Visa Source Provider（白名单域名）  
  - 验收：基于 Sherpa `Requirements API` 返回签证要求；仅白名单可访问，输出带来源 URL。
  - 测试方法：`pytest -q tests/unit/test_visa_whitelist.py`

- [x] B5：ProviderRegistry 与配置驱动完成  
  - 验收：所有 provider 通过 settings 统一装配。
  - 测试方法：`pytest -q tests/unit/test_provider_registry.py`

#### Phase C：多 Agent 与 Prompt

- [x] C1：PlannerAgent 编排核心实现（替代 Orchestrator）  
  - 验收：`PlannerAgent` 可根据请求路由全部 6 个 worker（`Attraction/Weather/Hotel/Flight/Visa/Export`），支持默认规划/景点增强/多轮增量三种模式。
  - 复用来源：hello agent 中可复用的任务拆解思路与业务规则。
  - 测试方法：`pytest -q tests/integration/test_planner_routing.py tests/integration/test_planner_delta_routing.py`

- [x] C2：AttractionAgent 实现（从 hello agent 搬运）  
  - 验收：能够稳定调用地图/图片工具返回候选景点，字段结构与 `FinalPlan` 契约一致，并返回 `detail_url/source_url`。
  - 复用来源：`trip_planner_agent.py` 中 `ATTRACTION_AGENT_PROMPT` 与景点搜索流程。
  - 测试方法：`pytest -q tests/unit/test_attraction_agent.py`

- [x] C3：WeatherAgent 实现（从 hello agent 搬运）  
  - 验收：能够按城市/日期返回天气信息并生成可执行天气建议，输出可被 Planner 消费。
  - 复用来源：`trip_planner_agent.py` 中 `WEATHER_AGENT_PROMPT` 与天气查询流程。
  - 测试方法：`pytest -q tests/unit/test_weather_agent.py`

- [x] C4：HotelAgent 实现（从 hello agent 搬运）  
  - 验收：能够按预算与偏好返回酒店候选，具备位置与价格关键信息，并返回 `booking_url/source_url`。
  - 复用来源：`trip_planner_agent.py` 中 `HOTEL_AGENT_PROMPT` 与酒店检索流程。
  - 测试方法：`pytest -q tests/unit/test_hotel_agent.py`

- [x] C5：PlannerAgent 计划合成与冲突处理实现  
  - 验收：可整合 Attraction(含RAG)/Weather/Hotel/Flight/Visa 的中间结果，输出完整按天 itinerary 与预算，并处理航班/酒店/天气冲突；最终计划必须显式包含 `flight_plan`、`visa_summary`、`source_links`，且推荐项链接可追溯。
  - 复用来源：`trip_planner_agent.py` 中 `PLANNER_AGENT_PROMPT` 基线结构与整合逻辑。
  - 测试方法：`pytest -q tests/unit/test_planner_synthesis.py`

- [x] C6：FlightAgent 实现  
  - 验收：输出结构化航班方案，含排序理由与 `booking_url`（无 deep link 时回退 `source_url` 并标注）。
  - 测试方法：`pytest -q tests/unit/test_flight_agent.py`

- [x] C7：VisaAgent 实现（仅跨国触发）  
  - 验收：跨国触发外部签证查询，国内不触发外部查询且返回 `not_required`；结果可解释且附来源链接。
  - 测试方法：`pytest -q tests/unit/test_visa_agent_trigger.py`

- [x] C8：AttractionAgent 的 RAG 工具接入实现  
  - 验收：按用户目的地调用 RAG 工具检索 Wikivoyage 中国/日本景点文档，并在输出中保留来源链接。
  - 测试方法：`pytest -q tests/integration/test_attraction_rag_flow.py`

- [ ] C9：全部新 Agent Prompt 定稿与回归集（含 Planner Orchestration Prompt）  
  - 验收：每个 agent prompt 含 8 个必备字段；`PlannerAgent` 额外满足 Routing/Delta/Merge/Conflict/Citation&Link 规则；结构化输出成功率 >= 95%。
  - 复用来源：`Attraction/Weather/Hotel` 允许直接照搬 `trip_planner_agent.py` 既有提示词；`Planner` 在 `PLANNER_AGENT_PROMPT` 基线上做编排增强。
  - 测试方法：`pytest -q tests/unit/test_prompt_regression.py`

- [ ] C10：短期记忆接入（ConversationBufferSummaryMemory）  
  - 验收：实现 `max_tokens` 内保留原文、超限自动摘要；`PlannerAgent` 能稳定读取 recent+summary 并保持多轮决策一致。
  - 复用来源：LangChain `ConversationBufferSummaryMemory` 组件，结合 LangGraph 会话状态管理。
  - 测试方法：`pytest -q tests/unit/test_memory_manager.py tests/integration/test_planner_memory_flow.py`

#### Phase D：RAG 知识库与导出

- [ ] D1：Wikivoyage Dump 基线导入与清洗流水线（Project1 内）  
  - 验收：使用固定 `latest` dump_url（`https://dumps.wikimedia.org/enwikivoyage/latest/enwikivoyage-latest-pages-articles.xml.bz2`）批量导入中国/日本旅游页面并完成清洗、切分、入索引编排；文档包含 `page_title/page_id/revision_id/source_url/retrieved_at`。
  - 测试方法：`pytest -q tests/integration/test_wikivoyage_ingestion.py`

- [ ] D2：RAG 检索服务封装与全量重建任务入口  
  - 验收：支持按目的地检索景点文档，支持手动/定时触发全量重建；通过桥接层调用 `MODULAR-RAG-MCP-SERVER` 现有能力且不修改其源码。
  - 测试方法：`pytest -q tests/integration/test_rag_retrieval_service.py`

- [ ] D3：Google Calendar Export 实现  
  - 验收：可创建日历事件并包含时间地点提醒。
  - 测试方法：`pytest -q tests/integration/test_google_calendar_export.py`

- [ ] D4：与 PDF/Image 导出统一导出网关  
  - 验收：同一导出接口支持 3 种目标。
  - 复用来源：hello agent 中现有 PDF/图片导出代码。
  - 测试方法：`pytest -q tests/unit/test_export_gateway.py`

#### Phase E：前端改造与联调

- [ ] E1：前端新增字段（国籍、导出 Google Calendar）  
  - 验收：表单项和交互完整，类型校验通过。
  - 复用来源：hello agent 现有表单、结果页和行程编辑组件。
  - 测试方法：`npm run test -- nationality export`

- [ ] E2：配色改造（去花哨）  
  - 验收：统一低饱和主色，页面信息层级清晰。
  - 复用来源：hello agent 当前样式体系，进行最小改造。
  - 测试方法：视觉走查 checklist。

- [ ] E3：端到端联调  
  - 验收：3 条核心业务流全通（国内、跨国、Wikivoyage RAG 景点增强）。
  - 复用来源：hello agent 既有联调流程与关键页面跳转逻辑。
  - 测试方法：`pytest -q tests/e2e/test_user_journeys.py`

#### Phase F：测试与发布准备

- [ ] F1：全量测试与覆盖率报告  
  - 验收：核心链路覆盖率 >= 80%。
  - 测试方法：`pytest --cov=backend/app tests/`

- [ ] F2：性能与成本基线  
  - 验收：典型请求延迟、token、外部 API 调用次数可观测。
  - 测试方法：压测脚本 + tracing 报告。

- [ ] F3：文档完善（README + API + Prompt 文档）  
  - 验收：新成员可按文档独立跑通。
  - 测试方法：新环境复现实验。

- [ ] F4：最终 checkpoint 与发布包  
  - 验收：`DEV_SPEC.md` 进度同步、变更日志、发布标签完成。
  - 测试方法：发布 checklist 审核通过。

### 6.4 每次任务执行时的标准输出要求（不可省略）

每次执行子任务时，Agent 必须严格输出以下节点内容：

1. 输出“`DEV_SPEC.md` 全文理解摘要”（至少包含：目标、约束、当前任务验收标准）。  
2. `progress-tracker` 输出“当前任务识别结果”并请求用户确认。  
3. `implement` 输出“设计原则清单 + 计划文件列表 + 实施结果”。  
4. `testing-stage` 输出“测试范围决策 + 测试结果 + 失败修复建议”。  
5. `checkpoint`：
   - 先输出“完成总结”，等待用户确认是否准确（第一次确认）。
   - 自动更新 `DEV_SPEC.md` 后，再询问是否执行 git commit（第二次确认）。

若任一确认缺失，则该次任务视为流程违规，不计入完成状态。
