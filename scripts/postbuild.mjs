import { writeFileSync, existsSync } from "node:fs";

// 静态导出后，用 meta-refresh 覆盖根 index.html，
// 让 satuky114.github.io/portfolio/ 立即跳到中文站，无白屏。
const outDir = "out";
if (!existsSync(outDir)) {
  console.warn("[postbuild] out/ 不存在，跳过根 redirect");
  process.exit(0);
}

const html = `<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8" />
  <meta http-equiv="refresh" content="0; url=/portfolio/zh/" />
  <title>罗政皓 | Luo Zhenghao</title>
  <link rel="canonical" href="/portfolio/zh/" />
</head>
<body></body>
</html>`;

writeFileSync(`${outDir}/index.html`, html);
console.log("[postbuild] 根 index.html → /portfolio/zh/");
