Clinical Report Extractor Lite - macOS
======================================

首次使用
--------
1. 根据电脑芯片选择压缩包：Apple Silicon（M1/M2/M3/M4）使用 arm64，
   Intel Mac 使用 x86_64。
2. 解压整个 ZIP，双击 ClinicalReportExtractorLite.app。
3. 浏览器打开后使用：
   账号 site-a-investigator@example.test
   密码 demo-password

接收方不需要安装 Python、Tesseract、Docker Desktop、Linux 或
LibreClinica。肺功能 PDF 在本机读取文本层，不需要网络或 Kimi 密钥。

签名说明
--------
已使用 Developer ID 签名并经 Apple 公证的正式包可以直接双击。内部测试包
若仅有临时签名，首次启动需在 Finder 中右键应用并选择“打开”；不要关闭
Gatekeeper，也不要运行来源不明的包。可在同目录验收 JSON 中查看 signing
与 notarized 状态。

可选 Kimi
---------
需要增强图片识别时，双击 Configure-Kimi.command，按遮罩提示输入接收方
自己的 Kimi API 密钥，然后重新打开应用。PDF 不会发送给 Kimi。

日常流程
--------
上传 PDF/图片 -> 选择识别项目 -> 人工接受/修改/拒绝 -> 导出已确认 Excel。
本地数据保存在：
~/Library/Application Support/ClinicalReportExtractorLite/

边界
----
Lite 不是 EDC，不连接 LibreClinica，也不执行权威库提交。导出的值是本地
人工确认副本。当前软件仍是本地研究验证版本；使用真实研究资料前必须完成
院方、伦理、隐私、安全和软件验证审批。
