export const MIN_PASSWORD = 15;

/**
 * Проверяемые до отправки требования к паролю, совпадающие с валидаторами сервера.
 * Распространённость пароля и похожесть на имя сервер проверяет окончательно; здесь отмечается явное совпадение.
 * @returns список требований с признаком выполнения (`null` - проверит сервер).
 */
export function passwordRules(password: string, email = '', name = ''): { text: string; met: boolean | null }[] {
  const lower = password.toLowerCase(), local = email.split('@')[0]?.toLowerCase() ?? '', person = name.trim().toLowerCase();
  const similar = (local.length >= 3 && lower.includes(local)) || (person.length >= 3 && lower.includes(person));
  return [
    { text: `Не короче ${MIN_PASSWORD} символов (сейчас ${password.length})`, met: password.length >= MIN_PASSWORD },
    { text: 'Не только из цифр', met: password.length ? !/^\d+$/.test(password) : false },
    { text: 'Не содержит имя или адрес почты', met: password ? !similar : false },
    { text: 'Не из списка распространённых паролей - проверим при отправке', met: null },
  ];
}
