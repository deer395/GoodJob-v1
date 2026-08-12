# Phase 3B 邮件理解评测集

这是 12 封完全虚构、脱敏的招聘邮件标准题；不读取邮箱、不写数据库，也不包含真实邮件正文。它覆盖初筛/笔试、面试、Offer、拒信、补材料、提醒、改期/取消、多事件、模糊邮件、广告排除和提示注入文本。

先运行稳定检查（不调用模型）：

```powershell
D:\ANACONDA\python.exe evaluation\phase3b_email_understanding\run_eval.py
```

它验证本地候选筛选与证据句提取。若要评估当前配置的真实模型，才主动运行：

```powershell
D:\ANACONDA\python.exe evaluation\phase3b_email_understanding\run_eval.py --live
```

`--live` 仅发送虚构案例的标题、发件域名和本地脱敏证据句，仍可能产生 API 费用。输出中的 `proposal_pair_matches`、`time_matches` 和 `valid_evidence_citations` 分别表示事件类型/阶段、明确时间和证据引用的通过数量。真实邮件仍需用户逐项确认；该评测集的作用是让规则、Prompt 或模型配置变化后有可比较的回归结果。
