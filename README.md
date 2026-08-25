# 自然语言多车 Agent 调度系统

本项目将一段自然语言解析为 1 到 N 张场内运输订单，由唯一
`DispatcherAgent` 完成整体任务分配和全局路径预约，再由每辆车对应的
`VehicleAgent` 独立执行 Mission。

```text
自然语言
  -> DeepSeek 批量运输意图
  -> Pydantic Schema
  -> 地点解析与订单批次持久化
  -> DispatcherAgent 批量车辆匹配与 Cooperative A*
  -> 持久化 AgentCommand / RouteReservation
  -> N 个 VehicleAgent 逐时间片执行
  -> 订单、Mission、车辆和事件状态落库
  -> Streamlit 动态回放
```

DeepSeek 只提取用户明确表达的订单、地点文字和调度约束；不生成数据库
ID，不选择车辆，不规划路径。安全相关决策由确定性服务执行。

## 双层 Agent 架构

- `DispatcherAgent`：唯一总控，负责批量订单—车辆最小成本匹配、Mission 创建、
  协同路径规划、时空预约和持久化命令下发。
- `VehicleAgent`：每辆车一个实例，只消费本车命令，逐 tick 更新位置、载货、
  订单与 Mission 状态。
- `AgentRuntime`：使用确定性虚拟时钟协调 N 个 VehicleAgent，命令消费进度保存在
  SQLite，Agent 重建后可从执行游标继续。

核心事实数据包括 `transport_batches`、`transport_orders`、`missions`、
`mission_steps`、`agent_commands`、`vehicle_agent_states`、`route_reservations`
和 `agent_events`。

## 快速开始

需要 Python 3.9 或更高版本。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-ui.txt
cp .env.example .env
# 在 .env 中设置 DEEPSEEK_API_KEY
python -m nl_json_translator.infrastructure.seed_demo_data
streamlit run app.py
```

UI 默认自然语言会产生 3 张订单、3 辆不同车、2 个取货点和 2 个目标点，
但运行时和 Schema 没有三车数量限制。修改自然语言即可提交单订单或其他批量订单。
多车回放同步展示 DispatcherAgent 与每个 VehicleAgent 的双向信息流：蓝色为 Mission、
步骤和路由命令，橙色为命令接收、位置、阻塞、心跳和 Mission 完成事件。
多车调度总览保留最近一次调度的规划路线，并以 `Vn + 起/终` 标记每辆车的
规划起点和终点；轨迹回放中车辆到达目标后仍保留其完整已行驶路线。

CLI 可只查看 Prompt 或调用 DeepSeek 输出批量意图：

```bash
python -m nl_json_translator.cli --show-prompt "从 A 取一箱零件送到 B"
python -m nl_json_translator.cli "从 A 取一箱零件送到 B"
```

唯一对外意图协议使用 `orders` 数组，即使只有一张订单：

```json
{
  "intent": "create_transport_orders",
  "orders": [
    {
      "cargo": {"name": "零件箱", "quantity": 1},
      "pickup_location_text": "A",
      "dropoff_location_text": "B",
      "priority": "normal"
    }
  ],
  "dispatch_constraints": {
    "distinct_vehicle_per_order": false
  }
}
```

## 数据库

默认使用 `data/nl_json_translator.db`：

```text
NL_JSON_DATABASE_URL=sqlite:///data/nl_json_translator.db
```

Demo 数据库可重建，不维护迁移链。结构变更后可删除旧数据库，然后执行：

```bash
python -m nl_json_translator.infrastructure.seed_demo_data
```

## 测试

离线测试不访问网络：

```bash
python -m unittest discover -s tests -v
```

真实 DeepSeek 端到端测试会产生 API 调用费用，需要显式开启：

```bash
RUN_DEEPSEEK_E2E=1 python -m unittest tests.test_deepseek_e2e -v
```

在临时 SQLite 中验收：DeepSeek 响应元数据、3 张订单、3 辆不同车、2 个取货点、
2 个目标点、3 个 Mission、全部 `DELIVERED` 和零运行时冲突。
