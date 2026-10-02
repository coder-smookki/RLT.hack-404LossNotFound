import React, { useEffect, useSyncExternalStore, type ReactNode, type MouseEvent } from 'react';
let memoryURL: string | null = null;
export function installMemoryRouter(initialURL: string) { memoryURL = initialURL; notify(); }
export function getRouterURL() { return memoryURL ?? location.pathname + location.search + location.hash; }
export function getRouterOrigin() { return memoryURL !== null ? 'http://localhost:5173' : location.origin; }
const listeners = new Set<() => void>();
function notify() { listeners.forEach(l => l()); }
window.addEventListener('popstate', notify);
function subscribe(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn); }; }
export function useLocation() { return useSyncExternalStore(subscribe, getRouterURL); }
function internalURL(to: string) { const u = new URL(to, getRouterOrigin()); if (u.origin !== getRouterOrigin()) throw Error('Only same-origin navigation is allowed'); return u.pathname + u.search + u.hash; }
/** Переходит по внутреннему адресу, сохраняя совместимость с Back/Forward и прямыми ссылками. */
export function navigate(to: string, options: { replace?: boolean; preserveScenario?: boolean; scroll?: boolean } = {}) { const target = internalURL(to); if (memoryURL !== null) memoryURL = target; else history[options.replace ? 'replaceState' : 'pushState']({}, '', target); notify(); if (options.scroll !== false) document.querySelector('main')?.scrollTo({ top: 0 }); }
export function Link({ to, children, className, title, onClick, ...rest }: { to: string; children?: ReactNode; className?: string; title?: string; onClick?: () => void;[key: string]: unknown }) {
  const href = internalURL(to); return <a {...rest} href={href} title={title} className={className} onClick={(event: MouseEvent<HTMLAnchorElement>) => { if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); onClick?.(); navigate(to); }}>{children}</a>;
}
export function useParams() { const current = useLocation(); return new URL(current, getRouterOrigin()); }
export function updateParams(values: Record<string, string | undefined>, replace = true) { const url = new URL(getRouterURL(), getRouterOrigin()); for (const [k, v] of Object.entries(values)) v == null || v === '' ? url.searchParams.delete(k) : url.searchParams.set(k, v); navigate(url.pathname + url.search, { replace, scroll: false }); }
export function PageFocus({ title }: { title: string }) { const current = useLocation().split('?')[0]; useEffect(() => { document.title = `${title} - Подбор контрагентов`; }, [title]); useEffect(() => { const t = setTimeout(() => document.querySelector<HTMLElement>('h1')?.focus({ preventScroll: true }), 30); return () => clearTimeout(t); }, [current]); return null; }
