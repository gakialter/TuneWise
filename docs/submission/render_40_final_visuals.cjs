"use strict";

const fs = require("fs");
const path = require("path");
const sharp = require("sharp");

const output = path.join(__dirname, "assets", "40-final");
const names = [
  "01_before_after",
  "02_dual_layer_ai_architecture",
  "03_core_pipeline",
  "04_safe_parameter_decision",
  "05_replay_opcua_safety",
  "06_demo_evidence_card",
  "07_aily_rag_workflow",
  "08_validation_summary",
];

async function main() {
  for (const name of names) {
    const source = path.join(output, name + ".svg");
    const target = path.join(output, name + ".png");
    if (!fs.existsSync(source)) {
      throw new Error("Missing SVG source: " + source);
    }
    await sharp(source, { density: 144 })
      .resize(2560, 1440, { fit: "fill" })
      .png({ compressionLevel: 9, adaptiveFiltering: true })
      .toFile(target);
    process.stdout.write("rendered " + name + ".png\n");
  }
}

main().catch((error) => {
  process.stderr.write(String(error.stack || error) + "\n");
  process.exitCode = 1;
});
