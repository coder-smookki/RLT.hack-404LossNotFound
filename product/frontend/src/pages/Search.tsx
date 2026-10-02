import { useEffect, useRef, useState, type FormEvent, type DragEvent } from 'react';
import { PageHeader, Card, Button, Alert, TextLink, Disclosure } from '../components/ui.js';
import { Icon } from '../components/Icon.js';
import { ProgressStepper } from '../components/ProgressStepper.js';
import { navigate } from '../app/router.js';
import { ApiError, request } from '../api/client.js';
import { config } from '../app/config.js';
import { CSVFileError, inspectCSVBytes, ITEM_COLUMNS, NOTICE_COLUMNS, type CSVFileProblem, type CSVKind } from '../domain/csv.js';
import { fileSize, plural } from '../domain/format.js';
import { downloadBlob } from '../features/export/download.js';
import type { ImportResult } from '../domain/types.js';
import s from '../styles/pages.module.css';

const KIND: Record<CSVKind, { title: string; rows: readonly [string, string, string]; columns: string[] }> = {
  notices: { title: 'Файл закупок', rows: ['закупка', 'закупки', 'закупок'], columns: NOTICE_COLUMNS },
  items: { title: 'Файл позиций (ТРУ)', rows: ['позиция', 'позиции', 'позиций'], columns: ITEM_COLUMNS },
};
interface Picked { file: File; rows: number; }
interface Problem extends CSVFileProblem { file?: string; }

/** Скачивает шаблон CSV с точными заголовками схемы (UTF-8 с BOM, разделитель «;»). */
export function downloadTemplate(kind: CSVKind) { downloadBlob(new Blob(['﻿' + KIND[kind].columns.join(';') + '\r\n'], { type: 'text/csv;charset=utf-8' }), kind === 'notices' ? 'shablon-zakupki.csv' : 'shablon-pozicii.csv'); }

/** Описывает ошибку сервера при загрузке: что произошло и как исправить. */
function serverProblem(error: ApiError): Problem {
  const fix: Record<string, string> = {
    INVALID_CSV: 'Исправьте указанную строку в исходном файле, сохраните его как CSV UTF-8 и добавьте снова.',
    INVALID_ENCODING: 'Сохраните файлы как «CSV UTF-8» и добавьте их снова.',
    IMPORT_LIMIT: 'Разделите закупки на несколько загрузок: до 100 закупок и 10 000 позиций за раз.',
    FILE_TOO_LARGE: 'Разделите закупки на несколько загрузок.',
    ACCOUNT_LIMIT: 'Достигнут предел запросов аккаунта. Обратитесь к администратору сервиса.',
  };
  return { title: 'Сервер не принял файлы.', detail: error.message, fix: fix[error.code] ?? 'Проверьте файлы и повторите загрузку.' };
}

/**
 * Загрузка пары CSV в любом порядке. Тип файла определяется по колонкам, файлы показываются в двух
 * слотах с размером и числом строк. Проблемы остаются на экране, пока пользователь их не исправит.
 */
export function Search() {
  const input = useRef<HTMLInputElement>(null), idempotency = useRef(crypto.randomUUID()), problemsRef = useRef<HTMLDivElement>(null);
  const [files, setFiles] = useState<Partial<Record<CSVKind, Picked>>>({});
  const [busy, setBusy] = useState(false), [reading, setReading] = useState(false), [drag, setDrag] = useState(false);
  const [problems, setProblems] = useState<Problem[]>([]), [notice, setNotice] = useState(''), [retryable, setRetryable] = useState(false);

  useEffect(() => {
    const block = (e: globalThis.DragEvent) => { if (e.dataTransfer?.types.includes('Files')) e.preventDefault(); };
    window.addEventListener('dragover', block); window.addEventListener('drop', block);
    return () => { window.removeEventListener('dragover', block); window.removeEventListener('drop', block); };
  }, []);

  /** Проверяет выбранные файлы по содержимому и раскладывает их по слотам; ошибочный файл не занимает слот. */
  async function choose(selected: File[]) {
    if (reading || busy || !selected.length) return;
    setReading(true); setNotice(''); setRetryable(false);
    const found: Problem[] = [], detected: Partial<Record<CSVKind, Picked>> = {}, notes: string[] = [];
    try {
      if (selected.length > 2) { found.push({ title: `Выбрано ${selected.length} ${plural(selected.length, ['файл', 'файла', 'файлов'])}.`, detail: 'Нужны ровно два CSV: закупки и их позиции.', fix: 'Выберите только эти два файла. Таблицу поставщиков добавлять не нужно.' }); return; }
      for (const file of selected) {
        try {
          const info = inspectCSVBytes(new Uint8Array(await file.arrayBuffer()), config.maxCSVMB * 1024 * 1024);
          if (detected[info.kind]) { found.push({ file: file.name, title: `Оба файла - ${info.kind === 'notices' ? 'файлы закупок' : 'файлы позиций'}.`, detail: `«${detected[info.kind]!.file.name}» и «${file.name}» имеют одинаковые колонки.`, fix: `Нужен один файл закупок и один файл позиций. Добавьте ${info.kind === 'notices' ? 'файл позиций (ТРУ)' : 'файл закупок'}.` }); continue; }
          detected[info.kind] = { file, rows: info.rows };
        } catch (e) { found.push(e instanceof CSVFileError ? { file: file.name, ...e.problem } : { file: file.name, title: 'Файл не удалось прочитать.', detail: (e as Error).message, fix: 'Проверьте, что файл доступен, и выберите его снова.' }); }
      }
      setFiles(current => {
        const next = { ...current };
        for (const kind of ['notices', 'items'] as const) {
          const incoming = detected[kind], old = current[kind]; if (!incoming) continue;
          if (old && old.file.name === incoming.file.name && old.file.size === incoming.file.size && old.file.lastModified === incoming.file.lastModified) notes.push(`«${incoming.file.name}» уже добавлен.`);
          else if (old) notes.push(`${KIND[kind].title} заменён: «${old.file.name}» на «${incoming.file.name}».`);
          next[kind] = incoming;
        }
        return next;
      });
      if (Object.keys(detected).length) idempotency.current = crypto.randomUUID();
    } finally {
      setProblems(found); setNotice(notes.join(' ')); setReading(false);
      if (input.current) input.current.value = '';
      if (found.length) requestAnimationFrame(() => problemsRef.current?.focus());
    }
  }
  function drop(event: DragEvent<HTMLDivElement>) { event.preventDefault(); setDrag(false); void choose(Array.from(event.dataTransfer.files)); }
  function remove(kind: CSVKind) { setFiles(current => { const next = { ...current }; delete next[kind]; return next; }); setProblems([]); setNotice(`${KIND[kind].title} удалён.`); idempotency.current = crypto.randomUUID(); }
  async function submit(event?: FormEvent) {
    event?.preventDefault(); if (busy || reading) return; setNotice('');
    const missing = (['notices', 'items'] as const).filter(kind => !files[kind]);
    if (missing.length) { setProblems([{ title: missing.length === 2 ? 'Файлы не добавлены.' : `Не хватает файла: ${KIND[missing[0]!].title.toLowerCase()}.`, detail: 'Для проверки нужны оба CSV: закупки и позиции, связанные по lot_id.', fix: 'Перетащите файл в область выше или нажмите «Выбрать файлы». Тип определится автоматически.' }]); requestAnimationFrame(() => problemsRef.current?.focus()); return; }
    setBusy(true); setProblems([]); setRetryable(false);
    const body = new FormData(); body.append('notices', files.notices!.file); body.append('items', files.items!.file);
    try { const result = await request<ImportResult>('/imports', { method: 'POST', body, idempotencyKey: idempotency.current }); navigate(`/imports/${result.id}/validation`); }
    catch (e) {
      const error = e as ApiError, network = ['NETWORK', 'TIMEOUT'].includes(error.code) || error.status >= 500;
      setRetryable(network);
      setProblems([network ? { title: 'Файлы не отправлены.', detail: error.message, fix: 'Повторите отправку: повтор безопасен и не создаст дубликат загрузки.' } : serverProblem(error)]);
      requestAnimationFrame(() => problemsRef.current?.focus());
    } finally { setBusy(false); }
  }
  const ready = Boolean(files.notices && files.items);
  return <>
    <PageHeader title="Новая закупка" subtitle="Добавьте два CSV - файл закупок и файл их позиций. Порядок не важен: тип файла определяется по колонкам." />
    <ProgressStepper step={1} />
    <div className={s.searchLayout}>
      <Card className={s.uploadCard}>
        <form onSubmit={submit} noValidate>
          <div className={[s.dropZone, drag ? s.dragging : ''].join(' ')} onDragEnter={e => { e.preventDefault(); setDrag(true); }} onDragOver={e => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; setDrag(true); }} onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setDrag(false); }} onDrop={drop} aria-busy={reading} role="group" aria-label="Область загрузки файлов">
            <span className={s.dropIcon}><Icon name="upload" size={26} /></span>
            <p className={s.dropTitle}>{drag ? 'Отпустите файлы здесь' : 'Перетащите сюда файлы CSV'}</p>
            <p className={s.muted}>Можно оба сразу или по одному. До {config.maxCSVMB} МБ каждый, кодировка UTF-8.</p>
            <input ref={input} id="procurement-files" name="procurement-files" type="file" multiple accept=".csv,text/csv" className={s.visuallyHidden} tabIndex={-1} aria-hidden="true" disabled={busy || reading} onChange={event => void choose(Array.from(event.target.files ?? []))} />
            <Button variant="secondary" icon="plus" busy={reading} disabled={busy} onClick={() => input.current?.click()}>{reading ? 'Проверяем файлы' : 'Выбрать файлы'}</Button>
          </div>

          <ul className={s.fileSlots} aria-label="Добавленные файлы">{(['notices', 'items'] as const).map(kind => { const picked = files[kind]; return <li key={kind} className={picked ? s.fileSlot : [s.fileSlot, s.fileSlotEmpty].join(' ')}>
            <span className={s.fileSlotIcon}><Icon name={picked ? 'check' : 'report'} size={20} /></span>
            <div className={s.fileSlotMain}><span className={s.fileSlotKind}>{KIND[kind].title}</span>{picked ? <><strong>{picked.file.name}</strong><span className={s.muted}>{fileSize(picked.file.size)} · {picked.rows.toLocaleString('ru-RU')} {plural(picked.rows, KIND[kind].rows)}</span></> : <span className={s.muted}>Ещё не добавлен</span>}</div>
            {picked && <div className={s.fileSlotActions}><Button small variant="ghost" onClick={() => input.current?.click()} disabled={busy || reading}>Заменить</Button><Button small variant="ghost" onClick={() => remove(kind)} disabled={busy || reading}>Убрать</Button></div>}
          </li>; })}</ul>

          <p className={s.notice} role="status">{notice && <><Icon name="info" size={16} />{notice}</>}</p>
          {problems.length > 0 && <div ref={problemsRef} tabIndex={-1} className={s.problems} aria-label="Проблемы с файлами">{problems.map((p, i) => <Alert key={i} tone="error" title={(p.file ? `«${p.file}»: ` : '') + p.title} action={retryable && i === 0 ? <Button small icon="refresh" onClick={() => void submit()} busy={busy}>Повторить отправку</Button> : p.repairedText && p.file ? <Button small icon="check" onClick={() => void choose([new File([p.repairedText!], p.file!, { type: 'text/csv' })])}>Исправить заголовок и добавить</Button> : undefined}><p>{p.detail}</p><p><strong className={s.inlineStrong}>Как исправить:</strong> {p.fix}</p></Alert>)}</div>}

          <div className={s.submitRow}><Button type="submit" icon="arrow" busy={busy} disabled={reading}>{busy ? 'Отправляем файлы' : 'Проверить файлы'}</Button><span className={s.muted}>{ready ? 'Оба файла на месте. Подбор начнётся только после проверки.' : 'Нужны оба файла.'}</span></div>
        </form>
      </Card>
      <aside className={s.aside} aria-label="Требования к файлам">
        <h2 className={s.asideTitle}>Что нужно</h2>
        <p className={s.muted}>Два CSV, связанные по <code>lot_id</code>. Разделитель «;» или «,», кодировка UTF-8. До 100 закупок и 10 000 позиций за одну загрузку.</p>
        {(['notices', 'items'] as const).map(kind => <Disclosure key={kind} summary={`${KIND[kind].title}: ${KIND[kind].columns.length} ${plural(KIND[kind].columns.length, ['колонка', 'колонки', 'колонок'])}`}><code className={s.codeBlock}>{KIND[kind].columns.join('; ')}</code><TextLink icon="download" onClick={() => downloadTemplate(kind)}>Скачать шаблон</TextLink></Disclosure>)}
        <p className={s.muted}>Номера и ИНН сохраняются как текст: ведущие нули и повторяющиеся позиции не теряются.</p>
      </aside>
    </div>
  </>;
}
