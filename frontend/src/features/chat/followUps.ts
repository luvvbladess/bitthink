export type FollowUpChip = { label: string; text: string };
export type FollowUpMode = 'auto' | 'computer' | 'studio' | 'search' | 'research' | 'astra' | 'docgen';

export function followUpMode(selected?: string | null): FollowUpMode {
  if (selected === 'director') return 'computer';
  if (selected === 'studio') return 'studio';
  if (selected === 'docgen') return 'docgen';
  if (selected === 'gpt-6-astra') return 'astra';
  if (selected === 'kimi-k2.6') return 'search';
  if (selected === 'gpt-5.6-sol' || selected === 'gpt-5.6-sol-pro' || selected === 'gpt-5.6-terra') {
    return 'research';
  }
  return 'auto';
}

export function followUpChips(
  userText: string,
  assistantText: string,
  mode: FollowUpMode,
  hasCanvas = false,
): FollowUpChip[] {
  const user = (userText || '').toLowerCase();
  const answer = (assistantText || '').trim();
  if (answer.length < 40) return [];

  if (mode === 'studio') {
    if (!hasCanvas) {
      return [
        {
          label: 'Собрать на холст',
          text: 'Собери презентацию на холст справа по файлам и брифу. Не пиши концепт текстом — нужен живой макет.',
        },
      ];
    }
    return [
      { label: 'Темнее шапка', text: 'Сделай шапку и фон темнее, контрастнее, без смены композиции' },
      { label: 'Другой стиль', text: 'Тот же материал, но другой визуальный мир. Не переписывай смысл.' },
      { label: 'Поправь слайд', text: 'Поправь текущий макет на холсте, не собирай заново. Напиши, какой слайд и что изменить.' },
    ];
  }

  if (mode === 'docgen') {
    // A follow-up chip here would launch another multi-hour, thousand-call run.
    return [];
  }

  if (/скил|запомни как скил|добавь скил|мои скил/.test(user)) {
    return [
      { label: 'Показать скилы', text: 'Покажи каталог скилов: общие и те, что сохранены для меня' },
      { label: 'Запомнить как скил', text: 'Запомни это как мой скил: имя латиницей, когда включать и правила работы' },
    ];
  }
  if (/фото|картин|где сня|локац|на снимк/.test(user)) {
    return [
      { label: 'Как добраться', text: 'Как туда добраться общественным транспортом и что ориентир у входа' },
      { label: 'Что рядом', text: 'Что посмотреть рядом в радиусе 15 минут пешком' },
    ];
  }
  if (mode === 'astra') {
    return [
      { label: 'Запусти в песочнице', text: 'Доведи это в песочнице: напиши файлы, запусти проверку и приложи артефакт на скачивание' },
      { label: 'Проверь кодом', text: 'Не описывай гипотезу – проверь скриптом в песочнице и покажи фактический вывод' },
    ];
  }
  if (/код|python|скрипт|ошибк|баг|функци/.test(user)) {
    return [
      { label: 'Проверки', text: 'Добавь проверки на ошибочный ввод и короткий пример запуска' },
      { label: 'По шагам', text: 'Разложи решение по шагам, где чаще ломается' },
    ];
  }
  if (/сравни|vs |что лучше|что выбрать/.test(user)) {
    return [
      { label: 'Что выбрать', text: 'Скажи, что выбрать в типичном случае и когда наоборот' },
      { label: 'Риски', text: 'Какие риски и скрытые ограничения у каждого варианта' },
    ];
  }
  if (mode === 'computer') {
    return [
      { label: 'Проверь ещё', text: 'Перепроверь вывод по первоисточнику и напиши, где сомнение' },
      { label: 'Следующий шаг', text: 'Что сделать дальше, чтобы довести это до рабочего результата' },
    ];
  }
  if (mode === 'search' || mode === 'research' || /новост|сейчас|актуаль|найд/.test(user)) {
    return [
      { label: 'Что изменилось', text: 'Что изменилось за последний месяц и на что смотреть дальше' },
      { label: 'Альтернативы', text: 'Какие есть близкие альтернативы и чем они хуже или лучше' },
    ];
  }
  return [
    { label: 'Чеклист', text: 'Собери короткий чеклист, что сделать с этим дальше' },
    { label: 'Главное', text: 'Разверни самый важный пункт и скажи, где обычно ошибаются' },
  ];
}
