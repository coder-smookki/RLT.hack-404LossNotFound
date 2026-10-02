import React, { useEffect, useId, useRef, useState, type ReactNode, type ChangeEvent, type MouseEvent, type Ref } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from './Icon.js';
import { Link, PageFocus } from '../app/router.js';
import { useApp } from '../app/store.js';
import { isNotFound } from '../api/client.js';
import type { Tone } from '../domain/types.js';
import s from '../styles/ui.module.css';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
const cx = (...names: (string | false | null | undefined)[]) => names.filter(Boolean).join(' ');

export function Button({ children, onClick, type = 'button', variant = 'primary', icon, disabled = false, busy = false, className = '', title, small = false, wide = false, describedBy }: { children?: ReactNode; onClick?: () => void; type?: 'button' | 'submit' | 'reset'; variant?: ButtonVariant; icon?: string; disabled?: boolean; busy?: boolean; className?: string; title?: string; small?: boolean; wide?: boolean; describedBy?: string }) {
  return <button type={type} onClick={onClick} className={cx(s.button, s[variant], small && s.small, wide && s.wide, className)} disabled={disabled || busy} aria-busy={busy || undefined} aria-describedby={describedBy} title={title}>{busy ? <span className={s.spinner} aria-hidden="true" /> : icon ? <Icon name={icon} size={18} /> : null}{children}</button>;
}
export function ButtonLink({ children, to, icon, secondary = false, variant, className = '', small = false }: { children?: ReactNode; to: string; icon?: string; secondary?: boolean; variant?: ButtonVariant; className?: string; small?: boolean }) {
  return <Link to={to} className={cx(s.button, s[variant ?? (secondary ? 'secondary' : 'primary')], small && s.small, className)}>{icon && <Icon name={icon} size={18} />}{children}</Link>;
}
export function TextLink({ children, to, icon, onClick, iconAfter = false }: { children?: ReactNode; to?: string; icon?: string; onClick?: () => void; iconAfter?: boolean }) {
  const content = <>{icon && !iconAfter && <Icon name={icon} size={18} />}<span>{children}</span>{icon && iconAfter && <Icon name={icon} size={18} />}</>;
  return to ? <Link to={to} className={s.textLink}>{content}</Link> : <button type="button" className={s.textLink} onClick={onClick}>{content}</button>;
}
export function IconButton({ icon, label, onClick, disabled = false, pressed }: { icon: string; label: string; onClick: () => void; disabled?: boolean; pressed?: boolean }) {
  return <button type="button" className={s.iconButton} aria-label={label} title={label} aria-pressed={pressed} onClick={onClick} disabled={disabled}><Icon name={icon} /></button>;
}
export function Card({ children, className = '', label, as = 'section' }: { children?: ReactNode; className?: string; label?: string; as?: 'section' | 'div' | 'article' }) {
  const Tag = as; return <Tag className={cx(s.card, className)} aria-label={label}>{children}</Tag>;
}

/** Заголовок страницы: единственный h1, необязательная надпись над ним, пояснение и действия справа. */
export function PageHeader({ title, eyebrow, subtitle, actions }: { title: string; eyebrow?: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return <><PageFocus title={title} /><header className={s.pageHeader}><div>{eyebrow && <span className={s.eyebrow}>{eyebrow}</span>}<h1 tabIndex={-1} className={title.length > 70 ? s.longTitle : undefined}>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>{actions && <div className={s.actions}>{actions}</div>}</header></>;
}

const toneIcon: Record<Tone, string> = { success: 'success', warning: 'warning', error: 'error', info: 'info', neutral: 'neutral', accent: 'info' };
/** Короткая метка состояния. Иконка дублирует цвет, чтобы статус не передавался только цветом. */
export function Badge({ children, tone = 'neutral', icon = true }: { children?: ReactNode; tone?: Tone; icon?: boolean }) {
  return <span className={cx(s.badge, s[tone], !icon && s.badgePlain)}>{icon && <Icon name={toneIcon[tone]} size={15} />}<span>{children}</span></span>;
}

/**
 * Устойчивое сообщение рядом с действием. Ошибки объявляются через role="alert",
 * остальные тона через role="status", если `live` включён.
 */
export function Alert({ title, children, tone = 'info', action, live = false, id }: { title: string; children?: ReactNode; tone?: Tone; action?: ReactNode; live?: boolean; id?: string }) {
  return <div id={id} className={cx(s.alert, s[tone])} role={tone === 'error' ? 'alert' : live ? 'status' : undefined} tabIndex={id ? -1 : undefined}><Icon name={toneIcon[tone]} size={20} /><div><strong>{title}</strong>{children && <div className={s.alertBody}>{children}</div>}{action && <div className={s.alertAction}>{action}</div>}</div></div>;
}

interface FieldProps { label: string; hint?: ReactNode; error?: string; id?: string }
function useFieldIds(given?: string) { const auto = useId(), id = given ?? auto; return { id, hintId: id + '-hint', errorId: id + '-error' }; }
function describe(ids: { hintId: string; errorId: string }, hint: unknown, error?: string) { return [hint ? ids.hintId : '', error ? ids.errorId : ''].filter(Boolean).join(' ') || undefined; }
function FieldMessages({ hint, error, ids }: { hint?: ReactNode; error?: string; ids: { hintId: string; errorId: string } }) {
  return <>{hint && <div className={s.hint} id={ids.hintId}>{hint}</div>}{error && <div className={s.fieldError} id={ids.errorId}><Icon name="error" size={15} /><span>{error}</span></div>}</>;
}

/** Текстовое поле с подписью, подсказкой и ошибкой, связанными через aria-describedby. */
export function Input({ label, hideLabel = false, value, onChange, placeholder = '', type = 'text', error, hint, required = false, icon, disabled = false, id: given, name, autoComplete, inputRef, maxLength, minLength, inputMode, suffix }: FieldProps & { hideLabel?: boolean; value: string; onChange: (value: string) => void; placeholder?: string; type?: string; required?: boolean; icon?: string; disabled?: boolean; name?: string; autoComplete?: string; inputRef?: Ref<HTMLInputElement>; maxLength?: number; minLength?: number; inputMode?: 'text' | 'email' | 'search' | 'numeric'; suffix?: ReactNode }) {
  const ids = useFieldIds(given);
  return <div className={s.field}><label htmlFor={ids.id} style={hideLabel ? srOnly : undefined}>{label}</label><div className={cx(s.inputWrap, error && s.invalid)}>{icon && <Icon name={icon} size={18} />}<input ref={inputRef} id={ids.id} name={name} type={type} value={value} onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)} placeholder={placeholder} required={required} disabled={disabled} autoComplete={autoComplete} maxLength={maxLength} minLength={minLength} inputMode={inputMode} aria-invalid={error ? true : undefined} aria-describedby={describe(ids, hint, error)} />{suffix}</div><FieldMessages hint={hint} error={error} ids={ids} /></div>;
}
const srOnly: React.CSSProperties = { position: 'absolute', width: 1, height: 1, padding: 0, margin: -1, overflow: 'hidden', clip: 'rect(0,0,0,0)', whiteSpace: 'nowrap', border: 0 };

/** Поле пароля с кнопкой показа и скрытия; состояние кнопки передаётся через aria-pressed. */
export function PasswordInput(props: Omit<Parameters<typeof Input>[0], 'type' | 'suffix'>) {
  const [visible, setVisible] = useState(false);
  return <Input {...props} type={visible ? 'text' : 'password'} suffix={<span className={s.reveal}><IconButton icon={visible ? 'eyeOff' : 'eye'} label={visible ? 'Скрыть пароль' : 'Показать пароль'} pressed={visible} onClick={() => setVisible(v => !v)} /></span>} />;
}
export function Textarea({ label, value, onChange, placeholder, error, hint, rows = 4 }: FieldProps & { value: string; onChange: (s: string) => void; placeholder?: string; rows?: number }) {
  const ids = useFieldIds();
  return <div className={s.field}><label htmlFor={ids.id}>{label}</label><textarea id={ids.id} rows={rows} value={value} onChange={(e: ChangeEvent<HTMLTextAreaElement>) => onChange(e.target.value)} placeholder={placeholder} aria-invalid={error ? true : undefined} aria-describedby={describe(ids, hint, error)} /><FieldMessages hint={hint} error={error} ids={ids} /></div>;
}
export function Select({ label, value, onChange, options, ariaLabel, className = '', hint, disabled = false }: { label?: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; ariaLabel?: string; className?: string; hint?: ReactNode; disabled?: boolean }) {
  const ids = useFieldIds();
  return <div className={cx(s.field, className)}>{label && <label htmlFor={ids.id}>{label}</label>}<div className={s.selectWrap}><select id={ids.id} value={value} aria-label={label ? undefined : ariaLabel} aria-describedby={hint ? ids.hintId : undefined} disabled={disabled} onChange={(e: ChangeEvent<HTMLSelectElement>) => onChange(e.target.value)}>{options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}</select><Icon name="chevron" size={18} /></div>{hint && <div className={s.hint} id={ids.hintId}>{hint}</div>}</div>;
}

/** Флажок с областью нажатия 44 px. С `text` подпись видима, иначе передаётся только через aria-label. */
export function Check({ checked, onChange, label, disabled = false, text }: { checked: boolean; onChange: () => void; label: string; disabled?: boolean; text?: ReactNode }) {
  const box = <span className={s.checkbox}><input type="checkbox" checked={checked} onChange={onChange} aria-label={text ? undefined : label} disabled={disabled} /><span aria-hidden="true">{checked && <Icon name="check" size={14} />}</span></span>;
  return text ? <label className={s.checkRow}>{box}<span>{text}</span></label> : box;
}

/**
 * Переключатель разделов. Пункты со ссылкой образуют навигацию (aria-current),
 * пункты без ссылки - вкладки внутри страницы с управлением стрелками.
 */
export function Tabs({ items, value, onChange, label = 'Разделы' }: { items: { id: string; label: string; count?: number; to?: string }[]; value: string; onChange?: (id: string) => void; label?: string }) {
  const inner = (item: { label: string; count?: number }) => <>{item.label}{item.count !== undefined && <span className={s.count}>{item.count.toLocaleString('ru-RU')}</span>}</>;
  if (items.every(item => item.to)) return <nav className={s.tabs} aria-label={label}>{items.map(item => <Link key={item.id} to={item.to!} className={cx(s.tab, item.id === value && s.activeTab)} aria-current={item.id === value ? 'page' : undefined}>{inner(item)}</Link>)}</nav>;
  return <div className={s.tabs} role="tablist" aria-label={label} onKeyDown={(e: React.KeyboardEvent<HTMLDivElement>) => { if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return; const nodes = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('[role="tab"]')); const active = nodes.indexOf(document.activeElement as HTMLElement); const index = e.key === 'Home' ? 0 : e.key === 'End' ? nodes.length - 1 : (active + (e.key === 'ArrowRight' ? 1 : -1) + nodes.length) % nodes.length; e.preventDefault(); nodes[index]?.focus(); nodes[index]?.click(); }}>{items.map(item => <button key={item.id} type="button" role="tab" tabIndex={item.id === value ? 0 : -1} aria-selected={item.id === value} className={cx(s.tab, item.id === value && s.activeTab)} onClick={() => onChange?.(item.id)}>{inner(item)}</button>)}</div>;
}

export function Empty({ title, children, action, icon = 'search', plain = false, level = 2 }: { title: string; children?: ReactNode; action?: ReactNode; icon?: string; plain?: boolean; level?: 1 | 2 }) {
  const body = <><div className={s.emptyIcon}><Icon name={icon} size={28} /></div>{level === 1 ? <h1 tabIndex={-1}>{title}</h1> : <h2>{title}</h2>}{children && <p>{children}</p>}{action && <div className={s.actions}>{action}</div>}</>;
  return plain ? <div className={s.empty}>{body}</div> : <Card className={s.empty}>{body}</Card>;
}
export function Loading({ text = 'Загружаем данные', rows = 3 }: { text?: string; rows?: number }) {
  return <Card className={s.loading} label="Загрузка" as="div"><p className={s.loadingLine} role="status"><span className={s.spinner} aria-hidden="true" />{text}</p>{Array.from({ length: rows }, (_, i) => <div key={i} className={s.skeleton} />)}</Card>;
}

/**
 * Ошибка загрузки страницы с рабочим продолжением. 404/403 объясняются как отсутствие записи
 * в этом аккаунте; сетевые сбои предлагают повтор без создания новых записей.
 */
export function Failure({ error, onRetry, back = { to: '/queries', label: 'Мои запросы' } }: { error: Error; onRetry?: () => void; back?: { to: string; label: string } }) {
  if (isNotFound(error)) return <><PageFocus title="Запись не найдена" /><Empty level={1} icon="lock" title="Запись не найдена" action={<ButtonLink to={back.to}>{back.label}</ButtonLink>}>Её нет в вашем аккаунте или ссылка устарела. Результаты других пользователей недоступны.</Empty></>;
  return <><PageFocus title="Не удалось загрузить данные" /><Empty level={1} icon="warning" title="Не удалось загрузить данные" action={<>{onRetry && <Button onClick={onRetry} icon="refresh">Повторить</Button>}<ButtonLink to={back.to} secondary>{back.label}</ButtonLink></>}>{error.message}</Empty></>;
}

/** Раскрываемый блок для длинных сведений; заголовок остаётся доступным с клавиатуры. */
export function Disclosure({ summary, children, open, className = '' }: { summary: ReactNode; children?: ReactNode; open?: boolean; className?: string }) {
  return <details className={cx(s.disclosure, className)} open={open}><summary><Icon name="chevron" size={18} />{summary}</summary><div className={s.disclosureBody}>{children}</div></details>;
}
export function Stat({ value, label }: { value: ReactNode; label: string }) { return <Card className={s.stat} as="div"><strong>{value}</strong><span>{label}</span></Card>; }

/** Список «поле - значение» с необязательным источником под значением. */
export function Facts({ rows }: { rows: { label: string; value: ReactNode; source?: ReactNode }[] }) {
  return <dl className={s.facts}>{rows.map(row => <div key={row.label}><dt>{row.label}</dt><dd>{row.value}{row.source && <span className={s.factSource}>{row.source}</span>}</dd></div>)}</dl>;
}

/**
 * Модальное окно для выбора или подтверждения: ловушка фокуса, Escape, возврат фокуса
 * на вызвавший элемент и заголовок, связанный через aria-labelledby.
 */
export function Dialog({ title, children, onClose, footer }: { title: string; children?: ReactNode; onClose: () => void; footer?: ReactNode }) {
  const ref = useRef<HTMLDivElement | null>(null), id = useId(), close = useRef(onClose); close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null; const panel = ref.current; const main = document.getElementById('workspace'); main?.setAttribute('inert', '');
    const focusables = () => Array.from(panel?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input:not(:disabled),select,textarea,[tabindex="0"]') ?? []);
    focusables()[0]?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); close.current(); } if (e.key === 'Tab') { const f = focusables(), first = f[0], last = f[f.length - 1]; if (!first) { e.preventDefault(); return; } if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); } else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); } } };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); main?.removeAttribute('inert'); previous?.focus({ preventScroll: true }); };
  }, []);
  return createPortal(<div className={s.overlay} onClick={(e: MouseEvent<HTMLDivElement>) => { if (e.target === e.currentTarget) onClose(); }}><div ref={ref} className={s.dialog} role="dialog" aria-modal="true" aria-labelledby={id}><div className={s.dialogHeader}><h2 id={id}>{title}</h2><IconButton icon="close" label="Закрыть окно" onClick={onClose} /></div><div className={s.dialogContent}>{children}</div>{footer && <div className={s.dialogFooter}>{footer}</div>}</div></div>, document.body);
}

/** Неблокирующие уведомления. Контейнер с aria-live существует всегда, чтобы сообщения объявлялись. */
export function Toasts() {
  const { toasts, dismiss } = useApp();
  return <div className={s.toasts} role="status" aria-live="polite" aria-relevant="additions text">{toasts.map(t => <div key={t.id} className={cx(s.toast, s[t.tone])}><Icon name={toneIcon[t.tone]} /><span>{t.text}</span><IconButton icon="close" label="Закрыть уведомление" onClick={() => dismiss(t.id)} /></div>)}</div>;
}
