# Benchmark v1 双人标注、裁决与冻结操作手册

当前状态是“工具和合成语料已准备，实验尚未运行”。本手册只适用于仓库生成的
无身份合成报告，不得换成真实受试者材料。

## 1. 人员与隔离

至少安排四个职责，人员姓名保存在研究管理记录中，不写进评测文件：

- `corpus_custodian`：保管锁定语料、发放审核包、运行校验命令；不代替审核员填写。
- `reviewer_a`：只接收 reviewer A 包，独立转录 75 份报告。
- `reviewer_b`：只接收 reviewer B 包，独立转录另外 75 份报告；其中 30 份与 A 重叠。
- `adjudicator`：在两人都提交并冻结后，只处理双审差异；不能是 A 或 B。
- `prediction_operator`：gold 关闭后运行两条提取臂；运行时不能打开 gold。

审核员之间不得交换文件、讨论具体字段，也不能看到 construction truth、OCR、Kimi
或另一人的结果。`accept/edit/reject` 历史不能替代本次独立标注。

## 2. 中央生成并发放两个审核包

在项目根目录运行：

```powershell
uv run python scripts/benchmark_v1_workflow.py prepare-review-kits `
  --corpus-dir .runtime/benchmark-v1-corpus-freeze-20260901 `
  --allocation benchmarks/synthetic-v1/dataset-plan.json `
  --output-dir .runtime/benchmark-v1-review-kits-20260901
```

输出包括 `reviewer-a/`、`reviewer-b/` 和中央专用的
`custody-manifest.json`。立即把 custody manifest 单独复制到只读研究目录并记录其
SHA-256。只把对应 reviewer 文件夹交给相应审核员，不要把整个父目录发出去。

每个审核包包括：

- 75 份分配给该审核员的合成源报告；
- 相同的字段字典；
- `assignments.csv`；
- 可编辑的 `annotations.csv`；
- 覆盖不可编辑文件的 `manifest.json`。

两个包恰好重叠 30 份报告，不包含 construction truth 或系统预测。

## 3. 两名审核员独立填写

用 Excel、LibreOffice 或其他表格软件打开 `annotations.csv`。每个字段占一行，
同一报告有多个字段时重复填写 `report_id`。不要改名、移动或覆盖 `sources/`、
`dictionary/`、`assignments.csv` 和 `manifest.json`。

字段规则：

- `field_code`：只能使用包内字典的标准代码；
- `displayed_label`：报告上实际显示的名称；
- `value`：按报告原样转录，不自行换算单位；
- `comparator`：只允许空、`<`、`<=`、`>` 或 `>=`；
- `unit`、`reference_interval`：按报告原样转录，没有时留空；
- `page_number`：从 1 开始；
- 四个 `evidence_*`：使用 0–1 的页面归一化坐标；无法可靠标框时四项全部留空。

不得把目标字段数、构造记录或任何模型建议补给审核员。完成后分别把整个 reviewer
文件夹返回中央保管员。

## 4. 中央校验并冻结两份独立标注

中央使用最初单独保管的 custody manifest，分别运行：

```powershell
uv run python scripts/benchmark_v1_workflow.py compile-review `
  --review-kit PATH/reviewer-a `
  --custody-manifest PATH/custody-manifest.json `
  --output-dir PATH/reviewer-a-evidence

uv run python scripts/benchmark_v1_workflow.py compile-review `
  --review-kit PATH/reviewer-b `
  --custody-manifest PATH/custody-manifest.json `
  --output-dir PATH/reviewer-b-evidence
```

任何源文件/字典/分配表哈希变化、漏报、重复字段或错误格式都会失败。成功输出的
`annotations.jsonl` 和 `manifest.json` 是两份独立标注证据。不要手工修改 JSONL。

## 5. 生成差异表并由第三人裁决

两份标注都冻结后运行：

```powershell
uv run python scripts/benchmark_v1_workflow.py prepare-adjudication `
  --allocation benchmarks/synthetic-v1/dataset-plan.json `
  --reviewer-a PATH/reviewer-a-evidence/annotations.jsonl `
  --reviewer-b PATH/reviewer-b-evidence/annotations.jsonl `
  --output-dir PATH/adjudication
```

`agreement-summary.json` 记录 30 份双审报告的完全一致数、存在分歧的报告数和分歧
字段槽数。它衡量标注可重复性，不证明构造真值正确。

第三裁决者只编辑 `adjudication.csv` 的三列：

- `resolution`：填写 `reviewer_a`、`reviewer_b`、`custom` 或 `omit`；
- `custom_json`：仅当两人均不正确且选择 `custom` 时填写完整字段 JSON；
- `reason`：每条都必须填写可审计理由。

其余四列是由两份冻结标注生成的证据，不得修改。`omit` 表示源报告不支持该字段，
不是缺失值填零。

## 6. 关闭裁决并生成 locked gold

```powershell
uv run python scripts/benchmark_v1_workflow.py finalize-gold `
  --allocation benchmarks/synthetic-v1/dataset-plan.json `
  --reviewer-a PATH/reviewer-a-evidence/annotations.jsonl `
  --reviewer-b PATH/reviewer-b-evidence/annotations.jsonl `
  --adjudication-csv PATH/adjudication/adjudication.csv `
  --output-dir PATH/gold-v1
```

只有所有分歧都完成裁决时才会生成：

- `locked-gold.jsonl`：120 份锁定报告的最终金标准；
- `disagreement-log.jsonl`：两名审核员原值、裁决选择、最终值和理由；
- `annotation-summary.json`：单审/双审、一致和裁决计数；
- `manifest.json`：所有输入与输出的 SHA-256。

目录存在时命令拒绝覆盖。该目录应复制到访问受控、备份且只读的位置。manifest
只能发现修改，不等同于 WORM 或电子签名系统。

## 7. 生成并冻结两组预测

只有 gold 完成后才运行正式提取。两条臂必须使用同一 Git commit、Python lock、
字典、150 份中的同一 120 份 locked 源文件、相同预处理和固定重试规则：

- `local_ocr`：关闭模型，只运行本地 OCR/PDF 解析；
- `local_ocr_plus_model`：打开已批准的 OpenAI-compatible/Kimi 配置；模型失败、超时、
  fallback 和主动弃权分别记录，不能偷偷重跑或删除报告。

当前仓库尚未提供付费模型的正式 120 份批量运行器，因此不能用网页人工多次尝试后
拼出“最好结果”。批量运行器完成并冻结成本/重试参数前，不要正式运行 Kimi；需要
密钥时只通过本机密钥配置入口输入，绝不写入命令、仓库或结果文件。

获得两个完整的 prediction-v2 JSONL 后，先冻结而不评分：

```powershell
uv run python scripts/benchmark_v1_workflow.py freeze-predictions `
  --allocation benchmarks/synthetic-v1/dataset-plan.json `
  --source-manifest .runtime/benchmark-v1-corpus-freeze-20260901/manifests/source-manifest.json `
  --application-commit (git rev-parse HEAD) `
  --gold PATH/gold-v1/locked-gold.jsonl `
  --local-ocr PATH/local-ocr.jsonl `
  --assisted PATH/local-ocr-plus-model.jsonl `
  --output-dir PATH/frozen-inputs-v1
```

命令要求两条臂均为 `clin-data-relay-prediction-v2`，并且与 120 份 gold 完全同覆盖；
它同时记录 source manifest、`uv.lock`、两份字典、模型契约和 Git commit，只复制和
哈希，不计算准确率。冻结前必须确保工作区没有未提交代码变更。

## 8. 生成不可覆盖的结果包

冻结成功后才运行评分：

```powershell
uv run python scripts/evaluate_extraction_benchmark.py `
  --gold PATH/frozen-inputs-v1/locked-gold.jsonl `
  --predictions local_ocr=PATH/frozen-inputs-v1/local-ocr.jsonl `
  --predictions local_ocr_plus_model=PATH/frozen-inputs-v1/local-ocr-plus-model.jsonl `
  --output-dir PATH/evaluation-package-v1 `
  --bootstrap-samples 2000 `
  --seed 20260901
```

结果目录包含 `summary.json`、不含字段值的 `errors.csv` 和 `manifest.json`，并拒绝
覆盖已有目录。确认所有哈希、样本数、失败数和分母后，才能填写 `REPORT.md`。
在报告完成、人工复核和 CI 通过前，不创建 `bench-v1` 标签。

## 当前实际状态

- 审核包工具：已实现并通过合成端到端测试；
- 本机审核包：已生成，但尚未由两名真实审核员填写；
- 独立标注、第三人裁决、两组正式预测、评测数字：均尚不存在；
- `REPORT.md`：继续保持 `EXPERIMENT_NOT_RUN`。
