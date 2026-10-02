import { useRef, useState } from 'react';
import { Link, useParams, updateParams } from '../app/router.js';
import { request, useResource } from '../api/client.js';
import { useApp } from '../app/store.js';
import { QueryTabs, SelectionBar, LotFacts, SaveToggle } from '../components/QueryParts.js';
import { PageHeader, Card, Badge, Button, ButtonLink, Select, TextLink, Check, Alert, Empty, Failure, Loading, Disclosure } from '../components/ui.js';
import { ROLE_LABEL, type QueryRecord, type Recommendation } from '../domain/types.js';
import { allRecommendations } from '../domain/recommendations.js';
import { companyName, companyLabel, evidenceTags, itemCoverage } from '../domain/presentation.js';
import { dateTime, plural } from '../domain/format.js';
import { assessCandidate, type Assessment } from '../domain/assessment.js';
import { ScoreBadge } from '../components/Score.js';
import s from '../styles/pages.module.css';

export const roleOptions = [{ value: '', label: 'Все роли' }, ...Object.entries(ROLE_LABEL).map(([value, label]) => ({ value, label }))];
export const originOptions = [{ value: '', label: 'Оба канала' }, { value: 'history', label: 'История закупок' }, { value: 'discovered', label: 'Внешние источники' }];

/** Строка кандидата: место в своём канале, название, ИНН, доказательные метки и покрытие позиций. Порядок не меняется. */
function CandidateRow({ row, query, external, assessment }: { row: Recommendation; query: QueryRecord; external: boolean; assessment: Assessment }) {
  const app = useApp(), c = row.company, cover = itemCoverage(row, query.procurement.items.length), checked = app.selected(query).includes(c.id);
  const href = `/companies/${encodeURIComponent(c.id)}?queryId=${query.id}`;
  return <li className={[s.candidate, checked ? s.candidateSelected : ''].join(' ')}>
    <div className={s.candidateCheck}><Check checked={checked} onChange={() => app.toggle(query, c.id)} label={`Выбрать для сравнения: ${companyLabel(c)}`} /></div>
    <span className={s.rank} title="Место в порядке алгоритма подбора" aria-label={`Место ${row.rank} у алгоритма`}>{row.rank}</span>
    <div className={s.candidateMain}>
      <Link to={href} className={s.candidateName}>{companyName(c)}</Link>
      <span className={s.muted}>ИНН {c.inn ?? 'не указан'}{c.role.verified && c.role.role !== 'unknown' ? ` · ${ROLE_LABEL[c.role.role]} (подтверждено)` : ''}{external && c.newToFullHistory ? ' · нет в нашей истории закупок' : ''}</span>
      <ul className={s.tags} aria-label="Основания">{evidenceTags(row, true).map(tag => <li key={tag.label}><Badge tone={tag.tone} icon={tag.tone === 'warning'}>{tag.label}</Badge></li>)}</ul>
    </div>
    <div className={s.candidateCover}>
      <ScoreBadge assessment={assessment} />
      <span className={s.muted}>Основания: {cover.withEvidence} из {cover.total} {plural(cover.total, ['позиции', 'позиций', 'позиций'])}</span>
      <TextLink to={href} icon="chevronRight" iconAfter>Подробный анализ</TextLink>
    </div>
  </li>;
}

/**
 * Результат подбора по закупке: суть лота и действия сверху, затем два раздельных канала
 * (история закупок и внешние источники) в сохранённом порядке, выбор для сравнения и экспорт.
 */
export function Results() {
  const url = useParams(), id = url.pathname.split('/')[2] ?? '', role = url.searchParams.get('role') ?? '', sort = url.searchParams.get('sort') === 'score' ? 'score' : 'rank';
  const q = useResource<QueryRecord>(`/queries/${id}`, query => ['queued', 'running'].includes(query.status), 3000);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), errorRef = useRef<HTMLDivElement>(null);
  async function start() { if (busy) return; setBusy(true); setError(''); try { await request(`/queries/${id}/start`, { method: 'POST', body: {} }); q.reload(); } catch (e) { setError((e as Error).message); requestAnimationFrame(() => errorRef.current?.focus()); } finally { setBusy(false); } }
  if (q.loading) return <Loading text="Загружаем результат подбора" rows={4} />;
  if (q.error) return <Failure error={q.error} onRetry={q.reload} />;
  if (!q.data) return null;
  const query = q.data, p = query.procurement, external = query.externalCandidates ?? [], all = allRecommendations(query);
  const pending = query.status === 'queued' || query.status === 'running', ready = !pending && query.status !== 'awaiting_engine' && query.status !== 'failed';
  const showRoles = all.some(r => r.company.role.verified && r.company.role.role !== 'unknown');
  const scores = new Map(all.map(r => [r.company.id, assessCandidate(r, p.items)]));
  const section = (list: Recommendation[], externalChannel: boolean, idName: string, title: string, note: string) => {
    const filtered = list.filter(row => !role || row.company.role.role === role);
    const visible = sort === 'score' ? [...filtered].sort((a, b) => scores.get(b.company.id)!.score - scores.get(a.company.id)!.score || a.rank - b.rank) : filtered;
    return <section className={s.block} aria-labelledby={idName}>
      <div className={s.sectionHead}><div><h2 id={idName}>{title} <span className={s.headCount}>{list.length}</span></h2><p className={s.muted}>{note}</p></div></div>
      <Card as="div">{visible.length ? <ol className={s.candidateList}>{visible.map(row => <CandidateRow key={row.company.id} row={row} query={query} external={externalChannel} assessment={scores.get(row.company.id)!} />)}</ol> : <p className={s.emptyInline}>{list.length ? 'С выбранной ролью компаний нет.' : externalChannel ? 'Во внешних источниках подходящих компаний не найдено.' : 'В истории закупок подходящих компаний не найдено.'}</p>}</Card>
    </section>;
  };
  return <>
    <PageHeader eyebrow={`Лот ${p.lotId} · ${p.items.length} ${plural(p.items.length, ['позиция', 'позиции', 'позиций'])}`} title={p.subject || 'Закупка без описания'} actions={<><SaveToggle query={query} reload={q.reload} />{ready && <ButtonLink secondary icon="download" to={`/exports?queryId=${id}`}>Экспорт</ButtonLink>}</>} />
    <LotFacts query={query} />
    <QueryTabs query={query} value="results" />
    {q.refreshError && <div className={s.block}><Alert tone="warning" title="Статус не обновляется" action={<Button small variant="secondary" icon="refresh" onClick={q.reload}>Обновить</Button>}>{q.refreshError.message}</Alert></div>}
    {error && <div ref={errorRef} tabIndex={-1} className={s.block}><Alert tone="error" title="Подбор не запущен" action={<Button small icon="refresh" busy={busy} onClick={() => void start()}>Повторить</Button>}>{error}</Alert></div>}

    {query.status === 'awaiting_engine' ? <Card className={s.statePanel}><h2>Подбор ещё не запускался</h2><p className={s.muted}>Закупка и {p.items.length} {plural(p.items.length, ['позиция', 'позиции', 'позиций'])} сохранены. Подбор сравнит их с историей закупок и сведениями компаний и покажет основания по позициям.</p><div><Button icon="search" busy={busy} onClick={() => void start()}>Запустить подбор</Button></div></Card>
      : pending ? <Card className={s.statePanel}><div className={s.jobState} role="status"><span className={s.jobSpinner} aria-hidden="true" /><div><h2>{query.status === 'queued' ? 'Закупка в очереди' : 'Подбираем кандидатов'}</h2><p className={s.muted}>{query.job?.message || 'Результат появится здесь автоматически.'}</p></div></div><p className={s.muted}>Страницу можно закрыть - результат сохранится в «Моих запросах».</p><div><ButtonLink secondary to={query.importId ? `/queries?importId=${query.importId}` : '/queries'}>К ходу подбора</ButtonLink></div></Card>
      : query.status === 'failed' ? <Card className={s.statePanel}><Alert tone="error" title="Подбор не завершён">{query.job?.message || 'Обработка прервалась.'} Исходные данные сохранены.</Alert><div><Button icon="refresh" busy={busy} onClick={() => void start()}>Запустить ещё раз</Button></div></Card>
      : <>
        {query.warnings.length > 0 && <div className={s.block}><Alert tone="neutral" title="Замечания к исходным данным">{[...new Set(query.warnings)].join(' ')}</Alert></div>}
        <div className={s.resultsIntro}><p className={s.muted}>Номер - место в порядке алгоритма подбора. Оценка из 10 показывает, насколько кандидат подтверждён данными: наведите на неё, чтобы увидеть составляющие и пробелы. Это не вероятность поставки.</p><div className={s.sortRow}><Select ariaLabel="Порядок кандидатов" value={sort} onChange={value => updateParams({ sort: value === 'score' ? 'score' : undefined })} options={[{ value: 'rank', label: 'Порядок алгоритма' }, { value: 'score', label: 'По оценке обоснованности' }]} />{showRoles && <Select ariaLabel="Роль компании" value={role} onChange={value => updateParams({ role: value || undefined })} options={roleOptions} />}</div></div>
        {!all.length ? <Empty title="Кандидаты не найдены" icon="search" action={<ButtonLink secondary to={`/queries/${id}/items`}>Посмотреть состав закупки</ButtonLink>}>В доступной истории и источниках нет компаний с основаниями для этой закупки. Это не значит, что поставщиков нет.</Empty> : <>
          {section(query.recommendations, false, 'history-heading', 'Из истории закупок', 'Компании, участвовавшие в закупках с похожими товарами или услугами. Участие не означает исполненный договор.')}
          {section(external, true, 'external-heading', 'Из внешних источников', 'Компании из проверенных сайтов и реестров, известных системе. Это не поиск по всему интернету.')}
        </>}
        <Disclosure summary="Что проверить перед обращением к компании"><ul className={s.plainList}><li>Точные характеристики и соответствие каждой позиции.</li><li>Наличие, количество, сроки и условия поставки.</li><li>Юридический статус, исполнение договоров, финансы и реестр недобросовестных поставщиков - система их не проверяла.</li></ul></Disclosure>
        <p className={s.belowCard}>Подбор выполнен {dateTime(query.processedAt)}. Порядок кандидатов зафиксирован и не меняется при обновлении сведений о компаниях.</p>
      </>}
    {ready && <SelectionBar query={query} />}
  </>;
}
