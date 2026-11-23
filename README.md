# 榕桥光学分选试验室换版复盘台

包装产线的分选机换版前，白班登记台架记录和勘误，质量员批准上游给出的响应模型并核对实际挑战工序。白班发行两版站件，夜班验收后可以关站复盘。可沿用时保留原放行结论，需复测时按定稿中的动作顺序执行。后来勘误产生新修订，审计员仍可按旧号追查当班决定。

## 运行

需要 Python 3.11 标准库。控制台物化工程时提供完整回归入口。进入项目目录执行：

```sh
python3 -B check_project.py
python3 -B demo.py
```

演示从 `samples/left.json` 和 `samples/right.json` 录入两版，在临时目录分别建立站库和夜班库。程序关闭并移走站库后复盘，随后追加勘误并签出后续报告，最后在重开的夜班库领取旧号。输出含台架复算、实际定稿和旧号导出。随后演示 `samples/recipes.json` 的分层批准、V2 发行、关站配方签报、依实收件独立复算见证，以及重开夜班库后按号重领配方报告。

## Python API

站端和夜班使用两个独立的 `sqlite3.Connection`。可在重开后重复初始化。初始化与写入在没有调用方事务的连接上进行，各写入 API 自行提交。调用方持有并关闭连接。

| 位置 | 调用 | 返回 |
| --- | --- | --- |
| `runs.store` | `RunStore(station).initialize()` | 初始化试验账 |
| `models.approval` | `initialize_models(station)` | 初始化批准表 |
| `exchange.receipt` | `initialize_receipts(night)` | 初始化实收表 |
| `archive.publish` | `initialize_archive(night)` | 初始化归档、出处表和配方报告表 |
| `runs.intake` | `record_run(store, machine_model, catalog, observations, predecessor_id=None)` | 修订号 |
| `runs.store` | `store.load_revision(revision_id)` | 原修订，含按录入顺序返回的 `observations` |
| `models.approval` | `approve_model(store, revision_id, state_ids, initial, transitions, classification)` | 批准模型号（V1） |
| `models.approval` | `approve_layered_model(store, revision_id, state_ids, layers, transitions, classification)` | 分层批准模型号（V2） |
| `models.replay` | `replay(store, model_id, actions)` | `Outcome` |
| `exchange.issue` | `issue(store, model_id)` | 可用 `to_json()` 传送的 `EvidenceEnvelope`（按批准版自动取 V1/V2） |
| `exchange.receipt` | `receive(night, envelope, expected_model)` | 实收号，接受外层对象或其 JSON |
| `exchange.receipt` | `get_receipt(night, receipt_id)` | 实收件，含固定外层及可复算正文 |
| `review.compare` | `compare_publish(night, left_receipt_id, right_receipt_id)` | V1 定稿号 |
| `review.compare` | `compare_recipe_publish(night, left_receipt_id, right_receipt_id, actions, constraints, tolerance)` | 配方定稿号（V2） |
| `archive.retrieve` | `retrieve(night, report_id)` | 原定稿（V1 或配方），可用 `as_dict()` 查看 |
| `archive.export` | `export_report(night, report_id)` | 确定性 JSON |

`catalog` 将两个或三个不同的公开动作码映射为显示名称。观测以有序 JSON 对象列表提交，每行含登记过的 `action`，其余字段随原行保存。勘误前驱必须是同型号的既有修订。`state_ids` 是一至六个不同的站内字符串编号，其顺序同时确定初态向量、矩阵行和矩阵列。`transitions` 按公开动作码提供矩阵，`classification` 以 `pass`、`fail`、`pending` 三组列出全部状态编号，每个状态恰好出现一次。概率接受整数、整数字符串、分数字符串或 `Fraction`，初态及每行总质量均须为一。样例文件展示完整输入。

以列表或元组提交动作序列。空序列直接汇总初态，重复动作按出现次数执行。`Outcome` 给出 `passed`、`failed`、`pending` 三类 `Fraction`，以及 `is_decidable` 和 `conditional_rate`。末端存在合格或不合格质量时有出判资格，条件率以二者之和为分母。没有出判资格时比例为 `None`，有资格且合格质量为零时比例为 `Fraction(0)`。导出用整数或分数字符串表示有理数。

V1 发行件正文以位置索引表达完整初态、逐动作转移和末状态分类。原始行及私有状态编号留在站库。外层 SHA-256 指纹覆盖版本、型号、批准号、源修订号和确切正文，供交接时核对固定身份。实收要求型号和正文均有效。复盘只读取请求指定的两个实收号，要求型号及公开动作码相同，动作按码对齐。所有有限工序的资格和适用条件率一致时，定稿为 `reuse`。否则为 `retest`，附一条确定性选择并经独立复算确认的工序，以及两侧资格和比例。`actions: []` 表示按初态复测。无出判的比例为 `null`，有出判而零合格的比例为 `"0"`。

非法输入、配对不符和错件引发 `ValueError`。未知修订、批准、实收或定稿号引发 `LookupError`，未知工序动作引发 `ValueError`。签存错误按原 SQLite 异常返回，报告、两条出处及成功记录一并回滚。定稿和导出按号码读取固定归档快照，保留原请求和两件出处顺序。数据库重开、重新初始化和后续勘误均保留既有编号及内容。

## 分层批准与配方复核（V2）

`approve_layered_model` 接受一至三个具名公开层，每层一条按站内 `state_ids` 顺序排列的初态向量，各层共用动作响应表和末状态分类。批准即冻结调用方输入。`issue` 对分层批准发行 `version=2` 件：外层字段与 SHA-256 指纹算法沿用 V1，正文恰有 `layers`、`transitions`、`classification` 三个字段，原始行和站内状态编号不出站。实收拒绝重复 JSON 字段、缺失字段、无效分层和指纹不符；对 V2 实收件可用 `get_receipt(night, receipt_id).body.replay_layer(layer_name, actions)` 独立复算任一层。

`compare_recipe_publish` 要求两件 V2 实收件的型号、公开动作码和层名集合完全一致，层录入顺序和站内状态位置可以不同。`constraints` 为有序 `(系数字典, 上界)` 列表，省略层系数为零，系数和上界允许为负、容差非负；权重落在单位单纯形与约束的交集内，空域报 `ValueError`，允许单点和线段。每侧按层名对齐权重合计合格质量 `P` 与出判质量 `D`，先判零分母（无出判资格，率为空），再求 `P/D`。仅当整个允许域资格处处一致且共同出判配方的率差绝对值不超过容差才签 `reuse`；否则签 `retest`，保存一个可凭实收件复算的合法有理配方、原工序及两侧资格和率。

配方报告使用独立的 `recipe_reports`、`recipe_report_parents` 和 `recipe_publication_receipts` 表，并与 V1 报告共用 `report_identifiers` 号段，因此两类报告号全局不撞。`request` 在两个实收号之外保存请求顺序的 `actions`、`constraints`（编码为 `[系数字典, 上界]`）和 `tolerance`；有理数用约分字符串表示，无出判比例为 `null`，有资格零率为 `"0"`。`retrieve` 和 `export_report` 按号同时支持两类报告。V1 发行格式、`compare_publish` 及旧报告行为保持不变。完整输入输出契约见 `RECIPES.md`，端到端样例见 `samples/recipes.json`。
