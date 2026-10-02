import React, { useState } from 'react';
import { useParams, navigate } from '../app/router.js';
import { request, useResource } from '../api/client.js';
import { ProgressStepper } from '../components/ProgressStepper.js';
import { PageHeader, Card, Button, Alert, Failure, Loading } from '../components/ui.js';
import type { QueryRecord } from '../domain/types.js';
import { money } from '../domain/format.js';
import s from '../styles/pages.module.css';

/** Проверка сохранённой потребности перед запуском подбора: все позиции без сокращений и запуск. */
export function Review() {
  const url = useParams(), queryId = url.searchParams.get('queryId'); const q = useResource<QueryRecord>(queryId ? `/queries/${queryId}` : null); const [busy, setBusy] = useState(false), [error, setError] = useState('');
  async function start() { if (!q.data || busy) return; setBusy(true); setError(''); try { await request(`/queries/${q.data.id}/start`, { method: 'POST', body: {} }); navigate(`/queries/${q.data.id}/results`); } catch (e) { setError((e as Error).message); setBusy(false); } }
  if (!queryId) return <Failure error={Error('Проверяемая закупка не найдена. Загрузите файлы заново.')} back={{ to: '/search', label: 'Загрузить файлы' }} />;
  if (q.loading) return <Loading />; if (q.error) return <Failure error={q.error} onRetry={q.reload} />; if (!q.data) return null; const p = q.data.procurement;
  return <>
    <PageHeader title="Проверьте закупку" subtitle={`${p.subject} · ${p.items.length} позиций · ${p.price ? money(p.price) : 'цена не указана'}`} />
    <ProgressStepper step={2} />
    <Card as="div"><div className={s.tableWrap}><table className={s.itemsTable}><thead><tr><th scope="col" className={s.numCol}>№</th><th scope="col">Позиция</th><th scope="col">ОКПД2</th></tr></thead><tbody>{p.items.map((it, i) => <tr key={it.id}><td className={s.numCol}>{i + 1}</td><td className={s.itemName}>{it.name}</td><td className={s.codeCell}>{it.okpd2 ?? 'не указан'}</td></tr>)}</tbody></table></div></Card>
    <p className={s.belowCard}>Количество и условия поставки не указаны - их нужно уточнить у компаний.</p>
    {error && <Alert title="Подбор не запущен" tone="error" action={<Button small icon="refresh" busy={busy} onClick={() => void start()}>Повторить</Button>}>{error}</Alert>}
    <div className={s.submitRow}><Button icon="search" busy={busy} onClick={() => void start()}>Запустить подбор</Button><Button variant="secondary" icon="back" onClick={() => navigate('/search')}>Загрузить другие файлы</Button></div>
  </>;
}
