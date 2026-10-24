// Разбор страниц Coupang — общий для сбора в фоне (coupang_snippet.js) и закладки ручной проверки (coupang_manual.js).
// Ничего не загружает: только читает переданный документ. Здесь же дневной лимит слов на Coupang.
// Числа совпадают с browser_agent.py: LOW_REVIEWS, PRICE_MIN/MAX, PAGE_PRICE_MIN, MIN_LOW_IN_TOP20, MAX_ROCKET, BEST_PER_WORD, DAILY_CAP.

window.kf_rules = { MIN_PRICE: 12000, MAX_PRICE: 60000, MIN_PAGE_PRICE: 10000, MAX_REV: 170, MIN_LOW: 5, MAX_ROCKET: 70, BEST: 3, DAILY_CAP: 20 };

window.kf_clean = s => s.replace(/[|;~\n]/g, ' ');
window.kf_leaves = root => [...root.querySelectorAll('*')].filter(e => e.childElementCount === 0 && !['SCRIPT', 'STYLE'].includes(e.tagName))
  .map(e => (e.textContent || '').replace(/\s+/g, ' ').trim()).filter(Boolean);

// Выдача поиска → поля строки «S|…» и кандидаты в лучшие (только если слово подтверждено)
window.kf_parseSearch = (doc, word) => {
  const R = kf_rules;
  if (doc.querySelector('input[type=password]')) throw new Error('Coupang просит войти');
  // Пустая страница без «검색결과가 없습니다» — Coupang временно не отдаёт выдачу (защита от частых запросов)
  if (!doc.querySelector('#product-list > li') && !/검색결과가 없/.test(doc.body?.textContent || ''))
    throw new Error('Coupang не отдал выдачу — защита от частых запросов, повторите позже');
  const items = [...doc.querySelectorAll('#product-list > li')].slice(0, 36).map(li => {
    const lines = kf_leaves(li);
    const srcs = [...li.querySelectorAll('img')].map(im => (im.getAttribute('src') || '') + ' ' + (im.getAttribute('data-src') || '')).join(' ');
    const prices = lines.filter(l => /^[\d,]+원$/.test(l)).map(l => +l.replace(/[,원]/g, ''));
    const rev = lines.join('\n').match(/\(([\d,]+)\)/);
    const href = li.querySelector('a')?.getAttribute('href') || '';
    const q = new URL(href, 'https://www.coupang.com').searchParams;
    const title = kf_clean(lines.find(l => l.length > 12 && !/원$|적립|도착|배송|쿠폰|할인|남음|구매|고객|추천/.test(l)) || '').slice(0, 30);
    return { price: prices.length ? prices[prices.length - 1] : null, rev: rev ? +rev[1].replace(/,/g, '') : 0,
             ad: lines.includes('광고'), rocket: /rocket/i.test(srcs.replace(/rocket_merchant/gi, '')),
             id: (href.match(/products\/(\d+)/) || [])[1] || '', itemId: q.get('itemId') || '', vendorItemId: q.get('vendorItemId') || '', title };
  });
  const org = items.filter(x => !x.ad), top10 = org.slice(0, 10), top20 = org.slice(0, 20);
  const avg = a => a.length ? Math.round(a.reduce((s, x) => s + x, 0) / a.length) : '';
  const good = top20.filter(x => x.rev <= R.MAX_REV && x.price >= R.MIN_PRICE && x.price <= R.MAX_PRICE);
  const seen = new Set(), uniq = good.filter(x => x.id && !seen.has(x.id) && seen.add(x.id));
  const rocket = items.length ? Math.round(100 * items.filter(x => x.rocket).length / items.length) : '';
  // Подтверждено так же, как в browser_agent.verdict; кандидаты в лучшие — без синей ракеты, с наибольшими отзывами
  const confirmed = good.length >= R.MIN_LOW && (rocket === '' || rocket < R.MAX_ROCKET);
  const fields = [word, items.length, org.length, avg(top10.map(x => x.price).filter(Boolean)), avg(top10.map(x => x.rev)),
    top10.length ? Math.max(...top10.map(x => x.rev)) : '', good.length, rocket, items.filter(x => x.ad).length];
  return { fields, confirmed, candidates: confirmed ? uniq.filter(x => !x.rocket).sort((a, b) => b.rev - a.rev) : [] };
};

// Строка «S|…»: поля выдачи и лучшие товары id~цена~отзывы~название~синяя ракета
window.kf_searchLine = (fields, best) =>
  ['S', ...fields, best.map(x => [x.id, x.price ?? '', x.rev, x.title, x.rocket ? 1 : 0].join('~')).join(';')].join('|');

// Карточка товара: итоговая цена (final-price-amount, иначе sales-price-amount), «N명 … 구매», листья текста
window.kf_parseProduct = doc => {
  const priceEl = doc.querySelector('.final-price-amount') || doc.querySelector('.sales-price-amount');
  const price = +((priceEl?.textContent || '').replace(/[^\d]/g, '')) || '';
  const leaves = kf_leaves(doc.body);
  const buy = (leaves.join(' ').match(/\d[\d,]*\s*명[^\d명]{0,12}구매/) || [''])[0];  // «100명 이상» и «구매» — бывают в разных элементах
  return { price, buy, leaves };
};

// Вариант «사이즈 …» в опциях товара — когда «필수 표기 정보» не даёт цифр
window.kf_sizeOption = leaves => {
  const oi = leaves.findIndex(c => /^사이즈/.test(c) && c.length < 60);
  return oi < 0 ? '' : leaves[oi].length < 12 ? leaves[oi] + ' ' + (leaves[oi + 1] || '') : leaves[oi];
};

// Строка «D|id|размер и вес|покупки|цена на странице»
window.kf_detailLine = (id, spec, buy, price) => ['D', id, kf_clean(spec).slice(0, 80), kf_clean(buy), price].join('|');

// Дневной лимит слов, проверенных на Coupang (общий для закладки и сбора в фоне; слова из кэша не считаются).
// Хранится в localStorage coupang.com: { d: дата, w: [слова за этот день] }; то же слово повторно лимит не тратит.
window.kf_today = () => { const t = new Date(); return `${t.getFullYear()}-${t.getMonth() + 1}-${t.getDate()}`; };
window.kf_dayWords = () => {
  try {
    const c = JSON.parse(localStorage.getItem('kf_day'));
    return c && c.d === kf_today() ? c.w : [];
  } catch (e) { return []; }
};
window.kf_dayUse = word => {
  const w = kf_dayWords();
  if (w.includes(word)) return true;
  if (w.length >= kf_rules.DAILY_CAP) return false;
  try { localStorage.setItem('kf_day', JSON.stringify({ d: kf_today(), w: [...w, word] })); } catch (e) {}
  return true;
};
window.kf_limitText = () => `Дневной лимит ${kf_rules.DAILY_CAP} слов на Coupang исчерпан — продолжите завтра`;

'ok';
