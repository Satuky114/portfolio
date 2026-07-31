/**
 * Merge class names. Filters falsy values.
 * Equivalent to clsx but zero-dependency.
 */
export function cn(...classes: (string | boolean | undefined | null)[]): string {
  return classes.filter(Boolean).join(" ");
}

/**
 * 给 public/ 下的静态资源补上 basePath 前缀。
 * 用于原生 <img>/<a>（next/link、next/image 会自动处理，无需此函数）。
 * 注意：需与 next.config.ts 的 basePath 保持一致。
 */
export function asset(path: string): string {
  return `/portfolio${path}`;
}
