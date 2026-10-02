import React, { createContext, useContext, useState, useRef, useEffect, useCallback, type ReactNode } from 'react';
import type { Draft, QueryRecord, Tone } from '../domain/types.js';
import { uid } from '../domain/format.js';
interface Toast { id: string; text: string; tone: Tone; }
interface Context { selections: Record<string, string[]>; setSelection: (q: QueryRecord, ids: string[]) => void; selected: (q: QueryRecord) => string[]; toggle: (q: QueryRecord, id: string) => void; toast: (text: string, tone?: Tone) => void; toasts: Toast[]; dismiss: (id: string) => void; }
const Store = createContext<Context | null>(null);
export const MAX_COMPARE = 4;
let storageScope = '';
let privateMemory = new Map<string, unknown>();
const selectionKey = (userId: string) => 'supply-selection:' + userId;

/**
 * Переключает область хранения на аккаунт. Черновики живут только в памяти вкладки.
 * @param userId идентификатор аккаунта или пустая строка после выхода.
 * @param clearPrevious удалить сохранённый во вкладке выбор компаний прежнего аккаунта (при явном выходе).
 */
export function setStorageScope(userId: string, clearPrevious = false) {
  if (clearPrevious && storageScope) { try { sessionStorage.removeItem(selectionKey(storageScope)); } catch { /* Хранилище вкладки недоступно. */ } }
  if (storageScope !== userId) { storageScope = userId; privateMemory = new Map(); }
}
function read<T>(key: string, initial: T): T { return (privateMemory.get(storageScope + ':' + key) as T | undefined) ?? initial; }
function write(key: string, value: unknown) { if (storageScope) privateMemory.set(storageScope + ':' + key, value); }

/** Читает выбор компаний текущего аккаунта из sessionStorage вкладки; при недоступности хранилища возвращает пустой выбор. */
function readSelections(): Record<string, string[]> {
  try { const raw = storageScope ? sessionStorage.getItem(selectionKey(storageScope)) : null; const value = raw ? JSON.parse(raw) as unknown : null; return value && typeof value === 'object' ? value as Record<string, string[]> : {}; } catch { return {}; }
}
function writeSelections(value: Record<string, string[]>) { try { if (storageScope) sessionStorage.setItem(selectionKey(storageScope), JSON.stringify(value)); } catch { /* Выбор остаётся в памяти страницы. */ } }

export function loadDraft(): Draft { return read<Draft>('supply-ai-draft', { id: uid('draft'), mode: 'csv', text: '', codes: [], price: '', region: '', updatedAt: new Date().toISOString() }); }
export function saveDraft(d: Draft) { write('supply-ai-draft', { ...d, updatedAt: new Date().toISOString() }); }
export function getDraft(id: string): Draft | null { const d = loadDraft(); return d.id === id ? d : read<Draft | null>('draft:' + id, null); }
export function archiveDraft(d: Draft) { write('draft:' + d.id, d); saveDraft(d); }
export function clearDraft() { privateMemory.delete(storageScope + ':supply-ai-draft'); }

/**
 * Общее состояние рабочего пространства: выбор компаний для сравнения (переживает перезагрузку вкладки)
 * и короткие уведомления. Одинаковые уведомления не дублируются, а продлевают показ.
 */
export function AppStore({ children }: { children?: ReactNode }) {
  const [selections, setSelections] = useState<Record<string, string[]>>(readSelections); const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>()); useEffect(() => () => { for (const timer of timers.current.values()) clearTimeout(timer); timers.current.clear(); }, []);
  const dismiss = useCallback((id: string) => { clearTimeout(timers.current.get(id)); timers.current.delete(id); setToasts(t => t.filter(x => x.id !== id)); }, []);
  const toast = useCallback((text: string, tone: Tone = 'info') => {
    const id = tone + ':' + text, duration = Math.min(12000, Math.max(5000, text.length * 75));
    clearTimeout(timers.current.get(id));
    setToasts(t => { const rest = t.filter(x => x.id !== id); for (const old of rest.slice(0, -2)) { clearTimeout(timers.current.get(old.id)); timers.current.delete(old.id); } return [...rest.slice(-2), { id, text, tone }]; });
    if (tone !== 'error') timers.current.set(id, setTimeout(() => dismiss(id), duration));
  }, [dismiss]);
  const selected = (q: QueryRecord) => selections[q.id + '@' + q.resultVersion] ?? [];
  const setSelection = (q: QueryRecord, ids: string[]) => { const unique = [...new Set(ids)].slice(0, MAX_COMPARE); setSelections(old => { const next = { ...old, [q.id + '@' + q.resultVersion]: unique }; writeSelections(next); return next; }); };
  const toggle = (q: QueryRecord, id: string) => { const current = selected(q); if (!current.includes(id) && current.length >= MAX_COMPARE) { toast(`Можно выбрать не больше ${MAX_COMPARE} компаний. Уберите одну из выбранных.`, 'warning'); return; } setSelection(q, current.includes(id) ? current.filter(x => x !== id) : [...current, id]); };
  return <Store.Provider value={{ selections, setSelection, selected, toggle, toast, toasts, dismiss }}>{children}</Store.Provider>;
}
export function useApp() { const ctx = useContext(Store); if (!ctx) throw Error('AppStore is required'); return ctx; }
