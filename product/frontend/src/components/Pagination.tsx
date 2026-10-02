import React from 'react';
import { Button } from './ui.js';
import s from '../styles/ui.module.css';
export function Pagination({ page, pages, onChange }: { page: number; pages: number; onChange: (page: number) => void }) { if (pages <= 1) return null; return <nav className={s.pagination} aria-label="Страницы списка"><Button variant="secondary" disabled={page <= 1} onClick={() => onChange(page - 1)}>Назад</Button><span aria-live="polite">Страница {page} из {pages}</span><Button variant="secondary" disabled={page >= pages} onClick={() => onChange(page + 1)}>Далее</Button></nav>; }
