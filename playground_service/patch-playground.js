"use strict";

const fs = require("node:fs");
const path = require("node:path");

const clientDir = path.join(
  __dirname,
  "node_modules",
  "@microsoft",
  "m365agentsplayground",
  "dist",
  "client",
  "static",
  "js",
);
const bundle = fs.readdirSync(clientDir).find((name) => /^main\..+\.js$/.test(name));
if (!bundle) throw new Error("Unable to find the Agents Playground client bundle");

const bundlePath = path.join(clientDir, bundle);
const source = fs.readFileSync(bundlePath, "utf8");
const original = 'return t.protocol="ws:",t.toString()';
const replacement = 'return t.protocol="https:"===t.protocol?"wss:":"ws:",t.toString()';
const occurrences = source.split(original).length - 1;
if (occurrences !== 1) {
  throw new Error(`Expected one insecure WebSocket protocol marker, found ${occurrences}`);
}

fs.writeFileSync(bundlePath, source.replace(original, replacement));
console.log(`Patched HTTPS WebSocket support in ${bundle}`);
