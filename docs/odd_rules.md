# ODD 判别规则明细（逐条 + 边界值）

> 适用 profile：`profiles/byd_tjp.json`（`profile_id=byd_tjp`，`definition_mode=restrictive`，共 43 条规则）
> 行为基准：本工作区代码 `odd_judge/core/{margin,evaluate,aggregate}.py`，所有边界值均经探针实测校验（校验日期 2026-11-06）
> 语义总纲见 `docs/semantics.md`；本文只做"逐条可核对"的规格化列举。

---

## 1. 判决流水线（每条规则的执行顺序）

对单帧观测，按以下顺序判定，任一步即可得出该规则结论：

1. **开关过滤**（`api.SwitchPolicy`）：`global_enabled=false` / `by_element` / `by_rule_type` / `by_tag` 命中 false → 该规则不评估，记入 `skipped[]`，不参与聚合。
2. **适用条件**（`applies_when`）：条件树求值为假 → `SKIPPED`（`CONDITIONAL-SKIP`），不参与聚合。
   - 叶子键**缺失**时该叶子判为假（`evaluate._eval_leaf`），因此条件整体可能变假 → 走"跳过"而非"缺失回退"。
   - `not` 内部叶子缺失 → 叶子假 → `not` 为**真**（即 `not` 分支下缺失视为"满足条件"）。
3. **元素要求为 `undefined`** → 直接 `UNDEFINED`（`UNDEFINED-REQ`），不读观测、不参与聚合。
4. **观测缺失**（键不存在）→ 按第 6 节的回退矩阵处理；元素级 `undefined_as` 优先于 profile 级 `definition_mode`。
5. **规则类型评估**（`evaluate.py`）→ 原始状态，再经 `_apply_requirement` 映射：
   - `allowed`：原样保留；
   - `not_allowed`：`INSIDE↔OUTSIDE` 对调，`BOUNDARY` 保持；
   - `undefined`：恒为 `UNDEFINED`。
6. **聚合**（`aggregate.py`）：取参与规则的最差状态 `OUTSIDE > BOUNDARY > INSIDE`；`UNDEFINED`/`SKIPPED` 不参与；无参与规则 → 整体 `UNDEFINED`。

---

## 2. 数值规则判定式（`numeric_range`，实现：`margin.classify_numeric`）

边界带（band）：

```
absolute 模式:  band = boundary_margin.value
relative 模式:  band = |threshold| × value        （between 用 |hi − lo| × value）
未配置时:       band = 0（无边界带，只有 INSIDE/OUTSIDE 两态）
```

### 2.1 各运算符的精确三态不等式

设观测值 `v`、阈值 `thr`、区间 `[lo, hi]`、边界带 `band`：

| op | INSIDE | BOUNDARY | OUTSIDE | remaining_margin |
|---|---|---|---|---|
| `>=` | `v ≥ thr + band` | `thr ≤ v < thr + band` | `v < thr` | `v − thr` |
| `>` | `v ≥ thr + band`（band=0 时须 `v > thr`） | `thr < v < thr + band`（band=0 时为空） | `v ≤ thr` | `v − thr` |
| `<=` | `v ≤ thr − band` | `thr − band < v ≤ thr` | `v > thr` | `thr − v` |
| `<` | `v ≤ thr − band`（band=0 时须 `v < thr`） | `thr − band < v < thr`（band=0 时为空） | `v ≥ thr` | `thr − v` |
| `between` | 命中区间且 `min(v−lo, hi−v) ≥ band` | 命中区间且 `0 ≤ min(v−lo, hi−v) < band` | `v < lo` 或 `v > hi` | 命中时 `min(v−lo, hi−v)`；越界时 `v−lo`（偏低）或 `hi−v`（偏高），均为负 |
| `==` | `v == thr` | `0 < \|v−thr\| ≤ band` | 其余 | `thr − v` |
| `!=` | `\|v−thr\| > band` | `0 < \|v−thr\| ≤ band` | `v == thr` | INSIDE/BND 时 `\|v−thr\|`，越界时 `0.0` |

统一的**安全裕度原理**（`>= > <= < between` 六个序关系/区间算子）：

```
OUTSIDE   触碰违反集（margin < 0；严格算子 `>`/`<` 在 margin == 0 处也违反）
BOUNDARY  0 ≤ margin < band        （阈值/区间端点 margin == 0 恒为 BOUNDARY）
INSIDE    margin ≥ band            （"恰好差一个 band" 的端点归 INSIDE）
```

比较类算子（`==` / `!=`）的 band 是**闭合容差带**：带边缘（`\|v−thr\| = band`）归 **BOUNDARY**（`==` 带外即越界，`!=` 带内告警）；`band = 0` 时两者均退化为两态。

`band = 0`（或未配置 `boundary_margin`）时**无边界带**，只有 INSIDE/OUTSIDE。

`remaining_margin` 约定：**带符号距离**，正 = 域内、0 = 恰在阈值/边界上、负 = 越界。

### 2.2 端点与浮点语义

- **带边缘统一归 INSIDE**（序关系/区间类）：判定在 `margin` 与 `band` 比较时启用相对容差 `EDGE_REL_TOL = 1e-12`（`math.isclose`），因此十进制字面量端点（`220`、`13.4`、`2.7`、`1.8`、`0.65`、`±8.1` 等）**无论二进制舍入方向如何都稳定判 INSIDE**，不会出现"同为 band 0.2、横坡 1.8 归 BOUNDARY、车道宽度 2.7 归 INSIDE"的抖动。
- **阈值/区间端点归 BOUNDARY**：`v = thr`（`>=`/`<=`）、`v = lo` / `v = hi`（`between`）处 margin = 0，恒为 BOUNDARY。
- 严格算子 `>` / `<`：阈值本身（margin = 0）归 OUTSIDE。
- **非有限数值**：`classify_numeric` 对 `NaN` / `±inf` 直接抛 `ValueError`；评估层（`evaluate_numeric`）在更外层把非有限值**视同缺失观测**，按第 6 节回退矩阵处理（JSON 默认接受 `NaN` 字面量，接入层无需额外防护，但建议数据源直接杜绝）。
- 实现位置：`odd_judge/core/margin.py`（`_reaches_band` / `EDGE_REL_TOL`）。

---

## 3. 逐条规则明细

规则字段说明：`要求` = 元素要求（allowed / not_allowed）；`缺失` = 本 profile（restrictive）下观测缺失的结论。

### 3.1 道路特征 ODC.1（14 条）

**ODC.1.1.1.road_type 道路类型** `qualitative_enum`｜`scenery.road_type`｜要求 allowed｜预警码 `ODD-ROAD-TYPE-001`

| 观测值 | 判决 |
|---|---|
| `expressway_main`、`highway_main` | INSIDE |
| `urban_arterial`、`urban_minor`、`urban_branch`、`rural_road`、`highway_l1`～`highway_l4`、`other_road`（9 个 forbidden 值） | OUTSIDE |
| 其他任意未知值 | 视同缺失 → UNDEFINED（`missing_policy by_tag road`，`MISSING-POLICY-UNDEFINED`） |
| 缺失 | UNDEFINED（`missing_policy by_tag road`，不参与聚合） |

注：该规则**无 `boundary_values`**，永远不会产生 BOUNDARY；schema 强制 `allowed_values` 与 `forbidden_values`/`boundary_values` 两两不重叠（配置重叠会在 `validate` 阶段报错）。

**ODC.1.1.2.road_area 运行区域** `qualitative_bool`｜`scenery.legal_l3_area`｜expect=true｜要求 allowed｜预警码 `ODD-AREA-001`

| 观测 | 判决 |
|---|---|
| `true` | INSIDE |
| `false` | OUTSIDE |
| 缺失 | OUTSIDE（`UNDEFINED-STRICT`） |

**ODC.1.2.1.curve_radius 曲率半径** `numeric_range`｜`scenery.curve_radius_m`｜`op >=`，`thr=200.0`，`band=20.0 (absolute)`｜要求 allowed｜预警码 outside `ODD-GEO-RADIUS-001` / boundary `ODD-GEO-RADIUS-NEAR`

适用条件：`applies_when = scenery.road_type ∈ {expressway_main, highway_main}`，条件为假（含 road_type 缺失或取非高速值）→ 本规则 `SKIPPED`，不评估。

| 区间 | 判决 | remaining_margin |
|---|---|---|
| `v ≥ 220.0` | INSIDE | `v − 200` |
| `200.0 ≤ v < 220.0` | BOUNDARY | `v − 200`（0 ~ 20） |
| `v < 200.0` | OUTSIDE | `v − 200`（负） |
| 端点 `v = 200.0` | **BOUNDARY**（余量 0） | 0.0 |
| 端点 `v = 220.0` | **INSIDE** | 20.0 |
| 条件为假时 | SKIPPED（`CONDITIONAL-SKIP`） | — |
| road_type 存在但键本身缺失 | OUTSIDE（`UNDEFINED-STRICT`） | — |

**ODC.1.2.2.longitudinal_grade 纵坡** `numeric_range`｜`scenery.longitudinal_grade_pct`｜`op between`，`range=[-9.0, 9.0]`，`band=0.9`｜要求 allowed｜`ODD-GEO-GRADE-001` / `ODD-GEO-GRADE-NEAR`

| 区间 | 判决 | remaining_margin |
|---|---|---|
| `v < −9.0` 或 `v > 9.0` | OUTSIDE | 负值（到越近端的距离） |
| `[−9.0, −8.1) ∪ (8.1, 9.0]` | BOUNDARY | `min(v+9, 9−v)`（0 ~ 0.9） |
| `[−8.1, 8.1]` | INSIDE | `min(v+9, 9−v)` |
| 端点 `v = ±9.0` | BOUNDARY（余量 0） | 0.0 |
| 端点 `v = ±8.1` | **INSIDE**（带边统一归 INSIDE，fp 容差保护） | 0.9 |

**ODC.1.2.3.cross_slope 横坡 / 超高** `numeric_range`｜`scenery.cross_slope_pct`｜`between [-2.0, 2.0]`，`band=0.2`｜要求 allowed｜`ODD-GEO-SLOPE-001` / `ODD-GEO-SLOPE-NEAR`

| 区间 | 判决 | remaining_margin |
|---|---|---|
| `v < −2.0` 或 `v > 2.0` | OUTSIDE | 负 |
| `[−2.0, −1.8) ∪ (1.8, 2.0]` | BOUNDARY | `min(v+2, 2−v)`（0 ~ 0.2） |
| `[−1.8, 1.8]` | INSIDE | `min(v+2, 2−v)` |
| 端点 `v = ±2.0` | BOUNDARY（余量 0） | 0.0 |
| 端点 `v = ±1.8` | **INSIDE**（带边统一归 INSIDE，fp 容差保护） | 0.2 |

**ODC.1.2.4.lane_width 车道宽度** `numeric_range`｜`scenery.lane_width_m`｜`between [2.5, 5.5]`，`band=0.2`｜要求 allowed｜`ODD-LANE-WIDTH-001` / `ODD-LANE-WIDTH-NEAR`

| 区间 | 判决 | remaining_margin |
|---|---|---|
| `v < 2.5` 或 `v > 5.5` | OUTSIDE | 负 |
| `[2.5, 2.7) ∪ (5.3, 5.5]` | BOUNDARY | `min(v−2.5, 5.5−v)`（0 ~ 0.2） |
| `[2.7, 5.3]` | INSIDE | `min(v−2.5, 5.5−v)` |
| 端点 `v = 2.5 / 5.5` | BOUNDARY（余量 0） | 0.0 |
| 端点 `v = 2.7 / 5.3` | **INSIDE**（带边统一归 INSIDE，fp 容差保护） | 0.2 |

**ODC.1.3.1.marking_clear 标线清晰** `qualitative_bool`｜`scenery.marking_clear`｜expect=true｜要求 allowed｜`SCN-LANE-01`
→ `true` = INSIDE；`false` = OUTSIDE；缺失 = OUTSIDE。

**ODC.1.3.2.no_marking 无道路交通标线** `qualitative_bool`｜`scenery.has_no_marking`｜expect=true｜要求 **not_allowed**｜`SCN-LANE-03`
→ 出现（`true`）= OUTSIDE；未出现（`false`）= INSIDE；缺失 = OUTSIDE。

**ODC.1.4.1.intersection 平面交叉路口** `qualitative_bool`｜`scenery.has_intersection`｜expect=true｜**not_allowed**｜`SCN-JCT-01`
→ `true` = OUTSIDE；`false` = INSIDE；缺失 = OUTSIDE。

**ODC.1.4.2.roundabout 环岛** `qualitative_bool`｜`scenery.has_roundabout`｜expect=true｜**not_allowed**｜`SCN-JCT-02`
→ `true` = OUTSIDE；`false` = INSIDE；缺失 = OUTSIDE。

**ODC.1.4.3.ramp 匝道** `qualitative_bool`｜`scenery.has_ramp`｜expect=true｜**not_allowed**｜`ODD-JCT-RAMP-001`
→ `true` = OUTSIDE；`false` = INSIDE；缺失 = OUTSIDE。

**ODC.1.4.4.toll_station 收费站** `qualitative_bool`｜`scenery.has_toll_station`｜expect=true｜**not_allowed**｜`SCN-STR-03`
→ `true` = OUTSIDE；`false` = INSIDE；缺失 = OUTSIDE。

**ODC.1.4.5.railway_crossing 铁路交叉** `qualitative_bool`｜`scenery.has_railway_crossing`｜expect=true｜**not_allowed**｜`SCN-STR-04`
→ `true` = OUTSIDE；`false` = INSIDE；缺失 = OUTSIDE。

**ODC.1.4.6.construction 道路施工** `qualitative_bool`｜`scenery.construction_zone`｜expect=true｜**not_allowed**｜`SCN-SIGN-04`
→ `true` = OUTSIDE；`false` = INSIDE；缺失 = OUTSIDE。

**ODC.1.4.7.accident_scene 事故现场** `qualitative_bool`｜`scenery.accident_scene`｜expect=true｜**not_allowed**｜`ODD-TEMP-ACC-001`
→ `true` = OUTSIDE；`false` = INSIDE；缺失 = OUTSIDE。

**ODC.1.4.8.traffic_control 交通管制** `qualitative_bool`｜`scenery.traffic_control`｜expect=true｜**not_allowed**｜`ODD-TEMP-CTRL-001`
→ `true` = OUTSIDE；`false` = INSIDE；缺失 = OUTSIDE。

### 3.2 车辆运动状态 ODC.2（6 条）

**ODC.2.1.1.speed 运行速度** `numeric_range`｜`vehicle.speed_kmh`｜`between [0.0, 80.0]`，`band=3.0`｜要求 allowed｜`ODD-SPD-001` / `ODD-SPD-NEAR`

| 区间 | 判决 | remaining_margin |
|---|---|---|
| `v < 0.0` 或 `v > 80.0` | OUTSIDE | 负 |
| `[0.0, 3.0)` | BOUNDARY | `min(v, 80−v)` |
| `[3.0, 77.0]` | INSIDE | `min(v, 80−v)` |
| `(77.0, 80.0]` | BOUNDARY | `min(v, 80−v)` |
| `v = 0.0` | **BOUNDARY（余量 0）** —— 低速端 0 ≤ v < 3 km/h 是边界带，拥堵停走工况会持续告警 | 0.0 |
| `v = 80.0` | BOUNDARY（余量 0） | 0.0 |
| 端点 `v = 3.0 / 77.0` | **INSIDE**（带边统一归 INSIDE，fp 容差保护） | 3.0 |

**ODC.2.1.2.activation_speed 激活速度** `numeric_range`｜`vehicle.activation_speed_kmh`｜`between [0.0, 80.0]`，`band=3.0`｜要求 allowed｜`ODD-SPD-ACT-001` / `ODD-SPD-ACT-NEAR`
→ 边界值与"运行速度"完全相同：OUT `v<0 ∨ v>80`；BND `[0,3) ∪ (77,80]`；INS `[3,77]`。

**ODC.2.1.3.lat_accel 横向加速度** `numeric_range`｜`vehicle.lat_accel_mps2`｜`between [-2.0, 2.0]`，`band=0.2`｜要求 allowed｜`ODD-ACC-LAT-001` / `ODD-ACC-LAT-NEAR`
→ OUT `v<−2 ∨ v>2`；BND `[−2,−1.8) ∪ (1.8,2]`（端点 ±1.8 归 INSIDE）；INS `[−1.8,1.8]`。

**ODC.2.1.4.lon_accel 纵向加速度** `numeric_range`｜`vehicle.lon_accel_mps2`｜`between [-10.0, 2.0]`，`band=0.5`｜要求 allowed｜`ODD-ACC-LON-001` / `ODD-ACC-LON-NEAR`

| 区间 | 判决 |
|---|---|
| `v < −10.0` 或 `v > 2.0` | OUTSIDE |
| `[−10.0, −9.5) ∪ (1.5, 2.0]` | BOUNDARY（端点 −9.5 / 1.5 归 INSIDE） |
| `[−9.5, 1.5]` | INSIDE |

### 3.3 天气与光照环境 ODC.3（6 条）

**ODC.3.1.1.visibility 能见度** `numeric_range`｜`environment.visibility_m`｜`op >=`，`thr=200.0`，`band=30.0`｜要求 allowed｜`ENV-VIS-001` / `ENV-VIS-NEAR`
→ INS `v ≥ 230.0`；BND `200.0 ≤ v < 230.0`（端点 200.0 = BOUNDARY，230.0 = INSIDE）；OUT `v < 200.0`；missing → OUTSIDE。

**ODC.3.1.2.rain_intensity 降雨强度** `numeric_range`｜`environment.rain_mm_per_h`｜`op <=`，`thr=14.9`，`band=1.5`｜要求 allowed｜`ENV-RAIN-002` / `ENV-RAIN-NEAR`
→ INS `v ≤ 13.4`；BND `13.4 < v ≤ 14.9`（端点 14.9 = BOUNDARY，13.4 = INSIDE）；OUT `v > 14.9`；missing → OUTSIDE。

**ODC.3.1.3.snow_level 降雪** `qualitative_enum`｜`environment.snow_level`｜要求 allowed｜`ENV-SNOW-001` / `ENV-SNOW-NEAR`

| 观测值 | 判决 |
|---|---|
| `none`、`light` | INSIDE |
| `moderate` | BOUNDARY |
| `heavy`、`blizzard` | OUTSIDE |
| 其他未知值 | 视同缺失（restrictive → OUTSIDE，`UNDEFINED-STRICT`） |
| 缺失 | OUTSIDE（`UNDEFINED-STRICT`） |

**ODC.3.1.4.illumination 环境照度** `numeric_range`｜`environment.illumination_lux`｜`op >=`，`thr=50.0`，`band=10.0`｜要求 allowed｜`ILL-LUX-001` / `ILL-LUX-NEAR`
→ INS `v ≥ 60.0`；BND `50.0 ≤ v < 60.0`；OUT `v < 50.0`；missing → OUTSIDE。

**ODC.3.1.5.glare 强眩光 / 逆光** `qualitative_bool`｜`environment.glare`｜expect=true｜**not_allowed**｜`ILL-GLARE-01`
→ `true` = OUTSIDE；`false` = INSIDE；缺失 = OUTSIDE。

**ODC.3.1.6.fog 雾 / 浓雾** `qualitative_bool`｜`environment.fog`｜expect=true｜**not_allowed**｜`ENV-FOG-02`
→ `true` = OUTSIDE；`false` = INSIDE；缺失 = OUTSIDE。

### 3.4 目标物 ODC.4（4 条）

**ODC.4.1.1.pedestrian 行人** `qualitative_bool`｜`dynamic.pedestrians_present`｜expect=true｜**not_allowed**｜`DYN-VRU-01`
→ `true` = OUTSIDE；`false` = INSIDE；缺失 = OUTSIDE。

**ODC.4.1.2.two_wheeler 两轮 / 三轮车** `qualitative_bool`｜`dynamic.two_wheelers_present`｜expect=true｜**not_allowed**｜`DYN-VRU-03`
→ `true` = OUTSIDE；`false` = INSIDE；缺失 = OUTSIDE。

**ODC.4.1.3.animal 动物（>0.3 m）** `numeric_range`｜`dynamic.animals_over_0_3m`｜`op <=`，`thr=0.0`，`band=0.0`｜要求 allowed｜`DYN-ANM-01`

| 区间 | 判决 |
|---|---|
| `v ≤ 0.0` | INSIDE |
| `v > 0.0` | OUTSIDE（`band=0` ⇒ **无边界带**，不可能 BOUNDARY） |

**ODC.4.1.4.obstacle 障碍物（>0.3 m）** `numeric_range`｜`dynamic.obstacles_over_0_3m`｜`op <=`，`thr=0.0`，`band=0.0`｜要求 allowed｜`DYN-STA-01`
→ 同上：`v ≤ 0` = INSIDE；`v > 0` = OUTSIDE；无边界带。

### 3.5 用户状态 ODC.5（4 条）

**ODC.5.1.1.seatbelt 安全带** `qualitative_bool`｜`vehicle.seatbelt_on`｜expect=**false**｜要求 **not_allowed**｜`ODC-BELT-001`
→ 禁止条件 = "未系安全带"：`false`（未系）= OUTSIDE；`true`（已系）= INSIDE；缺失 = OUTSIDE。

**ODC.5.1.2.driver_in_seat 驾驶员在位** `qualitative_bool`｜`vehicle.driver_in_seat`｜expect=true｜要求 allowed｜`ODC-SEAT-001`
→ `true` = INSIDE；`false` = OUTSIDE；缺失 = OUTSIDE。

**ODC.5.1.3.eyes_closed 闭眼 / 头部不动时长** `numeric_range`｜`vehicle.driver_eyes_closed_s`｜`op <=`，`thr=30.0`，`band=5.0`｜要求 allowed｜`ODC-DMS-001` / `ODC-DMS-NEAR`

| 区间 | 判决 | remaining_margin |
|---|---|---|
| `v ≤ 25.0` | INSIDE | `30 − v` |
| `25.0 < v ≤ 30.0` | BOUNDARY | `30 − v`（0 ~ 5） |
| `v > 30.0` | OUTSIDE | `30 − v`（负） |
| 端点 `v = 30.0` | BOUNDARY（余量 0） | 0.0 |
| 端点 `v = 25.0` | INSIDE | 5.0 |

**ODC.5.1.4.driver_attention 驾驶员状态正常** `qualitative_bool`｜`vehicle.driver_attention_ok`｜expect=true｜要求 allowed｜`ODC-DMS-002`
→ `true` = INSIDE；`false` = OUTSIDE；缺失 = OUTSIDE。

### 3.6 系统状态 ODC.6（4 条）

**ODC.6.1.1.map_coverage 导航地图覆盖** `qualitative_bool`｜`vehicle.map_coverage`｜expect=true｜allowed｜`ODC-MAP-001`
→ `true` = INSIDE；`false` = OUTSIDE；缺失 = OUTSIDE。

**ODC.6.1.2.ads_fault 无 ADS 故障** `qualitative_bool`｜`vehicle.ads_fault`｜expect=**false**｜allowed｜`ODC-FAULT-001`
→ `false`（无故障）= INSIDE；`true`（有故障）= OUTSIDE；缺失 = OUTSIDE。

**ODC.6.1.3.dssad_ok DSSAD 正常** `qualitative_bool`｜`vehicle.dssad_ok`｜expect=true｜allowed｜`ODC-DSSAD-001`
→ `true` = INSIDE；`false` = OUTSIDE；缺失 = OUTSIDE。

**ODC.6.1.4.dms_ok DMS 正常** `qualitative_bool`｜`vehicle.dms_ok`｜expect=true｜allowed｜`ODC-DMS-SYS-001`
→ `true` = INSIDE；`false` = OUTSIDE；缺失 = OUTSIDE。

### 3.7 传感器状态 ODC.7（5 条）

**ODC.7.1.1.camera_degraded 摄像头退化** `qualitative_bool`｜`sensors.camera_degraded`｜expect=true｜**not_allowed**｜`PER-DEG-01`
→ `true` = OUTSIDE；`false` = INSIDE；缺失 = OUTSIDE。

**ODC.7.1.2.lidar_degraded 激光雷达退化** `qualitative_bool`｜`sensors.lidar_degraded`｜expect=true｜**not_allowed**｜`PER-DEG-02`
→ `true` = OUTSIDE；`false` = INSIDE；缺失 = OUTSIDE。

**ODC.7.1.3.camera_confidence 摄像头置信度** `numeric_range`｜`sensors.confidence_camera`｜`op >=`，`thr=0.6`，`band=0.05`｜要求 allowed｜`PER-CONF-001` / `PER-CONF-NEAR`
→ INS `v ≥ 0.65`；BND `0.6 ≤ v < 0.65`（端点 0.6 = BOUNDARY，0.65 = INSIDE）；OUT `v < 0.6`；missing → OUTSIDE。

**ODC.7.1.4.lidar_confidence 激光雷达置信度** `numeric_range`｜`sensors.confidence_lidar`｜`op >=`，`thr=0.6`，`band=0.05`｜要求 allowed｜`PER-CONF-002` / `PER-CONF-NEAR`
→ 同 7.1.3：INS `v ≥ 0.65`；BND `[0.6, 0.65)`；OUT `v < 0.6`。

**ODC.7.1.5.robc 综合运行置信度** `numeric_range`｜`sensors.robc`｜`op >=`，`thr=0.6`，`band=0.05`｜要求 allowed｜`PER-ROBC-001` / `PER-ROBC-NEAR`
→ INS `v ≥ 0.65`；BND `[0.6, 0.65)`；OUT `v < 0.6`（ROBC 低分 → 该元素 OUTSIDE → 聚合 `mrm_or_refuse`，即 profile 级 fail-safe，对应感知侧 `out/robc`）；
缺失 → **UNDEFINED**（`missing_policy.by_element`，`MISSING-POLICY-UNDEFINED` — IQSM 通道未接时保守未决，不判越界）。
阈值 0.6/band 0.05 与同组 confidence 规则同口径，**占位待 IQSM 确认**。

---

## 4. 定性规则真值表汇总

### 4.1 枚举规则（2 条，判定优先级 `allowed` > `boundary` > `forbidden` > 未知）

| element_id | allowed | boundary | forbidden | 未知值 | 缺失 |
|---|---|---|---|---|---|
| ODC.1.1.1.road_type | `expressway_main`, `highway_main` | —（无，故无 BOUNDARY） | 9 个非高速/快速路取值 | 视同缺失 → UNDEFINED† | UNDEFINED† |
| ODC.3.1.3.snow_level | `none`, `light` | `moderate` | `heavy`, `blizzard` | 视同缺失 → OUTSIDE | OUTSIDE |

枚举规则的通用映射（`requirement=allowed`）：命中 allowed → INSIDE；命中 boundary → BOUNDARY；命中 forbidden → OUTSIDE；**未命中任何集合（未知取值）→ 视同缺失，按第 6 节回退**（byd_tjp：道路组命中 `missing_policy` → UNDEFINED†；环境组如 snow_level 无策略命中 → restrictive 下 OUTSIDE）。

若 `requirement=not_allowed`：命中 forbidden/boundary/未知的处理先按上表得出原始状态，再整体对调（INSIDE↔OUTSIDE）。schema 为此约束了两种合法配置形态，消除歧义：

- `requirement=allowed` → **必须**给 `allowed_values`（可附 forbidden/boundary，三集合两两不重叠）；此时"未命中任何集合"= 无法确认合规 → 视同缺失。
- `requirement=not_allowed` → **必须**给 `forbidden_values`，且**不得**给 `allowed_values`；此时"不在禁止清单内" = 合规 → INSIDE（对调后），不存在"未知值"概念。
- 两种形态互斥由 `validate` 强制（`must not define` / `needs allowed_values` 报错）。

### 4.2 布尔规则（24 条，二值、无边界带）

| 判决 | `allowed` + expect=T | `allowed` + expect=F | `not_allowed` + expect=T | `not_allowed` + expect=F |
|---|---|---|---|---|
| 观测 = true | INSIDE | OUTSIDE | **OUTSIDE** | INSIDE |
| 观测 = false | OUTSIDE | INSIDE | INSIDE | **OUTSIDE** |
| 观测缺失 | 按第 6 节（本 profile → OUTSIDE） | 同左 | 同左 | 同左 |

本 profile 中的分布：

| 组合 | 数量 | element_id |
|---|---|---|
| allowed + expect=T | 7 | 1.1.2 运行区域、1.3.1 标线清晰、5.1.2 在位、5.1.4 状态正常、6.1.1 地图覆盖、6.1.3 DSSAD、6.1.4 DMS |
| allowed + expect=F | 1 | 6.1.2 无 ADS 故障 |
| not_allowed + expect=T | 15 | 1.3.2 无标线、1.4.1～1.4.8（路口/环岛/匝道/收费站/铁路/施工/事故/管制）、3.1.5 眩光、3.1.6 雾、4.1.1 行人、4.1.2 两轮车、7.1.1 摄像头退化、7.1.2 激光雷达退化 |
| not_allowed + expect=F | 1 | 5.1.1 安全带 |

合计 7 + 1 + 15 + 1 = **24 条布尔规则**（42 总数 − 16 数值 − 2 枚举 = 24，交叉核对一致）。

默认（未配置置信度）时布尔规则**严格两态，不产生 BOUNDARY**。可选置信度判别（schema 强制三字段成组出现，且仅允许在 `qualitative_bool` 上）：

```json
{"rule_type": "qualitative_bool", "observation_key": "a.flag", "expect": true,
 "confidence_threshold": 0.7, "confidence_band": 0.1, "confidence_observation_key": "a.score"}
```

仅当**观测与 expect 失配**时启用（匹配恒为 INSIDE，不读置信度）：

| 置信度 `c` | 原始判决 | 说明 |
|---|---|---|
| `c ≥ threshold` | OUTSIDE | 可信失配 → 越界 |
| `threshold − band ≤ c < threshold` | BOUNDARY | 临界带 → 告警 |
| `c < threshold − band` | 视同缺失 | 数据不可靠 → 按第 6 节回退（restrictive → OUTSIDE） |
| 置信度键缺失 / 非有限值 | 视同缺失 | 同上 |

观测值类型：接受 JSON 布尔与数值 `0`/`1`；**其他类型（含字符串 `"false"`）一律视同缺失**（不再做 `bool()` 真值化），按第 6 节回退。

---

## 5. 数值规则边界值速查总表（17 条）

| # | element_id | 运算符 | 阈值/区间 | band | INSIDE | BOUNDARY | OUTSIDE | 缺失 |
|---|---|---|---|---|---|---|---|---|
| 1 | ODC.1.2.1.curve_radius 曲率半径 | `>=` | 200.0 | 20.0 | `≥220` | `[200,220)` | `<200` | UNDEFINED† / SKIPPED* |
| 2 | ODC.1.2.2.longitudinal_grade 纵坡 | `between` | [−9, 9] | 0.9 | `[−8.1,8.1]` | `[−9,−8.1)∪(8.1,9]` | `<−9 ∨ >9` | UNDEFINED† |
| 3 | ODC.1.2.3.cross_slope 横坡 | `between` | [−2, 2] | 0.2 | `[−1.8,1.8]` | `[−2,−1.8)∪(1.8,2]` | `<−2 ∨ >2` | UNDEFINED† |
| 4 | ODC.1.2.4.lane_width 车道宽度 | `between` | [2.5, 5.5] | 0.2 | `[2.7,5.3]` | `[2.5,2.7)∪(5.3,5.5]` | `<2.5 ∨ >5.5` | UNDEFINED† |
| 5 | ODC.2.1.1.speed 运行速度 | `between` | [0, 80] | 3.0 | `[3,77]` | `[0,3)∪(77,80]` | `<0 ∨ >80` | OUTSIDE |
| 6 | ODC.2.1.2.activation_speed 激活速度 | `between` | [0, 80] | 3.0 | `[3,77]` | `[0,3)∪(77,80]` | `<0 ∨ >80` | OUTSIDE |
| 7 | ODC.2.1.3.lat_accel 横向加速度 | `between` | [−2, 2] | 0.2 | `[−1.8,1.8]` | `[−2,−1.8)∪(1.8,2]` | `<−2 ∨ >2` | OUTSIDE |
| 8 | ODC.2.1.4.lon_accel 纵向加速度 | `between` | [−10, 2] | 0.5 | `[−9.5,1.5]` | `[−10,−9.5)∪(1.5,2]` | `<−10 ∨ >2` | OUTSIDE |
| 9 | ODC.3.1.1.visibility 能见度 | `>=` | 200.0 | 30.0 | `≥230` | `[200,230)` | `<200` | OUTSIDE |
| 10 | ODC.3.1.2.rain_intensity 降雨强度 | `<=` | 14.9 | 1.5 | `≤13.4` | `(13.4,14.9]` | `>14.9` | OUTSIDE |
| 11 | ODC.3.1.4.illumination 环境照度 | `>=` | 50.0 | 10.0 | `≥60` | `[50,60)` | `<50` | OUTSIDE |
| 12 | ODC.4.1.3.animal 动物计数 | `<=` | 0.0 | 0.0 | `≤0` | 无带 | `>0` | UNDEFINED† |
| 13 | ODC.4.1.4.obstacle 障碍物计数 | `<=` | 0.0 | 0.0 | `≤0` | 无带 | `>0` | UNDEFINED† |
| 14 | ODC.5.1.3.eyes_closed 闭眼时长 | `<=` | 30.0 | 5.0 | `≤25` | `(25,30]` | `>30` | OUTSIDE |
| 15 | ODC.7.1.3.camera_confidence 摄像头置信度 | `>=` | 0.6 | 0.05 | `≥0.65` | `[0.6,0.65)` | `<0.6` | OUTSIDE |
| 16 | ODC.7.1.4.lidar_confidence 激光雷达置信度 | `>=` | 0.6 | 0.05 | `≥0.65` | `[0.6,0.65)` | `<0.6` | OUTSIDE |
| 17 | ODC.7.1.5.robc 综合运行置信度 | `>=` | 0.6 | 0.05 | `≥0.65` | `[0.6,0.65)` | `<0.6` | UNDEFINED† |

\* 曲率半径在 `applies_when`（road_type ∈ 高速/快速路主路）为假时 **SKIPPED**（`applies_when` 先于缺失回退）；road_type 合规而曲率半径键缺失时按 † 走 UNDEFINED。
† `missing_policy` 命中（`by_tag road/scenery/dynamic` 或 `by_element ODC.7.1.5.robc`）→ **UNDEFINED**（`MISSING-POLICY-UNDEFINED`，不参与聚合，来源记入 `policy_source`）；其余元素缺失仍按 restrictive → OUTSIDE。

区间端点约定（详见 2.1/2.2）：**区间内侧的带边缘（如 3、77、2.7、±1.8、±8.1）归 INSIDE**（fp 容差保护）；**阈值与区间外端点（200、14.9、0、80、±2、±9、±10…）归 BOUNDARY**。

---

## 6. 缺失观测回退矩阵

优先级从高到低：

1. 元素 `requirement = undefined` → `UNDEFINED`（`UNDEFINED-REQ`），永不读观测。
2. 元素 `undefined_as`：
   - `allowed` → **INSIDE**（静默，无 reason_code）；
   - `not_allowed` → **OUTSIDE**（`UNDEFINED-AS-NOT-ALLOWED`）；
   - `undefined` → **UNDEFINED**（`UNDEFINED-AS-UNDEFINED`，不参与聚合）。
3. profile `missing_policy`（`by_element` → `by_tag` → `default`；byd_tjp 已配置）：
   - `by_tag road/scenery/dynamic` → **UNDEFINED**（`MISSING-POLICY-UNDEFINED`，道路/目标物组 20 条，不参与聚合，来源记入 `policy_source`）；
   - `by_element ODC.7.1.5.robc` → **UNDEFINED**（IQSM 通道未接时未决）；
   - `default: "mode"` → 落到下一级 `definition_mode`。
4. profile `definition_mode`（byd_tjp = `restrictive`）：
   - `restrictive` → **OUTSIDE**（`UNDEFINED-STRICT`）；
   - `permissive` → INSIDE（`UNDEFINED-PERMISSIVE`）；
   - `default` → UNDEFINED（`UNDEFINED-DEFAULT`，不参与聚合）。

以下情况**视同观测缺失**，走上列回退：

5. 数值规则：观测键缺失、非数字字符串（如 `"N/A"`）、**非有限数值（`NaN` / `±inf`）**。
6. 布尔规则：观测键缺失、**非布尔类型**（字符串 `"false"`、`2`、对象等；数值 `0`/`1` 合法）。
7. 枚举规则（`requirement=allowed` 形态）：观测键缺失、**未命中任何取值集合的未知值**。
8. 布尔置信度判别（失配分支）：置信度键缺失、非数值或非有限值、`c < threshold − band`。

不走缺失回退的两类：

9. `applies_when` 中引用的键缺失 → 该叶子为假 → 规则 **SKIPPED**（`CONDITIONAL-SKIP`）。
10. 元素 `requirement = undefined` → `UNDEFINED-REQ`（见第 1 条）。

byd_tjp（restrictive + missing_policy）下 43 条规则的缺失结论：**道路/目标物组 20 条 + ROBC 1 条 → UNDEFINED（命中 missing_policy），其余 22 条 → OUTSIDE（restrictive）；曲率半径在 road_type 缺失/不合规时 → SKIPPED（applies_when 先于缺失回退）**。映射层配套：检测出现未知类别时 `dynamic.*` 整组不产出（见 suite `dynamic_rollup`），恰由 `by_tag dynamic` 承接为 UNDEFINED。

---

## 7. 聚合、建议与开关

**聚合**（`aggregate.aggregate`）：

- 参与状态：`INSIDE` / `BOUNDARY` / `OUTSIDE`；`UNDEFINED`、`SKIPPED` 剔除后取最差；
- 无参与规则 → 整体 `UNDEFINED`；
- 全部规则被开关关闭 → 结果同上（`UNDEFINED` → `continue`）。

| 整体状态 | severity | recommendation |
|---|---|---|
| INSIDE | info | `continue` |
| BOUNDARY | warning | `warn_driver` |
| OUTSIDE | critical | `mrm_or_refuse` |
| UNDEFINED | info | `continue` |

**理由列表**：`outside_reasons` = 每条 OUTSIDE 规则的 `预警码: 中文消息`；`boundary_reasons` = 每条 BOUNDARY 规则（仅当 `boundary_warnings_enabled=true`）。

**开关**（`api.SwitchPolicy`，判定顺序即优先级）：

| 开关 | 命中效果 |
|---|---|
| `global_enabled=false` | 全部规则 → `skipped`，整体 `UNDEFINED` |
| `by_element[element_id]=false` | 单条规则 → `skipped` |
| `by_rule_type[type]=false` | 同类型全部 → `skipped` |
| `by_tag[tag]=false` | 命中标签的规则 → `skipped`（规则任一标签命中即跳过） |
| `boundary_warnings_enabled=false` | `boundary_reasons` 清空，**整体状态由 BOUNDARY 降为 INSIDE**（recommendation 随之变 `continue`），但 `results[]` 中各规则仍保留 BOUNDARY 原值（实测：curve_boundary 样例整体 INSIDE、仍有 5 条 per-rule BOUNDARY） |

关闭的规则记入 `skipped[] = {element_id, reason}`，不参与聚合。

**报告字段 `active_switches`**：列出**实际生效（非默认）**的开关项，如 `by_element[ODC.3.1.2.rain_intensity]=false`、`boundary_warnings_enabled=false`；全默认时为空列表 `[]`。

---

## 8. 遗留限制与设计注意点（非缺陷）

以下条目为**有意保留或待产品决策**的事项；原"已知实现偏差"中影响判决正确性的缺陷（带端点不一致、`!=` 无边界、NaN 无防护、置信度死配置、`undefined_as` 无效、枚举未知值分叉、schema 缺口、mock 脱节、CLI 退出码、合并优先级、`active_switches` 语义）已全部修复并有测试覆盖。

1. **速度低速端（设计决策）**：`[0,80]` + band 3 ⇒ `v ∈ [0,3)`（含停车 0 km/h）为 BOUNDARY，TJP 拥堵停走会常态告警——如需"停车属域内"应改 profile（例如低速端不设带、或单独规则放行），属配置调整而非代码缺陷。
2. **注册表元素绕过重复检查（P2）**：`register_element` 追加发生在 `validate_profile_dict` 之后，注册的 `element_id` 仍可能与 profile 内重复（重复 id 会被评估两次，不改变最差态聚合结果）。
3. **保留未接线的配置字段（预留扩展）**：开关项 `boundary_severity`、`on_switch_mismatch`，规则字段 `qualifier`、`relation`、`road_rule_match` 目前加载但不参与评估。
4. **`==` / `!=` 的容差带为闭合语义**：带边缘归 BOUNDARY（与序关系算子的"带边缘归 INSIDE"相反），这是比较类算子的固有语义（见 2.1），非缺陷。
5. **布尔置信度仅在失配时生效**：观测与 expect 匹配时恒为 INSIDE，不读置信度；如需"低置信匹配也告警"需另行设计。
6. **pytest 提示 `Unknown config option: pythonpath`**：系统 pytest 6.2.5 不支持 `pyproject.toml` 的 `pythonpath` 键（pytest ≥7 才支持），仅为告警，测试仍通过（依赖以项目根目录运行）。

## 9. CLI 退出码（`python -m odd_judge evaluate`）

| 退出码 | 含义 | 对应状态 / 建议 |
|---|---|---|
| `0` | 域内（或 UNDEFINED / 全部 SKIPPED） | `INSIDE` → `continue` |
| `1` | 临近边界 | `BOUNDARY` → `warn_driver` |
| `3` | 越界 | `OUTSIDE` → `mrm_or_refuse` |
| `4` | 输入 / 配置 / 运行时错误（信息打到 stderr，带 `ERROR:` 前缀，无堆栈） | — |
| `2` | argparse 参数解析错误（保留值） | — |

`validate` 子命令：`0` 合法 / `1` 内容非法（逐条列出错误） / `4` 文件不可读。多帧 `--stream` 取全部帧中最差状态对应码。

