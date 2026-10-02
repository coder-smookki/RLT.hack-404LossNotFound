import { ButtonLink, Card, TextLink, Badge, Stat, Alert, Button } from '../components/ui.js';
import { Icon } from '../components/Icon.js';
import { Link, PageFocus } from '../app/router.js';
import { useAuth } from '../app/auth.js';
import { useResource } from '../api/client.js';
import type { Analytics, QueryRecord } from '../domain/types.js';
import { STATUS_LABEL, STATUS_TONE } from '../domain/types.js';
import { date, number, plural } from '../domain/format.js';
import { batchProgress } from './Queries.js';
import s from '../styles/pages.module.css';

/** Главная: одно главное действие (новая загрузка), продолжение недавней работы и только реальные показатели аккаунта. */
export function Home() {
  const auth = useAuth();
  const q = useResource<QueryRecord[]>('/queries', data => data.some(x => x.status === 'queued' || x.status === 'running'), 5000);
  const a = useResource<Analytics>('/analytics');
  const list = q.data ?? [], recent = [...list].sort((x, y) => y.createdAt.localeCompare(x.createdAt)).slice(0, 5);
  const active = list.filter(x => x.status === 'queued' || x.status === 'running'), activeImport = active[0]?.importId;
  const progress = active.length ? batchProgress(list.filter(x => x.importId === activeImport)) : null;
  return <>
    <PageFocus title="Главная" />
    <section className={s.welcome} aria-labelledby="home-title">
      <div><span className={s.eyebrow}>{auth.user?.name ? `Здравствуйте, ${auth.user.name}` : 'Здравствуйте'}</span><h1 id="home-title" tabIndex={-1}>Подбор поставщиков для закупки</h1><p>Загрузите два CSV - закупки и их позиции. Мы проверим файлы, подберём кандидатов и покажем основания по каждой позиции.</p></div>
      <div className={s.welcomeActions}><ButtonLink to="/search" icon="upload">Загрузить файлы</ButtonLink><TextLink to="/help#csv">Требования к файлам</TextLink></div>
    </section>

    {progress && <Card className={s.padded}><div className={s.sectionHead}><div><h2>Идёт подбор</h2><p className={s.muted}>Готовые закупки можно открывать, не дожидаясь остальных.</p></div><ButtonLink small secondary to={`/queries?importId=${activeImport}`}>Следить за ходом</ButtonLink></div><progress className={s.progress} value={progress.done} max={progress.total} aria-label={`Готово ${progress.done} из ${progress.total}`} /><p className={s.muted}>Готово {progress.done} из {progress.total} · в работе {progress.running} · в очереди {progress.queued}{progress.failed ? ` · не завершено ${progress.failed}` : ''}</p></Card>}

    <section className={s.block} aria-labelledby="recent-title">
      <div className={s.sectionHead}><h2 id="recent-title">Недавние закупки</h2>{list.length > 0 && <TextLink to="/queries" icon="arrow" iconAfter>Все запросы ({list.length})</TextLink>}</div>
      {q.error && !q.data ? <Alert tone="error" title="Не удалось загрузить историю" action={<Button small variant="secondary" icon="refresh" onClick={q.reload}>Повторить</Button>}>{q.error.message}</Alert>
        : q.loading ? <Card className={s.padded}><p className={s.muted} role="status">Загружаем историю запросов</p></Card>
        : !recent.length ? <Card className={s.padded}><p>Здесь появятся ваши закупки. Начните с загрузки двух CSV.</p></Card>
        : <Card as="div"><ul className={s.recentList}>{recent.map(item => <li key={item.id}><span className={s.recentIcon}><Icon name="report" /></span><div className={s.recentMain}><Link to={`/queries/${item.id}/results`}><strong>{item.procurement.subject || 'Закупка без описания'}</strong></Link><span className={s.muted}>Лот {item.procurement.lotId} · {item.procurement.items.length} {plural(item.procurement.items.length, ['позиция', 'позиции', 'позиций'])} · загружено {date(item.createdAt)}</span></div><Badge tone={STATUS_TONE[item.status]}>{STATUS_LABEL[item.status]}</Badge></li>)}</ul></Card>}
    </section>

    {a.data && a.data.notices > 0 && <section className={s.block} aria-labelledby="stats-title">
      <div className={s.sectionHead}><h2 id="stats-title">Ваши данные</h2><TextLink to="/analytics" icon="arrow" iconAfter>Подробнее</TextLink></div>
      <div className={s.statsRow}><Stat value={number(a.data.notices)} label={plural(a.data.notices, ['закупка загружена', 'закупки загружены', 'закупок загружено'])} /><Stat value={number(a.data.items)} label="позиций ТРУ" /><Stat value={number(a.data.withSuppliers)} label="закупок с кандидатами" /><Stat value={number(a.data.inn)} label="компаний в результатах" /></div>
    </section>}
  </>;
}
