import { useState } from 'react';
import { useParams } from '../app/router.js';
import { useApp } from '../app/store.js';
import { request, useResource } from '../api/client.js';
import { PageHeader, Card, Button, ButtonLink, Alert, Empty, Loading, Failure, Check } from '../components/ui.js';
import { Icon } from '../components/Icon.js';
import type { QueryRecord } from '../domain/types.js';
import { allRecommendations } from '../domain/recommendations.js';
import { downloadBlob } from '../features/export/download.js';
import s from '../styles/pages.module.css';
const formats = ['csv', 'json', 'pdf'] as const;
export function Export() {
  const params = useParams().searchParams, id = params.get('queryId'), app = useApp(), q = useResource<QueryRecord>(id ? `/queries/${id}` : null);
  const [format, setFormat] = useState<typeof formats[number]>('pdf'), [selectedOnly, setSelectedOnly] = useState(params.get('selection') === '1'), [busy, setBusy] = useState(false), [error, setError] = useState(''), [done, setDone] = useState(false);
  async function generate() {
    if (!q.data || busy) return; setBusy(true); setError(''); setDone(false);
    try {
      const valid = new Set(allRecommendations(q.data).map(r => r.company.id));
      const companyIds = selectedOnly ? app.selected(q.data).filter(id => valid.has(id)) : [];
      if (selectedOnly && !companyIds.length) throw Error('Выберите компании в результатах или снимите ограничение подборки.');
      const blob = await request<Blob>('/exports', { method: 'POST', body: { queryId: q.data.id, format, companyIds, resultVersion: q.data.resultVersion }, response: 'blob', idempotencyKey: crypto.randomUUID() });
      downloadBlob(blob, `podbor-${q.data.procurement.lotId}.${format}`); setDone(true);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  if (q.loading) return <Loading/>;
  if (q.error) return <Failure error={q.error} onRetry={q.reload}/>;
  if (!id || !q.data) return <><PageHeader title="Экспорт данных"/><Empty title="Сначала выберите закупку" action={<ButtonLink to="/queries">Мои запросы</ButtonLink>}>Откройте сохранённый запрос, чтобы скачать его данные.</Empty></>;
  const query = q.data, rows = allRecommendations(query), ids = app.selected(query);
  return <><PageHeader title="Экспорт данных" subtitle={query.procurement.subject}/><div className={s.exportGrid}><Card className={s.padded}><h2>{rows.length ? 'Состав отчёта' : 'Данные вашей закупки'}</h2><ul className={s.exportChecklist}>{['Исходный предмет и номер лота', 'Позиции ТРУ и коды ОКПД2', 'Предупреждения и состояние обработки', ...(rows.length ? ['Исторические рекомендации и внешние кандидаты отдельно', 'Источники, объяснения и ограничения результата'] : [])].map(text => <li key={text}><Icon name="check" size={18}/>{text}</li>)}</ul>{rows.length ? <><div className={s.inlineActions}><Check checked={selectedOnly} onChange={() => { setSelectedOnly(v => !v); setDone(false); }} label={`Только выбранные компании (${ids.length})`}/><span>Только выбранные компании ({ids.length})</span></div><p className={s.muted}>{selectedOnly ? `${ids.length} компаний в подборке.` : `Все компании результата: ${rows.length}.`}</p></> : <Alert title="Рекомендации ещё не сформированы">Экспорт содержит сохранённые входные данные и состояние запроса.</Alert>}<p className={s.muted}>В отчёте сохраняются основания подбора и сведения, которые нужно уточнить у компаний.</p>{format === 'json' && <Alert title="JSON содержит полный снимок для аудита">Выбор компаний применяется к PDF и CSV. В JSON сохраняются все исходные данные, рекомендации и основания результата.</Alert>}</Card><Card className={s.padded}><h2>Формат файла</h2><div className={s.formatChoices} role="radiogroup" aria-label="Формат файла" onKeyDown={event => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault(); const index = formats.indexOf(format), next = event.key === 'Home' ? formats[0] : event.key === 'End' ? formats[2] : formats[(index + (['ArrowLeft', 'ArrowUp'].includes(event.key) ? -1 : 1) + formats.length) % formats.length]!;
    setFormat(next); setDone(false); event.currentTarget.querySelector<HTMLButtonElement>(`[data-format="${next}"]`)?.focus();
  }}>{formats.map(f => <button type="button" key={f} role="radio" data-format={f} tabIndex={format === f ? 0 : -1} aria-checked={format === f} className={format === f ? s.formatActive : ''} onClick={() => { setFormat(f); setDone(false); }}><Icon name="report"/><strong>{f.toUpperCase()}</strong><span>{f === 'csv' ? 'Для таблиц' : f === 'json' ? 'Полный снимок' : 'Отчёт для чтения'}</span></button>)}</div>{error && <Alert title="Не удалось скачать файл" tone="error">{error}</Alert>}{done && <Alert title="Файл передан браузеру" tone="success">Проверьте папку загрузок.</Alert>}<Button icon="download" busy={busy} disabled={selectedOnly && !ids.length} onClick={() => void generate()}>Скачать {format.toUpperCase()}</Button></Card></div><div className={s.pageFooter}><ButtonLink secondary icon="back" to={`/queries/${id}/results`}>Вернуться к закупке</ButtonLink></div></>;
}
