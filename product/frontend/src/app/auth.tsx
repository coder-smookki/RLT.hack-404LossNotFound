import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { ApiError, request, resetCSRF } from '../api/client.js';
import { setStorageScope } from './store.js';
export interface User { id: string; email: string; name: string; }
interface AuthValue { user: User | null; loading: boolean; error: string; accept: (user: User) => void; logout: () => Promise<void>; retry: () => void; }
const Auth = createContext<AuthValue | null>(null);
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState(''), [revision, setRevision] = useState(0);
  const accept = (next: User) => { setStorageScope(String(next.id)); setUser(next); resetCSRF(); setError(''); };
  useEffect(() => {
    let live = true; setLoading(true); setError('');
    request<{ user: User | null }>('/auth/me').then(data => { if (live && data.user) accept(data.user); }).catch(err => { if (live && !(err instanceof ApiError && err.status === 401)) setError(err.message); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [revision]);
  useEffect(() => { const expired = () => { setStorageScope(''); setUser(null); resetCSRF(); }; window.addEventListener('supply-session-expired', expired); return () => window.removeEventListener('supply-session-expired', expired); }, []);
  const logout = async () => { await request('/auth/logout', { method: 'POST', body: {} }); setStorageScope(''); setUser(null); resetCSRF(); };
  return <Auth.Provider value={{ user, loading, error, accept, logout, retry: () => setRevision(x => x + 1) }}>{children}</Auth.Provider>;
}
export function useAuth() { const value = useContext(Auth); if (!value) throw Error('AuthProvider is required'); return value; }
