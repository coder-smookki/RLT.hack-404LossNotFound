import { useCallback, useEffect, useRef, useState } from 'react';
import { config } from '../app/config.js';
export class ApiError extends Error {
  constructor(public code: string, message: string, public status = 0) { super(message); this.name = 'ApiError'; }
}
let csrfToken = '';
export function resetCSRF() { csrfToken = ''; }
export async function getCSRF(signal?: AbortSignal) {
  if (!csrfToken) {
    const response = await fetch(config.apiBaseUrl + '/auth/csrf', { credentials: 'same-origin', signal });
    if (!response.ok) throw new ApiError('CSRF', 'Не удалось установить защищённое соединение. Обновите страницу.', response.status);
    csrfToken = (await response.json() as { csrfToken: string }).csrfToken;
  }
  return csrfToken;
}
export async function request<T>(path: string, options: { method?: string; body?: unknown; signal?: AbortSignal; idempotencyKey?: string; response?: 'json' | 'blob' } = {}): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  options.signal?.addEventListener('abort', abort, { once: true });
  if (options.signal?.aborted) controller.abort();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const method = options.method ?? 'GET';
    const multipart = options.body instanceof FormData;
    const headers: Record<string, string> = {};
    if (options.body !== undefined && !multipart) headers['Content-Type'] = 'application/json';
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) headers['X-CSRFToken'] = await getCSRF(controller.signal);
    if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey;
    const res = await fetch(config.apiBaseUrl + path, { method, headers, body: options.body === undefined ? undefined : multipart ? options.body as FormData : JSON.stringify(options.body), signal: controller.signal, credentials: 'same-origin' });
    if (!res.ok) {
      let message = 'Не удалось получить ответ сервера.', code = 'HTTP_ERROR';
      try { const data = await res.json() as { error?: { message?: string; code?: string } }; message = data.error?.message ?? message; code = data.error?.code ?? code; } catch { /* Non-JSON server failure. */ }
      if (res.status === 401 && !['/auth/me', '/auth/login', '/auth/register'].includes(path)) window.dispatchEvent(new Event('supply-session-expired'));
      throw new ApiError(code, message, res.status);
    }
    if (options.response === 'blob') return await res.blob() as T;
    if (res.status === 204) return undefined as T;
    return await res.json() as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (options.signal?.aborted) throw new DOMException('Запрос отменён', 'AbortError');
    if (controller.signal.aborted) throw new ApiError('TIMEOUT', 'Сервер не ответил вовремя. Повторите действие.');
    throw new ApiError('NETWORK', 'Нет связи с сервером. Проверьте подключение и повторите действие.');
  } finally { clearTimeout(timeout); options.signal?.removeEventListener('abort', abort); }
}
export interface Resource<T> { data: T | null; loading: boolean; error: Error | null; reload: () => void; }
export function useResource<T>(path: string | null, poll?: (data: T) => boolean): Resource<T> {
  const [state, setState] = useState<{ key: string; data: T | null; loading: boolean; error: Error | null }>({ key: '', data: null, loading: true, error: null });
  const [revision, setRevision] = useState(0); const pollRef = useRef(poll); pollRef.current = poll; const key = path ?? '';
  useEffect(() => {
    if (!path) { setState({ key, data: null, loading: false, error: null }); return; }
    const controller = new AbortController(); let active = true, timer: ReturnType<typeof setTimeout> | undefined;
    setState({ key, data: null, loading: true, error: null });
    async function load() {
      try { const data = await request<T>(path!, { signal: controller.signal }); if (!active) return; setState({ key, data, loading: false, error: null }); if (pollRef.current?.(data)) timer = setTimeout(load, 1500); }
      catch (error) { if (active) setState({ key, data: null, loading: false, error: error as Error }); }
    }
    void load(); return () => { active = false; controller.abort(); clearTimeout(timer); };
  }, [path, key, revision]);
  const reload = useCallback(() => setRevision(r => r + 1), []);
  return state.key === key ? { ...state, reload } : { data: null, loading: Boolean(path), error: null, reload };
}
