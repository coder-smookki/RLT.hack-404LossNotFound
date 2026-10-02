import { useEffect } from 'react';
import { PageHeader, Card, ButtonLink, Disclosure, TextLink } from '../components/ui.js';
import { NOTICE_COLUMNS, ITEM_COLUMNS } from '../domain/csv.js';
import { config } from '../app/config.js';
import { downloadTemplate } from './Search.js';
import s from '../styles/pages.module.css';

const STEPS = [
  ['Загрузите два CSV', 'Файл закупок и файл позиций (ТРУ). Порядок не важен - тип определяется по колонкам.'],
  ['Проверьте файлы', 'Увидите число закупок и позиций, ошибки с номером строки и способом исправления.'],
  ['Запустите подбор', 'Каждая закупка обрабатывается отдельно. Готовые можно открывать, не дожидаясь остальных.'],
  ['Изучите кандидатов', 'Откройте компанию: основания по позициям, источники, история участия, что уточнить.'],
] as const;

/** Справка: короткий сценарий, как читать основания, формат CSV с шаблонами и решения частых проблем. */
export function Help() {
  useEffect(() => { if (location.hash === '#csv') requestAnimationFrame(() => document.getElementById('csv')?.scrollIntoView()); }, []);
  return <>
    <PageHeader title="Как пользоваться" subtitle="От загрузки файлов до проверки кандидата - четыре шага." actions={<ButtonLink to="/search" icon="upload">Загрузить файлы</ButtonLink>} />
    <ol className={s.steps}>{STEPS.map(([title, text], i) => <li key={title}><span className={s.stepNo}>{i + 1}</span><div><h2>{title}</h2><p className={s.muted}>{text}</p></div></li>)}</ol>

    <Card className={[s.padded, s.block].join(' ')}>
      <h2>Как читать основания</h2>
      <dl className={s.glossary}>
        <div><dt>Есть опыт похожих закупок</dt><dd>Компания участвовала в закупках с похожими позициями. Участие не означает исполненный договор.</dd></div>
        <div><dt>Есть сведения в источниках компании</dt><dd>На известном системе сайте или в реестре есть фрагмент, связанный с позицией. Наличие и цена не подтверждены.</dd></div>
        <div><dt>Есть подтверждённые совпадения характеристик</dt><dd>Явно указанные характеристики совпали. Это не подтверждает всю позицию.</dd></div>
        <div><dt>Противоречия в характеристиках</dt><dd>Характеристики в источнике расходятся с закупкой. Проверьте до обращения.</dd></div>
        <div><dt>Нужно уточнить характеристики</dt><dd>Подтверждённых совпадений нет - уточните у компании.</dd></div>
      </dl>
      <p className={s.muted}>Место в списке - порядок проверки, а не вероятность успешной поставки и не оценка надёжности. Юридический статус, исполнение договоров, финансы и реестр недобросовестных поставщиков система не проверяет. Дата получения страницы не равна дате её содержания; 36 месяцев - ориентир актуальности, а не жёсткий фильтр.</p>
    </Card>

    <Card className={[s.padded, s.block].join(' ')}>
      <h2 id="csv" tabIndex={-1}>Формат файлов</h2>
      <p>CSV в кодировке UTF-8, разделитель «;» или «,», до {config.maxCSVMB} МБ на файл, до 100 закупок и 10 000 позиций за загрузку. Нужны все колонки схемы, порядок любой. Файлы связываются по <code>lot_id</code>.</p>
      <div className={s.twoColumns}>
        <div className={s.stackSm}><h3>Файл закупок</h3><code className={s.codeBlock}>{NOTICE_COLUMNS.join('; ')}</code><TextLink icon="download" onClick={() => downloadTemplate('notices')}>Шаблон закупок</TextLink></div>
        <div className={s.stackSm}><h3>Файл позиций (ТРУ)</h3><code className={s.codeBlock}>{ITEM_COLUMNS.join('; ')}</code><TextLink icon="download" onClick={() => downloadTemplate('items')}>Шаблон позиций</TextLink></div>
      </div>
      <p className={s.muted}>Номера и ИНН сохраняются как текст: ведущие нули и повторяющиеся позиции не теряются. Таблицы Excel и PDF не поддерживаются - сохраните их как CSV.</p>
    </Card>

    <section className={s.block} aria-labelledby="faq"><h2 id="faq" className={s.groupTitle}>Частые проблемы</h2><Card as="div" className={s.faq}>
      <Disclosure summary="«Кодировка не UTF-8»"><p>Откройте файл в Excel или LibreOffice и сохраните как «CSV UTF-8 (разделитель - точка с запятой)».</p></Disclosure>
      <Disclosure summary="«Не удалось определить таблицу по колонкам»"><p>Названия колонок должны точно совпадать со схемой выше. Скачайте шаблон и перенесите данные в него.</p></Disclosure>
      <Disclosure summary="«Оба файла - файлы закупок»"><p>Выбраны два файла одного типа. Нужен один файл закупок и один файл позиций.</p></Disclosure>
      <Disclosure summary="Сессия завершилась"><p>Войдите снова - вы вернётесь на ту же страницу. Загруженные закупки и результаты сохранены в аккаунте.</p></Disclosure>
      <Disclosure summary="Подбор не завершён"><p>Откройте закупку и нажмите «Запустить ещё раз». Исходные данные сохраняются, повтор не создаёт дубликатов.</p></Disclosure>
    </Card></section>
  </>;
}
