import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, navigate, useParams } from '../app/router.js';
import { useAuth } from '../app/auth.js';
import { useApp } from '../app/store.js';
import { Icon } from './Icon.js';
import { TEAM_NAME } from '../domain/types.js';
import s from '../styles/layout.module.css';

const nav = [['/search', 'upload', 'Новая закупка'], ['/', 'home', 'Главная'], ['/queries', 'clock', 'Мои запросы'], ['/companies', 'building', 'Контрагенты'], ['/sources', 'link', 'Источники'], ['/analytics', 'chart', 'Статистика']] as const;

/** Определяет пункт меню, к которому относится адрес, включая вложенные страницы сценария. */
function activeSection(path: string): string {
  if (path === '/') return '/';
  if (path.startsWith('/search') || path.startsWith('/imports')) return '/search';
  for (const root of ['/companies', '/sources', '/analytics', '/help', '/account']) if (path.startsWith(root)) return root;
  return path.startsWith('/queries') || path.startsWith('/exports') ? '/queries' : '';
}

/**
 * Каркас рабочего пространства: боковая навигация, на узком экране - верхняя панель
 * с выезжающим меню (Escape и щелчок по фону закрывают его, фокус возвращается на кнопку).
 */
export function Layout({ children }: { children?: ReactNode }) {
  const path = useParams().pathname, auth = useAuth(), app = useApp(); const [menu, setMenu] = useState(false), [leaving, setLeaving] = useState(false);
  const active = activeSection(path), menuButton = useRef<HTMLButtonElement>(null), sidebar = useRef<HTMLElement>(null);
  useEffect(() => setMenu(false), [path]);
  useEffect(() => {
    if (!menu) return;
    sidebar.current?.querySelector<HTMLElement>('nav a')?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setMenu(false); menuButton.current?.focus(); } };
    document.addEventListener('keydown', onKey); return () => document.removeEventListener('keydown', onKey);
  }, [menu]);
  async function logout() {
    if (leaving) return; setLeaving(true);
    try { await auth.logout(); navigate('/login', { replace: true }); } catch (e) { app.toast(`Не удалось выйти: ${(e as Error).message}`, 'error'); } finally { setLeaving(false); }
  }
  const item = (to: string, icon: string, label: string, extra = '') => <Link key={to} to={to} className={[s.navItem, extra].join(' ')} aria-current={active === to ? 'page' : undefined}><Icon name={icon} /><span>{label}</span></Link>;
  return <div id="workspace" className={s.workspace}>
    <a href="#main" className={s.skip}>Перейти к содержимому</a>
    <header className={s.topbar}>
      <button ref={menuButton} type="button" className={s.menuButton} aria-label={menu ? 'Закрыть меню' : 'Открыть меню'} aria-expanded={menu} aria-controls="main-navigation" onClick={() => setMenu(x => !x)}><Icon name={menu ? 'close' : 'menu'} /></button>
      <Link to="/" className={s.brand}><span><Icon name="layers" size={18} /></span><strong>Подбор контрагентов</strong></Link>
      <Link to="/account" className={s.topbarAccount} aria-label="Личный кабинет"><Icon name="user" /></Link>
    </header>
    {menu && <button type="button" className={s.backdrop} aria-label="Закрыть меню" tabIndex={-1} onClick={() => setMenu(false)} />}
    <aside ref={sidebar} className={[s.sidebar, menu ? s.open : ''].join(' ')} id="main-navigation">
      <Link to="/" className={s.brand}><span><Icon name="layers" size={18} /></span><strong>Подбор контрагентов</strong></Link>
      <nav className={s.nav} aria-label="Основная навигация">{nav.map(([to, icon, label]) => item(to, icon, label, to === '/search' ? s.navPrimary : ''))}</nav>
      <div className={s.sidebarFooter}>
        {item('/help', 'help', 'Как пользоваться')}
        {item('/account', 'user', 'Личный кабинет')}
        <div className={s.account}><div><strong>{auth.user?.name || 'Аккаунт'}</strong><span>{auth.user?.email}</span></div><button type="button" className={s.logout} onClick={() => void logout()} disabled={leaving} aria-label="Выйти из аккаунта" title="Выйти из аккаунта"><Icon name="logout" /></button></div>
        <div className={s.team}>{TEAM_NAME}</div>
      </div>
    </aside>
    <div className={s.content}><main id="main" className={s.main} tabIndex={-1}><div className={s.inner}>{children}</div></main></div>
  </div>;
}
