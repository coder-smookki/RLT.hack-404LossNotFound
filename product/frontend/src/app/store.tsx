import React, { createContext, useContext, useState, useRef, useEffect, type ReactNode } from 'react';
import type { Draft, QueryRecord, Tone } from '../domain/types.js';
import { uid } from '../domain/format.js';
interface Toast { id: string; text: string; tone: Tone; }
interface Context { selections: Record<string, string[]>; setSelection: (q: QueryRecord, ids: string[]) => void; selected: (q: QueryRecord) => string[]; toggle: (q: QueryRecord, id: string) => void; toast: (text: string, tone?: Tone) => void; toasts: Toast[]; dismiss: (id: string) => void; }
const Store = createContext<Context | null>(null);
let storageScope = '';
let privateMemory = new Map<string, unknown>();
export function setStorageScope(userId: string) { if (storageScope !== userId) { storageScope = userId; privateMemory = new Map(); } }
function read<T>(key: string, initial: T): T { return (privateMemory.get(storageScope + ':' + key) as T | undefined) ?? initial; }
function write(key: string, value: unknown) { if (storageScope) privateMemory.set(storageScope + ':' + key, value); }
export function loadDraft(): Draft { return read<Draft>('supply-ai-draft', { id: uid('draft'), mode: 'csv', text: '', codes: [], price: '', region: '', updatedAt: new Date().toISOString() }); }
export function saveDraft(d: Draft) { write('supply-ai-draft', { ...d, updatedAt: new Date().toISOString() }); }
export function getDraft(id: string): Draft | null { const d = loadDraft(); return d.id === id ? d : read<Draft | null>('draft:' + id, null); }
export function archiveDraft(d: Draft) { write('draft:' + d.id, d); saveDraft(d); }
export function clearDraft() { privateMemory.delete(storageScope + ':supply-ai-draft'); }
export function AppStore({ children }: { children?: ReactNode }) {
  const [selections, setSelections] = useState<Record<string, string[]>>(() => read('supply-ai-selections', {})); const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>()); useEffect(() => () => { for (const timer of timers.current.values()) clearTimeout(timer); timers.current.clear(); }, []);
  const dismiss = (id: string) => { clearTimeout(timers.current.get(id)); timers.current.delete(id); setToasts(t => t.filter(x => x.id !== id)); };
  const toast = (text: string, tone: Tone = 'info') => { const id = uid('toast'); setToasts(t => { for (const old of t.slice(0, -2)) { clearTimeout(timers.current.get(old.id)); timers.current.delete(old.id); } return [...t.slice(-2), { id, text, tone }]; }); if (tone === 'success' || tone === 'info') timers.current.set(id, setTimeout(() => dismiss(id), 6000)); };
  const selected = (q: QueryRecord) => selections[q.id + '@' + q.resultVersion] ?? [];
  const setSelection = (q: QueryRecord, ids: string[]) => { const unique = [...new Set(ids)].slice(0, 4); setSelections(old => { const next = { ...old, [q.id + '@' + q.resultVersion]: unique }; write('supply-ai-selections', next); return next; }); };
  const toggle = (q: QueryRecord, id: string) => { const current = selected(q); if (!current.includes(id) && current.length >= 4) { toast('Можно сравнить не больше четырёх компаний. Уберите одну из выбранных.', 'warning'); return; } setSelection(q, current.includes(id) ? current.filter(x => x !== id) : [...current, id]); };
  return <Store.Provider value={{ selections, setSelection, selected, toggle, toast, toasts, dismiss }}>{children}</Store.Provider>;
}
export function useApp() { const ctx = useContext(Store); if (!ctx) throw Error('AppStore is required'); return ctx; }
