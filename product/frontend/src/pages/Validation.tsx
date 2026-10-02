import React, { useRef, useState } from 'react';
import { useParams, navigate, updateParams } from '../app/router.js';
import { request, useResource } from '../api/client.js';
import { PageHeader, Card, Tabs, Button, ButtonLink, Alert, Loading, Failure, Stat, Disclosure, TextLink } from '../components/ui.js';
import { Pagination } from '../components/Pagination.js';
import { ProgressStepper } from '../components/ProgressStepper.js';
import type { ImportResult, Issue, Procurement } from '../domain/types.js';
import { encodeCSV } from '../domain/csv.js';
import { date, money, number, plural } from '../domain/format.js';
import { paginate } from '../domain/pagination.js';
import { downloadBlob } from '../features/export/download.js';
import s from '../styles/pages.module.css';

/** Место проблемы в исходных данных: файл, строка (если известна), поле и лот. */
function issuePlace(i: Issue) { return [i.file, i.row ? `строка ${i.row}` : '', i.field ? `поле ${i.field}` : '', i.lotId ? `лот ${i.lotId}` : ''].filter(Boolean).join(' · '); }

function LotItems({ lot }: { lot: Procurement }) {
  return <Disclosure summary={`Позиции: ${lot.items.length}`}><div className={s.scrollBox} tabIndex={0} role="region" aria-label={`Позиции лота ${lot.lotId}`}><table className={s.compactTable}><thead><tr><th scope="col" className={s.numCol}>№</th><th scope="col">Наименование</th><th scope="col">ОКПД2</th></tr></thead><tbody>{lot.items.map((item, i) => <tr key={item.id}><td className={s.numCol}>{i + 1}</td><td>{item.name}</td><td className={s.codeCell}>{item.okpd2 ?? 'не указан'}</td></tr>)}</tbody></table></div></Disclosure>;
}

/**
 * Результат проверки импорта: сводка, ошибки с местом и способом исправления, предпросмотр всех лотов
 * и их позиций без изменения исходных значений, запуск подбора для всего импорта.
 */
export function Validation() {
  const url = useParams(), id = url.pathname.split('/')[2] ?? '', tab = url.searchParams.get('tab') ?? 'lots';
  const r = useResource<ImportResult>(`/imports/${id}`);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), errorRef = useRef<HTMLDivElement>(null);
  if (r.loading) return <Loading text="Загружаем результат проверки" />;
  if (r.error) return <Failure error={r.error} onRetry={r.reload} back={{ to: '/search', label: 'Загрузить файлы' }} />;
  if (!r.data) return null;
  const data = r.data, errors = data.issues.filter(i => i.severity === 'error'), warnings = data.issues.filter(i => i.severity !== 'error');
  const rawPage = url.searchParams.get('page'), lotPage = paginate(data.procurements, rawPage, 20), issuePage = paginate(tab === 'errors' ? errors : warnings, rawPage, 20);
  const exportIssues = () => downloadBlob(new Blob([encodeCSV([['Файл', 'Строка', 'Поле', 'Лот', 'Уровень', 'Проблема', 'Как исправить'], ...data.issues.map(i => [i.file, i.row || '', i.field, i.lotId ?? '', i.severity === 'error' ? 'ошибка' : 'предупреждение', i.message, i.action])])], { type: 'text/csv;charset=utf-8' }), 'zamechaniya.csv');
  async function start() {
    if (busy) return; setBusy(true); setError('');
    try { await request(`/imports/${id}/start`, { method: 'POST', body: {} }); navigate(data.queryIds.length === 1 ? `/queries/${data.queryIds[0]}/results` : `/queries?importId=${id}`); }
    catch (e) { setError((e as Error).message); setBusy(false); requestAnimationFrame(() => errorRef.current?.focus()); }
  }
  const lots = data.procurements.length;
  return <>
    <PageHeader title="Проверка файлов" subtitle={data.files.join(' + ')} />
    <ProgressStepper step={2} />
    <div className={s.statsRow}><Stat value={number(lots)} label={plural(lots, ['закупка', 'закупки', 'закупок'])} /><Stat value={number(data.rows.items)} label={plural(data.rows.items, ['позиция', 'позиции', 'позиций'])} /><Stat value={number(warnings.length)} label={plural(warnings.length, ['предупреждение', 'предупреждения', 'предупреждений'])} /><Stat value={number(errors.length)} label={plural(errors.length, ['ошибка', 'ошибки', 'ошибок'])} /></div>
    <Card className={s.actionPanel}>
      {errors.length ? <Alert tone="error" title="Подбор нельзя запустить">Исправьте ошибки в исходных файлах (вкладка «Ошибки») и загрузите их снова.</Alert>
        : <div className={s.actionText}><h2>Файлы приняты</h2><p className={s.muted}>{lots} {plural(lots, ['закупка сохранена', 'закупки сохранены', 'закупок сохранено'])} в вашем аккаунте. {warnings.length ? 'Предупреждения не мешают подбору - посмотрите их перед запуском.' : 'Замечаний нет.'}</p></div>}
      <div className={s.actionButtons}>{data.queryIds.length > 0 && !errors.length && <Button icon="search" busy={busy} onClick={() => void start()}>Запустить подбор{lots > 1 ? ` для ${lots} ${plural(lots, ['закупки', 'закупок', 'закупок'])}` : ''}</Button>}<ButtonLink secondary to="/search">Загрузить другие файлы</ButtonLink></div>
    </Card>
    {error && <div ref={errorRef} tabIndex={-1} className={s.block}><Alert tone="error" title="Подбор не запущен" action={<Button small icon="refresh" onClick={() => void start()} busy={busy}>Повторить</Button>}>{error} Повтор не создаёт дубликатов: уже запущенные закупки не перезапускаются.</Alert></div>}

    <section className={s.block} aria-labelledby="validation-details">
      <h2 id="validation-details" className={s.visuallyHidden}>Подробности проверки</h2>
      <Tabs label="Подробности проверки" value={tab} onChange={v => updateParams({ tab: v === 'lots' ? undefined : v, page: undefined })} items={[{ id: 'lots', label: 'Закупки', count: lots }, { id: 'warnings', label: 'Предупреждения', count: warnings.length }, { id: 'errors', label: 'Ошибки', count: errors.length }]} />
      {tab === 'lots' ? <Card as="div">{lots ? <ul className={s.lotList}>{lotPage.items.map(p => { const notes = data.issues.filter(i => i.lotId === p.lotId); return <li key={p.lotId}>
          <div className={s.lotHead}><div><span className={s.lotId}>Лот {p.lotId}</span><strong className={s.lotSubject}>{p.subject || 'Описание не указано'}</strong><span className={s.muted}>{[p.publishDate ? `опубликовано ${date(p.publishDate)}` : '', p.price ? money(p.price) : 'цена не указана', p.source].filter(Boolean).join(' · ')}</span></div>{notes.length > 0 && <span className={s.noteCount}>{notes.length} {plural(notes.length, ['замечание', 'замечания', 'замечаний'])}</span>}</div>
          {notes.length > 0 && <ul className={s.noteList}>{notes.map((n, i) => <li key={i}>{n.message} {n.action}</li>)}</ul>}
          <LotItems lot={p} />
        </li>; })}</ul> : <p className={s.emptyInline}>Закупки не распознаны. Откройте вкладку «Ошибки».</p>}<Pagination page={lotPage.page} pages={lotPage.pages} total={lotPage.total} onChange={p => updateParams({ page: String(p) })} /></Card>
        : <Card as="div">{(tab === 'errors' ? errors : warnings).length ? <ul className={s.issueList}>{issuePage.items.map((i, index) => <li key={index}><span className={s.issuePlace}>{issuePlace(i)}</span><strong>{i.message}</strong><span>Как исправить: {i.action}</span></li>)}</ul> : <p className={s.emptyInline}>{tab === 'errors' ? 'Ошибок нет.' : 'Предупреждений нет.'}</p>}<Pagination page={issuePage.page} pages={issuePage.pages} total={issuePage.total} onChange={p => updateParams({ page: String(p) })} /></Card>}
      {data.issues.length > 0 && <div className={s.belowCard}><TextLink icon="download" onClick={exportIssues}>Скачать список замечаний (CSV)</TextLink></div>}
    </section>
  </>;
}
