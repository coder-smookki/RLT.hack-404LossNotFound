import React, { useState } from 'react';
import { companyLabel } from '../domain/presentation.js';
import { allRecommendations } from '../domain/recommendations.js';
import { request } from '../api/client.js';
import { useApp, MAX_COMPARE } from '../app/store.js';
import { Tabs, ButtonLink, Button, Facts } from './ui.js';
import type { QueryRecord } from '../domain/types.js';
import { date, money } from '../domain/format.js';
import s from '../styles/pages.module.css';

/** Адрес сравнения с выбранными компаниями в параметре `ids`: ссылка работает после перезагрузки и при пересылке. */
export function compareURL(query: QueryRecord, ids: string[]) { return `/queries/${query.id}/compare?ids=${ids.map(encodeURIComponent).join(',')}`; }

/** Навигация по разделам одной закупки. */
export function QueryTabs({ query, value }: { query: QueryRecord; value: string }) {
  return <Tabs label="Разделы закупки" value={value} items={[{ id: 'results', label: 'Кандидаты', count: allRecommendations(query).length, to: `/queries/${query.id}/results` }, { id: 'items', label: 'Состав закупки', count: query.procurement.items.length, to: `/queries/${query.id}/items` }, { id: 'sources', label: 'Источники', to: `/sources?queryId=${query.id}` }]} />;
}

/** Ключевые сведения закупки одной строкой фактов: номер лота, цена, дата, заказчик, площадка. */
export function LotFacts({ query }: { query: QueryRecord }) {
  const p = query.procurement;
  return <div className={s.lotFacts}><Facts rows={[{ label: 'Начальная цена', value: money(p.price) }, { label: 'Опубликовано', value: date(p.publishDate) }, { label: 'ИНН заказчика', value: p.customerInn ?? 'не указан' }, { label: 'Площадка', value: p.source || 'не указана' }]} /></div>;
}

/** Кнопка «Сохранить в избранное» для запроса; результат подтверждается коротким уведомлением. */
export function SaveToggle({ query, reload }: { query: QueryRecord; reload: () => void }) {
  const app = useApp(); const [saving, setSaving] = useState(false);
  async function save() { if (saving) return; setSaving(true); try { await request(`/queries/${query.id}/saved`, { method: 'PATCH', body: { saved: !query.saved } }); app.toast(query.saved ? 'Запрос убран из сохранённых.' : 'Запрос сохранён.', 'success'); reload(); } catch (e) { app.toast(`Не удалось изменить: ${(e as Error).message}`, 'error'); } finally { setSaving(false); } }
  return <Button variant="secondary" icon={query.saved ? 'check' : 'bookmark'} busy={saving} onClick={() => void save()}>{query.saved ? 'Сохранён' : 'Сохранить'}</Button>;
}

/** Закреплённая панель выбранных компаний: сравнение доступно от двух компаний, экспорт - от одной. */
export function SelectionBar({ query }: { query: QueryRecord }) {
  const app = useApp(), ids = app.selected(query), names = ids.map(id => allRecommendations(query).find(r => r.company.id === id)).filter(Boolean).map(r => companyLabel(r!.company));
  if (!ids.length) return null;
  return <div className={s.selectionBar} role="region" aria-label="Выбранные компании">
    <div className={s.selectionText}><strong>Выбрано {ids.length} из {MAX_COMPARE}</strong><span className={s.muted} title={names.join(', ')}>{names.join(', ')}</span></div>
    <div className={s.selectionActions}><Button small variant="ghost" onClick={() => app.setSelection(query, [])}>Очистить</Button><ButtonLink small secondary icon="download" to={`/exports?queryId=${query.id}&selection=1`}>Экспорт выбранных</ButtonLink>{ids.length >= 2 ? <ButtonLink small icon="compare" to={compareURL(query, ids)}>Сравнить</ButtonLink> : <span className={s.selectionHint}>Для сравнения выберите ещё одну</span>}</div>
  </div>;
}
