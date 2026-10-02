import React, { useEffect, useId, useRef, useState } from 'react';
import { formatScore, type Assessment } from '../domain/assessment.js';
import { Icon } from './Icon.js';
import s from '../styles/pages.module.css';

const stateIcon = { good: 'check', partial: 'neutral', missing: 'close', risk: 'warning' } as const;
const stateText = { good: 'подтверждено', partial: 'частично', missing: 'нет данных', risk: 'есть риск' } as const;

/** Разбор оценки по составляющим: баллы, полоса заполнения и пояснение для каждой. */
export function ScoreFactors({ assessment }: { assessment: Assessment }) {
  return <ul className={s.factorList}>{assessment.factors.map(f => <li key={f.id} className={s[`factor_${f.state}`]}>
    <div className={s.factorHead}><span className={s.factorIcon} aria-hidden="true"><Icon name={stateIcon[f.state]} size={14} /></span><span className={s.factorLabel}>{f.label}<span className={s.visuallyHidden}>, {stateText[f.state]}</span></span><span className={s.factorPoints}>{formatScore(f.points)} из {formatScore(f.max)}</span></div>
    <span className={s.factorBar} aria-hidden="true"><span style={{ width: `${f.max ? f.points / f.max * 100 : 0}%` }} /></span>
    <span className={s.factorDetail}>{f.detail}</span>
  </li>)}</ul>;
}

/**
 * Оценка обоснованности кандидата «7,4 из 10» с уровнем. Наведение, фокус или нажатие открывают
 * расшифровку: составляющие и что снижает оценку. Escape закрывает панель, фокус остаётся на кнопке.
 */
export function ScoreBadge({ assessment, align = 'end' }: { assessment: Assessment; align?: 'start' | 'end' }) {
  const [open, setOpen] = useState(false), [pinned, setPinned] = useState(false), id = useId(), root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setOpen(false); setPinned(false); } };
    const onDown = (e: PointerEvent) => { if (!root.current?.contains(e.target as Node)) { setOpen(false); setPinned(false); } };
    document.addEventListener('keydown', onKey); document.addEventListener('pointerdown', onDown);
    return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('pointerdown', onDown); };
  }, [open]);
  const a = assessment;
  return <div ref={root} className={s.scoreWrap} onMouseEnter={() => setOpen(true)} onMouseLeave={() => { if (!pinned) setOpen(false); }}>
    <button type="button" className={[s.score, s[`score_${a.level.tone}`]].join(' ')} aria-expanded={open} aria-controls={id} onFocus={() => setOpen(true)} onBlur={e => { if (!pinned && !root.current?.contains(e.relatedTarget as Node)) setOpen(false); }} onClick={() => { setPinned(!pinned); setOpen(!pinned); }}>
      <span className={s.scoreValue}>{formatScore(a.score)}<span> из 10</span></span>
      <span className={s.scoreLevel}>{a.level.label}</span>
      <span className={s.visuallyHidden}>. Показать, из чего складывается оценка</span>
    </button>
    {open && <div id={id} role="region" aria-label="Из чего складывается оценка" className={[s.scorePanel, align === 'start' ? s.scorePanelStart : ''].join(' ')}>
      <p className={s.scorePanelTitle}>Оценка обоснованности: {formatScore(a.score)} из 10</p>
      <ScoreFactors assessment={a} />
      {a.gaps.length > 0 && <><p className={s.miniTitle}>Что снижает оценку</p><ul className={s.gapList}>{a.gaps.slice(0, 4).map(g => <li key={g}>{g}</li>)}</ul></>}
      <p className={s.scoreNote}>Показывает, насколько кандидат подтверждён данными. Это не вероятность поставки; порядок в списке задаёт алгоритм подбора.</p>
    </div>}
  </div>;
}
