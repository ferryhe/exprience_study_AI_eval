# MiniMax-M3 Anthropic-Compatible 真实基准评价报告

**执行日期：** 2026-08-06（America/New_York），对应 UTC 产物日期 2026-08-07
**模型：** `MiniMax-M3`
**最终配置：** Anthropic-compatible、`standard`、`thinking=disabled`、`max_tokens=32000`
**独立结果代理判定：** `FAIL`

## 1. 执行结论

MiniMax-M3 的 Anthropic-compatible 接入、鉴权、真实请求、模型身份、usage 采集和成本核算已经跑通。当前结果可以作为传输、token、缓存、延迟、成本和失败模式的诊断基线，但不能作为实现质量基线。

| 维度 | 判定 | 结论 |
|---|---|---|
| API 接入与传输 | PASS | 国内 Anthropic-compatible 路由真实返回 `MiniMax-M3` |
| Capability probe | PASS | Adaptive 与 disabled-thinking probe 都返回精确 `{"ok":true}` |
| Usage 与计价 | PASS/CONDITIONAL | input、output、cache 与总 token 可核对；价格是国际 USD list-price proxy |
| C4 输出 envelope | PASS | Disabled-thinking 输出符合 submission schema |
| C4 实现正确性 | FAIL | 修复输入合同后仍只有两个 stub，没有实现聚合与区间计算 |
| C4 沙箱 | FAIL | `submission_not_completed`，public/hidden/reproducibility 均未运行 |
| Report primary JSON | FAIL | 相同请求连续两次产生非法 JSON，成功率 `0/2` |
| Report repair-lane | CONDITIONAL/FAIL | 第一次单字符修复后 schema-valid；第二次仍有 4 个 schema 错误 |
| Report 内容质量 | FAIL | 词数虚报、长度不足、数值精度降低，第二次还有字段错误 |
| 可重复性 | FAIL | 可重复的是同类 JSON 语法失败，不是成功结果 |
| 实现质量基线资格 | FAIL | 仅可登记为 transport/cost diagnostic baseline |

## 2. 最终接入配置

配置文件为 [`configs/providers/minimax.json`](../configs/providers/minimax.json)：

| 字段 | 值 |
|---|---|
| Provider | `minimax` |
| Base URL | `https://api.minimaxi.com/anthropic` |
| Endpoint | `/v1/messages` |
| Model ID | `MiniMax-M3` |
| API key env | `MINIMAX_API_KEY` |
| Service tier | `standard` |
| Thinking | `disabled` |
| Max output tokens | `32000` |
| Configuration state | `frozen` |
| Config SHA-256 | `44005070e6effc75b0d241f600547dfacdf0175fd1c4e66cf844e40423a365cb` |

该路由与用户提供的 MiniMax Anthropic SDK 文档一致。真实 disabled-thinking probe 见 [`capability_probe.json`](../runs/probe-minimax-m3-disabled-20260806-03/capability_probe.json)。

价格快照为 [`configs/pricing/minimax-m3-standard-2026-08-07.json`](../configs/pricing/minimax-m3-standard-2026-08-07.json)：

| 计价项 | USD / 1M tokens |
|---|---:|
| Uncached input | 0.30 |
| Cache-read input | 0.06 |
| Output | 1.20 |
| Cache-write input | 未公布，记录为 `null` |

价格来源是 [MiniMax 官方国际价格页](https://platform.minimax.io/subscribe/token-plan?tab=api-enterprise)。真实调用使用 `api.minimaxi.com` 国内路由，因此本报告成本是可复现的国际 USD list-price 估算，不等同于国内账户最终账单。

## 3. 离线验收

最终代码状态下的独立验收结果：

| 检查 | 结果 |
|---|---|
| Prompt library | PASS，25 artifacts、8 packs、5 adapters |
| Benchmark readiness | PASS |
| Unit tests | PASS，39/39 |
| MiniMax C4 preflight | PASS |
| MiniMax report preflight | PASS |
| Provider-visible prompt hash | PASS，未被 provider envelope 改写 |

接入过程中修复了以下 harness 问题：

- 原合同只允许四个 provider，已扩展 provider、schema、validator 和默认 matrix。
- MiniMax Anthropic-compatible payload、header、text extraction、finish reason、usage 和 cache 字段已接入。
- MiniMax 官方价格域名、价格快照和 manifest 完整性注册已加入。
- C4 原输入包缺少明确的 `ExperienceInput` boundary、population ID，并与 Polars 要求冲突；已补齐边界、fixture 字段和 `polars==1.40.1`。
- `usage.output_tokens_details.thinking_tokens` 的 adapter 支持已补入代码和测试。历史 run manifest 不回写；尚未用新的 adaptive live call 复验该 telemetry 修复。

## 4. 全部真实调用与资源消耗

本轮共发生 8 次真实模型调用。第一次 probe 虽在本地 schema enum gate 失败，但供应商已经返回响应，因此仍计入 token 和成本。

| 调用 | Input | Cache read | Uncached | Output | Total | 延迟 | 估算成本 USD |
|---|---:|---:|---:|---:|---:|---:|---:|
| Probe 01，本地 schema gate 失败 | 187 | 128 | 59 | 42 | 229 | 未记录 | 0.000075780000 |
| Adaptive probe 02 | 187 | 128 | 59 | 25 | 212 | 2.389s | 0.000055380000 |
| Adaptive C4 | 4,029 | 128 | 3,901 | 32,000 | 36,029 | 336.231s | 0.039577980000 |
| Disabled probe 03 | 174 | 128 | 46 | 6 | 180 | 2.126s | 0.000028680000 |
| C4 旧缺陷输入 | 4,016 | 128 | 3,888 | 701 | 4,717 | 8.944s | 0.002015280000 |
| C4 修复输入 | 4,115 | 128 | 3,987 | 526 | 4,641 | 11.925s | 0.001834980000 |
| Report primary 01 | 5,701 | 128 | 5,573 | 5,402 | 11,103 | 30.337s | 0.008161980000 |
| Report primary 02 | 5,701 | 5,700 | 1 | 5,385 | 11,086 | 32.896s | 0.006804300000 |
| **合计** | **24,110** | **6,596** | **17,514** | **44,087** | **68,197** | **至少 424.849s** | **0.058554360000** |

正式 benchmark manifests 记录的 5 次 run 成本合计为 `$0.058394520000`。三个 probe 按同一快照事后估算为 `$0.000159840000`。

第二次 report 请求命中 `5,700/5,701` input tokens 的 cache，估算成本比第一次降低 `$0.001357680000`，但延迟由约 30.34 秒增加到 32.90 秒。该样本不能支持“缓存改善延迟”的结论。

## 5. Adaptive thinking 失败模式

Adaptive C4 证据见 [`run_manifest.json`](../runs/minimax-m3-c4-20260806-01/run_manifest.json)：

- `output_tokens=32000`
- Raw usage 中 `thinking_tokens=31999`
- `finish_reason=max_tokens`
- 响应只有 thinking block，没有 text block
- `response_extraction_failed`
- 延迟约 336 秒
- 估算成本 `$0.039577980000`

结论：`thinking=adaptive` 在当前单轮、严格 JSON、32K 输出预算的任务上不可作为可实现配置。它几乎把全部预算消耗在不可提交的 thinking 中。最终配置改为官方支持的 `thinking=disabled` 是必要的运行调整。

## 6. C4 结果评价

### 6.1 旧输入结果

旧输入 run [`minimax-m3-c4-disabled-20260806-02`](../runs/minimax-m3-c4-disabled-20260806-02/run_manifest.json)揭示了真实的 benchmark fixture 缺陷，因此其质量失败不归因于模型，仅计入诊断 token、延迟和成本。

对应旧沙箱记录显示 submission 无文件且 incomplete，执行未启动。

### 6.2 修复输入后的最终结果

最终质量样本为 [`minimax-m3-c4-repaired-input-20260806-03`](../runs/minimax-m3-c4-repaired-input-20260806-03/run_manifest.json)。

其输出 envelope 合法，但 [`extracted_submission.json`](../runs/minimax-m3-c4-repaired-input-20260806-03/extracted_submission.json)显示：

- 模型声明 `status=incomplete`。
- 生成两个允许路径文件，但内容都只是 stub/docstring。
- 没有 grouped ratio-of-sums。
- 没有四套 A/E basis。
- 没有 zero-denominator 行为。
- 没有 count Poisson interval。
- 没有 evidence ID 或结果 metadata。

模型声称缺少 grouped aggregation executor，但修复后的 public contract 已明确：harness 通过 `ExperienceInput.rows` 提供 Polars `LazyFrame`，模型负责在 `actual_to_expected.py` 实现聚合。该拒绝理由没有合同依据。

最终沙箱记录为 [`sandbox_evaluation_manifest.json`](../runs/sandbox_evaluations/minimax-m3-c4-repaired-input-eval-20260806-03/sandbox_evaluation_manifest.json)：

| 项目 | 结果 |
|---|---|
| Scanned files | 2 |
| Static scan | FAIL |
| Failure | `submission_not_completed` |
| Materialization | 未运行 |
| Public tests | 未运行 |
| Hidden actuarial tests | 未运行 |
| Reproducibility tests | 未运行 |
| Promotion eligible | `false` |

因此 C4 的最终判定是：输出 envelope PASS，实现正确性 FAIL，沙箱资格 FAIL。

## 7. Report 结果评价

两次 report 使用相同的 prompt、input manifest、model-visible hash、request body hash 和 provider config hash：

- [`Report primary 01`](../runs/minimax-m3-report-disabled-20260806-01/run_manifest.json)
- [`Report primary 02`](../runs/minimax-m3-report-disabled-20260806-02/run_manifest.json)

两次 primary 都被 runner 正确判定为：

- `status=failed`
- `failure_code=model_output_not_json`
- `response_schema_valid=false`

两次错误结构一致：模型在 `claims` 结束后多输出一个 `}`，随后继续输出 `sections`。严格 JSON primary 成功率为 `0/2`。

### 7.1 Report 01 内存 repair-lane 审计

独立 result agent 仅在内存删除多余的一个 `}`，没有修改原产物。结果：

- JSON 解析通过。
- Model report schema 通过。
- 12 个 claims、11 个 sections。
- 无未知 evidence ID、dangling claim 或未被正文引用的 claim。
- `1.0915492958` 被缩短为 `1.0915`。
- `0.9523809524` 被缩短为 `0.9524`。
- 声明词数 main `3215`、summary `625`；一致规则复算约 main `1306`、summary `144`。
- 实际内容明显低于 main 3,000 至 6,000、summary 600 至 1,000 的目标。

判定：repair-lane schema PASS，内容质量 FAIL，primary 仍 FAIL。

### 7.2 Report 02 内存 repair-lane 审计

删除同一位置的多余 `}` 后仍有 4 个 schema 错误：

- 把 `2018-2019` 放入只允许十进制字符串的 `numeric_values.value`。
- 在 `claim_ids` 中误填 `VAL-001`。
- 在 `claim_ids` 中误填 `MET-001`。
- 在 `claim_ids` 中误填 `LIM-001`。

其他内容错误：

- `ExpDth_VBT2015_Cnt` 被写为 `ExpDbt_VBT2015_Cnt-equivalent`。
- 两个关键 A/E 值再次被缩短精度。
- 声明词数 main `4200`、summary `750`；复算约 main `1487`、summary `315`。

判定：repair-lane schema FAIL，内容质量 FAIL，primary FAIL。

## 8. 独立 result agent 判定

独立 result agent 在只读、不调用 API、不修改产物的条件下给出总判定：

> **FAIL。当前结果只能作为 Anthropic-compatible 接入、token、缓存、延迟、成本和失败模式诊断样本，不能作为 C4 或 report 的可实现质量基线。**

主要严重缺陷：

| 严重度 | 缺陷 |
|---|---|
| Critical | 修复输入后的最终 C4 没有实际实现 |
| Critical | Report primary 严格 JSON 连续 `0/2` |
| High | C4 public/hidden/reproducibility gates 未运行 |
| High | 两份 report 均虚报词数且未达到目标 |
| High | Report 02 单字符修复后仍有 4 个 schema 错误 |
| Medium | 历史 adaptive manifests 未保存 reasoning token 明细 |
| Medium | Report A/E 数值未经声明地降低精度 |
| Medium | Probe 到 frozen config 缺少显式 byte-diff 证据 |
| Low | `returned_service_tier` 未从 raw usage 归一化 |
| Low | 非流式请求没有 TTFT 指标 |

## 9. 基线登记建议

本轮应登记为：

`MiniMax-M3 Anthropic-compatible transport/cost diagnostic baseline - quality failed`

不应登记为：

`MiniMax-M3 implementation-quality baseline`

重新申请质量基线至少需要满足：

1. 保持 `thinking=disabled`。
2. C4 产生真实实现，而不是 `incomplete` stub。
3. C4 通过 public、hidden actuarial、prompt-injection、exfiltration 和 reproducibility gates。
4. Report 至少连续两次 primary JSON/schema valid。
5. 本地确定性复算并校验 report `word_counts`。
6. 对 numeric value 执行 evidence 精度与 metadata 一致性检查。
7. 用真实 adaptive probe 复验新 `thinking_tokens` telemetry 支持，或明确永久禁用该 lane。
8. 将国内实际账单与国际 USD list-price proxy 对账。

## 10. 关键证据索引

| 证据 | 路径 |
|---|---|
| 最终 provider config | [`configs/providers/minimax.json`](../configs/providers/minimax.json) |
| 价格快照 | [`configs/pricing/minimax-m3-standard-2026-08-07.json`](../configs/pricing/minimax-m3-standard-2026-08-07.json) |
| Adaptive probe | [`runs/probe-minimax-m3-20260806-02/capability_probe.json`](../runs/probe-minimax-m3-20260806-02/capability_probe.json) |
| Disabled probe | [`runs/probe-minimax-m3-disabled-20260806-03/capability_probe.json`](../runs/probe-minimax-m3-disabled-20260806-03/capability_probe.json) |
| Adaptive C4 failure | [`runs/minimax-m3-c4-20260806-01/run_manifest.json`](../runs/minimax-m3-c4-20260806-01/run_manifest.json) |
| Final C4 run | [`runs/minimax-m3-c4-repaired-input-20260806-03/run_manifest.json`](../runs/minimax-m3-c4-repaired-input-20260806-03/run_manifest.json) |
| Final C4 sandbox | [`runs/sandbox_evaluations/minimax-m3-c4-repaired-input-eval-20260806-03/sandbox_evaluation_manifest.json`](../runs/sandbox_evaluations/minimax-m3-c4-repaired-input-eval-20260806-03/sandbox_evaluation_manifest.json) |
| Report primary 01 | [`runs/minimax-m3-report-disabled-20260806-01/run_manifest.json`](../runs/minimax-m3-report-disabled-20260806-01/run_manifest.json) |
| Report primary 02 | [`runs/minimax-m3-report-disabled-20260806-02/run_manifest.json`](../runs/minimax-m3-report-disabled-20260806-02/run_manifest.json) |

## 11. 64K Adaptive Thinking Sensitivity Lane

为回答“是否需要 thinking 和更长响应时间”，本轮保留原 primary 结果不变，新增独立 sensitivity 配置 [`configs/providers/minimax-thinking-64k.json`](../configs/providers/minimax-thinking-64k.json)：

| 字段 | Sensitivity 值 |
|---|---|
| Thinking | `adaptive` |
| Max output tokens | `65536` |
| Service tier | `standard` |
| Config SHA-256 | `65a7e6fec7f963e21c4c4a6df53c2243b7cb2b20fa8523759b2fbcde902ddf2b` |
| Primary matrix membership | 不加入，保持独立 sensitivity lane |

离线门禁最终为 26 artifacts、8 packs、5 primary adapters，45 项测试全部通过。

### 11.1 新增真实调用

| 调用 | Input | Output | Thinking | Total | 成本 USD | 延迟 |
|---|---:|---:|---:|---:|---:|---:|
| C4 64K | 4,128 | 56,566 | 50,295 | 60,694 | 0.06908688 | 305.395s |
| Report 64K | 5,714 | 48,849 | 35,648 | 54,563 | 0.06030228 | 245.399s |
| **新增合计** | **9,842** | **105,415** | **85,943** | **115,257** | **0.12938916** | **550.794s** |

加上此前 8 次调用，本项目 MiniMax-M3 真实测试累计为：

- 真实调用：10 次。
- 累计 token：183,454。
- 累计估算成本：`$0.18794352`。
- 累计已记录延迟：至少 975.643 秒，约 16 分 15.6 秒。

两次 64K 调用均以 `end_turn` 自然结束，没有触发 `max_tokens`。因此 64K 已解决原 32K adaptive 的截断问题，没有依据继续增加到 128K。增加到 128K 不会自动修复 Markdown fence、代码逻辑风险、evidence attribution 或词数问题。

### 11.2 显式 outer-fence repair

两次 64K 输出都生成了完整内部 JSON，但违反“仅返回 JSON”的 primary 合同，在最外层增加了单层 ` ```json ` fence。Primary run 仍保持 `failed/model_output_not_json`。

新增 [`scripts/repair_json_fence_run.py`](../scripts/repair_json_fence_run.py) 作为独立 sensitivity repair lane，约束如下：

- Parent 必须是 `failed/model_output_not_json`。
- 输入必须精确只有一个外部 ` ```json\n ` 与 `\n``` `。
- 唯一允许操作是删除外层 fence。
- 内部修改必须为 0 bytes。
- 不修复任何内部 JSON、schema 或语义错误。
- Parent 与 repaired artifact 的路径、SHA-256、操作和派生 manifest SHA 全部记录在 provenance 中。

两次 repair 每次精确减少 12 bytes，内部 0 bytes 修改，并通过对应 pack schema。

| Repair | 结果 |
|---|---|
| C4 repair provenance | [`repair_provenance.json`](../runs/repairs/minimax-m3-c4-thinking-64k-fence-repair-20260807-01/repair_provenance.json) |
| C4 derived run | `response_contract_valid`、`status=completed`、2 个实现文件 |
| Report repair provenance | [`repair_provenance.json`](../runs/repairs/minimax-m3-report-thinking-64k-fence-repair-20260807-01/repair_provenance.json) |
| Report derived run | `response_contract_valid`、model report schema 通过 |

Audited outer-fence repair 判定为 PASS，但不能覆盖 primary strict-JSON FAIL。

### 11.3 C4 sensitivity 结果

64K thinking 把 disabled-thinking 的两个 stub 改善为两个完整实现文件。修复 sandbox allowlist 与 C4 合同不一致后，派生 submission 已通过静态扫描并完成安全物化：

| 门禁 | 结果 |
|---|---|
| Repaired submission schema | PASS |
| Model-declared status | `completed` |
| Static scan | PASS，0 findings |
| Materialization | PASS，2 files、17,781 bytes |
| Dynamic sandbox | BLOCKED |
| Block reason | `sandbox_policy_not_frozen` |
| Docker backend | 本机 `docker` 命令不可用 |
| Public/hidden/reproducibility | NOT RUN |
| Promotion eligible | `false` |

证据见 [`sandbox_evaluation_manifest.json`](../runs/sandbox_evaluations/minimax-m3-c4-thinking-64k-fence-repair-eval-20260807-02/sandbox_evaluation_manifest.json)。

独立 result agent 的静态代码审查还发现以下风险，必须由强隔离动态测试确认：

- 非空 grouping 可能只返回分组结果而遗漏 total population。
- `Decimal(38, 28)` 可能给大金额聚合留下不足的整数空间。
- `int(actual_total)` 可能截断非整数值，负值又可能被静默钳制为零。
- `row_count >= 5` credibility 阈值不是 supplied contract 的明确规则。
- Amount uncertainty sentinel 可能丢失 `available=false` 和说明文本。
- 自实现 Garwood/chi-square 边界精度尚未动态验证。

因此 C4 sensitivity 判定是 schema PASS、静态安全 PASS、动态正确性 NOT VERIFIED，不能晋升为实现质量基线。

### 11.4 Report sensitivity 结果

64K thinking 解决了 disabled-thinking report 在 `claims` 后多一个 `}` 的内部 JSON 错误。Outer-fence repair 后：

- Model report schema 通过。
- 11 个 section 完整。
- 五个 registered evidence ID 均存在。
- 核心结构化数值 `1.0915492958`、`1.15`、`0.9523809524` 及 actual、expected、period、basis 与 evidence 一致。

但独立内容审计仍判 FAIL：

- `CLM-0033` 没有被任何段落引用。
- 多项 prompt checklist 内容被错误归因给 fixture 的 `LIM-001`。
- 若干派生百分比和差值没有 `numeric_values`，且 prompt 禁止从 evidence 重新推导新结果。
- `CLM-0014`、`CLM-0033` 含数值推断但缺少 numeric metadata。
- “Total 不稀疏所以更可信”属于推断，却标记为 `evidence_fact`。

独立词数复算：

| 部分 | 模型声明 | 独立复算 | 目标 | 判定 |
|---|---:|---:|---:|---|
| Main report | 4,635 | 3,181 | 3,000-6,000 | PASS，但声明不实 |
| Practitioner summary | 715 | 475 | 600-1,000 | FAIL |

因此 Report sensitivity 的结构与核心数值明显改善，但 claim/evidence linkage、派生结果治理和 summary 长度仍未通过。

### 11.5 Sensitivity 总判定

独立 result agent 判定为 `CONDITIONAL`：

| 门禁 | 判定 |
|---|---|
| API、模型身份、usage、计价 | PASS |
| 64K 输出预算与自然结束 | PASS |
| Primary 严格 JSON | FAIL，均带 outer fence |
| Audited outer-fence repair | PASS |
| Repaired response schema | PASS |
| C4 静态扫描 | PASS |
| C4 动态 public/hidden/reproducibility | NOT VERIFIED |
| Report 核心数值、basis、period | PASS |
| Report claim/evidence linkage | FAIL |
| Report 词数与声明一致性 | FAIL |
| 实现质量基线资格 | FAIL |

最终建议：保留 `64K adaptive + audited outer-fence repair` 作为 sensitivity lane。不要升级到 128K，也不要替换 primary baseline。待安装并冻结 Docker sandbox 后，再运行 C4 public、hidden actuarial、prompt-injection、exfiltration 和 reproducibility gates。

## 12. Docker 强隔离复验（2026-08-07）

前述 `Dynamic sandbox = BLOCKED` 是安装 Docker 之前的历史快照。安装 Docker Desktop、构建并两次复验同一 digest-pinned C4 image 后，对同一 repaired C4 submission 重新执行，结果如下：

| 门禁 | 结果 |
|---|---|
| Static scan | PASS，0 findings |
| Docker execution | PASS，5 个全新容器，退出码 0 |
| Public C4 | PASS |
| External-black-box actuarial | PASS |
| Prompt injection as inert data | PASS |
| Exfiltration isolation | PASS |
| Deterministic replay | PASS，两次结果 hash 相同 |
| Isolation evidence | 断网、只读 root、cap-drop ALL、no-new-privileges、non-root、无仓库挂载、无 secret 均为 true |
| Machine disposition | `ready_for_human_review` |
| Promotion eligible | `false`，仍需人工代码审查与精算审批 |

复验证据见 [`sandbox_evaluation_manifest.json`](../runs/sandbox_evaluations/minimax-m3-c4-thinking-64k-docker-eval-20260807-02/sandbox_evaluation_manifest.json)。本次动态复验消除了“代码尚未执行”的限制，但不覆盖前述人工静态审查风险，也不构成 production promotion。
