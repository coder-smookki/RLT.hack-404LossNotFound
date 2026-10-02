import { Link, useParams, updateParams } from '../app/router.js';
import { useResource } from '../api/client.js';
import { PageHeader, Card, Input, Select, ButtonLink, Button, Empty, Loading, Failure } from '../components/ui.js';
import { Pagination } from '../components/Pagination.js';
import { type Company } from '../domain/types.js';
import { companyName, verifiedText } from '../domain/presentation.js';
import { number, plural } from '../domain/format.js';
import { paginate } from '../domain/pagination.js';
import { originOptions, roleOptions } from './Results.js';
import s from '../styles/pages.module.css';

/** Компании из результатов аккаунта: поиск по названию или ИНН, канал, регион и опыт участия из подтверждённых сведений. */
export function Companies() {
  const p = useParams().searchParams, search = p.get('q') ?? '', origin = p.get('origin') ?? '', role = p.get('role') ?? '';
  const r = useResource<Company[]>('/companies');
  if (r.loading) return <Loading text="Загружаем компании из ваших результатов" />;
  if (r.error) return <Failure error={r.error} onRetry={r.reload} back={{ to: '/', label: 'На главную' }} />;
  const needle = search.trim().toLowerCase(), list = (r.data ?? []).filter(c => (!needle || `${companyName(c)} ${c.inn ?? ''}`.toLowerCase().includes(needle)) && (!origin || c.origin === origin) && (!role || c.role.role === role));
  const showRoles = (r.data ?? []).some(c => c.role.verified && c.role.role !== 'unknown');
  const page = paginate(list, p.get('page'), 25), filtered = Boolean(needle || origin || role);
  return <>
    <PageHeader title="Контрагенты" subtitle="Компании из результатов ваших закупок. Основания по позициям смотрите в карточке, открытой из конкретной закупки." />
    <div className={s.filters}>
      <Input label="Поиск по названию или ИНН" hideLabel type="search" icon="search" placeholder="Название или ИНН" value={search} onChange={v => updateParams({ q: v || undefined, page: undefined })} />
      <Select ariaLabel="Канал" value={origin} onChange={v => updateParams({ origin: v || undefined, page: undefined })} options={originOptions} />
      {showRoles && <Select ariaLabel="Роль компании" value={role} onChange={v => updateParams({ role: v || undefined, page: undefined })} options={roleOptions} />}
    </div>
    {list.length ? <Card as="div">
      <div className={s.tableWrap}><table className={s.queryTable}><caption className={s.visuallyHidden}>Компании: {list.length}</caption><thead><tr><th scope="col">Компания</th><th scope="col">Канал</th><th scope="col">Регион</th><th scope="col">Опыт участия</th></tr></thead>
        <tbody>{page.items.map(c => <tr key={c.id}><td data-label="Компания"><Link to={`/companies/${encodeURIComponent(c.id)}`} className={s.rowTitle}>{companyName(c)}</Link><span className={s.muted}>ИНН {c.inn ?? 'не указан'}</span></td><td data-label="Канал">{c.origin === 'history' ? 'История закупок' : 'Внешние источники'}</td><td data-label="Регион">{verifiedText(c, 'region') ?? <span className={s.muted}>не найден</span>}</td><td data-label="Опыт участия">{c.historySummary?.lotCount ? `${number(c.historySummary.lotCount)} ${plural(c.historySummary.lotCount, ['закупка', 'закупки', 'закупок'])} с участием` : <span className={s.muted}>нет сводных сведений</span>}</td></tr>)}</tbody></table></div>
      <Pagination page={page.page} pages={page.pages} total={page.total} size={25} onChange={n => updateParams({ page: String(n) })} />
    </Card> : <Empty title={filtered ? 'Ничего не найдено' : 'Компаний пока нет'} icon="building" action={filtered ? <Button variant="secondary" onClick={() => updateParams({ q: undefined, origin: undefined, role: undefined, page: undefined })}>Сбросить фильтры</Button> : <ButtonLink to="/search" icon="upload">Загрузить файлы</ButtonLink>}>{filtered ? 'Измените условия поиска.' : 'Здесь появятся компании из результатов подбора ваших закупок.'}</Empty>}
  </>;
}
