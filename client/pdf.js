import { PDFDocument, rgb } from "pdf-lib";
import fontkit from "@pdf-lib/fontkit";
import QRCode from "qrcode";

function boxOnPage(box, metadata, page) {
  const scaleX = page.getWidth() / metadata.slide_width;
  const scaleY = page.getHeight() / metadata.slide_height;
  return {
    x: box.left * scaleX,
    y: page.getHeight() - ((box.top + box.height) * scaleY),
    width: box.width * scaleX,
    height: box.height * scaleY,
  };
}

export async function createVoucherPdf({ passwords, ruCount, assets, progress = () => {} }) {
  const output = await PDFDocument.create();
  output.registerFontkit(fontkit);
  const font = await output.embedFont(assets.font, { subset: true });
  const sources = {
    ru: await PDFDocument.load(assets.ru),
    en: await PDFDocument.load(assets.en),
  };
  const fontSize = 18;

  for (let index = 0; index < passwords.length; index += 1) {
    const language = index < ruCount ? "ru" : "en";
    const metadata = assets.layout.templates[language];
    const source = sources[language];
    const pages = await output.copyPages(source, source.getPageIndices());
    pages.forEach((page) => output.addPage(page));
    const target = pages[metadata.password.page];
    const passwordBox = boxOnPage(metadata.password, metadata, target);
    const qrBox = boxOnPage(metadata.qr, metadata, target);
    const password = passwords[index];
    const textWidth = font.widthOfTextAtSize(password, fontSize);
    target.drawText(password, {
      x: passwordBox.x + Math.max(0, (passwordBox.width - textWidth) / 2),
      y: passwordBox.y + 2,
      size: fontSize,
      font,
      color: rgb(0.05, 0.05, 0.06),
    });
    const qrUrl = await QRCode.toDataURL(password, {
      errorCorrectionLevel: "M",
      margin: 2,
      width: 512,
      color: { dark: "#000000", light: "#FFFFFF" },
    });
    const qrBytes = await (await fetch(qrUrl)).arrayBuffer();
    const qr = await output.embedPng(qrBytes);
    target.drawImage(qr, {
      x: qrBox.x,
      y: qrBox.y,
      width: qrBox.width,
      height: qrBox.height,
    });
    progress(index + 1, passwords.length);
    if (typeof requestAnimationFrame === "function" && index % 4 === 3) {
      await new Promise((resolve) => requestAnimationFrame(resolve));
    }
  }
  return output.save({ useObjectStreams: true, addDefaultPage: false });
}
