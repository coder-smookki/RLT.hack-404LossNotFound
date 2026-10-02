import { useState } from 'react';
import { request, useResource } from '../api/client.js';
import { Link, useParams, updateParams } from '../app/router.js';
import { useApp } from '../app/store.js';
import { PageHeader, Card, Alert, Input, Select, Tabs, Badge, TextLink, ButtonLink, Button, Empty, Loading, Failure } from '../components/ui.js';
import { Pagination } from '../components/Pagination.js';
import { READY_STATUSES, STATUS_LABEL, STATUS_TONE, type QueryRecord } from '../domain/types.js';
import { date, plural } from '../domain/format.js';
import { paginate } from '../domain/pagination.js';
import s from '../styles/pages.module.css';

/** Сводка обработки набора закупок: готовые, в работе, в очереди, не запущенные и незавершённые. */
export function batchProgress(rows: QueryRecord[]) {
  const count = (...statuses: string[]) => rows.filter(q => statuses.includes(q.status)).length;
  const done = count(...READY_STATUSES), failed = count('failed');
  return { total: rows.length, done, failed, running: count('running'), queued: count('queued'), waiting: count('awaiting_engine'), finished: done + failed };
}
const isActive = (q: QueryRecord) => q.status === 'queued' || q.status === 'running';

/**
 * История запросов с ходом пакетного подбора. Готовые лоты открываются сразу, не дожидаясь остальных;
 * незавершённые можно перезапустить (сервер повторяет только задания в состоянии «не завершён»).
 */
export function Queries() {
  const url = useParams(), p = url.searchParams, app = useApp();
  const tab = p.get('tab') ?? 'all', search = p.get('q') ?? '', state = p.get('status') ?? '', importId = p.get('importId');
  const r = useResource<QueryRecord[]>('/queries', data => data.some(isActive), 4000);
  const [retrying, setRetrying] = useState<string | null>(null);
  if (r.loading) return <Loading text="Загружаем ваши запросы" />;
  if (r.error) return <Failure error={r.error} onRetry={r.reload} back={{ to: '/', label: 'На главную' }} />;
  const all = r.data ?? [];
  const batch = importId ? all.filter(q => q.importId === importId) : all.filter(isActive).length ? all.filter(q => q.importId && q.importId === all.find(isActive)?.importId) : [];
  const progress = batch.length ? batchProgress(batch) : null;
  const rows = all.filter(q => (!importId || q.importId === importId) && (tab !== 'saved' || q.saved) && (tab !== 'exported' || q.exported) && (!search || `${q.procurement.subject} ${q.procurement.lotId}`.toLowerCase().includes(search.trim().toLowerCase())) && (!state || q.status === state || (state === 'ready' && READY_STATUSES.includes(q.status))));
  const page = paginate(rows, p.get('page'), 25);
  async function retry(q: QueryRecord) {
    if (retrying) return; setRetrying(q.id);
    try { await request(`/queries/${q.id}/start`, { method: 'POST', body: {} }); app.toast(`Лот ${q.procurement.lotId} снова в очереди.`, 'success'); r.reload(); }
    catch (e) { app.toast(`Не удалось перезапустить лот ${q.procurement.lotId}: ${(e as Error).message}`, 'error'); }
    finally { setRetrying(null); }
  }
  const filtered = Boolean(search || state || tab !== 'all' || importId);
  return <>
    <PageHeader title="Мои запросы" subtitle="Каждая закупка из загруженных файлов - отдельный запрос со своим результатом." actions={<ButtonLink to="/search" icon="upload">Новая закупка</ButtonLink>} />
    {r.refreshError && <div className={s.block}><Alert tone="warning" title="Статус не обновляется" action={<Button small variant="secondary" icon="refresh" onClick={r.reload}>Обновить сейчас</Button>}>{r.refreshError.message} Показаны последние полученные данные.</Alert></div>}
    {progress && <Card className={[s.padded, s.block].join(' ')}>
      <div className={s.sectionHead}><div><h2>{progress.finished === progress.total ? 'Подбор завершён' : 'Идёт подбор'}</h2><p className={s.muted}>{progress.finished === progress.total ? 'Все закупки этой загрузки обработаны.' : 'Готовые закупки уже можно открыть. Страница обновляется сама.'}</p></div>{!importId && <TextLink onClick={() => updateParams({ importId: batch[0]?.importId ?? undefined, page: undefined })}>Показать только эту загрузку</TextLink>}</div>
      <progress className={s.progress} value={progress.finished} max={progress.total} aria-label={`Обработано ${progress.finished} из ${progress.total}`} />
      <ul className={s.progressCounts} aria-label="Состояние закупок"><li><strong>{progress.done}</strong> готово</li><li><strong>{progress.running}</strong> в работе</li><li><strong>{progress.queued}</strong> в очереди</li>{progress.waiting > 0 && <li><strong>{progress.waiting}</strong> не запущено</li>}{progress.failed > 0 && <li className={s.countWarn}><strong>{progress.failed}</strong> не завершено</li>}</ul>
      {progress.waiting > 0 && batch[0]?.importId && <p className={s.muted}>Часть закупок ещё не запущена. <Link to={`/imports/${batch[0].importId}/validation`}>Открыть проверку и запустить подбор</Link></p>}
    </Card>}
    <Tabs label="Набор запросов" value={tab} onChange={v => updateParams({ tab: v === 'all' ? undefined : v, page: undefined })} items={[{ id: 'all', label: 'Все' }, { id: 'saved', label: 'Сохранённые' }, { id: 'exported', label: 'Экспортированные' }]} />
    <div className={s.filters}>
      <Input label="Поиск по названию или номеру лота" hideLabel value={search} onChange={v => updateParams({ q: v || undefined, page: undefined })} icon="search" placeholder="Название или номер лота" type="search" />
      <Select ariaLabel="Состояние" value={state} onChange={v => updateParams({ status: v || undefined, page: undefined })} options={[{ value: '', label: 'Все состояния' }, { value: 'ready', label: 'Готовые' }, { value: 'running', label: STATUS_LABEL.running }, { value: 'queued', label: STATUS_LABEL.queued }, { value: 'awaiting_engine', label: STATUS_LABEL.awaiting_engine }, { value: 'failed', label: STATUS_LABEL.failed }]} />
      {importId && <TextLink icon="close" onClick={() => updateParams({ importId: undefined, page: undefined })}>Показать все загрузки</TextLink>}
    </div>
    {rows.length ? <Card as="div">
      <div className={s.tableWrap}><table className={s.queryTable}><caption className={s.visuallyHidden}>Запросы: {rows.length}</caption><thead><tr><th scope="col">Закупка</th><th scope="col" className={s.numCol}>Позиции</th><th scope="col">Загружено</th><th scope="col">Состояние</th><th scope="col"><span className={s.visuallyHidden}>Действие</span></th></tr></thead>
        <tbody>{page.items.map(q => { const ready = READY_STATUSES.includes(q.status); return <tr key={q.id}>
          <td data-label="Закупка"><Link to={`/queries/${q.id}/results`} className={s.rowTitle}>{q.procurement.subject || 'Закупка без описания'}</Link><span className={s.muted}>Лот {q.procurement.lotId}{q.procurement.source ? ` · ${q.procurement.source}` : ''}{q.saved ? ' · сохранён' : ''}</span></td>
          <td data-label="Позиции" className={s.numCol}>{q.procurement.items.length}</td>
          <td data-label="Загружено">{date(q.createdAt)}</td>
          <td data-label="Состояние"><Badge tone={STATUS_TONE[q.status]}>{STATUS_LABEL[q.status]}</Badge>{q.status === 'failed' && q.job?.message && <span className={s.cellNote}>{q.job.message}</span>}</td>
          <td className={s.actionCell}>{q.status === 'failed' ? <Button small variant="secondary" icon="refresh" busy={retrying === q.id} disabled={Boolean(retrying)} onClick={() => void retry(q)}>Повторить</Button> : <ButtonLink small variant={ready ? 'secondary' : 'ghost'} to={`/queries/${q.id}/results`}>{ready ? 'Результат' : q.status === 'awaiting_engine' ? 'Запустить' : 'Ход подбора'}</ButtonLink>}</td>
        </tr>; })}</tbody></table></div>
      <Pagination page={page.page} pages={page.pages} total={page.total} size={25} onChange={n => updateParams({ page: String(n) })} />
    </Card> : <Empty title={filtered ? 'Ничего не найдено' : 'Запросов пока нет'} icon={filtered ? 'filter' : 'clock'} action={filtered ? <Button variant="secondary" onClick={() => updateParams({ tab: undefined, q: undefined, status: undefined, importId: undefined, page: undefined })}>Сбросить фильтры</Button> : <ButtonLink to="/search" icon="upload">Загрузить файлы</ButtonLink>}>{filtered ? 'Измените условия поиска или сбросьте фильтры.' : 'Загрузите два CSV - закупки и позиции, - чтобы получить первый результат.'}</Empty>}
    {rows.length > 0 && <p className={s.belowCard}>{rows.length} {plural(rows.length, ['запрос', 'запроса', 'запросов'])}{filtered ? ' по выбранным условиям' : ''}</p>}
  </>;
}
