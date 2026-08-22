# Kimi K3 检查单识别接入研究

**核验日期：** 2026-08-10  
**范围：** 当前本地合成数据沙箱；不授权上传真实患者原图或生产写入。

## 结论

当前程序已经有 `app/kimi.py` 和 `/api/source-files/{id}/kimi-extract`。分发构建默认启用 Kimi 配置，但没有收件人本地密钥时健康状态为 `kimi_integration=key_required`，网页保持本地 OCR 可用且不会发起外部请求。现有适配器只接收本地 OCR 文本；它可以整理文本，却无法可靠恢复 Tesseract 已经漏掉或读错的字符。

提高准确率的推荐方式不是用 Kimi 替换 OCR，而是建立一个有证据链的混合识别器：

1. 本地生成遮盖后的 PNG，人工确认遮盖预览；原图禁止外发。
2. 对确认后的衍生图运行本地 OCR，保留文本、词级 bbox、置信度和引擎版本。
3. 将同一检查单的去标识化衍生图或项目行裁剪图、本地 OCR span/bbox、当前访视允许的 CRF 字段字典一起提交给 `kimi-k3`。
4. 要求 `json_schema` 且 `strict: true` 的结构化输出，只允许返回白名单字段、原始可见值、单位、图像证据位置和“不确定/未见”状态；禁止补全缺失值。
5. 服务端再次执行字段白名单、数值格式、单位和协议范围校验，并把本地 OCR 与 Kimi 的一致/冲突状态写入候选来源。
6. 所有结果仍停留在候选库，由研究者或中央数据管理员逐项确认；只有人工确认后的冻结包可走现有 LibreClinica SOAP/ODM 通路。

## 官方接口事实

- 正式模型标识为 `kimi-k3`；中国区 OpenAI 兼容地址为 `https://api.moonshot.cn/v1`，国际区为 `https://api.moonshot.ai/v1`，两区密钥不能混用。[中国区 API 概览](https://platform.kimi.com/docs/api/overview)；[国际区 API 概览](https://platform.kimi.ai/docs/api/overview)
- K3 支持 `image_url`/`video_url` 多模态内容；图片可使用 base64 或上传后得到的 `ms://file_id`，不支持普通互联网图片 URL。支持 JPEG、PNG、GIF、WebP、BMP、HEIC、HEIF，不支持 SVG；官方建议图片不超过 4096×2160，请求体不超过 100 MB。[视觉模型指南](https://platform.kimi.com/docs/guide/use-kimi-vision-model)
- `response_format` 支持 `json_object` 和 `json_schema`；生产环境推荐 `json_schema` 加 `strict: true`，对象应设 `additionalProperties: false`。客户端还应检查 `finish_reason` 后再解析 `message.content`。[Structured Output 指南](https://platform.kimi.com/docs/guide/response_format)
- `/v1/files` 支持 `purpose=image` 的原生视觉文件上传；单文件上限 100 MB。[文件上传 API](https://platform.kimi.com/docs/api/files-upload)
- 429 过载应服从 `Retry-After` 并指数退避；余额不足不应重试。持续 500 错误应保留 `request_id` 供支持定位。[错误处理](https://platform.kimi.ai/docs/api/errors)

## 推荐请求契约

服务端请求应由以下三部分组成，API key 只能保存在服务器端：

```json
{
  "model": "kimi-k3",
  "reasoning_effort": "low",
  "messages": [
    {
      "role": "system",
      "content": "仅从可见证据抽取。不得猜测、补全或返回白名单外字段。"
    },
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "event=WEEK_0; allowed_fields=[...]; local_ocr_spans=[...]"
        },
        {
          "type": "image_url",
          "image_url": {
            "url": "data:image/png;base64,<confirmed-deidentified-derivative>"
          }
        }
      ]
    }
  ],
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "lab_candidates",
      "strict": true,
      "schema": {
        "type": "object",
        "additionalProperties": false,
        "properties": {
          "candidates": {
            "type": "array",
            "items": {
              "type": "object",
              "additionalProperties": false,
              "properties": {
                "field_code": {"type": "string"},
                "proposed_value": {"type": ["string", "null"]},
                "unit": {"type": ["string", "null"]},
                "evidence_text": {"type": "string"},
                "evidence_bbox": {
                  "type": ["array", "null"],
                  "items": {"type": "integer"}
                },
                "status": {
                  "type": "string",
                  "enum": ["read", "uncertain", "not_visible"]
                }
              },
              "required": [
                "field_code",
                "proposed_value",
                "unit",
                "evidence_text",
                "evidence_bbox",
                "status"
              ]
            }
          }
        },
        "required": ["candidates"]
      }
    }
  }
}
```

真实实现中，字段字典应从当前 `edc_event_ref` 对应的版本化 CRF 映射生成，而不是让模型自由创造字段代码。图片必须是已经人工确认的 `deidentified/...` 衍生文件，并在发送前再次验证其 SHA-256 与草稿记录一致。

## 合并与置信规则

模型自报 `confidence` 不应当作为临床置信度。建议由服务端根据可验证事实生成审核优先级：

- 本地 OCR 与 Kimi 的字段、值、单位完全一致：普通审核优先级。
- 值一致但单位冲突、字符形近或小数点冲突：高优先级人工核对。
- 只有 Kimi 读到、本地 OCR 未读到：必须显示证据裁剪图，不得自动接受。
- 只有本地 OCR 读到、Kimi 标记不确定：保留候选并标记冲突。
- 非白名单字段、缺失证据、范围/单位校验失败：拒绝入候选库并记录审计原因。

## 当前代码需要的改造点

1. 把 `KimiClient.extract_candidates(text)` 扩展为接收衍生图片、本地 OCR 结构和事件字段字典的混合输入。
2. 将 `json_object` 改为严格 `json_schema`，验证 `finish_reason`、响应大小、字段数和所有返回类型。
3. 新增幂等的 `hybrid-extract` 端点，只允许读取已确认的去标识化衍生文件，禁止读取原图。
4. 网页批量流程改为“确认遮盖 → 本地 OCR → Kimi 复核 → 合并候选”，并明确提示哪些图片会离开本机。
5. 保存模型 ID、schema/prompt 版本、请求/响应哈希、Moonshot `request_id`、OCR 引擎版本及一致/冲突状态；不得将 API key 或完整敏感响应写日志。
6. 加入 429/503/504 的有限指数退避、超时和断路保护；模型失败时保留本地 OCR 结果，不得阻断人工录入。
7. 用合成金标准检查单做 A/B 验证，至少比较字段召回率、字段精确率、数值完全一致率、单位一致率和需要人工修改的比例；在测得改善前不能宣称准确率提高。

## 隐私和合规边界

Moonshot 中国区公开隐私政策说明会收集输入的文字、图片、视频等，并可能用于模型优化；服务协议也不承诺输出准确，且允许将输入输出和反馈用于模型服务优化。公开条款没有零留存或不训练保证。[中国区隐私政策](https://platform.kimi.com/docs/agreement/userprivacy)；[开放平台服务协议](https://platform.kimi.com/docs/agreement/modeluse)

因此，当前只能用合成检查单或经过批准并人工确认的去标识化衍生图做接口验证。真实临床数据上线前仍需院方/伦理批准、正式 DPA、留存期与不训练条款、区域和跨境评估、访问控制及验证方案；不能把自动遮盖成功当作已经完成去标识化。

## 其他官方资源

- [Kimi K3 官方仓库](https://github.com/MoonshotAI/Kimi-K3)
- [官方 MFJS/JSON Schema 校验工具 Walle](https://github.com/MoonshotAI/walle)
