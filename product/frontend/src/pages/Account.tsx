import { useEffect, useRef, useState, type FormEvent, type RefObject } from 'react';
import { ApiError, request, resetCSRF } from '../api/client.js';
import { useAuth, type User } from '../app/auth.js';
import { Link, navigate, useParams, PageFocus } from '../app/router.js';
import { useApp } from '../app/store.js';
import { Alert, Button, Card, Input, PageHeader, PasswordInput } from '../components/ui.js';
import { Icon } from '../components/Icon.js';
import { TEAM_NAME } from '../domain/types.js';
import { passwordRules } from '../domain/password.js';
import s from '../styles/account.module.css';

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
type Errors = Record<string, string>;

function PasswordRules({ password, email, name, id }: { password: string; email?: string; name?: string; id: string }) {
  return <ul className={s.rules} id={id} aria-label="Требования к паролю">{passwordRules(password, email, name).map(rule => <li key={rule.text} className={rule.met ? s.ruleMet : undefined}><Icon name={rule.met ? 'check' : rule.met === null ? 'info' : 'neutral'} size={16} /><span>{rule.text}{rule.met ? <span className={s.srOnly}> - выполнено</span> : rule.met === false ? <span className={s.srOnly}> - не выполнено</span> : null}</span></li>)}</ul>;
}

/** Переводит фокус на первое поле с ошибкой в порядке формы. */
function focusFirst(errors: Errors, order: [string, RefObject<HTMLInputElement | null>][]) { for (const [key, ref] of order) if (errors[key]) { ref.current?.focus(); return; } }

/** Вход и регистрация: ошибки у полей, требования к паролю до отправки, возврат на исходную страницу после входа. */
export function SignIn() {
  const auth = useAuth(), path = useParams().pathname, register = path === '/register';
  const [email, setEmail] = useState(''), [name, setName] = useState(''), [password, setPassword] = useState(''), [busy, setBusy] = useState(false), [errors, setErrors] = useState<Errors>({}), [formError, setFormError] = useState('');
  const emailRef = useRef<HTMLInputElement>(null), nameRef = useRef<HTMLInputElement>(null), passwordRef = useRef<HTMLInputElement>(null);
  const order: [string, RefObject<HTMLInputElement | null>][] = register ? [['name', nameRef], ['email', emailRef], ['password', passwordRef]] : [['email', emailRef], ['password', passwordRef]];
  function validate(): Errors {
    const next: Errors = {};
    if (register && !name.trim()) next.name = 'Укажите имя - оно видно только вам.';
    if (!email.trim()) next.email = 'Укажите адрес электронной почты.'; else if (!EMAIL.test(email.trim())) next.email = 'Проверьте адрес: нужен формат name@example.ru.';
    if (!password) next.password = 'Введите пароль.';
    else if (register && passwordRules(password, email, name).some(rule => rule.met === false)) next.password = 'Пароль не соответствует требованиям ниже.';
    return next;
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return; setFormError('');
    const local = validate(); setErrors(local); if (Object.keys(local).length) { focusFirst(local, order); return; }
    setBusy(true);
    try {
      const data = await request<{ user: User }>(register ? '/auth/register' : '/auth/login', { method: 'POST', body: register ? { email: email.trim(), name: name.trim(), password } : { email: email.trim(), password } });
      auth.accept(data.user); if (path === '/login' || path === '/register') navigate('/', { replace: true });
    } catch (e) {
      const error = e as ApiError, fields: Errors = { ...(error.fields ?? {}) };
      if (error.code === 'ACCOUNT_EXISTS') fields.email = 'Аккаунт с этим адресом уже есть. Войдите или используйте другой адрес.';
      if (error.code === 'WEAK_PASSWORD') fields.password = error.message;
      if (error.code === 'INVALID_EMAIL') fields.email = error.message;
      if (Object.keys(fields).length) { setErrors(fields); focusFirst(fields, order); } else setFormError(error.message);
    } finally { setBusy(false); }
  }
  useEffect(() => { setErrors({}); setFormError(''); }, [register]);
  return <div className={s.authPage}>
    <PageFocus title={register ? 'Регистрация' : 'Вход'} />
    <section className={s.authIntro} aria-label="О сервисе">
      <div className={s.authBrand}><span><Icon name="layers" size={22} /></span><strong>Подбор контрагентов</strong></div>
      <div className={s.authCopy}><p className={s.authLead}>Кандидаты в поставщики по вашим закупкам - с основаниями по каждой позиции.</p><ul><li><Icon name="upload" />Загрузите два CSV: закупки и позиции</li><li><Icon name="list" />Проверьте, на чём основан каждый кандидат</li><li><Icon name="lock" />Запросы и результаты видны только вам</li></ul></div>
      <span className={s.team}>{TEAM_NAME}</span>
    </section>
    <main className={s.authMain}>
      <div className={s.authForm}>
        <h1 tabIndex={-1}>{register ? 'Создать аккаунт' : 'Вход'}</h1>
        <p className={s.authSub}>{register ? 'Аккаунт хранит ваши закупки, результаты подбора и статистику.' : 'Войдите, чтобы продолжить работу с закупками.'}</p>
        {auth.expired && !register && <Alert tone="warning" title="Сессия завершилась">Войдите снова - вы вернётесь на страницу, где были.</Alert>}
        <form onSubmit={submit} noValidate>
          {register && <Input label="Имя" name="name" autoComplete="name" value={name} onChange={setName} maxLength={100} required error={errors.name} inputRef={nameRef} />}
          <Input label="Электронная почта" name="email" type="email" inputMode="email" autoComplete={register ? 'email' : 'username'} value={email} onChange={setEmail} maxLength={254} required error={errors.email} inputRef={emailRef} />
          <PasswordInput label="Пароль" name="password" autoComplete={register ? 'new-password' : 'current-password'} value={password} onChange={setPassword} maxLength={128} required error={errors.password} inputRef={passwordRef} hint={register ? <PasswordRules id="register-rules" password={password} email={email} name={name} /> : undefined} />
          {formError && <Alert tone="error" title={register ? 'Не удалось создать аккаунт' : 'Не удалось войти'}>{formError}</Alert>}
          <Button type="submit" busy={busy} wide>{register ? 'Создать аккаунт' : 'Войти'}</Button>
        </form>
        <p className={s.authSwitch}>{register ? 'Уже есть аккаунт?' : 'Нет аккаунта?'} <Link to={register ? '/login' : '/register'}>{register ? 'Войти' : 'Зарегистрироваться'}</Link></p>
      </div>
    </main>
  </div>;
}

/** Личный кабинет: имя аккаунта, смена пароля с проверкой требований и выход. */
export function Account() {
  const auth = useAuth(), app = useApp();
  const [name, setName] = useState(auth.user?.name ?? ''), [current, setCurrent] = useState(''), [password, setPassword] = useState(''), [repeat, setRepeat] = useState(''), [busy, setBusy] = useState(''), [errors, setErrors] = useState<Errors>({}), [formError, setFormError] = useState<{ form: string; text: string } | null>(null);
  const nameRef = useRef<HTMLInputElement>(null), currentRef = useRef<HTMLInputElement>(null), newRef = useRef<HTMLInputElement>(null), repeatRef = useRef<HTMLInputElement>(null);
  async function saveName(e: FormEvent) {
    e.preventDefault(); setFormError(null);
    if (!name.trim()) { setErrors({ name: 'Имя не может быть пустым.' }); nameRef.current?.focus(); return; }
    setErrors({}); setBusy('profile');
    try { const data = await request<{ user: User }>('/auth/profile', { method: 'PATCH', body: { name: name.trim() } }); auth.accept(data.user); app.toast('Имя сохранено.', 'success'); }
    catch (err) { const error = err as ApiError; if (error.fields?.name) { setErrors({ name: error.fields.name }); nameRef.current?.focus(); } else setFormError({ form: 'profile', text: error.message }); }
    finally { setBusy(''); }
  }
  async function changePassword(e: FormEvent) {
    e.preventDefault(); setFormError(null);
    const local: Errors = {};
    if (!current) local.current = 'Введите текущий пароль.';
    if (passwordRules(password, auth.user?.email, auth.user?.name).some(rule => rule.met === false)) local.password = 'Новый пароль не соответствует требованиям ниже.';
    if (password && repeat !== password) local.repeat = 'Пароли не совпадают. Введите новый пароль ещё раз.';
    setErrors(local); if (Object.keys(local).length) { focusFirst(local, [['current', currentRef], ['password', newRef], ['repeat', repeatRef]]); return; }
    setBusy('password');
    try { await request('/auth/password', { method: 'POST', body: { currentPassword: current, newPassword: password } }); resetCSRF(); setCurrent(''); setPassword(''); setRepeat(''); app.toast('Пароль изменён. Сессия на этом устройстве сохранена.', 'success'); }
    catch (err) {
      const error = err as ApiError, fields: Errors = {};
      if (error.code === 'INVALID_PASSWORD') fields.current = 'Текущий пароль неверен.';
      else if (error.code === 'WEAK_PASSWORD' || error.code === 'PASSWORD_UNCHANGED') fields.password = error.message;
      if (Object.keys(fields).length) { setErrors(fields); focusFirst(fields, [['current', currentRef], ['password', newRef]]); } else setFormError({ form: 'password', text: error.message });
    } finally { setBusy(''); }
  }
  async function logout() { setBusy('logout'); try { await auth.logout(); navigate('/login', { replace: true }); } catch (e) { setFormError({ form: 'logout', text: (e as Error).message }); setBusy(''); } }
  return <>
    <PageHeader title="Личный кабинет" subtitle={`Вы вошли как ${auth.user?.email ?? ''}`} actions={<Button variant="secondary" icon="logout" busy={busy === 'logout'} onClick={() => void logout()}>Выйти</Button>} />
    {formError?.form === 'logout' && <Alert tone="error" title="Не удалось выйти">{formError.text}</Alert>}
    <div className={s.accountGrid}>
      <Card className={s.accountCard}><h2>Профиль</h2><form onSubmit={saveName} noValidate><Input label="Имя" value={name} onChange={setName} maxLength={100} required error={errors.name} inputRef={nameRef} autoComplete="name" /><Input label="Электронная почта" value={auth.user?.email ?? ''} onChange={() => undefined} disabled hint="Адрес используется для входа и не меняется." />{formError?.form === 'profile' && <Alert tone="error" title="Имя не сохранено">{formError.text}</Alert>}<div><Button type="submit" busy={busy === 'profile'} disabled={Boolean(busy)}>Сохранить имя</Button></div></form></Card>
      <Card className={s.accountCard}><h2>Смена пароля</h2><form onSubmit={changePassword} noValidate><PasswordInput label="Текущий пароль" value={current} onChange={setCurrent} autoComplete="current-password" maxLength={128} required error={errors.current} inputRef={currentRef} /><PasswordInput label="Новый пароль" value={password} onChange={setPassword} autoComplete="new-password" maxLength={128} required error={errors.password} inputRef={newRef} hint={<PasswordRules id="account-rules" password={password} email={auth.user?.email} name={auth.user?.name} />} /><PasswordInput label="Повторите новый пароль" value={repeat} onChange={setRepeat} autoComplete="new-password" maxLength={128} required error={errors.repeat} inputRef={repeatRef} />{formError?.form === 'password' && <Alert tone="error" title="Пароль не изменён">{formError.text}</Alert>}<div><Button type="submit" variant="secondary" busy={busy === 'password'} disabled={Boolean(busy)}>Изменить пароль</Button></div></form></Card>
    </div>
  </>;
}
