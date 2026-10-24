// Сбор данных Coupang через Claude in Chrome (javascript_tool). Только чтение, страницы не открываются:
// поиск и карточки товаров загружаются в фоне (fetch) с открытой вкладки coupang.com, с паузами как у человека.
// Вкладка — https://www.coupang.com/robots.txt: тот же сайт и вход, но другие расширения (Itemscout) туда не встраиваются.
// 1) На этой вкладке выполнить целиком один раз coupang_parse.js (разбор страниц, лимит), затем этот файл (kf_pack, kf_run, kf_next).
// 2) kf_run(["слово", …], download) — сбор всех слов в фоне; await kf_next() — результат следующего слова
//    («FILE pack_<номер>.txt» и строки ниже; ответ инструмента обрезается после ~1000 символов, поэтому по одному слову),
//    «WAIT» — ещё собирается, «DONE» — всё. download — в конце скачать coupang_result.txt (онлайн-версия).
// 3) await kf_pack(["слово"]) → строки через \n:
//    «S|слово|товаров|органических|ср.цена топ-10|ср.отзывы топ-10|макс.отзывы топ-10|подходящих в топ-20|Rocket %|реклама|товары»,
//      «подходящие» — отзывов ≤170 и цена 12 000–60 000 ₩; «товары» — лучшие из них, если слово подтверждено:
//      id~цена~отзывы~название~синяя ракета (1/0) через «;»; товары с синей ракетой и товары, у которых цена на их странице
//      меньше 10 000 ₩, пропускаются. Слово не подтверждается, если синяя ракета у 70% выдачи и больше.
//      Rocket — только синяя ракета самого Coupang (로켓배송); Rocket продавца (판매자로켓, rocket_merchant) не считается.
//    «D|id|크기/무게 из «필수 표기 정보» или вариант «사이즈»|покупки|цена на странице товара» — для лучших товаров;
//    «ERROR|причина» — блокировка (Access Denied, проверка на бота, пустая выдача, вход) или дневной лимит: сбор остановлен.
// Против блокировки: пауза 5–10 с между страницами, перерыв 1–2 минуты после каждых 10 новых слов, не больше 3 карточек
// на слово, не больше kf_rules.DAILY_CAP новых слов в день (вместе с ручной проверкой закладкой). Ответ по слову хранится
// 3 дня в localStorage coupang.com этого Chrome: повторная проверка запросов не шлёт и лимит не тратит. Числа правил — в coupang_parse.js.

// Таймер — в Worker: в фоновой вкладке Chrome обычный setTimeout может «спать» до минуты, а таймеры Worker не тормозятся.
// Ждать могут сразу двое (сбор и kf_next), поэтому у каждого ожидания свой номер
window.kf_clock = window.kf_clock || new Worker(URL.createObjectURL(new Blob(['onmessage = e => setTimeout(() => postMessage(e.data.id), e.data.ms)'], { type: 'text/javascript' })));
window.kf_waits = window.kf_waits || {};
kf_clock.onmessage = e => { kf_waits[e.data]?.(); delete kf_waits[e.data]; };
window.kf_sleep = ms => new Promise(r => { const id = Math.random(); kf_waits[id] = r; kf_clock.postMessage({ id, ms }); });

window.kf_pack = async (words) => {
  const { MIN_PAGE_PRICE, BEST } = kf_rules;
  const CACHE_DAYS = 3, CACHE_VER = 1, REST_EVERY = 10;  // CACHE_VER — поднять при смене правил, чтобы старые ответы не брались
  const pause = () => kf_sleep(5000 + Math.random() * 5000);
  const cacheKey = word => 'kf_cache:' + word;
  const cacheGet = word => {
    try {
      const c = JSON.parse(localStorage.getItem(cacheKey(word)));
      return c && c.v === CACHE_VER && Date.now() - c.t < CACHE_DAYS * 864e5 ? c.out : null;
    } catch (e) { return null; }
  };
  const cachePut = (word, out) => { try { localStorage.setItem(cacheKey(word), JSON.stringify({ v: CACHE_VER, t: Date.now(), out })); } catch (e) {} };
  const blocked = e => /Access Denied|ответил 403|войти|не отдал|проверку|лимит/.test(e.message);
  const load = async url => {
    const r = await fetch(url, { credentials: 'include' });
    const text = await r.text();
    const denied = /Access Denied/i.test(text.slice(0, 3000));
    if (r.status !== 200 || denied) throw new Error(`Coupang ответил ${r.status}${denied ? ' Access Denied' : ''}`);
    // Маленькая страница без корейского текста — проверка на бота вместо страницы: не обходим, останавливаемся
    if (!url.includes('/next-api/') && text.length < 20000 && !/[가-힣]/.test(text)) throw new Error('Coupang включил проверку на бота — подождите 30–60 минут');
    return text;
  };
  const html = async url => new DOMParser().parseFromString(await load(url), 'text/html');

  const search = async word => kf_parseSearch(await html(`/np/search?q=${encodeURIComponent(word)}&listSize=36`), word);

  const detail = async p => {
    // Цена по прямой ссылке меньше 10 000 ₩ — дальше не смотрим
    const { price, buy, leaves } = kf_parseProduct(await html(`/vp/products/${p.id}`));
    if (price !== '' && price < MIN_PAGE_PRICE) return { price, line: '' };
    // «필수 표기 정보» страница подгружает отдельным запросом — берём его же
    let spec = '';
    if (p.itemId && p.vendorItemId) {
      try {
        const j = JSON.parse(await load(`/next-api/products/btf?productId=${p.id}&itemId=${p.itemId}&vendorItemId=${p.vendorItemId}`));
        spec = (j.essentials || []).filter(e => /크기|중량|무게|치수|사이즈/.test(e.title || '')).map(e => `${e.title}: ${e.description}`).join('; ');
      } catch (e) { if (blocked(e)) throw e; }
    }
    if (!spec || /참조/.test(spec)) spec = kf_sizeOption(leaves) || spec;
    return { price, line: kf_detailLine(p.id, spec, buy, price) };
  };

  const out = [];
  try {
    for (const word of words) {
      const cached = cacheGet(word);
      if (cached) {
        out.push(cached);
        continue;
      }
      if (!kf_dayUse(word)) throw new Error(kf_limitText());
      // Перерыв после каждых REST_EVERY слов, проверенных на Coupang (слова из кэша не считаются)
      window.kf_fresh = (window.kf_fresh || 0) + 1;
      if (kf_fresh > 1 && kf_fresh % REST_EVERY === 1) {
        window.kf_note?.('Перерыв 1–2 минуты против блокировки Coupang…');
        await kf_sleep(60000 + Math.random() * 60000);
      }
      const { fields, candidates } = await search(word);
      await pause();
      // Лучшие: до BEST кандидатов по порядку, без тех, у которых цена на странице товара меньше 10 000 ₩
      const best = [], details = [];
      for (const p of candidates.slice(0, BEST)) {
        const d = await detail(p).catch(e => { if (blocked(e)) throw e; return { price: '', line: `D|${p.id}||` }; });
        await pause();
        if (d.price !== '' && d.price < MIN_PAGE_PRICE) continue;
        best.push(p);
        details.push(d.line);
      }
      const lines = [kf_searchLine(fields, best), ...details];
      cachePut(word, lines.join('\n'));
      out.push(...lines);
    }
  } catch (e) {
    out.push(`ERROR|${kf_clean(e.message)}`);
  }
  return out.join('\n');
};

// Сбор всех слов в фоне: ответ сразу, ход виден на самой вкладке. Результаты по словам забирает kf_next (агент Claude Code),
// а при download в конце скачивается coupang_result.txt (онлайн-версия). Кнопка на вкладке сохраняет и неполный результат.
window.kf_run = (words, download = true) => {
  const lines = [];
  window.kf_queue = [];
  window.kf_finished = false;
  document.body.innerHTML = '';
  document.body.style.font = '16px sans-serif';
  const status = document.body.appendChild(document.createElement('h2'));
  const note = document.body.appendChild(document.createElement('p'));
  const save = document.body.appendChild(document.createElement('button'));
  save.textContent = 'Скачать coupang_result.txt';
  const saveFile = () => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/plain' }));
    a.download = 'coupang_result.txt';
    a.click();
  };
  save.onclick = saveFile;
  window.kf_note = t => { note.textContent = t; };
  (async () => {
    for (const [i, word] of words.entries()) {
      status.textContent = `Coupang: слово ${i + 1} из ${words.length} — ${word}. Не закрывайте вкладку.`;
      note.textContent = '';
      const out = await kf_pack([word]);
      lines.push(out);
      kf_queue.push(`FILE pack_${i + 1}.txt\n${out}`);
      if (out.includes('ERROR|')) break;
    }
    const err = lines.join('\n').match(/ERROR\|(.*)/);
    status.textContent = err ? `Остановлено: ${err[1]}. Проверенные слова сохранены.` : `Готово: ${words.length} слов.`;
    note.textContent = download ? 'Загрузите coupang_result.txt в приложение.' : '';
    kf_finished = true;
    if (download) saveFile();
  })();
  return 'started';
};

// Результат следующего слова; ждёт до 15 секунд, чтобы вызов инструмента не упирался в тайм-аут
window.kf_next = async () => {
  for (let i = 0; i < 15 && !kf_queue.length && !kf_finished; i++) await kf_sleep(1000);
  return kf_queue.length ? kf_queue.shift() : kf_finished ? 'DONE' : 'WAIT';
};

'ok';
