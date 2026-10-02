import React, { useRef } from 'react';
import { allRecommendations, evidenceLabel, itemStatus } from '../domain/recommendations.js';
import { companyName, evidenceTags, itemCoverage } from '../domain/presentation.js';
import { SourceCard } from '../components/SourceCard.js';
import { useParams, updateParams } from '../app/router.js';
import { useResource } from '../api/client.js';
import { useApp } from '../app/store.js';
import { PageHeader, Card, Tabs, Button, ButtonLink, TextLink, Badge, Empty, Loading, Failure, Input } from '../components/ui.js';
import { EvidencePanel, evidenceTone } from '../components/Evidence.js';
import { ChecksCard, ExperienceCard, CompanyHistoryTable, RequisitesCard } from '../components/CompanyDossier.js';
import { CompanyRefresh } from '../components/CompanyRefresh.js';
import { compareURL } from '../components/QueryParts.js';
import { ROLE_LABEL, type Company as CompanyType, type QueryRecord, type Recommendation, type SourceEvidence } from '../domain/types.js';
import { date, plural } from '../domain/format.js';
import { assessCandidate, formatScore, winStats } from '../domain/assessment.js';
import { ScoreFactors } from '../components/Score.js';
import { Icon } from '../components/Icon.js';
import s from '../styles/pages.module.css';

/** Причины, по которым компания в списке: метки, критерии из сохранённого объяснения и покрытие позиций. */
function WhyCard({ rec, total, onItems }: { rec: Recommendation; total: number; onItems: () => void }) {
  const cover = itemCoverage(rec, total);
  return <Card className={s.padded}>
    <h2>Почему компания в списке</h2>
    <ul className={s.tags} aria-label="Основания">{evidenceTags(rec).map(tag => <li key={tag.label}><Badge tone={tag.tone} icon={tag.tone === 'warning'}>{tag.label}</Badge></li>)}</ul>
    {rec.explanationSummary && <p>{rec.explanationSummary}</p>}
    {rec.explanationCriteria?.length ? <ul className={s.criteria}>{rec.explanationCriteria.map((c, i) => <li key={`${c.code}-${i}`} className={c.status === 'conflict' ? s.criterionConflict : undefined}><strong>{c.label}</strong>{c.basis && <span className={s.muted}>{c.basis}</span>}</li>)}</ul> : null}
    <div className={s.coverRow}><div><span className={s.coverNumber}>{cover.withEvidence}<span> из {cover.total}</span></span><span className={s.muted}>{plural(cover.total, ['позиции', 'позиций', 'позиций'])} с основанием{cover.history ? ` · история ${cover.history}` : ''}{cover.catalog ? ` · источники компании ${cover.catalog}` : ''}{cover.conflicts ? ` · противоречий ${cover.conflicts}` : ''}</span></div><Button small variant="secondary" onClick={onItems}>Основания по позициям</Button></div>
    {rec.explanationNotes?.length ? <ul className={s.notes}>{rec.explanationNotes.map((n, i) => <li key={i}>{n}</li>)}</ul> : null}
  </Card>;
}

/**
 * Подробный анализ кандидата: оценка обоснованности по составляющим, сильные стороны,
 * риски и пробелы, совпадение опыта с категориями закупки. Все выводы следуют из сохранённых данных.
 */
function AnalysisCard({ rec, query }: { rec: Recommendation; query: QueryRecord }) {
  const a = assessCandidate(rec, query.procurement.items), stats = winStats(rec), history = rec.company.historySummary;
  return <Card className={s.padded} label="Анализ контрагента">
    <div className={s.sectionHead}><h2>Анализ контрагента</h2><span className={s.muted}>Место у алгоритма: № {rec.rank} {rec.company.origin === 'history' ? 'в истории закупок' : 'во внешних источниках'}</span></div>
    <div className={s.analysisGrid}>
      <div className={s.stackSm}>
        <div className={s.analysisScore}><strong>{formatScore(a.score)}</strong><span className={s.muted}>из 10</span><Badge tone={a.level.tone} icon={false}>{a.level.label}</Badge></div>
        <p className={s.muted}>Оценка обоснованности: насколько кандидат подтверждён данными. Отсутствующие сведения дают 0 баллов по своей составляющей, поэтому кандидат без данных оценивается ниже. Это не вероятность поставки и не проверка надёжности.</p>
        <ScoreFactors assessment={a} />
      </div>
      <div className={s.analysisLists}>
        {a.strengths.length > 0 && <div><h3 className={s.miniTitle}>Сильные стороны</h3><ul className={s.strengthList}>{a.strengths.map(t => <li key={t}><Icon name="check" size={16} /><span>{t}</span></li>)}</ul></div>}
        <div><h3 className={s.miniTitle}>Риски и пробелы</h3><ul className={s.riskList}>{a.gaps.map(t => <li key={t}><Icon name="warning" size={16} /><span>{t}</span></li>)}</ul></div>
        <div><h3 className={s.miniTitle}>Опыт и эта закупка</h3><ul className={s.plainList}>
          <li>{history?.lotCount || stats?.lotCount ? `Участий в закупках: ${history?.lotCount ?? stats?.lotCount}${stats ? `, побед в торгах: ${stats.winnerLotCount}` : ''}.` : 'Участий в предоставленной истории нет.'}</li>
          {a.monthsSinceLastSeen !== null && <li>Последнее участие {date(history?.lastSeen)} ({a.monthsSinceLastSeen} мес. назад).</li>}
          <li>{a.categoryMatches.length ? `Категории закупки в её истории: ${a.categoryMatches.map(c => `${c.code} (${c.lotCount})`).join(', ')}.` : 'Категории ОКПД2 этой закупки в её истории не встречаются.'}</li>
        </ul></div>
      </div>
    </div>
  </Card>;
}

const FILTERS = [{ id: 'all', label: 'Все' }, { id: 'found', label: 'С основанием' }, { id: 'conflict', label: 'Противоречия' }, { id: 'none', label: 'Без основания' }] as const;

/** Основания по позициям: фильтр и поиск по списку позиций, панель с основанием выбранной позиции. */
function ItemsTab({ company, query, rec }: { company: CompanyType; query: QueryRecord; rec?: Recommendation }) {
  const url = useParams().searchParams, filter = url.get('filter') ?? 'all', search = url.get('find') ?? '', panel = useRef<HTMLDivElement>(null);
  const items = query.procurement.items, byItem = new Map((rec?.evidence ?? []).map(e => [e.itemId, e]));
  const rows = items.map((item, index) => ({ item, index, ev: byItem.get(item.id) })).filter(({ item, ev }) => (filter === 'all' || (filter === 'found' && ev && ev.kind !== 'none') || (filter === 'conflict' && itemStatus(ev) === 'conflict') || (filter === 'none' && (!ev || ev.kind === 'none'))) && (!search || item.name.toLowerCase().includes(search.toLowerCase())));
  const current = rows.find(r => r.item.id === url.get('item')) ?? rows[0];
  const sources = new Map<string, SourceEvidence>([...company.sources, ...(company.currentProfile?.sources ?? [])].map(src => [src.id, src]));
  const count = (id: string) => id === 'all' ? items.length : items.filter(i => { const ev = byItem.get(i.id); return id === 'found' ? ev && ev.kind !== 'none' : id === 'conflict' ? itemStatus(ev) === 'conflict' : !ev || ev.kind === 'none'; }).length;
  if (!rec) return <Empty title="Компания не входит в результат этой закупки" icon="search">Основания по позициям показываются только для кандидатов выбранной закупки.</Empty>;
  return <div className={s.evidenceLayout}>
    <Card as="div" className={s.itemPicker}>
      <div className={s.itemPickerHead}>
        <div className={s.chips} role="group" aria-label="Фильтр позиций">{FILTERS.map(f => <button key={f.id} type="button" className={s.chip} aria-pressed={filter === f.id} onClick={() => updateParams({ filter: f.id === 'all' ? undefined : f.id, item: undefined })}>{f.label} <span>{count(f.id)}</span></button>)}</div>
        <Input label="Поиск позиции" hideLabel type="search" icon="search" placeholder="Найти позицию" value={search} onChange={v => updateParams({ find: v || undefined, item: undefined })} />
      </div>
      {rows.length ? <ul className={s.itemOptions} aria-label="Позиции закупки">{rows.map(({ item, index, ev }) => <li key={item.id}><button type="button" aria-current={current?.item.id === item.id ? 'true' : undefined} onClick={() => { updateParams({ item: item.id }); if (matchMedia('(max-width: 1023px)').matches) requestAnimationFrame(() => panel.current?.focus()); }}><span className={s.itemNo}>{index + 1}</span><span className={s.itemOptionText}><span>{item.name}</span><Badge tone={evidenceTone(ev)} icon={itemStatus(ev) === 'conflict'}>{evidenceLabel(ev)}</Badge></span></button></li>)}</ul> : <p className={s.emptyInline}>Позиций по этому условию нет.</p>}
    </Card>
    <Card as="div" className={s.evidenceCard}><div ref={panel} tabIndex={-1} className={s.panelFocus} aria-live="polite">{current ? <EvidencePanel item={current.item} number={current.index + 1} evidence={current.ev} source={current.ev?.sourceId ? sources.get(current.ev.sourceId) : undefined} /> : <p className={s.emptyInline}>Выберите позицию слева.</p>}</div></Card>
  </div>;
}

/**
 * Карточка компании в контексте закупки: причины попадания в список и покрытие позиций, реквизиты
 * с источниками, проверки «не проверено», опыт участия; отдельные вкладки для оснований, источников и истории.
 */
export function Company() {
  const url = useParams(), id = decodeURIComponent(url.pathname.split('/')[2] ?? ''), queryId = url.searchParams.get('queryId'), tab = url.searchParams.get('tab') ?? 'overview';
  const company = useResource<CompanyType>(`/companies/${encodeURIComponent(id)}${queryId ? `?queryId=${encodeURIComponent(queryId)}` : ''}`), qr = useResource<QueryRecord>(queryId ? `/queries/${queryId}` : null), app = useApp();
  if (company.loading || qr.loading) return <Loading text="Загружаем карточку компании" rows={4} />;
  if (company.error) return <Failure error={company.error} onRetry={company.reload} back={queryId ? { to: `/queries/${queryId}/results`, label: 'К кандидатам закупки' } : { to: '/companies', label: 'К списку компаний' }} />;
  if (qr.error) return <Failure error={qr.error} onRetry={qr.reload} />;
  if (!company.data) return null;
  const c = company.data, q = qr.data, rec = q ? allRecommendations(q).find(row => row.company.id === c.id) : undefined;
  const selected = q ? app.selected(q) : [], isSelected = selected.includes(c.id), name = companyName(c);
  const channel = c.origin === 'history' ? 'из истории закупок' : 'из внешних источников';
  const profileSources = c.currentProfile?.sources ?? [], calcSources = c.sources.filter(src => !src.id.startsWith('history:')), historySources = c.sources.filter(src => src.id.startsWith('history:'));
  const goItems = () => updateParams({ tab: 'items' });
  return <>
    <PageHeader eyebrow={q ? `Кандидат для лота ${q.procurement.lotId}${rec ? ` · № ${rec.rank} ${channel}` : ''}` : `Компания ${channel}`} title={name} subtitle={`ИНН ${c.inn ?? 'не указан'}${c.role.verified && c.role.role !== 'unknown' ? ` · ${ROLE_LABEL[c.role.role]} (подтверждено источником)` : ''}`}
      actions={q && rec ? <><Button variant={isSelected ? 'secondary' : 'primary'} icon={isSelected ? 'check' : 'compare'} onClick={() => app.toggle(q, c.id)}>{isSelected ? 'Выбрана для сравнения' : 'Выбрать для сравнения'}</Button>{isSelected && selected.length >= 2 && <ButtonLink secondary to={compareURL(q, selected)}>Сравнить ({selected.length})</ButtonLink>}</> : undefined} />
    <Tabs label="Разделы карточки" value={tab} onChange={value => updateParams({ tab: value === 'overview' ? undefined : value, item: undefined, filter: undefined, find: undefined })} items={[{ id: 'overview', label: 'Обзор' }, ...(q ? [{ id: 'items', label: 'По позициям', count: rec ? itemCoverage(rec, q.procurement.items.length).withEvidence : 0 }] : []), { id: 'sources', label: 'Источники', count: profileSources.length + calcSources.length }, { id: 'history', label: 'История участия' }]} />
    {tab === 'overview' ? <>{rec && q && <div className={s.analysisBlock}><AnalysisCard rec={rec} query={q} /></div>}<div className={s.companyGrid}>
      <div className={s.stack}>
        {rec && q ? <WhyCard rec={rec} total={q.procurement.items.length} onItems={goItems} /> : <Card className={s.padded}><h2>Связь с закупкой</h2><p className={s.muted}>Основания показываются в контексте конкретной закупки. Откройте компанию из результатов подбора.</p><div><ButtonLink small secondary to="/queries">Мои запросы</ButtonLink></div></Card>}
        <ExperienceCard history={c.historySummary} onOpen={() => updateParams({ tab: 'history' })} />
      </div>
      <div className={s.stack}>
        <RequisitesCard company={c} processedAt={q?.processedAt} />
        <ChecksCard company={c} />
        {q && <CompanyRefresh queryId={q.id} inn={c.inn} initialJob={c.sourceRefresh} onUpdated={() => { company.reload(); }} />}
      </div>
    </div></>
      : tab === 'items' && q ? <ItemsTab company={c} query={q} rec={rec} />
      : tab === 'sources' ? <div className={s.stack}>
        {profileSources.length > 0 && <section aria-labelledby="src-current"><h2 id="src-current" className={s.groupTitle}>Текущие сведения о компании</h2><Card as="div" className={s.sourceList}>{profileSources.map(src => <SourceCard key={`p-${src.id}`} source={src} />)}</Card></section>}
        {calcSources.length > 0 && <section aria-labelledby="src-calc"><h2 id="src-calc" className={s.groupTitle}>Основания на момент расчёта</h2><Card as="div" className={s.sourceList}>{calcSources.map(src => <SourceCard key={src.id} source={src} />)}</Card></section>}
        {historySources.length > 0 && <section aria-labelledby="src-hist"><h2 id="src-hist" className={s.groupTitle}>Закупки из истории в расчёте: {historySources.length}</h2><p className={s.muted}>Участие в закупках с похожими позициями. Исполнение договора не подтверждено. <TextLink onClick={() => updateParams({ tab: 'history' })}>Открыть историю участия</TextLink></p></section>}
        {!profileSources.length && !calcSources.length && !historySources.length && <Empty title="Источники не сохранены" icon="link">Подтверждающих страниц для этой компании пока нет.</Empty>}
      </div>
      : <CompanyHistoryTable company={c} />}
    <div className={s.belowCard}><TextLink icon="back" to={q ? `/queries/${q.id}/results` : '/companies'}>{q ? 'К кандидатам закупки' : 'К списку компаний'}</TextLink></div>
  </>;
}
