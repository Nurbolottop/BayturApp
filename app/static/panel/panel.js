/* BAYTUR panel — общие компоненты без библиотек. */
(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var NNBSP = ' ';

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    var i = $('input[name=csrfmiddlewaretoken]');
    return i ? i.value : '';
  }
  function fmt(n) {
    if (n === null || n === undefined || n === '') return '—';
    var neg = n < 0; n = Math.abs(Math.round(n));
    return (neg ? '−' : '') + String(n).replace(/\B(?=(\d{3})+(?!\d))/g, NNBSP);
  }
  window.Panel = { $: $, $$: $$, csrf: csrf, fmt: fmt, reduced: reduced };

  /* ---------------------------------------------------------------- тема */
  function currentTheme() {
    var t = document.documentElement.getAttribute('data-theme');
    if (t) return t;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  function syncThemeIcons() {
    $$('[data-theme-toggle]').forEach(function (b) { b.setAttribute('aria-pressed', currentTheme() === 'dark'); });
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-theme-toggle]');
    if (!b) return;
    var next = currentTheme() === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('panel-theme', next); } catch (err) {}
    syncThemeIcons();
  });
  syncThemeIcons();

  /* ---------------------------------------------------------------- сообщения */
  $$('.toast').forEach(function (t, i) {
    setTimeout(function () { t.classList.add('hide'); setTimeout(function () { t.remove(); }, 400); }, 4200 + i * 400);
    t.addEventListener('click', function () { t.remove(); });
  });
  window.Panel.toast = function (text, kind) {
    var box = $('.toasts'); if (!box) return;
    var t = document.createElement('div');
    t.className = 'toast ' + (kind || 'success');
    t.innerHTML = '<span class="ic-bubble">' + (kind === 'error' ? '!' : '✓') + '</span><span></span>';
    t.lastChild.textContent = text;
    box.appendChild(t);
    setTimeout(function () { t.classList.add('hide'); setTimeout(function () { t.remove(); }, 400); }, 4000);
  };

  /* ---------------------------------------------------------------- «набегающие» цифры */
  function countUp(el) {
    var target = parseFloat(el.getAttribute('data-countup'));
    if (isNaN(target) || reduced) return;
    var suffix = el.getAttribute('data-suffix') || '';
    var decimals = (el.getAttribute('data-countup').split('.')[1] || '').length;
    var start = performance.now(), dur = 380 + Math.min(500, Math.abs(target) > 1000 ? 500 : 200);
    function frame(now) {
      var p = Math.min(1, (now - start) / dur);
      var e = 1 - Math.pow(1 - p, 3);
      var v = target * e;
      el.textContent = (decimals ? v.toFixed(decimals).replace('.', ',') : fmt(v)) + suffix;
      if (p < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }
  $$('[data-countup]').forEach(countUp);

  /* ---------------------------------------------------------------- локализуемые поля */
  function markL10n(box) {
    $$('.l10n-pane', box).forEach(function (pane) {
      var input = $('input,textarea', pane);
      var btn = $('button[data-lang="' + pane.getAttribute('data-lang') + '"]', box);
      if (input && btn) btn.classList.toggle('empty', !input.value.trim());
    });
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('.l10n-tabs button');
    if (!b) return;
    var box = b.closest('.l10n'), lang = b.getAttribute('data-lang');
    $$('.l10n-tabs button', box).forEach(function (x) { x.classList.toggle('on', x === b); });
    $$('.l10n-pane', box).forEach(function (p) { p.classList.toggle('on', p.getAttribute('data-lang') === lang); });
    var inp = $('.l10n-pane.on input, .l10n-pane.on textarea', box);
    if (inp) inp.focus();
    document.dispatchEvent(new CustomEvent('panel:lang', { detail: lang }));
  });
  document.addEventListener('input', function (e) {
    var box = e.target.closest && e.target.closest('.l10n');
    if (box) markL10n(box);
  });
  $$('.l10n').forEach(function (box) {
    markL10n(box);
    // если в ru ошибка — открыть ru; если форма содержит ошибки в другом языке — пусто
  });
  window.Panel.switchLang = function (lang) {
    $$('.l10n').forEach(function (box) {
      $$('.l10n-tabs button', box).forEach(function (x) { x.classList.toggle('on', x.getAttribute('data-lang') === lang); });
      $$('.l10n-pane', box).forEach(function (p) { p.classList.toggle('on', p.getAttribute('data-lang') === lang); });
    });
  };

  /* ---------------------------------------------------------------- подтверждения */
  document.addEventListener('submit', function (e) {
    var f = e.target;
    var msg = f.getAttribute('data-confirm');
    if (msg && !window.confirm(msg)) { e.preventDefault(); return; }
    var btn = f.querySelector('button[type=submit],button:not([type])');
    if (btn && !f.hasAttribute('data-no-lock')) setTimeout(function () { btn.disabled = true; }, 0);
  }, true);

  /* ---------------------------------------------------------------- строки-ссылки */
  document.addEventListener('click', function (e) {
    var tr = e.target.closest('tr[data-href]');
    if (!tr || e.target.closest('a,button,input,form,select,label')) return;
    if (tr.hasAttribute('data-sheet')) { openSheet(tr.getAttribute('data-href')); return; }
    window.location = tr.getAttribute('data-href');
  });

  /* ---------------------------------------------------------------- боковая панель / нижний лист */
  var sheet = $('[data-sheet]'), backdrop = $('[data-sheet-backdrop]'), body = $('[data-sheet-body]');
  var lastFocus = null;
  function showSheet() {
    lastFocus = document.activeElement;
    sheet.hidden = false; backdrop.hidden = false;
    requestAnimationFrame(function () { sheet.classList.add('open'); backdrop.classList.add('open'); });
    document.body.style.overflow = 'hidden';
    setTimeout(function () { var f = $('[autofocus], input, button', body); if (f) f.focus(); }, 60);
  }
  function closeSheet() {
    if (!sheet || sheet.hidden) return;
    sheet.classList.remove('open'); backdrop.classList.remove('open');
    document.body.style.overflow = '';
    setTimeout(function () { sheet.hidden = true; backdrop.hidden = true; body.innerHTML = ''; }, reduced ? 0 : 380);
    if (lastFocus) lastFocus.focus();
  }
  function openSheet(url) {
    if (!sheet) { window.location = url; return; }
    fetch(url + (url.indexOf('?') >= 0 ? '&' : '?') + 'partial=1', { credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch' } })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) { body.innerHTML = html; showSheet(); document.dispatchEvent(new CustomEvent('panel:sheet', { detail: body })); })
      .catch(function () { window.location = url; });
  }
  window.Panel.openSheet = openSheet; window.Panel.closeSheet = closeSheet;
  document.addEventListener('click', function (e) {
    var a = e.target.closest('a[data-sheet]');
    if (a && window.innerWidth > 0) { e.preventDefault(); openSheet(a.getAttribute('href')); return; }
    if (e.target.closest('[data-sheet-close]') || e.target === backdrop) closeSheet();
    var m = e.target.closest('[data-open-menu]');
    if (m) { body.innerHTML = $('#menu-sheet').innerHTML; showSheet(); }
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeSheet(); });

  /* ---------------------------------------------------------------- график: перекрестие и подсказка */
  $$('.chart-wrap').forEach(function (wrap) {
    var svg = $('svg.chart', wrap), tip = $('.chart-tip', wrap), cross = $('.cross', wrap);
    if (!svg) return;
    var meta = JSON.parse(svg.getAttribute('data-chart') || '{}');
    var values = JSON.parse(wrap.getAttribute('data-values') || '[]');
    var xs = meta.x || [], labels = meta.labels || [];
    var vb = svg.viewBox.baseVal, pl = 48, pr = 12;
    function move(ev) {
      var r = svg.getBoundingClientRect();
      var px = (ev.clientX - r.left) / r.width * vb.width;
      var n = xs.length; if (!n) return;
      var i;
      if (meta.kind === 'bar') i = Math.floor((px - pl) / ((vb.width - pl - pr) / n));
      else i = Math.round((px - pl) / ((vb.width - pl - pr) / Math.max(1, n - 1)));
      i = Math.max(0, Math.min(n - 1, i));
      var x = meta.kind === 'bar' ? pl + (vb.width - pl - pr) * (i + .5) / n : pl + (n > 1 ? (vb.width - pl - pr) * i / (n - 1) : (vb.width - pl - pr) / 2);
      if (cross) { cross.setAttribute('x1', x); cross.setAttribute('x2', x); cross.style.opacity = 1; }
      var html = '<b>' + xs[i] + '</b>';
      values.forEach(function (s, k) {
        var col = values.length > 1 ? 'var(--series-' + (k + 1) + ')' : 'var(--accent)';
        html += '<div><i style="background:' + col + '"></i>' + (labels[k] || '') + ': ' + fmt(s[xs[i]]) + '</div>';
      });
      tip.innerHTML = html; tip.hidden = false;
      tip.style.left = Math.max(60, Math.min(r.width - 60, x / vb.width * r.width)) + 'px';
    }
    svg.addEventListener('mousemove', move);
    svg.addEventListener('mouseleave', function () { tip.hidden = true; if (cross) cross.style.opacity = 0; });
  });

  /* ---------------------------------------------------------------- загрузка фото */
  function upload(file) {
    var fd = new FormData(); fd.append('file', file);
    return fetch('/panel/uploads/', { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'X-CSRFToken': csrf() } })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || 'Ошибка загрузки'); return j; }); });
  }
  window.Panel.upload = upload;
  function mediaUrl(path) {
    if (!path) return '';
    if (/^(https?:)?\//.test(path)) return path;
    return (window.PANEL_MEDIA_URL || '/media/') + path;
  }
  window.Panel.mediaUrl = mediaUrl;

  // одиночное фото: <div class="photo-field" data-photo="id_image">
  $$('[data-photo]').forEach(function (box) {
    var input = document.getElementById(box.getAttribute('data-photo'));
    var ph = $('.ph', box), file = $('input[type=file]', box), rm = $('[data-photo-remove]', box);
    function paint() {
      var v = input.value;
      ph.style.backgroundImage = v ? 'url("' + mediaUrl(v) + '")' : '';
      ph.classList.toggle('has', !!v);
      if (rm) rm.hidden = !v;
    }
    paint();
    file.addEventListener('change', function () {
      if (!file.files[0]) return;
      box.classList.add('loading');
      upload(file.files[0]).then(function (j) {
        input.value = j.path; paint(); input.dispatchEvent(new Event('input', { bubbles: true }));
      }).catch(function (err) { window.Panel.toast(err.message, 'error'); })
        .finally(function () { box.classList.remove('loading'); file.value = ''; });
    });
    if (rm) rm.addEventListener('click', function () { input.value = ''; paint(); input.dispatchEvent(new Event('input', { bubbles: true })); });
  });

  /* ---------------------------------------------------------------- перетаскивание (мышь и палец) */
  function sortable(container, itemSel, handleSel, onChange) {
    var dragging = null;
    container.addEventListener('pointerdown', function (e) {
      var item = e.target.closest(itemSel);
      if (!item || !container.contains(item)) return;
      if (handleSel && !e.target.closest(handleSel)) return;
      if (e.target.closest('button,input,textarea,select') && !e.target.closest(handleSel || '__')) return;
      dragging = item; item.classList.add('dragging');
      container.setPointerCapture && container.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    container.addEventListener('pointermove', function (e) {
      if (!dragging) return;
      var over = document.elementFromPoint(e.clientX, e.clientY);
      over = over && over.closest(itemSel);
      if (!over || over === dragging || !container.contains(over)) return;
      var r = over.getBoundingClientRect();
      var after = (r.width > r.height * 1.5) ? e.clientY > r.top + r.height / 2 : e.clientX > r.left + r.width / 2;
      if (r.width > r.height * 1.5 || container.classList.contains('rows-editor')) after = e.clientY > r.top + r.height / 2;
      container.insertBefore(dragging, after ? over.nextSibling : over);
    });
    function end() {
      if (!dragging) return;
      dragging.classList.remove('dragging'); dragging = null;
      onChange && onChange();
    }
    container.addEventListener('pointerup', end);
    container.addEventListener('pointercancel', end);
  }
  window.Panel.sortable = sortable;

  // галерея: <div data-gallery="id_gallery">
  $$('[data-gallery]').forEach(function (box) {
    var input = document.getElementById(box.getAttribute('data-gallery'));
    var list = $('.gallery', box), addFile = $('input[type=file]', box);
    var items = [];
    try { items = JSON.parse(input.value || '[]'); } catch (e) { items = []; }
    function save() {
      items = $$('.g-item', list).map(function (n) { return n.getAttribute('data-path'); });
      input.value = JSON.stringify(items);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }
    function render() {
      $$('.g-item', list).forEach(function (n) { n.remove(); });
      var add = $('.g-add', list);
      items.forEach(function (p) {
        var d = document.createElement('div');
        d.className = 'g-item'; d.setAttribute('data-path', p);
        d.innerHTML = '<img alt="" draggable="false"><button type="button" class="btn btn-icon btn-s g-rm" title="Убрать">✕</button>';
        d.firstChild.src = mediaUrl(p);
        list.insertBefore(d, add);
      });
    }
    render();
    list.addEventListener('click', function (e) {
      var rmb = e.target.closest('.g-rm');
      if (rmb) { rmb.closest('.g-item').remove(); save(); }
    });
    sortable(list, '.g-item', null, save);
    addFile.addEventListener('change', function () {
      var files = Array.prototype.slice.call(addFile.files);
      Promise.all(files.map(upload)).then(function (res) {
        res.forEach(function (j) { items.push(j.path); }); render(); save();
      }).catch(function (err) { window.Panel.toast(err.message, 'error'); }).finally(function () { addFile.value = ''; });
    });
  });

  /* ---------------------------------------------------------------- сетка иконок-кнопок (popover) */
  window.Panel.iconPicker = function (anchor, icons, current, onPick) {
    $$('.popover').forEach(function (p) { p.remove(); });
    var pop = document.createElement('div');
    pop.className = 'popover';
    var grid = '<div class="small muted" style="margin-bottom:8px">Выберите иконку</div><div class="icon-grid">';
    icons.forEach(function (name) {
      var tpl = document.getElementById('icon-' + name);
      grid += '<button type="button" data-icon="' + name + '" class="' + (name === current ? 'on' : '') + '"><span class="ic-bubble">' + (tpl ? tpl.innerHTML : '') + '</span>' + name + '</button>';
    });
    pop.innerHTML = grid + '</div>';
    document.body.appendChild(pop);
    var r = anchor.getBoundingClientRect();
    pop.style.top = (window.scrollY + r.bottom + 8) + 'px';
    pop.style.left = Math.max(8, Math.min(window.innerWidth - pop.offsetWidth - 8, window.scrollX + r.left)) + 'px';
    function close(e) { if (!pop.contains(e.target) && e.target !== anchor) { pop.remove(); document.removeEventListener('pointerdown', close); } }
    setTimeout(function () { document.addEventListener('pointerdown', close); }, 0);
    pop.addEventListener('click', function (e) {
      var b = e.target.closest('[data-icon]');
      if (!b) return;
      onPick(b.getAttribute('data-icon')); pop.remove(); document.removeEventListener('pointerdown', close);
    });
  };

  // «что входит»: <div class="rows-editor" data-features="id_features" data-icons='[...]'>
  $$('[data-features]').forEach(function (box) {
    var input = document.getElementById(box.getAttribute('data-features'));
    var icons = JSON.parse(box.getAttribute('data-icons'));
    var list = $('.re-list', box);
    var langs = ['ru', 'ky', 'en'];
    var rows = [];
    try { rows = JSON.parse(input.value || '[]'); } catch (e) { rows = []; }
    function iconHtml(n) { var t = document.getElementById('icon-' + n); return t ? t.innerHTML : n; }
    function save() {
      rows = $$('.re-row', list).map(function (r) {
        var text = {};
        langs.forEach(function (l) { text[l] = $('[data-lang=' + l + ']', r).value; });
        return { icon: r.getAttribute('data-icon'), text: text };
      });
      input.value = JSON.stringify(rows);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }
    function row(f) {
      var d = document.createElement('div');
      d.className = 're-row'; d.setAttribute('data-icon', f.icon);
      d.innerHTML = '<span class="re-handle" title="Перетащите">⋮⋮</span><button type="button" class="re-icon" title="Иконка">' + iconHtml(f.icon) + '</button>' +
        '<div class="re-langs">' + langs.map(function (l) { return '<input data-lang="' + l + '" placeholder="' + l.toUpperCase() + '">'; }).join('') + '</div>' +
        '<button type="button" class="btn btn-icon btn-s btn-ghost re-rm" title="Удалить">✕</button>';
      langs.forEach(function (l) { var i = $('[data-lang=' + l + ']', d); i.value = (f.text || {})[l] || ''; i.classList.toggle('miss', !i.value); });
      return d;
    }
    rows.forEach(function (f) { list.appendChild(row(f)); });
    $('[data-add]', box).addEventListener('click', function () {
      var d = row({ icon: icons[0], text: {} }); list.appendChild(d); save(); $('input', d).focus();
    });
    list.addEventListener('input', function (e) { e.target.classList.toggle('miss', !e.target.value); save(); });
    list.addEventListener('click', function (e) {
      var rm = e.target.closest('.re-rm'); if (rm) { rm.closest('.re-row').remove(); save(); return; }
      var ib = e.target.closest('.re-icon');
      if (ib) {
        var r = ib.closest('.re-row');
        window.Panel.iconPicker(ib, icons, r.getAttribute('data-icon'), function (n) {
          r.setAttribute('data-icon', n); ib.innerHTML = iconHtml(n); save();
        });
      }
    });
    sortable(list, '.re-row', '.re-handle', save);
  });

  // слайды сторис: <div class="rows-editor" data-slides="id_slides">
  $$('[data-slides]').forEach(function (box) {
    var input = document.getElementById(box.getAttribute('data-slides'));
    var list = $('.re-list', box), tpl = $('template', box);
    var langs = ['ru', 'ky', 'en'];
    var rows = [];
    try { rows = JSON.parse(input.value || '[]'); } catch (e) { rows = []; }
    function save() {
      rows = $$('.re-row', list).map(function (r) {
        var o = { image: r.getAttribute('data-image') || '', item: $('select', r).value || null, title: {}, text: {} };
        langs.forEach(function (l) { o.title[l] = $('[data-f=title][data-lang=' + l + ']', r).value; o.text[l] = $('[data-f=text][data-lang=' + l + ']', r).value; });
        return o;
      });
      input.value = JSON.stringify(rows);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }
    function row(s) {
      var d = tpl.content.firstElementChild.cloneNode(true);
      d.setAttribute('data-image', s.image || '');
      var ph = $('.re-icon', d);
      if (s.image) { ph.style.backgroundImage = 'url("' + mediaUrl(s.image) + '")'; ph.style.backgroundSize = 'cover'; ph.innerHTML = ''; }
      langs.forEach(function (l) {
        $('[data-f=title][data-lang=' + l + ']', d).value = (s.title || {})[l] || '';
        $('[data-f=text][data-lang=' + l + ']', d).value = (s.text || {})[l] || '';
      });
      $('select', d).value = s.item || '';
      return d;
    }
    rows.forEach(function (s) { list.appendChild(row(s)); });
    $('[data-add]', box).addEventListener('click', function () { list.appendChild(row({})); save(); });
    list.addEventListener('input', save);
    list.addEventListener('change', function (e) {
      if (e.target.type === 'file' && e.target.files[0]) {
        var r = e.target.closest('.re-row');
        upload(e.target.files[0]).then(function (j) {
          r.setAttribute('data-image', j.path);
          var ph = $('.re-icon', r); ph.style.backgroundImage = 'url("' + j.url + '")'; ph.style.backgroundSize = 'cover'; ph.innerHTML = '';
          save();
        }).catch(function (err) { window.Panel.toast(err.message, 'error'); });
        return;
      }
      save();
    });
    list.addEventListener('click', function (e) {
      var rm = e.target.closest('.re-rm'); if (rm) { rm.closest('.re-row').remove(); save(); return; }
      var ph = e.target.closest('.re-icon'); if (ph) { $('input[type=file]', ph.closest('.re-row')).click(); }
    });
    sortable(list, '.re-row', '.re-handle', save);
  });

  /* ---------------------------------------------------------------- переключатели видимости */
  $$('[data-toggle-by]').forEach(function (el) {
    var name = el.getAttribute('data-toggle-by'), val = el.getAttribute('data-toggle-value');
    function sync() {
      var c = $('input[name="' + name + '"]:checked') || $('[name="' + name + '"]');
      el.hidden = !c || c.value !== val;
    }
    $$('[name="' + name + '"]').forEach(function (i) { i.addEventListener('change', sync); });
    sync();
  });

  /* ---------------------------------------------------------------- шаблоны ответов */
  document.addEventListener('change', function (e) {
    var s = e.target.closest('[data-reply-template]');
    if (!s || !s.value) return;
    var tpls = JSON.parse(document.getElementById('reply-templates').textContent);
    var lang = s.getAttribute('data-lang') || 'ru';
    var t = tpls.filter(function (x) { return String(x.id) === s.value; })[0];
    if (t) {
      var ta = document.getElementById(s.getAttribute('data-reply-template'));
      ta.value = (t.text[lang] || t.text.ru || '');
      ta.focus();
    }
  });


  /* ---------------------------------------------------------------- карточка заявки: правка суммы, отказ, наличные */
  document.addEventListener('click', function (e) {
    var o = e.target.closest('[data-open]');
    if (o) {
      var target = document.getElementById(o.getAttribute('data-open'));
      if (target) {
        var card = o.closest('[data-request-card]') || document;
        $$('[data-adjust],form[id^="reject-"]', card).forEach(function (f) { if (f !== target) f.hidden = true; });
        target.hidden = !target.hidden;
        if (!target.hidden) { var i = $('input:not([type=hidden]),textarea', target); if (i) i.focus(); target.scrollIntoView({ block: 'nearest', behavior: reduced ? 'auto' : 'smooth' }); }
      }
      return;
    }
    var pv = e.target.closest('[data-preview]');
    if (pv) {
      var form = pv.closest('[data-adjust]');
      var fd = new FormData(); fd.append('total', form.total.value);
      fetch(form.getAttribute('data-preview-url'), { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'X-CSRFToken': csrf() } })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          if (j.error) { window.Panel.toast(j.error, 'error'); return; }
          var out = $('[data-preview-out]', form);
          ['total', 'pointsSom', 'moneySom'].forEach(function (k) { $('[data-k=' + k + ']', out).textContent = fmt(j[k]) + NNBSP + 'сом'; });
          $('[data-k=cashback]', out).textContent = '+' + fmt(j.cashback);
          $('[data-needs-manager]', out).hidden = !j.needsManager;
          out.classList.add('on');
          $('[data-adjust-save]', form).disabled = false;
        });
    }
  });
  document.addEventListener('input', function (e) {
    var f = e.target.closest && e.target.closest('[data-adjust]');
    if (f && e.target.name === 'total') { $('[data-adjust-save]', f).disabled = true; $('[data-preview-out]', f).classList.remove('on'); }
  });
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-needs-cash]');
    if (!b) return;
    var chk = document.querySelector('[data-cash-check]');
    if (chk && !chk.checked) {
      e.preventDefault();
      chk.closest('label').animate && chk.closest('label').animate([{ transform: 'translateX(0)' }, { transform: 'translateX(-6px)' }, { transform: 'translateX(6px)' }, { transform: 'translateX(0)' }], { duration: 240 });
      window.Panel.toast('Сначала отметьте, что деньги приняты', 'error');
    }
  });

  /* ---------------------------------------------------------------- автоотправка фильтров */
  $$('form[data-autosubmit]').forEach(function (f) {
    f.addEventListener('change', function (e) { if (e.target.matches('select,input[type=checkbox],input[type=date],input[type=radio]')) f.submit(); });
  });
})();
