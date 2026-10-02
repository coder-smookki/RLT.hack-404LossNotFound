import { useState } from 'react';
import { useParams, updateParams } from '../app/router.js';
import { request, useResource } from '../api/client.js';
import { useApp } from '../app/store.js';
import { QueryTabs, SelectionBar } from '../components/QueryParts.js';
import { PageHeader, Card, Badge, Button, ButtonLink, Select, TextLink, Check, Alert, Empty, Failure, Loading } from '../components/ui.js';
import { ROLE_LABEL, type QueryRecord, type Recommendation } from '../domain/types.js';
import { allRecommendations } from '../domain/recommendations.js';
import { companyName, companyLabel, recommendationBasis, verifiedText } from '../domain/presentation.js';
import { money, date } from '../domain/format.js';
import s from '../styles/pages.module.css';
export const roleOptions = [{ value: '', label: 'Все роли' }, ...Object.entries(ROLE_LABEL).map(([value, label]) => ({ value, label }))];
export const originOptions = [{ value: '', label: 'Все источники' }, { value: 'discovered', label: 'Внешний каталог' }, { value: 'history', label: 'История закупок' }];
export function Results() {
  const url = useParams(), id = url.pathname.split('/')[2] ?? '', role = url.searchParams.get('role') ?? '';
  const app = useApp(), q = useResource<QueryRecord>(`/queries/${id}`, query => ['queued', 'running'].includes(query.status));
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  async function start() { if (busy) return; setBusy(true); setError(''); try { await request(`/queries/${id}/start`, { method: 'POST', body: {} }); q.reload(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }
  if (q.loading) return <Loading/>;
  if (q.error) return <Failure error={q.error} onRetry={q.reload}/>;
  if (!q.data) return null;
  const query = q.data, p = query.procurement, selected = app.selected(query), external = query.externalCandidates ?? [], rows = allRecommendations(query);
  const pending = query.status === 'queued' || query.status === 'running';
  function renderRows(list: Recommendation[], externalChannel: boolean) {
    const visible = list.filter(row => !role || row.company.role.role === role);
    if (!visible.length) return <p className={s.emptyInline}>{list.length ? 'По выбранной роли компаний нет. Сбросьте фильтр.' : externalChannel ? 'В доступных внешних источниках кандидаты не найдены.' : 'В доступной истории кандидаты не найдены.'}</p>;
    return <ol className={s.recommendationList}>{visible.map(row => {
      const c = row.company, basis = recommendationBasis(row), description = verifiedText(c, 'description');
      return <li key={c.id} className={s.recommendationRow}>
        <div className={s.recommendationIdentity}><Check checked={selected.includes(c.id)} onChange={() => app.toggle(query, c.id)} label={`Выбрать ${companyLabel(c)}`}/><div><span className={s.listPosition}>№ {row.rank}</span><h3>{companyName(c)}</h3><p className={s.muted}>ИНН {c.inn ?? 'не указан'}</p>{description && <p className={s.companyDescription}>{description}</p>}{c.role.role !== 'unknown' && c.role.verified && <Badge tone="neutral" icon={false}>{ROLE_LABEL[c.role.role]}</Badge>}{externalChannel && c.newToFullHistory === true && <p className={s.cellHint}>Не встречалась в нашей истории закупок</p>}</div></div>
        <div className={s.recommendationReason}><strong>{basis.title}</strong><p>{basis.detail}</p><p className={s.cellHint}>{basis.caution}</p><TextLink icon="arrow" to={`/companies/${encodeURIComponent(c.id)}?queryId=${query.id}`}>Компания и основания</TextLink></div>
      </li>;
    })}</ol>;
  }
  return <><PageHeader title={pending ? 'Подбираем контрагентов' : query.status === 'awaiting_engine' ? 'Закупка готова к подбору' : query.status === 'failed' ? 'Подбор не завершён' : 'Контрагенты для закупки'} subtitle={`${p.subject} · лот ${p.lotId} · ${p.items.length} позиций · ${p.price ? money(p.price) : 'цена не указана'}`} actions={<ButtonLink secondary icon="download" to={`/exports?queryId=${id}`}>Скачать результаты</ButtonLink>}/><QueryTabs query={query} value="results"/>
    {error && <div className={s.sectionGap}><Alert title="Не удалось запустить подбор" tone="error">{error}</Alert></div>}
    {query.status === 'awaiting_engine' ? <Card className={`${s.padded} ${s.sectionGap}`}><h2>Данные проверены и сохранены</h2><p className={s.reasonText}>Сравним товары и услуги с историей закупок и сведениями о компаниях. Покажем, на чём основано каждое предложение.</p><Button busy={busy} icon="search" onClick={() => void start()}>Подобрать контрагентов</Button></Card>
      : pending ? <Card className={`${s.padded} ${s.sectionGap}`}><div className={s.jobState} role="status" aria-live="polite"><span className={s.jobSpinner} aria-hidden="true"/><div><h2>{query.status === 'queued' ? 'Закупка в очереди' : 'Ищем компании и проверяем основания'}</h2><p>Результат появится здесь автоматически.</p></div></div><p className={s.muted}>Можно перейти к другим закупкам. Подбор продолжится, а результат сохранится в вашей истории.</p><ButtonLink secondary to="/queries">Все закупки</ButtonLink></Card>
      : query.status === 'failed' ? <Card className={`${s.padded} ${s.sectionGap}`}><Alert title="Не удалось завершить подбор" tone="error">Исходные данные сохранены. Попробуйте запустить подбор ещё раз.</Alert><div className={s.sectionGap}><Button busy={busy} icon="refresh" onClick={() => void start()}>Повторить подбор</Button></div></Card>
      : <><div className={s.resultsFilters}><Select ariaLabel="Роль контрагента" value={role} onChange={value => updateParams({ role: value })} options={roleOptions}/><p className={s.muted}>Откройте компанию, чтобы проверить сведения по каждой позиции.</p>{role && <TextLink onClick={() => updateParams({ role: undefined })}>Сбросить фильтр</TextLink>}</div>
        {!rows.length && <Empty title="Кандидаты не найдены" icon="search" action={<ButtonLink to="/search">Загрузить другую закупку</ButtonLink>}>Доступных сведений недостаточно. Состав закупки и результат запроса сохранены.</Empty>}
        <section className={s.resultSection} aria-labelledby="history-heading"><div className={s.resultSectionHeading}><div><h2 id="history-heading">Из истории закупок</h2><p>Компании, участвовавшие в закупках с похожими товарами или услугами.</p></div><Badge tone="neutral" icon={false}>{query.recommendations.length}</Badge></div><Card>{renderRows(query.recommendations, false)}</Card></section>
        <section className={s.resultSection} aria-labelledby="external-heading"><div className={s.resultSectionHeading}><div><h2 id="external-heading">Из внешних источников</h2><p>Дополнительные кандидаты по сведениям сайтов и реестров.</p></div><Badge tone="accent" icon={false}>{external.length}</Badge></div><Card>{renderRows(external, true)}</Card></section>
        <Alert title="Что проверить перед обращением" tone="neutral">Уточните точные характеристики, наличие, количество и условия поставки. Похожая закупка или отдельная запись в каталоге не подтверждает возможность исполнить весь лот.</Alert><p className={s.resultsDisclaimer}>Подбор выполнен: {date(query.processedAt)}</p>
      </>}
    {query.warnings.length > 0 && <div className={s.sectionGap}><Alert title="Замечания к данным" tone="warning">{[...new Set(query.warnings)].join(" ")}</Alert></div>}
    <SelectionBar query={query} reload={q.reload}/>
  </>;
}
