import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { ApiError, request, resetCSRF } from '../api/client.js';
import { setStorageScope } from './store.js';
export interface User { id: string; email: string; name: string; }
interface AuthValue { user: User | null; loading: boolean; error: string; expired: boolean; accept: (user: User) => void; logout: () => Promise<void>; retry: () => void; }
const Auth = createContext<AuthValue | null>(null);

/**
 * Хранит текущий аккаунт и состояние сессии.
 * `expired` становится true, когда сервер ответил 401 на рабочий запрос: форма входа
 * объясняет причину и после входа возвращает пользователя на ту же страницу.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState(''), [revision, setRevision] = useState(0), [expired, setExpired] = useState(false);
  const accept = (next: User) => { setStorageScope(String(next.id)); setUser(next); resetCSRF(); setError(''); setExpired(false); };
  useEffect(() => {
    let live = true; setLoading(true); setError('');
    request<{ user: User | null }>('/auth/me').then(data => { if (live && data.user) accept(data.user); }).catch(err => { if (live && !(err instanceof ApiError && err.status === 401)) setError(err.message); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [revision]);
  useEffect(() => { const onExpired = () => { setStorageScope(''); setUser(null); resetCSRF(); setExpired(true); }; window.addEventListener('supply-session-expired', onExpired); return () => window.removeEventListener('supply-session-expired', onExpired); }, []);
  const logout = async () => { await request('/auth/logout', { method: 'POST', body: {} }); setStorageScope('', true); setUser(null); resetCSRF(); setExpired(false); };
  return <Auth.Provider value={{ user, loading, error, expired, accept, logout, retry: () => setRevision(x => x + 1) }}>{children}</Auth.Provider>;
}
export function useAuth() { const value = useContext(Auth); if (!value) throw Error('AuthProvider is required'); return value; }
