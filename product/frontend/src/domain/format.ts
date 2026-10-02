import type { Recommendation } from './types.js';
export const number = (n: number) => new Intl.NumberFormat('ru-RU').format(n);
export const date = (v: string | null | undefined) => { if (!v) return 'Не указана'; const d = new Date(v.length === 10 ? v + 'T12:00:00Z' : v); return Number.isFinite(d.getTime()) ? new Intl.DateTimeFormat('ru-RU', { timeZone: 'UTC' }).format(d) : 'Дата требует проверки'; };
export const money = (v: string | null) => v == null || v.trim() === '' ? 'Не указана' : Number.isFinite(Number(v)) ? new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' }).format(Number(v)) : 'Цена требует проверки';
export const evidenceCount = (r: Recommendation) => r.evidence.filter(e => e.kind !== 'none').length;
export function safeURL(url: string | null | undefined): string | null { if (!url) return null; try { const u = new URL(url); return ['http:', 'https:'].includes(u.protocol) && !u.username && !u.password ? u.href : null; } catch { return null; } }
export function uid(prefix = 'id'): string { return `${prefix}-${crypto.randomUUID()}`; }
export function truncate(s: string, len = 110) { return s.length > len ? s.slice(0, len - 1) + '…' : s; }

export function plural(n: number, forms: readonly [string, string, string]): string { const value = Math.abs(n) % 100, tail = value % 10; return value > 10 && value < 20 ? forms[2] : tail === 1 ? forms[0] : tail >= 2 && tail <= 4 ? forms[1] : forms[2]; }
/** Размер файла для людей: «820 КБ», «2,4 МБ». */
export function fileSize(bytes: number): string { return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024)).toLocaleString('ru-RU')} КБ` : `${(bytes / 1024 / 1024).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} МБ`; }
/** Дата и время в часовом поясе пользователя: «02.10.2026, 15:04». */
export function dateTime(v: string | null | undefined): string { if (!v) return 'не указано'; const d = new Date(v); return Number.isFinite(d.getTime()) ? new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' }).format(d) : 'требует проверки'; }
