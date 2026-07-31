import { readFile, mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { createVoucherPdf } from "../client/pdf.js";

const root = resolve(import.meta.dirname, "..");
const publicDir = resolve(root, "web", "public");
const outputDir = resolve(root, "tmp", "pdfs", "client-verification");
await mkdir(outputDir, { recursive: true });

const asArrayBuffer = async (path) => {
  const buffer = await readFile(path);
  return buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength);
};

const assets = {
  layout: JSON.parse(await readFile(resolve(publicDir, "templates", "layout.json"), "utf8")),
  ru: await asArrayBuffer(resolve(publicDir, "templates", "brochure_ru.pdf")),
  en: await asArrayBuffer(resolve(publicDir, "templates", "brochure_en.pdf")),
  font: await asArrayBuffer(resolve(publicDir, "fonts", "circe.ttf")),
};

const started = performance.now();
const bytes = await createVoucherPdf({
  passwords: ["TEST-RU01", "TEST-EN02"],
  ruCount: 1,
  assets,
});
const target = resolve(outputDir, "browser-generated-vouchers.pdf");
await writeFile(target, bytes);
console.log(JSON.stringify({ target, bytes: bytes.length, milliseconds: Math.round(performance.now() - started) }));
