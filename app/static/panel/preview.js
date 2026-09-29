/* «Как в приложении»: рамка телефона обновляется из формы на лету; ru / ky / en и светлая / тёмная тема. */
(function () {
  'use strict';
  var P = window.Panel, $ = P.$, $$ = P.$$;
  var root = $('[data-phone]');
  if (!root) return;
  var screen = $('.phone-screen', root);
  var form = document.getElementById(root.getAttribute('data-form')) || document.querySelector('form[data-preview-form]');
  var lang = 'ru';
  var extra = window.PREVIEW || {};

  function field(name) { return form.querySelector('[name="' + name + '"]'); }
  function val(name) { var f = field(name); if (!f) return ''; if (f.type === 'checkbox') return f.checked; if (f.type === 'radio') { var c = form.querySelector('[name="' + name + '"]:checked'); return c ? c.value : ''; } return f.value; }
  function l10n(name) {
    var v = (val(name + '_' + lang) || '').trim();
    var ru = (val(name + '_ru') || '').trim();
    return { text: v || ru, missing: !v && lang !== 'ru' && !!ru };
  }
  function mark(el, missing) { el.classList.toggle('p-miss', !!missing); }
  function paras(text) { return text.split(/\n\s*\n/).map(function (s) { return s.trim(); }).filter(Boolean); }
  function esc(s) { var d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
  function iconSvg(n) { var t = document.getElementById('icon-' + n); return t ? t.innerHTML : ''; }

  var helpers = { val: val, l10n: l10n, esc: esc, paras: paras, iconSvg: iconSvg, fmt: P.fmt, media: P.mediaUrl, lang: function () { return lang; } };

  function render() {
    $$('[data-p-l10n]', screen).forEach(function (el) {
      var name = el.getAttribute('data-p-l10n'), r = l10n(name);
      if (el.hasAttribute('data-p-paras')) {
        el.innerHTML = paras(r.text).map(function (p) { return '<p style="margin:0 0 10px">' + esc(p) + '</p>'; }).join('');
      } else { el.textContent = r.text || el.getAttribute('data-p-empty') || ''; }
      el.hidden = !r.text && el.hasAttribute('data-p-hide-empty');
      mark(el, r.missing);
    });
    $$('[data-p-text]', screen).forEach(function (el) {
      var v = val(el.getAttribute('data-p-text'));
      el.textContent = el.getAttribute('data-p-format') === 'num' ? P.fmt(parseInt(v || 0, 10)) : v;
    });
    $$('[data-p-bg]', screen).forEach(function (el) {
      var v = val(el.getAttribute('data-p-bg'));
      el.style.backgroundImage = v ? 'url("' + P.mediaUrl(v) + '")' : '';
    });
    if (extra.render) extra.render(screen, helpers);
    var miss = $$('.p-miss', screen).length;
    var badge = $('[data-p-missing]', root);
    if (badge) { badge.hidden = !miss; badge.textContent = 'Нет перевода: ' + miss; }
  }

  root.addEventListener('click', function (e) {
    var b = e.target.closest('[data-p-lang]');
    if (b) {
      lang = b.getAttribute('data-p-lang');
      $$('[data-p-lang]', root).forEach(function (x) { x.classList.toggle('on', x === b); });
      P.switchLang(lang);
      render();
    }
    var t = e.target.closest('[data-p-theme]');
    if (t) {
      var th = t.getAttribute('data-p-theme');
      $$('[data-p-theme]', root).forEach(function (x) { x.classList.toggle('on', x === t); });
      screen.classList.toggle('theme-dark', th === 'dark');
      screen.classList.toggle('theme-light', th === 'light');
    }
  });
  document.addEventListener('panel:lang', function (e) {
    lang = e.detail;
    $$('[data-p-lang]', root).forEach(function (x) { x.classList.toggle('on', x.getAttribute('data-p-lang') === lang); });
    render();
  });
  // тема рамки по умолчанию — как у админки
  var dark = document.documentElement.getAttribute('data-theme') === 'dark' ||
    (!document.documentElement.getAttribute('data-theme') && window.matchMedia('(prefers-color-scheme: dark)').matches);
  screen.classList.add(dark ? 'theme-dark' : 'theme-light');
  $$('[data-p-theme]', root).forEach(function (x) { x.classList.toggle('on', x.getAttribute('data-p-theme') === (dark ? 'dark' : 'light')); });

  var pending = false;
  function schedule() { if (pending) return; pending = true; requestAnimationFrame(function () { pending = false; render(); }); }
  form.addEventListener('input', schedule);
  form.addEventListener('change', schedule);
  render();
  window.PanelPreview = { render: render, helpers: helpers };
})();
