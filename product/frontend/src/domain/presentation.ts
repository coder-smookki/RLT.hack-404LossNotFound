import type { Company, CompanyProfileField, Recommendation, ItemEvidence } from './types.js';
const itemStatus = (evidence: ItemEvidence) => evidence.status ?? evidence.technicalStatus ?? 'unknown';

/** Display verified present-day facts without changing a saved recommendation or its order. */
export function profileField(company: Company, name: string): CompanyProfileField | undefined {
  return company.currentProfile?.fields[name] ?? company.profileAtCalculation?.fields[name];
}
export function verifiedText(company: Company, name: string): string | null {
  for (const profile of [company.currentProfile, company.profileAtCalculation]) {
    const field = profile?.fields[name];
    if (field?.status === 'verified' && typeof field.value === 'string' && field.value.trim()) return field.value.trim();
  }
  return null;
}
export function companyName(company: Company): string {
  const name = verifiedText(company, 'name') ?? company.name?.trim();
  return name && !/^ИНН\s*\d+$/i.test(name) && name !== company.inn ? name : 'Название пока не найдено';
}
export function companyLabel(company: Company): string {
  const name = companyName(company);
  return name === 'Название пока не найдено' && company.inn ? `Контрагент с ИНН ${company.inn}` : name;
}
export interface RecommendationBasis { title: string; detail: string; caution: string; conflictCount: number; }
/** Evidence statements, never a score-to-confidence conversion. */
export function recommendationBasis(rec: Recommendation): RecommendationBasis {
  const conflictCount = rec.evidence.filter(e => itemStatus(e) === 'conflict').length;
  const history = rec.evidence.some(e => e.kind === 'history');
  const license = rec.company.sources.some(source => /лицензи/i.test(source.title));
  const catalog = rec.evidence.some(e => e.kind === 'catalog') || rec.company.sources.length > 0;
  const matched = rec.evidence.filter(e => itemStatus(e) === 'match').length;
  const title = conflictCount ? 'Есть противоречия по позициям' : history ? 'Есть опыт похожих закупок' : license ? 'Есть сведения о лицензии' : catalog ? 'Есть сведения в каталоге' : 'Сведений недостаточно';
  const detail = conflictCount
    ? `Обнаружены расхождения по ${conflictCount} позициям. Посмотрите основания перед обращением.`
    : history ? 'В истории есть участие компании в закупках с похожими товарами или услугами.'
    : license ? 'Лицензия подтверждает разрешённый вид деятельности, а не конкретные товары или наличие.'
    : catalog ? 'В источниках компании есть сведения, связанные с закупкой. Проверьте, к каким позициям они относятся.'
    : 'Не найдено достаточно предметных сведений. Возможности компании нужно уточнить.';
  const caution = matched ? 'Совпадение отдельных характеристик не подтверждает весь лот.' : 'Нужно уточнить характеристики и возможность поставить весь лот.';
  return { title, detail: rec.explanationSummary || detail, caution, conflictCount };
}

export interface BusinessContact { kind: string; value: string; sourceIds: string[]; }
export function verifiedContacts(company: Company): BusinessContact[] {
  const field = profileField(company, 'contacts');
  if (field?.status !== 'verified' || !Array.isArray(field.value)) return [];
  return field.value.flatMap(value => {
    if (typeof value === 'string' && value.trim()) return [{ kind: value.includes('@') ? 'email' : /^[+\d\s()\-]+$/.test(value) ? 'phone' : 'contact', value: value.trim(), sourceIds: field.sourceIds }];
    if (!value || typeof value !== 'object' || typeof value.value !== 'string' || !value.value.trim()) return [];
    return [{ kind: typeof value.kind === 'string' ? value.kind : 'contact', value: value.value.trim(), sourceIds: Array.isArray(value.sourceIds) ? value.sourceIds.filter((id: unknown): id is string => typeof id === 'string') : field.sourceIds }];
  });
}
export function contactHref(contact: BusinessContact): string | undefined {
  if (contact.kind === 'email' && /^[^\s<>@?]+@[^\s<>@?]+\.[^\s<>@?]+$/.test(contact.value)) return `mailto:${contact.value}`;
  if (contact.kind === 'phone' && /^[+\d\s()\-]+$/.test(contact.value)) return `tel:${contact.value.replace(/[^+\d]/g, '')}`;
  return undefined;
}

export interface EvidenceTag { label: string; tone: 'info' | 'warning' | 'neutral' | 'accent'; }
export interface ItemCoverage { total: number; withEvidence: number; history: number; catalog: number; matched: number; conflicts: number; }

/**
 * Считает основания по позициям закупки без пересчёта рейтинга: сколько позиций имеют
 * историческое или внешнее основание, сколько явных совпадений и противоречий характеристик.
 * @param rec сохранённая рекомендация; @param total число позиций закупки.
 */
export function itemCoverage(rec: Recommendation, total: number): ItemCoverage {
  const rows = rec.evidence.filter(e => e.kind !== 'none');
  return { total, withEvidence: rows.length, history: rows.filter(e => e.kind === 'history').length, catalog: rows.filter(e => e.kind === 'catalog').length, matched: rec.evidence.filter(e => itemStatus(e) === 'match').length, conflicts: rec.evidence.filter(e => itemStatus(e) === 'conflict').length };
}

/**
 * Короткие доказательные метки рекомендации. Каждая метка следует из сохранённых данных
 * (вид основания, статус сравнения характеристик, лицензия), а не из балла или места в списке.
 * Зелёный тон не используется: ни одна метка не означает надёжность компании.
 * @param compact без общей метки «Нужно уточнить характеристики» (для списков, где она объяснена один раз).
 */
export function evidenceTags(rec: Recommendation, compact = false): EvidenceTag[] {
  const tags: EvidenceTag[] = [], codes = new Set((rec.explanationCriteria ?? []).map(c => c.code));
  const conflicts = rec.evidence.filter(e => itemStatus(e) === 'conflict').length, matched = rec.evidence.filter(e => itemStatus(e) === 'match').length;
  if (rec.evidence.some(e => e.kind === 'history') || codes.has('similar_items') || codes.has('similar_procurements')) tags.push({ label: 'Есть опыт похожих закупок', tone: 'info' });
  if (rec.evidence.some(e => e.kind === 'catalog') || codes.has('external_information')) tags.push({ label: 'Есть сведения в источниках компании', tone: 'info' });
  if (codes.has('licensed_activity') || rec.company.sources.some(source => /лицензи/i.test(source.title))) tags.push({ label: 'Есть лицензия на вид деятельности', tone: 'accent' });
  if (matched) tags.push({ label: `Есть подтверждённые совпадения характеристик: ${matched}`, tone: 'info' });
  if (conflicts) tags.push({ label: `Противоречия в характеристиках: ${conflicts}`, tone: 'warning' });
  if (!matched && !compact) tags.push({ label: 'Нужно уточнить характеристики', tone: 'neutral' });
  return tags;
}
