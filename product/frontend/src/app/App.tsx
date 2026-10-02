import React, { Component, useEffect, type ReactNode } from 'react';
import { AuthProvider, useAuth } from './auth.js';
import { navigate, useParams, PageFocus } from './router.js';
import { AppStore } from './store.js';
import { Account, SignIn } from '../pages/Account.js';
import { Layout } from '../components/Layout.js';
import { Empty, Button, ButtonLink, Toasts } from '../components/ui.js';
import { Icon } from '../components/Icon.js';
import { Home } from '../pages/Home.js'; import { Search } from '../pages/Search.js'; import { Review } from '../pages/Review.js'; import { Validation } from '../pages/Validation.js'; import { Queries } from '../pages/Queries.js'; import { Results } from '../pages/Results.js'; import { Lot } from '../pages/Lot.js'; import { Company } from '../pages/Company.js'; import { Compare } from '../pages/Compare.js'; import { Sources } from '../pages/Sources.js'; import { Analytics } from '../pages/Analytics.js'; import { Companies } from '../pages/Companies.js'; import { Export } from '../pages/Export.js'; import { Help } from '../pages/Help.js';
import s from '../styles/account.module.css';

/** Перехватывает ошибку отрисовки страницы: пользователь видит понятный выход, технические детали уходят в консоль. */
class ErrorBoundary extends Component<{ children?: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error) { console.error('[ui] render failure', error); }
  render() { return this.state.failed ? <Empty icon="warning" title="Страницу не удалось показать" action={<><Button icon="refresh" onClick={() => location.reload()}>Обновить страницу</Button><ButtonLink to="/queries" secondary>Мои запросы</ButtonLink></>}>Сохранённые данные не изменились. Обновите страницу или вернитесь к списку запросов.</Empty> : this.props.children; }
}

function NotFound() { return <><PageFocus title="Страница не найдена" /><Empty level={1} icon="search" title="Страница не найдена" action={<><ButtonLink to="/">На главную</ButtonLink><ButtonLink to="/queries" secondary>Мои запросы</ButtonLink></>}>Адрес набран с ошибкой или страница больше не существует.</Empty></>; }

const routes: [RegExp, () => ReactNode][] = [
  [/^\/$/, () => <Home />], [/^\/search$/, () => <Search />], [/^\/search\/[^/]+\/review$/, () => <Review />], [/^\/imports\/[^/]+\/validation$/, () => <Validation />],
  [/^\/queries$/, () => <Queries />], [/^\/queries\/[^/]+\/results$/, () => <Results />], [/^\/queries\/[^/]+\/items$/, () => <Lot />], [/^\/queries\/[^/]+\/compare$/, () => <Compare />],
  [/^\/companies$/, () => <Companies />], [/^\/companies\/[^/]+$/, () => <Company />], [/^\/sources$/, () => <Sources />], [/^\/analytics$/, () => <Analytics />],
  [/^\/exports$/, () => <Export />], [/^\/help$/, () => <Help />], [/^\/account$/, () => <Account />],
];

function RouterView() {
  const p = useParams().pathname;
  useEffect(() => { if (p === '/login' || p === '/register') navigate('/', { replace: true }); }, [p]);
  const view = p === '/login' || p === '/register' ? <Home /> : routes.find(([pattern]) => pattern.test(p))?.[1]() ?? <NotFound />;
  return <Layout><ErrorBoundary key={p}>{view}</ErrorBoundary></Layout>;
}

/** Экран недоступности сервера до проверки сессии: причина и повтор без перезагрузки. */
function ServerUnavailable({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <main className={s.statusPage}><PageFocus title="Сервер недоступен" /><div className={s.statusCard}><span className={s.statusIcon}><Icon name="warning" size={28} /></span><h1 tabIndex={-1}>Сервер недоступен</h1><p>{message}</p><p className={s.statusHint}>Проверьте подключение. Если приложение запущено локально, убедитесь, что контейнеры работают.</p><Button icon="refresh" onClick={onRetry}>Повторить</Button></div></main>;
}

function AuthenticatedApp() {
  const auth = useAuth();
  if (auth.loading) return <main className={s.statusPage} aria-busy="true"><p className={s.statusHint} role="status">Проверяем сессию</p></main>;
  if (auth.error) return <ServerUnavailable message={auth.error} onRetry={auth.retry} />;
  if (!auth.user) return <SignIn />;
  return <AppStore key={auth.user.id}><RouterView /><Toasts /></AppStore>;
}
export function App() { return <AuthProvider><AuthenticatedApp /></AuthProvider>; }
