// 将当前锁定版本的字体、字符映射和解码器随 Web 部署，不依赖外部 CDN。
import { cp, mkdir, rm } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const source = dirname(require.resolve("pdfjs-dist/package.json"));
const target = fileURLToPath(new URL("../public/pdfjs/", import.meta.url));
await mkdir(target, { recursive: true });
for (const folder of ["cmaps", "standard_fonts", "wasm"]) {
  await rm(join(target, folder), { recursive: true, force: true });
  await cp(join(source, folder), join(target, folder), { recursive: true });
}
