// Copies a playbook for rendering, rewriting the app port and optionally
// stripping narration (silent mode: no TTS calls, no OpenAI key needed).
// Usage: node prepare-playbook.mjs <ndemo-dir> <src.yaml> <dest.yaml> <port> [--silent]
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const [ndemoDir, src, dest, port, ...flags] = process.argv.slice(2);
const require = createRequire(path.join(path.resolve(ndemoDir), "package.json"));
const YAML = require("yaml");

const doc = YAML.parse(fs.readFileSync(src, "utf-8"));
const url = new URL(doc.app.url);
url.port = port;
doc.app.url = url.toString();

if (flags.includes("--silent")) {
  for (const seg of doc.segments) {
    delete seg.narration;
    delete seg.audioDuration;
  }
}

fs.mkdirSync(path.dirname(dest), { recursive: true });
fs.writeFileSync(dest, YAML.stringify(doc, { lineWidth: 0 }));
