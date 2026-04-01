#!/usr/bin/env node

const fs = require("fs");
const path = require("path");
const torrentStream = require("torrent-stream");

function emit(event) {
  process.stdout.write(`${JSON.stringify(event)}\n`);
}

function normalizePath(value) {
  return String(value || "").replace(/\\/g, "/").toLowerCase();
}

const [torrentUrl, targetFileName, destinationPath, tempPathArg] = process.argv.slice(2);

if (!torrentUrl || !targetFileName || !destinationPath) {
  emit({
    type: "error",
    message: "Usage: node minerva_torrent_download.js <torrent_url> <target_file_name> <destination_path> [temp_path]"
  });
  process.exit(2);
}

const tempPath = tempPathArg || path.join(process.cwd(), ".torrent-tmp");
const timeoutMs = Number(process.env.MINERVA_TORRENT_TIMEOUT_MS || 0);

fs.mkdirSync(path.dirname(destinationPath), { recursive: true });
fs.mkdirSync(tempPath, { recursive: true });

let engine = null;
let progressTimer = null;
let timeoutHandle = null;
let finished = false;

function finish(exitCode, extraEvent) {
  if (finished) return;
  finished = true;

  if (progressTimer) clearInterval(progressTimer);
  if (timeoutHandle) clearTimeout(timeoutHandle);

  if (extraEvent) emit(extraEvent);

  if (!engine) {
    process.exit(exitCode);
    return;
  }

  engine.destroy(() => process.exit(exitCode));
}

(async () => {
  const response = await fetch(torrentUrl);
  if (!response.ok) {
    finish(1, { type: "error", message: `Unable to fetch torrent: HTTP ${response.status}` });
    return;
  }

  const torrentBuffer = Buffer.from(await response.arrayBuffer());

  engine = torrentStream(torrentBuffer, {
    path: tempPath,
    connections: 80,
    uploads: 4,
    tracker: true,
    dht: true
  });

  engine.on("error", (err) => finish(1, { type: "error", message: String(err) }));

  if (timeoutMs > 0) {
    timeoutHandle = setTimeout(() => {
      finish(1, { type: "error", message: `Torrent timeout after ${timeoutMs} ms` });
    }, timeoutMs);
  }

  engine.on("ready", () => {
    emit({
      type: "metadata",
      torrentName: engine.torrent && engine.torrent.name,
      files: engine.files.length
    });

    const wanted = normalizePath(targetFileName);
    const targetFile = engine.files.find((file) => {
      const fileName = normalizePath(file.name);
      const filePath = normalizePath(file.path);
      return fileName === wanted || filePath === wanted || filePath.endsWith(`/${wanted}`);
    });

    if (!targetFile) {
      finish(1, {
        type: "error",
        message: `Target file not found in torrent: ${targetFileName}`
      });
      return;
    }

    emit({
      type: "selected",
      file: targetFile.path,
      length: targetFile.length
    });

    progressTimer = setInterval(() => {
      const swarm = engine.swarm;
      const downloadSpeed = swarm && typeof swarm.downloadSpeed === "function"
        ? swarm.downloadSpeed()
        : 0;
      emit({
        type: "progress",
        progress: targetFile.length > 0
          ? Number(((swarm.downloaded / targetFile.length) * 100).toFixed(2))
          : 0,
        downloadSpeed,
        downloaded: swarm.downloaded,
        peers: swarm.wires ? swarm.wires.length : 0
      });
    }, 1000);

    const input = targetFile.createReadStream();
    const output = fs.createWriteStream(destinationPath);

    input.on("error", (err) => finish(1, { type: "error", message: String(err) }));
    output.on("error", (err) => finish(1, { type: "error", message: String(err) }));
    output.on("finish", () => {
      finish(0, {
        type: "done",
        file: targetFile.path,
        destination: destinationPath,
        bytes: targetFile.length
      });
    });

    input.pipe(output);
  });
})().catch((err) => {
  finish(1, { type: "error", message: String(err) });
});
