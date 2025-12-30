import { readFile, writeFile, mkdir } from "fs/promises";
import { join } from "path";

const srcDir = join(import.meta.dir, "src");
const outDir = join(import.meta.dir, "dist");

async function build() {
  await mkdir(outDir, { recursive: true });

  const html = await readFile(join(srcDir, "index.html"), "utf-8");
  const css = await readFile(join(srcDir, "style.css"), "utf-8");
  const js = await readFile(join(srcDir, "theme.js"), "utf-8");

  const inlined = html
    .replace(
      '<link rel="stylesheet" href="style.css">',
      `<style>${css}</style>`
    )
    .replace(
      '<script src="theme.js"></script>',
      `<script>${js}</script>`
    );

  await writeFile(join(outDir, "index.html"), inlined);

  console.log("Built docs/dist/index.html");
}

build().catch((err) => {
  console.error(err);
  process.exit(1);
});
