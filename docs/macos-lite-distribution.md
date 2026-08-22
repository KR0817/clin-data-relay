# macOS Lite 版构建、安装与使用说明

本文说明如何把 ClinicalReportExtractorLite 构建为可在苹果电脑上运行的独立应用，以及接收方如何安装、识别肺功能 PDF、人工审核并导出 Excel。

## 1. 先看结论

macOS Lite 版只包含以下本地工作流：

1. 上传肺功能 PDF。
2. 在本机提取候选值。
3. 人工接受、修改或拒绝候选值。
4. 导出已接受项目的 Excel。
5. 可选使用 Kimi 辅助纠错。

接收方不需要安装 Docker Desktop、Linux、LibreClinica、Python 或 Tesseract。以上依赖只在“构建应用”的 Mac 上需要，构建完成后已经包含在 `.app` 中。

> **重要边界：**Lite 版不是 LibreClinica，也不会把数据提交到权威 EDC。它适合完成 PDF 读取、人工复核和 Excel 导出。真实受试者资料投入使用前，仍需完成所在机构的数据安全、伦理和软件验证流程。

## 2. 选择正确的 Mac 版本

应用按处理器分为两个版本，不能混用：

| Mac 类型 | 应选择的压缩包 | 终端显示 |
| --- | --- | --- |
| Apple Silicon：M1、M2、M3、M4 等 | `ClinicalReportExtractorLite-macos-arm64.zip` | `arm64` |
| Intel 处理器 Mac | `ClinicalReportExtractorLite-macos-x86_64.zip` | `x86_64` |

查看处理器的方法：

- 图形界面：点击屏幕左上角苹果菜单，选择“关于本机”。
- 终端：打开“终端”并运行：

```bash
uname -m
```

输出 `arm64` 就使用 Apple Silicon 版；输出 `x86_64` 就使用 Intel 版。

## 3. 接收方如何安装和使用

本节面向最终使用应用的研究者。前提是已经收到与自己 Mac 处理器匹配的可运行 ZIP，而不是名称含 `build-source` 的源码构建包。

### 3.1 解压并首次打开

1. 将收到的 ZIP 保存到 Mac，例如“下载”文件夹。
2. 双击 ZIP 解压。
3. 打开解压后的完整文件夹。
4. 双击 `ClinicalReportExtractorLite.app`。
5. 等待浏览器自动打开本地工作台。

应用只监听本机地址，通常为：

```text
http://127.0.0.1:8000/
```

不要只把 `.app` 单独拖出文件夹后删除其余文件；请保留 `Configure-Kimi.command`、说明和第三方许可文件。

### 3.2 macOS 提示“无法验证开发者”

正式对外分发的版本应使用 Apple Developer ID 签名并完成苹果公证，通常可直接打开。

内部测试用的临时签名版本第一次打开时，可以：

1. 在 Finder 中找到 `ClinicalReportExtractorLite.app`。
2. 按住 Control 键并点击应用，或右键点击应用。
3. 选择“打开”。
4. 在系统弹窗中再次选择“打开”。

不要关闭 Gatekeeper，也不要运行 `spctl --master-disable`。若系统仍然拦截，应让构建者提供已签名、公证的正式包。

### 3.3 完成一次 PDF 识别和导出

1. 登录工作台。
2. 在识别范围中勾选本次需要提取的肺功能项目。
3. 上传一个或多个 PDF。
4. 点击准备/识别按钮，等待候选值出现。
5. 检查字段名称、数值、单位及原始证据。
6. 对可信结果选择“接受”；有误时修改后接受，或直接拒绝。
7. 使用“一键接受”时仍需确认本批报告属于正确受试者，且数值和单位没有明显错位。
8. 在导出区导出 Excel。导出内容以当前识别范围和已接受项目为准。

PDF 本地提取不依赖 Kimi，也不依赖网络。Kimi 是可选的辅助纠错层，不能代替人工审核。

### 3.4 配置或更换 Kimi API 密钥

1. 关闭正在运行的应用。
2. 双击同一文件夹中的 `Configure-Kimi.command`。
3. 按提示在终端中输入自己的 Kimi API 密钥。
4. 输入过程中密钥不会显示在屏幕上，这是正常现象。
5. 配置完成后重新打开 `ClinicalReportExtractorLite.app`。
6. 在工作台中打开 Kimi 开关。

密钥写入当前用户的本地应用数据目录，并设置为仅当前用户可读写。不要把 API 密钥发给其他人，也不要写进源码、压缩包、聊天记录或截图。

### 3.5 关闭应用

关闭浏览器标签页并不一定会结束后台应用。可先在应用页面使用退出功能；如果没有退出入口，可在“活动监视器”中结束 `ClinicalReportExtractorLite`。不要强制结束名称不明的系统进程。

## 4. 数据保存、升级和备份

应用、数据库和导出记录默认保存在：

```text
~/Library/Application Support/ClinicalReportExtractorLite
```

在 Finder 中打开该目录：

1. 打开 Finder。
2. 点击菜单“前往”→“前往文件夹”。
3. 输入：

```text
~/Library/Application Support/ClinicalReportExtractorLite
```

### 4.1 备份

1. 完全关闭应用。
2. 复制整个 `ClinicalReportExtractorLite` 数据目录到加密磁盘或获批的研究存储位置。
3. 同时单独保存最终导出的 Excel。

### 4.2 升级应用

通常只需关闭旧应用、解压新版 ZIP，再打开新版 `.app`。不要删除上述 Application Support 数据目录，否则本地账号、审核记录和配置可能丢失。升级前先做备份。

## 5. 构建者准备工作

本节面向负责生成可分发 `.app` 的开发者。若你只是使用别人已经构建好的应用，可以跳过本节。

### 5.1 为什么必须在 Mac 上构建

PyInstaller 不是跨平台编译器：Windows 不能直接生成可运行的 macOS `.app`。因此：

- Windows 可以生成 `ClinicalReportExtractorLite-macos-build-source.zip` 源码构建包。
- Apple Silicon 应用必须在 `arm64` Mac 上原生构建。
- Intel 应用必须在 `x86_64` Mac 上原生构建。
- 名称含 `build-source` 的 ZIP 不能直接发给研究者运行。

### 5.2 构建机要求

准备一台与目标架构匹配的 Mac，并确保：

- 可以访问互联网以安装构建依赖。
- 已安装 Xcode Command Line Tools。
- 已安装 Homebrew。
- 至少预留约 10 GB 可用空间。
- 源码路径和构建路径中不要放入真实患者资料或密钥。

安装 Xcode Command Line Tools：

```bash
xcode-select --install
```

Homebrew 请按照其[官方网站](https://brew.sh/)的当前说明安装，不要从非官方网站复制安装命令。

## 6. 方式 A：在本地 Mac 上构建

### 6.1 复制并校验源码构建包

将以下文件复制到 Mac：

```text
ClinicalReportExtractorLite-macos-build-source.zip
```

在“终端”中进入 ZIP 所在目录，例如：

```bash
cd ~/Downloads
shasum -a 256 ClinicalReportExtractorLite-macos-build-source.zip
```

将输出值与发送方单独提供的 SHA-256 值比较。两者完全一致后再继续；不一致时重新传输文件，不要继续构建。

解压到用户目录：

```bash
mkdir -p ~/ClinicalReportExtractorLiteBuild
ditto -x -k ClinicalReportExtractorLite-macos-build-source.zip ~/ClinicalReportExtractorLiteBuild
cd ~/ClinicalReportExtractorLiteBuild/ClinicalReportExtractorLite-macos-build-source
```

确认当前目录包含 `pyproject.toml`、`app`、`scripts`、`packaging` 等内容：

```bash
ls
```

### 6.2 安装构建依赖

```bash
brew install python@3.12 tesseract
PYTHON312="$(brew --prefix python@3.12)/bin/python3.12"
"$PYTHON312" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -c packaging/macos-build-constraints.txt -e '.[dev]'
```

验证处理器、Python 和 Tesseract：

```bash
uname -m
.venv/bin/python --version
tesseract --version
```

预期 Python 为 3.12，处理器必须与目标 ZIP 一致。

### 6.3 构建并自动验证

```bash
TARGET_ARCH="$(uname -m)" bash ./scripts/build_macos_lite.sh
```

脚本会依次完成：

1. 运行相关自动化测试。
2. 用 PyInstaller 生成 `.app`。
3. 检查代码签名。
4. 启动已打包的应用。
5. 用合成肺功能 PDF 验证 18 个候选字段。
6. 验证人工审核和 Excel 导出链路。
7. 生成架构明确的 ZIP 和验证报告。

构建成功后，Apple Silicon Mac 应生成：

```text
dist/ClinicalReportExtractorLite-macos-arm64.zip
dist/ClinicalReportExtractorLite-macos-arm64.verification.json
```

Intel Mac 应生成：

```text
dist/ClinicalReportExtractorLite-macos-x86_64.zip
dist/ClinicalReportExtractorLite-macos-x86_64.verification.json
```

### 6.4 检查验证报告

Apple Silicon 示例：

```bash
cat dist/ClinicalReportExtractorLite-macos-arm64.verification.json
shasum -a 256 dist/ClinicalReportExtractorLite-macos-arm64.zip
```

Intel 示例：

```bash
cat dist/ClinicalReportExtractorLite-macos-x86_64.verification.json
shasum -a 256 dist/ClinicalReportExtractorLite-macos-x86_64.zip
```

至少确认以下结果：

- `architecture` 与目标 Mac 一致。
- `pulmonary_pdf_candidates` 为 `18`。
- `human_review` 为 `verified`。
- `reviewed_excel_export` 为 `verified`。
- `product_mode` 为 `lite`。
- `authority_edc_included` 为 `false`。

`production_readiness` 显示 `BLOCK` 不代表程序构建失败，而是提醒该 Lite 工具尚未完成真实临床生产环境所需的机构批准和验证。

## 7. 方式 B：使用 GitHub Actions 构建两个架构

项目内置 `.github/workflows/build-macos-lite.yml`，可以分别使用 Apple Silicon 和 Intel macOS runner 构建两个版本。

操作步骤：

1. 在 GitHub 新建一个**私有仓库**。
2. 将源码构建包解压后的内容上传到仓库根目录。
3. 确认仓库中能看到 `.github/workflows/build-macos-lite.yml`。
4. 打开仓库的“Actions”页面。
5. 在左侧选择“Build macOS Lite”。
6. 点击“Run workflow”并确认运行。
7. 等待 `arm64` 和 `x86_64` 两个任务都完成。
8. 打开本次运行记录，在“Artifacts”区域下载两个构建产物。
9. 解压 GitHub 下载的 artifact，取得应用 ZIP 和对应的 `.verification.json`。
10. 检查验证报告后，再把正确架构的应用 ZIP 发给接收方。

当前 GitHub Actions 工作流默认生成内部测试用的临时签名包，不会自动读取你的 Apple 证书，也不会自动完成公证。不要把 Apple 证书、密码、Kimi 密钥或真实研究数据提交到仓库。

## 8. 签名与苹果公证

### 8.1 两种分发级别

| 用途 | 签名状态 | 使用体验 |
| --- | --- | --- |
| 自己或受控团队内部测试 | `ad_hoc` | 首次可能需要右键选择“打开” |
| 发给外部研究者正式使用 | `developer_id` 且 `notarized=true` | 通常可直接打开，系统提示更少 |

对外分发建议完成 Developer ID 签名和苹果公证。参考苹果官方的[macOS 软件公证说明](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)。

### 8.2 准备 Developer ID

需要：

- 有效的 Apple Developer Program 账号。
- 安装在本机构建 Mac“钥匙串访问”中的 `Developer ID Application` 证书。
- 已在本机钥匙串中保存的 `notarytool` 凭据配置。

查看可用签名身份：

```bash
security find-identity -v -p codesigning
```

在本机交互式保存公证凭据，配置名称可使用 `clinical-edc-notary`：

```bash
xcrun notarytool store-credentials "clinical-edc-notary"
```

按终端提示在本机输入 Apple ID、团队 ID 和应用专用密码等信息。不要把这些内容复制到项目、文档、GitHub 或聊天中。

### 8.3 生成正式签名和公证包

将下面示例中的签名身份替换为 `security find-identity` 显示的完整名称：

```bash
MACOS_CODESIGN_IDENTITY='Developer ID Application: Your Name (TEAMID)' \
MACOS_NOTARY_KEYCHAIN_PROFILE='clinical-edc-notary' \
TARGET_ARCH="$(uname -m)" \
bash ./scripts/build_macos_lite.sh
```

构建脚本会提交公证、等待结果、把公证票据装订到应用，并再次进行系统安全评估。完成后必须检查验证报告：

```json
{
  "signing": "developer_id",
  "notarized": true
}
```

只有同时满足这两个值，才能把构建结果描述为已签名、公证的正式外部分发包。

## 9. 如何同时提供 Apple Silicon 和 Intel 版本

本地构建脚本要求原生架构匹配，不能在 Apple Silicon Mac 上把 `TARGET_ARCH` 强制写成 `x86_64` 来绕过检查，也不能在 Intel Mac 上生成 `arm64` 包。

可靠做法只有两种：

1. 分别在一台 Apple Silicon Mac 和一台 Intel Mac 上执行本地构建。
2. 使用项目自带的 GitHub Actions 两个 macOS runner 生成两个架构。

构建完成后分别保留 ZIP、验证 JSON 和 SHA-256，不要把两个 ZIP 改成相同文件名。

## 10. 常见问题排查

### 10.1 显示 `This build must run on macOS`

原因：正在 Windows 或 Linux 上运行 macOS 构建脚本。

处理：把源码构建包复制到 Mac，或使用 GitHub Actions。Windows 只能准备源码包，不能生成 `.app`。

### 10.2 显示 `Native build required`

原因：`TARGET_ARCH` 与当前 Mac 的 `uname -m` 不一致。

处理：运行：

```bash
uname -m
TARGET_ARCH="$(uname -m)" bash ./scripts/build_macos_lite.sh
```

若需要另一架构，换用对应处理器的 Mac 或 GitHub runner。

### 10.3 显示 `Project Python is missing`

原因：虚拟环境未创建、目录不正确或 Python 安装失败。

处理：确认自己位于项目根目录，然后重新执行第 6.2 节的 Python 安装和虚拟环境命令。

### 10.4 显示 `Tesseract is required`

处理：

```bash
brew install tesseract
tesseract --version
```

确认第二条命令能够显示版本后重新构建。

### 10.5 构建验证端口 8013 被占用

换一个未被占用的本机端口，例如：

```bash
VERIFICATION_PORT=18013 TARGET_ARCH="$(uname -m)" bash ./scripts/build_macos_lite.sh
```

### 10.6 打开应用后网页没有出现

1. 等待约 10 至 30 秒。
2. 手动访问 `http://127.0.0.1:8000/`，注意末尾不要输入中文句号。
3. 在“活动监视器”中确认应用是否仍在运行。
4. 若 8000 端口被另一个已知服务占用，先正常退出该服务，再重新打开应用。

### 10.7 PDF 上传后未识别出数值

检查：

- PDF 是否加密或损坏。
- 报告是否超过当前支持的页数。
- 页面是否为低清晰度扫描图。
- 项目名称是否存在于当前肺功能字段字典。
- 是否在识别范围中勾选了需要导出的项目。

对于无文本层或质量很差的扫描 PDF，可先导出为清晰 PNG/JPEG 后上传。无论是否启用 Kimi，都必须人工核对候选值。

### 10.8 Kimi 显示未启用

关闭应用，重新运行 `Configure-Kimi.command`，再启动应用。即使 Kimi 不可用，本地 PDF 提取和 Excel 导出仍应可以运行。

### 10.9 验证报告中 `notarized` 为 `false`

这表示当前是内部测试包，或没有正确提供 Keychain 公证配置。检查 Apple Developer 证书、`notarytool` 配置和构建命令。不要把它标记为已公证正式包。

## 11. 交付前检查清单

构建者在发包前逐项确认：

- [ ] ZIP 架构与接收方 Mac 一致。
- [ ] 对应验证 JSON 全部通过。
- [ ] 合成 PDF 提取 18 个候选字段。
- [ ] 人工审核链路为 `verified`。
- [ ] Excel 导出链路为 `verified`。
- [ ] ZIP 中没有 `.env`、数据库、日志、私钥、证书或真实患者资料。
- [ ] 已记录并通过独立渠道提供 ZIP 的 SHA-256。
- [ ] 正式外发包为 `signing=developer_id` 且 `notarized=true`。
- [ ] 接收方获得了与自己处理器匹配的 ZIP，而不是源码构建包。
- [ ] 接收方知道本地数据目录和备份方法。

## 12. 安全与临床使用边界

- Kimi 只能处理完成获批去标识化后的内容，不能直接接收含姓名、证件号、手机号、住院号等直接身份信息的原始报告。
- AI 或 OCR 候选值不得绕过人工审核直接成为最终临床数据。
- Lite 版导出的 Excel 是本地审核结果，不等同于 LibreClinica 中的权威记录。
- 在真实多中心研究中使用前，应明确账号权限、审计、备份、数据保留、跨机构传输和软件验证责任。
- 构建包、代码仓库和日志中不得保存 Kimi 密钥、Apple 凭据或研究数据。

## 13. 官方参考

- [Homebrew](https://brew.sh/)
- [PyInstaller 使用说明](https://pyinstaller.org/en/stable/usage.html)
- [GitHub Actions macOS runner](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job)
- [Apple：Notarizing macOS software before distribution](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
