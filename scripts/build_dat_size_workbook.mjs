import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, Workbook, SpreadsheetFile } from "@oai/artifact-tool";

const projectRoot = process.cwd();
const inputPath = path.join(projectRoot, "dat_size_summary.tsv");
const outputDir = path.join(projectRoot, "outputs", "dat_sizes");
const outputPath = path.join(outputDir, "romset_dat_sizes.xlsx");
const verificationPath = path.join(outputDir, "romset_dat_sizes_verification.json");

function formatBytes(bytes) {
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  let value = Number(bytes);
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(2)} ${units[unitIndex]}`;
}

function colLetter(index) {
  let n = index + 1;
  let result = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    result = String.fromCharCode(65 + rem) + result;
    n = Math.floor((n - 1) / 26);
  }
  return result;
}

function makeRange(rowStart, colStart, rowCount, colCount) {
  return `${colLetter(colStart)}${rowStart}:${colLetter(colStart + colCount - 1)}${rowStart + rowCount - 1}`;
}

function parseTsv(text) {
  const [headerLine, ...lines] = text.trim().split(/\r?\n/);
  const headers = headerLine.split("\t");
  return lines
    .filter((line) => line.trim().length > 0)
    .map((line) => {
      const values = line.split("\t");
      const row = {};
      headers.forEach((header, index) => {
        row[header] = values[index] ?? "";
      });
      row.games = row.games === "" ? "" : Number(row.games);
      row.rom_entries = row.rom_entries === "" ? "" : Number(row.rom_entries);
      row.total_bytes = row.total_bytes === "" ? "" : Number(row.total_bytes);
      return row;
    });
}

const tsvText = await fs.readFile(inputPath, "utf8");
const rows = parseTsv(tsvText);
const validRows = rows.filter((row) => !row.error);

const families = ["no-intro", "redump"];
const summaryRows = families.map((family) => {
  const subset = validRows.filter((row) => row.family === family);
  const dats = subset.length;
  const games = subset.reduce((sum, row) => sum + row.games, 0);
  const romEntries = subset.reduce((sum, row) => sum + row.rom_entries, 0);
  const totalBytes = subset.reduce((sum, row) => sum + row.total_bytes, 0);
  return [family, dats, games, romEntries, totalBytes, formatBytes(totalBytes)];
});

const totalBytesAll = validRows.reduce((sum, row) => sum + row.total_bytes, 0);
summaryRows.push([
  "total",
  validRows.length,
  validRows.reduce((sum, row) => sum + row.games, 0),
  validRows.reduce((sum, row) => sum + row.rom_entries, 0),
  totalBytesAll,
  formatBytes(totalBytesAll),
]);

const topByFamily = [];
for (const family of families) {
  const topFive = validRows
    .filter((row) => row.family === family)
    .sort((a, b) => b.total_bytes - a.total_bytes)
    .slice(0, 5);
  for (const row of topFive) {
    topByFamily.push([
      family,
      row.file,
      row.games,
      row.rom_entries,
      row.total_bytes,
      formatBytes(row.total_bytes),
    ]);
  }
}

const workbook = Workbook.create();
const summarySheet = workbook.worksheets.add("Summary");
const detailSheet = workbook.worksheets.add("All DATs");

const summaryMatrix = [
  ["ROM Set Size Summary"],
  [],
  ["Family", "DAT Count", "Games", "ROM Entries", "Total Bytes", "Total Size"],
  ...summaryRows,
  [],
  ["Top 5 by Family"],
  ["Family", "DAT File", "Games", "ROM Entries", "Total Bytes", "Total Size"],
  ...topByFamily,
];

summarySheet.getRange(makeRange(1, 0, summaryMatrix.length, 6)).values = summaryMatrix.map((row) => {
  const padded = [...row];
  while (padded.length < 6) padded.push(null);
  return padded;
});

const detailHeader = [["Family", "DAT File", "Games", "ROM Entries", "Total Bytes", "Total Size", "Error"]];
const detailRows = rows.map((row) => [
  row.family,
  row.file,
  row.games === "" ? null : row.games,
  row.rom_entries === "" ? null : row.rom_entries,
  row.total_bytes === "" ? null : row.total_bytes,
  row.total_bytes === "" ? null : formatBytes(row.total_bytes),
  row.error || null,
]);
const detailMatrix = [...detailHeader, ...detailRows];
detailSheet.getRange(makeRange(1, 0, detailMatrix.length, 7)).values = detailMatrix;

await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

const savedBlob = await FileBlob.load(outputPath);
const importedWorkbook = await SpreadsheetFile.importXlsx(savedBlob);
const summaryCheck = await importedWorkbook.inspect({
  kind: "table",
  range: "Summary!A1:F14",
  include: "values,formulas",
  tableMaxRows: 14,
  tableMaxCols: 6,
});
const detailCheck = await importedWorkbook.inspect({
  kind: "table",
  range: "All DATs!A1:G12",
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 7,
});
const errorScan = await importedWorkbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "formula error scan",
});

await fs.writeFile(
  verificationPath,
  JSON.stringify(
    {
      outputPath,
      rowCount: rows.length,
      summaryRows: summaryRows.length,
      summaryCheck: summaryCheck.ndjson,
      detailCheck: detailCheck.ndjson,
      errorScan: errorScan.ndjson,
    },
    null,
    2,
  ),
  "utf8",
);

console.log(JSON.stringify({ outputPath, verificationPath, rowCount: rows.length, summaryRows: summaryRows.length }));
