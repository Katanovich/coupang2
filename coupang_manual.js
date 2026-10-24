// Закладка ручной проверки (выполняется после coupang_parse.js, оба файла — в одной закладке).
// Вы сами открываете на Coupang поиск по слову или страницу товара и нажимаете закладку: она читает уже открытую страницу,
// ничего не загружает и копит строки «S|…» (поиск) и «D|…» (товар) в localStorage coupang.com этого Chrome.
// Кнопка панели скачивает coupang_result.txt — его принимает приложение. Новые слова тратят общий дневной лимит kf_rules.DAILY_CAP.

const KEY = 'kf_manual';
let store;
try { store = JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { store = {}; }
store.S = store.S || {};
store.D = store.D || {};
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(store)); } catch (e) {} };
const num = n => n === '' || n == null ? '—' : Number(n).toLocaleString('ru-RU').replace(/\s/g, ' ');

// «필수 표기 정보»: ячейка-заголовок «크기 / 중량 …» и значение рядом (таблица появляется, когда до неё прокрутили)
const pageSpec = () => [...document.querySelectorAll('th, dt')]
  .map(el => [(el.textContent || '').replace(/\s+/g, ' ').trim(), (el.nextElementSibling?.textContent || '').replace(/\s+/g, ' ').trim()])
  .filter(([t, v]) => /^(크기|중량|무게|치수|사이즈)/.test(t) && t.length < 40 && v)
  .map(([t, v]) => `${t}: ${v}`).join('; ');

const url = new URL(location.href);
let msg = '', note = '', links = [];
try {
  if (url.pathname.startsWith('/np/search')) {
    const word = (url.searchParams.get('q') || '').trim();
    if (!word) throw new Error('В адресе страницы нет слова поиска');
    const r = kf_parseSearch(document, word);
    if (!store.S[word] && !kf_dayUse(word)) throw new Error(kf_limitText() + '. Слово не записано');
    const best = r.candidates.slice(0, kf_rules.BEST);
    store.S[word] = kf_searchLine(r.fields, best);
    save();
    msg = `«${word}» записано: ${r.confirmed ? '✅ подтверждено' : '❌ не подтверждено'} — подходящих товаров в топ-20: ${r.fields[6]}, Rocket ${num(r.fields[7])}%.`;
    if (best.length) {
      note = 'Откройте каждый товар и на его странице снова нажмите закладку — запишутся покупки, вес и габарит:';
      links = best.map(p => ({
        href: `/vp/products/${p.id}` + (p.itemId ? `?itemId=${p.itemId}&vendorItemId=${p.vendorItemId}` : ''),
        text: `${store.D[p.id] ? '✓ ' : ''}${p.title} — ${num(p.price)} ₩, отзывов ${num(p.rev)}`,
      }));
    }
  } else if (/^\/vp\/products\/\d+/.test(url.pathname)) {
    const id = url.pathname.match(/products\/(\d+)/)[1];
    const { price, buy, leaves } = kf_parseProduct(document);
    let spec = pageSpec();
    if (!spec || /참조/.test(spec)) spec = kf_sizeOption(leaves) || spec;
    store.D[id] = kf_detailLine(id, spec, buy, price);
    save();
    msg = `Товар ${id} записан: цена ${num(price)} ₩, ${buy || 'покупки не указаны'}.`;
    note = spec ? `Размер и вес: ${spec}` : 'Вес и габарит не найдены. Прокрутите страницу до «필수 표기 정보» и нажмите закладку ещё раз.';
    if (price !== '' && price < kf_rules.MIN_PAGE_PRICE) note += ' Дешевле 10 000 ₩ — в лучшие товары не попадёт.';
  } else {
    msg = 'Откройте на Coupang поиск по слову (ссылки — в приложении) или страницу товара и нажмите закладку.';
  }
} catch (e) {
  msg = '⚠ ' + e.message;
}

// Панель поверх страницы, в Shadow DOM — стили Coupang её не трогают
document.getElementById('kf-panel')?.remove();
const host = document.body.appendChild(document.createElement('div'));
host.id = 'kf-panel';
host.style.cssText = 'position:fixed;top:16px;right:16px;z-index:2147483647';
const root = host.attachShadow({ mode: 'open' });
const el = (tag, text, parent = box) => { const e = parent.appendChild(document.createElement(tag)); if (text) e.textContent = text; return e; };
el('style', ':host{all:initial}div.box{font:14px/1.45 -apple-system,sans-serif;color:#111;background:#fff;border:2px solid #e3342f;'
  + 'border-radius:10px;padding:12px 14px;width:340px;box-shadow:0 6px 24px #0003}h3{margin:0 0 6px;font-size:15px}p{margin:6px 0}'
  + 'a{color:#0a58ca;display:block;margin:4px 0}button{font:inherit;margin:8px 6px 0 0;padding:5px 10px;border-radius:6px;border:1px solid #999;'
  + 'background:#f4f4f4;cursor:pointer}button.main{background:#e3342f;color:#fff;border-color:#e3342f}.x{position:absolute;top:4px;right:6px;'
  + 'border:0;background:none;font-size:18px;margin:0}.muted{color:#666;font-size:12px}', root);
const box = el('div', '', root);
box.className = 'box';
el('button', '×').className = 'x';
box.querySelector('.x').onclick = () => host.remove();
el('h3', 'Проверка Coupang вручную');
el('p', msg);
if (note) el('p', note);
for (const l of links) Object.assign(el('a', l.text), { href: l.href, target: '_blank' });
const words = Object.keys(store.S).length, items = Object.keys(store.D).length;
el('p', `Сегодня новых слов: ${kf_dayWords().length} из ${kf_rules.DAILY_CAP} · записано слов ${words}, товаров ${items}`).className = 'muted';
const dl = el('button', 'Скачать coupang_result.txt');
dl.className = 'main';
dl.onclick = () => {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([[...Object.values(store.S), ...Object.values(store.D)].join('\n')], { type: 'text/plain' }));
  a.download = 'coupang_result.txt';
  a.click();
};
const clear = el('button', 'Очистить');
clear.onclick = () => {
  if (clear.dataset.sure) {
    localStorage.removeItem(KEY);
    host.remove();
  } else {
    clear.dataset.sure = 1;
    clear.textContent = 'Точно очистить всё?';
  }
};
