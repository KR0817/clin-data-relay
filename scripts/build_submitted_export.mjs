import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputPath = process.argv[2];
const previewDirectory = process.argv[3] || "";
if (!outputPath) throw new Error("output path is required");

let inputText = "";
for await (const chunk of process.stdin) inputText += chunk;
const payload = JSON.parse(inputText);

const workbook = Workbook.create();
const darkBlue = "#1E40AF";
const paleBlue = "#DBEAFE";
const ink = "#172554";
const muted = "#475569";
const uiFont = "Microsoft YaHei";
const exportTitle = payload.export_title || "已提交临床数据导出";
const inclusionRule = payload.inclusion_rule || "仅纳入 LibreClinica 已确认 submitted 的记录";
const authorityNote = payload.authority_note || "LibreClinica；本工作簿为便捷导出副本";
const valueCount = payload.value_count ?? payload.submitted_value_count ?? 0;
const includeAuthorityStatus = payload.include_authority_status === true;
const authorityStatusHeader = payload.authority_status_header || "LibreClinica状态";

function excelSafeValue(value) {
  if (typeof value !== "string") return value;
  return /^[=+\-@]/.test(value) ? `'${value}` : value;
}

function styleHeader(range) {
  range.format = {
    fill: darkBlue,
    font: { name: uiFont, size: 10, bold: true, color: "#FFFFFF" },
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#1E3A8A" },
  };
}

function addDataSheet(eventRef, eventData, tableIndex) {
  const sheet = workbook.worksheets.add(eventRef);
  sheet.showGridLines = false;
  const fixedHeaders = ["中心", "受试者研究编号"];
  if (includeAuthorityStatus) fixedHeaders.push(excelSafeValue(authorityStatusHeader));
  const headers = [...fixedHeaders, ...eventData.columns.map((column) => excelSafeValue(column.display_header))];
  const rows = eventData.rows.map((row) => [
    excelSafeValue(row.centre_code),
    excelSafeValue(row.edc_subject_ref),
    ...(includeAuthorityStatus ? [excelSafeValue(row.authority_status)] : []),
    ...eventData.columns.map((column) => excelSafeValue(row.values[column.field_code] ?? null)),
  ]);
  const matrix = [headers, ...rows];
  const dataRange = sheet.getRangeByIndexes(0, 0, matrix.length, headers.length);
  dataRange.values = matrix;
  dataRange.format = {
    font: { name: uiFont, size: 10, color: ink },
    verticalAlignment: "center",
  };
  styleHeader(sheet.getRangeByIndexes(0, 0, 1, headers.length));
  sheet.getRangeByIndexes(0, 0, matrix.length, 1).format.columnWidth = 16;
  sheet.getRangeByIndexes(0, 1, matrix.length, 1).format.columnWidth = 22;
  if (includeAuthorityStatus) {
    sheet.getRangeByIndexes(0, 2, matrix.length, 1).format.columnWidth = 20;
  }
  if (headers.length > fixedHeaders.length) {
    sheet.getRangeByIndexes(0, fixedHeaders.length, matrix.length, headers.length - fixedHeaders.length).format.columnWidth = 18;
  }
  sheet.getRangeByIndexes(0, 0, 1, headers.length).format.rowHeight = 36;
  sheet.freezePanes.freezeRows(1);
  sheet.freezePanes.freezeColumns(fixedHeaders.length);
  if (rows.length) {
    const table = sheet.tables.add(
      sheet.getRangeByIndexes(0, 0, matrix.length, headers.length),
      true,
      `SubmittedEvent${tableIndex}`,
    );
    table.style = "TableStyleMedium2";
    table.showFilterButton = true;
  }
}

const notes = workbook.worksheets.add("导出说明");
notes.showGridLines = false;
notes.getRange("A1:B8").values = [
  [exportTitle, ""],
  ["生成时间（UTC）", `UTC ${payload.generated_at}`],
  ["导出范围", payload.scope],
  ["纳入规则", inclusionRule],
  ["权威记录", authorityNote],
  ["数据字典", payload.dictionary_id],
  ["字典版本", payload.dictionary_version],
  ["字段值数量", valueCount],
];
notes.getRange("A1:B8").format = {
  font: { name: uiFont, size: 10, color: ink },
  verticalAlignment: "center",
};
notes.getRange("A1:B1").merge();
notes.getRange("A1").values = [[exportTitle]];
notes.getRange("A1:B1").format = {
  fill: darkBlue,
  font: { name: uiFont, bold: true, color: "#FFFFFF", size: 16 },
  verticalAlignment: "center",
};
notes.getRange("A2:A8").format = { fill: paleBlue, font: { name: uiFont, size: 10, bold: true, color: ink } };
notes.getRange("B2:B8").format = { font: { name: uiFont, size: 10, color: muted }, wrapText: true };
notes.getRange("A1:B8").format.borders = { preset: "outside", style: "thin", color: "#BFDBFE" };
notes.getRange("A1:A8").format.columnWidth = 24;
notes.getRange("B1:B8").format.columnWidth = 58;
notes.getRange("A1:B1").format.rowHeight = 30;

Object.entries(payload.events).forEach(([eventRef, eventData], index) => {
  addDataSheet(eventRef, eventData, index + 1);
});

const mapping = workbook.worksheets.add("字段映射");
mapping.showGridLines = false;
const mappingHeaders = ["访视", "字段代码（不可变）", "当前显示表头", "原始 Excel 表头", "修订版本"];
const mappingRows = payload.field_mapping.map((item) => [
  excelSafeValue(item.event_ref),
  excelSafeValue(item.field_code),
  excelSafeValue(item.display_header),
  excelSafeValue(item.source_header),
  item.revision,
]);
const mappingMatrix = [mappingHeaders, ...mappingRows];
const mappingRange = mapping.getRangeByIndexes(0, 0, mappingMatrix.length, mappingHeaders.length);
mappingRange.values = mappingMatrix;
mappingRange.format = {
  font: { name: uiFont, size: 10, color: ink },
  verticalAlignment: "center",
};
styleHeader(mapping.getRangeByIndexes(0, 0, 1, mappingHeaders.length));
mapping.getRangeByIndexes(0, 0, mappingMatrix.length, 2).format.columnWidth = 22;
mapping.getRangeByIndexes(0, 2, mappingMatrix.length, 2).format.columnWidth = 34;
mapping.getRangeByIndexes(0, 4, mappingMatrix.length, 1).format.columnWidth = 14;
mapping.freezePanes.freezeRows(1);
if (mappingRows.length) {
  const table = mapping.tables.add(
    mapping.getRangeByIndexes(0, 0, mappingMatrix.length, mappingHeaders.length),
    true,
    "FieldMapping",
  );
  table.style = "TableStyleMedium2";
  table.showFilterButton = true;
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

if (previewDirectory) {
  await fs.mkdir(previewDirectory, { recursive: true });
  const sheetNames = ["导出说明", ...Object.keys(payload.events), "字段映射"];
  for (const sheetName of sheetNames) {
    const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
    await fs.writeFile(
      `${previewDirectory}/${sheetName}.png`,
      new Uint8Array(await preview.arrayBuffer()),
    );
  }
}
