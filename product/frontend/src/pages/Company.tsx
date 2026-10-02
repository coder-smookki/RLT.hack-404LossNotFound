import { useState } from 'react';
import { allRecommendations, evidenceLabel } from '../domain/recommendations.js';
import { companyName, recommendationBasis, verifiedText, verifiedContacts, contactHref } from '../domain/presentation.js';
import { SourceCard } from '../components/SourceCard.js';
import { useParams, updateParams } from '../app/router.js';
import { ApiError, useResource } from '../api/client.js';
import { useApp } from '../app/store.js';
import { PageHeader, Card, Tabs, Button, ButtonLink, TextLink, Badge, Alert, Empty, Loading, Failure, Dialog, Drawer } from '../components/ui.js';
import { Icon } from '../components/Icon.js';
import { EvidencePanel } from '../components/Evidence.js';
import { CompanyChecks, CompanyCompleteness, CompanyExperience, CompanyHistoryTable } from '../components/CompanyDossier.js';
import { CompanyRefresh } from '../components/CompanyRefresh.js';
import { ROLE_LABEL, type Company as CompanyType, type QueryRecord } from '../domain/types.js';
import { safeURL } from '../domain/format.js';
import s from '../styles/pages.module.css';
export function Company() {
  const url = useParams(), id = url.pathname.split('/')[2] ?? '', queryId = url.searchParams.get('queryId'), tab = url.searchParams.get('tab') ?? 'overview';
  const company = useResource<CompanyType>(`/companies/${id}${queryId ? `?queryId=${encodeURIComponent(queryId)}` : ''}`), qr = useResource<QueryRecord>(queryId ? `/queries/${queryId}` : null), app = useApp();
  const [roleOpen, setRoleOpen] = useState(false), [drawer, setDrawer] = useState(false);
  if (company.loading || qr.loading) return <Loading/>;
  if (company.error instanceof ApiError && company.error.status === 404) return <><PageHeader title="Карточка контрагента"/><Empty title="Профиль пока недоступен" icon="building" action={<ButtonLink to="/companies">К контрагентам</ButtonLink>}>Компания не найдена в результатах вашего аккаунта. Откройте её из своей закупки.</Empty></>;
  if (company.error) return <Failure error={company.error} onRetry={company.reload}/>;
  if (qr.error) return <Failure error={qr.error} onRetry={qr.reload}/>;
  if (!company.data) return null;
  const c = company.data, q = qr.data, rec = q ? allRecommendations(q).find(row => row.company.id === c.id) : undefined, items = q?.procurement.items ?? [];
  const currentItem = items.find(item => item.id === url.searchParams.get('item')) ?? items[0], ev = rec?.evidence.find(e => e.itemId === currentItem?.id), source = c.sources.find(source => source.id === ev?.sourceId);
  const selected = q ? app.selected(q).includes(c.id) : false, name = companyName(c), basis = rec ? recommendationBasis(rec) : null;
  const title = tab === 'items' ? 'Основания по позициям' : tab === 'sources' ? 'Источники компании' : tab === 'history' ? 'История участия' : name;
  const website = verifiedText(c, 'website') ?? c.website, description = verifiedText(c, 'description');
  const fields = [['ИНН', c.inn ?? 'Не указан'], ['ОГРН', verifiedText(c, 'ogrn') ?? 'Не подтверждён'], ['КПП', verifiedText(c, 'kpp') ?? c.kpp ?? 'Не найден'], ['Сайт', website ?? 'Не найден'], ['Регион', verifiedText(c, 'region') ?? c.region ?? 'Не установлен']];
  const itemPanel = currentItem ? <EvidencePanel item={currentItem} evidence={ev} source={source}/> : null;
  const profileSources = c.currentProfile?.sources ?? [];
  const contacts = verifiedContacts(c);
  return <><PageHeader title={title} subtitle={q ? `${tab === 'overview' ? 'Для закупки' : name + ' · закупка'} ${q.procurement.lotId} · ${q.procurement.subject}` : 'Доступные сведения о компании и их источники.'} actions={q && rec ? <Button variant={selected ? 'secondary' : 'primary'} icon={selected ? 'check' : 'bookmark'} onClick={() => app.toggle(q, c.id)}>{selected ? 'В подборке' : 'Добавить в подборку'}</Button> : undefined}/>
    <Tabs value={tab} items={[{ id: 'overview', label: 'О компании' }, { id: 'items', label: 'По позициям' }, { id: 'sources', label: 'Источники' }, { id: 'history', label: 'История участия' }]} onChange={value => updateParams({ tab: value, item: undefined })}/>
    {tab === 'overview' ? <div className={s.companyGrid}><div className={s.verticalCards}>
      <Card className={s.padded}><h2>Что известно о компании</h2><p className={s.profileSummary}>{description ?? 'Описание деятельности пока не подтверждено. Ниже показаны доступные реквизиты и сведения.'}</p><dl className={s.description}>{fields.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{label === 'Сайт' && safeURL(value) ? <a href={safeURL(value)!} target="_blank" rel="noopener noreferrer">{value}</a> : value}</dd></div>)}</dl>{c.currentProfile && <p className={s.profileStatus}>{c.currentProfile.completeness.verifiedFields > 0 ? 'Есть сведения с подтверждающими источниками.' : 'Сведения о компании ещё не подтверждены.'}</p>}<div className={s.sectionGap}><TextLink icon="link" onClick={() => updateParams({ tab: 'sources' })}>Посмотреть источники сведений</TextLink></div></Card>
      <Card className={s.padded}><h2>Деловые контакты</h2>{contacts.length ? <><ul className={s.contactsList}>{contacts.map((contact, index) => { const sources = profileSources.filter(source => contact.sourceIds.includes(source.id)); return <li key={`${contact.kind}-${index}`}><span className={s.muted}>{contact.kind === 'email' ? 'Электронная почта' : contact.kind === 'phone' ? 'Телефон' : 'Контакт'}</span>{contactHref(contact) ? <a href={contactHref(contact)}>{contact.value}</a> : <strong>{contact.value}</strong>}{sources.map(source => safeURL(source.url) ? <a className={s.contactSource} key={source.id} href={safeURL(source.url)!} target="_blank" rel="noopener noreferrer">Источник контакта</a> : <span className={s.contactSource} key={source.id}>{source.title}</span>)}</li>; })}</ul><p className={s.muted}>Контакты опубликованы в источниках компании. Доступность телефона и доставку писем мы не проверяли.</p></> : <p className={s.muted}>Контакты с подтверждённым источником пока не найдены.</p>}</Card>
      <Card className={s.padded}><h2>Роль компании</h2><Badge tone={c.role.role === 'unknown' ? 'neutral' : 'accent'} icon={false}>{c.role.role === 'unknown' ? 'Пока не установлена' : ROLE_LABEL[c.role.role]}</Badge><p className={s.muted}>{c.role.verified ? 'Есть подтверждающий источник.' : 'Участие в закупках само по себе не определяет производителя или продавца.'}</p><TextLink icon="info" onClick={() => setRoleOpen(true)}>На чём основана роль</TextLink></Card>
      <CompanyExperience history={c.historySummary}/>
      <CompanyChecks company={c}/>
    </div><div className={s.verticalCards}>
      <Card className={s.padded}><h2>Почему предложена</h2>{rec && q && basis ? <><p className={s.listPosition}>№ {rec.rank} в своём списке</p><h3>{basis.title}</h3><p className={s.reasonText}>{basis.detail}</p>{rec.explanationCriteria?.length ? <ul className={s.basisList}>{rec.explanationCriteria.map((criterion, index) => <li key={`${criterion.code}-${index}`}><strong>{criterion.label}</strong>{criterion.basis && <p>{criterion.basis}</p>}{criterion.status === 'conflict' && <Badge tone="warning">Есть противоречие</Badge>}</li>)}</ul> : null}<p className={s.muted}>{basis.caution}</p><TextLink onClick={() => updateParams({ tab: 'items' })} icon="arrow">Проверить позиции закупки</TextLink></> : <><p className={s.muted}>Связь компании с потребностью показывается в конкретной закупке.</p><ButtonLink to="/queries" secondary>Выбрать закупку</ButtonLink></>}</Card>
      <Card className={s.padded}><h2>Что уточнить перед обращением</h2><ul className={s.checkList}>{['Точные товары, услуги и характеристики', 'Наличие, количество и сроки', 'Возможность исполнить все позиции закупки'].map(text => <li key={text}><Icon name="warning" size={18}/><span>{text}</span></li>)}</ul></Card>
      <CompanyCompleteness company={c}/>
      {q && <CompanyRefresh queryId={q.id} inn={c.inn} initialJob={c.sourceRefresh} onUpdated={() => { company.reload(); qr.reload(); }}/>}
    </div></div> : tab === 'items' ? q && currentItem ? <div className={s.evidenceGrid}><Card className={s.itemList}><h2>Все позиции · {items.length}</h2>{items.map(item => { const evidence = rec?.evidence.find(e => e.itemId === item.id); return <button type="button" key={item.id} aria-pressed={item.id === currentItem.id} className={item.id === currentItem.id ? s.itemActive : ''} onClick={() => updateParams({ item: item.id })}><strong>{item.name}</strong><span>{evidenceLabel(evidence)}</span></button>; })}</Card><Card>{itemPanel}<div className={s.paddedFooter}><TextLink icon="external" onClick={() => setDrawer(true)}>Развернуть основание</TextLink></div></Card></div> : <Empty title="Выберите закупку" action={<ButtonLink to="/queries">Мои запросы</ButtonLink>}>Основания по позициям доступны для конкретной закупки.</Empty>
      : tab === 'sources' ? <div className={s.verticalCards}>{profileSources.length > 0 && <><h2>Сведения о компании</h2>{profileSources.map(source => <SourceCard key={`profile-${source.id}`} source={source}/>)}</>}{c.sources.length ? <><h2>Основания сохранённого подбора</h2>{c.sources.map(source => <SourceCard key={source.id} source={source}/>)}</> : !profileSources.length && <Empty title="Материалы не сохранены" icon="link">Подтверждающих страниц пока нет. История участия, если доступна, находится на соседней вкладке.</Empty>}</div>
      : <CompanyHistoryTable company={c}/>}
    <div className={s.pageFooter}><TextLink icon="back" to={q ? `/queries/${q.id}/results` : '/companies'}>{q ? 'К контрагентам закупки' : 'К списку контрагентов'}</TextLink></div>
    {roleOpen && <Dialog title="Основание роли компании" onClose={() => setRoleOpen(false)}><Badge tone={c.role.verified ? 'success' : 'neutral'}>{c.role.verified ? 'Подтверждена источником' : 'Нужно уточнить'}</Badge><p>{c.role.basis}</p><p className={s.muted}>{c.role.scope}</p><Alert title="Роль не подтверждает весь ассортимент">Даже производитель может не выпускать конкретный товар из вашей закупки.</Alert></Dialog>}
    {drawer && currentItem && <Drawer title={`Основание · ${currentItem.name}`} onClose={() => setDrawer(false)}>{itemPanel}</Drawer>}
  </>;
}
