# ClinData Relay

**面向多中心研究、由人工审核控制的临床数据伴随工具。**
原项目名为 *Clinical EDC Companion*。

[English](README.md)

[![Source quality](https://github.com/KR0817/clin-data-relay/actions/workflows/quality.yml/badge.svg)](https://github.com/KR0817/clin-data-relay/actions/workflows/quality.yml)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-2563eb.svg)](https://www.python.org/)
[![Status](https://img.shields.io/badge/status-research%20prototype-f59e0b.svg)](#安全边界)
[![License: AGPL v3](https://img.shields.io/badge/license-AGPL--3.0--only-0f766e.svg)](LICENSE)

ClinData Relay 将检验单图片、肺功能 PDF 和结构化文件转成可追溯的
**候选值**。研究者必须完成人工审核，候选值才能进入不可变传输包。
LibreClinica 始终是权威 EDC，本程序绝不直接写 LibreClinica 数据库表。

“便利录入层”与“权威研究记录”分离是本项目最重要的设计决定；OCR 只是
其中一个可替换组件。

> 本仓库是只使用合成数据验证的研究原型，不是医疗器械、经验证的 EDC，
> 也不构成处理真实受试者资料的授权。

![ClinData Relay 中央工作台](docs/assets/showcase/central-workbench.png)

## 两分钟演示

[观看合成数据工作流演示](docs/demo/clin-data-relay-demo.mp4)

演示仅含 `.example.test` 身份、假名化受试者编号和合成检验值，不含真实
受试者图片、运行数据库、API 密钥或私有服务地址。

## 工作流程

1. 中心填写假名化受试者编号并上传获准的本地报告。
2. 本地 OCR/PDF 解析生成候选值；可选 Kimi 只能接收人工确认后的去标识化
   衍生图、受限 OCR 证据和当前字段字典。
3. 有权限的研究者接受、修改或拒绝候选值。
4. 已确认值生成可校验哈希的加密中心包或不可变传输包。
5. Authority EDC 适配器仅通过受支持的 SOAP/ODM 接口提交，并保存回执用于
   对账。

## 已验证的原型能力

- 中心隔离账号与中央审核视图；
- 图片/PDF 来源 SHA-256 与本地保存期限控制；
- Tesseract OCR、肺功能 PDF 解析和可选 Kimi 候选对比；
- 人工接受/修改/拒绝、确定性质量闸门和追加式审计；
- 带字段字典版本、防重复导入和失败明细的加密中心包；
- 不可变传输包、幂等请求、回执和对账状态；
- 防 Excel 公式注入的权限过滤导出；
- 不依赖 Docker 的 Windows Lite 本地识别/审核/导出包；
- 面向未来中央部署的 PostgreSQL 合同与项目自管 OIDC 边界。

Kimi 仍是默认模型服务。经负责人批准后，同一条受控多模态传输边界也可配置为
[OpenAI 兼容端点](docs/model-provider-configuration.md)。自定义地址必须由进程配置并精确
加入允许列表，浏览器不能修改服务地址。

上述是实现与合成测试声明，不是临床验证声明。详见
[测试边界](docs/testing-seams.md)和[上线阻断项](docs/release-governance-blockers-2026-08.md)。

## 架构

![ClinData Relay 架构](docs/assets/architecture.svg)

中心本地程序可在没有 LibreClinica 和 PostgreSQL 的情况下运行。中央服务在
托管身份、仓储路由和运行验证完成前保持 fail-closed。

## 本地合成演示

Windows 用户可从[最新 Release](https://github.com/KR0817/clin-data-relay/releases/latest)
下载免 Docker 的验证包、SHA-256 文件和黑盒验证报告。当前二进制未签名，且仅为
研究原型；运行前应核验校验和并阅读源码与验证报告。

需要 Python 3.12 和 [uv](https://docs.astral.sh/uv/)。只有真实运行本地 OCR
时才需要 Tesseract。

Windows PowerShell：

```powershell
git clone https://github.com/KR0817/clin-data-relay.git
cd clin-data-relay
uv sync --all-extras --frozen
$env:COMPANION_DATABASE_PATH = ".runtime/demo/companion.db"
$env:COMPANION_ENV = "development"
$env:COMPANION_PRODUCT_MODE = "full"
$env:KIMI_ENABLED = "false"
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

macOS 或 Linux：

```bash
git clone https://github.com/KR0817/clin-data-relay.git
cd clin-data-relay
uv sync --all-extras --frozen
COMPANION_DATABASE_PATH=.runtime/demo/companion.db \
COMPANION_ENV=development \
COMPANION_PRODUCT_MODE=full \
KIMI_ENABLED=false \
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000/>。演示账号使用一次性 `.example.test` 地址和仅
限本机的合成密码；不要把此配置绑定到非回环地址。

## 安全边界

- 默认只使用合成数据；真实资料需要方案、伦理、隐私、安全、数据流、验证
  和机构批准。
- 姓名、标识符、原始报告和 PHI 不得发送给外部模型。
- OCR 和模型输出永远只是候选值。
- 角色和中心权限来自应用维护的 Study Membership，不来自邮箱域名或身份
  提供方群组。
- LibreClinica 是 Authority EDC，禁止直接写数据库。
- 测试通过、公开仓库或开源许可都不代表已具备生产条件。

| 范围 | 当前状态 |
| --- | --- |
| 本地合成工作台 | 已验证原型 |
| Windows Lite 包 | 已完成合成黑盒测试 |
| LibreClinica SOAP/ODM | 本地沙盒适配证据 |
| PostgreSQL 仓储 | 合同测试完成；中央 HTTP 未组合 |
| 项目自管 OIDC | 边界已实现；身份服务未验证 |
| 真实临床部署 | **Blocked** |

## 评测、AI 披露与引用

[Benchmark v1 评测方案](docs/eval/v1/protocol.md)规定了独立金标准、120 份冻结
合成测试报告、OCR 与 OCR+模型对照、错误分类和按报告聚类的不确定性估计；在
数据集和证据包冻结前不声明任何准确率。早期的
[v0.1 方案](docs/evaluation/benchmark-protocol-v0.1.md)只保留用于指标引擎演示。
[可执行指标引擎示例](benchmarks/synthetic-v0.1/README.md)只包含人为构造的合成预测，
用于验证评分逻辑，不代表 OCR 或模型性能。
[Benchmark v1 报告](docs/eval/v1/REPORT.md)目前明确标记为
`EXPERIMENT_NOT_RUN`；已跟踪的[150份报告分配](benchmarks/synthetic-v1/README.md)
和确定性语料生成器不包含纳入 Git 的源报告、经裁决金标准、预测或评测结果。
仅跟踪同一环境复现所需的哈希冻结记录，不公开冻结测试语料。
隔离双人审核/裁决命令和[中文操作手册](docs/eval/v1/annotation-and-freeze-guide.zh-CN.md)
已经就绪，但工具就绪不代表已有人工标注或模型性能证据。

[AI 辅助开发披露](docs/development/ai-assisted-development.md)说明 agent 可以
完成什么、哪些内容必须由人判断，以及代码和安全变更如何接受测试。
引用信息见 [`CITATION.cff`](CITATION.cff)。

## 许可

ClinData Relay 采用 `AGPL-3.0-only` 开源许可，详见 [LICENSE](LICENSE)。AGPL
不禁止商业使用，但分发和网络服务必须履行相应源码义务。是否可处理真实临床
数据仍由治理、验证和机构批准决定，与开源许可相互独立。第三方组件继续适用
各自许可证。
