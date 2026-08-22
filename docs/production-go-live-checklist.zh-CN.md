# 生产就绪实施清单

当前工作台已经具备本地识别、人工审核、加密中心包、批量导入、审计、备份和 BitLocker/FileVault 检查。但本地 SQLite + 演示身份不能被配置开关“变成”医院生产系统。

## 当前自动检查

使用与 `/api/health` 相同的只读检查：

```powershell
\.venv\Scripts\python.exe scripts\check_production_readiness.py
```

脚本退出码为 `0` 才表示当前运行时和证据清单全部通过；退出码为 `1` 表示仍有阻塞项。它不会启用服务、修改账号、保存密钥或连接远程医院系统。

证据清单模板位于 `config/production-evidence.example.json`。正式部署时复制到机构批准的受控路径，并设置：

```powershell
$env:COMPANION_PRODUCTION_EVIDENCE_FILE = 'D:\institution-controlled\clinical-edc\production-evidence.json'
```

每个已批准项目必须包含 `status=approved`、外部审批/验证记录编号 `evidence_ref`、`checked_at` 和未来的 `expires_at`。清单不得写入密码、Token、私钥、Kimi Key、患者信息或临床值。

## 必须由机构完成的闸门

### 1. 中央数据库

- 由医院信息中心提供受管控的 PostgreSQL 集群和备份策略。
- 为 companion、LibreClinica、迁移、备份分别创建非超级用户。
- 完成迁移、并发、中心隔离、事务回滚、备份恢复和性能测试。
- 在代码完成 PostgreSQL repository adapter 并通过专门测试前，`COMPANION_DEPLOYMENT_PROFILE=central` 会故意启动失败。

### 2. 身份与权限

- 接入医院批准的 OIDC 或 SAML 身份提供方。
- 强制 MFA、最小权限、账号开通/变更/离职回收和定期权限复核。
- 生产环境不得使用演示账号、固定密码或应用内批量生成的 bootstrap 密码。

### 3. HTTPS 与网络

- 使用医院域名、受管控证书和反向代理。
- 外部只开放 HTTPS；FastAPI、LibreClinica、PostgreSQL 和 Docker 管理接口不直接暴露公网。
- 配置访问日志脱敏、超时、上传大小、来源网络限制和证书到期告警。

### 4. 密钥管理

- 使用医院批准的 Secret Manager/KMS，不使用环境变量或仓库文件保存生产密码。
- Kimi Key、LibreClinica SOAP 凭据、数据库凭据和 TLS 私钥分离管理、可轮换、可吊销。
- 记录密钥所有者、轮换周期和紧急恢复流程，但不把密钥值写入工单或日志。

### 5. EDC 与接口验证

- 固定 LibreClinica 版本、Tomcat/OpenJDK/PostgreSQL 版本和 CRF/OID 映射。
- 对每个支持的字段完成 SOAP/ODM 写入、重复提交、超时、失败重试和权威回读验证。
- `readback=unsupported`、`mismatch` 和不确定超时不得被标记为成功。

### 6. 验证、SOP 和培训

- 完成 IQ/OQ/PQ、UAT、变更控制、版本回滚和发布审批。
- 建立数据录入、审核、导入包、错误处理、备份恢复、原图清理、停机录入和对账 SOP。
- 记录研究者、中央数据管理员、监查员、审计员培训和权限复核。

### 7. 监控、事件和灾备

- 监控应用健康、PostgreSQL、磁盘容量、证书、备份年龄、导入失败和 LibreClinica 回读不一致。
- 建立安全事件、数据泄露、误导入、密钥泄露和停机升级流程。
- 在隔离主机完成恢复演练，证明登录、审计、候选值、导入日志、备份哈希和 EDC 对账均可恢复。

## 当前状态判定

BitLocker 已在本机完成；但这只满足本机磁盘保护一项。生产状态仍须等待 PostgreSQL、医院身份/MFA、TLS、密钥托管、接口验证、SOP/培训、监控、事件响应和灾备证据全部齐全后，由牵头研究者、数据管理员、信息中心、隐私/安全和验证负责人共同签署 go-live 记录。
