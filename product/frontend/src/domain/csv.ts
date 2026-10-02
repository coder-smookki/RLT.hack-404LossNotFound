import type { ImportResult, Issue, NeedItem, Procurement } from './types.js';
export const NOTICE_COLUMNS = ['publish_date', 'procedure_id', 'lot_id', 'start_price', 'reqnum', 'procedure_name', 'subject', 'is_smp', 'customer_inn', 'customer_kpp', 'is_eshop_or_aisgz'];
export const ITEM_COLUMNS = ['lot_id', 'product_name', 'okpd2_code'];
export interface CSVRow { cells: string[]; line: number; }
export class CSVParseError extends Error { readonly line: number; constructor(message: string, line: number) { super(message); this.name = 'CSVParseError'; this.line = line; } }
/** Разбирает CSV конечным автоматом: кавычки, BOM, CRLF, разделитель и многострочные поля. */
export function parseCSV(input: string, delimiter = ';'): CSVRow[] {
  const text = input.replace(/^\uFEFF/, ''); const rows: CSVRow[] = []; let cells: string[] = [], cell = '', quoted = false, closed = false, line = 1, rowLine = 1;
  const push = () => { cells.push(cell); if (cells.some(c => c.length > 0)) rows.push({ cells, line: rowLine }); cells = []; cell = ''; closed = false; };
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]!;
    if (quoted) { if (ch === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else { quoted = false; closed = true; } } else { cell += ch; if (ch === '\n') line++; } continue; }
    if (ch === '"') { if (cell !== '' || closed) throw new CSVParseError('Кавычка внутри неэкранированного поля.', line); quoted = true; continue; }
    if (ch === delimiter) { cells.push(cell); cell = ''; closed = false; continue; }
    if (ch === '\n' || ch === '\r') { if (ch === '\r' && text[i + 1] === '\n') i++; push(); line++; rowLine = line; continue; }
    if (closed) { if (ch === ' ' || ch === '\t') continue; throw new CSVParseError('После закрывающей кавычки ожидается разделитель или конец строки.', line); }
    cell += ch;
  }
  if (quoted) throw new CSVParseError('Не закрыта кавычка в CSV.', rowLine);
  if (cell.length || cells.length || closed) push(); return rows;
}
function validDate(value: string) { if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false; const d = new Date(value + 'T12:00:00Z'); return Number.isFinite(d.getTime()) && d.toISOString().slice(0, 10) === value; }
function parseTable(text: string, file: string, columns: string[], issues: Issue[]): { value: Record<string, string>; line: number }[] {
  let rows: CSVRow[];
  try { rows = parseCSV(text); } catch (error) { const e = error as CSVParseError; issues.push({ severity: 'error', code: 'CSV_SYNTAX', file, row: e.line, field: 'CSV', message: e.message, action: 'Проверьте кавычки и разделитель «;».' }); return []; }
  const header = rows.shift(); if (!header) { issues.push({ severity: 'error', code: 'EMPTY_FILE', file, row: 1, field: 'CSV', message: 'Файл пуст.', action: 'Загрузите файл с заголовками и строками.' }); return []; }
  const names = header.cells.map(c => c.trim()); const missing = columns.filter(c => !names.includes(c));
  const unknown = names.filter(c => !columns.includes(c)); const duplicate = names.filter((c, i) => names.indexOf(c) !== i);
  if (missing.length || unknown.length || duplicate.length) { issues.push({ severity: 'error', code: 'SCHEMA', file, row: 1, field: 'Заголовки', message: [missing.length ? 'Нет колонок: ' + missing.join(', ') : '', unknown.length ? 'Неизвестные колонки: ' + unknown.join(', ') : '', duplicate.length ? 'Повтор колонки: ' + duplicate.join(', ') : ''].filter(Boolean).join('. '), action: 'Используйте точную схему из справки. Колонки не переименовываются автоматически.' }); return []; }
  return rows.flatMap(row => {
    if (row.cells.length !== names.length) { issues.push({ severity: 'error', code: 'ROW_WIDTH', file, row: row.line, field: 'CSV', message: `Полей ${row.cells.length}, ожидается ${names.length}.`, action: 'Проверьте разделитель и кавычки.' }); return []; }
    return [{ value: Object.fromEntries(names.map((name, i) => [name, row.cells[i]!])), line: row.line }];
  });
}
/** Проверяет две таблицы без удаления исходных строк; идентификаторы остаются строками. */
export function validateImport(noticesText: string, itemsText: string, files = ['zakupki.csv', 'tru.csv']): ImportResult {
  const issues: Issue[] = []; const notices = parseTable(noticesText, files[0]!, NOTICE_COLUMNS, issues), items = parseTable(itemsText, files[1]!, ITEM_COLUMNS, issues);
  const lots = new Map<string, Procurement>(); const itemCounts = new Map<string, number>();
  for (const row of notices) {
const n = row.value, id = n.lot_id ?? '';
    if (!id || lots.has(id)) { issues.push({ severity: 'error', code: !id ? 'LOT_REQUIRED' : 'DUPLICATE_LOT', file: files[0]!, row: row.line, field: 'lot_id', lotId: id, message: !id ? 'Не указан идентификатор лота.' : 'Повторяющийся lot_id в файле закупок.', action: 'Укажите уникальный идентификатор записи.' }); continue; }
    if (n.publish_date && !validDate(n.publish_date)) issues.push({ severity: 'error', code: 'DATE_FORMAT', file: files[0]!, row: row.line, field: 'publish_date', lotId: id, message: 'Дата должна быть реальной датой ГГГГ-ММ-ДД.', action: 'Исправьте дату публикации.' });
    if (n.start_price && !/^\d+(?:[.,]\d{1,2})?$/.test(n.start_price)) issues.push({ severity: 'error', code: 'PRICE_FORMAT', file: files[0]!, row: row.line, field: 'start_price', lotId: id, message: 'Не удалось прочитать начальную цену.', action: 'Укажите неотрицательное число без пробелов или оставьте пустым.' });
    if (!n.subject && !n.procedure_name) issues.push({ severity: 'warning', code: 'SUBJECT_MISSING', file: files[0]!, row: row.line, field: 'subject', lotId: id, message: 'Описание закупки отсутствует.', action: 'Подбор будет опираться на позиции ТРУ.' });
    lots.set(id, { lotId: id, subject: n.subject || n.procedure_name || 'Закупка без описания', source: n.is_eshop_or_aisgz || 'Не указан', publishDate: n.publish_date || null, price: n.start_price?.replace(',', '.') || null, customerInn: n.customer_inn || null, customerName: null, region: '', items: [] });
  }
  const noticeSchemaInvalid = issues.some(i => i.file === files[0] && i.severity === 'error' && ['SCHEMA', 'EMPTY_FILE', 'CSV_SYNTAX'].includes(i.code));
  const seen = new Set<string>();
  for (const row of items) {
if (noticeSchemaInvalid) continue; const r = row.value, id = r.lot_id ?? '', lot = lots.get(id);
    if (!lot) { issues.push({ severity: 'error', code: 'ORPHAN_ITEM', file: files[1]!, row: row.line, field: 'lot_id', lotId: id, message: `В файле закупок нет лота «${id}».`, action: 'Проверьте связь двух файлов по lot_id.' }); continue; }
    const code = r.okpd2_code || null; const valid = !code || /^\d{2}(?:\.\d{1,2}){0,2}(?:\.\d{3})?$/.test(code);
    if (!code || !valid) issues.push({ severity: 'warning', code: !code ? 'OKPD2_MISSING' : 'OKPD2_FORMAT', file: files[1]!, row: row.line, field: 'okpd2_code', lotId: id, message: !code ? 'Не указан код ОКПД2.' : 'Формат кода ОКПД2 требует проверки.', action: 'Текстовый поиск доступен. Уточните код при возможности.' });
    if (!r.product_name) issues.push({ severity: 'warning', code: 'ITEM_NAME_MISSING', file: files[1]!, row: row.line, field: 'product_name', lotId: id, message: 'Нет наименования позиции.', action: 'Позиция сохранена; уточните её описание.' });
    const identity = JSON.stringify([id, r.product_name, code]);
    if (seen.has(identity)) issues.push({ severity: 'warning', code: 'DUPLICATE_ITEM', file: files[1]!, row: row.line, field: 'product_name', lotId: id, message: 'Повторяющаяся запись сохранена.', action: 'Уточните, является ли повтор отдельной позицией.' });
    seen.add(identity); const index = (itemCounts.get(id) ?? 0) + 1; itemCounts.set(id, index);
    lot.items.push({ id: `${id}-item-${index}`, name: r.product_name || 'Позиция без названия', okpd2: code, quantity: null });
  }
  for (const lot of lots.values()) if (!lot.items.length) issues.push({ severity: 'warning', code: 'NO_ITEMS', file: files[1]!, row: 0, field: 'lot_id', lotId: lot.lotId, message: 'У лота нет позиций ТРУ.', action: 'Подбор возможен по предмету закупки, но оснований будет меньше.' });
  if (!notices.length && !issues.some(x => x.severity === 'error')) issues.push({ severity: 'error', code: 'NO_LOTS', file: files[0]!, row: 2, field: 'lot_id', message: 'Нет закупок для обработки.', action: 'Добавьте хотя бы одну строку закупки.' });
  return { id: '', files, procurements: [...lots.values()], issues, rows: { notices: notices.length, items: items.length }, queryIds: [] };
}
/** Экранирует текстовые значения для CSV и нейтрализует формулы в табличных редакторах. */
export function encodeCSV(rows: readonly (readonly unknown[])[]): string {
  return '\uFEFF' + rows.map(row => row.map(value => { let s = value == null ? '' : String(value); if (/^[\s\u0000-\u001f]*[=+@-]/.test(s) || /^[\t\r\n]/.test(s)) s = "'" + s; return /[;"\r\n]/.test(s) ? '"' + s.replaceAll('"', '""') + '"' : s; }).join(';')).join('\r\n');
}
export function ensureItems(items: NeedItem[], text: string): NeedItem[] { return items.length ? items : [{ id: 'subject-1', name: text, okpd2: null, quantity: null }]; }

export type CSVKind = 'notices' | 'items';
/** Match only the supported schemas. Original files, rows and values are sent unchanged. */
export function detectCSVKind(text: string): CSVKind {
  if (!text.replace(/^\uFEFF/, '').trim()) throw new Error('Файл пуст. Выберите CSV с данными.');
  for (const delimiter of [';', ',']) {
    try {
      const header = parseCSV(text, delimiter)[0]?.cells.map(value => value.trim());
      if (!header?.length) continue;
      const exact = (columns: string[]) => header.length === columns.length && new Set(header).size === header.length && columns.every(column => header.includes(column));
      if (exact(NOTICE_COLUMNS)) return 'notices';
      if (exact(ITEM_COLUMNS)) return 'items';
    } catch { /* The server reports exact syntax errors for the supported schema. */ }
  }
  throw new Error('Не удалось определить файл по колонкам. Нужны два CSV исходного формата: закупки и позиции. Проверьте формат в справке.');
}
