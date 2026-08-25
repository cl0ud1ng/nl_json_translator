# 场内多车货物运输系统升级计划

## 2026-08-25 双层 Agent 升级实施结果

项目的运行时主线已从“三车双取送专用场景”升级为通用双层 Agent 架构：

```text
DeepSeek 批量意图
  -> TransportBatch / TransportOrder
  -> DispatcherAgent（唯一总控）
  -> 持久化 AgentCommand / RouteReservation
  -> VehicleAgent[vehicle_id] * N
  -> 逐时间片执行与事件落库
```

已完成：

- 唯一自然语言协议升级为 `create_transport_orders` + `orders[]`。
- DeepSeek 响应 ID、实际模型、完成原因和 token 用量可审计。
- DispatcherAgent 支持整批订单的全局最小成本车辆匹配，不再逐单贪心占用稀缺能力车辆。
- 车辆 Agent 通过持久化命令、执行游标和状态版本独立执行本车 Mission。
- 节点与边预约落库，消费后释放；Agent 重建后可从游标继续。
- Streamlit 默认自然语言仍演示三车双取送，但业务链路不包含场景专用分支。
- 真实 `deepseek-v4-pro` API 已在临时数据库中跑通 3 单、3 车、3 Mission、全部交付且无运行时冲突的完整链路。

后续演进重点调整为：独立 Agent Worker 进程、滚动时域重规划、车辆取货后故障救援任务和多 Mission 队列优化。

## 1. 文档目的

本文档用于指导 `nl_json_translator` 从当前的“单车自然语言指令翻译与地图演示”，逐步升级为“数据库驱动、支持多车协同的场内货物运输调度系统”。

本轮升级重点解决三个问题：

1. 地点、地图与车辆信息从静态代码和提示词中分离，改为数据库管理。
2. 从单车、单执行器扩展为多车、多逻辑智能体协同运行。
3. 将业务场景聚焦为场地内货物取送，建立运输订单、任务分配和完整执行状态。

本文档描述初步技术路线和阶段划分，不要求第一阶段立即覆盖真实车辆控制、复杂交通规则或全局最优调度。

---

## 2. 当前项目基线

当前系统的处理链路为：

```text
自然语言
  -> DeepSeek 翻译
  -> JSON 提取
  -> Schema 校验
  -> 单车地图执行
  -> SVG / Streamlit 展示
```

当前实现的主要特点：

- `prompts.py` 定义自然语言到 JSON 的动作语义。
- `translator.py` 负责调用模型、解析输出、校验和失败重试。
- `schema.py` 支持 `go_to_goal`、`move`、`rotate`、`sequence`、`stop`。
- `map_executor.py` 使用静态 `POINTS`、`OBSTACLES` 和 A* 完成单车模拟。
- `app.py` 提供单次翻译和单车轨迹播放界面。
- 当前测试覆盖基础 Schema、翻译重试和单车地图路径。

现有结构适合验证 NL-to-JSON 思路，但还缺少业务订单、持久状态、并发调度、车辆隔离和多车冲突处理。

---

## 3. 升级目标与边界

### 3.1 核心目标

- 地点和地图数据可以在 Demo 启动前通过数据库新增、修改、停用，无需修改 Prompt 或代码；系统运行期间保持固定。
- 自然语言中的地点名称可以通过名称、别名和模糊匹配解析为稳定地点 ID。
- 支持多辆车拥有独立位置、朝向、容量、电量、能力和运行状态。
- 支持创建“到指定地点取货，再送往目标地点”的运输订单。
- 由中央调度器完成车辆筛选、订单分配和任务生成。
- 多个 VehicleAgent 可以并发推进自己的任务状态。
- 在模拟环境中避免多车节点冲突和迎面边冲突。
- 所有重要状态变化可持久化、追踪和重放。

本项目当前采用以下简化假设：

- 系统运行期间地图固定，不支持在线修改地图拓扑。
- 数据库中仅保存可随时重建的虚拟 Demo 数据。
- 系统只有一个 DispatcherAgent 负责订单分配。
- 所有逻辑 Agent 暂时运行在同一个 Python 进程中。

### 3.2 第一阶段非目标

- 不直接控制电机、转向、油门或制动。
- 不立即接入 ROS、PLC、AGV 厂商协议或真实传感器。
- 不要求一开始就获得全局最优调度结果。
- 不立即拆分为多个独立微服务。
- 不让 LLM 直接决定车辆分配、行驶路径或安全避让。

---

## 4. 设计原则

### 4.1 LLM 只负责意图理解

LLM 输出包含用户提到的地点文本、货物和约束，但不生成数据库 ID，不判断地点是否真实存在，也不直接生成最终车辆路径。

### 4.2 业务决策必须确定性执行

地点解析、容量校验、任务分配、状态流转、路径规划和冲突检测由普通程序完成，保证结果可测试、可解释和可重复。

### 4.3 使用稳定 ID 连接业务对象

地点、车辆、订单、任务和路径均使用数据库 ID 关联。名称只用于展示和用户输入，避免重命名破坏历史任务。

### 4.4 先模块化单体，后按需拆分

初期在一个 Python 项目中建立清晰模块边界，并通过进程内事件机制运行多个逻辑 Agent。只有在车辆规模、吞吐量或部署要求明确后，才拆分调度器、车辆网关和消息系统。

### 4.5 数据库是共享状态的事实来源

车辆当前位置、订单状态、任务归属和资源预约不能只保存在 Streamlit Session 或 Agent 内存中。

### 4.6 Git 管理开发版本

源代码、数据库模型和 Demo 种子数据全部由 Git 管理。数据库文件本身不纳入版本控制；当数据结构变化时，删除旧数据库并根据当前代码重新建表、重新填充虚拟数据。

---

## 5. 目标架构

```text
┌──────────────────────────────────────────────────────────┐
│                    CLI / Streamlit / API                  │
└────────────────────────────┬─────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────┐
│ IntentAgent：自然语言 -> 运输意图草稿                    │
└────────────────────────────┬─────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────┐
│ LocationResolver：地点文本 -> 数据库地点 ID              │
└────────────────────────────┬─────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────┐
│ OrderService：校验并创建 TransportOrder                  │
└────────────────────────────┬─────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────┐
│ DispatcherAgent：车辆筛选、任务分配、Mission 创建        │
└────────────────────────────┬─────────────────────────────┘
                             │
                   ┌─────────┼─────────┐
                   ▼         ▼         ▼
             VehicleAgent  VehicleAgent  VehicleAgent
                  #1          #2          #N
                   │           │           │
                   └───────────┼───────────┘
                               ▼
┌──────────────────────────────────────────────────────────┐
│ SQLite：地点、地图、车辆、订单、任务、预约和事件          │
└──────────────────────────────────────────────────────────┘
```

建议将路径规划分为两层：

1. 调度层：确定哪辆车执行哪个订单，以及多个订单的执行顺序。
2. 路径层：根据地图和时空预约生成不会与其他车辆冲突的路径。

---

## 6. 领域模型

### 6.1 地点与地图

#### `locations`

| 字段 | 说明 |
|---|---|
| `id` | 稳定地点 ID |
| `name` | 标准名称 |
| `location_type` | pickup、dropoff、both、charging 等 |
| `map_node_id` | 对应地图节点 |
| `enabled` | 是否允许使用 |
| `metadata` | 扩展属性 |
| `created_at` / `updated_at` | 审计时间 |

#### `location_aliases`

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `location_id` | 对应地点 |
| `alias` | 原始别名 |
| `normalized_alias` | 规范化后的别名，建议唯一索引 |

#### `map_nodes`

保存地图节点、网格坐标或实际场地坐标。

#### `map_edges`

保存节点连接关系、距离、预计通行时间、方向、通行能力和封闭状态。

### 6.2 车辆

#### `vehicles`

| 字段 | 说明 |
|---|---|
| `id` | 车辆 ID |
| `name` | 展示名称 |
| `current_node_id` | 当前节点 |
| `heading` | 当前朝向 |
| `status` | 当前状态 |
| `capacity_weight` | 最大载重 |
| `capacity_volume` | 最大容积 |
| `battery_level` | 当前电量 |
| `capabilities` | 冷链、防爆、叉取等能力 |
| `telemetry_updated_at` | 最近遥测时间 |

建议车辆状态：

```text
IDLE
RESERVED
TO_PICKUP
LOADING
TO_DROPOFF
UNLOADING
CHARGING
BLOCKED
OFFLINE
FAILED
```

### 6.3 货物与运输订单

#### `cargo_items`

保存货物名称、数量、重量、体积、类别和特殊处理要求。

#### `transport_orders`

| 字段 | 说明 |
|---|---|
| `id` | 订单 ID |
| `batch_id` | 批量自然语言请求的关联 ID |
| `pickup_location_id` | 取货点 |
| `dropoff_location_id` | 送货点 |
| `priority` | 优先级 |
| `status` | 订单状态 |
| `requested_vehicle_id` | 用户指定车辆，可为空 |
| `earliest_start_at` | 最早开始时间 |
| `deadline_at` | 截止时间 |
| `idempotency_key` | 防止重复创建 |

建议订单状态：

```text
CREATED
NEEDS_REVIEW
RESOLVED
ASSIGNED
PICKING
IN_TRANSIT
DELIVERED
CANCELLED
FAILED
```

### 6.4 任务与执行步骤

#### `missions`

表示订单与车辆的一次具体绑定，记录分配时间、执行车辆和最终状态。

#### `mission_steps`

建议支持以下步骤：

```text
REPOSITION  车辆当前位置 -> 取货点
LOAD        在取货点装货
TRANSPORT   取货点 -> 送货点
UNLOAD      在送货点卸货
WAIT        等待资源或避让
COMPLETE    任务完成
```

#### `agent_events`

使用追加写入方式记录状态变化、位置更新、调度结果、异常和人工操作。业务表保存当前状态，事件表保存审计历史；第一阶段不必实现完整事件溯源架构。

### 6.5 时空资源预约

#### `route_reservations`

| 字段 | 说明 |
|---|---|
| `mission_id` | 所属任务 |
| `vehicle_id` | 所属车辆 |
| `resource_type` | node 或 edge |
| `resource_id` | 节点或边 ID |
| `start_time_slot` | 开始时间片 |
| `end_time_slot` | 结束时间片 |

需要通过唯一约束或事务逻辑避免：

- 两辆车在同一时间占用同一节点。
- 两辆车在同一时间从相反方向占用同一条边。

---

## 7. 自然语言与 JSON 协议升级

### 7.1 LLM 输出草稿

LLM 不直接输出地点 ID，而是保留地点文本：

```json
{
  "intent": "create_transport_order",
  "cargo": {
    "name": "零件箱",
    "quantity": 3,
    "weight_kg": 15
  },
  "pickup_location_text": "一号库",
  "dropoff_location_text": "装配区",
  "vehicle_text": null,
  "priority": "normal"
}
```

### 7.2 地点解析后的正式订单

```json
{
  "type": "transport_order",
  "cargo": {
    "name": "零件箱",
    "quantity": 3,
    "weight_kg": 15
  },
  "pickup_location_id": "loc_warehouse_01",
  "dropoff_location_id": "loc_assembly_02",
  "requested_vehicle_id": null,
  "priority": "normal"
}
```

### 7.3 地点解析策略

解析顺序：

1. 统一大小写、空白、符号和中文数字。
2. 精确匹配标准地点名称。
3. 精确匹配地点别名。
4. 进行有限的模糊匹配。
5. 唯一且超过阈值时自动确认。
6. 多个候选时设置订单为 `NEEDS_REVIEW`。
7. 无候选时返回明确的未知地点错误。

第一阶段不使用向量数据库。只有在后续出现大量描述性地点表达时，再增加语义检索作为候选召回手段；最终确认仍需依赖确定性规则。

### 7.4 与现有动作执行器衔接

新的运输订单协议作为唯一对外业务协议。现有动作对象不再作为对外协议，只作为 Mission 执行层的内部表示：

```text
TransportOrder
  -> Mission
  -> MissionStep
  -> 内部 go_to_goal / move / rotate / stop
```

现有测试样例可继续用于执行器回归，但不再为新旧 JSON 协议维护并行解析分支或协议版本字段。

---

## 8. 多智能体设计

### 8.1 IntentAgent

职责：

- 调用 DeepSeek。
- 将自然语言转换为运输意图草稿。
- 不访问车辆执行状态。
- 不决定车辆和路径。
- 在 Schema 不合法时使用现有重试机制修正。

### 8.2 DispatcherAgent

职责：

- 获取未分配订单。
- 查询可用车辆。
- 执行硬约束过滤和成本评分。
- 作为唯一任务分配者，在事务中检查订单和车辆状态。
- 创建 Mission 和 MissionStep。
- 规划初始路径并写入预约。
- 车辆失败时重新调度尚未完成的订单。

第一版使用可解释的贪心成本：

```text
cost =
  distance(vehicle, pickup)
  + distance(pickup, dropoff)
  + battery_penalty
  + congestion_penalty
  + deadline_penalty
```

硬约束至少包括：

- 车辆状态为 `IDLE`。
- 遥测信息未过期。
- 载重和容积满足要求。
- 电量满足预计任务消耗和安全余量。
- 车辆能力满足货物要求。
- 用户指定车辆时只能选择对应车辆。

后续任务量增大后，可使用 OR-Tools 处理 Pickup-and-Delivery、车辆容量、时间窗和多订单顺序优化。

### 8.3 VehicleAgent

每辆车对应一个 VehicleAgent 实例，通过 `vehicle_id` 隔离状态。职责：

- 领取已分配给本车的 Mission。
- 按顺序执行 MissionStep。
- 更新车辆位置、状态和任务进度。
- 写入执行事件。
- 报告阻塞、低电量、超时和执行失败。
- 等待调度器确认后进行重新规划。

第一阶段可以通过 `asyncio` 在同一进程运行多个 Agent。Agent 内存只保存临时上下文，关键状态必须持久化。

### 8.4 MonitorAgent

职责：

- 检查遥测是否过期。
- 检查任务是否超时。
- 标记离线、故障或阻塞车辆。
- 在车辆故障或多车预约冲突时触发路径重规划或订单重新分配。

---

## 9. 多车路径规划

### 9.1 当前 A* 的保留与改造

保留现有 A* 作为单车静态路径计算基础，但将以下静态全局变量替换为数据库中的固定地图数据：

- `POINTS`
- `OBSTACLES`
- 固定网格尺寸

路径规划函数需要接收：

- 由 `MapRepository` 读取的当前固定地图。
- 起点和终点节点。
- 当前时间片。
- 已存在的节点和边预约。

### 9.2 第一版多车避碰

采用“优先级规划 + Cooperative A*”思路：

1. 按订单优先级和车辆任务顺序逐辆规划。
2. 高优先级车辆先写入时空预约。
3. 后续车辆规划时将已预约资源视为动态障碍。
4. 如果暂时无路可走，插入 `WAIT` 步骤。
5. 如果等待仍无法解决，调整优先级或触发重新规划。

### 9.3 后续扩展

当车辆数量和冲突复杂度提高后，再评估：

- Conflict-Based Search。
- 基于路口通行权的规则系统。
- 路段容量和单向通行。
- 拥堵成本和动态路径权重。
- 与真实车辆局部避障系统协同。

调度器负责全局路径意图，真实车辆仍应拥有独立的紧急停车和局部避障能力。

---

## 10. 推荐技术栈

| 领域 | 推荐方案 | 说明 |
|---|---|---|
| 数据库 | SQLite | 零部署，适合单进程 Demo 和可重建虚拟数据 |
| ORM | SQLAlchemy | 隔离领域逻辑与数据库细节 |
| 数据初始化 | `init_db.py` + `seed_demo_data.py` | 根据当前模型建表并填充虚拟数据 |
| 数据校验 | Pydantic | 替换部分手写 JSON 字段校验 |
| API | FastAPI | 为 UI、CLI 和外部系统提供统一接口 |
| 演示 UI | Streamlit | 保留现有可视化能力 |
| Agent 运行 | asyncio | 第一阶段的进程内多 Agent |
| 调度优化 | OR-Tools | 第二阶段后处理容量和时间窗 |
| 消息系统 | 暂不引入 | 规模扩大后评估 Redis Streams、NATS 或 MQTT |

数据库文件属于临时运行数据，应加入 `.gitignore`。表结构和虚拟数据由 SQLAlchemy 模型、初始化脚本和种子脚本描述，并随 Git 管理。数据结构变化时直接重建 Demo 数据库，不维护迁移链。

系统只运行一个 DispatcherAgent，由它串行处理任务分配。分配操作仍应放在短事务中，并通过订单状态条件、车辆状态条件和唯一约束防止重复分配，但当前阶段不引入乐观锁字段、数据库行锁或并行调度器领取机制。

---

## 11. 目标代码结构

```text
nl_json_translator/
├── domain/
│   ├── models.py             # 领域对象
│   ├── enums.py              # 状态枚举
│   └── schemas.py            # Pydantic 输入输出协议
├── repositories/
│   ├── locations.py
│   ├── vehicles.py
│   ├── orders.py
│   ├── missions.py
│   └── reservations.py
├── services/
│   ├── intent_parser.py
│   ├── location_resolver.py
│   ├── order_service.py
│   ├── dispatch_service.py
│   ├── routing_service.py
│   └── simulation_service.py
├── agents/
│   ├── dispatcher_agent.py
│   ├── vehicle_agent.py
│   └── monitor_agent.py
├── infrastructure/
│   ├── database.py
│   ├── orm_models.py
│   ├── init_db.py
│   ├── seed_demo_data.py
│   ├── deepseek_client.py
│   └── event_bus.py
├── api/
│   ├── app.py
│   └── routes/
└── simulation/
    ├── map_renderer.py
    └── runtime.py
```

无需一次完成全部重构。建议先新增目录并逐步迁移，保证现有 CLI 和 Streamlit 演示始终可运行。

---

## 12. 初步 API 设计

### 地点与地图

```text
POST   /locations
GET    /locations
GET    /locations/{id}
PATCH  /locations/{id}
POST   /locations/{id}/aliases

GET    /map
POST   /map/nodes
POST   /map/edges
POST   /map/obstacles
```

地图管理接口只用于启动 Demo 前准备虚拟数据。仿真运行后地图进入只读状态，修改在下一次运行时生效。

### 车辆

```text
POST   /vehicles
GET    /vehicles
GET    /vehicles/{id}
PATCH  /vehicles/{id}
POST   /vehicles/{id}/telemetry
GET    /vehicles/{id}/missions
```

### 订单与任务

```text
POST   /orders/from-natural-language
POST   /orders
GET    /orders
GET    /orders/{id}
POST   /orders/{id}/confirm-location
POST   /orders/{id}/cancel

GET    /missions
GET    /missions/{id}
POST   /missions/{id}/replan
```

所有创建类接口应支持幂等键，避免 UI 重试或网络重发造成重复订单。

---

## 13. 实施阶段

### 当前实施状态（2026-08-25）

- 阶段 0 和阶段 1 的核心数据链路已经完成；地点管理页面或基础 API 仍未实现。
- 阶段 2 已完成订单创建、Mission、MissionStep 和 AgentEvent 持久化，订单可展开为标准任务步骤。
- 阶段 3 已进入开发：当前已有三辆差异化 Demo 车辆、确定性 DispatchService、活动 Mission 唯一约束、批量分配和多车 SVG 调度总览。
- 阶段 3 已支持进程内同步播放多个 Mission：车辆会依次前往取货点、装货、载货运输、卸货，并在动画结束后提交最终状态。
- 阶段 3 尚未实现各 VehicleAgent 独立异步推进和逐时间片状态落库；当前由统一仿真运行时生成同步帧。
- 阶段 4 已实现进程内离散时间片、Cooperative A*、普通节点容量、双向边预约和 WAIT/绕行；三车同步帧会验证节点与迎面边冲突。
- 阶段 4 尚未实现 `route_reservations` 数据库表、预约恢复和阻塞后的在线局部重规划。
- 阶段 5 尚未开始。

### 阶段 0：领域协议与工程准备

工作内容：

- 确定地点、车辆、订单、Mission、Step 和 Reservation 的状态枚举。
- 定义运输意图草稿和正式订单 Pydantic Schema。
- 增加 SQLite、SQLAlchemy 和数据库配置。
- 实现 `init_db.py` 和 `seed_demo_data.py`。
- 建立 Repository 接口，业务层不直接依赖 ORM 查询。
- 保留现有动作执行器的行为测试。

验收标准：

- 现有测试继续通过。
- 空数据库可以根据当前模型自动建表并填充虚拟数据。
- TransportOrder Schema 能校验合法与非法运输订单。

### 阶段 1：地点和地图数据库化

工作内容：

- 创建地点、别名、地图节点和地图边表。
- 将当前 A、B、C、lab、charging station 和障碍物迁移为种子数据。
- 实现 `LocationRepository` 和 `MapRepository`。
- 实现 `LocationResolver`。
- 改造地图执行器，从数据库读取固定地图节点和障碍物。
- 增加 Streamlit 地点管理页面或基础 API。

验收标准：

- 数据库新增地点后，无需修改 Prompt 和代码即可解析。
- 地点重命名后历史任务仍通过 ID 正确关联。
- 未知或歧义地点不会被模型自动猜测。
- 地点或地图数据的修改在下一次 Demo 初始化或运行时生效，不支持执行中修改。
- 当前单车 A* 示例迁移后保持结果一致。

### 阶段 2：货物运输订单

工作内容：

- 实现 Cargo、TransportOrder、Mission 和 MissionStep。
- 修改 Prompt，使其输出运输意图草稿。
- 实现“意图解析 -> 地点解析 -> 订单创建”流水线。
- 将订单展开为 REPOSITION、LOAD、TRANSPORT、UNLOAD。
- 在 UI 中展示订单状态、取送点、货物和执行步骤。

验收标准：

- “从 A 取 3 箱零件送到 B”可以生成正式运输订单。
- 地点歧义订单进入 `NEEDS_REVIEW`。
- 货物超出车辆容量时不能进入正常分配流程。
- 同一幂等键不会重复创建订单。

### 阶段 3：多车与中央调度

工作内容：

- 实现车辆表和车辆状态机。
- 支持每辆车独立的初始位置、容量、电量和能力。
- 实现 DispatcherAgent 的候选过滤与贪心分配。
- 由唯一 DispatcherAgent 在短事务中检查并更新订单和车辆状态。
- 实现多个进程内 VehicleAgent。
- 更新 SVG 和 Streamlit，一张地图同时显示多辆车。

验收标准：

- 多辆车可以从不同地点并行执行不同订单。
- 一个订单不会被重复分配。
- 一辆车同一时刻最多拥有一个互斥的活动 Mission。
- 指定车辆、容量、电量和能力约束均生效。

### 阶段 4：多车冲突避免

工作内容：

- 引入离散时间片。
- 建立节点和边预约表。
- 扩展 A*，加入时间维度和 WAIT 动作。
- 检测同节点冲突和迎面边冲突。
- 实现阻塞后的局部重新规划。

验收标准：

- 任意时间片不存在两辆车占用同一节点。
- 任意时间片不存在两辆车在同一边迎面通行。
- 狭窄路径冲突时至少一辆车能够等待或改道。
- 无法安全规划时任务保持等待或失败，不产生不安全路径。

### 阶段 5：监控、异常与优化

工作内容：

- 实现 MonitorAgent。
- 支持车辆离线、低电量和任务超时。
- 支持任务重新分配和路径重规划。
- 评估 OR-Tools 进行批量订单优化。
- 根据真实设备接入需求选择消息系统。

验收标准：

- 车辆故障后未完成订单可以安全重新调度。
- 所有关键操作均可从事件日志追踪。

---

## 14. 测试计划

### 14.1 单元测试

- 地点名称与别名规范化。
- 精确匹配、模糊匹配、歧义和未知地点。
- TransportOrder Schema。
- 车辆硬约束过滤。
- 调度成本计算。
- 车辆和订单状态机合法迁移。
- 节点与边冲突检测。

### 14.2 数据库集成测试

- 空 SQLite 数据库初始化。
- Demo 种子数据重复执行时不会产生重复记录。
- 单 Dispatcher 连续调度时不会重复分配订单或车辆。
- 非法订单和车辆状态迁移会被拒绝。
- 唯一约束和幂等键。
- Agent 异常退出后的状态恢复。

### 14.3 仿真测试

- 两辆车从不同位置执行不同订单。
- 两辆车争用同一取货点。
- 两辆车在狭窄通道相向行驶。
- 指定车辆正在忙碌。
- 车辆到达取货点前故障。
- 低电量车辆不参与长距离订单。

### 14.4 LLM 回归测试

样例文件需要从“只校验预期 JSON Schema”升级为：

- 验证模型输出的意图类型。
- 验证地点原文提取。
- 验证货物、数量、重量和优先级提取。
- 验证多订单输入的顺序。
- 对模型相关测试区分离线 FakeClient 测试和可选在线评估。

---

## 15. 关键风险与应对

### 15.1 地点模糊匹配错误

风险：模型或模糊搜索将相似地点错误匹配。

应对：稳定 ID、别名表、置信度阈值、歧义确认和审计日志；禁止低置信度自动执行。

### 15.2 过早引入过多基础设施

风险：微服务、消息队列和分布式 Agent 增加开发成本。

应对：先使用模块化单体、SQLite 和 `asyncio`，待真实规模明确后再评估更高并发数据库、独立进程和消息系统。

### 15.3 调度与路径规划职责混合

风险：优化器既决定车辆又直接处理所有网格冲突，难以测试和演进。

应对：明确区分订单分配、任务排序、全局路径和车辆局部控制。

### 15.4 数据库状态与 Agent 内存不一致

风险：Agent 重启后丢失任务进度或重复执行。

应对：数据库保存事实状态；命令和事件使用幂等键；Agent 启动时从数据库恢复。

### 15.5 模拟假设与真实车辆不一致

风险：一格一米、离散朝向和固定耗时无法代表真实车辆。

应对：将地图、路径和执行接口抽象化；模拟器作为一种执行后端，未来真实车辆网关作为另一种后端。

---

## 16. 近期建议执行清单

建议下一轮实现优先完成以下事项：

1. 定义运输意图和正式订单 Schema。
2. 建立 SQLite、SQLAlchemy、初始化脚本和 Demo 种子数据。
3. 创建地点、别名、地图节点和地图边表。
4. 将当前静态地图迁移为种子数据。
5. 实现 `LocationResolver` 和地点歧义处理。
6. 改造 `map_executor`，使其通过 Repository 读取固定地图而非全局常量。
7. 增加 TransportOrder 和车辆的最小数据模型。
8. 保持现有 CLI、测试和 Streamlit 单车流程可运行。

完成以上内容后，再进入多车调度和避碰阶段，可以显著降低一次性重构风险。

---

## 17. 参考资料

- OR-Tools Pickup and Delivery：<https://developers.google.com/optimization/routing/pickup_delivery>
