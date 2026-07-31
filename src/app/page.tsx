"use client";

import { useEffect } from "react";

// Dev 兜底：生产环境的根路径跳转由 postbuild 写入的 meta-refresh HTML 处理。
export default function RootPage() {
  useEffect(() => {
    window.location.replace("/portfolio/zh/");
  }, []);
  return null;
}
