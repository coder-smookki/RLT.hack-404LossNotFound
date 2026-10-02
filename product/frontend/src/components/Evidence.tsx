import React from 'react';
import { evidenceLabel, itemStatus } from '../domain/recommendations.js';
import { Badge } from './ui.js';
import { Icon } from './Icon.js';
import { sourceDates } from './SourceCard.js';
import type { NeedItem, ItemEvidence, SourceEvidence } from '../domain/types.js';
import { safeURL } from '../domain/format.js';
import s from '../styles/pages.module.css';

/** Тон метки основания: противоречие - предупреждение, остальное нейтрально; совпадение не окрашивается в «надёжный» зелёный. */
export function evidenceTone(evidence?: ItemEvidence): 'warning' | 'info' | 'neutral' { const status = itemStatus(evidence); return status === 'conflict' ? 'warning' : evidence && evidence.kind !== 'none' ? 'info' : 'neutral'; }

/**
 * Основание по одной позиции закупки: позиция, вид основания, пояснение и подтверждающий фрагмент
 * с датами и ссылкой. Отсутствие основания не трактуется как невозможность поставки.
 */
export function EvidencePanel({ item, number, evidence, source }: { item: NeedItem; number: number; evidence: ItemEvidence | undefined; source: SourceEvidence | undefined }) {
  const url = safeURL(source?.url), found = evidence && evidence.kind !== 'none';
  return <div className={s.evidencePanel}>
    <span className={s.eyebrowSmall}>Позиция {number}{item.okpd2 ? ` · ОКПД2 ${item.okpd2}` : ''}</span>
    <h3 className={s.evidenceTitle}>{item.name}</h3>
    <Badge tone={evidenceTone(evidence)} icon={itemStatus(evidence) === 'conflict'}>{evidenceLabel(evidence)}</Badge>
    {found ? <>
      <p>{evidence!.reason}</p>
      <div className={s.evidenceSource}>
        <strong>{source?.title ?? 'Источник не указан'}</strong>
        {source?.excerpt && <blockquote className={s.quote}>{source.excerpt}</blockquote>}
        {source && <p className={s.muted}>{sourceDates(source).join(' · ')}{source.id.startsWith('history:') ? '' : ` · связь с ИНН ${source.identityVerified ? 'подтверждена' : 'не подтверждена'}`}</p>}
        {url && <a href={url} target="_blank" rel="noopener noreferrer" className={s.externalLink}>Открыть источник<Icon name="external" size={15} /><span className={s.visuallyHidden}> (в новой вкладке)</span></a>}
      </div>
      <p className={s.muted}>Совпадение отдельных признаков не подтверждает всю позицию: уточните характеристики, наличие и условия поставки.</p>
    </> : <p className={s.muted}>В доступных источниках основания для этой позиции нет. Это не значит, что компания не может её поставить - уточните у компании.</p>}
  </div>;
}
