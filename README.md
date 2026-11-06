# ODD_Judge — 设计运行域判决引擎

针对 **临近边界** 与 **越界** 行为进行预警的 ODD（Operational Design Domain）判决工程。

> **独立仓库**：本仓是 `odd_judge` 引擎的 canonical 源。
> `odd_perception_suite` 以 **git submodule `judge/`** 消费本仓（双 editable 安装
> `pip install -e ./judge -e ".[dev]"`）；引擎改动请在本仓提交后再更新子模块指针。
> 引擎级 fixture 同步约定：`profiles/`、`switches/` 的规则内容以**本仓为准**，
> 改动后同步到 suite 根目录同名副本（suite CLI 按自身根目录读取）。

## 特性

- **三态判决**：`INSIDE`（域内）/ `BOUNDARY`（临近边界）/ `OUTSIDE`（越界）
- **定量规则**：数值阈值 + 可配置边界带（绝对/相对），输出剩余裕度
- **定性规则**：枚举匹配、布尔标志、禁止项（`not_allowed`）语义
- **开关控制**：按元素 / 规则类型 / 标签开关，关闭规则跳过并记录
- **JSON 配置**：ODD 规则 profile、感知观测、开关策略全部 JSON 驱动
- **可扩展**：插件注册新规则类型与 ODC 元素，ODC 骨架 + 企业 override
- **感知接入**：统一 `Observation` schema，Mock / JSON / JSONL 适配器，预留 ROS/CAN

## 快速开始

```bash
cd /home/shuai/projects/ODD_Judge

# 域内场景
python3 -m odd_judge evaluate --profile byd_tjp \
  --obs observations/sample_highway_inside.json --format text

# 临近边界场景（输出预警码 + 剩余裕度）
python3 -m odd_judge evaluate --profile byd_tjp \
  --obs observations/sample_curve_boundary.json --format text

# 越界场景（输出 mrm_or_refuse 建议）
python3 -m odd_judge evaluate --profile byd_tjp \
  --obs observations/sample_rain_outside.json --format text

# JSON 输出
python3 -m odd_judge evaluate --profile byd_tjp \
  --obs observations/sample_curve_boundary.json --format json --out report.json

# 校验配置 / 列出规则
python3 -m odd_judge validate --profile profiles/byd_tjp.json
python3 -m odd_judge list-rules --profile byd_tjp --tag driver

# 运行测试
python3 -m pytest tests/ -v
```

### 退出码（evaluate）

| 码 | 含义 |
|---|---|
| `0` | INSIDE（或 UNDEFINED / 全部 SKIPPED）→ `continue` |
| `1` | BOUNDARY → `warn_driver` |
| `3` | OUTSIDE → `mrm_or_refuse` |
| `4` | 输入/配置错误（stderr，`ERROR:` 前缀，无堆栈） |
| `2` | argparse 参数解析错误（保留） |

## Python API

```python
from odd_judge import OddJudge

judge = OddJudge.from_files("profiles/byd_tjp.json", "switches/default_switches.json")
report = judge.evaluate_path("observations/sample_curve_boundary.json")

print(report.state)          # ScenarioState.BOUNDARY
print(report.recommendation) # warn_driver
print(report.boundary_reasons)
for r in report.results:
    if r.remaining_margin is not None:
        print(r.element_id, r.remaining_margin)
```

## 目录结构

```
ODD_Judge/
├── odd_judge/            # 核心包
│   ├── core/             # 类型、边界带、规则评估、聚合
│   ├── config/           # 配置加载、校验、插件注册
│   ├── perception/       # 感知适配器 (Mock / JSON)
│   └── report/           # 报告渲染
├── profiles/             # ODD 规则 profile
│   ├── byd_tjp.json      # BYD TJP 默认 profile（restrictive）
│   ├── odc_skeleton.json # GB/T 45312 骨架（default）
│   ├── odc_ext_cn.json   # CN 扩展维度（附着/密度/限速）
│   └── overrides/        # 企业扩展 override（example_enterprise / city_noa_cn）
├── switches/             # 开关策略
├── observations/         # 观测样例 (inside/boundary/outside)
├── tests/                # 单元 + e2e（含自 suite 迁入的 missing_policy / ext / city override 用例）
├── docs/
│   ├── odd_rules.md      # 逐条 ODD 判别规则 + 边界值明细（byd_tjp 42 条）
│   └── semantics.md      # 判决语义说明（通用语义总纲）
```

## 判决语义速查

> 完整的逐条规则与精确边界值（16 条数值 / 2 条枚举 / 24 条布尔）见 **`docs/odd_rules.md`**。

| 元素要求 | 域内 | 临近边界 | 越界 |
|---|---|---|---|
| `allowed` | INSIDE | BOUNDARY 预警 | OUTSIDE 退出/拒绝 |
| `not_allowed` | OUTSIDE | BOUNDARY | INSIDE |
| `undefined` | 不评估 | — | — |

**definition_mode**（缺失观测回退）：
- `restrictive` → OUTSIDE（BYD TJP 默认，安全优先）
- `permissive` → INSIDE
- `default` → UNDEFINED

回退优先级：`requirement=undefined` > 元素 `undefined_as` > profile 顶层
`missing_policy`（`by_element` → `by_tag` → `default`，取值
`allowed | not_allowed | undefined | mode`，命中来源记入 `policy_source`）> `definition_mode`。

聚合优先级：`OUTSIDE > BOUNDARY > INSIDE`  
建议映射：`continue` / `warn_driver` / `mrm_or_refuse`

## 扩展方式

1. **新增 ODC 元素**：在 override JSON 中追加 `element_id` + 规则
2. **新增规则类型**：`register_rule_type("my_type")` + 在 `evaluate.py` 增加评估函数
3. **接入感知**：实现 `ObservationAdapter.get_observation()` 返回 `Observation`
4. **合并骨架**：`--extends odc_skeleton` 合并 GB/T 45312 层级元素

## 配置要点

### 定量规则
```json
{
  "rule_type": "numeric_range",
  "observation_key": "scenery.curve_radius_m",
  "op": ">=",
  "threshold": 200.0,
  "boundary_margin": {"mode": "absolute", "value": 20.0}
}
```
值落入边界带 → `BOUNDARY`，输出 `remaining_margin`（到最近阈值的有符号距离）。

### 定性规则
```json
{
  "rule_type": "qualitative_enum",
  "observation_key": "scenery.road_type",
  "allowed_values": ["expressway_main", "highway_main"],
  "forbidden_values": ["rural_road"],
  "boundary_values": ["urban_arterial"]
}
```

### 开关
```json
{
  "by_element": {"ODC.3.1.2.rain_intensity": false},
  "by_tag": {"driver": true},
  "boundary_warnings_enabled": true
}
```

## 来源依据

- BYD TJP ODC 表 B.1/B.2/B.3（交通拥堵自动驾驶设计运行条件）
- ISO 34503:2023（ODD 分类法与定义格式）
- GB/T 43267—2023（预期功能安全 / ODD exit）
- GB/T 45312（ODC 元素列表层级）
- ODD 边界与域外 Case 感知可判定清单
