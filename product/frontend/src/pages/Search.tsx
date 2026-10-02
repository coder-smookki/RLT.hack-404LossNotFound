import { useRef, useState, type FormEvent, type DragEvent } from 'react';
import { PageHeader, Card, Button, TextLink, Alert, IconButton } from '../components/ui.js';
import { Icon } from '../components/Icon.js';
import { navigate } from '../app/router.js';
import { request } from '../api/client.js';
import { config } from '../app/config.js';
import { detectCSVKind, type CSVKind } from '../domain/csv.js';
import type { ImportResult } from '../domain/types.js';
import s from '../styles/pages.module.css';
const labels: Record<CSVKind, string> = { notices: 'Закупки', items: 'Позиции закупок' };
export function Search() {
  const input = useRef<HTMLInputElement>(null), idempotency = useRef(crypto.randomUUID());
  const [files, setFiles] = useState<Partial<Record<CSVKind, File>>>({});
  const [busy, setBusy] = useState(false), [reading, setReading] = useState(false), [drag, setDrag] = useState(false), [error, setError] = useState('');
  async function choose(selected: File[]) {
    if (reading || busy || !selected.length) return;
    setError(''); setReading(true);
    try {
      if (selected.length > 2) throw Error('Выберите два CSV. Таблицу поставщиков добавлять не нужно.');
      const detected: Partial<Record<CSVKind, File>> = {};
      for (const file of selected) {
        if (!file.name.toLowerCase().endsWith('.csv')) throw Error(`Файл «${file.name}» не является CSV. Выберите исходные CSV закупок.`);
        if (!file.size) throw Error(`Файл «${file.name}» пуст. Выберите файл с данными.`);
        if (file.size > config.maxCSVMB * 1024 * 1024) throw Error(`Файл «${file.name}» превышает ${config.maxCSVMB} МБ.`);
        let kind: CSVKind;
        try { kind = detectCSVKind(await file.text()); } catch (e) { throw Error(`«${file.name}»: ${(e as Error).message}`); }
        if (detected[kind]) throw Error(`Выбраны два файла одного типа: ${labels[kind].toLowerCase()}. Нужен файл закупок и файл их позиций.`);
        detected[kind] = file;
      }
      setFiles(current => ({ ...current, ...detected })); idempotency.current = crypto.randomUUID();
    } catch (e) { setError((e as Error).message); }
    finally { setReading(false); if (input.current) input.current.value = ''; }
  }
  function drop(event: DragEvent<HTMLDivElement>) { event.preventDefault(); setDrag(false); void choose(Array.from(event.dataTransfer.files)); }
  function remove(kind: CSVKind) { setFiles(current => { const next = { ...current }; delete next[kind]; return next; }); setError(''); idempotency.current = crypto.randomUUID(); }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (busy || reading) return; setError('');
    if (!files.notices || !files.items) { setError('Добавьте второй CSV. Мы сами определим, где закупки, а где их позиции.'); return; }
    setBusy(true); const body = new FormData(); body.append('notices', files.notices); body.append('items', files.items);
    try { const result = await request<ImportResult>('/imports', { method: 'POST', body, idempotencyKey: idempotency.current }); navigate(`/imports/${result.id}/validation`); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  const count = Object.keys(files).length;
  return <><PageHeader title="Новая закупка" subtitle="Выберите файлы закупок вместе. Система сама определит их содержимое."/><div className={s.searchGrid}>
    <Card className={s.searchForm}><form onSubmit={submit}><div className={s.searchBody}>
      <div className={[s.dropZone, s.unifiedDrop, drag ? s.dragging : ''].join(' ')} onDragOver={event => { event.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={drop} aria-busy={reading}>
        <Icon name="upload" size={32}/><h2>Добавьте файлы закупок</h2><p>Перетащите сюда два CSV или выберите их вместе.</p>
        <input ref={input} id="procurement-files" name="procurement-files" type="file" multiple accept=".csv,text/csv" aria-label="Файлы закупок CSV" disabled={busy || reading} onChange={event => void choose(Array.from(event.target.files ?? []))}/>
        <Button variant="secondary" busy={reading} disabled={busy} onClick={() => input.current?.click()}>{count ? 'Добавить или заменить файлы' : 'Выбрать файлы'}</Button><small>CSV, до {config.maxCSVMB} МБ каждый. Порядок выбора не важен.</small>
      </div>
      {count > 0 && <div className={s.detectedFiles} aria-live="polite">{(['notices', 'items'] as const).map(kind => files[kind] ? <div className={s.detectedFile} key={kind}><Icon name="report" size={22}/><div><strong>{files[kind]!.name}</strong><span>{labels[kind]} - определено автоматически</span></div><IconButton icon="close" disabled={busy || reading} label={`Удалить ${files[kind]!.name}`} onClick={() => remove(kind)}/></div> : <p className={s.muted} key={kind}>Осталось добавить: {labels[kind].toLowerCase()}.</p>)}</div>}
      {error && <Alert title="Проверьте файлы" tone="error">{error}</Alert>}<TextLink to="/help#csv" icon="report">Формат файлов и шаблоны</TextLink>
    </div><div className={s.formFooter}><Button type="submit" busy={busy} disabled={reading} icon="check">Проверить закупки</Button></div></form></Card>
    <aside className={s.searchAside}><section className={s.tipCard}><Icon name="link" size={24}/><h2>Один выбор - вся закупка</h2><p>Добавьте полученные файлы закупок и их позиций. Распределять их по отдельным полям не нужно.</p><p>Все товары, работы и услуги сохранятся, включая повторяющиеся строки.</p></section><p className={s.asideNote}>После проверки увидите количество закупок и позиций. Затем можно запустить подбор и открыть результат любой закупки.</p></aside>
  </div></>;
}
