/** Возвращает ограниченную страницу списка; неизвестный или устаревший номер безопасно приводится к границам. */
export function paginate<T>(items: readonly T[], rawPage: string | number | null, pageSize = 20): { items: T[]; page: number; pages: number; total: number } {
  const parsed = Number(rawPage ?? 1); const size = Math.max(1, Math.floor(pageSize)); const pages = Math.max(1, Math.ceil(items.length / size)); const page = Math.max(1, Math.min(pages, Number.isFinite(parsed) ? Math.floor(parsed) : 1)); return { items: items.slice((page - 1) * size, page * size), page, pages, total: items.length };
}
