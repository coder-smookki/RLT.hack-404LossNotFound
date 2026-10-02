import { useEffect, useRef, useState } from 'react';
import { request, useResource } from '../api/client.js';
import { useApp } from '../app/store.js';
import type { SourceRefreshJob, SourceRefreshResponse } from '../domain/types.js';
import { dateTime } from '../domain/format.js';
import { Alert, Badge, Button, Card } from './ui.js';
import s from '../styles/pages.module.css';

const active = (job: SourceRefreshJob) => job.status === 'queued' || job.status === 'running';
const labels: Record<SourceRefreshJob['status'], string> = { queued: 'Ожидает проверки', running: 'Проверяется', complete: 'Сайт проверен', needs_source: 'Официальный сайт не известен', unconfirmed: 'Сведения не подтверждены', failed: 'Проверка не удалась' };

/**
 * Обновление сведений с известных официальных сайтов компаний закупки. Показывает действительное
 * состояние задания по этой компании; порядок кандидатов не пересчитывается.
 */
export function CompanyRefresh({ queryId, inn, initialJob, onUpdated }: { queryId: string; inn: string | null; initialJob?: SourceRefreshJob | null; onUpdated: () => void }) {
  const app = useApp();
  const resource = useResource<SourceRefreshResponse>(`/source-jobs?queryId=${encodeURIComponent(queryId)}`, data => data.jobs.some(active), 3000);
  const [submitting, setSubmitting] = useState(false), [error, setError] = useState<Error | null>(null);
  const wasActive = useRef(false), updated = useRef(onUpdated); updated.current = onUpdated;
  const jobs = resource.data?.jobs ?? [], busy = jobs.some(active), job = jobs.find(row => row.inn === inn) ?? initialJob;
  useEffect(() => {
    if (!resource.data) return;
    if (resource.data.jobs.some(active)) wasActive.current = true;
    else if (wasActive.current) { wasActive.current = false; updated.current(); app.toast('Проверка сведений завершена. Карточка обновлена.', 'success'); }
  }, [resource.data]);
  async function refresh() {
    setSubmitting(true); setError(null);
    try { const response = await request<SourceRefreshResponse>('/source-jobs', { method: 'POST', body: { queryId, force: true } }); if (response.jobs.some(active)) wasActive.current = true; else updated.current(); resource.reload(); }
    catch (cause) { setError(cause as Error); }
    finally { setSubmitting(false); }
  }
  return <Card className={s.padded}>
    <h2>Обновление сведений</h2>
    <p className={s.muted}>Проверяются только известные системе официальные сайты компаний этой закупки. Это не поиск по всему интернету. Порядок кандидатов не изменится.</p>
    <div className={s.refreshState} role="status">{job ? <><Badge tone={active(job) ? 'info' : job.status === 'failed' || job.status === 'unconfirmed' ? 'warning' : 'neutral'} icon={active(job) || job.status === 'failed'}>{labels[job.status]}</Badge>{job.checkedAt && <span className={s.muted}>Последняя проверка {dateTime(job.checkedAt)}</span>}{job.message && <span>{job.message}</span>}</> : <span className={s.muted}>{resource.loading ? 'Получаем состояние проверки' : 'Для этой компании проверка ещё не выполнялась.'}</span>}</div>
    {busy && <p className={s.muted}>Компаний в проверке: {jobs.filter(active).length}. Можно продолжать работу.</p>}
    {(error || resource.error || resource.refreshError) && <Alert tone="error" title="Состояние проверки не получено" action={<Button small variant="secondary" icon="refresh" onClick={() => { setError(null); resource.reload(); }}>Повторить</Button>}>{(error ?? resource.error ?? resource.refreshError)?.message}</Alert>}
    <div><Button variant="secondary" icon="refresh" busy={submitting} disabled={busy} onClick={() => void refresh()}>{busy ? 'Идёт проверка' : 'Проверить сайты сейчас'}</Button></div>
    <p className={s.muted}>Ручная проверка одного сайта - не чаще раза в 15 минут, автоматическая - раз в сутки. Дата проверки не равна дате публикации сведений.</p>
  </Card>;
}
