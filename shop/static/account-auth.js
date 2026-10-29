// Refresh rotated CSRF cookies and retry a CSRF rejection once, never credentials.
(() => {
  document.querySelectorAll('[data-auth-csrf-url]').forEach(form => {
    let sending = false;
    const feedback = document.createElement('p');
    feedback.className = 'account-feedback'; feedback.setAttribute('role', 'alert'); feedback.hidden = true;
    form.prepend(feedback);
    const localURL = value => {
      const url = new URL(value, location.href);
      if (url.origin !== location.origin) throw new Error('Prijava mora ostati na istoj domeni.');
      return url.href;
    };
    async function refreshToken() {
      const response = await fetch(localURL(form.dataset.authCsrfUrl), {
        credentials: 'same-origin', cache: 'no-store', mode: 'same-origin', headers: {'X-Requested-With': 'XMLHttpRequest'},
      });
      if (!response.ok || response.redirected) throw new Error('Osvježavanje sigurnosnog tokena nije uspjelo.');
      const data = await response.json();
      if (typeof data.csrfToken !== 'string' || !/^[a-zA-Z0-9]{64}$/.test(data.csrfToken)) throw new Error('Neispravan sigurnosni token.');
      form.querySelector('[name="csrfmiddlewaretoken"]').value = data.csrfToken;
    }
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (sending) return;
      sending = true; feedback.hidden = true;
      const button = event.submitter;
      if (button) button.disabled = true;
      try {
        for (let attempt = 0; attempt < 2; attempt++) {
          await refreshToken();
          const body = new FormData(form);
          if (button?.name) body.append(button.name, button.value);
          const response = await fetch(localURL(form.action || location.href), {
            method: 'POST', credentials: 'same-origin', cache: 'no-store', mode: 'same-origin',
            headers: {'X-Requested-With': 'XMLHttpRequest'}, body,
          });
          if (response.status === 403 && response.headers.get('X-Auth-CSRF-Failure') === '1') {
            if (attempt === 0) continue;
            throw new Error('Preglednik ne čuva sigurnosni kolačić. Dozvolite kolačiće za ovaj sajt i osvježite stranicu.');
          }
          if (response.redirected) {
            location.assign(localURL(response.url));
            return;
          }
          if (!response.ok) throw new Error('Prijava trenutno nije dostupna. Pokušajte ponovo.');
          const html = new DOMParser().parseFromString(await response.text(), 'text/html');
          const errors = Array.from(html.querySelectorAll('.errorlist')).map(node => node.textContent.trim()).filter(Boolean);
          throw new Error(errors.join(' ') || 'Provjerite unesene podatke i pokušajte ponovo.');
        }
      } catch (error) {
        feedback.textContent = error.message || 'Provjerite vezu i pokušajte ponovo.';
        feedback.hidden = false;
      } finally {
        sending = false;
        if (button) button.disabled = false;
      }
    });
  });
})();
