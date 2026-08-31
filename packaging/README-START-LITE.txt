Clinical Report Extractor Lite - Windows x64
==============================================

首次使用
--------
1. 将整个 ZIP 解压到可写入的本地文件夹。
2. 双击带蓝色盾牌/检查单图标的 Start-Clinical-EDC-Lite.exe。若本机策略要求命令入口，再运行 compatibility\Start-Clinical-EDC-Lite.cmd。
3. 浏览器打开后使用：
   账号 site-a-investigator@example.test
   密码 demo-password

不需要安装 Python、Tesseract、Docker Desktop、WSL、Linux 引擎或
LibreClinica。肺功能 PDF 在本机读取文本层，不需要网络或 Kimi 密钥。

可选 Kimi
---------
图片识别需要增强时，先双击 Configure-Kimi.cmd，按遮罩提示输入接收方
自己的 Kimi API 密钥，然后关闭并重新启动 Lite。PDF 不会发送给 Kimi。

日常流程
--------
上传 PDF/图片 -> 选择识别项目 -> 人工接受/修改/拒绝 -> 导出已确认 Excel。
本地数据保存在 data\companion.db，上传文件保存在 data\ 下的应用目录。

边界
----
Lite 不是 EDC，不连接 LibreClinica，也不执行权威库提交。导出的值是本地
人工确认副本。当前软件仍是本地研究验证版本；使用真实研究资料前必须完成
院方、伦理、隐私、安全和软件验证审批。

完整性
------
MANIFEST.sha256 记录分发文件哈希。本构建未进行代码签名，Windows 可能显示
SmartScreen 提示。机构分发前仍需完成签名、恶意软件扫描和许可证审查。

开源许可
--------
本程序采用 AGPL-3.0-only。LICENSE 是许可全文，SOURCE-CODE.txt 提供与版本
对应的完整源码地址；第三方组件继续适用 THIRD-PARTY-NOTICES.txt 中的许可。
