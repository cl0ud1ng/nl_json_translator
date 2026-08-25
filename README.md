# 场内货物运输 NL-to-JSON Demo

本项目将自然语言货物取送请求转换为运输意图，使用数据库地点解析生成正式订单，由中央调度服务分配车辆和 Mission，并在 SQLite 地图上展示多车计划路线。

当前链路：

```text
自然语言
  -> DeepSeek 运输意图提取
  -> Pydantic Schema 校验
  -> LocationResolver 地点解析
  -> TransportOrder 持久化
  -> DispatchService 车辆筛选与 Mission 创建
  -> 多车 SVG 调度总览与单车路径预览
```

LLM 只保留用户输入的地点文字、货物和约束，不生成数据库 ID，不分配车辆，也不规划路径。地点确认、订单状态和路径计算均由确定性代码执行。

## 当前项目进展

截至 2026-08-24，`plan.md` 中的“近期建议执行清单”已经完成：

- 运输意图和正式订单已成为唯一对外 Schema，旧动作协议仅保留为内部执行格式。
- SQLite/SQLAlchemy 数据层已建立，支持幂等初始化 Demo 地图、地点、别名和车辆。
- 地点解析支持标准名、别名、规范化、有限模糊匹配、歧义确认和未知地点错误。
- 地图执行器已改为通过 Repository 读取节点、边和地点，并保留单车 A* 与 SVG 动画。
- 车辆和运输订单已持久化，订单支持地点解析状态及幂等键。
- Mission、MissionStep 和 AgentEvent 已持久化；活动订单和活动车辆具备唯一 Mission 约束。
- DispatchService 支持优先级、指定车辆、遥测时效、容量、电量和能力硬约束，并使用数据库边权进行可解释的贪心分配。
- Demo 包含三辆差异化车辆，Streamlit 可同时展示车辆状态、活动 Mission、计划路线和调度事件。
- 多车运行时会同步播放车辆前往取货点、装货、载货运输、卸货和完成的全过程；已行驶路线、剩余路线与载货状态分别可见。
- 动画完成后会持久化订单、Mission、MissionStep、车辆最终位置和完成事件。
- 当前自动化测试共 45 项，覆盖 Schema、数据库、地点解析、订单、调度、加权路径、多车 SVG 和动态任务执行。

项目目前处于单进程、多车动态仿真阶段。当前运行时会同步推进多个 Mission 并在动画结束后提交最终状态，但尚未实现独立异步 VehicleAgent 和完整时空预约持久化；下一步是 Cooperative A* 冲突避免。

## 快速开始

项目要求 Python 3.9 或更高版本。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install "pydantic>=2.7,<3" "SQLAlchemy>=2.0,<3"
cp .env.example .env
# 编辑 .env，设置 DEEPSEEK_API_KEY
python -m nl_json_translator.infrastructure.seed_demo_data
python -m nl_json_translator.cli "从 A 取 3 箱零件送到 B"
```

CLI 输出的是唯一对外协议——运输意图草稿：

```json
{
  "intent": "create_transport_order",
  "cargo": {
    "name": "零件箱",
    "quantity": 3,
    "weight_kg": null,
    "volume_m3": null,
    "category": null,
    "required_capabilities": []
  },
  "pickup_location_text": "A",
  "dropoff_location_text": "B",
  "vehicle_text": null,
  "priority": "normal"
}
```

`go_to_goal` 等动作对象不再是外部协议，只在订单展开为内部执行步骤后使用。

## 数据库

默认数据库为 `data/nl_json_translator.db`，数据库文件不会提交到 Git。可通过环境变量覆盖：

```text
NL_JSON_DATABASE_URL=sqlite:///data/nl_json_translator.db
```

初始化空表结构：

```bash
python -m nl_json_translator.infrastructure.init_db
```

初始化并幂等填充 Demo 地图、地点、别名和车辆：

```bash
python -m nl_json_translator.infrastructure.seed_demo_data
```

当前 Demo 数据库属于可重建数据。表结构变化时删除旧数据库并重新运行种子命令，不维护迁移链。

## CLI 与 Streamlit

显示 Prompt 而不调用 API：

```bash
python -m nl_json_translator.cli --show-prompt "从实验室取药品送到充电站"
```

启动多车调度演示 UI：

```bash
python -m pip install -r requirements-ui.txt
streamlit run app.py
```

UI 会展示运输意图、地点候选、调度候选及拒绝原因、MissionStep、三辆车的计划路线、同步动态执行过程和最近事件。歧义地点进入 `NEEDS_REVIEW`；未知地点明确报错，不会自动猜测。

## 测试

```bash
python -m unittest discover -s tests -v
```

测试覆盖运输 Schema、数据库初始化和幂等种子、地点解析与歧义、订单幂等键、Mission/Event、车辆硬约束、加权调度、批量分配、多车 SVG，以及 Repository 驱动的 A* 回归。
