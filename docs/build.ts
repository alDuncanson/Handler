import { readFileSync, writeFileSync, mkdirSync, existsSync } from "fs";
import { join, dirname } from "path";

const srcDir = join(import.meta.dir, "src");
const distDir = join(import.meta.dir, "dist");

const html = readFileSync(join(srcDir, "index.html"), "utf-8");
const css = readFileSync(join(srcDir, "style.css"), "utf-8");
const js = readFileSync(join(srcDir, "theme.js"), "utf-8");

const inlined = html
  .replace(
    '<link rel="stylesheet" href="style.css">',
    `<style>${css}</style>`
  )
  .replace(
    '<script src="theme.js"></script>',
    `<script>${js}</script>`
  );

if (!existsSync(distDir)) {
  mkdirSync(distDir, { recursive: true });
}

writeFileSync(join(distDir, "index.html"), inlined);
console.log("Built docs/dist/index.html");
