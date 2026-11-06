# ODD 判决语义

> 逐条规则与具体边界值见 **`docs/odd_rules.md`**（profile = `byd_tjp`，43 条，边界值经实测校验）。
> 本文描述通用语义，与当前实现一致（2026-11-06 基准）；逐条规则与精确边界值见 `docs/odd_rules.md`。

## 1. 三态分类（ISO 34503 Clause 6）

| 状态 | 含义 | 系统期望行为 |
|------|------|-------------|
| **INSIDE** | 满足 ODD | ADS 执行 DDT，性能达标 |
| **BOUNDARY** | 接近限制值 / Conditional 切换区 | 降级、限速、预警、准备 MRM |
| **OUTSIDE** | 不满足 ODD | 拒绝激活 / transition demand / MRM |

另有两个不参与聚合的辅助态：`UNDEFINED`（不定义/按 default 回退）、`SKIPPED`（开关关闭或 `applies_when` 不成立）。

## 2. 元素要求映射

### allowed（允许）

观测值 → 直接映射：

| 观测状态 | 判决 |
|---|---|
| 在阈值内且有裕度 | INSIDE |
| 落入边界带 | BOUNDARY |
| 超出阈值 | OUTSIDE |

### not_allowed（不允许）

「禁止条件**出现**」是越界触发。语义反转：

| 禁止条件 | 判决 |
|---|---|
| 出现（如：有行人、有路口） | OUTSIDE |
| 临近（如：枚举 boundary_values） | BOUNDARY |
| 不存在 | INSIDE |

### undefined（不定义）

不评估，记入 `undefined_handled`，不参与聚合。

## 3. 定义模式（DefinitionMode）— 缺失观测回退

最后一级回退。完整优先级链（高 → 低）：元素 `requirement=undefined` →
元素级 `undefined_as` → profile 顶层 `missing_policy.by_element` → `by_tag` →
`default` → 本节的 `definition_mode`。

| 模式 | 行为 | 用途 |
|------|------|------|
| **permissive** | 视为 INSIDE，跳过 | 演示 / 宽松原型 |
| **restrictive** | 视为 OUTSIDE（`UNDEFINED-STRICT`） | **BYD TJP 默认**，安全优先 |
| **default** | UNDEFINED，不入聚合 | ODC 骨架探索 |

`undefined_as` 三个取值均有效：`allowed` → INSIDE、`not_allowed` → OUTSIDE、`undefined` → UNDEFINED（`UNDEFINED-AS-UNDEFINED`），逐元素覆盖 profile 模式。

`missing_policy` 取值 `allowed | not_allowed | undefined | mode`（`mode` = 落到
`definition_mode`），按 `by_element[id]` → `by_tag[标签]`（依 `rule.tags` 顺序）→
`default` 解析；命中来源记入 `RuleResult.policy_source` 与
`report.undefined_handled[].policy`。元素级 `undefined_as` 优先于 `missing_policy`。

**视同缺失的非法观测**（同样走上述回退）：数值规则的非数字字符串与 `NaN`/`±inf`；布尔规则的非布尔类型（字符串 `"false"` 等，数值 `0`/`1` 合法）；枚举规则（allowed 形态）未命中任何集合的未知值；失配时的低置信数据（`c < threshold − band`）。

## 4. 定量边界（BoundaryMargin）

```
absolute: band = value
relative: band = |threshold| * value   (between: band = (hi-lo) * value)
未配置:   band = 0（两态，无 BOUNDARY）
```

判定式（`odd_judge/core/margin.py`，统一安全裕度原理）：

```
margin = 到违反集的距离（域内为正；margin == 0 恰在阈值/区间端点上）

序关系/区间类（>= > <= < between）:
    margin < 0（严格算子 == 0 也违反） → OUTSIDE
    0 ≤ margin < band                 → BOUNDARY
    margin ≥ band                     → INSIDE（带边缘归 INSIDE）

比较类（== / !=）:
    band 是闭合容差带：|v−thr| ∈ (0, band] → BOUNDARY；带边缘归 BOUNDARY
    == : v == thr → INSIDE，|v−thr| > band → OUTSIDE
    != : v == thr → OUTSIDE，|v−thr| > band → INSIDE（band=0 时为两态）
```

- **端点稳定**：`margin` 与 `band` 比较时启用 `EDGE_REL_TOL = 1e-12`（`math.isclose`），十进制字面量端点（`220`、`13.4`、`2.7`、`1.8`、`0.65`…）无论二进制舍入方向都稳定归 INSIDE。
- `between` 的边界带**两端都生效**（如速度 `[0,80]` band 3 ⇒ `[0,3)` 与 `(77,80]` 为 BOUNDARY，含 0 km/h 停车；`3` 与 `77` 归 INSIDE）。
- `NaN` / `±inf`：`classify_numeric` 直接抛 `ValueError`；评估层视同缺失，按第 3 节回退（不再可能误判 INSIDE）。

`remaining_margin`：到最近阈值的**有符号距离**（正=域内，0=恰在阈值，负=越界）。

## 5. 定性边界

- **枚举**：判定优先级 `allowed_values` > `boundary_values` > `forbidden_values`；**未命中任何集合的未知值视同缺失**（按第 3 节回退）。配置形态由 schema 约束：`allowed` 要求必须给 `allowed_values`；`not_allowed` 要求必须给 `forbidden_values` 且不得给 `allowed_values`；三集合两两不重叠——两种形态下语义唯一，无分叉。
- **布尔**：默认严格两态（INSIDE / OUTSIDE）。可选置信度三段判别（仅失配时启用，`confidence_threshold` + `confidence_band` + `confidence_observation_key` 三字段成组、仅限 `qualitative_bool`）：
  - `c ≥ threshold` → OUTSIDE（可信失配）；
  - `threshold − band ≤ c < threshold` → BOUNDARY（临界带）；
  - `c < threshold − band` / 置信度缺失 → 视同缺失回退。
- 观测值须为 JSON 布尔或数值 `0`/`1`；字符串等其他类型视同缺失（不再 `bool()` 真值化）。

## 6. 组合条件（Conditional / AllOf / AnyOf / Not）

```json
{"all_of": [
  {"key": "scenery.road_type", "op": "in", "value": ["expressway_main"]},
  {"not": {"key": "scenery.construction_zone", "op": "==", "value": true}}
]}
```

- `applies_when` 为假时规则跳过（`CONDITIONAL-SKIP`），不参与判决，**不走缺失回退**。
- 叶子引用的键缺失 → 该叶子为**假**；因此 `not` 内部叶子缺失时整体为**真**（`not` 分支把缺失当"满足"）。
- 求值顺序：开关 → `applies_when` → `requirement=undefined` → 缺失回退 → 规则类型评估。

## 7. 聚合与建议

```
参与态: INSIDE / BOUNDARY / OUTSIDE（UNDEFINED、SKIPPED 剔除）
优先级: OUTSIDE > BOUNDARY > INSIDE；无参与规则 → UNDEFINED
severity: OUTSIDE→critical, BOUNDARY→warning, 其余→info
recommendation: INSIDE→continue, BOUNDARY→warn_driver, OUTSIDE→mrm_or_refuse, UNDEFINED→continue
```

## 8. 开关（Switches）

- `global_enabled=false`：全部跳过
- `by_element[id]=false`：按元素关闭
- `by_rule_type[type]=false`：按规则类型关闭
- `by_tag[tag]=false`：按标签关闭（规则任一标签命中即跳过）
- `boundary_warnings_enabled=false`：`boundary_reasons` 清空，**整体状态由 BOUNDARY 降为 INSIDE**（建议随之变 `continue`），但 `results[]` 中各规则仍保留 BOUNDARY 原值

关闭的规则记入 `skipped[]`，不参与判决。
报告字段 `active_switches` 只列出**实际生效（非默认）**的开关项（全默认时为空列表）。

## 9. 告警码

- 引擎判决码（`reason_code`，如 `UNDEFINED-STRICT`、`MISSING-POLICY-ALLOWED`）随结果输出。
- profile 元素级告警码（`warning_codes.outside` / `warning_codes.boundary`，格式
  `^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$`，全 profile 唯一，schema 强制校验）供报告消费方
  归因；命名规范与完整码表见 `odd_perception_suite` 仓库 `docs/warning_codes.md`。

