import { useRef, useState } from 'react';
import { useParams, updateParams } from '../app/router.js';
import { useApp } from '../app/store.js';
import { ApiError, request, useResource } from '../api/client.js';
import { PageHeader, Card, Button, ButtonLink, Alert, Empty, Loading, Failure, Select } from '../components/ui.js';
import { Icon } from '../components/Icon.js';
import { READY_STATUSES, type QueryRecord } from '../domain/types.js';
import { allRecommendations } from '../domain/recommendations.js';
import { companyLabel } from '../domain/presentation.js';
import { dateTime, fileSize, plural } from '../domain/format.js';
import { downloadBlob } from '../features/export/download.js';
import s from '../styles/pages.module.css';

const FORMATS = [
  { id: 'pdf', title: 'PDF', text: 'Отчёт для чтения и печати: закупка, кандидаты, основания и что уточнить.' },
  { id: 'csv', title: 'CSV', text: 'Таблица для Excel: кандидаты и основания построчно.' },
  { id: 'json', title: 'JSON', text: 'Полный технический снимок для аудита: исходные данные, рекомендации, основания.' },
] as const;
type Format = typeof FORMATS[number]['id'];

/** Выбор закупки, если экспорт открыт без неё: только закупки с готовым результатом. */
function QueryPicker() {
  const qs = useResource<QueryRecord[]>('/queries');
  if (qs.loading) return <Loading text="Загружаем закупки" />;
  if (qs.error) return <Failure error={qs.error} onRetry={qs.reload} />;
  const ready = (qs.data ?? []).filter(q => READY_STATUSES.includes(q.status));
  return <><PageHeader title="Экспорт" subtitle="Выберите закупку с готовым результатом." />{ready.length ? <Card className={s.padded}><Select label="Закупка" value="" onChange={v => updateParams({ queryId: v || undefined })} options={[{ value: '', label: 'Выберите закупку' }, ...ready.map(q => ({ value: q.id, label: `Лот ${q.procurement.lotId} - ${q.procurement.subject}` }))]} /></Card> : <Empty title="Нет готовых результатов" icon="report" action={<ButtonLink to="/queries">Мои запросы</ButtonLink>}>Экспорт станет доступен после завершения подбора хотя бы по одной закупке.</Empty>}</>;
}

/**
 * Экспорт результата закупки в PDF, CSV или JSON. Ключ идемпотентности сохраняется для одинаковых
 * параметров до успешного скачивания, поэтому повтор после сбоя не создаёт лишних записей экспорта.
 */
export function Export() {
  const params = useParams().searchParams, id = params.get('queryId'), app = useApp(), q = useResource<QueryRecord>(id ? `/queries/${id}` : null);
  const [format, setFormat] = useState<Format>('pdf'), [scope, setScope] = useState<'all' | 'selected'>(params.get('selection') === '1' ? 'selected' : 'all');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [last, setLast] = useState<{ name: string; size: number; at: string } | null>(null);
  const keys = useRef(new Map<string, string>()), errorRef = useRef<HTMLDivElement>(null);
  if (!id) return <QueryPicker />;
  if (q.loading) return <Loading text="Готовим экспорт" />;
  if (q.error) return <Failure error={q.error} onRetry={q.reload} />;
  if (!q.data) return null;
  const query = q.data, rows = allRecommendations(query), valid = new Set(rows.map(r => r.company.id)), selected = app.selected(query).filter(cid => valid.has(cid));
  const effective = scope === 'selected' && selected.length ? 'selected' : 'all';
  async function generate() {
    if (busy) return; setBusy(true); setError('');
    const companyIds = effective === 'selected' ? selected : [], signature = `${format}|${companyIds.join(',')}|${query.resultVersion}`;
    const key = keys.current.get(signature) ?? crypto.randomUUID(); keys.current.set(signature, key);
    try {
      const blob = await request<Blob>('/exports', { method: 'POST', body: { queryId: query.id, format, companyIds, resultVersion: query.resultVersion }, response: 'blob', idempotencyKey: key });
      const name = `podbor-lot-${query.procurement.lotId}${companyIds.length ? '-vybor' : ''}.${format}`;
      downloadBlob(blob, name); keys.current.delete(signature);
      setLast({ name, size: blob.size, at: new Date().toISOString() }); app.toast(`Файл ${name} скачан.`, 'success');
    } catch (e) {
      const err = e as ApiError; setError(err.code === 'VERSION_CONFLICT' ? 'Результат закупки изменился. Обновите страницу и скачайте файл снова.' : err.message);
      if (err.code === 'VERSION_CONFLICT') q.reload();
      requestAnimationFrame(() => errorRef.current?.focus());
    } finally { setBusy(false); }
  }
  const fmt = FORMATS.find(f => f.id === format)!;
  return <>
    <PageHeader eyebrow={`Лот ${query.procurement.lotId}`} title="Экспорт результата" subtitle={query.procurement.subject} />
    <div className={s.exportLayout}>
      <Card className={s.padded}>
        <fieldset className={s.fieldset}><legend><h2>Формат</h2></legend><div className={s.formatGrid}>{FORMATS.map(f => <label key={f.id} className={[s.formatOption, format === f.id ? s.formatActive : ''].join(' ')}><input type="radio" name="format" value={f.id} checked={format === f.id} onChange={() => setFormat(f.id)} /><span className={s.formatTitle}><Icon name="report" size={18} />{f.title}</span><span className={s.muted}>{f.text}</span></label>)}</div></fieldset>
        <fieldset className={s.fieldset}><legend><h2>Компании</h2></legend>{rows.length ? <div className={s.radioList}>
          <label className={s.radioRow}><input type="radio" name="scope" checked={effective === 'all'} onChange={() => setScope('all')} /><span>Все кандидаты: {rows.length}</span></label>
          <label className={s.radioRow}><input type="radio" name="scope" checked={effective === 'selected'} disabled={!selected.length} onChange={() => setScope('selected')} aria-describedby="scope-hint" /><span>Только выбранные: {selected.length}</span></label>
          <p id="scope-hint" className={s.muted}>{selected.length ? selected.map(cid => companyLabel(rows.find(r => r.company.id === cid)!.company)).join(', ') : 'Чтобы выгрузить часть компаний, отметьте их в списке кандидатов.'}</p>
          {format === 'json' && <p className={s.muted}>JSON всегда содержит полный снимок результата; выбор компаний записывается в файл как отметка.</p>}
        </div> : <p className={s.muted}>Кандидатов нет: файл будет содержать исходные данные закупки и состояние обработки.</p>}</fieldset>
      </Card>
      <Card className={[s.padded, s.exportSummary].join(' ')}>
        <h2>Файл</h2>
        <p><strong>{fmt.title}</strong>, {effective === 'selected' ? `${selected.length} ${plural(selected.length, ['выбранная компания', 'выбранные компании', 'выбранных компаний'])}` : `все кандидаты (${rows.length})`}</p>
        <p className={s.muted}>В файл попадут основания и ограничения: участие не означает исполненный договор, место в списке - не вероятность поставки.</p>
        {!READY_STATUSES.includes(query.status) && <Alert tone="warning" title="Подбор не завершён">Файл будет содержать только исходные данные и состояние обработки.</Alert>}
        {error && <div ref={errorRef} tabIndex={-1}><Alert tone="error" title="Файл не сформирован" action={<Button small icon="refresh" busy={busy} onClick={() => void generate()}>Повторить</Button>}>{error}</Alert></div>}
        <Button icon="download" busy={busy} wide onClick={() => void generate()}>{busy ? 'Формируем файл' : `Скачать ${fmt.title}`}</Button>
        <p className={s.muted} role="status">{last ? `Скачан ${last.name} (${fileSize(last.size)}) в ${dateTime(last.at)}. Проверьте папку загрузок.` : ''}</p>
      </Card>
    </div>
    <div className={s.belowCard}><ButtonLink variant="ghost" icon="back" to={`/queries/${query.id}/results`}>К кандидатам закупки</ButtonLink></div>
  </>;
}
