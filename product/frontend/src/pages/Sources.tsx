import { useParams, updateParams } from '../app/router.js';
import { useResource } from '../api/client.js';
import { PageHeader, Select, Alert, ButtonLink, Empty, Loading, Failure } from '../components/ui.js';
import { SourceCard } from '../components/SourceCard.js';
import type { QueryRecord } from '../domain/types.js';
import { allRecommendations } from '../domain/recommendations.js';
import s from '../styles/pages.module.css';
export function Sources() {
  const id = useParams().searchParams.get('queryId'), qs = useResource<QueryRecord[]>('/queries'), r = useResource<QueryRecord>(id ? `/queries/${id}` : null);
  if (qs.loading || r.loading) return <Loading/>;
  if (qs.error || r.error) return <Failure error={(qs.error || r.error)!} onRetry={() => { qs.reload(); r.reload(); }}/>;
  const query = r.data, sources = query ? [...new Map(allRecommendations(query).flatMap(x => x.company.sources).map(source => [source.companyId + ':' + source.id, source])).values()] : [];
  return <><PageHeader title="Источники" subtitle="Происхождение сведений, область подтверждения и даты материалов."/>{qs.data?.length ? <div className={s.sourceToolbar}><Select label="Закупка" value={id ?? ''} onChange={value => updateParams({ queryId: value })} options={[{ value: '', label: 'Выберите закупку' }, ...qs.data.map(q => ({ value: q.id, label: `${q.procurement.lotId} - ${q.procurement.subject}` }))]}/></div> : null}{sources.length ? <div className={s.verticalCards}>{sources.map(source => <SourceCard key={source.companyId + ':' + source.id} source={source}/>)}</div> : <Empty title={query ? 'Материалы источников не найдены' : 'Выберите закупку'} icon="link" action={<ButtonLink secondary to={query ? `/queries/${query.id}/results` : '/queries'}>{query ? 'К результатам закупки' : 'Мои запросы'}</ButtonLink>}>{query ? 'Источники показываются из сохранённого результата. Если подбор ещё не запущен, начните его на странице закупки.' : 'Выберите запрос, чтобы посмотреть материалы, на которых основаны рекомендации.'}</Empty>}<div className={s.sectionGap}><Alert title="Дата проверки и дата публикации различаются">Получение страницы сегодня не подтверждает обновление её содержания сегодня. Период 36 месяцев служит ориентиром для проверки актуальности, а не автоматическим запретом на более старые сведения.</Alert></div></>;
}
