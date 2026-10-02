import React, { useEffect, useState } from 'react';
import { Icon } from './Icon.js';
import s from '../styles/layout.module.css';
const previousStages = new Map<string, number>();
/** Показывает действительный этап. Анимация продолжает предыдущий этап только в том же сценарии. */
export function ProgressStepper({ step, onBack, flowId = 'current' }: { step: 1 | 2 | 3; onBack?: (step: number) => void; flowId?: string }) {
  const [painted, setPainted] = useState(() => { const previous = previousStages.get(flowId); return previous !== undefined && Math.abs(previous - step) === 1 ? previous : step; });
  useEffect(() => {
previousStages.set(flowId, step); if (previousStages.size > 50) previousStages.delete(previousStages.keys().next().value!); let next = 0;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { setPainted(step); return; }
    const frame = requestAnimationFrame(() => { next = requestAnimationFrame(() => setPainted(step)); }); return () => { cancelAnimationFrame(frame); cancelAnimationFrame(next); };
  }, [step, flowId]);
  return <ol className={s.stepper} aria-label="Этапы подбора">{['Потребность', 'Проверка', 'Результаты'].map((label, i) => <React.Fragment key={label}><li aria-current={step === i + 1 ? 'step' : undefined} className={[s.step, i + 1 <= step ? s.stepReached : '', step === i + 1 ? s.stepActive : ''].join(' ')}><button type="button" disabled={i + 1 >= step || !onBack} onClick={() => onBack?.(i + 1)} aria-label={`${i + 1}. ${label}${i + 1 < step ? ', завершён' : ''}`}><span className={s.stepCircle}>{i + 1 < step ? <Icon name="check" size={19} /> : i + 1}</span><span>{label}</span></button></li>{i < 2 && <li aria-hidden="true" className={s.stepLine}><span data-filled={step > i + 1} style={{ transform: `scaleX(${painted > i + 1 ? 1 : 0})` }} /></li>}</React.Fragment>)}</ol>;
}
