# SOA Experience Study AI Benchmark 操作手册

## 1. 手册目的

本手册用于操作当前仓库中的直接 API benchmark，确保四条 provider route
在相同 prompt、相同 input、相同输出契约和相同执行预算下接受测试，并留下可复核的
token、费用、延迟、失败、生成结果和安全评估记录。

计划比较的 benchmark alias 为：

- `gpt-5.6-sol`
- `claude-opus-5`
- `kimi-k3`
- `deepseek-v4-pro`

这些名称目前是 benchmark alias 和待验证的 requested model ID。只有 capability
probe 返回并确认 effective model ID 后，才能把某条 route 描述为已验证模型。

本手册区分三种不同结论：

1. `response_contract_valid`：API 返回内容通过 JSON、task 和路径契约；不代表代码安全或报告质量合格。
2. `ready_for_human_review`：未来的强隔离执行、安全检查和自动测试全部通过；仍未获得人工批准。
3. `promotion_eligible`：未来的人工代码审核和必要的精算审批完成后，才允许进入 deterministic calculation package。

## 2. 当前状态与可执行边界

截至当前实现状态：

- 基线 commit `f4b0ef8` 已推送到 `origin/main`。
- frozen Docker sandbox 改动在本地工作树中，正式 confirmatory run 前必须审核、提交并保持工作树干净。
- prompt library、provider adapter、API runner、token/cost ledger、synthetic C4 fixture 和 small report fixture 已存在。
- 四个 provider config 均为 `configuration_state=pre_probe`。
- `configs/pricing/pricing_manifest.json` 尚未注册正式价格快照。
- 用户已说明 `.env.local` 中放入了三个 key；程序和本手册不读取或显示 key 值。四模型正式比较必须确认第四条 route 的凭证。
- C4 sandbox policy 已冻结到可复建的 digest-pinned Docker image。
- 本机 Docker Desktop/WSL2 Linux backend 已验证，C4 动态 gate 可执行且不回退到宿主机。
- 完整 SOA data-to-evidence calculation package、生产 evidence bundle、JSON-to-HTML/PDF renderer、hidden actuarial evaluator、人工评分工具和 promotion workflow 尚未完成。

因此当前能够完成的是：离线公平性验证、capability probe、冻结 route 与价格、API
smoke/pilot、报告 JSON 采集、token/cost/latency 比较，以及 C4 生成代码的静态安全比较。
当前不能形成正式 code correctness 排名或最终 SOA 风格 JSON/HTML/PDF 交付结论。

## 3. 数据流与安全边界

```text
Canonical prompt/input
        |
        v
可信 API runner（联网、持有 API key）
        |
        +-- provider raw response
        +-- token / cost / latency / retry ledger
        v
extracted_report.json 或 extracted_submission.json
        |
        +-- 报告：schema、证据和人工质量评估
        |
        `-- 代码：静态扫描 -> 强隔离断网 sandbox -> tests -> 人工/精算审批
```

API runner 可以联网，但不执行模型生成代码。代码 sandbox 不持有 API key，不挂载
`.env.local`、`data/`、gold、hidden expected values 或仓库根目录，也不需要访问模型 API。

## 4. 全流程速查表

| 步骤 | 做什么 | 目的 | 期待结果 | 形成的比较数据 |
|---|---|---|---|---|
| 1 | 冻结实验范围和预算 | 防止测试中途改变规则 | 明确模型、pack、重复次数、预算和停止条件 | 无；形成 preregistration |
| 2 | 安装锁定依赖 | 统一本地执行环境 | 依赖版本与 lock 完全一致 | 环境可重放性 |
| 3 | 运行离线 validator/tests | 验证 prompt、schema、fixture 和 runner | 全部退出码为 0 | 四 route 的 model-visible hash 是否相同 |
| 4 | 运行 capability probe | 验证 route、凭证、model ID 和参数 | 每条 route 返回精确 `{"ok":true}` | 可用性、returned model、probe 延迟/token/重试 |
| 5 | 冻结 provider config 和价格 | 让费用和模型身份可解释 | config 为 `frozen`，价格文件已注册 | 可比较的有效模型和 USD 计价基础 |
| 6 | 单条 route smoke | 小成本验证真实请求链路 | C4 和 report 各产生 schema-valid output | 首次成功、token、费用、延迟、失败原因 |
| 7 | C4 sandbox gate | 静态拦截危险代码并在强隔离容器中测试 | 恶意代码失败；全部机器 gate 通过后进入人工复核 | static/dynamic pass rate、finding 类型 |
| 8 | 四 route pilot matrix | 观察稳定性和成本区间 | 每条 route 获得相同次数输出 | 成功率、延迟、token、费用、重复性 |
| 9 | 报告质量评估 | 比较数字、证据、洞察和治理质量 | 盲审评分与接受/修订决定 | report quality panel、repair time |
| 10 | 强隔离 code evaluation | 比较生成代码的正确性和安全性 | public/hidden/replay 全部有结果 | code quality panel、sandbox failure rate |
| 11 | confirmatory matrix | 产生正式估计而非挑最好样本 | 干净代码树、预注册次数、全部失败保留 | 区间估计、Pareto 比较、接受率 |
| 12 | 形成结论与发布包 | 给出可审计的模型选择 | 原始指标、评分、限制和审批完整 | 主路线、备选路线、成本质量权衡 |

## 5. 步骤 1：冻结实验范围和停止条件

### 操作

在任何付费调用前记录以下内容：

- 使用的 commit hash 和工作树状态；
- provider config 路径与 SHA-256；
- pack ID、input manifest SHA-256 和 model-visible SHA-256；
- pilot 和 confirmatory 重复次数；
- 每条 route 允许的最大请求数和总费用；
- transport retry、timeout、service tier 和 cache lane；
- 报告人工评分阈值和 code security 阻断条件；
- 发生 model ID 变化、价格变化或 schema 变化时的停止规则。

当前 runner 为保证四条 route 的执行位置完全均衡，要求 `--repetitions` 是 provider
数量的整数倍。因此当前可执行建议是：

- pilot：每个模型 4 次，共 16 次 API 请求；
- confirmatory：每个模型 12 次，共 48 次 API 请求。

实施计划中原有的 pilot 3 次和 confirmatory 10 次与当前四 provider 精确位置均衡规则
不兼容。如果必须保留 3/10 次，应先修改、审核并冻结 runner；不要在同一次研究中混用
不同规则。

### 目的

避免看到早期结果后修改模型、prompt、样本数或评分规则，造成选择偏差。

### 期待结果

形成一份冻结的实验登记；confirmatory 开始后不再修改 prompt、input、provider config、
pricing snapshot、重复次数或评分阈值。

### 比较结果

本步骤不产生模型优劣结论，只产生后续比较的共同依据。

## 6. 步骤 2：安装锁定依赖

### 操作

在仓库根目录执行：

```text
python -m pip install -r requirements-benchmark.lock
```

### 目的

让 JSON Schema 验证、runner 和测试使用完全相同的依赖版本。

### 期待结果

命令成功，随后 `validate_benchmark_readiness.py` 不报告 installed dependency 与 lock
不一致。

### 停止条件

依赖无法安装、版本冲突或 lock 被临时修改时，不运行付费 API。

### 比较结果

无模型比较；记录 Python 和依赖版本作为 replay identity。

## 7. 步骤 3：确认凭证边界

### 操作

`.env.local` 只允许出现以下名称：

```text
OPENAI_API_KEY
ANTHROPIC_API_KEY
MOONSHOT_API_KEY
DEEPSEEK_API_KEY
```

确认 `.env.local`、`data/` 和 `runs/` 被 Git 忽略：

```text
git check-ignore -v .env.local data runs
git ls-files .env.local data runs
```

第二条命令应无输出。不要把 key 值打印到终端日志、issue、prompt 或报告中。

### 目的

保证 API runner 可以调用 provider，但生成代码、模型 prompt 和 Git 历史都无法取得凭证。

### 期待结果

- 四条待测 route 各有对应 key；或明确记录哪条 route 因缺少 key 尚未进入四模型比较。
- Git 只显示 ignore 规则，不显示任何被跟踪的秘密或本地数据文件。

### 停止条件

任何 key、`.env.local`、生产 TSV 或 `runs/` 文件被 Git 跟踪时，立即停止并先处理泄露风险。

### 比较结果

凭证是否存在只决定 route eligibility，不属于模型质量分数。

## 8. 步骤 4：运行离线验收

### 操作

```text
python scripts/validate_prompt_library.py
python scripts/validate_benchmark_readiness.py
python -m unittest discover -s tests -v
ruff check src scripts tests
python scripts/run_benchmark.py preflight --pack-id codegen-c4-v1 --input-manifest fixtures/codegen/c4/input_manifest.json
python scripts/run_benchmark.py preflight --pack-id report-v1 --input-manifest fixtures/report/small_evidence/input_manifest.json
```

### 目的

验证 prompt pack、输入文件、provider envelope、schema、cost calculation 和 sandbox
静态 gate 在不调用 API 的情况下内部一致。

### 期待结果

- 两个 validator 输出 `PASS`；
- 所有单元测试和 Ruff 检查通过；
- 每个 preflight 中四条 route 的 `model_visible_sha256` 完全相同；
- C4 和 report pack 各自拥有稳定但不同的 model-visible hash；
- 不产生 `runs/` API response，也不产生费用。

### 停止条件

任一 provider 的 model-visible hash 不同、fixture hash 不匹配、schema 失败或 canary 泄露，
都必须停止。

### 比较结果

此处只比较公平性：四条 route 是否看到了完全相同的 prompt 和 input。不能比较模型质量。

## 9. 步骤 5：执行四条 capability probe

### 操作

probe 是真实、小输出上限的付费 API 调用。按 route 单独执行，便于隔离失败：

```text
python scripts/run_benchmark.py probe --provider-config configs/providers/openai.json --probe-id probe-openai-YYYYMMDD
python scripts/run_benchmark.py probe --provider-config configs/providers/anthropic.json --probe-id probe-anthropic-YYYYMMDD
python scripts/run_benchmark.py probe --provider-config configs/providers/kimi.json --probe-id probe-kimi-YYYYMMDD
python scripts/run_benchmark.py probe --provider-config configs/providers/deepseek.json --probe-id probe-deepseek-YYYYMMDD
```

每次执行后先检查对应的 `runs/<probe-id>/capability_probe.json`，再执行下一条 route。

### 目的

确认：

- key 和 endpoint 可用；
- requested model ID 是否存在；
- provider 实际返回的 model ID/service tier；
- reasoning 参数是否被接受；
- response extraction、usage telemetry、request ID 和 retry ledger 是否工作。

### 期待结果

- `status=accepted`；
- 模型输出精确解析为 `{"ok": true}`；
- 返回或有效 model ID 可以被冻结；
- 记录 input/output/reasoning/cache token、总耗时、重试和 request ID；
- 未提供价格快照时，cost 显示 unavailable/incomplete，而不是零。

### 停止条件

- model not found、参数不支持或 returned model 与预期不一致；
- 任一 route 缺少 key；
- usage 字段无法解释；
- 发生重定向、未登记 endpoint 或其他安全错误。

### 比较结果

形成 provider eligibility 表：

| Route | Probe status | Requested model | Returned/effective model | Reasoning accepted | Probe latency | Tokens | Retries |
|---|---|---|---|---|---:|---:|---:|

probe 只比较 route 可用性和接口行为，不比较报告或代码质量。

## 10. 步骤 6：冻结 provider config

### 操作

根据 capability probe 的实际证据更新每个 `configs/providers/*.json`：

```text
configuration_state = "frozen"
effective_model_id = <probe confirmed ID>
effective_model_reason_code = "capability_probe_confirmed"
version_semantics = "pinned_exact"
capability_probe_date = "YYYY-MM-DD"
```

不要根据营销名称猜 effective model ID。更新后重新计算每个 config 的 byte length 和
SHA-256，并更新 `prompts/prompt_manifest.json` 中对应的 provider registration。

PowerShell 可用于计算文件 hash：

```text
(Get-FileHash -Algorithm SHA256 configs/providers/openai.json).Hash.ToLower()
(Get-Item configs/providers/openai.json).Length
```

随后重新执行两项 validator 和全部单元测试。

### 目的

把“计划测试哪个模型”转换为“实际测试了哪个有效模型”的可审计证据。

### 期待结果

所有 provider config 均通过 frozen-state validation，prompt manifest 中的 config hash
与实际文件一致。

### 停止条件

provider 只能返回浮动 alias、无法说明版本语义或不同 probe 返回明显不同模型时，标记为
`service_as_observed` 研究限制；在确定处理规则前不进入 confirmatory。

### 比较结果

记录每条 route 的身份可重放程度。模型版本不可固定不会自动判质量差，但会降低治理和
reproducibility 结论。

## 11. 步骤 7：建立并注册正式价格快照

### 操作

1. 在测试当天从各 provider 官方价格页面取得与 effective model ID、service tier 匹配的价格。
2. 创建 `configs/pricing/pilot-YYYY-MM-DD.json`。
3. 所有费率使用每百万 token 的十进制字符串；不支持的 cache 类别写 `null`，不能写零。
4. 每个 model entry 记录官方 `source_url`、`effective_at_utc` 和 service tier。
5. 计算文件 byte length/SHA-256，并登记到 `configs/pricing/pricing_manifest.json`。
6. 重新执行离线 validator 和 tests。

不要把 `fixtures/pricing/synthetic_pricing_snapshot.json` 用于真实请求；live loader 会拒绝它。

### 目的

让每次 API 调用的费用能够按当时公开价格重算，并区分未知费用和真实零费用。

### 期待结果

- 价格快照通过 `pricing_snapshot.schema.json`；
- live pricing manifest 注册成功；
- 每条 effective model/service tier 都能找到唯一价格；
- `cost.complete=true` 时才允许使用 `total_usd`。

### 停止条件

价格来源不是官方页面、model/tier 不匹配、价格单位不清或 cache 类别被错误填零。

### 比较结果

形成统一 USD 计价基础。最终同时报告 `known_subtotal_usd`、费用完整性和 provider billing
reconciliation 差异。

## 12. 步骤 8：每条 route 进行单次 smoke

### 12.1 C4 code-generation smoke

以 OpenAI route 为例：

```text
python scripts/run_benchmark.py run --pack-id codegen-c4-v1 --input-manifest fixtures/codegen/c4/input_manifest.json --provider-config configs/providers/openai.json --pricing-snapshot configs/pricing/pilot-YYYY-MM-DD.json --run-id smoke-c4-openai-01 --run-stage pilot
```

对另外三条 route 只替换 provider config 和 run ID。不要修改 pack 或 input。

### 12.2 Small report smoke

```text
python scripts/run_benchmark.py run --pack-id report-v1 --input-manifest fixtures/report/small_evidence/input_manifest.json --provider-config configs/providers/openai.json --pricing-snapshot configs/pricing/pilot-YYYY-MM-DD.json --run-id smoke-report-openai-01 --run-stage pilot
```

### 目的

在启动多次 matrix 前，以最小成本验证完整真实链路、输出上限、schema、usage 和费用。

### 期待结果

每个 run 目录至少包含：

- `run_manifest.json`；
- 每个 transport attempt 的 raw response；
- codegen 的 `extracted_submission.json`，或 report 的 `extracted_report.json`。

理想状态为：

- `status=response_contract_valid`；
- `validation.response_schema_valid=true`；
- returned/effective model 与 frozen config 一致；
- usage integrity 通过；
- cost complete，或明确记录缺失字段；
- 没有因 schema/内容错误自动重试。只有 transport-only retry 被允许。

### 停止条件

任一 route 无法生成契约有效的 C4 或 report 输出、返回模型漂移、价格无法匹配、输出被截断，
或发生不可解释的 usage/cost 差异。

### 比较结果

形成 smoke 表：

| Route | Pack | Contract valid | Attempts | Total elapsed | Input tokens | Output tokens | Reasoning tokens | Cost complete | Total/known cost |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|

`response_contract_valid` 不是 reviewer acceptance；只能证明 API 返回结构可以进入下一阶段。

## 13. 步骤 9：运行 C4 sandbox gate

### 操作

对每个 C4 run 执行：

```text
python scripts/run_benchmark.py evaluate-codegen --run-manifest runs/smoke-c4-openai-01/run_manifest.json --evaluation-id sandbox-c4-openai-01
```

### 目的

验证 extracted submission 未被篡改，先执行静态检测，再把通过的代码放入冻结的强隔离容器：

- 非 allowlist import；
- 网络、subprocess、动态执行和文件 I/O；
- `.env`、API key、gold/canary 探测；
- 非允许文件路径、编码和大小；
- model-declared `incomplete` 或 `blocked` 状态。
- public/外部黑盒精算、prompt-injection、exfiltration-isolation 和确定性 replay gate。

### 期待结果

- 恶意或不合规代码：`static_scan.status=failed`、`machine_disposition=failed`、不创建 subject tree；
- 缺少 Docker backend 或冻结镜像：`machine_disposition=blocked`，绝不在宿主机执行；
- 静态安全且全部动态 gate 通过：`execution.result=passed`、`machine_disposition=ready_for_human_review`；
- 动态 gate 失败：`machine_disposition=failed` 并保留 failure code；
- `promotion_eligible=false`。

基础设施缺失导致的 `blocked` 不是模型失败。静态或动态 gate 失败属于模型输出结果，必须计入
scorecard。

### 停止条件

静态失败后仍产生 subject tree、任何代码在宿主机执行、submission hash 不一致，或 sandbox
能够读取 `.env.local`、gold、hidden expected values、Git 或生产数据。

### 比较结果

可比较：

| Route | Static pass | Public | Hidden | Injection | Exfiltration isolation | Replay | Machine disposition |
|---|---:|---:|---:|---:|---:|---:|---|

## 14. 步骤 10：运行四 route pilot matrix

### 操作

当前四 provider 精确位置均衡使用 4 次 repetition。

C4 pilot：

```text
python scripts/run_benchmark.py matrix --pack-id codegen-c4-v1 --input-manifest fixtures/codegen/c4/input_manifest.json --pricing-snapshot configs/pricing/pilot-YYYY-MM-DD.json --repetitions 4 --batch-id pilot-c4-YYYYMMDD --run-stage pilot
```

Small report pilot：

```text
python scripts/run_benchmark.py matrix --pack-id report-v1 --input-manifest fixtures/report/small_evidence/input_manifest.json --pricing-snapshot configs/pricing/pilot-YYYY-MM-DD.json --repetitions 4 --batch-id pilot-report-YYYYMMDD --run-stage pilot
```

provider configs 未显式传入时，runner 使用登记的四条 route。matrix 会轮换执行位置；不得
删除失败 run 或用“最好的一次”替换 repetition 1。

### 目的

观察 API route 的重复稳定性、失败率、成本和延迟范围，并估计正式 confirmatory 的预算。

### 期待结果

- 每个 batch 产生 `batch_manifest.json`；
- 每条 route 有 4 个 run manifest，共 16 个 run；
- 执行位置循环均衡；
- 所有 transport attempt、重试成本和失败均保留；
- C4 run 随后逐一进入 frozen Docker sandbox gate。

### 停止条件

- model ID/service tier 在 batch 内变化；
- 某 route 连续失败且原因不是暂时 transport error；
- 实际费用明显超过登记预算；
- schema、prompt、input 或 price snapshot 在 matrix 中途变化。

### 比较结果

pilot 至少汇总：

- response-contract-valid rate；
- first-attempt success rate；
- retry rate 和 failure-code 分布；
- median、IQR 和最大 total elapsed time；
- input、uncached、cache-read、cache-write、output、reasoning、total tokens；
- 每个 run 成本、known subtotal 和 cost completeness；
- C4 static pass rate；
- report 初步人工接受率和修订时间。

pilot 用于校准预算和评估流程，不进入 confirmatory 主估计。

## 15. 步骤 11：报告质量评估

### 操作

当前 runner 只生成 schema-valid report JSON；自动 evidence scorer、盲审分配和 HTML/PDF
renderer 尚未实现。在这些工具完成前，使用相同的 reviewer worksheet，并把 provider identity
替换为盲化 ID。

逐项检查：

- material numeric claims 是否与 evidence bundle 完全一致；
- numeric value 的 unit、population、period、basis 是否正确；
- evidence citation precision 和 recall；
- unsupported material claim 数量；
- 关键 actuarial insight 是否被识别；
- limitations、governance 和 unresolved issues 是否完整；
- 11 个固定章节是否清楚、可复核；
- reviewer 是否接受、要求小修、大修或拒绝；
- 人工修复分钟数和修改类型。

### 目的

把“JSON 结构正确”升级为“数值、证据和精算叙述可接受”。

### 期待结果

每份报告有盲化 reviewer score、材料错误清单、接受决定和修复时间。原始模型输出与人工修改版
分开保存，不能覆盖。

### 比较结果

报告质量面板：

| 维度 | 权重 |
|---|---:|
| Numeric claim accuracy | 30 |
| Evidence citation precision/recall | 20 |
| Unsupported-claim control | 15 |
| Useful actuarial insight | 15 |
| Limitations and governance | 10 |
| Clarity and reviewer acceptance | 10 |

建议在 confirmatory 前冻结以下硬门槛：material numeric claim 必须 100% 正确、material
unsupported claim 必须为 0、所有关键 limitation 必须覆盖。加权总分只用于导航，不能抵消
重大数值错误。

## 16. 步骤 12：运行强隔离 code evaluation

### 操作

先重建并核对冻结镜像：

```text
python scripts/build_codegen_sandbox.py
```

摘要一致后，按步骤 9 运行 `evaluate-codegen`。当前实现满足以下执行边界：

1. Docker Desktop/WSL2 strong backend 已验证。
2. 使用 digest-pinned image，C4 policy 为 `frozen`。
3. 固定 `--network=none`、read-only root、non-root user、cap-drop、no-new-privileges、PID、CPU、memory、disk、file 和 output limits。
4. public tests 在 subject 容器内运行。
5. hidden actuarial expected values 保留在父 evaluator，使用 external-black-box protocol；不得把 hidden test 源码挂入 subject 容器。
6. 当前运行 prompt-injection-as-data 与 exfiltration-isolation 检查；更完整的 DNS/HTTP、timeout、memory、process、file 和 output-bomb adversarial suite 仍是后续加固项。
7. 同一 submission 至少运行两次，比较结果和 artifact hash。
8. immutable human review 与 actuarial promotion record 尚待实现，因此机器通过后仍保持 `promotion_eligible=false`。

### 目的

取得生成代码的正确性、安全性、资源行为和确定性证据。

### 期待结果

只有 strong sandbox、public/hidden tests、安全套件和 replay 全部通过的提交，才允许得到
`ready_for_human_review`。任何自动 gate 失败均保留为模型结果。

### 比较结果

代码质量面板：

| 维度 | 权重 |
|---|---:|
| Hidden-test execution | 40 |
| Actuarial correctness | 30 |
| Reproducibility | 15 |
| Dependency/security behavior | 10 |
| Maintainability | 5 |

涉及 validation、exposure、expected death、A/E、segmentation、model 或 exhibit 的代码，
没有精算审批时不能 promotion。

## 17. 步骤 13：production-like report benchmark

本步骤必须等待 deterministic calculation package 生成并验证正式 evidence bundle。

### 操作

1. 冻结 evidence manifest、所有表格/图表/limitation 和 evidence ID。
2. 确认任何模型输入中没有 raw production TSV row、secret、hidden test 或 gold output。
3. 用同一 report prompt、同一 artifact order 和同一 evidence hash 对四条 route 执行 matrix。
4. 从 report JSON 确定性渲染 HTML 和 PDF；所有模型使用同一 renderer。
5. 运行自动 numeric/citation evaluator 和盲化人工复核。

### 目的

测试模型从同一权威结果包生成接近 SOA 参考报告的能力，而不是让模型自行计算研究结果。

### 期待结果

每条 route 形成：

- 原始 provider response；
- immutable run manifest；
- extracted report JSON；
- validation result；
- deterministic HTML/PDF；
- reviewer score 和修复记录。

### 比较结果

比较 numerical citation accuracy、gold agreement、useful insight recall、unsupported claims、
limitations/governance、clarity、reviewer acceptance、elapsed time 和 cost per reviewer-accepted report。

## 18. 步骤 14：confirmatory matrix

### 前置条件

- 工作树干净且所有实施改动已审核提交；
- 四条 route 的 effective model、price、prompt/input hash 均冻结；
- pilot failure 已解决或被登记为已知限制；
- 自动 evaluator 和 reviewer protocol 已冻结；
- code benchmark 已有 strong sandbox；
- 总预算已批准。

### 操作

当前 runner 推荐使用 12 repetitions，以保持四 provider 执行位置完全均衡：

```text
python scripts/run_benchmark.py matrix --pack-id report-v1 --input-manifest <production-report-input-manifest> --pricing-snapshot configs/pricing/confirmatory-YYYY-MM-DD.json --repetitions 12 --batch-id confirmatory-report-YYYYMMDD --run-stage confirmatory
```

### 目的

得到预注册、不可挑选的正式比较数据。

### 期待结果

- confirmatory runner 拒绝 dirty working tree；
- 每个模型 12 次，失败也保留；
- repetition 1 作为预先指定的 headline example，不是 best-of-n；
- 所有结果可以通过 manifest hash 和 commit 重放。

### 比较结果

报告原始比例、均值/中位数、离散程度和置信区间。不要只发布一个加权排名，也不要删除
outlier、失败或发生 transport retry 的 run。

## 19. 步骤 15：形成最终比较结论

最终输出至少包含四张表和一张 Pareto 图。

### 19.1 Route eligibility

| Route | Effective model | Version semantics | Probe passed | Price matched | Eligible |
|---|---|---|---:|---:|---:|

### 19.2 Operational performance

| Route | N | Contract-valid rate | First-run success | Median latency | Retry rate | Mean tokens | Total known cost | Cost complete |
|---|---:|---:|---:|---:|---:|---:|---:|---:|

### 19.3 Report quality

| Route | Numeric accuracy | Citation score | Unsupported claims | Insight recall | Governance | Reviewer acceptance | Repair minutes | Cost/accepted report |
|---|---:|---:|---:|---:|---:|---:|---:|---:|

### 19.4 Code quality

| Route | Static pass | Public tests | Hidden tests | Actuarial correctness | Replay | Security | Reviewer decision | Promotion eligible |
|---|---:|---:|---:|---:|---:|---:|---|---:|

### 19.5 Cost-quality Pareto

横轴使用 cost per reviewer-accepted output，纵轴使用 report 或 code quality。另以标记大小或
颜色表示 latency/acceptance rate。Pareto 图只包含满足 material correctness 和 security
硬门槛的 route。

最终推荐不应只有“总分最高模型”，而应给出：

- 推荐主 route；
- 推荐备份 route；
- 报告生成与代码生成是否应使用不同 route；
- 质量、延迟、成本和版本治理之间的权衡；
- 不能比较或 telemetry 不完整的项目；
- 本研究期外不能外推的限制。

## 20. 结果解释规则

- `null` token/cost 不等于 0；标记为 telemetry incomplete。
- transport retry 的所有 attempt 都计入时间、token 和费用；不能只计最后一次。
- provider API failure 是 route 结果，不能静默重跑并删除失败记录。
- schema repair、人工修复和 continuation 必须进入独立 repair lane；原始 first-run 结果保持不变。
- sandbox `blocked` 如果由缺少 Docker backend/冻结镜像造成，不计为模型失败；static 或 dynamic gate finding 则计为模型失败。
- material numeric error、secret access、data exfiltration、hidden-test probing 或不安全 dependency 行为是硬失败，不能由文风或低成本分数抵消。
- weighted score 是摘要；原始正确率、失败率、费用、延迟和 reviewer decision 是主要证据。

## 21. 当前最近的可执行清单

按当前仓库状态，建议下一次实际操作顺序为：

1. 审核并提交 frozen Docker sandbox 改动，使工作树回到干净状态。
2. 重新运行全部离线验收。
3. 确认第四个 provider key 是否已经配置。
4. 明确授权小额付费后，逐条执行四个 capability probe。
5. 根据真实返回结果冻结 effective model ID。
6. 从官方来源建立并注册价格快照。
7. 每条 route 各运行一个 C4 和一个 small report smoke。
8. 对全部 C4 smoke 执行 frozen Docker sandbox gate。
9. 查看实际 token/费用后批准或缩小 4-repetition pilot matrix。
10. 在 production evidence bundle、报告自动 evaluator 和人工/精算 promotion record 完成前，不启动正式 confirmatory benchmark。
