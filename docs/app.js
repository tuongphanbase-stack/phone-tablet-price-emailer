// Phone & tablet price dashboard: reads latest.json and models.json written
// by phone_tablet_price_emailer.py and shows a searchable comparison.
const PAGE = 40;
const $ = (s) => document.querySelector(s);
const vnd = (n) => (n == null ? '—' : `${Number(n).toLocaleString('vi-VN')} ₫`);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fold = (s) => String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd').toLowerCase();
let models = [];
let shown = PAGE;

function chart(history) {
  if (!history || history.length < 2) return '';
  const pts = history.map(([d, p]) => [new Date(d).getTime(), p]);
  const xs = pts.map((p) => p[0]); const ys = pts.map((p) => p[1]);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const W = 600; const H = 110; const pad = 6;
  const sx = (x) => pad + ((x - x0) / (x1 - x0 || 1)) * (W - 2 * pad);
  const sy = (y) => H - pad - ((y - y0) / (y1 - y0 || 1)) * (H - 2 * pad);
  // Step line: a price holds until the next change.
  let d = `M${sx(pts[0][0])},${sy(pts[0][1])}`;
  for (let i = 1; i < pts.length; i += 1) d += `H${sx(pts[i][0])}V${sy(pts[i][1])}`;
  d += `H${W - pad}`;
  return `<div class="chart"><div class="sub">Giá rẻ nhất theo ngày · thấp nhất ${vnd(y0)} · cao nhất ${vnd(y1)}</div>
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Biểu đồ giá"><path d="${d}" fill="none" stroke="currentColor" stroke-width="2" vector-effect="non-scaling-stroke"/></svg></div>`;
}

function card(m) {
  const best = m.offers[0]; const worst = m.offers[m.offers.length - 1];
  const rows = m.offers.map((o) => `<tr><td>${o.url ? `<a href="${esc(o.url)}" target="_blank" rel="noopener">${esc(o.shop_name)}</a>` : esc(o.shop_name)}<div class="sub">${esc(o.name)}</div></td>
    <td class="p">${o.old_price ? `<span class="old">${vnd(o.old_price)}</span>` : ''}${vnd(o.price)}</td></tr>`).join('');
  return `<article class="model"><button type="button" aria-expanded="false">
      <h3>${esc(m.model)}</h3><div class="best">${vnd(best.price)}</div>
      <div class="sub">${m.offers.length} cửa hàng · ${m.category === 'tablet' ? 'Máy tính bảng' : 'Điện thoại'}</div>
      <div class="sub r">${m.offers.length > 1 ? `rẻ nhất ở ${esc(best.shop_name)} · chênh ${vnd(worst.price - best.price)}` : esc(best.shop_name)}</div>
    </button><div class="offers"><table>${rows}</table>${chart(m.history)}</div></article>`;
}

function render() {
  const q = fold($('#q').value.trim()).split(/\s+/).filter(Boolean);
  const cat = $('#cat').value; const multi = $('#multi').checked; const sort = $('#sort').value;
  let list = models.filter((m) => (!cat || m.category === cat) && (!multi || m.offers.length > 1)
    && q.every((w) => fold(`${m.model} ${m.offers.map((o) => o.name).join(' ')}`).includes(w)));
  const spread = (m) => m.offers[m.offers.length - 1].price - m.offers[0].price;
  const sorters = {
    shops: (a, b) => b.offers.length - a.offers.length || spread(b) - spread(a),
    spread: (a, b) => spread(b) - spread(a),
    low: (a, b) => a.offers[0].price - b.offers[0].price,
    high: (a, b) => b.offers[0].price - a.offers[0].price,
  };
  list = list.sort(sorters[sort]);
  $('#count').textContent = `${list.length} model`;
  $('#list').innerHTML = list.slice(0, shown).map(card).join('') || '<p class="muted">Không có model nào khớp.</p>';
  $('#more').hidden = list.length <= shown;
}

async function load() {
  const get = async (f) => { try { return await (await fetch(f, { cache: 'no-store' })).json(); } catch (e) { return null; } };
  const [latest, data] = await Promise.all([get('latest.json'), get('models.json')]);
  if (!latest || !latest.updated_at) {
    $('#updated').textContent = 'Chưa có dữ liệu: workflow "Send phone & tablet prices" chưa chạy lần nào.';
    return;
  }
  $('#updated').textContent = `Cập nhật ${new Date(latest.updated_at).toLocaleString('vi-VN')}`;
  $('#items').textContent = latest.item_count.toLocaleString('vi-VN');
  $('#models').textContent = (data?.models || []).filter((m) => m.offers.length > 1).length.toLocaleString('vi-VN');
  const shops = latest.shops || [];
  $('#shopsOk').textContent = `${shops.filter((s) => s.status !== 'failed').length} / ${shops.length}`;
  $('#shops').innerHTML = shops.map((s) => `<div class="shop-row"><span>${esc(s.name)}</span><span class="${s.status === 'failed' ? 'bad' : ''}">${s.status === 'failed' ? 'lỗi' : `${s.count} sản phẩm`}</span></div>`).join('');
  models = data?.models || [];
  render();
}

['#q', '#cat', '#sort', '#multi'].forEach((s) => $(s).addEventListener('input', () => { shown = PAGE; render(); }));
$('#more').addEventListener('click', () => { shown += PAGE; render(); });
$('#list').addEventListener('click', (e) => {
  const btn = e.target.closest('.model>button');
  if (!btn) return;
  const open = btn.parentElement.classList.toggle('open');
  btn.setAttribute('aria-expanded', open);
});
load();
