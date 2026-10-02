import React from 'react';
import { Icon } from './Icon.js';
import s from '../styles/layout.module.css';

const labels = ['Файлы', 'Проверка', 'Подбор'] as const;

/**
 * Показывает этап сценария «файлы - проверка - подбор». Пройденные этапы отмечены галочкой
 * и текстом для экранного диктора; текущий этап передаётся через aria-current.
 * @param step текущий этап от 1 до 3.
 */
export function ProgressStepper({ step }: { step: 1 | 2 | 3; onBack?: (step: number) => void; flowId?: string }) {
  return <ol className={s.stepper} aria-label="Этапы подбора">{labels.map((label, i) => {
    const n = i + 1, done = n < step;
    return <React.Fragment key={label}>
      <li className={[s.step, done ? s.stepDone : '', n === step ? s.stepActive : ''].join(' ')} aria-current={n === step ? 'step' : undefined}><span className={s.stepCircle} aria-hidden="true">{done ? <Icon name="check" size={16} /> : n}</span><span>{label}{done && <span style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0,0,0,0)' }}>, завершено</span>}</span></li>
      {n < labels.length && <li aria-hidden="true" className={[s.stepLine, done ? s.stepLineDone : ''].join(' ')} />}
    </React.Fragment>;
  })}</ol>;
}
