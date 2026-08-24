# 场内货物运输 NL-to-JSON Demo

本项目将自然语言货物取送请求转换为运输意图，使用数据库地点解析生成正式订单，并在 SQLite 地图上演示单车取送路径。

当前链路：

```text
自然语言
  -> DeepSeek 运输意图提取
  -> Pydantic Schema 校验
  -> LocationResolver 地点解析
  -> TransportOrder 持久化
  -> Repository 地图读取与单车 A* 演示
```

LLM 只保留用户输入的地点文字、货物和约束，不生成数据库 ID，不分配车辆，也不规划路径。地点确认、订单状态和路径计算均由确定性代码执行。

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

启动完整单车演示 UI：

```bash
python -m pip install -r requirements-ui.txt
streamlit run app.py
```

UI 会展示运输意图、地点候选、订单状态、内部路径动作和数据库地图轨迹。歧义地点进入 `NEEDS_REVIEW`；未知地点明确报错，不会自动猜测。

## 测试

```bash
python -m unittest discover -s tests -v
```

测试覆盖运输 Schema、数据库初始化和幂等种子、地点解析与歧义、订单幂等键、车辆模型，以及 Repository 驱动的 A* 回归。
