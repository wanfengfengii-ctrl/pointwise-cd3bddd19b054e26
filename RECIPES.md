# 同配方换版复核

## 白班批准与交接

`models.approval.approve_layered_model(store, revision_id, state_ids, layers, transitions, classification)` 返回批准号。`layers` 是含一至三个条目的字典，键是去除首尾空白后仍原样且非空的公开层名，值是按本站 `state_ids` 顺序排列的初态向量。每个向量沿用原初态的概率规则。各层共用本批准版的动作响应表和末状态分类。批准后，改动调用方输入或追加源修订均不影响该批准版。

沿用 `issue`、`receive`、`get_receipt` 和既有初始化入口。`issue` 按指定批准号发行相应版本。分层件使用 `version=2`，采用原外层字段及指纹算法。V2 正文对象恰有 `layers`、`transitions`、`classification` 三个字段，`layers` 把公开层名映射到初态数组，另两项沿用 V1 正文中按位置表达的转移矩阵与分类。传输有理数沿用 V1 约定。实收核对型号、版本、指纹及全部正文，拒绝重复 JSON 字段、缺失字段和无效分层。原始行及站内状态编号不出站。批准和实收各自失败时均无新增记录。

对 V2 实收件调用 `get_receipt(connection, receipt_id).body.replay_layer(layer_name, actions)`，返回已有的 `Outcome`，供夜班按指定工序独立复算任一层。未知层和未知动作报 `ValueError`。V1 实收件的 `body.replay(actions)`、V1 发行格式和原双件复盘沿用原约定。

## 夜班裁决与领取

`review.compare.compare_recipe_publish(connection, left_receipt_id, right_receipt_id, actions, constraints, tolerance)` 返回定稿号。两个号按甲乙顺序指定已实收 V2 件。型号、公开动作码和层名集合必须一致，各版的层录入顺序和站内状态位置可以不同。原 `compare_publish` 继续用于双 V1 件。

`actions` 为列表或元组，按给定顺序执行。允许空工序和重复动作。`constraints` 是有序列表或元组，元素为 `(coefficients, upper)` 对。`coefficients` 是由层名映射到有理系数的字典，省略的已知层系数为零。每一对表示加权系数和小于或等于 `upper`。未知层非法。所有权重非负且和为一，空约束表示完整单纯形。相交为空时报 `ValueError`，允许单点和线段。系数与容差沿用 V1 的精确有理数输入类型，系数和上界允许为负，容差非负。

同一配方在两版上都按层名使用。对各版在指定工序末端按权重合计 `passed` 得到 P，按权重合计 `passed + failed` 得到 D。D 为零表示无出判资格，条件率为空。D 为正时条件率为 P/D。只有整个允许域的出判资格一致、且所有共同出判配方的绝对条件率差都不超过容差，才签 `reuse`。其余情形签 `retest`，提交任一合法有理配方，且在该配方上确有资格不一致或严格超差。

新定稿继续用 `retrieve(connection, report_id).as_dict()` 和 `export_report(connection, report_id)` 读取。沿用原外层报告字段，`request` 在两个原实收号字段之外保存 `actions`、`constraints` 和 `tolerance`。动作与约束按请求顺序保存，约束编码为 `[系数字典, 上界]` 数组。`retest` 在可沿用时为 `null`，需复测时含 `recipe`、`actions`、`left`、`right`。`recipe` 列出所有层名及权重，两侧结构沿用 `eligible` 和 `conditional_rate`。报告中的有理数用约分后的字符串表示，包括有资格的零率 `"0"`，无出判的比例为 `null`。

报告、请求、两条有序出处和成功记录同次提交。非法输入、坏件和不相容配对报 `ValueError`，未知固定号报 `LookupError`。签存失败传递原 SQLite 异常且无部分定稿。后来追加修订、重新初始化或重开数据库后，按号仍领到当时保存的请求、结果及有序父件。V1 旧件和旧报告保持原有格式及行为。

## 样例与运行

`samples/recipes.json` 给出两版的模型输入。用顶层 `machine_model`、`catalog` 和 `observations` 登记各版，右版以左版修订为前驱。按顶层 `actions` 复测。两版 A 层的条件率都是 0，B 层都是 1，C 层均无出判。在 A=B=1/2、C=0 时，甲为 2/3，乙为 1/3。无附加约束或限制 C=1/2 时，容差 1/4 须签 `retest`，容差 1/3 须签 `reuse`。C=1/2 可用 `[( {"C": 1}, "1/2"), ({"C": -1}, "-1/2")]` 表达。在只允许 C=1 的域上，两侧均待定应签 `reuse`。若登记并发行一版用 `right_C_with_zero_rate` 替换右侧 C 初态的件，同一单点请求应签 `retest`，左侧比例为 `null`，右侧为 `"0"`。

现有 `.pointwise-runtime.json` 用版本 1 的 `cli` 清单登记运行入口，`setup` 是准备命令的参数数组列表，`verify` 和 `demo` 各是一条命令的参数数组。将新业务核验接入 `verify`，保留原回归，检查失败须非零退出。`demo` 演示样例关站签报、依实收件复算见证并在重开后按号领报。
