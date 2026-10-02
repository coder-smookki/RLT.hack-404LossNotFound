import { AuthProvider, useAuth } from './auth.js';
import { Account, SignIn } from '../pages/Account.js';
import { Loading, Failure } from '../components/ui.js';
import React, { Component, type ReactNode } from 'react'; import { Layout } from '../components/Layout.js'; import { useParams } from './router.js';  import { AppStore } from './store.js'; import { Empty, ButtonLink, Toasts } from '../components/ui.js';
import { Home } from '../pages/Home.js'; import { Search } from '../pages/Search.js'; import { Review } from '../pages/Review.js'; import { Validation } from '../pages/Validation.js'; import { Queries } from '../pages/Queries.js'; import { Results } from '../pages/Results.js'; import { Lot } from '../pages/Lot.js'; import { Company } from '../pages/Company.js'; import { Compare } from '../pages/Compare.js'; import { Sources } from '../pages/Sources.js'; import { Analytics } from '../pages/Analytics.js'; import { Companies } from '../pages/Companies.js'; import { Export } from '../pages/Export.js'; import { Help } from '../pages/Help.js';
class ErrorBoundary extends Component<{ children?: ReactNode }, { error: string | null }> { state = { error: null as string | null }; static getDerivedStateFromError(error: Error) { return { error: error.message }; } render() { return this.state.error ? <Empty title="Не удалось отобразить страницу" action={<button onClick={() => location.assign('/queries')}>Вернуться к запросам</button>}>Данные не соответствуют ожидаемому формату. {this.state.error}</Empty> : this.props.children; } }
function RouterView() {
const url = useParams(), p = url.pathname; let view: ReactNode;
  if (p === '/' || p === '/login' || p === '/register') view = <Home />; else if (p === '/search') view = <Search />; else if (/^\/search\/[^/]+\/review$/.test(p)) view = <Review />; else if (/^\/imports\/[^/]+\/validation$/.test(p)) view = <Validation />; else if (p === '/queries') view = <Queries />; else if (/^\/queries\/[^/]+\/results$/.test(p)) view = <Results />; else if (/^\/queries\/[^/]+\/items$/.test(p)) view = <Lot />; else if (/^\/queries\/[^/]+\/compare$/.test(p)) view = <Compare />; else if (p === '/companies') view = <Companies />; else if (/^\/companies\/[^/]+$/.test(p)) view = <Company />; else if (p === '/sources') view = <Sources />; else if (p === '/analytics') view = <Analytics />; else if (p === '/exports') view = <Export />; else if (p === '/help') view = <Help />; else if (p === '/account') view = <Account />; else view = <Empty title="Страница не найдена" action={<ButtonLink to="/">На главную</ButtonLink>}>Проверьте адрес или вернитесь в рабочее пространство.</Empty>;
  return <Layout><ErrorBoundary key={p}>{view}</ErrorBoundary></Layout>;
}
function AuthenticatedApp() {
  const auth = useAuth();
  if (auth.loading) return <div style={{ padding: 32 }}><Loading text="Проверяем сессию" /></div>;
  if (auth.error) return <div style={{ padding: 32 }}><Failure error={Error(auth.error)} onRetry={auth.retry} /></div>;
  if (!auth.user) return <SignIn />;
  return <AppStore key={auth.user.id}><RouterView /><Toasts /></AppStore>;
}
export function App() { return <AuthProvider><AuthenticatedApp /></AuthProvider>; }
