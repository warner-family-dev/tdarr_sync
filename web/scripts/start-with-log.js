#!/usr/bin/env node
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const logFile = process.env.LOG_FILE || "/logs/tdarr_sync.log";
const timeZone = process.env.TZ || "UTC";

const formatter = new Intl.DateTimeFormat("sv-SE", {
  timeZone,
  hourCycle: "h23",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  timeZoneName: "shortOffset",
});

fs.mkdirSync(path.dirname(logFile), { recursive: true });
const logStream = fs.createWriteStream(logFile, { flags: "a" });

const timestamp = () => {
  const parts = formatter.formatToParts(new Date());
  const lookup = (type) => parts.find((p) => p.type === type)?.value ?? "";
  let offset = lookup("timeZoneName");
  if (offset === "UTC" || offset === "GMT") {
    offset = "+00:00";
  } else if (offset.startsWith("GMT")) {
    offset = offset.slice(3);
  }
  return `${lookup("year")}-${lookup("month")}-${lookup("day")}T${lookup("hour")}:${lookup("minute")}:${lookup("second")}${offset}`;
};

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
