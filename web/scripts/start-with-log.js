#!/usr/bin/env node
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const logFile = process.env.LOG_FILE || "/logs/tdarr_sync.log";

fs.mkdirSync(path.dirname(logFile), { recursive: true });
const logStream = fs.createWriteStream(logFile, { flags: "a" });

const timestamp = () => new Date().toISOString();

function writeLine(line) {
  if (!line) {
    return;
  }
  const entry = `${timestamp()} [WEB] ${line}\n`;
  logStream.write(entry);
  process.stdout.write(`${line}\n`);
}

const child = spawn("npm", ["run", "start:raw"], {
  env: process.env,
  stdio: ["inherit", "pipe", "pipe"],
});

child.stdout.on("data", (chunk) => {
  chunk
    .toString()
    .split(/\r?\n/)
    .forEach(writeLine);
});

child.stderr.on("data", (chunk) => {
  chunk
    .toString()
    .split(/\r?\n/)
    .forEach(writeLine);
});

child.on("close", (code) => {
  logStream.end();
  process.exit(code ?? 0);
});
