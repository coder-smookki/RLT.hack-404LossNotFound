import { useCallback, useEffect, useRef, useState } from 'react';
import { config } from '../app/config.js';

/** Ошибка API с кодом сервера, HTTP-статусом и сообщениями для конкретных полей формы. */
export class ApiError extends Error {
  constructor(public code: string, message: string, public status = 0, public fields: Record<string, string> = {}) { super(message); this.name = 'ApiError'; }
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

interface RequestOptions { method?: string; body?: unknown; signal?: AbortSignal; idempotencyKey?: string; response?: 'json' | 'blob' }

/**
 * Выполняет запрос к API с сессионной cookie, CSRF и необязательным Idempotency-Key.
 * Если сервер отклонил устаревший CSRF-токен, запрос повторяется один раз с новым токеном:
 * отклонённый запрос не выполнялся, поэтому повтор не создаёт дубликатов.
 * @param path путь относительно `/api/v1`.
 * @param options метод, тело, сигнал отмены, ключ идемпотентности и тип ответа.
 * @returns разобранный JSON, Blob или `undefined` для ответа 204.
 * @throws ApiError с понятным сообщением при ошибке сервера, таймауте или отсутствии сети.
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  try {
    return await send<T>(path, options);
  } catch (error) {
    if (error instanceof ApiError && error.code === 'CSRF_REJECTED') { resetCSRF(); return await send<T>(path, options); }
    throw error;
  }
}

async function send<T>(path: string, options: RequestOptions): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  options.signal?.addEventListener('abort', abort, { once: true });
  if (options.signal?.aborted) controller.abort();
  const timeout = setTimeout(() => controller.abort(), 60000);
  try {
    const method = options.method ?? 'GET';
    const multipart = options.body instanceof FormData;
    const headers: Record<string, string> = {};
    if (options.body !== undefined && !multipart) headers['Content-Type'] = 'application/json';
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) headers['X-CSRFToken'] = await getCSRF(controller.signal);
    if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey;
    const res = await fetch(config.apiBaseUrl + path, { method, headers, body: options.body === undefined ? undefined : multipart ? options.body as FormData : JSON.stringify(options.body), signal: controller.signal, credentials: 'same-origin' });
    if (!res.ok) {
      let message = res.status >= 500 ? 'Сервер временно не может выполнить запрос. Повторите действие позже.' : 'Не удалось выполнить запрос.', code = 'HTTP_ERROR', fields: Record<string, string> = {};
      try { const data = await res.json() as { error?: { message?: string; code?: string; fields?: Record<string, string> } }; message = data.error?.message ?? message; code = data.error?.code ?? code; fields = data.error?.fields ?? {}; } catch { /* Ответ сервера без JSON. */ }
      if (res.status === 401 && !['/auth/me', '/auth/login', '/auth/register'].includes(path)) window.dispatchEvent(new Event('supply-session-expired'));
      throw new ApiError(code, message, res.status, fields);
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

/** Возвращает true для ответа «запись не найдена или недоступна этому аккаунту». */
export function isNotFound(error: unknown): boolean { return error instanceof ApiError && (error.status === 404 || error.status === 403); }

export interface Resource<T> { data: T | null; loading: boolean; error: Error | null; refreshError: Error | null; reload: () => void; }

/**
 * Загружает ресурс API и при необходимости опрашивает его, пока `poll` возвращает true.
 * Во время опроса показанные данные сохраняются; сбой фонового обновления не стирает их,
 * а попадает в `refreshError`, чтобы страница могла показать устойчивое предупреждение.
 * @param path путь API или null, если загрузка не нужна.
 * @param poll условие продолжения опроса по последним данным.
 * @param intervalMs пауза между запросами опроса.
 */
export function useResource<T>(path: string | null, poll?: (data: T) => boolean, intervalMs = 2000): Resource<T> {
  const [state, setState] = useState<{ key: string; data: T | null; loading: boolean; error: Error | null; refreshError: Error | null }>({ key: '', data: null, loading: true, error: null, refreshError: null });
  const [revision, setRevision] = useState(0); const pollRef = useRef(poll); pollRef.current = poll; const key = path ?? '';
  useEffect(() => {
    if (!path) { setState({ key, data: null, loading: false, error: null, refreshError: null }); return; }
    const controller = new AbortController(); let active = true, timer: ReturnType<typeof setTimeout> | undefined;
    setState(old => old.key === key && old.data !== null ? { ...old, refreshError: null } : { key, data: null, loading: true, error: null, refreshError: null });
    async function load() {
      try {
        const data = await request<T>(path!, { signal: controller.signal }); if (!active) return;
        setState({ key, data, loading: false, error: null, refreshError: null });
        if (pollRef.current?.(data)) timer = setTimeout(load, intervalMs);
      } catch (error) {
        if (!active) return;
        setState(old => old.key === key && old.data !== null ? { ...old, loading: false, refreshError: error as Error } : { key, data: null, loading: false, error: error as Error, refreshError: null });
      }
    }
    void load(); return () => { active = false; controller.abort(); clearTimeout(timer); };
  }, [path, key, revision, intervalMs]);
  const reload = useCallback(() => setRevision(r => r + 1), []);
  return state.key === key ? { ...state, reload } : { data: null, loading: Boolean(path), error: null, refreshError: null, reload };
}
