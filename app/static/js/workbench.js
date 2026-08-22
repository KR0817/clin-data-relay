    let token = null;
    let currentUser = null;
    let pendingUploadQueue = [];
    let intakeQueueLocked = false;
    let uploadQueueSequence = 0;
    let activeUploadBatch = [];
    let activeBatchPreviewUrls = [];
    let activeTransferId = null;
    let edcReadiness = { status: "blocked", write_path: "disabled" };
    let currentCandidatesById = new Map();
    let transfersByCandidateId = new Map();
    let activeBatchCandidateIds = new Set();
    let kimiServiceReady = false;
    let kimiUserEnabled = false;
    let kimiIntegrationState = "key_required";
    let fieldDictionaryHeaders = [];
    let dictionaryReleases = [];
    let activeDictionaryReleaseId = null;
    let currentDictionaryDraftId = null;
    let candidateQualityById = new Map();
    let recognitionFieldOptions = [];
    let selectedRecognitionFieldCodes = new Set();
    let productMode = "full";
    const CONFIRMED_LIST_LIMIT = 5;
    let confirmedRecordsExpanded = false;
    let activeRecognitionJobId = null;
    let activeRecognitionJob = null;
    let recognitionJobs = [];
    let setupCredential = null;
    let centreProfile = null;
    let loadedCandidateEvidenceIds = new Set();
    let candidateEvidenceUrls = new Map();

    const ROLE_LABELS = Object.freeze({
      principal_investigator: "牵头研究者",
      central_data_manager: "中央数据管理员",
      site_investigator: "中心研究者",
      monitor: "监查员（只读）",
      auditor: "审计员（只读）",
    });

    const WORKSPACE_ART_BY_MODE = Object.freeze({
      central: "/static/img/workbench-central-context.webp",
      oversight: "/static/img/workbench-central-context.webp",
      site: "/static/img/workbench-site-context.webp",
    });

    function workspaceModeFor(user) {
      if (!user) return "site";
      if (["principal_investigator", "central_data_manager"].includes(user.role)) return "central";
      if (["monitor", "auditor"].includes(user.role)) return "oversight";
      return "site";
    }

    function setWorkspaceNavigationCurrent(hash) {
      document.querySelectorAll(".workspace-nav a[href^='#']").forEach(function(link) {
        if (link.getAttribute("href") === hash) link.setAttribute("aria-current", "location");
        else link.removeAttribute("aria-current");
      });
    }

    function applyWorkspaceProjection() {
      if (!currentUser) return;
      const mode = workspaceModeFor(currentUser);
      const workflowWriteRoles = ["site_investigator", "central_data_manager"];
      const canWriteWorkflow = workflowWriteRoles.includes(currentUser.role);
      const centre = currentUser.centre_code || "全部授权中心";
      const roleLabel = ROLE_LABELS[currentUser.role] || currentUser.role;
      const projection = {
        central: {
          badge: "主中心",
          eyebrow: "中央协调工作区",
          title: "多中心研究控制台",
          summary: currentUser.role === "principal_investigator"
            ? "查看多中心研究进度、风险、确认结果与审计状态。"
            : "汇总中心进度，优先处理数据问题、版本差异与传输状态。",
          centre: "全部授权中心",
          focus: currentUser.role === "principal_investigator" ? "研究进度与风险监督" : "跨中心质量与数据汇总",
          boundary: roleLabel + " · 按服务器授权范围操作",
          actionLabel: "进入中央总览",
          actionTarget: "#operations-section",
        },
        site: {
          badge: "分中心",
          eyebrow: "中心数据采集工作区",
          title: centre + " 报告录入",
          summary: "按病人研究编号上传报告，完成去标识化确认、识别与候选审核。",
          centre: centre,
          focus: "报告录入、候选审核与中心包",
          boundary: roleLabel + " · 仅当前中心",
          actionLabel: "开始报告录入",
          actionTarget: "#intake-section",
        },
        oversight: {
          badge: "监督视图",
          eyebrow: "研究监督工作区",
          title: "多中心只读监督",
          summary: "查看获授权范围内的进度、数据问题、确认结果与审计状态。",
          centre: centre,
          focus: "进度、问题与审计证据",
          boundary: roleLabel + " · 不可录入或审核",
          actionLabel: "进入监督总览",
          actionTarget: "#operations-section",
        },
      }[mode];

      document.body.dataset.workspaceMode = mode;
      document.getElementById("workspace-context-art").setAttribute("src", WORKSPACE_ART_BY_MODE[mode]);
      document.getElementById("workspace-mode-badge").textContent = projection.badge;
      document.getElementById("workspace-context-eyebrow").textContent = projection.eyebrow;
      document.getElementById("workspace-context-title").textContent = projection.title;
      document.getElementById("workspace-context-summary").textContent = projection.summary;
      document.getElementById("workspace-context-centre").textContent = projection.centre;
      document.getElementById("workspace-context-focus").textContent = projection.focus;
      document.getElementById("workspace-context-boundary").textContent = projection.boundary;
      document.getElementById("workspace-primary-action-label").textContent = projection.actionLabel;
      document.getElementById("workspace-primary-action").setAttribute("href", projection.actionTarget);

      document.querySelectorAll(".workspace-nav [data-workspace-visible]").forEach(function(link) {
        const visibleModes = (link.dataset.workspaceVisible || "").split(",");
        let visible = visibleModes.includes(mode);
        const visibleRoles = (link.dataset.workspaceRoles || "").split(",").filter(Boolean);
        if (visibleRoles.length) visible = visible && visibleRoles.includes(currentUser.role);
        link.classList.toggle("workspace-projection-hidden", !visible);
        let label = link.dataset[mode + "Label"];
        if (currentUser.role === "principal_investigator" && link.getAttribute("href") === "#review-section") label = "候选查看";
        if (label) link.querySelector("span").textContent = label;
      });

      document.querySelectorAll(".workspace-write-only").forEach(function(element) {
        element.classList.toggle("workspace-projection-hidden", !canWriteWorkflow);
      });

      const dictionaryLink = document.getElementById("dictionary-nav-link");
      dictionaryLink.classList.toggle("hidden", currentUser.role !== "central_data_manager");
      const operations = document.getElementById("operations-section");
      operations.open = mode !== "site";
      setWorkspaceNavigationCurrent(projection.actionTarget);
    }

    function setStatus(elementId, message, tone) {
      const element = document.getElementById(elementId);
      if (!element) return;
      element.textContent = message || "";
      if (tone) element.dataset.tone = tone;
      else element.removeAttribute("data-tone");
    }

    function setBusy(button, busy, busyLabel) {
      if (!button) return;
      if (busy) {
        if (button.getAttribute("aria-busy") !== "true") button.dataset.idleLabel = button.textContent;
        button.textContent = busyLabel || "处理中…";
        button.disabled = true;
        button.setAttribute("aria-busy", "true");
      } else {
        button.textContent = button.dataset.idleLabel || button.textContent;
        button.disabled = false;
        button.removeAttribute("aria-busy");
      }
    }

    function applyProductMode(mode) {
      productMode = mode === "lite" ? "lite" : "full";
      const lite = productMode === "lite";
      document.body.classList.toggle("lite-mode", lite);
      document.getElementById("brand-kicker").textContent = lite
        ? "Clinical Report Extractor Lite"
        : "ClinData Relay";
      document.getElementById("app-title").textContent = lite
        ? "检查报告识别与导出"
        : "临床数据采集工作台";
      document.getElementById("environment-chip").textContent = lite
        ? "本地 Lite 版"
        : "合成数据沙箱";
      document.getElementById("confirmed-title").textContent = lite
        ? "本地已确认数据"
        : "已确认数据与 LibreClinica 提交";
      document.getElementById("download-submitted-excel").textContent = lite
        ? "导出已确认 Excel"
        : "导出已确认 Excel";
      if (lite) setStatus("edc-status", "");
    }

    function setProgress(stage) {
      ["upload", "review", "freeze", "submit"].forEach(function(name, index) {
        const element = document.getElementById("step-" + name);
        element.classList.toggle("complete", index + 1 < stage);
        element.classList.toggle("active", index + 1 === stage);
      });
    }

    function humanizeApiError(detail, status) {
      const messages = {
        deidentified_text_required: "图片中检测到直接身份信息，需要先核对本地遮盖草稿。",
        event_not_in_crf_mapping: "该访视不在当前数据字典中；请选择 WEEK_0、WEEK_4、WEEK_8 或 WEEK_12。",
        field_not_in_crf_mapping: "未识别到当前数据字典允许的检验项目。系统支持标准英文代码及版本化中文精确名称。",
        no_demo_lab_values_found: "没有识别出可解析的检验结果；请检查图片清晰度和项目名称。",
        deidentification_confirmation_required: "去标识化衍生图尚未人工确认。",
        deidentification_review_attestation_required: "必须确认所有直接身份区域均已遮盖。",
        subject_and_event_required_together: "必须同时填写受试者研究编号和访视。",
        subject_and_event_required_for_live_edc: "LibreClinica 已连接；上传前必须填写研究编号和访视。",
        pseudonymous_subject_ref_required: "研究编号格式不合规；只能使用大写字母开头的去标识化研究代码。",
        libreclinica_subject_provisioning_disabled: "LibreClinica 自动建号尚未启用。",
        libreclinica_subject_create_failed: "LibreClinica 未能创建该研究编号。",
        libreclinica_event_schedule_failed: "LibreClinica 已有研究编号，但未能安排该访视。",
        candidate_already_decided: "该候选已经审核，请刷新列表。",
        edited_value_required: "修改时必须填写确认后的值。",
        conflict_source_selection_required: "冲突项必须明确选择本地 OCR 值或 Kimi 值。",
        kimi_source_selection_required: "Kimi 单独识别项必须明确选择 Kimi 值。",
        manual_source_selection_required: "手工修改冲突项时必须标记为人工录入值。",
        candidate_evidence_acknowledgement_required: "请先加载去标识化证据图并确认已逐项核对。",
        candidate_deidentified_evidence_required: "该候选缺少已确认的去标识化证据图，不能接受。",
        bulk_override_forbidden: "只有中央数据管理员可以执行例外批量接受。",
        bulk_override_reason_required: "例外批量接受必须填写书面理由。",
        bulk_conflict_source_required: "例外接受冲突项时必须指定采用本地值或 Kimi 值。",
        bulk_evidence_acknowledgement_required: "例外批量接受前必须逐项加载全部去标识化证据图。",
        edc_adapter_disabled: "LibreClinica 提交闸门当前未就绪。",
        central_data_manager_required: "只有中央数据管理员可以管理表头。",
        spreadsheet_export_unavailable: "Excel 导出服务当前不可用。",
        spreadsheet_export_failed: "Excel 生成失败，请稍后重试。",
        quality_blocked: "该数值触发阻断级质量规则，不能接受或提交。",
        open_data_issue_blocks_transfer: "仍有未解决的数据问题，暂不能创建传输。",
        transfer_hold_active: "当前记录处于伴随模块传输暂停状态。",
        read_only_role: "当前账号为只读角色，不能执行此操作。",
        structured_import_invalid_schema: "CSV 表头不符合要求，请使用标准五列模板。",
        dictionary_release_not_draft: "所选字典版本不是可编辑草稿。",
        supported_report_upload_required: "仅支持检查单图片或肺功能 PDF。",
        unsupported_image_type: "检查单图片仅支持 PNG 或 JPEG。",
        image_signature_invalid: "图片类型与文件内容不一致，已拒绝上传。",
        image_decode_failed: "图片已损坏或无法安全解码。",
        image_dimensions_too_large: "图片像素尺寸过大，已拒绝上传。",
        local_ocr_output_too_large: "OCR 输出超过本地安全上限，已停止本次识别。",
        pdf_eof_marker_required: "PDF 文件不完整，未找到结束标记。",
        pdf_structure_too_complex: "PDF 结构超过本地安全限制，已拒绝处理。",
        pulmonary_pdf_required: "该操作需要有效的肺功能 PDF。",
        pdf_too_large: "PDF 超过 20 MiB，无法上传。",
        pdf_encrypted: "PDF 已加密，无法在本机读取。",
        pdf_text_layer_required: "PDF 没有可用文本层；请导出文字版肺功能报告。",
        pulmonary_report_values_not_found: "PDF 中未找到当前肺功能表头对应的结果行。",
        pulmonary_pdf_parse_failed: "PDF 解析失败，请确认文件完整且未损坏。",
        pulmonary_pdf_page_limit: "PDF 页数超出本地肺功能解析上限。",
        recognition_field_not_allowed: "选择中包含当前访视不允许识别的项目，请刷新项目列表。",
        recognition_job_already_running: "该识别任务正在运行中，请等待当前任务完成。",
        recognition_job_running: "识别任务正在运行中，暂不能取消。",
        offline_package_hash_mismatch: "中心数据包完整性校验失败，未导入。",
        offline_package_already_imported: "该中心数据包已经导入过。",
        offline_package_field_invalid: "中心数据包包含不允许的字段。",
        offline_package_mixed_centres: "中心数据包不能混合多个中心。",
        offline_package_passphrase_invalid: "数据包密码至少 12 位。",
        offline_package_decryption_failed: "数据包密码错误或数据包已损坏。",
        offline_package_dictionary_version_mismatch: "数据包字段字典版本与中央当前版本不一致。",
        centre_profile_required: "当前安装包没有中心身份配置。",
        centre_kimi_configuration_unavailable: "当前安装不是可配置 Kimi 的中心本地版。",
        centre_kimi_configuration_forbidden: "当前账号不能修改本中心 Kimi 密钥。",
        kimi_credential_write_failed: "Kimi 密钥未能安全写入本机，请使用备用配置命令。",
        kimi_configuration_invalid: "密钥已保存，但 Kimi 模型配置未通过本机校验。",
        setup_already_completed: "该中心账号已经完成首次设置，请直接登录。",
        password_confirmation_mismatch: "两次输入的密码不一致。",
        strong_password_required: "密码需为 16–128 位，并包含大写字母、小写字母、数字和符号。",
      };
      return messages[detail] || (typeof detail === "string" ? detail : "HTTP " + status);
    }

    async function api(path, options) {
      const requestOptions = Object.assign({ cache: "no-store" }, options || {});
      const headers = new Headers(requestOptions.headers || {});
      if (token) headers.set("Authorization", "Bearer " + token);
      const response = await fetch(path, Object.assign({}, requestOptions, { headers: headers }));
      const body = await response.json().catch(function() { return {}; });
      if (!response.ok) {
        const error = new Error(humanizeApiError(body.detail, response.status));
        error.code = body.detail;
        throw error;
      }
      return body;
    }

    function renderKimiPreference() {
      const button = document.getElementById("kimi-toggle");
      const active = kimiServiceReady && kimiUserEnabled;
      button.disabled = !kimiServiceReady;
      button.setAttribute("aria-checked", active ? "true" : "false");
      button.textContent = !kimiServiceReady ? "待配置" : active ? "已启用" : "仅本地";
      document.getElementById("kimi-toggle-help").textContent = !kimiServiceReady
        ? kimiIntegrationState === "key_required" ? "默认开启，请先配置本机密钥" : "服务未就绪"
        : active ? "当前批次将使用 Kimi" : "当前批次只用本地 OCR";
      const settingsButton = document.getElementById("show-kimi-settings");
      settingsButton.textContent = kimiServiceReady ? "更换密钥" : "配置密钥";
    }

    function renderRecognitionFieldOptions() {
      const query = document.getElementById("recognition-field-search").value.trim().toLowerCase();
      const visibleFields = recognitionFieldOptions
        .filter(function(field) {
          return !query || [field.field_code, field.display_header, field.source_header]
            .some(function(value) { return String(value || "").toLowerCase().includes(query); });
        })
        .sort(function(left, right) {
          const selectedDifference = Number(selectedRecognitionFieldCodes.has(right.field_code)) - Number(selectedRecognitionFieldCodes.has(left.field_code));
          return selectedDifference || left.field_code.localeCompare(right.field_code);
        });
      const container = document.getElementById("recognition-field-options");
      container.innerHTML = visibleFields.length
        ? visibleFields.map(function(field) {
            const code = escapeHtml(field.field_code);
            const checked = selectedRecognitionFieldCodes.has(field.field_code) ? " checked" : "";
            const category = field.category === "pulmonary_function" ? "肺功能" : "检验";
            return (
              '<label class="recognition-option" for="recognition-field-' + code + '">' +
                '<input id="recognition-field-' + code + '" type="checkbox" data-recognition-field-code="' + code + '"' + checked + '>' +
                '<span><strong>' + escapeHtml(field.display_header) + '</strong><br><span class="meta">' + code + " · " + category + "</span></span>" +
              "</label>"
            );
          }).join("")
        : '<p class="empty-state">没有符合搜索条件的项目。</p>';
      document.getElementById("recognition-field-summary").textContent =
        "已选 " + selectedRecognitionFieldCodes.size + " / " + recognitionFieldOptions.length + " 项";
    }

    function selectRecognitionFields(predicate) {
      selectedRecognitionFieldCodes = new Set(
        recognitionFieldOptions.filter(predicate).map(function(field) { return field.field_code; })
      );
      renderRecognitionFieldOptions();
      setStatus(
        "recognition-field-status",
        selectedRecognitionFieldCodes.size
          ? "本批次只会为已选项目创建候选。"
          : "至少选择一个项目后才能开始识别。",
        selectedRecognitionFieldCodes.size ? "success" : "warning"
      );
    }

    async function refreshRecognitionFields() {
      const eventRef = document.getElementById("event-ref").value;
      const uploadButton = document.getElementById("upload-and-recognize");
      uploadButton.disabled = true;
      setStatus("recognition-field-status", "正在加载当前访视项目…");
      try {
        const result = await api("/api/recognition-fields?event_ref=" + encodeURIComponent(eventRef));
        recognitionFieldOptions = result.fields || [];
        selectedRecognitionFieldCodes = new Set(
          recognitionFieldOptions.map(function(field) { return field.field_code; })
        );
        renderRecognitionFieldOptions();
        setStatus("recognition-field-status", "默认全选，可切换为仅肺功能或自定义项目。", "success");
      } catch (error) {
        recognitionFieldOptions = [];
        selectedRecognitionFieldCodes = new Set();
        renderRecognitionFieldOptions();
        setStatus("recognition-field-status", error.message, "error");
      } finally {
        renderPendingUploadQueue();
      }
    }

    async function refreshSystemCapabilities() {
      const health = await api("/api/health");
      applyProductMode(health.product_mode || "full");
      centreProfile = health.centre_profile || null;
      kimiIntegrationState = health.kimi_integration || "key_required";
      kimiServiceReady = health.kimi_integration === "ready";
      kimiUserEnabled = kimiServiceReady || health.kimi_default_enabled === true;
      if (!kimiServiceReady) kimiUserEnabled = false;
      renderKimiPreference();
      document.getElementById("show-kimi-settings").classList.toggle(
        "hidden",
        productMode !== "lite" || !centreProfile,
      );
      const readiness = health.production_readiness || {};
      const blockers = Object.values(readiness.blocking_reasons || {});
      setStatus(
        "production-status",
        "生产闸门：" + (readiness.status || "BLOCK") + (blockers.length ? " · " + blockers.slice(0, 3).join("、") : ""),
        readiness.status === "PASS" ? "success" : "warning"
      );
      const exportButton = document.getElementById("download-submitted-excel");
      const exportRole = currentUser && ["site_investigator", "central_data_manager"].includes(currentUser.role);
      exportButton.disabled = health.excel_export !== "ready" || !exportRole;
      document.getElementById("download-reviewed-package").disabled = !currentUser || currentUser.role !== "site_investigator";
      document.getElementById("offline-package-import-control").classList.toggle(
        "hidden",
        !currentUser || currentUser.role !== "central_data_manager",
      );
      if (!exportRole) {
        setStatus("export-status", "当前只读角色不能导出识别数据。", "warning");
      } else if (health.excel_export !== "ready") {
        setStatus("export-status", "Excel 一键导出服务未就绪。", "warning");
      } else {
        setStatus("export-status", "");
      }
    }

    function recognitionJobStatusLabel(status) {
      return {
        queued: "待执行",
        running: "识别中",
        succeeded: "已完成",
        failed: "有失败项",
        cancelled: "已取消",
      }[status] || status || "未创建";
    }

    function recognitionJobItemStatusLabel(status) {
      return {
        queued: "待执行",
        running: "识别中",
        succeeded: "完成",
        failed: "失败",
        cancelled: "已取消",
      }[status] || status;
    }

    function renderRecognitionJob(job) {
      const panel = document.getElementById("recognition-job-panel");
      if (!panel) return;
      activeRecognitionJob = job || null;
      activeRecognitionJobId = job ? job.id : null;
      panel.classList.toggle("hidden", !job);
      if (!job) return;
      const state = document.getElementById("recognition-job-state");
      state.textContent = recognitionJobStatusLabel(job.status);
      state.className = "tag " + (job.status === "succeeded" ? "confirmed" : job.status === "failed" ? "rejected" : job.status === "cancelled" ? "muted" : "queued");
      const failed = Number(job.failed_count || 0);
      document.getElementById("recognition-job-status").textContent =
        "任务 " + job.id.slice(0, 8) + " · " + Number(job.completed_count || 0) + " / " + Number(job.item_count || 0) + " 完成" +
        (failed ? " · " + failed + " 项失败" : "");
      document.getElementById("recognition-job-items").innerHTML = (job.items || []).map(function(item) {
        const error = item.error_code ? " · " + escapeHtml(item.error_code) : "";
        return '<li class="recognition-job-item"><span><strong>' + escapeHtml(item.edc_subject_ref) + " / " + escapeHtml(item.edc_event_ref) + '</strong> · ' + escapeHtml(item.source_file_id.slice(0, 8)) + '</span><span>' + escapeHtml(recognitionJobItemStatusLabel(item.status)) + error + '</span></li>';
      }).join("");
      const terminal = ["succeeded", "cancelled"].includes(job.status);
      document.getElementById("run-recognition-job").disabled = terminal || job.status === "running";
      document.getElementById("cancel-recognition-job").disabled = terminal || job.status === "running";
      document.getElementById("retry-recognition-job").disabled = failed === 0 || job.status === "running";
    }

    function recognitionJobCandidateIds(job) {
      return (job.items || []).flatMap(function(item) { return item.candidate_ids || []; });
    }

    function selectNewestPendingRecognitionBatch(candidates) {
      const pendingCandidateIds = new Set(
        candidates
          .filter(function(candidate) { return candidate.status === "candidate"; })
          .map(function(candidate) { return candidate.id; })
      );
      const activeBatchHasPending = Array.from(activeBatchCandidateIds).some(function(candidateId) {
        return pendingCandidateIds.has(candidateId);
      });
      if (activeBatchHasPending) return;

      const pendingJob = recognitionJobs.find(function(job) {
        return recognitionJobCandidateIds(job).some(function(candidateId) {
          return pendingCandidateIds.has(candidateId);
        });
      });
      activeBatchCandidateIds = new Set(pendingJob ? recognitionJobCandidateIds(pendingJob) : []);
      if (pendingJob && activeRecognitionJobId !== pendingJob.id) renderRecognitionJob(pendingJob);
    }

    async function refreshRecognitionJobs() {
      if (!token) return;
      try {
        recognitionJobs = await api("/api/recognition-jobs");
        const latestJob = recognitionJobs[0] || null;
        activeBatchCandidateIds = new Set(
          latestJob ? recognitionJobCandidateIds(latestJob) : []
        );
        renderRecognitionJob(latestJob);
        return latestJob;
      } catch (error) {
        recognitionJobs = [];
        activeBatchCandidateIds = new Set();
        renderRecognitionJob(null);
        setStatus("recognition-status", "识别任务状态暂不可用：" + error.message, "warning");
      }
    }

    async function refreshActiveRecognitionJob() {
      if (!activeRecognitionJobId) return;
      try {
        renderRecognitionJob(await api("/api/recognition-jobs/" + activeRecognitionJobId));
      } catch (error) {
        setStatus("recognition-job-status", error.message, "error");
      }
    }

    async function createRecognitionJobFromBatch(items) {
      const payloadItems = items.map(function(item) {
        return {
          source_file_id: item.originalSourceId,
          edc_subject_ref: item.subjectRef,
          edc_event_ref: item.eventRef,
          field_codes: item.selectedFieldCodes,
          use_kimi: Boolean(item.useKimi),
        };
      });
      if (!payloadItems.length) return null;
      const job = await api("/api/recognition-jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: payloadItems }),
      });
      renderRecognitionJob(job);
      return job;
    }

    async function runActiveRecognitionJob(button) {
      if (!activeRecognitionJobId) return;
      setBusy(button, true, "正在识别…");
      try {
        const job = await api("/api/recognition-jobs/" + activeRecognitionJobId + "/run", { method: "POST" });
        renderRecognitionJob(job);
        activeBatchCandidateIds = new Set(
          (job.items || []).flatMap(function(item) { return item.candidate_ids || []; })
        );
        await refreshCandidates();
        setStatus("recognition-status", job.status === "succeeded" ? "识别任务已完成，候选值已进入审核。" : "识别任务已更新，请查看失败项并重试。", job.status === "succeeded" ? "success" : "warning");
      } catch (error) {
        setStatus("recognition-job-status", error.message, "error");
      } finally {
        setBusy(button, false);
      }
    }

    async function cancelActiveRecognitionJob(button) {
      if (!activeRecognitionJobId) return;
      setBusy(button, true, "正在取消…");
      try {
        renderRecognitionJob(await api("/api/recognition-jobs/" + activeRecognitionJobId + "/cancel", { method: "POST" }));
      } catch (error) {
        setStatus("recognition-job-status", error.message, "error");
      } finally {
        setBusy(button, false);
      }
    }

    async function retryActiveRecognitionJob(button) {
      if (!activeRecognitionJobId) return;
      setBusy(button, true, "正在重试…");
      try {
        renderRecognitionJob(await api("/api/recognition-jobs/" + activeRecognitionJobId + "/retry", { method: "POST" }));
      } catch (error) {
        setStatus("recognition-job-status", error.message, "error");
      } finally {
        setBusy(button, false);
      }
    }

    async function downloadSubmittedExcel(button) {
      setBusy(button, true, "正在生成 Excel…");
      try {
        const response = await fetch("/api/exports/reviewed-recognition-data.xlsx", {
          headers: { Authorization: "Bearer " + token },
          cache: "no-store",
        });
        if (!response.ok) {
          const body = await response.json().catch(function() { return {}; });
          throw new Error(humanizeApiError(body.detail, response.status));
        }
        const disposition = response.headers.get("Content-Disposition") || "";
        const match = disposition.match(/filename="([^"]+)"/);
        const filename = match ? match[1] : "reviewed-recognition-data.xlsx";
        const url = URL.createObjectURL(await response.blob());
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        setStatus(
          "export-status",
          productMode === "lite"
            ? "Excel 已生成：仅包含本地已人工确认且实际识别到的项目。"
            : "Excel 已生成：仅包含已人工确认且实际识别到的项目，并标注 LibreClinica 提交状态。",
          "success"
        );
      } catch (error) {
        setStatus("export-status", error.message, "error");
      } finally {
        setBusy(button, false);
      }
    }

    async function downloadReviewedPackage(button) {
      setBusy(button, true, "正在生成数据包…");
      try {
        const packagePassphrase = document.getElementById("offline-package-passphrase").value;
        const form = new FormData();
        form.append("package_passphrase", packagePassphrase);
        const response = await fetch("/api/exports/reviewed-recognition-package.json", {
          method: "POST",
          headers: { Authorization: "Bearer " + token },
          body: form,
          cache: "no-store",
        });
        if (!response.ok) {
          const body = await response.json().catch(function() { return {}; });
          throw new Error(humanizeApiError(body.detail, response.status));
        }
        const disposition = response.headers.get("Content-Disposition") || "";
        const match = disposition.match(/filename="([^"]+)"/);
        const filename = match ? match[1] : "reviewed-recognition-package.json";
        const url = URL.createObjectURL(await response.blob());
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        setStatus("export-status", "中心数据包已生成，可交给中央数据管理员导入。", "success");
      } catch (error) {
        setStatus("export-status", error.message, "error");
      } finally {
        setBusy(button, false);
      }
    }

    async function importReviewedPackage(input) {
      const files = Array.from(input.files || []);
      if (!files.length) return;
      const packagePassphrase = document.getElementById("offline-package-passphrase").value;
      const form = new FormData();
      files.forEach(function(file) { form.append("files", file, file.name); });
      form.append("package_passphrase", packagePassphrase);
      setStatus("export-status", "正在校验并导入中心数据包…", "warning");
      try {
        const result = await api("/api/imports/reviewed-packages", {
          method: "POST",
          headers: { Authorization: "Bearer " + token },
          body: form,
        });
        const failures = result.results.filter(function(item) { return item.result === "failed"; });
        const failureText = failures.length ? " 失败：" + failures.map(function(item) { return item.filename + "（" + item.error_code + "）"; }).join("；") : "";
        setStatus("export-status", "中心数据包已导入：成功 " + result.imported_count + " 个，重复 " + result.duplicate_count + " 个，失败 " + result.failed_count + " 个。" + failureText, failures.length ? "warning" : "success");
        await refreshPackageImportLogs();
        await refreshCandidates();
      } catch (error) {
        setStatus("export-status", error.message, "error");
      } finally {
        input.value = "";
      }
    }

    function updateFileSelection() {
      const files = Array.from(document.getElementById("image-file").files || []);
      const summary = document.getElementById("file-selection-summary");
      if (!files.length) {
        summary.textContent = "尚未选择文件";
        return;
      }
      const names = files.slice(0, 2).map(function(file) { return file.name; }).join("、");
      summary.textContent = files.length + " 份：" + names + (files.length > 2 ? " 等" : "");
    }

    function isSupportedReportFile(file) {
      const mime = String(file.type || "").toLowerCase();
      const name = String(file.name || "").toLowerCase();
      const imageMimes = ["image/png", "image/jpeg", "image/webp", "image/bmp", "image/heic", "image/heif"];
      const imageSuffixes = [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".heic", ".heif"];
      return mime === "application/pdf" || name.endsWith(".pdf") || imageMimes.includes(mime) || imageSuffixes.some(function(suffix) { return name.endsWith(suffix); });
    }

    function queuedFileSignature(subjectRef, eventRef, file) {
      return [subjectRef, eventRef, file.name, file.size, file.lastModified].join("::");
    }

    function renderPendingUploadQueue() {
      const container = document.getElementById("patient-upload-queue");
      const count = document.getElementById("patient-upload-queue-count");
      if (!container || !count) return;
      const subjectCount = new Set(pendingUploadQueue.map(function(item) { return item.subjectRef; })).size;
      count.textContent = subjectCount + " 名病人 · " + pendingUploadQueue.length + " 份报告";
      container.innerHTML = pendingUploadQueue.length
        ? pendingUploadQueue.map(function(item) {
            return '<article class="queued-patient-report" data-queue-id="' + escapeHtml(item.queueId) + '">' +
              '<div><strong>' + escapeHtml(item.subjectRef) + '</strong><span class="meta">' + escapeHtml(item.eventRef) + '</span></div>' +
              '<span class="queue-file">' + escapeHtml(item.fileName) + (item.useKimi ? " · Kimi" : " · 本地 OCR") + '</span>' +
              '<button class="text-button" data-action="remove-queued-report" data-queue-id="' + escapeHtml(item.queueId) + '" type="button"' + (intakeQueueLocked ? " disabled" : "") + '>移除</button></article>';
          }).join("")
        : '<p class="empty-state">尚未加入报告。</p>';
      const addButton = document.getElementById("add-patient-reports");
      const uploadButton = document.getElementById("upload-and-recognize");
      if (addButton) addButton.disabled = intakeQueueLocked || recognitionFieldOptions.length === 0;
      if (uploadButton) uploadButton.disabled = intakeQueueLocked || pendingUploadQueue.length === 0;
    }

    function setIntakeQueueLocked(locked) {
      intakeQueueLocked = locked;
      ["subject-ref", "event-ref", "image-file"].forEach(function(id) {
        const element = document.getElementById(id);
        if (element) element.disabled = locked;
      });
      renderPendingUploadQueue();
    }

    function addPatientReportsToQueue() {
      if (intakeQueueLocked) return false;
      const subjectInput = document.getElementById("subject-ref");
      const subjectRef = subjectInput.value.trim().toUpperCase();
      const eventRef = document.getElementById("event-ref").value;
      const files = Array.from(document.getElementById("image-file").files || []);
      subjectInput.value = subjectRef;
      if (!/^[A-Z][A-Z0-9_-]{2,63}$/.test(subjectRef)) {
        setStatus("source-status", "请输入大写字母开头的去标识化病人研究编号。", "error");
        subjectInput.focus();
        return false;
      }
      if (!files.length) {
        setStatus("source-status", "请为该病人至少选择一份检查报告。", "error");
        document.getElementById("image-file").focus();
        return false;
      }
      const unsupported = files.filter(function(file) { return !isSupportedReportFile(file); });
      if (unsupported.length) {
        setStatus("source-status", "不支持的文件：" + unsupported.map(function(file) { return file.name; }).join("、"), "error");
        return false;
      }
      const selectedFieldCodes = Array.from(selectedRecognitionFieldCodes);
      if (!selectedFieldCodes.length) {
        setStatus("source-status", "请先选择至少一个要识别的项目。", "error");
        return false;
      }
      const signatures = new Set(pendingUploadQueue.map(function(item) { return item.signature; }));
      let added = 0;
      files.forEach(function(file) {
        const signature = queuedFileSignature(subjectRef, eventRef, file);
        if (signatures.has(signature)) return;
        uploadQueueSequence += 1;
        pendingUploadQueue.push({
          queueId: "queued-" + uploadQueueSequence,
          signature: signature,
          file: file,
          fileName: file.name,
          subjectRef: subjectRef,
          eventRef: eventRef,
          selectedFieldCodes: selectedFieldCodes.slice(),
          useKimi: !file.name.toLowerCase().endsWith(".pdf") && kimiServiceReady && kimiUserEnabled,
        });
        signatures.add(signature);
        added += 1;
      });
      renderPendingUploadQueue();
      if (!added) {
        setStatus("source-status", "所选报告已经在该病人队列中。", "warning");
        return false;
      }
      document.getElementById("image-file").value = "";
      updateFileSelection();
      subjectInput.value = "";
      setStatus("source-status", "已加入 " + added + " 份报告，可继续填写下一名病人。", "success");
      return true;
    }

    function removeQueuedPatientReport(queueId) {
      if (intakeQueueLocked) return;
      pendingUploadQueue = pendingUploadQueue.filter(function(item) { return item.queueId !== queueId; });
      renderPendingUploadQueue();
      setStatus("source-status", "已从待上传队列移除报告。", "success");
    }

    function escapeHtml(value) {
      return String(value == null ? "" : value).replace(/[&<>'"]/g, function(char) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char];
      });
    }

    function renderOperationsDashboard(dashboard) {
      const overall = dashboard.overall || {};
      const metrics = [
        ["受试者", overall.subjects || 0, ""],
        ["访视", overall.visits || 0, ""],
        ["待审核", overall.pending_reviews || 0, overall.pending_reviews ? "warning" : ""],
        ["开放问题", overall.open_data_issues || 0, overall.open_data_issues ? "warning" : ""],
        ["质量阻断", overall.blocking_findings || 0, overall.blocking_findings ? "danger" : ""],
        ["开放待办", overall.open_tasks || 0, overall.open_tasks ? "warning" : ""],
        ["回读异常", (overall.readback || {}).mismatch || 0, (overall.readback || {}).mismatch ? "danger" : ""],
      ];
      document.getElementById("operations-metrics").innerHTML = metrics.map(function(metric) {
        return '<article class="metric-card"' + (metric[2] ? ' data-tone="' + metric[2] + '"' : "") + '><span>' +
          escapeHtml(metric[0]) + '</span><strong>' + escapeHtml(metric[1]) + '</strong></article>';
      }).join("");
    }

    function renderOperationsTasks(tasks) {
      document.getElementById("tasks-count").textContent = tasks.length + " 项";
      document.getElementById("operations-tasks").innerHTML = tasks.length ? tasks.map(function(task) {
        const canComplete = task.task_type !== "data_issue_response" && currentUser && currentUser.role === "central_data_manager";
        return '<article class="ops-item"><strong>' + escapeHtml(task.title) + '</strong>' +
          '<p>' + escapeHtml(task.centre_code) + ' · ' + escapeHtml(task.task_type) + ' · ' + escapeHtml(task.created_at) + '</p>' +
          (task.task_type === "data_issue_response" ? '<p>请在右侧数据问题中完成答复。</p>' : "") +
          (canComplete ? '<div class="actions"><button class="secondary" data-action="complete-task" data-task-id="' + escapeHtml(task.id) + '" type="button">标记完成</button></div>' : "") +
          '</article>';
      }).join("") : '<p class="empty-state">当前没有开放待办。</p>';
    }

    function renderOperationsIssues(issues) {
      document.getElementById("issues-count").textContent = issues.length + " 项";
      document.getElementById("operations-issues").innerHTML = issues.length ? issues.map(function(issue) {
        const id = escapeHtml(issue.id);
        let action = "";
        if (issue.status === "open" && currentUser.role === "site_investigator") {
          action = '<input data-issue-message="' + id + '" maxlength="1000" aria-label="数据问题答复" placeholder="输入来源核对结果">' +
            '<div class="actions"><button data-action="answer-issue" data-issue-id="' + id + '" type="button">提交答复</button></div>';
        } else if (issue.status === "answered" && currentUser.role === "central_data_manager") {
          action = '<input data-issue-message="' + id + '" maxlength="1000" aria-label="问题解决说明" placeholder="解决说明（选填）">' +
            '<div class="actions"><button class="success" data-action="resolve-issue" data-issue-id="' + id + '" type="button">确认解决</button></div>';
        } else if (issue.status === "resolved" && currentUser.role === "central_data_manager") {
          action = '<input data-issue-message="' + id + '" maxlength="1000" aria-label="重新打开原因" placeholder="重新打开原因">' +
            '<div class="actions"><button class="warn" data-action="reopen-issue" data-issue-id="' + id + '" type="button">重新打开</button></div>';
        }
        return '<article class="ops-item"><strong>' + escapeHtml(issue.status.toUpperCase()) + ' · ' + escapeHtml(issue.centre_code) + '</strong>' +
          '<p>候选 ' + escapeHtml(issue.candidate_id) + '</p><p>' + escapeHtml(issue.opened_message) + '</p>' +
          (issue.answer_message ? '<p>答复：' + escapeHtml(issue.answer_message) + '</p>' : "") + action + '</article>';
      }).join("") : '<p class="empty-state">当前没有伴随模块数据问题。</p>';
    }

    function renderAnalysisSnapshots(snapshots) {
      document.getElementById("analysis-snapshots").innerHTML = snapshots.length ? snapshots.slice().reverse().map(function(snapshot) {
        return '<article class="ops-item"><strong>' + escapeHtml(snapshot.row_count) + ' 行 · ' + escapeHtml(snapshot.integrity) + '</strong>' +
          '<p>SHA-256 ' + escapeHtml(snapshot.content_sha256) + '</p>' +
          '<div class="actions"><button class="secondary" data-action="download-snapshot" data-snapshot-id="' + escapeHtml(snapshot.id) + '" type="button">下载 JSON</button></div></article>';
      }).join("") : '<p class="empty-state">尚未创建分析快照。</p>';
    }

    function renderUserAccounts(accounts) {
      document.getElementById("user-accounts").innerHTML = accounts.map(function(account) {
        const mutable = !["central_data_manager", "system_administrator"].includes(account.role);
        const action = mutable
          ? '<button class="secondary" data-action="' + (account.active ? "deactivate-account" : "reactivate-account") + '" data-account-id="' + escapeHtml(account.id) + '" type="button">' + (account.active ? "停用" : "重新启用") + '</button>'
          : "";
        return '<article class="ops-item"><strong>' + escapeHtml(account.username) + '</strong><p>' + escapeHtml(account.role) + ' · ' + escapeHtml(account.centre_code || "CENTRAL") + ' · ' + (account.active ? "启用" : "停用") + '</p><div class="actions">' + action + '</div></article>';
      }).join("");
    }

    async function refreshUserAccounts() {
      renderUserAccounts(await api("/api/admin/users"));
    }

    function renderPackageImportLogs(logs) {
      const target = document.getElementById("package-import-logs");
      if (!logs.length) {
        target.innerHTML = '<p class="empty-state">暂无中心包导入记录</p>';
        return;
      }
      target.innerHTML = logs.slice(0, 20).map(function(log) {
        const outcome = log.result === "imported" ? "成功" : log.result === "duplicate" ? "重复" : "失败";
        const detail = log.error_code ? " · " + log.error_code + (log.error_detail ? "：" + log.error_detail : "") : " · 新增 " + log.created_count + "，重复 " + log.duplicate_count;
        return '<article class="ops-item"><strong>' + escapeHtml(log.source_filename || "中心包") + '</strong><p>' + escapeHtml(outcome + " · " + (log.centre_code || "未知中心") + detail) + '</p><small>' + escapeHtml(log.created_at || "") + (log.package_sha256 ? " · SHA-256 " + escapeHtml(log.package_sha256.slice(0, 16)) + "…" : "") + '</small></article>';
      }).join("");
    }

    async function refreshPackageImportLogs() {
      if (!token || !currentUser || currentUser.role !== "central_data_manager") return;
      renderPackageImportLogs(await api("/api/imports/reviewed-package-logs?limit=100"));
    }

    async function refreshOperations() {
      if (!token) return;
      setStatus("operations-status", "正在刷新运营状态…");
      try {
        const results = await Promise.all([
          api("/api/dashboard"),
          api("/api/tasks?status=open"),
          api("/api/data-issues"),
        ]);
        renderOperationsDashboard(results[0]);
        renderOperationsTasks(results[1]);
        renderOperationsIssues(results[2]);
        const centralControls = document.getElementById("central-operations-controls");
        centralControls.classList.toggle("hidden", currentUser.role !== "central_data_manager");
        if (currentUser.role === "central_data_manager") {
          const centralResults = await Promise.all([api("/api/analysis-snapshots"), api("/api/admin/users"), api("/api/imports/reviewed-package-logs?limit=100")]);
          renderAnalysisSnapshots(centralResults[0]);
          renderUserAccounts(centralResults[1]);
          renderPackageImportLogs(centralResults[2]);
        }
        setStatus("operations-status", "运营状态已刷新；正式 EDC 工作流仍以 LibreClinica 为准。", "success");
      } catch (error) {
        setStatus("operations-status", error.message, "error");
      }
    }

    async function transitionIssue(issueId, action, button) {
      const input = document.querySelector('[data-issue-message="' + CSS.escape(issueId) + '"]');
      const message = input ? input.value.trim() : "";
      if ((action === "answer" || action === "reopen") && !message) {
        setStatus("operations-status", "请先填写处理内容。", "error");
        if (input) input.focus();
        return;
      }
      setBusy(button, true, "正在保存…");
      try {
        await api("/api/data-issues/" + issueId + "/" + action, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: message || null }),
        });
        await refreshOperations();
      } catch (error) {
        setStatus("operations-status", error.message, "error");
        setBusy(button, false);
      }
    }

    async function appendTransferHold(action, button) {
      const scope = document.getElementById("hold-scope").value;
      const payload = {
        scope: scope,
        action: action,
        reason: document.getElementById("hold-reason").value.trim(),
      };
      if (scope !== "dataset") payload.centre_code = document.getElementById("hold-centre").value.trim().toUpperCase();
      if (["subject", "visit"].includes(scope)) payload.subject_ref = document.getElementById("hold-subject").value.trim().toUpperCase();
      if (scope === "visit") payload.event_ref = document.getElementById("hold-event").value.trim().toUpperCase();
      if (!payload.reason) {
        setStatus("hold-status", "请填写暂停或解除原因。", "error");
        return;
      }
      setBusy(button, true, "正在记录…");
      try {
        const result = await api("/api/transfer-holds", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        setStatus("hold-status", result.scope_key + (result.effective ? " 已暂停" : " 已解除"), result.effective ? "warning" : "success");
        await refreshOperations();
      } catch (error) {
        setStatus("hold-status", error.message, "error");
      } finally {
        setBusy(button, false);
      }
    }

    async function uploadStructuredCsv(button) {
      const file = document.getElementById("structured-csv-file").files[0];
      const attested = document.getElementById("structured-csv-attestation").checked;
      if (!file || !attested) {
        setStatus("structured-import-status", "请选择 CSV 并确认数据边界。", "error");
        return;
      }
      const form = new FormData();
      form.append("file", file);
      form.append("synthetic_attestation", "true");
      if (currentUser.role === "central_data_manager") form.append("centre_code", document.getElementById("hold-centre").value.trim().toUpperCase());
      setBusy(button, true, "正在校验并导入…");
      try {
        const result = await api("/api/imports/structured-csv", { method: "POST", body: form });
        result.candidates.forEach(function(candidate) { activeBatchCandidateIds.add(candidate.id); });
        setStatus("structured-import-status", "已创建 " + result.created_count + " 条候选，跳过重复 " + result.duplicate_count + " 条，质量阻断 " + result.blocked_count + " 条。", result.blocked_count ? "warning" : "success");
        await refreshCandidates();
        await refreshOperations();
      } catch (error) {
        setStatus("structured-import-status", error.message, "error");
      } finally {
        setBusy(button, false);
      }
    }

    async function createAnalysisSnapshot(button) {
      setBusy(button, true, "正在创建…");
      try {
        const snapshot = await api("/api/analysis-snapshots", { method: "POST" });
        setStatus("snapshot-status", "快照已创建并校验：" + snapshot.content_sha256, "success");
        renderAnalysisSnapshots(await api("/api/analysis-snapshots"));
      } catch (error) {
        setStatus("snapshot-status", error.message, "error");
      } finally {
        setBusy(button, false);
      }
    }

    async function createUserAccount(button) {
      const role = document.getElementById("account-role").value;
      const payload = {
        username: document.getElementById("account-username").value.trim(),
        role: role,
      };
      if (role === "site_investigator") payload.centre_code = document.getElementById("account-centre").value.trim().toUpperCase();
      if (!payload.username) {
        setStatus("account-status", "请填写账号邮箱。", "error");
        return;
      }
      setBusy(button, true, "正在创建…");
      try {
        const account = await api("/api/admin/users", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        setStatus("account-status", "账号已创建。一次性合成环境初始密码：" + account.bootstrap_password, "success");
        await refreshUserAccounts();
      } catch (error) {
        setStatus("account-status", error.message, "error");
      } finally {
        setBusy(button, false);
      }
    }

    async function createCentreAccounts(button) {
      const accounts = document.getElementById("centre-account-batch").value.split(/\r?\n/)
        .map(function(line) { return line.trim(); })
        .filter(Boolean)
        .map(function(line) {
          const parts = line.split(/[;,]/).map(function(value) { return value.trim(); });
          return { centre_code: (parts[0] || "").toUpperCase(), username: parts[1] || "" };
        });
      if (!accounts.length || accounts.some(function(item) { return !item.centre_code || !item.username; })) {
        setStatus("account-status", "请按“中心代码, 邮箱”逐行填写。", "error");
        return;
      }
      setBusy(button, true, "正在生成…");
      try {
        const result = await api("/api/admin/centre-accounts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ accounts: accounts }),
        });
        setStatus(
          "account-status",
          "已生成 " + result.accounts.length + " 个中心账号；一次性密码：" +
            result.accounts.map(function(account) { return account.centre_code + "=" + account.bootstrap_password; }).join("；"),
          "success"
        );
        document.getElementById("centre-account-batch").value = "";
        await refreshUserAccounts();
      } catch (error) {
        setStatus("account-status", error.message, "error");
      } finally {
        setBusy(button, false);
      }
    }

    async function downloadSnapshot(snapshotId) {
      const response = await fetch("/api/analysis-snapshots/" + snapshotId + "/download", { headers: { Authorization: "Bearer " + token }, cache: "no-store" });
      if (!response.ok) {
        const body = await response.json().catch(function() { return {}; });
        throw new Error(humanizeApiError(body.detail, response.status));
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "analysis-snapshot-" + snapshotId + ".json";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    }

    function reviewStatusLabel(status) {
      return { candidate: "待审核", human_confirmed: "已确认", rejected: "已拒绝" }[status] || status;
    }

    function transferStatusLabel(status) {
      return { queued: "已冻结待提交", submitted: "已写入", failed: "提交失败", reconciled: "已人工对账" }[status] || status;
    }

    function renderFieldDictionary() {
      const search = document.getElementById("field-dictionary-search").value.trim().toLocaleLowerCase();
      const eventFilter = document.getElementById("field-dictionary-event").value;
      const filtered = fieldDictionaryHeaders.filter(function(header) {
        const matchesEvent = !eventFilter
          || (eventFilter === "EXCLUDED" ? !header.editable : header.event_ref === eventFilter);
        const haystack = [header.source_header, header.display_header, header.field_code, header.source_group]
          .join(" ").toLocaleLowerCase();
        return matchesEvent && (!search || haystack.includes(search));
      });
      document.getElementById("field-dictionary-count").textContent = filtered.length + " / " + fieldDictionaryHeaders.length + " 个表头";
      document.getElementById("field-dictionary-rows").innerHTML = filtered.length
        ? filtered.map(function(header) {
            const key = escapeHtml((header.event_ref || "") + "::" + (header.field_code || ""));
            const editor = header.editable
              ? '<input data-header-key="' + key + '" value="' + escapeHtml(header.display_header) + '" maxlength="200" aria-label="' + escapeHtml(header.field_code) + ' 当前显示表头">'
              : '<span class="immutable">' + escapeHtml(header.display_header) + '</span>';
            const statusText = header.editable
              ? (header.revision ? "已修订 v" + header.revision : "可修改")
              : (header.target_kind === "excluded_direct_identifier" ? "直接身份字段，已排除" : "结构字段，只读");
            const action = header.editable
              ? '<button class="secondary" data-action="save-field-header" data-event-ref="' + escapeHtml(header.event_ref) + '" data-field-code="' + escapeHtml(header.field_code) + '" type="button">保存</button>'
              : '<span class="immutable">—</span>';
            return '<tr>' +
              '<td>' + escapeHtml(header.column == null ? "—" : header.column) + '</td>' +
              '<td>' + escapeHtml(header.event_ref || "—") + '</td>' +
              '<td><code>' + escapeHtml(header.field_code || "—") + '</code></td>' +
              '<td>' + escapeHtml(header.source_header) + '</td>' +
              '<td>' + editor + '</td>' +
              '<td>' + escapeHtml(statusText) + '</td>' +
              '<td>' + action + '</td>' +
            '</tr>';
          }).join("")
        : '<tr><td colspan="7" class="immutable">没有符合筛选条件的表头。</td></tr>';
    }

    function renderDictionaryReleases() {
      const select = document.getElementById("dictionary-release-select");
      select.innerHTML = dictionaryReleases.slice().reverse().map(function(release) {
        const label = release.version + " · " + release.status + (release.active ? " · 当前" : "") + (release.rollback_of ? " · 回滚" : "");
        return '<option value="' + escapeHtml(release.id) + '"' + (release.active ? " selected" : "") + '>' + escapeHtml(label) + '</option>';
      }).join("");
      currentDictionaryDraftId = (dictionaryReleases.find(function(release) { return release.status === "draft"; }) || {}).id || null;
      document.getElementById("publish-dictionary-draft").disabled = !currentDictionaryDraftId;
    }

    async function refreshDictionaryReleases() {
      const result = await api("/api/admin/dictionary-releases");
      dictionaryReleases = result.releases || [];
      activeDictionaryReleaseId = result.active_release_id;
      renderDictionaryReleases();
    }

    async function createDictionaryDraft(button) {
      setBusy(button, true, "正在创建…");
      try {
        const draft = await api("/api/admin/dictionary-releases/draft", { method: "POST" });
        currentDictionaryDraftId = draft.id;
        await refreshDictionaryReleases();
        setStatus("dictionary-release-status", "草稿 " + draft.version + " 已打开；后续表头保存进入草稿，发布前不影响识别。", "success");
      } catch (error) {
        setStatus("dictionary-release-status", error.message, "error");
      } finally {
        setBusy(button, false);
      }
    }

    async function publishDictionaryDraft(button) {
      if (!currentDictionaryDraftId) return;
      setBusy(button, true, "正在发布…");
      try {
        const published = await api("/api/admin/dictionary-releases/" + currentDictionaryDraftId + "/publish", { method: "POST" });
        currentDictionaryDraftId = null;
        setStatus("dictionary-release-status", "字典版本 " + published.version + " 已原子发布。", "success");
        await refreshFieldDictionary();
      } catch (error) {
        setStatus("dictionary-release-status", error.message, "error");
      } finally {
        setBusy(button, false);
      }
    }

    async function rollbackDictionaryRelease(button) {
      const releaseId = document.getElementById("dictionary-release-select").value;
      if (!releaseId) return;
      setBusy(button, true, "正在回滚…");
      try {
        const release = await api("/api/admin/dictionary-releases/" + releaseId + "/rollback", { method: "POST" });
        setStatus("dictionary-release-status", "已创建新的回滚版本 " + release.version + "；历史版本未被覆盖。", "success");
        await refreshFieldDictionary();
      } catch (error) {
        setStatus("dictionary-release-status", error.message, "error");
      } finally {
        setBusy(button, false);
      }
    }

    async function refreshFieldDictionary() {
      if (!currentUser || currentUser.role !== "central_data_manager") return;
      const section = document.getElementById("field-dictionary-section");
      section.classList.remove("hidden");
      setStatus("field-dictionary-status", "正在加载当前数据字典…");
      try {
        const result = await api("/api/admin/field-dictionary");
        fieldDictionaryHeaders = result.headers || [];
        await refreshDictionaryReleases();
        renderFieldDictionary();
        setStatus(
          "field-dictionary-status",
          "已加载 " + fieldDictionaryHeaders.length + " 个原始 Excel 表头；当前发布版本 " + (result.active_release ? result.active_release.version : "未建立") + "。",
          "success"
        );
      } catch (error) {
        setStatus("field-dictionary-status", error.message, "error");
      }
    }

    async function saveFieldHeader(eventRef, fieldCode, button) {
      const key = eventRef + "::" + fieldCode;
      const input = document.querySelector('[data-header-key="' + CSS.escape(key) + '"]');
      const displayHeader = input ? input.value.trim() : "";
      if (!displayHeader) {
        setStatus("field-dictionary-status", "表头不能为空。", "error");
        if (input) input.focus();
        return;
      }
      setBusy(button, true, "正在保存…");
      try {
        const path = currentDictionaryDraftId
          ? "/api/admin/dictionary-releases/" + currentDictionaryDraftId + "/items/" + encodeURIComponent(eventRef) + "/" + encodeURIComponent(fieldCode)
          : "/api/admin/field-dictionary/" + encodeURIComponent(eventRef) + "/" + encodeURIComponent(fieldCode);
        const updated = await api(
          path,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ display_header: displayHeader }),
          }
        );
        fieldDictionaryHeaders = fieldDictionaryHeaders.map(function(header) {
          return header.event_ref === eventRef && header.field_code === fieldCode
            ? Object.assign({}, header, updated)
            : header;
        });
        renderFieldDictionary();
        setStatus(
          "field-dictionary-status",
          eventRef + " / " + fieldCode + (currentDictionaryDraftId ? " 已保存到草稿；发布后生效。" : " 已生成并发布兼容版本；字段代码和 OID 未改变。"),
          "success"
        );
        if (!currentDictionaryDraftId) await refreshFieldDictionary();
      } catch (error) {
        setStatus("field-dictionary-status", error.message, "error");
        setBusy(button, false);
      }
    }

    function renderPendingCandidate(candidate) {
      const id = escapeHtml(candidate.id);
      const reviewed = candidate.reviewed_by
        ? '<div class="meta">审核：' + escapeHtml(candidate.reviewed_by) + "；" + escapeHtml(candidate.review_reason || "未填写说明") + "</div>"
        : "";
      let actions = "";
      let inlineReview = "";
      let issueControl = "";
      let evidenceControl = "";
      const reviewer = currentUser && ["site_investigator", "central_data_manager"].includes(currentUser.role);
      const agreementLabels = {
        agreement: "本地 OCR 与 Kimi 一致",
        conflict: "本地 OCR 与 Kimi 冲突，请重点核对",
        kimi_only: "仅 Kimi 识别到，请核对图片证据",
        local_only: "仅本地 OCR",
        local_fallback: "Kimi 不可用，已回退到本地 OCR",
        local_pdf_text: "肺功能 PDF 本地文本层",
      };
      const localValueLabel = candidate.origin_type === "pdf_text" ? "本地解析值 " : "本地 OCR 值 ";
      const extractionMeta = candidate.extraction_agreement
        ? '<div class="meta">识别来源：' + escapeHtml(agreementLabels[candidate.extraction_agreement] || candidate.extraction_agreement) +
          (candidate.local_ocr_value ? " · " + localValueLabel + escapeHtml(candidate.local_ocr_value) + " " + escapeHtml(candidate.local_ocr_unit || "") : "") +
          (candidate.evidence_text ? " · 解析证据 “" + escapeHtml(candidate.evidence_text) + "”" : "") +
          " · 模型 " + escapeHtml(candidate.kimi_model || "未使用") + "</div>"
        : "";
      const evidence = candidate.extraction_evidence;
      const evidenceMeta = evidence
        ? '<div class="meta">证据契约：' + escapeHtml(evidence.engine || "local") +
          " / " + escapeHtml(evidence.engine_version || "") +
          " · 页面 " + escapeHtml((evidence.page_dimensions || []).length) +
          " · 耗时 " + escapeHtml(evidence.duration_ms || 0) + " ms" +
          (evidence.warnings && evidence.warnings.length ? " · 警告 " + escapeHtml(evidence.warnings.join(", ")) : "") +
          "</div>"
        : "";
      const quality = candidateQualityById.get(candidate.id);
      const qualityMeta = quality
        ? '<div class="meta">质量规则：<span class="tag ' + (quality.status === "BLOCK" ? "rejected" : quality.status === "WARN" ? "queued" : "confirmed") + '">' + escapeHtml(quality.status) + '</span> · ' + escapeHtml(quality.rule_version) + '</div>'
        : '<div class="meta">质量规则：正在加载</div>';
      const riskyReview = ["conflict", "kimi_only"].includes(candidate.extraction_agreement);
      const displayedCandidateValue = candidate.extraction_agreement === "conflict"
        ? "待选择（本地 " + (candidate.local_ocr_value || "无值") + " / Kimi " + candidate.proposed_value + "）"
        : (candidate.final_value || candidate.proposed_value) + " " + (candidate.unit || "");
      if (candidate.status === "candidate" && reviewer) {
        const acceptAction = riskyReview
          ? '<button data-action="open-review" data-decision="accept" data-candidate-id="' + id + '" type="button">核对后接受</button>'
          : '<button data-action="accept-candidate" data-candidate-id="' + id + '" type="button">接受该值</button>';
        actions =
          acceptAction +
          '<button class="warn" data-action="open-review" data-decision="edit" data-candidate-id="' + id + '" type="button">修改</button>' +
          '<button class="danger" data-action="open-review" data-decision="reject" data-candidate-id="' + id + '" type="button">拒绝</button>';
        const conflictChoices = candidate.extraction_agreement === "conflict"
          ? '<fieldset class="review-source-choice"><legend>明确选择确认来源</legend>' +
              '<label><input type="radio" name="review-source-' + id + '" value="local"> 本地 OCR：' + escapeHtml(candidate.local_ocr_value || "无值") + " " + escapeHtml(candidate.local_ocr_unit || "") + '</label>' +
              '<label><input type="radio" name="review-source-' + id + '" value="kimi"> Kimi：' + escapeHtml(candidate.proposed_value) + " " + escapeHtml(candidate.unit || "") + '</label>' +
            '</fieldset>'
          : "";
        const evidenceAttestation = riskyReview
          ? '<label class="review-evidence-attestation"><input type="checkbox" data-review-evidence-attestation="' + id + '"> 我已打开并逐项核对下方去标识化证据图</label>'
          : "";
        inlineReview =
          '<div id="review-form-' + id + '" class="inline-review hidden" data-review-form="' + id + '">' +
            conflictChoices +
            '<div class="inline-review-grid">' +
              '<label class="review-value-field" for="review-value-' + id + '">确认后的值' +
                '<input id="review-value-' + id + '" data-review-value="' + id + '" maxlength="200" value="' + escapeHtml(riskyReview ? "" : (candidate.final_value || candidate.proposed_value)) + '" autocomplete="off">' +
              "</label>" +
              '<label for="review-note-' + id + '">审核说明 <span class="optional">选填，不得包含身份信息</span>' +
                '<textarea id="review-note-' + id + '" data-review-note="' + id + '" maxlength="500" placeholder="可留空"></textarea>' +
              "</label>" +
            "</div>" +
            evidenceAttestation +
            '<p id="review-status-' + id + '" class="status" aria-live="polite"></p>' +
            '<div class="actions">' +
              '<button class="secondary" data-action="cancel-review" data-candidate-id="' + id + '" type="button">取消</button>' +
              '<button data-action="confirm-review" data-candidate-id="' + id + '" type="button">确认</button>' +
            "</div>" +
          "</div>";
        if (riskyReview) {
          const existingEvidenceUrl = candidateEvidenceUrls.get(candidate.id);
          evidenceControl =
            '<div class="candidate-evidence-panel">' +
              '<button class="secondary" data-action="load-review-evidence" data-candidate-id="' + id + '" type="button">' + (existingEvidenceUrl ? "重新显示去标识化证据图" : "打开去标识化证据图") + '</button>' +
              '<div id="candidate-evidence-' + id + '" class="candidate-evidence-image' + (existingEvidenceUrl ? "" : " hidden") + '" aria-live="polite">' +
                (existingEvidenceUrl ? '<img src="' + escapeHtml(existingEvidenceUrl) + '" alt="候选 ' + id + ' 的去标识化证据图">' : "") +
              '</div>' +
            '</div>';
        }
      }
      if (currentUser && currentUser.role === "central_data_manager") {
        issueControl = '<div class="inline-review"><label for="new-issue-' + id + '">打开伴随模块数据问题' +
          '<input id="new-issue-' + id + '" data-new-issue="' + id + '" maxlength="1000" placeholder="需要中心研究者核对的具体内容"></label>' +
          '<div class="actions"><button class="secondary" data-action="open-data-issue" data-candidate-id="' + id + '" type="button">创建问题</button></div></div>';
      }
      const reviewPanels = riskyReview
        ? '<div class="review-evidence-layout">' + evidenceControl + inlineReview + '</div>'
        : evidenceControl + inlineReview;
      return (
        '<article class="candidate" data-candidate-card-id="' + id + '" tabindex="-1">' +
          '<div class="candidate-main">' +
            "<div>" +
              '<div class="candidate-value"><strong>' + escapeHtml(candidate.field_code) + "：" + escapeHtml(displayedCandidateValue) + "</strong>" +
                '<span class="tag ' + (candidate.status === "rejected" ? "rejected" : "") + '">' + escapeHtml(reviewStatusLabel(candidate.status)) + "</span></div>" +
              '<div class="meta">' + escapeHtml(candidate.edc_subject_ref) + " / " + escapeHtml(candidate.edc_event_ref) + " · 中心 " + escapeHtml(candidate.centre_code) + " · 置信度 " + escapeHtml(candidate.confidence) + "</div>" +
              '<div class="meta">来源哈希 ' + escapeHtml(candidate.source_sha256) + " · OCR " + escapeHtml(candidate.ocr_engine_version) + " · schema " + escapeHtml(candidate.schema_version) + "</div>" +
              extractionMeta +
              evidenceMeta +
              qualityMeta +
              reviewed +
            "</div>" +
            '<div class="actions">' + actions + "</div>" +
          "</div>" +
          reviewPanels +
          issueControl +
        "</article>"
      );
    }

    async function toggleKimiSettings() {
      const card = document.getElementById("kimi-settings-card");
      const button = document.getElementById("show-kimi-settings");
      const opening = card.classList.contains("hidden");
      card.classList.toggle("hidden", !opening);
      button.setAttribute("aria-expanded", opening ? "true" : "false");
      if (!opening) return;
      document.getElementById("kimi-key").value = "";
      try {
        const result = await api("/api/settings/kimi");
        setStatus(
          "kimi-settings-status",
          result.configured ? "本机已配置 Kimi；输入新密钥可替换。" : "尚未配置本机密钥。",
          result.configured ? "success" : "warning"
        );
      } catch (error) {
        setStatus("kimi-settings-status", error.message, "error");
      }
      document.getElementById("kimi-key").focus();
    }

    async function saveKimiKey() {
      const input = document.getElementById("kimi-key");
      const button = document.getElementById("save-kimi-key");
      const key = input.value;
      if (key.length < 16) {
        setStatus("kimi-settings-status", "请输入完整的 Kimi API key。", "error");
        input.focus();
        return;
      }
      setBusy(button, true, "正在保存…");
      try {
        const result = await api("/api/settings/kimi", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key: key }),
        });
        input.value = "";
        await refreshSystemCapabilities();
        setStatus(
          "kimi-settings-status",
          result.status === "ready" ? "Kimi 已启用，可直接开始下一批识别。" : "密钥已保存，但服务尚未就绪。",
          result.status === "ready" ? "success" : "warning"
        );
      } catch (error) {
        setStatus("kimi-settings-status", error.message, "error");
      } finally {
        setBusy(button, false);
      }
    }

    function latestTransferForCandidate(candidateId) {
      return transfersByCandidateId.get(candidateId) || null;
    }

    function confirmedActionLabel(transfer) {
      if (!transfer) return "单条冻结并提交";
      if (transfer.status === "submitted") return "已写入 LibreClinica";
      if (transfer.status === "failed") return "重试并提交";
      if (transfer.status === "queued") return "提交已冻结包";
      if (transfer.status === "reconciled") return "已人工对账";
      return "查看传输状态";
    }

    function renderConfirmedRecords(candidates) {
      const confirmed = candidates
        .filter(function(candidate) { return candidate.status === "human_confirmed"; })
        .sort(function(left, right) {
          const leftTransfer = latestTransferForCandidate(left.id);
          const rightTransfer = latestTransferForCandidate(right.id);
          const leftFinal = leftTransfer && ["submitted", "reconciled"].includes(leftTransfer.status) ? 1 : 0;
          const rightFinal = rightTransfer && ["submitted", "reconciled"].includes(rightTransfer.status) ? 1 : 0;
          if (leftFinal !== rightFinal) return leftFinal - rightFinal;
          return String(right.reviewed_at || right.created_at || "").localeCompare(String(left.reviewed_at || left.created_at || ""));
        });
      const canWrite = currentUser && ["site_investigator", "central_data_manager"].includes(currentUser.role);
      const container = document.getElementById("confirmed-records");
      const batchButton = document.getElementById("submit-all-confirmed");
      const toggleButton = document.getElementById("toggle-confirmed-records");
      const pendingBatch = confirmed.filter(function(candidate) {
        const transfer = latestTransferForCandidate(candidate.id);
        return !transfer || !["submitted", "reconciled"].includes(transfer.status);
      });
      document.getElementById("confirmed-count").textContent = confirmed.length + " 条已确认";
      document.getElementById("batch-submit-summary").textContent = productMode === "lite"
        ? "Lite 版仅保存本地审核结果，不执行外部 EDC 提交。"
        : pendingBatch.length
          ? "共有 " + pendingBatch.length + " 条已接受数据尚未获得 LibreClinica 提交确认。"
          : "当前没有待提交的已接受数据。";
      batchButton.disabled = pendingBatch.length === 0 || !canWrite;
      batchButton.textContent = pendingBatch.length
        ? "冻结并提交全部 " + pendingBatch.length + " 条"
        : "冻结并提交全部已接受数据";
      if (!confirmed.length) {
        container.innerHTML = '<p class="empty-state">接受或修改候选后，确认值会显示在这里。</p>';
        toggleButton.classList.add("hidden");
        toggleButton.setAttribute("aria-expanded", "false");
        setStatus("confirmed-records-status", "当前授权范围内还没有已确认数据。");
        return;
      }
      const visibleConfirmed = confirmedRecordsExpanded ? confirmed : confirmed.slice(0, CONFIRMED_LIST_LIMIT);
      const hiddenCount = Math.max(confirmed.length - CONFIRMED_LIST_LIMIT, 0);
      toggleButton.classList.toggle("hidden", hiddenCount === 0);
      toggleButton.setAttribute("aria-expanded", confirmedRecordsExpanded ? "true" : "false");
      toggleButton.textContent = confirmedRecordsExpanded
        ? "收起，仅显示前 5 条"
        : "展开其余 " + hiddenCount + " 条";
      container.innerHTML = visibleConfirmed.map(function(candidate) {
        const id = escapeHtml(candidate.id);
        if (productMode === "lite") {
          return (
            '<article class="confirmed-item" role="listitem">' +
              "<div>" +
                '<div class="confirmed-value">' + escapeHtml(candidate.field_code) + " " + escapeHtml(candidate.final_value) + " " + escapeHtml(candidate.unit || "") +
                  '<span class="tag confirmed">已保存</span></div>' +
                '<div class="meta">' + escapeHtml(candidate.edc_subject_ref) + " / " + escapeHtml(candidate.edc_event_ref) + " · " + escapeHtml(candidate.centre_code) + "</div>" +
                '<div class="meta">审核：' + escapeHtml(candidate.reviewed_by || "") + " · " + escapeHtml(candidate.reviewed_at || "") + "</div>" +
              "</div>" +
            "</article>"
          );
        }
        const transfer = latestTransferForCandidate(candidate.id);
        const submitted = transfer && ["submitted", "reconciled"].includes(transfer.status);
        const transferState = transfer
          ? '<div class="meta">传输状态：' + escapeHtml(transferStatusLabel(transfer.status)) + (transfer.external_reference ? ' · <span class="transfer-reference">' + escapeHtml(transfer.external_reference) + "</span>" : "") + "</div>"
          : '<div class="meta">尚未创建冻结传输包</div>';
        const disabled = !canWrite || (transfer && ["submitted", "reconciled"].includes(transfer.status)) ? " disabled" : "";
        return (
          '<article class="confirmed-item" role="listitem">' +
            "<div>" +
              '<div class="confirmed-value">' + escapeHtml(candidate.field_code) + " " + escapeHtml(candidate.final_value) + " " + escapeHtml(candidate.unit || "") +
                '<span class="tag ' + (submitted ? "confirmed" : "queued") + '">' + (submitted ? "已提交" : "待提交") + "</span></div>" +
              '<div class="meta">' + escapeHtml(candidate.edc_subject_ref) + " / " + escapeHtml(candidate.edc_event_ref) + " · " + escapeHtml(candidate.centre_code) + "</div>" +
              '<div class="meta">审核：' + escapeHtml(candidate.reviewed_by || "") + " · " + escapeHtml(candidate.reviewed_at || "") + "</div>" +
              transferState +
            "</div>" +
            '<div class="actions"><button class="secondary" data-action="freeze-submit" data-candidate-id="' + id + '" type="button"' + disabled + ">" + escapeHtml(confirmedActionLabel(transfer)) + "</button></div>" +
          "</article>"
        );
      }).join("");
      setStatus("confirmed-records-status", "");
    }

    async function refreshCandidates() {
      if (!token) return;
      const candidates = await api("/api/candidates");
      const assessments = await Promise.all(candidates.map(function(candidate) {
        return api("/api/candidates/" + candidate.id + "/quality").catch(function() { return null; });
      }));
      candidateQualityById = new Map();
      candidates.forEach(function(candidate, index) {
        if (assessments[index]) candidateQualityById.set(candidate.id, assessments[index]);
      });
      currentCandidatesById = new Map(candidates.map(function(candidate) { return [candidate.id, candidate]; }));
      selectNewestPendingRecognitionBatch(candidates);
      const pending = candidates.filter(function(candidate) { return candidate.status === "candidate"; });
      const rejected = candidates.filter(function(candidate) { return candidate.status === "rejected"; });
      const container = document.getElementById("candidates");
      document.getElementById("candidate-count").textContent = pending.length + " 条待审核";
      const reviewGroups = activeBatchReviewGroups(pending);
      const recommendedButton = document.getElementById("accept-recommended-batch");
      const reviewableButton = document.getElementById("accept-reviewable-batch");
      recommendedButton.disabled = false;
      reviewableButton.disabled = false;
      recommendedButton.textContent = reviewGroups.recommended.length
        ? "批量接受本地证据项 " + reviewGroups.recommended.length + " 条"
        : "批量接受本地证据项";
      reviewableButton.textContent = reviewGroups.reviewable.length
        ? "查看需逐项审核项 " + reviewGroups.reviewable.length + " 条"
        : "查看需逐项审核项";
      const activeBatchCount = reviewGroups.recommended.length + reviewGroups.reviewable.length + reviewGroups.individual.length;
      document.getElementById("bulk-accept-summary").textContent = activeBatchCount
        ? "本批次：本地证据可批量 " + reviewGroups.recommended.length + " 条；冲突或仅 Kimi 识别需逐项审核 " + reviewGroups.reviewable.length + " 条；质量阻断 " + reviewGroups.individual.length + " 条。"
        : "完成识别后，本地证据项可批量确认；冲突和仅 Kimi 识别项需逐项核对。";
      const rows = pending.concat(rejected);
      container.innerHTML = rows.length
        ? renderCandidatesBySubject(rows)
        : '<div class="empty-state empty-state-with-art">' +
            '<img class="empty-state-illustration" src="/static/img/workbench-review-empty.webp" alt="" aria-hidden="true" width="640" height="480" loading="lazy" decoding="async">' +
            '<div class="empty-state-copy"><strong>当前没有待审核候选</strong><span>上传报告后，OCR 结果会自动出现在这里。</span></div>' +
          '</div>';
      renderConfirmedRecords(candidates);
      if (pending.length) setProgress(2);
      else if (candidates.some(function(candidate) { return candidate.status === "human_confirmed"; })) setProgress(3);
      return candidates;
    }

    function renderCandidatesBySubject(candidates) {
      const groups = new Map();
      candidates.forEach(function(candidate) {
        const key = [candidate.edc_subject_ref, candidate.edc_event_ref].join("::");
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(candidate);
      });
      return Array.from(groups.values()).map(function(group) {
        const first = group[0];
        return '<section class="candidate-subject-group" data-subject-ref="' + escapeHtml(first.edc_subject_ref) + '" data-event-ref="' + escapeHtml(first.edc_event_ref) + '">' +
          '<header><strong>' + escapeHtml(first.edc_subject_ref) + '</strong><span class="meta">' + escapeHtml(first.edc_event_ref) + ' · ' + group.length + ' 条</span></header>' +
          group.map(renderPendingCandidate).join("") +
          '</section>';
      }).join("");
    }

    function activeBatchReviewGroups(candidates) {
      const groups = { recommended: [], reviewable: [], individual: [] };
      const safeSources = new Set([null, "agreement", "local_only", "local_fallback", "local_pdf_text", "structured_source"]);
      const hasActiveBatchContext = activeBatchCandidateIds.size > 0;
      candidates.forEach(function(candidate) {
        if (hasActiveBatchContext && !activeBatchCandidateIds.has(candidate.id)) return;
        const quality = candidateQualityById.get(candidate.id);
        if (!quality || quality.status === "BLOCK") {
          groups.individual.push(candidate);
        } else if (["conflict", "kimi_only"].includes(candidate.extraction_agreement)) {
          groups.reviewable.push(candidate);
        } else if (safeSources.has(candidate.extraction_agreement)) {
          groups.recommended.push(candidate);
        } else {
          groups.individual.push(candidate);
        }
      });
      return groups;
    }

    function currentBatchCandidateIds(groupName) {
      const candidates = Array.from(currentCandidatesById.values()).filter(function(candidate) {
        return candidate.status === "candidate";
      });
      return activeBatchReviewGroups(candidates)[groupName].map(function(candidate) {
        return candidate.id;
      });
    }

    async function acceptCurrentBatchGroup(button, groupName) {
      let candidateIds = currentBatchCandidateIds(groupName);
      if (!candidateIds.length) {
        setBusy(button, true, "正在同步候选…");
        try {
          await refreshRecognitionJobs();
          await refreshCandidates();
          candidateIds = currentBatchCandidateIds(groupName);
        } catch (error) {
          setStatus("workflow-status", error.message, "error");
          setBusy(button, false);
          return;
        }
      }
      if (!candidateIds.length) {
        setBusy(button, false);
        setStatus(
          "workflow-status",
          groupName === "reviewable" ? "当前批次没有待审核项。" : "当前批次没有可批量接受的候选。",
          "warning"
        );
        return;
      }
      const requestBody = {
        candidate_ids: candidateIds,
        review_batch_id: activeRecognitionJobId || undefined,
      };
      if (groupName === "reviewable") {
        const firstCard = document.querySelector('[data-candidate-card-id="' + CSS.escape(candidateIds[0]) + '"]');
        if (firstCard) firstCard.scrollIntoView({ behavior: "smooth", block: "center" });
        setStatus("workflow-status", "冲突和仅 Kimi 识别项必须逐项查看证据并明确选择来源。", "warning");
        return;
      }
      setBusy(button, true, "正在接受 " + candidateIds.length + " 条…");
      try {
        const result = await api("/api/candidate-reviews/bulk-accept", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(requestBody),
        });
        result.candidates.forEach(function(candidate) {
          activeBatchCandidateIds.delete(candidate.id);
          currentCandidatesById.set(candidate.id, candidate);
          const card = document.querySelector('[data-candidate-card-id="' + CSS.escape(candidate.id) + '"]');
          if (card) card.remove();
        });
        const skippedReasons = result.summary && result.summary.skipped_by_reason
          ? Object.entries(result.summary.skipped_by_reason).map(function(entry) { return entry[0] + " " + entry[1] + " 条"; }).join("，")
          : "";
        const skipped = result.skipped_count ? "；跳过 " + result.skipped_count + " 条（" + skippedReasons + "）" : "";
        setStatus("workflow-status", "已按 " + (result.summary ? result.summary.policy : "服务端策略") + " 批量确认 " + result.accepted_count + " 条" + skipped + "。", result.skipped_count ? "warning" : "success");
        await refreshCandidates();
        await refreshOperations();
        if (result.skipped && result.skipped.length) {
          const firstSkipped = document.querySelector('[data-candidate-card-id="' + CSS.escape(result.skipped[0].candidate_id) + '"]');
          if (firstSkipped) {
            firstSkipped.scrollIntoView({ behavior: "smooth", block: "center" });
            firstSkipped.focus({ preventScroll: true });
          }
        }
      } catch (error) {
        setStatus("workflow-status", error.message, "error");
        setBusy(button, false);
      }
    }

    function transferActions(transfer) {
      let html = '<button class="secondary" data-action="view-transfer" data-transfer-id="' + escapeHtml(transfer.id) + '" type="button">查看冻结包</button>';
      if (transfer.status === "queued" && transfer.target === "libreclinica") {
        html += '<button data-action="submit-transfer" data-transfer-id="' + escapeHtml(transfer.id) + '" type="button">提交 LibreClinica</button>';
      }
      if (transfer.status === "failed") {
        html += '<button class="warn" data-action="retry-transfer" data-transfer-id="' + escapeHtml(transfer.id) + '" type="button">重新排队</button>';
        html += '<button class="secondary" data-action="open-reconciliation" data-transfer-id="' + escapeHtml(transfer.id) + '" type="button">人工对账</button>';
      }
      return html;
    }

    async function refreshTransfers() {
      if (!token) return;
      try {
        const transfers = await api("/api/transfers");
        transfersByCandidateId = new Map();
        transfers.forEach(function(transfer) { transfersByCandidateId.set(transfer.candidate_id, transfer); });
        const container = document.getElementById("transfers");
        if (!transfers.length) {
          container.innerHTML = '<p class="empty-state">当前授权范围内没有传输记录。</p>';
        } else {
          container.innerHTML = transfers.slice().reverse().map(function(transfer) {
            const id = escapeHtml(transfer.id);
            const statusClass = transfer.status === "submitted" || transfer.status === "reconciled"
              ? "confirmed"
              : transfer.status === "failed" ? "failed" : "queued";
            return (
              '<article class="candidate">' +
                '<div class="candidate-main">' +
                  "<div>" +
                    "<strong>" + escapeHtml(transfer.candidate_id) + "</strong>" +
                    '<span class="tag ' + statusClass + '">' + escapeHtml(transferStatusLabel(transfer.status)) + "</span>" +
                    '<div class="meta">中心 ' + escapeHtml(transfer.centre_code) + " · 目标 " + escapeHtml(transfer.target) + " · 尝试 " + escapeHtml(transfer.attempt_count) + " · 重试 " + escapeHtml(transfer.retry_count) + "</div>" +
                    '<div class="meta">传输 ' + id + " · 包哈希 " + escapeHtml(transfer.package_sha256) + "</div>" +
                    (transfer.last_error ? '<div class="meta">最近错误：' + escapeHtml(transfer.last_error.code) + "；" + escapeHtml(transfer.last_error.message) + "</div>" : "") +
                    (transfer.external_reference ? '<div class="meta transfer-reference">LibreClinica 权威引用：' + escapeHtml(transfer.external_reference) + "；响应哈希 " + escapeHtml(transfer.authority_response_sha256) + "</div>" : "") +
                    (transfer.reconciliation ? '<div class="meta">人工对账：' + escapeHtml(transfer.reconciliation.reconciled_by) + "；" + escapeHtml(transfer.reconciliation.note) + "</div>" : "") +
                  "</div>" +
                  '<div class="actions">' + transferActions(transfer) + "</div>" +
                "</div>" +
                '<div id="reconciliation-' + id + '" class="inline-review hidden">' +
                  '<label for="reconciliation-note-' + id + '">人工对账结论 <span class="required">*</span>' +
                    '<textarea id="reconciliation-note-' + id + '" data-reconciliation-note="' + id + '" maxlength="500"></textarea>' +
                  "</label>" +
                  '<p id="reconciliation-status-' + id + '" class="status" aria-live="polite"></p>' +
                  '<div class="actions">' +
                    '<button class="secondary" data-action="cancel-reconciliation" data-transfer-id="' + id + '" type="button">取消</button>' +
                    '<button data-action="confirm-reconciliation" data-transfer-id="' + id + '" type="button">确认对账</button>' +
                  "</div>" +
                "</div>" +
              "</article>"
            );
          }).join("");
        }
        setStatus("ledger-status", "传输记录已刷新，共 " + transfers.length + " 条。");
        if (Array.from(transfersByCandidateId.values()).some(function(transfer) { return transfer.status === "submitted"; })) setProgress(4);
        if (currentCandidatesById.size) renderConfirmedRecords(Array.from(currentCandidatesById.values()));
      } catch (error) {
        setStatus("ledger-status", error.message, "error");
      }
    }

    async function loadCandidateEvidence(candidateId, button) {
      const container = document.getElementById("candidate-evidence-" + candidateId);
      if (!container) return;
      if (loadedCandidateEvidenceIds.has(candidateId)) {
        container.classList.remove("hidden");
        return;
      }
      setBusy(button, true, "正在加载证据…");
      try {
        const response = await fetch("/api/candidates/" + encodeURIComponent(candidateId) + "/evidence-image", {
          headers: { Authorization: "Bearer " + token },
          cache: "no-store",
        });
        if (!response.ok) {
          const body = await response.json().catch(function() { return {}; });
          throw new Error(humanizeApiError(body.detail, response.status));
        }
        const existingUrl = candidateEvidenceUrls.get(candidateId);
        if (existingUrl) URL.revokeObjectURL(existingUrl);
        const url = URL.createObjectURL(await response.blob());
        candidateEvidenceUrls.set(candidateId, url);
        container.innerHTML = '<img src="' + escapeHtml(url) + '" alt="候选 ' + escapeHtml(candidateId) + ' 的去标识化证据图">';
        container.classList.remove("hidden");
        await new Promise(function(resolve, reject) {
          const image = container.querySelector("img");
          image.addEventListener("load", resolve, { once: true });
          image.addEventListener("error", reject, { once: true });
        });
        loadedCandidateEvidenceIds.add(candidateId);
        setStatus("review-status-" + candidateId, "证据图已加载；请核对后勾选确认。", "success");
      } catch (error) {
        setStatus("review-status-" + candidateId, error.message || "证据图加载失败。", "error");
      } finally {
        setBusy(button, false);
      }
    }

    function openInlineReview(candidateId, decision) {
      const candidate = currentCandidatesById.get(candidateId);
      const form = document.getElementById("review-form-" + candidateId);
      if (!candidate || !form) {
        setStatus("workflow-status", "候选记录已变化，请刷新后重试。", "error");
        return;
      }
      form.dataset.decision = decision;
      const valueField = form.querySelector(".review-value-field");
      valueField.classList.toggle("hidden", decision !== "edit");
      const sourceChoice = form.querySelector(".review-source-choice");
      if (sourceChoice) sourceChoice.classList.toggle("hidden", decision !== "accept");
      const evidenceAttestation = form.querySelector(".review-evidence-attestation");
      if (evidenceAttestation) evidenceAttestation.classList.toggle("hidden", decision === "reject");
      const confirmButton = form.querySelector('[data-action="confirm-review"]');
      confirmButton.textContent = decision === "edit" ? "确认修改" : decision === "accept" ? "确认接受" : "确认拒绝";
      confirmButton.className = decision === "edit" ? "warn" : decision === "accept" ? "" : "danger";
      form.classList.remove("hidden");
      const focusTarget = decision === "edit"
        ? form.querySelector("[data-review-value]")
        : form.querySelector("[data-review-note]");
      focusTarget.focus();
    }

    async function submitCandidateReview(candidateId, decision, button) {
      const payload = { decision: decision };
      const form = document.getElementById("review-form-" + candidateId);
      const candidate = currentCandidatesById.get(candidateId);
      const riskyReview = candidate && ["conflict", "kimi_only"].includes(candidate.extraction_agreement);
      if (decision === "edit") {
        const editedValue = form.querySelector("[data-review-value]").value.trim();
        if (!editedValue) {
          setStatus("review-status-" + candidateId, "请填写确认后的值。", "error");
          return;
        }
        payload.edited_value = editedValue;
        if (riskyReview) payload.selected_source = "manual";
      } else if (decision === "accept" && candidate && candidate.extraction_agreement === "conflict") {
        const selected = form.querySelector('input[name="review-source-' + CSS.escape(candidateId) + '"]:checked');
        if (!selected) {
          setStatus("review-status-" + candidateId, "请选择采用本地 OCR 值或 Kimi 值。", "error");
          return;
        }
        payload.selected_source = selected.value;
      } else if (decision === "accept" && candidate && candidate.extraction_agreement === "kimi_only") {
        payload.selected_source = "kimi";
      }
      if (riskyReview && decision !== "reject") {
        const attestation = form.querySelector("[data-review-evidence-attestation]");
        if (!loadedCandidateEvidenceIds.has(candidateId) || !attestation || !attestation.checked) {
          setStatus("review-status-" + candidateId, "请先打开证据图、逐项核对并勾选确认。", "error");
          return;
        }
        payload.evidence_acknowledged = true;
        payload.evidence_source_file_id = candidate.source_file_id;
      }
      if (form) {
        const noteInput = form.querySelector("[data-review-note]");
        const note = noteInput ? noteInput.value.trim() : "";
        if (note) payload.reason = note;
      }
      setBusy(button, true, decision === "accept" ? "正在接受…" : "正在保存…");
      try {
        await api("/api/candidates/" + candidateId + "/review", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        setStatus("workflow-status", decision === "reject" ? "候选已拒绝并写入审计记录。" : "候选已人工确认，可冻结并提交。", "success");
        await refreshCandidates();
        await refreshOperations();
      } catch (error) {
        setStatus(form ? "review-status-" + candidateId : "workflow-status", error.message, "error");
        setBusy(button, false);
      }
    }

    function resetDeidentificationPanel() {
      activeBatchPreviewUrls.forEach(function(url) { URL.revokeObjectURL(url); });
      activeBatchPreviewUrls = [];
      activeUploadBatch = [];
      document.getElementById("deidentification-panel").classList.add("hidden");
      document.getElementById("deidentification-previews").innerHTML = "";
      const attestation = document.getElementById("deidentification-review-attestation");
      attestation.checked = false;
      attestation.disabled = true;
      document.getElementById("confirm-deidentification-draft").disabled = true;
      document.getElementById("batch-progress").classList.add("hidden");
      document.getElementById("batch-file-statuses").innerHTML = "";
      setStatus("deidentification-status", "");
    }

    function updateBatchProgress(label, completed, total) {
      const progressPanel = document.getElementById("batch-progress");
      progressPanel.classList.remove("hidden");
      document.getElementById("batch-progress-label").textContent = label;
      document.getElementById("batch-progress-count").textContent = completed + " / " + total;
      const progress = document.getElementById("batch-progress-bar");
      progress.max = Math.max(total, 1);
      progress.value = completed;
    }

    function renderBatchFileStatuses() {
      document.getElementById("batch-file-statuses").innerHTML = activeUploadBatch.map(function(item) {
        return '<li data-tone="' + escapeHtml(item.tone || "") + '">' +
          escapeHtml(item.fileName) + "：" + escapeHtml(item.status || "等待处理") +
        "</li>";
      }).join("");
    }

    function renderBatchPreviews() {
      const readyItems = activeUploadBatch.filter(function(item) {
        return (item.draftId && item.previewUrl) || (item.isPdf && item.activeSourceId);
      });
      document.getElementById("deidentification-previews").innerHTML = readyItems.map(function(item, index) {
        if (item.isPdf) {
          return (
            '<figure class="batch-preview-card">' +
              '<div class="pdf-preview-tile" aria-label="本地 PDF 文本解析">PDF</div>' +
              '<figcaption class="batch-preview-copy">' +
                "<strong>" + escapeHtml(item.fileName) + "</strong>" +
                '<span class="meta">仅本机读取文本层；不调用 Kimi</span>' +
              "</figcaption>" +
            "</figure>"
          );
        }
        const markerText = item.markerCodes.length
          ? "检测到：" + item.markerCodes.join("、")
          : "未自动检出标记，仍需人工核对";
        return (
          '<figure class="batch-preview-card">' +
            '<img loading="lazy" src="' + escapeHtml(item.previewUrl) + '" alt="第 ' + (index + 1) + ' 张去标识化预览：' + escapeHtml(item.fileName) + '">' +
            '<figcaption class="batch-preview-copy">' +
              "<strong>" + escapeHtml(item.fileName) + "</strong>" +
              '<span class="meta">' + escapeHtml(markerText) + "</span>" +
            "</figcaption>" +
          "</figure>"
        );
      }).join("");
      const panel = document.getElementById("deidentification-panel");
      panel.classList.toggle("hidden", readyItems.length === 0);
      const attestation = document.getElementById("deidentification-review-attestation");
      attestation.checked = false;
      attestation.disabled = readyItems.length === 0;
      document.getElementById("confirm-deidentification-draft").disabled = true;
      setStatus(
        "deidentification-status",
        readyItems.length + " 份报告已就绪。请核对图片遮盖并统一确认本地处理。",
        readyItems.length ? "warning" : "error"
      );
    }

    async function prepareBatchDraft(item) {
      const draft = await api("/api/source-files/" + item.originalSourceId + "/deidentification-drafts", { method: "POST" });
      item.draftId = draft.id;
      item.markerCodes = draft.detected_marker_codes || [];
      const previewResponse = await fetch("/api/deidentification-drafts/" + draft.id + "/image", {
        headers: { Authorization: "Bearer " + token },
        cache: "no-store",
      });
      if (!previewResponse.ok) {
        const body = await previewResponse.json().catch(function() { return {}; });
        throw new Error(humanizeApiError(body.detail, previewResponse.status));
      }
      item.previewUrl = URL.createObjectURL(await previewResponse.blob());
      activeBatchPreviewUrls.push(item.previewUrl);
    }

    async function recognizeBatchItem(item) {
      if (item.isPdf) {
        return api("/api/source-files/" + item.activeSourceId + "/pulmonary-function-extract", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            edc_subject_ref: item.subjectRef,
            edc_event_ref: item.eventRef,
            field_codes: item.selectedFieldCodes,
          }),
        });
      }
      return api("/api/source-files/" + item.activeSourceId + "/hybrid-extract", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          edc_subject_ref: item.subjectRef,
          edc_event_ref: item.eventRef,
          use_kimi: item.useKimi,
          field_codes: item.selectedFieldCodes,
        }),
      });
    }

    async function uploadAndRecognize(button) {
      const files = pendingUploadQueue.length
        ? pendingUploadQueue.map(function(item) { return item.file; })
        : Array.from(document.getElementById("image-file").files || []);
      const subjectInput = document.getElementById("subject-ref");
      const subjectRef = (pendingUploadQueue.length ? pendingUploadQueue[0].subjectRef : subjectInput.value).trim().toUpperCase();
      subjectInput.value = subjectRef;
      if (!/^[A-Z][A-Z0-9_-]{2,63}$/.test(subjectRef)) {
        setStatus("source-status", "请输入大写字母开头的去标识化研究编号。", "error");
        subjectInput.focus();
        return;
      }
      if (!files.length) {
        setStatus("source-status", "请至少选择一份检查报告。", "error");
        document.getElementById("image-file").focus();
        return;
      }
      const selectedFieldCodes = pendingUploadQueue.length
        ? Array.from(new Set(pendingUploadQueue.flatMap(function(item) { return item.selectedFieldCodes; })))
        : Array.from(selectedRecognitionFieldCodes);
      if (!selectedFieldCodes.length) {
        setStatus("source-status", "请先选择至少一个要识别的项目。", "error");
        document.getElementById("recognition-field-scope").open = true;
        document.getElementById("recognition-field-search").focus();
        return;
      }
      if (!document.getElementById("synthetic-attestation").checked) {
        setStatus("source-status", "必须确认资料符合本机处理边界。", "error");
        document.getElementById("synthetic-attestation").focus();
        return;
      }
      const eventRef = pendingUploadQueue.length ? pendingUploadQueue[0].eventRef : document.getElementById("event-ref").value;
      const queuedBatch = pendingUploadQueue.slice();
      setIntakeQueueLocked(true);
      resetDeidentificationPanel();
      activeBatchCandidateIds = new Set();
      pendingUploadQueue = [];
      uploadQueueSequence = 0;
      activeUploadBatch = files.map(function(file, index) {
        const queuedItem = queuedBatch[index];
        const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
        return {
          file: file,
          fileName: file.name,
          subjectRef: queuedItem ? queuedItem.subjectRef : subjectRef,
          eventRef: queuedItem ? queuedItem.eventRef : eventRef,
          selectedFieldCodes: queuedItem ? queuedItem.selectedFieldCodes.slice() : selectedFieldCodes.slice(),
          useKimi: queuedItem ? queuedItem.useKimi : !isPdf && kimiServiceReady && kimiUserEnabled,
          isPdf: isPdf,
          status: "等待上传",
          tone: "",
          originalSourceId: null,
          activeSourceId: null,
          draftId: null,
          markerCodes: [],
          previewUrl: null,
          edcSyncDeferred: false,
        };
      });
      renderBatchFileStatuses();
      setBusy(button, true, "正在准备 0 / " + files.length);
      setStatus("source-status", "正在登记来源并准备本地处理；LibreClinica 可用时同步受试者与访视…");
      setStatus("recognition-status", "");
      let completed = 0;
      let failed = 0;
      for (const item of activeUploadBatch) {
        setBusy(button, true, "正在准备 " + completed + " / " + files.length);
        updateBatchProgress("上传并准备本地识别", completed, files.length);
        item.status = "正在上传";
        renderBatchFileStatuses();
        try {
          const form = new FormData();
          form.append("file", item.file);
          form.append("synthetic_attestation", "true");
          form.append("edc_subject_ref", item.subjectRef);
          form.append("edc_event_ref", item.eventRef);
          const source = await api("/api/source-files/upload", { method: "POST", body: form });
          item.originalSourceId = source.id;
          item.edcSyncDeferred = Boolean(
            source.edc_subject_provisioning && source.edc_subject_provisioning.status === "deferred"
          );
          if (item.isPdf) {
            item.activeSourceId = source.id;
            item.status = "PDF 本地文本解析已就绪" + (item.edcSyncDeferred ? "；LibreClinica 稍后同步" : "");
          } else {
            item.status = "正在生成遮盖预览";
            renderBatchFileStatuses();
            await prepareBatchDraft(item);
            item.status = "遮盖预览已就绪" + (item.edcSyncDeferred ? "；LibreClinica 稍后同步" : "");
          }
          item.tone = item.edcSyncDeferred ? "warning" : "success";
        } catch (error) {
          item.status = "准备失败：" + error.message;
          item.tone = "error";
          failed += 1;
        }
        completed += 1;
        updateBatchProgress("上传并准备本地识别", completed, files.length);
        renderBatchFileStatuses();
      }
      setBusy(button, false);
      renderBatchPreviews();
      const ready = activeUploadBatch.filter(function(item) {
        return (item.draftId && item.previewUrl) || (item.isPdf && item.activeSourceId);
      }).length;
      const deferred = activeUploadBatch.filter(function(item) { return item.edcSyncDeferred; }).length;
      setStatus(
        "source-status",
        "批次准备完成：共 " + files.length + " 份，" + ready + " 份已就绪，" + failed + " 份失败。" +
          (deferred ? " " + deferred + " 份等待 LibreClinica 恢复后同步；不影响识别、审核与 Excel 导出。" : ""),
        failed || deferred ? "warning" : "success"
      );
      setStatus("recognition-status", ready ? "识别尚未开始，等待统一人工确认。" : "没有可继续识别的报告。", ready ? "warning" : "error");
      if (ready) {
        try {
          await createRecognitionJobFromBatch(activeUploadBatch.filter(function(item) {
            return (item.draftId && item.previewUrl) || (item.isPdf && item.activeSourceId);
          }));
          setStatus("recognition-status", "批次已保存为可恢复识别任务，等待人工确认后执行。", "success");
        } catch (error) {
          setStatus("recognition-job-status", "任务保存失败：" + error.message, "warning");
        }
      }
      pendingUploadQueue = [];
      setIntakeQueueLocked(false);
      renderPendingUploadQueue();
    }

    async function showTransferArtifacts(transferId) {
      const results = await Promise.all([
        api("/api/transfers/" + transferId + "/package"),
        api("/api/transfers/" + transferId + "/integrity"),
      ]);
      const packageResult = results[0];
      const integrity = results[1];
      const panel = document.getElementById("transfer-panel");
      panel.classList.remove("hidden");
      panel.open = true;
      document.getElementById("transfer-package").textContent = JSON.stringify(packageResult.package, null, 2);
      setStatus(
        "transfer-integrity",
        "传输 " + transferId + "\n记录哈希：" + integrity.recorded_sha256 + "\n重新计算：" + integrity.recomputed_sha256 + "\n完整性：" + (integrity.integrity_valid ? "通过" : "失败"),
        integrity.integrity_valid ? "success" : "error"
      );
      return integrity;
    }

    async function submitTransfer(transferId, button) {
      activeTransferId = transferId;
      if (button) setBusy(button, true, "正在提交…");
      try {
        const submitted = await api("/api/transfers/" + transferId + "/submit", { method: "POST" });
        setStatus("workflow-status", "LibreClinica 已确认写入。权威引用：" + submitted.external_reference + "；响应哈希：" + submitted.authority_response_sha256, "success");
        setProgress(4);
        await refreshTransfers();
        await refreshOperations();
      } catch (error) {
        setStatus("workflow-status", "LibreClinica 提交未完成：" + error.message, "error");
        await refreshTransfers();
        await refreshOperations();
      } finally {
        if (button) setBusy(button, false);
      }
    }

    async function processCandidateTransfer(candidateId, showArtifacts) {
      let transfer = await api("/api/candidates/" + candidateId + "/transfers", { method: "POST" });
      activeTransferId = transfer.id;
      const integrity = showArtifacts
        ? await showTransferArtifacts(transfer.id)
        : await api("/api/transfers/" + transfer.id + "/integrity");
      if (!integrity.integrity_valid) throw new Error("冻结包完整性校验失败，已阻止提交。");
      setProgress(3);
      if (transfer.status === "submitted" || transfer.status === "reconciled") {
        return { state: "already_completed", transfer: transfer };
      }
      if (transfer.status === "failed") {
        transfer = await api("/api/transfers/" + transfer.id + "/retry", { method: "POST" });
      }
      const ready = edcReadiness.status === "ready" && edcReadiness.write_path === "human_triggered";
      if (!ready || transfer.target !== "libreclinica") {
        return { state: "frozen_queued", transfer: transfer };
      }
      const submitted = await api("/api/transfers/" + transfer.id + "/submit", { method: "POST" });
      return { state: "submitted", transfer: submitted };
    }

    async function freezeAndSubmit(candidateId, button) {
      setBusy(button, true, "正在冻结并校验…");
      try {
        setBusy(button, true, "正在写入 LibreClinica…");
        const result = await processCandidateTransfer(candidateId, true);
        if (result.state === "already_completed") {
          setStatus("workflow-status", "该冻结包已完成处理，无需重复提交。", "success");
        } else if (result.state === "frozen_queued") {
          setStatus("workflow-status", "规范 JSON 已冻结并校验通过；LibreClinica 提交闸门未就绪，记录保留为待提交。", "warning");
        } else {
          setStatus(
            "workflow-status",
            "LibreClinica 已确认写入。权威引用：" + result.transfer.external_reference + "；响应哈希：" + result.transfer.authority_response_sha256,
            "success"
          );
          setProgress(4);
        }
        await refreshTransfers();
        await refreshCandidates();
      } catch (error) {
        setStatus("workflow-status", error.message, "error");
        await refreshTransfers();
      } finally {
        setBusy(button, false);
      }
    }

    async function submitAllConfirmed(button) {
      const targets = Array.from(currentCandidatesById.values()).filter(function(candidate) {
        if (candidate.status !== "human_confirmed") return false;
        const transfer = latestTransferForCandidate(candidate.id);
        return !transfer || !["submitted", "reconciled"].includes(transfer.status);
      });
      if (!targets.length) {
        setStatus("batch-submit-status", "当前没有待提交的已接受数据。");
        return;
      }
      const resultsList = document.getElementById("batch-submit-results");
      resultsList.classList.remove("hidden");
      resultsList.innerHTML = "";
      setBusy(button, true, "正在提交 0 / " + targets.length);
      let submittedCount = 0;
      let queuedCount = 0;
      let failedCount = 0;
      for (let index = 0; index < targets.length; index += 1) {
        const candidate = targets[index];
        setBusy(button, true, "正在提交 " + (index + 1) + " / " + targets.length);
        setStatus(
          "batch-submit-status",
          "正在冻结、校验并提交第 " + (index + 1) + " / " + targets.length + " 条：" + candidate.field_code
        );
        const item = document.createElement("li");
        item.textContent = candidate.edc_subject_ref + " / " + candidate.edc_event_ref + " / " + candidate.field_code + "：处理中";
        resultsList.appendChild(item);
        try {
          const result = await processCandidateTransfer(candidate.id, false);
          if (result.state === "submitted") {
            submittedCount += 1;
            item.dataset.tone = "success";
            item.textContent = candidate.edc_subject_ref + " / " + candidate.edc_event_ref + " / " + candidate.field_code + "：已写入；" + result.transfer.external_reference;
          } else if (result.state === "frozen_queued") {
            queuedCount += 1;
            item.dataset.tone = "warning";
            item.textContent = candidate.edc_subject_ref + " / " + candidate.edc_event_ref + " / " + candidate.field_code + "：已冻结，提交闸门未就绪";
          } else {
            submittedCount += 1;
            item.dataset.tone = "success";
            item.textContent = candidate.edc_subject_ref + " / " + candidate.edc_event_ref + " / " + candidate.field_code + "：此前已完成";
          }
        } catch (error) {
          failedCount += 1;
          item.dataset.tone = "error";
          item.textContent = candidate.edc_subject_ref + " / " + candidate.edc_event_ref + " / " + candidate.field_code + "：失败；" + error.message;
        }
      }
      await refreshTransfers();
      await refreshCandidates();
      await refreshOperations();
      setBusy(button, false);
      const tone = failedCount ? "error" : queuedCount ? "warning" : "success";
      setStatus(
        "batch-submit-status",
        "批量处理完成：已写入或此前已完成 " + submittedCount + " 条，已冻结待提交 " + queuedCount + " 条，失败 " + failedCount + " 条。",
        tone
      );
      if (!failedCount && !queuedCount) setProgress(4);
    }

    async function refreshEdcReadiness() {
      if (productMode === "lite") {
        edcReadiness = { status: "blocked", write_path: "disabled" };
        setStatus("edc-status", "");
        return;
      }
      try {
        edcReadiness = await api("/api/edc-adapter/readiness");
        const ready = edcReadiness.status === "ready" && edcReadiness.write_path === "human_triggered";
        const endpoint = edcReadiness.endpoint ? "；端点：" + edcReadiness.endpoint : "";
        const mapping = edcReadiness.mapping_version ? "；OID 映射：" + edcReadiness.mapping_version : "";
        setStatus(
          "edc-status",
          ready ? "LibreClinica：已连接，人工提交已启用" + endpoint + mapping : "LibreClinica：提交已阻断；" + (edcReadiness.blockers || []).join("；"),
          ready ? "success" : "error"
        );
        const submitButton = document.getElementById("submit-active-transfer");
        submitButton.textContent = ready ? "提交当前冻结包" : "验证提交闸门";
        submitButton.className = ready ? "" : "danger";
      } catch (error) {
        edcReadiness = { status: "blocked", write_path: "disabled" };
        setStatus("edc-status", "LibreClinica 状态检查失败：" + error.message, "error");
      }
    }

    async function login() {
      const button = document.getElementById("login");
      setBusy(button, true, "正在登录…");
      setStatus("login-status", "");
      try {
        const result = await api("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            username: document.getElementById("username").value,
            password: document.getElementById("password").value,
          }),
        });
        token = result.access_token;
        currentUser = result.user;
        document.getElementById("password").value = "";
        document.getElementById("setup-password").value = "";
        document.getElementById("setup-password-confirmation").value = "";
        document.getElementById("login-card").classList.add("hidden");
        document.getElementById("workbench").classList.remove("hidden");
        document.getElementById("intake-section").classList.toggle("hidden", !["site_investigator", "central_data_manager"].includes(currentUser.role));
        applyWorkspaceProjection();
        setStatus("identity", "已登录：" + currentUser.username + "；角色：" + (ROLE_LABELS[currentUser.role] || currentUser.role) + "；中心范围：" + (currentUser.centre_code || "全部授权中心"));
        await refreshSystemCapabilities();
        if (["site_investigator", "central_data_manager"].includes(currentUser.role)) {
          await refreshRecognitionFields();
        }
        if (productMode === "lite") {
          transfersByCandidateId = new Map();
        } else {
          await refreshEdcReadiness();
          await refreshTransfers();
          await refreshOperations();
          if (currentUser.role === "central_data_manager") {
            await refreshFieldDictionary();
          } else {
            document.getElementById("field-dictionary-section").classList.add("hidden");
          }
        }
        await refreshRecognitionJobs();
        await refreshCandidates();
        clearSetupCredential();
        return true;
      } catch (error) {
        setStatus("login-status", "登录失败：" + error.message, "error");
        return false;
      } finally {
        setBusy(button, false);
      }
    }

    function randomCharacter(alphabet) {
      const sample = new Uint32Array(1);
      window.crypto.getRandomValues(sample);
      return alphabet[sample[0] % alphabet.length];
    }

    function generateSetupPassword() {
      const groups = ["ABCDEFGHJKLMNPQRSTUVWXYZ", "abcdefghijkmnopqrstuvwxyz", "23456789", "!@#$%*-_=+"];
      const all = groups.join("");
      const characters = groups.map(randomCharacter);
      while (characters.length < 24) characters.push(randomCharacter(all));
      for (let index = characters.length - 1; index > 0; index -= 1) {
        const sample = new Uint32Array(1);
        window.crypto.getRandomValues(sample);
        const swapIndex = sample[0] % (index + 1);
        const value = characters[index];
        characters[index] = characters[swapIndex];
        characters[swapIndex] = value;
      }
      const password = characters.join("");
      document.getElementById("setup-password").value = password;
      document.getElementById("setup-password-confirmation").value = password;
      setStatus("setup-status", "已生成 24 位随机密码。请保存后完成设置。", "success");
    }

    function setupCredentialText() {
      if (!setupCredential) return "";
      return "中心：" + setupCredential.centreCode + "\n账号：" + setupCredential.username + "\n密码：" + setupCredential.password + "\n";
    }

    function clearSetupCredential() {
      setupCredential = null;
      document.getElementById("setup-receipt-username").textContent = "";
      document.getElementById("setup-receipt-password").textContent = "";
      document.getElementById("setup-password").value = "";
      document.getElementById("setup-password-confirmation").value = "";
    }

    async function copySetupCredential() {
      if (!setupCredential) return;
      try {
        await navigator.clipboard.writeText(setupCredentialText());
        setStatus("setup-status", "账号和密码已复制；请粘贴到获批的密码管理器。", "success");
      } catch (error) {
        setStatus("setup-status", "浏览器未允许复制，请手动复制上方账号和密码。", "warning");
      }
    }

    function downloadSetupCredential() {
      if (!setupCredential) return;
      const blob = new Blob([setupCredentialText()], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "centre-login-" + setupCredential.centreCode + ".txt";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setStatus("setup-status", "一次性凭证已下载；导入密码管理器后请删除明文文件。", "warning");
    }

    async function continueAfterSetup() {
      if (!setupCredential) return;
      document.getElementById("username").value = setupCredential.username;
      document.getElementById("password").value = setupCredential.password;
      document.getElementById("setup-card").classList.add("hidden");
      document.getElementById("login-card").classList.remove("hidden");
      if (!(await login())) {
        document.getElementById("login-card").classList.add("hidden");
        document.getElementById("setup-card").classList.remove("hidden");
      }
    }

    async function completeSetup() {
      const button = document.getElementById("complete-setup");
      setBusy(button, true, "正在保存…");
      setStatus("setup-status", "");
      const password = document.getElementById("setup-password").value;
      try {
        const result = await api("/api/setup/complete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            password: password,
            password_confirmation: document.getElementById("setup-password-confirmation").value,
          }),
        });
        setupCredential = {
          username: result.username,
          centreCode: result.centre_code,
          password: password,
        };
        document.getElementById("setup-receipt-username").textContent = result.username;
        document.getElementById("setup-receipt-password").textContent = password;
        document.getElementById("setup-form").classList.add("hidden");
        document.getElementById("setup-credential-receipt").classList.remove("hidden");
        setStatus("setup-status", "账号已创建。请先保存上方一次性凭证。", "success");
      } catch (error) {
        setStatus("setup-status", error.message, "error");
      } finally {
        setBusy(button, false);
      }
    }

    async function initialisePublicScreen() {
      try {
        const results = await Promise.all([api("/api/health"), api("/api/setup/status")]);
        applyProductMode(results[0].product_mode || "full");
        const setup = results[1];
        if (setup.centre_profile) {
          document.getElementById("username").value = setup.centre_profile.username;
          document.getElementById("demo-usernames").innerHTML = "";
          document.getElementById("login-subtitle").textContent = setup.centre_profile.centre_code + " 中心本地账号";
          document.getElementById("password-label").textContent = "密码";
          document.getElementById("password").value = "";
          document.getElementById("setup-profile").textContent = "中心：" + setup.centre_profile.centre_code + "；账号：" + setup.centre_profile.username;
        }
        document.getElementById("setup-form").classList.toggle("hidden", !setup.required);
        document.getElementById("setup-credential-receipt").classList.add("hidden");
        if (currentUser) return;
        document.getElementById("setup-card").classList.toggle("hidden", !setup.required);
        document.getElementById("login-card").classList.toggle("hidden", setup.required);
      } catch (error) {
        applyProductMode("full");
        setStatus("login-status", "初始化失败：" + error.message, "error");
      }
    }

    initialisePublicScreen();

    document.getElementById("login").addEventListener("click", login);
    document.getElementById("generate-setup-password").addEventListener("click", generateSetupPassword);
    document.getElementById("complete-setup").addEventListener("click", completeSetup);
    document.getElementById("copy-setup-credential").addEventListener("click", copySetupCredential);
    document.getElementById("download-setup-credential").addEventListener("click", downloadSetupCredential);
    document.getElementById("continue-after-setup").addEventListener("click", continueAfterSetup);
    document.getElementById("password").addEventListener("keydown", function(event) {
      if (event.key === "Enter") login();
    });
    document.getElementById("logout").addEventListener("click", function() {
      token = null;
      currentUser = null;
      delete document.body.dataset.workspaceMode;
      activeTransferId = null;
      currentCandidatesById = new Map();
      transfersByCandidateId = new Map();
      activeBatchCandidateIds = new Set();
      fieldDictionaryHeaders = [];
      dictionaryReleases = [];
      activeDictionaryReleaseId = null;
      currentDictionaryDraftId = null;
      candidateQualityById = new Map();
      activeRecognitionJobId = null;
      activeRecognitionJob = null;
      recognitionFieldOptions = [];
      selectedRecognitionFieldCodes = new Set();
      candidateEvidenceUrls.forEach(function(url) { URL.revokeObjectURL(url); });
      candidateEvidenceUrls = new Map();
      loadedCandidateEvidenceIds = new Set();
      document.getElementById("recognition-field-search").value = "";
      renderRecognitionFieldOptions();
      confirmedRecordsExpanded = false;
      kimiServiceReady = false;
      kimiUserEnabled = false;
      kimiIntegrationState = "key_required";
      renderKimiPreference();
      resetDeidentificationPanel();
      document.getElementById("field-dictionary-section").classList.add("hidden");
      document.getElementById("central-operations-controls").classList.add("hidden");
      document.getElementById("workbench").classList.add("hidden");
      document.getElementById("kimi-settings-card").classList.add("hidden");
      document.getElementById("show-kimi-settings").setAttribute("aria-expanded", "false");
      document.getElementById("login-card").classList.remove("hidden");
      setProgress(1);
      renderRecognitionJob(null);
      document.getElementById("username").focus();
    });
    document.getElementById("subject-ref").addEventListener("blur", function(event) {
      event.target.value = event.target.value.trim().toUpperCase();
    });
    document.getElementById("event-ref").addEventListener("change", function() {
      refreshRecognitionFields();
    });
    document.getElementById("recognition-field-search").addEventListener("input", renderRecognitionFieldOptions);
    document.getElementById("select-all-recognition-fields").addEventListener("click", function() {
      selectRecognitionFields(function() { return true; });
    });
    document.getElementById("select-pulmonary-fields").addEventListener("click", function() {
      selectRecognitionFields(function(field) { return field.category === "pulmonary_function"; });
    });
    document.getElementById("clear-recognition-fields").addEventListener("click", function() {
      selectRecognitionFields(function() { return false; });
    });
    document.getElementById("recognition-field-options").addEventListener("change", function(event) {
      const checkbox = event.target.closest("[data-recognition-field-code]");
      if (!checkbox) return;
      if (checkbox.checked) selectedRecognitionFieldCodes.add(checkbox.dataset.recognitionFieldCode);
      else selectedRecognitionFieldCodes.delete(checkbox.dataset.recognitionFieldCode);
      renderRecognitionFieldOptions();
      setStatus(
        "recognition-field-status",
        selectedRecognitionFieldCodes.size
          ? "本批次只会为已选项目创建候选。"
          : "至少选择一个项目后才能开始识别。",
        selectedRecognitionFieldCodes.size ? "success" : "warning"
      );
    });
    document.getElementById("upload-and-recognize").addEventListener("click", function(event) {
      uploadAndRecognize(event.currentTarget);
    });
    document.getElementById("refresh-recognition-job").addEventListener("click", refreshActiveRecognitionJob);
    document.getElementById("run-recognition-job").addEventListener("click", function(event) { runActiveRecognitionJob(event.currentTarget); });
    document.getElementById("retry-recognition-job").addEventListener("click", function(event) { retryActiveRecognitionJob(event.currentTarget); });
    document.getElementById("cancel-recognition-job").addEventListener("click", function(event) { cancelActiveRecognitionJob(event.currentTarget); });
    document.getElementById("add-patient-reports").addEventListener("click", function() {
      addPatientReportsToQueue();
    });
    document.getElementById("patient-upload-queue").addEventListener("click", function(event) {
      const button = event.target.closest('[data-action="remove-queued-report"]');
      if (button) removeQueuedPatientReport(button.dataset.queueId);
    });
    document.getElementById("kimi-toggle").addEventListener("click", function() {
      if (!kimiServiceReady) return;
      kimiUserEnabled = !kimiUserEnabled;
      activeUploadBatch.forEach(function(item) {
        if (!item.activeSourceId) item.useKimi = kimiUserEnabled;
      });
      renderKimiPreference();
      setStatus(
        "source-status",
        kimiUserEnabled
          ? "Kimi 已启用：人工确认去标识化后，本批次将使用本地 OCR + Kimi K3。"
          : "Kimi 已关闭：本批次只运行本地 OCR，不会向 Kimi 发送图片。",
        kimiUserEnabled ? "success" : "warning"
      );
    });
    document.getElementById("show-kimi-settings").addEventListener("click", toggleKimiSettings);
    document.getElementById("save-kimi-key").addEventListener("click", saveKimiKey);
    document.querySelectorAll(".workspace-nav a[href^='#']").forEach(function(link) {
      link.addEventListener("click", function() {
        const target = document.getElementById(link.hash.slice(1));
        if (target instanceof HTMLDetailsElement) target.open = true;
        setWorkspaceNavigationCurrent(link.hash);
      });
    });
    document.getElementById("workspace-primary-action").addEventListener("click", function(event) {
      const target = document.getElementById(event.currentTarget.hash.slice(1));
      if (target instanceof HTMLDetailsElement) target.open = true;
      setWorkspaceNavigationCurrent(event.currentTarget.hash);
    });
    document.getElementById("download-submitted-excel").addEventListener("click", function(event) {
      downloadSubmittedExcel(event.currentTarget);
    });
    document.getElementById("download-reviewed-package").addEventListener("click", function(event) {
      downloadReviewedPackage(event.currentTarget);
    });
    document.getElementById("offline-package-file").addEventListener("change", function(event) {
      importReviewedPackage(event.currentTarget);
    });
    document.querySelectorAll("[data-bulk-accept-group]").forEach(function(button) {
      button.addEventListener("click", function(event) {
        acceptCurrentBatchGroup(event.currentTarget, event.currentTarget.dataset.bulkAcceptGroup);
      });
    });
    document.getElementById("image-file").addEventListener("change", updateFileSelection);
    const imageDropzone = document.getElementById("image-dropzone");
    ["dragenter", "dragover"].forEach(function(eventName) {
      imageDropzone.addEventListener(eventName, function(event) {
        event.preventDefault();
        imageDropzone.classList.add("drag-active");
      });
    });
    ["dragleave", "drop"].forEach(function(eventName) {
      imageDropzone.addEventListener(eventName, function(event) {
        event.preventDefault();
        imageDropzone.classList.remove("drag-active");
      });
    });
    imageDropzone.addEventListener("drop", function(event) {
      const files = event.dataTransfer && event.dataTransfer.files;
      if (files && files.length) {
        document.getElementById("image-file").files = files;
        updateFileSelection();
      }
    });
    document.getElementById("field-dictionary-search").addEventListener("input", renderFieldDictionary);
    document.getElementById("field-dictionary-event").addEventListener("change", renderFieldDictionary);
    document.getElementById("refresh-field-dictionary").addEventListener("click", refreshFieldDictionary);
    document.getElementById("refresh-operations").addEventListener("click", refreshOperations);
    document.getElementById("refresh-package-import-logs").addEventListener("click", refreshPackageImportLogs);
    document.getElementById("upload-structured-csv").addEventListener("click", function(event) { uploadStructuredCsv(event.currentTarget); });
    document.getElementById("place-transfer-hold").addEventListener("click", function(event) { appendTransferHold("held", event.currentTarget); });
    document.getElementById("release-transfer-hold").addEventListener("click", function(event) { appendTransferHold("released", event.currentTarget); });
    document.getElementById("create-analysis-snapshot").addEventListener("click", function(event) { createAnalysisSnapshot(event.currentTarget); });
    document.getElementById("create-user-account").addEventListener("click", function(event) { createUserAccount(event.currentTarget); });
    document.getElementById("create-centre-accounts").addEventListener("click", function(event) { createCentreAccounts(event.currentTarget); });
    document.getElementById("account-role").addEventListener("change", function(event) {
      document.getElementById("account-centre").disabled = event.target.value !== "site_investigator";
    });
    document.getElementById("create-dictionary-draft").addEventListener("click", function(event) { createDictionaryDraft(event.currentTarget); });
    document.getElementById("publish-dictionary-draft").addEventListener("click", function(event) { publishDictionaryDraft(event.currentTarget); });
    document.getElementById("rollback-dictionary-release").addEventListener("click", function(event) { rollbackDictionaryRelease(event.currentTarget); });
    document.getElementById("deidentification-review-attestation").addEventListener("change", function(event) {
      const readyItems = activeUploadBatch.filter(function(item) {
        return (item.draftId && item.previewUrl) || (item.isPdf && item.activeSourceId);
      });
      document.getElementById("confirm-deidentification-draft").disabled = !event.target.checked || readyItems.length === 0;
    });
    document.getElementById("confirm-deidentification-draft").addEventListener("click", async function(event) {
      const button = event.currentTarget;
      const attestation = document.getElementById("deidentification-review-attestation");
      const readyItems = activeUploadBatch.filter(function(item) {
        return (item.draftId && item.previewUrl) || (item.isPdf && item.activeSourceId);
      });
      if (!readyItems.length || !attestation.checked) {
        setStatus("deidentification-status", "请先逐张核对全部预览并勾选统一确认。", "error");
        return;
      }
      attestation.disabled = true;
      setBusy(button, true, "正在识别 0 / " + readyItems.length);
      setStatus("deidentification-status", "已记录本批次统一人工确认，正在运行本地识别。");
      if (activeRecognitionJobId) {
        try {
          for (const item of readyItems) {
            item.status = item.isPdf ? "正在读取肺功能 PDF 文本层" : "正在确认遮盖";
            item.tone = "";
            renderBatchFileStatuses();
            if (!item.isPdf) {
              const confirmed = await api("/api/deidentification-drafts/" + item.draftId + "/confirm", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ human_review_attestation: true }),
              });
              item.activeSourceId = confirmed.derivative_source_file.id;
            }
          }
          const job = await api("/api/recognition-jobs/" + activeRecognitionJobId + "/run", { method: "POST" });
          renderRecognitionJob(job);
          activeBatchCandidateIds = new Set(
            (job.items || []).flatMap(function(item) { return item.candidate_ids || []; })
          );
          await refreshCandidates();
          renderBatchFileStatuses();
          setBusy(button, false);
          button.disabled = true;
          setIntakeQueueLocked(false);
          const failedItems = (job.items || []).filter(function(item) { return item.status === "failed"; });
          const succeededItems = (job.items || []).filter(function(item) { return item.status === "succeeded"; });
          setStatus("deidentification-status", "本批次任务完成：成功 " + succeededItems.length + " 份，失败 " + failedItems.length + " 份。", failedItems.length ? "warning" : "success");
          setStatus("recognition-status", "识别任务已完成：候选值已进入审核；失败项可在任务面板重试。", failedItems.length ? "warning" : "success");
          if (succeededItems.length) {
            setStatus("workflow-status", "请逐项核对检查单，并接受、修改或拒绝候选。");
            setProgress(2);
          }
          return;
        } catch (error) {
          setStatus("recognition-job-status", "识别任务执行失败：" + error.message, "error");
          setBusy(button, false);
          button.disabled = false;
          attestation.disabled = false;
          return;
        }
      }
      let completed = 0;
      let recognizedImages = 0;
      let candidateCount = 0;
      let failed = 0;
      for (const item of readyItems) {
        setBusy(button, true, "正在识别 " + completed + " / " + readyItems.length);
        updateBatchProgress("确认并批量识别", completed, readyItems.length);
          item.status = item.isPdf ? "正在本机解析 PDF" : "正在确认遮盖";
        item.tone = "";
        renderBatchFileStatuses();
        try {
          if (!item.isPdf) {
            const confirmed = await api("/api/deidentification-drafts/" + item.draftId + "/confirm", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ human_review_attestation: true }),
            });
            item.activeSourceId = confirmed.derivative_source_file.id;
          }
          item.status = item.isPdf
            ? "正在读取肺功能 PDF 文本层"
            : item.useKimi ? "正在进行本地 OCR 与 Kimi 复核" : "正在进行本地 OCR（Kimi 已关闭）";
          renderBatchFileStatuses();
          const created = await recognizeBatchItem(item);
          item.candidateCount = created.length;
          created.forEach(function(candidate) { activeBatchCandidateIds.add(candidate.id); });
          item.status = (item.isPdf ? "PDF 本地解析完成" : item.useKimi ? "混合识别完成" : "本地 OCR 完成") + "，生成 " + created.length + " 个候选";
          item.tone = "success";
          recognizedImages += 1;
          candidateCount += created.length;
        } catch (error) {
          item.status = "识别失败：" + error.message;
          item.tone = "error";
          failed += 1;
        }
        completed += 1;
        updateBatchProgress("确认并批量识别", completed, readyItems.length);
        renderBatchFileStatuses();
      }
      setBusy(button, false);
      button.disabled = true;
      setStatus(
        "deidentification-status",
        "本批次确认已完成：成功识别 " + recognizedImages + " 份，失败 " + failed + " 份。",
        failed ? "warning" : "success"
      );
      setStatus(
        "recognition-status",
        "批量识别完成：共生成 " + candidateCount + " 个待审核候选值。可逐项审核，或按质量分组批量确认。",
        failed ? "warning" : "success"
      );
      if (candidateCount) {
        setStatus("workflow-status", "请逐项核对检查单，并接受、修改或拒绝候选。");
        setProgress(2);
      }
      await refreshCandidates();
    });
    document.getElementById("submit-all-confirmed").addEventListener("click", function(event) {
      submitAllConfirmed(event.currentTarget);
    });
    document.getElementById("toggle-confirmed-records").addEventListener("click", function(event) {
      confirmedRecordsExpanded = !confirmedRecordsExpanded;
      event.currentTarget.setAttribute("aria-expanded", confirmedRecordsExpanded ? "true" : "false");
      renderConfirmedRecords(Array.from(currentCandidatesById.values()));
    });
    document.getElementById("refresh-transfers").addEventListener("click", refreshTransfers);
    document.getElementById("verify-active-transfer").addEventListener("click", async function() {
      if (!activeTransferId) return;
      try { await showTransferArtifacts(activeTransferId); }
      catch (error) { setStatus("transfer-integrity", error.message, "error"); }
    });
    document.getElementById("download-active-receipt").addEventListener("click", async function() {
      if (!activeTransferId) return;
      try {
        const response = await fetch("/api/transfers/" + activeTransferId + "/receipt", {
          headers: { Authorization: "Bearer " + token },
        });
        if (!response.ok) {
          const body = await response.json().catch(function() { return {}; });
          throw new Error(humanizeApiError(body.detail, response.status));
        }
        const url = URL.createObjectURL(await response.blob());
        const link = document.createElement("a");
        link.href = url;
        link.download = "transfer-" + activeTransferId + "-receipt.json";
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
        setStatus("workflow-status", "传输请求回执已下载。");
      } catch (error) {
        setStatus("workflow-status", error.message, "error");
      }
    });
    document.getElementById("submit-active-transfer").addEventListener("click", function(event) {
      if (activeTransferId) submitTransfer(activeTransferId, event.currentTarget);
    });

    document.addEventListener("click", async function(event) {
      const button = event.target.closest("button[data-action]");
      if (!button) return;
      const action = button.dataset.action;
      const candidateId = button.dataset.candidateId;
      const transferId = button.dataset.transferId;
      const issueId = button.dataset.issueId;
      const taskId = button.dataset.taskId;
      const snapshotId = button.dataset.snapshotId;
      const accountId = button.dataset.accountId;
      if (action === "load-review-evidence") {
        await loadCandidateEvidence(candidateId, button);
      } else if (action === "accept-candidate") {
        await submitCandidateReview(candidateId, "accept", button);
      } else if (action === "open-review") {
        openInlineReview(candidateId, button.dataset.decision);
      } else if (action === "cancel-review") {
        document.getElementById("review-form-" + candidateId).classList.add("hidden");
      } else if (action === "confirm-review") {
        const form = document.getElementById("review-form-" + candidateId);
        await submitCandidateReview(candidateId, form.dataset.decision, button);
      } else if (action === "freeze-submit") {
        await freezeAndSubmit(candidateId, button);
      } else if (action === "view-transfer") {
        activeTransferId = transferId;
        try { await showTransferArtifacts(transferId); }
        catch (error) { setStatus("ledger-status", error.message, "error"); }
      } else if (action === "submit-transfer") {
        await submitTransfer(transferId, button);
      } else if (action === "retry-transfer") {
        setBusy(button, true, "正在排队…");
        try {
          await api("/api/transfers/" + transferId + "/retry", { method: "POST" });
          setStatus("ledger-status", "传输已重新排队。", "success");
          await refreshTransfers();
        } catch (error) {
          setStatus("ledger-status", error.message, "error");
          setBusy(button, false);
        }
      } else if (action === "open-reconciliation") {
        const panel = document.getElementById("reconciliation-" + transferId);
        panel.classList.remove("hidden");
        panel.querySelector("[data-reconciliation-note]").focus();
      } else if (action === "cancel-reconciliation") {
        document.getElementById("reconciliation-" + transferId).classList.add("hidden");
      } else if (action === "confirm-reconciliation") {
        const note = document.querySelector('[data-reconciliation-note="' + transferId + '"]').value.trim();
        if (!note) {
          setStatus("reconciliation-status-" + transferId, "请输入人工对账结论。", "error");
          return;
        }
        setBusy(button, true, "正在保存…");
        try {
          await api("/api/transfers/" + transferId + "/reconcile", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ note: note }),
          });
          setStatus("ledger-status", "人工对账结论已写入审计记录。", "success");
          await refreshTransfers();
        } catch (error) {
          setStatus("reconciliation-status-" + transferId, error.message, "error");
          setBusy(button, false);
        }
      } else if (action === "save-field-header") {
        await saveFieldHeader(button.dataset.eventRef, button.dataset.fieldCode, button);
      } else if (action === "open-data-issue") {
        const input = document.querySelector('[data-new-issue="' + CSS.escape(candidateId) + '"]');
        const message = input ? input.value.trim() : "";
        if (!message) {
          setStatus("operations-status", "请填写需要核对的具体内容。", "error");
          if (input) input.focus();
          return;
        }
        setBusy(button, true, "正在创建…");
        try {
          await api("/api/candidates/" + candidateId + "/data-issues", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: message }),
          });
          input.value = "";
          await refreshOperations();
        } catch (error) {
          setStatus("operations-status", error.message, "error");
          setBusy(button, false);
        }
      } else if (action === "answer-issue") {
        await transitionIssue(issueId, "answer", button);
      } else if (action === "resolve-issue") {
        await transitionIssue(issueId, "resolve", button);
      } else if (action === "reopen-issue") {
        await transitionIssue(issueId, "reopen", button);
      } else if (action === "complete-task") {
        setBusy(button, true, "正在完成…");
        try {
          await api("/api/tasks/" + taskId + "/complete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({}),
          });
          await refreshOperations();
        } catch (error) {
          setStatus("operations-status", error.message, "error");
          setBusy(button, false);
        }
      } else if (action === "download-snapshot") {
        setBusy(button, true, "正在下载…");
        try {
          await downloadSnapshot(snapshotId);
          setStatus("snapshot-status", "快照下载已开始。", "success");
        } catch (error) {
          setStatus("snapshot-status", error.message, "error");
        } finally {
          setBusy(button, false);
        }
      } else if (action === "deactivate-account" || action === "reactivate-account") {
        setBusy(button, true, action === "deactivate-account" ? "正在停用…" : "正在启用…");
        try {
          await api("/api/admin/users/" + accountId + "/" + (action === "deactivate-account" ? "deactivate" : "reactivate"), { method: "POST" });
          setStatus("account-status", action === "deactivate-account" ? "账号已停用，现有会话已撤销。" : "账号已重新启用。", "success");
          await refreshUserAccounts();
        } catch (error) {
          setStatus("account-status", error.message, "error");
          setBusy(button, false);
        }
      }
    });

    window.addEventListener("beforeunload", function() {
      activeBatchPreviewUrls.forEach(function(url) { URL.revokeObjectURL(url); });
      candidateEvidenceUrls.forEach(function(url) { URL.revokeObjectURL(url); });
    });
    renderPendingUploadQueue();
