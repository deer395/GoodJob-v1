# Phase 3A final reliability and independent blind evaluation

状态：**不采纳 LLM 进入无 JD 主排序。** 本轮解决了结构化调用可靠性，但最终独立人工 Eval 未满足所有预先冻结的排序门槛；不再调 Prompt、权重、职业赛道规则或样本标签。

## 可靠性修复

上一轮 24 条独立 Eval 中有 17 条有效结构化结果、6 条 `malformed_response` 与 1 条 `timeout`。当时客户端只保存了统一异常类别，未记录安全的 schema 子类或原始响应，故不能事后还原 6 条的逐条字段值。

可以从代码路径确定：那 6 条已经通过 JSON 解析，失败发生在严格 `ScreeningResult` 校验，因此不是 JSON code fence 或 JSON 语法错误。可能的历史子类是缺字段、非法 enum、额外字段或类型不符；原实现没有 `finish_reason`，也无法判断是否为“合法但不完整”的截断输出。

修复后：

- DeepSeek V4 Flash 使用官方 strict function schema；只传输 `role_family`、`relation_to_target_track`、`confidence`；
- 默认 thinking mode 与 forced `tool_choice` 会导致 HTTP 400：`Thinking mode does not support this tool_choice`。改为该 Provider 官方支持的 non-thinking transport；模型、职业赛道问题与评分规则未变；
- 增加 `max_tokens=180`、`finish_reason=length` 检查，以及 code fence、缺字段、非法 enum、非法置信度、空内容、JSON parse、缺 tool call 等分类；
- 仅对可修复的格式类失败进行一次有限重试；任何失败仍为 adjustment = 0，严格保留 baseline。

12 条未参与任何人工 Eval 的真实岗位被作为可靠性样本，只读运行且不写缓存或数据库：

| 指标 | strict 修复前 | strict 修复后 |
| --- | ---: | ---: |
| 有效结构化响应 | 0 / 12 | 12 / 12 |
| Provider error | 12 | 0 |
| malformed / timeout | 0 / 0 | 0 / 0 |
| 有效返回率 | 0% | 100% |
| 总耗时 | 3.69 秒 | 18.32 秒 |

修复前的 12 次失败均为 Provider 协议拒绝（HTTP 400），不是语义分类错误。修复后的单条耗时为 1.12–2.10 秒。

## 最终独立人工 Eval

样本文件：`evaluation/phase3a_reliability_final/human_review_blind.csv`。16 条真实岗位均未出现在此前两轮人工 Eval 或 12 条可靠性样本中。用户独立填写标签：priority 3 有 1 条、2 有 6 条、1 有 6 条、0 有 3 条。标签没有被修改。

在冻结的 `screening-v3-strict-schema`、DeepSeek V4 Flash、baseline 和有限调整规则下，16 / 16 得到有效结构化结果；无 timeout、malformed 或 Provider error，全部耗时 20.39 秒。

| 指标 | baseline | revised candidate |
| --- | ---: | ---: |
| Spearman（与人工 priority） | 0.369 | 0.561 |
| Top-10 中 priority 2/3 | 7 / 10（70%） | 7 / 10（70%） |
| Top-10 false high（priority 0） | 0 | 1 |
| Bottom-10 false low（priority 3） | 0 | 0 |

说明：所有 baseline 为 30 的岗位存在大规模并列；Top-10 采用盲评 CSV 的稳定原始顺序作为 tie-break。revised 通过有限调整打破一部分并列，因此 F014（机器人算法/软件方向，人工 priority 0）虽然从 30 降至 27，仍落在 revised 的 Top-10 同分边界内。它不是一次“被抬高”的 LLM 错误，但按预先冻结的 Top-10 计数规则，false high 从 0 变为 1，不能被事后解释或改规则消除。

有可见正向纠偏：F005（含数据/产品类）30 → 33，人工 priority 2；F009（产品类）30 → 33，人工 priority 2；F013（材料/制造方向）30 → 24，人工 priority 0。也有不应被掩盖的负向/不充分纠偏：F004（含数据产品但仍以算法/研发为主）30 → 27，人工 priority 3；F014 虽已下调，仍处于 Top-10 同分边界。

## 决定

结构化调用已达到实际可用稳定性，且 fallback 在全部测试与真实失败路径中保持 baseline 不变。然而最终 Eval 没有同时满足“Top-K 不低于 baseline、False High / False Low 不增加”的全部门槛。因此：

1. 停止无 JD 初筛算法优化；
2. 不调整任何机制来追求指标；
3. 无 JD 岗位的产品主排序应继续以已验证的本地 baseline 为准；
4. 结构化 LLM 能力保留给用户明确触发的单岗位分析；实现上语义缓存不再影响岗位池的 `match_score` 主排序；
5. 本结论不是 Provider 可靠性失败，而是产品排序增益不足以通过冻结验收。

## 工程回归

```powershell
$env:CAMPUSAI_DB_PATH='D:\CODEX\LLMcampus\pytest_phase3a_reliability_final\default.db'
D:\ANACONDA\python.exe -m pytest manual_capture\tests -q --basetemp=D:\CODEX\LLMcampus\pytest_phase3a_reliability_final\cases
```

结果：81 passed，0 failed，1 warning。warning 为现有 `StarletteDeprecationWarning`（TestClient/httpx），与本轮无关。测试全程使用临时数据库。停止规则落地后已再次运行同一完整套件，结果仍为 81 passed，0 failed，1 warning。
