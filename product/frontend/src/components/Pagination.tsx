import React from 'react';
import { Button } from './ui.js';
import s from '../styles/ui.module.css';

/**
 * Навигация по страницам длинного списка с указанием видимого диапазона.
 * @param page текущая страница (с 1); @param pages число страниц; @param total всего записей; @param size размер страницы.
 */
export function Pagination({ page, pages, onChange, total, size = 20, label = 'Страницы списка' }: { page: number; pages: number; onChange: (page: number) => void; total?: number; size?: number; label?: string }) {
  if (pages <= 1) return null;
  const from = (page - 1) * size + 1, to = total === undefined ? page * size : Math.min(total, page * size);
  return <nav className={s.pagination} aria-label={label}><span aria-live="polite">{total === undefined ? `Страница ${page} из ${pages}` : `${from}-${to} из ${total.toLocaleString('ru-RU')}`}</span><div><Button small variant="secondary" icon="back" disabled={page <= 1} onClick={() => onChange(page - 1)}>Назад</Button><Button small variant="secondary" disabled={page >= pages} onClick={() => onChange(page + 1)}>Далее</Button></div></nav>;
}
