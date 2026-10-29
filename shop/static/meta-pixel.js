/* One bootstrap per document. All values and event IDs originate on the server. */
(() => {
  if (window.mojaMetaPixel) return;
  const node = document.getElementById('meta-pixel-config');
  if (!node) return;
  const config = JSON.parse(node.textContent);
  const seen = new Set();
  const queue = [...config.events];
  let started = false;
  let allowed = window.metaMarketingConsent !== false;
  function bootstrap() {
    if (started || !allowed) return;
    started = true;
    if (!window.fbq) {
      const fbq = window.fbq = function () { fbq.callMethod ? fbq.callMethod.apply(fbq, arguments) : fbq.queue.push(arguments); };
      if (!window._fbq) window._fbq = fbq;
      fbq.push = fbq; fbq.loaded = true; fbq.version = '2.0'; fbq.queue = [];
      const script = document.createElement('script'); script.async = true;
      script.src = 'https://connect.facebook.net/en_US/fbevents.js';
      document.head.append(script);
    }
    const pixels = window.fbq.getState?.()?.pixels || [];
    if (!pixels.some(pixel => String(pixel.id) === config.pixel_id)) window.fbq('init', config.pixel_id);
    window.fbq('consent', 'grant');
  }
  function flush() {
    if (!allowed) return;
    bootstrap();
    while (queue.length) {
      const event = queue.shift();
      if (!event || seen.has(event.event_id)) continue;
      const key = `meta-purchase:${config.pixel_id}:${event.event_id}`;
      if (event.name === 'Purchase') {
        try {
          if (localStorage.getItem(key)) continue;
          localStorage.setItem(key, '1');
        } catch { /* Database claim also prevents refresh/concurrent repeats. */ }
      }
      seen.add(event.event_id);
      window.fbq('trackSingle', config.pixel_id, event.name, event.data, {eventID: event.event_id});
    }
  }
  window.mojaMetaPixel = {track(event) { queue.push(event); flush(); }};
  window.addEventListener('meta:commerce', event => window.mojaMetaPixel.track(event.detail));
  // A consent manager can suspend tracking and grant/revoke it through this hook.
  window.addEventListener('meta:consent-change', event => {
    allowed = event.detail?.marketing === true;
    if (!allowed && started) window.fbq('consent', 'revoke');
    if (allowed) { if (started) window.fbq('consent', 'grant'); flush(); }
  });
  flush();
})();
