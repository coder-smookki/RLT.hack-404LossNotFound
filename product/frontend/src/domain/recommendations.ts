import type { ItemEvidence, QueryRecord, Recommendation } from './types.js';

/** A company may occur in both channels; selection and export use its stable identity. */
export function allRecommendations(query: QueryRecord): Recommendation[] {
  const rows = [...query.recommendations, ...(query.externalCandidates ?? [])];
  return [...new Map(rows.map(row => [row.company.id, row])).values()];
}
export function itemStatus(evidence?: ItemEvidence): 'match' | 'conflict' | 'unknown' {
  return evidence?.status ?? evidence?.technicalStatus ?? 'unknown';
}
export function evidenceLabel(evidence?: ItemEvidence): string {
  const status = itemStatus(evidence);
  if (status === 'conflict') return 'Есть противоречие';
  if (status === 'match') return 'Совпадение признаков';
  return evidence?.kind === 'history' ? 'Историческое наблюдение' : evidence?.kind === 'catalog' ? 'Сведения каталога' : 'Нет подтверждения';
}
export function rankingScore(value?: number | null): string {
  return typeof value === 'number' && Number.isFinite(value) ? new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 4 }).format(value) : 'Не указан';
}
