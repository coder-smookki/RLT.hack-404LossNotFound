import type { NeedItem, Recommendation, SourceEvidence } from './types.js';

export type FactorState = 'good' | 'partial' | 'missing' | 'risk';
export interface AssessmentFactor { id: string; label: string; points: number; max: number; state: FactorState; detail: string; }
export interface Assessment { score: number; level: { label: string; tone: 'accent' | 'info' | 'warning' | 'neutral' }; factors: AssessmentFactor[]; strengths: string[]; gaps: string[]; categoryMatches: { code: string; lotCount: number }[]; monthsSinceLastSeen: number | null; }

const round = (n: number) => Math.round(n * 10) / 10;
const clamp = (n: number, max: number) => Math.max(0, Math.min(max, n));
const itemStatus = (e: { status?: string; technicalStatus?: string }) => e.status ?? e.technicalStatus ?? 'unknown';
const plural = (n: number, f: readonly [string, string, string]) => { const v = Math.abs(n) % 100, t = v % 10; return v > 10 && v < 20 ? f[2] : t === 1 ? f[0] : t >= 2 && t <= 4 ? f[1] : f[2]; };
const months = (from: string | null | undefined, now: Date) => { if (!from) return null; const d = new Date(from.length === 10 ? from + 'T12:00:00Z' : from); return Number.isFinite(d.getTime()) ? Math.max(0, (now.getTime() - d.getTime()) / (30.44 * 24 * 3600 * 1000)) : null; };

/** Значение поля профиля компании только при подтверждённом источнике. */
function verified(rec: Recommendation, field: string): unknown {
  for (const profile of [rec.company.currentProfile, rec.company.profileAtCalculation]) { const f = profile?.fields[field]; if (f?.status === 'verified' && f.value != null && f.value !== '' && !(Array.isArray(f.value) && !f.value.length)) return f.value; }
  return null;
}

/** Сводка участий и побед из исходных данных закупок (текущий профиль, иначе снимок расчёта). */
export function winStats(rec: Recommendation) { return rec.company.currentProfile?.historyStats ?? rec.company.profileAtCalculation?.historyStats ?? null; }

/** Категории истории компании, совпадающие с кодами позиций закупки до уровня группы (первые 5 знаков, например 33.13). */
export function categoryMatches(rec: Recommendation, items: NeedItem[]): { code: string; lotCount: number }[] {
  const wanted = new Set(items.map(i => i.okpd2?.slice(0, 5)).filter((c): c is string => Boolean(c && c.length >= 5)));
  return (rec.company.historySummary?.topCategories ?? []).filter(c => wanted.has(c.code.slice(0, 5)));
}

/**
 * Оценка обоснованности кандидата по шкале 0-10: насколько предложение подтверждено сохранёнными данными.
 * Складывается из семи прозрачных составляющих; объём опыта, доля побед и давность учитываются плавно
 * (логарифмическая шкала и линейное убывание по месяцам), чтобы различать кандидатов. Отсутствие сведений даёт 0 баллов,
 * поэтому кандидат без данных получает более низкую оценку. Оценка не меняет порядок рекомендаций
 * алгоритма, не использует его балл и не является вероятностью успешной поставки или проверкой надёжности.
 * @param rec сохранённая рекомендация с профилем компании; @param items позиции закупки; @param now момент расчёта давности.
 */
export function assessCandidate(rec: Recommendation, items: NeedItem[], now = new Date()): Assessment {
  const total = Math.max(1, items.length), ev = rec.evidence;
  const withEvidence = ev.filter(e => e.kind !== 'none').length, conflicts = ev.filter(e => itemStatus(e) === 'conflict').length, matched = ev.filter(e => itemStatus(e) === 'match').length;
  const factors: AssessmentFactor[] = [], strengths: string[] = [], gaps: string[] = [];
  const add = (f: AssessmentFactor) => { f.points = round(clamp(f.points, f.max)); factors.push(f); };

  const coverage = (withEvidence - conflicts) / total;
  add({ id: 'coverage', label: 'Основания по позициям', max: 3, points: 3 * coverage, state: coverage >= .8 ? 'good' : coverage > 0 ? 'partial' : 'missing', detail: withEvidence ? `Основание есть для ${withEvidence} из ${items.length} ${plural(items.length, ['позиции', 'позиций', 'позиций'])}${conflicts ? `, у ${conflicts} - противоречия` : ''}.` : 'Ни для одной позиции основание не найдено.' });
  if (coverage >= .8) strengths.push(`Основания найдены почти по всем позициям (${withEvidence} из ${items.length}).`);
  else if (withEvidence < items.length) gaps.push(`Нет оснований для ${items.length - withEvidence} ${plural(items.length - withEvidence, ['позиции', 'позиций', 'позиций'])} - уточните, поставляет ли их компания.`);

  add({ id: 'characteristics', label: 'Совпадение характеристик', max: 1, points: matched ? Math.min(1, matched / total * 2) - conflicts * .5 : 0, state: conflicts ? 'risk' : matched ? 'good' : 'missing', detail: conflicts ? `Противоречия характеристик: ${conflicts}.` : matched ? `Явно указанные характеристики совпали по ${matched} ${plural(matched, ['позиции', 'позициям', 'позициям'])}.` : 'Подтверждённых совпадений характеристик нет - нужно уточнить.' });
  if (conflicts) gaps.push(`Характеристики противоречат закупке по ${conflicts} ${plural(conflicts, ['позиции', 'позициям', 'позициям'])}.`);
  else if (!matched) gaps.push('Характеристики товаров не подтверждены - запросите спецификации.');

  const history = rec.company.historySummary, stats = winStats(rec), lots = history?.lotCount ?? stats?.lotCount ?? 0, cats = categoryMatches(rec, items), catLots = cats.reduce((n, c) => n + c.lotCount, 0);
  const wins = stats?.winnerLotCount ?? 0, rate = stats && stats.lotCount ? wins / stats.lotCount : 0;
  const log = (n: number, full: number) => Math.min(1, Math.log10(n + 1) / Math.log10(full + 1));
  const volume = .8 * log(lots, 1000), profile = .6 * log(catLots, 50), winPoints = .6 * rate * log(wins, 20);
  add({ id: 'experience', label: 'Опыт похожих закупок', max: 2, points: volume + profile + winPoints, state: lots && catLots ? 'good' : lots ? 'partial' : 'missing', detail: lots ? `${lots} ${plural(lots, ['закупка', 'закупки', 'закупок'])} с участием${stats ? `, побед в торгах: ${wins}` : ''}${cats.length ? `; в категориях этой закупки: ${catLots}` : '; категории не совпадают с закупкой'}. Участие и победа - не исполненный договор.` : 'Истории участия в предоставленных данных нет.' });
  if (lots && catLots) strengths.push(`Участвовала в ${catLots} ${plural(catLots, ['закупке', 'закупках', 'закупках'])} тех же категорий ОКПД2.`);
  else if (!lots) gaps.push('Нет истории участия в закупках - опыт нужно проверить отдельно.');
  if (wins >= 3 && rate >= .3) strengths.push(`Побеждала в ${wins} из ${stats!.lotCount} ${plural(stats!.lotCount, ['закупки', 'закупок', 'закупок'])} с участием.`);
  else if (stats && lots >= 5 && !wins) gaps.push(`Ни одной победы в ${stats.lotCount} ${plural(stats.lotCount, ['закупке', 'закупках', 'закупках'])} с участием.`);

  const since = months(history?.lastSeen, now);
  const dated = [...rec.company.sources, ...(rec.company.currentProfile?.sources ?? [])].map((s: SourceEvidence) => months(s.publishedAt ?? s.contentDate, now)).filter((m): m is number => m !== null);
  const freshSource = dated.length ? Math.min(...dated) : null;
  const recency = since !== null ? Math.max(.1, Math.min(1, 1 - (since - 1) / 47)) : freshSource !== null && freshSource <= 36 ? .5 : 0;
  add({ id: 'recency', label: 'Актуальность сведений', max: 1, points: recency, state: recency >= .7 ? 'good' : recency > 0 ? 'partial' : 'missing', detail: since !== null ? `Последнее участие ${Math.round(since)} мес. назад.` : freshSource !== null ? `Самый свежий датированный источник - ${Math.round(freshSource)} мес. назад.` : 'Нет датированных сведений о деятельности.' });
  if (since !== null && since <= 12) strengths.push('Участвовала в закупках в последние 12 месяцев.');
  else if (since !== null && since > 36) gaps.push('Последнее участие более 36 месяцев назад - проверьте, работает ли компания.');
  else if (since === null && freshSource === null) gaps.push('Нет датированных сведений - актуальность деятельности неизвестна.');

  const req = (verified(rec, 'name') ? .5 : 0) + (verified(rec, 'ogrn') ? .5 : 0) + (verified(rec, 'region') ? .25 : 0) + (verified(rec, 'kpp') ? .25 : 0);
  add({ id: 'requisites', label: 'Реквизиты с источником', max: 1.5, points: req, state: req >= 1 ? 'good' : req > 0 ? 'partial' : 'missing', detail: `Название ${verified(rec, 'name') ? 'подтверждено' : 'не найдено'}, ОГРН ${verified(rec, 'ogrn') ? 'подтверждён' : 'не найден'}, регион ${verified(rec, 'region') ? 'подтверждён' : 'не найден'}, КПП ${verified(rec, 'kpp') ? 'подтверждён' : 'не найден'}.` });
  if (!verified(rec, 'name')) gaps.push('Название компании не подтверждено источником.');
  else if (verified(rec, 'ogrn')) strengths.push('Название и ОГРН подтверждены источником.');

  const contact = (verified(rec, 'website') ? .5 : 0) + (verified(rec, 'contacts') ? .5 : 0);
  add({ id: 'contacts', label: 'Сайт и контакты', max: 1, points: contact, state: contact >= 1 ? 'good' : contact > 0 ? 'partial' : 'missing', detail: `Сайт ${verified(rec, 'website') ? 'подтверждён' : 'не найден'}, контакты ${verified(rec, 'contacts') ? 'найдены' : 'не найдены'}.` });
  if (!contact) gaps.push('Нет подтверждённого сайта и контактов - связаться будет сложнее.');

  const checks = rec.company.dueDiligence?.checks ?? [], ok = (id: string) => checks.find(c => c.id === id)?.status === 'verified';
  const dd = (ok('registration') ? .25 : 0) + (['execution', 'finances', 'rnp'].filter(ok).length / 3) * .25;
  add({ id: 'checks', label: 'Проверки юрлица', max: .5, points: dd, state: dd >= .5 ? 'good' : dd > 0 ? 'partial' : 'missing', detail: dd ? 'Часть проверок подтверждена источниками.' : 'Юридический статус, исполнение договоров, финансы и РНП не проверялись.' });
  gaps.push(...(dd < .5 ? ['Юридический статус, исполнение договоров, финансы и РНП нужно проверить самостоятельно.'] : []));

  const score = round(factors.reduce((n, f) => n + f.points, 0));
  const level = score >= 7 ? { label: 'Хорошо обосновано', tone: 'accent' as const } : score >= 5 ? { label: 'Обосновано частично', tone: 'info' as const } : score >= 3 ? { label: 'Мало сведений', tone: 'warning' as const } : { label: 'Почти нет сведений', tone: 'neutral' as const };
  return { score, level, factors, strengths, gaps, categoryMatches: cats, monthsSinceLastSeen: since === null ? null : Math.round(since) };
}

/** Число с одним знаком после запятой: «7,4». */
export const formatScore = (n: number) => n.toLocaleString('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
