/* Оплата баллами по QR клиента: живой расчёт «хватает / не хватает» и кнопка списания. */
(function () {
  var form = document.querySelector('[data-pay]');
  if (!form) return;
  var sel = form.querySelector('[name=item]'), qty = form.querySelector('[name=quantity]'),
      chk = form.querySelector('[name=check_amount]'), out = form.querySelector('[data-pay-result]'),
      btn = form.querySelector('[data-pay-submit]'), timer = form.querySelector('[data-pay-timer]');
  var fmt = function (n) { return Number(n).toLocaleString('ru-RU'); };
  var seq = 0, wait = null, expires = Date.now() + 10 * 60 * 1000;

  function opt() { return sel.options[sel.selectedIndex]; }
  function layout() {
    var o = opt(), type = o && o.getAttribute('data-type');
    form.querySelector('[data-pay-qty]').hidden = type !== 'unit';
    form.querySelector('[data-pay-check]').hidden = type !== 'check';
    if (type === 'unit') { qty.min = o.getAttribute('data-min'); qty.max = o.getAttribute('data-max'); }
    if (type === 'check') { chk.min = o.getAttribute('data-min'); chk.max = o.getAttribute('data-max');
      if (!chk.value) chk.value = o.getAttribute('data-price'); }
  }
  function show(html, cls) { out.hidden = false; out.className = 'pay-result ' + (cls || ''); out.innerHTML = html; }
  function quote() {
    btn.disabled = true;
    if (!sel.value) { out.hidden = true; btn.textContent = 'Списать баллы'; return; }
    var fd = new FormData(form), my = ++seq;
    if (opt().getAttribute('data-type') === 'unit') fd.delete('check_amount'); else fd.delete('quantity');
    fetch(form.getAttribute('data-quote-url'), { method: 'POST', body: fd, credentials: 'same-origin',
      headers: { 'X-CSRFToken': window.Panel.csrf() } })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (my !== seq) return;
        if (d.error) { show('<b>' + d.error.message + '</b>', 'bad'); return; }
        var sum = '<div class="pay-sum"><span>Итого</span><b class="tabular">' + fmt(d.total) + ' сом = ' + fmt(d.points) + ' баллов</b></div>';
        if (d.enough) {
          show(sum + '<div class="pay-status ok">Баллов хватает</div>', 'ok');
          btn.disabled = false; btn.textContent = 'Списать ' + fmt(d.points) + ' баллов';
        } else {
          var why = 'Не хватает ' + fmt(d.shortSom) + ' сом.';
          show(sum + '<div class="pay-status bad">Не хватает баллов — оплатите деньгами</div><div class="small">' + why + '</div>', 'bad');
          btn.textContent = 'Баллов недостаточно';
        }
      }).catch(function () { show('Не удалось проверить баллы, попробуйте ещё раз', 'bad'); });
  }
  function soon() { clearTimeout(wait); wait = setTimeout(quote, 250); }
  sel.addEventListener('change', function () { layout(); quote(); });
  qty.addEventListener('input', soon); chk.addEventListener('input', soon);
  form.addEventListener('submit', function (e) {
    if (btn.disabled) { e.preventDefault(); return; }
    btn.disabled = true; btn.textContent = 'Списываем…';
  });
  setInterval(function () {
    var left = Math.max(0, Math.round((expires - Date.now()) / 1000));
    timer.textContent = left ? 'QR действует ещё ' + Math.floor(left / 60) + ':' + String(left % 60).padStart(2, '0')
                             : 'Время вышло — отсканируйте QR ещё раз';
    if (!left) { btn.disabled = true; }
  }, 1000);
  layout();
})();
