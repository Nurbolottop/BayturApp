/* Рабочее место сотрудника: живая очередь (WS /api/v1/staff/events), звук и счётчик на вкладке, QR-сканер. */
(function () {
  'use strict';
  var P = window.Panel, $ = P.$, $$ = P.$$;
  var box = $('[data-queue-box]');
  var baseTitle = document.title, unseen = 0, soundOn = true;
  try { soundOn = localStorage.getItem('desk-sound') !== 'off'; } catch (e) {}

  /* ---------------------------------------------------------------- звук (WebAudio, без файлов) */
  var ctx = null;
  function beep() {
    if (!soundOn) return;
    try {
      ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
      var t = ctx.currentTime;
      [880, 1320].forEach(function (f, i) {
        var o = ctx.createOscillator(), g = ctx.createGain();
        o.type = 'sine'; o.frequency.value = f;
        g.gain.setValueAtTime(0.0001, t + i * 0.16);
        g.gain.exponentialRampToValueAtTime(0.25, t + i * 0.16 + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, t + i * 0.16 + 0.22);
        o.connect(g); g.connect(ctx.destination); o.start(t + i * 0.16); o.stop(t + i * 0.16 + 0.25);
      });
    } catch (e) {}
  }
  function syncSound() {
    var l = $('[data-sound-label]'); if (l) l.textContent = soundOn ? 'Звук вкл' : 'Звук выкл';
  }
  document.addEventListener('click', function (e) {
    if (!e.target.closest('[data-sound-toggle]')) return;
    soundOn = !soundOn;
    try { localStorage.setItem('desk-sound', soundOn ? 'on' : 'off'); } catch (err) {}
    syncSound(); if (soundOn) beep();
  });
  // браузер разрешает звук только после жеста пользователя
  document.addEventListener('pointerdown', function unlock() {
    try { ctx = ctx || new (window.AudioContext || window.webkitAudioContext)(); ctx.resume(); } catch (e) {}
    document.removeEventListener('pointerdown', unlock);
  });
  syncSound();

  /* ---------------------------------------------------------------- счётчик на вкладке */
  function setTitle() { document.title = (unseen ? '(' + unseen + ') ' : '') + baseTitle; }
  document.addEventListener('visibilitychange', function () { if (!document.hidden) { unseen = 0; setTitle(); } });
  function setBadges(count) {
    $$('[data-count="desk"]').forEach(function (b) { b.textContent = count; b.hidden = !count; });
  }

  /* ---------------------------------------------------------------- очередь */
  var known = {};
  function remember() { $$('[data-queue] [data-id]').forEach(function (n) { known[n.getAttribute('data-id')] = 1; }); }
  remember();
  var loading = false;
  function refresh(highlight) {
    if (!box || loading) return;
    loading = true;
    fetch(box.getAttribute('data-url'), { credentials: 'same-origin' })
      .then(function (r) { if (r.redirected || !r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) {
        box.innerHTML = html;
        var fresh = 0;
        $$('[data-queue] [data-id]', box).forEach(function (n) {
          var id = n.getAttribute('data-id');
          n.classList.remove('appear');
          if (!known[id]) { fresh++; if (highlight !== false) n.classList.add('new'); }
          known[id] = 1;
        });
        var q = $('[data-queue]', box);
        setBadges(q ? parseInt(q.getAttribute('data-count'), 10) : 0);
        return fresh;
      })
      .catch(function () {})
      .finally(function () { loading = false; });
  }

  function onEvent(ev) {
    if (!ev || !ev.type) return;
    if (ev.type === 'request.created') {
      beep();
      if (document.hidden) { unseen++; setTitle(); }
      P.toast('Новая заявка: ' + ((ev.data && ev.data.item && ev.data.item.title) || ''), 'success');
    }
    if (ev.type.indexOf('request.') === 0) refresh(ev.type === 'request.created');
    // карточка открыта в листе и заявку обработал другой сотрудник
    var open = document.querySelector('[data-sheet-body] [data-request-card]');
    if (open && ev.data && ev.data.id === open.getAttribute('data-request-card') && ev.data.status !== 'pending') {
      P.toast('Заявку уже обработали: ' + ev.data.status, 'error');
      P.closeSheet();
    }
  }

  /* ---------------------------------------------------------------- WebSocket (сессия, same-origin) + опрос как запасной путь */
  var live = $('[data-live]'), liveText = $('[data-live-text]');
  function setLive(on, text) { if (live) { live.classList.toggle('on', on); liveText.textContent = text; } }
  var ws = null, retry = 1000, pingTimer = null, pollTimer = null;
  function poll() { clearInterval(pollTimer); pollTimer = setInterval(function () { refresh(true); }, 20000); }
  function connect() {
    if (!('WebSocket' in window)) { setLive(false, 'обновление раз в 20 с'); poll(); return; }
    var url = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/api/v1/staff/events';
    try { ws = new WebSocket(url); } catch (e) { poll(); return; }
    ws.onopen = function () {
      retry = 1000; setLive(true, 'онлайн'); clearInterval(pollTimer);
      clearInterval(pingTimer);
      pingTimer = setInterval(function () { try { ws.send(JSON.stringify({ type: 'ping' })); } catch (e) {} }, 25000);
      refresh(false);
    };
    ws.onmessage = function (m) { try { onEvent(JSON.parse(m.data)); } catch (e) {} };
    ws.onclose = function () {
      clearInterval(pingTimer); setLive(false, 'переподключение…'); poll();
      setTimeout(connect, retry); retry = Math.min(retry * 2, 30000);
    };
  }
  if (box) connect();

  /* ---------------------------------------------------------------- QR-сканер (BarcodeDetector) */
  var scanner = $('[data-scanner]');
  if (scanner) {
    var startBtn = $('[data-scan-start]', scanner), view = $('[data-scan-view]', scanner), video = $('video', scanner);
    var form = $('[data-scan-form]', scanner), hint = $('[data-scan-hint]', scanner);
    var stream = null, detector = null, raf = null;
    var supported = 'BarcodeDetector' in window && navigator.mediaDevices && navigator.mediaDevices.getUserMedia;
    if (!supported) { startBtn.hidden = true; hint.textContent = 'Камера или распознавание QR недоступны в этом браузере — вставьте код вручную.'; }
    function stop() {
      if (raf) cancelAnimationFrame(raf);
      if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
      stream = null; view.hidden = true; startBtn.textContent = 'Сканировать';
    }
    function tick() {
      if (!stream) return;
      detector.detect(video).then(function (codes) {
        if (codes && codes.length) {
          var raw = codes[0].rawValue || '';
          var m = raw.match(/[?&]token=([^&]+)/);
          form.token.value = m ? decodeURIComponent(m[1]) : raw;
          stop(); form.submit(); return;
        }
        raf = requestAnimationFrame(tick);
      }).catch(function () { raf = requestAnimationFrame(tick); });
    }
    startBtn.addEventListener('click', function () {
      if (stream) { stop(); return; }
      try { detector = new window.BarcodeDetector({ formats: ['qr_code'] }); } catch (e) { hint.textContent = 'QR не поддерживается — вставьте код вручную.'; return; }
      navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } }).then(function (s) {
        stream = s; video.srcObject = s; view.hidden = false; startBtn.textContent = 'Остановить';
        video.play(); tick();
      }).catch(function () { hint.textContent = 'Нет доступа к камере — вставьте код вручную.'; });
    });
  }
})();
