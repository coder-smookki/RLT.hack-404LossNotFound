import { useEffect, useRef, useState } from 'react';
import { request, useResource } from '../api/client.js';
import type { SourceRefreshJob, SourceRefreshResponse } from '../domain/types.js';
import { Alert, Badge, Button, Card } from './ui.js';
import s from '../styles/pages.module.css';

const active = (job: SourceRefreshJob) => job.status === 'queued' || job.status === 'running';
const labels: Record<SourceRefreshJob['status'], string> = { queued: 'Ожидает проверки', running: 'Проверяем источники', complete: 'Проверка завершена', needs_source: 'Нужен официальный источник', unconfirmed: 'Сведения не подтверждены', failed: 'Не удалось проверить' };
const checkedDate = (value: string) => new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value));

export function CompanyRefresh({ queryId, inn, initialJob, onUpdated }: { queryId: string; inn: string | null; initialJob?: SourceRefreshJob | null; onUpdated: () => void }) {
  const resource = useResource<SourceRefreshResponse>(`/source-jobs?queryId=${encodeURIComponent(queryId)}`, data => data.jobs.some(active));
  const [submitting, setSubmitting] = useState(false), [error, setError] = useState<Error | null>(null), [notice, setNotice] = useState('');
  const wasActive = useRef(false), updated = useRef(onUpdated); updated.current = onUpdated;
  const jobs = resource.data?.jobs ?? [], busy = jobs.some(active), job = jobs.find(row => row.inn === inn) ?? initialJob;
  useEffect(() => {
    if (!resource.data) return;
    if (resource.data.jobs.some(active)) wasActive.current = true;
    else if (wasActive.current) { wasActive.current = false; updated.current(); }
  }, [resource.data]);
  async function refresh() {
    setSubmitting(true); setError(null); setNotice('');
    try {
      const response = await request<SourceRefreshResponse>('/source-jobs', { method: 'POST', body: { queryId, force: true } });
      setNotice(response.message ?? 'Проверка сведений запущена.');
      if (response.jobs.some(active)) wasActive.current = true;
      else updated.current();
      resource.reload();
    } catch (cause) { setError(cause as Error); }
    finally { setSubmitting(false); }
  }
  return <Card className={s.padded}><h2>Проверка сведений компаний</h2><p className={s.muted}>Проверяем известные официальные источники компаний этой закупки и сохраняем подтверждённые сведения. Если источник не найден, отметим это в карточке. Порядок рекомендаций останется прежним.</p>{job ? <div className={s.refreshStatus} role="status"><Badge tone={active(job) ? 'info' : job.status === 'failed' || job.status === 'unconfirmed' ? 'warning' : 'neutral'}>{labels[job.status]}</Badge>{job.checkedAt && <span>{job.status === 'needs_source' || job.checkKind === 'catalog_lookup' ? 'Сверка доступных источников' : 'Последняя проверка источника'}: {checkedDate(job.checkedAt)}</span>}{job.message && <p>{job.message}</p>}</div> : <p className={s.muted}>{resource.loading ? 'Получаем статус проверки.' : 'Для этой компании проверка источников ещё не выполнена.'}</p>}{busy && <p className={s.muted} role="status">Осталось проверить компаний: {jobs.filter(active).length}. Можно продолжать работу - результаты сохранятся.</p>}{(error || resource.error) && <Alert title="Проверку не удалось обновить">{(error ?? resource.error)?.message}<Button variant="secondary" onClick={resource.reload}>Повторить получение статуса</Button></Alert>}{notice && !busy && <p className={s.muted} role="status">{notice}</p>}<Button variant="secondary" icon="refresh" disabled={busy || submitting} onClick={() => void refresh()}>{submitting || busy ? 'Проверяем сведения' : 'Обновить сведения'}</Button><p className={s.refreshFootnote}>Повторная проверка каждого источника доступна не чаще одного раза в 15 минут. Дата проверки не является датой публикации сведений.</p></Card>;
}
