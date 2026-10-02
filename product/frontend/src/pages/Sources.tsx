import { Link, useParams, updateParams } from '../app/router.js';
import { useResource } from '../api/client.js';
import { PageHeader, Select, Alert, ButtonLink, Empty, Loading, Failure, Card } from '../components/ui.js';
import { SourceCard } from '../components/SourceCard.js';
import { READY_STATUSES, type QueryRecord, type SourceEvidence } from '../domain/types.js';
import { allRecommendations } from '../domain/recommendations.js';
import { companyName } from '../domain/presentation.js';
import { plural } from '../domain/format.js';
import s from '../styles/pages.module.css';

/**
 * Источники сохранённого результата закупки, сгруппированные по компаниям в порядке рекомендаций:
 * что подтверждено, даты публикации и получения, ссылка. Служебные хеши не показываются.
 */
export function Sources() {
  const id = useParams().searchParams.get('queryId'), qs = useResource<QueryRecord[]>('/queries'), r = useResource<QueryRecord>(id ? `/queries/${id}` : null);
  if (r.loading || (!id && qs.loading)) return <Loading text="Загружаем источники" />;
  if (r.error) return <Failure error={r.error} onRetry={r.reload} />;
  const query = r.data, ready = (qs.data ?? []).filter(q => READY_STATUSES.includes(q.status));
  const groups = query ? allRecommendations(query).map(rec => {
    const seen = new Set<string>(), own: SourceEvidence[] = [];
    for (const src of [...rec.company.sources, ...(rec.company.currentProfile?.sources ?? [])]) if (!src.id.startsWith('history:') && !seen.has(src.id)) { seen.add(src.id); own.push(src); }
    return { rec, own, history: rec.company.sources.filter(src => src.id.startsWith('history:')).length };
  }) : [];
  const total = groups.reduce((n, g) => n + g.own.length, 0);
  const picker = <div className={s.filters}><Select label="Закупка" value={id ?? ''} disabled={qs.loading} onChange={value => updateParams({ queryId: value || undefined })} options={[{ value: '', label: qs.loading ? 'Загружаем список закупок' : 'Выберите закупку' }, ...(query && !ready.some(q => q.id === query.id) ? [{ value: query.id, label: `Лот ${query.procurement.lotId} - ${query.procurement.subject}` }] : []), ...ready.map(q => ({ value: q.id, label: `Лот ${q.procurement.lotId} - ${q.procurement.subject}` }))]} /></div>;
  return <>
    <PageHeader title="Источники" subtitle="На чём основаны сведения о кандидатах: что подтверждает источник, когда он опубликован и когда получен системой." />
    {picker}
    {qs.error && !query && <Alert tone="error" title="Список закупок не загружен">{qs.error.message}</Alert>}
    {!query ? <Empty title="Выберите закупку" icon="link" action={<ButtonLink secondary to="/queries">Мои запросы</ButtonLink>}>Источники показываются для сохранённого результата конкретной закупки.</Empty>
      : !groups.length ? <Empty title="Источников нет" icon="link" action={<ButtonLink secondary to={`/queries/${query.id}/results`}>К закупке</ButtonLink>}>{READY_STATUSES.includes(query.status) ? 'В результате этой закупки нет кандидатов.' : 'Подбор для этой закупки ещё не завершён.'}</Empty>
      : <>
        <p className={[s.muted, s.lead].join(' ')}>{total} {plural(total, ['источник', 'источника', 'источников'])} сайтов и реестров для {groups.length} {plural(groups.length, ['компании', 'компаний', 'компаний'])}. Дата получения страницы не равна дате её содержания; 36 месяцев - ориентир актуальности, а не фильтр.</p>
        <div className={s.stack}>{groups.map(({ rec, own, history }) => <section key={rec.company.id} aria-labelledby={`src-${rec.company.id}`}>
          <div className={s.sourceGroupHead}><h2 id={`src-${rec.company.id}`} className={s.groupTitle}><Link to={`/companies/${encodeURIComponent(rec.company.id)}?queryId=${query.id}&tab=sources`}>{companyName(rec.company)}</Link></h2><span className={s.muted}>ИНН {rec.company.inn ?? 'не указан'} · {rec.company.origin === 'history' ? 'история закупок' : 'внешние источники'}, № {rec.rank}</span></div>
          {own.length ? <Card as="div" className={s.sourceList}>{own.map(src => <SourceCard key={src.id} source={src} />)}</Card> : <p className={s.muted}>Сайтов и реестров с подтверждением нет.</p>}
          {history > 0 && <p className={s.muted}>Плюс {history} {plural(history, ['закупка', 'закупки', 'закупок'])} из истории участия - они в карточке компании.</p>}
        </section>)}</div>
      </>}
  </>;
}
