(() => {
  const dialog = document.getElementById('giftPopup');
  if (!dialog || typeof dialog.showModal !== 'function') return;
  const status = dialog.querySelector('.gift-popup-status');
  const choices = [...dialog.querySelectorAll('[data-gift-answer]')];
  const shown = key => { try { return sessionStorage.getItem(key); } catch { return false; } };
  const remember = key => { try { sessionStorage.setItem(key, '1'); } catch { /* Storage may be disabled. */ } };
  dialog.querySelector('.gift-popup-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => { if (event.target === dialog) {
    const box = dialog.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
  } });
  fetch(dialog.dataset.configUrl, {credentials: 'same-origin', cache: 'no-store'})
    .then(response => { if (!response.ok) throw new Error(); return response.json(); })
    .then(config => {
      if (!config.enabled) return;
      const key = `gift-popup:${config.revision}`;
      if (shown(key)) return;
      dialog.querySelector('h2').textContent = config.question;
      choices[0].textContent = `A · ${config.answer_a}`;
      choices[1].textContent = `B · ${config.answer_b}`;
      const started = Date.now();
      const open = () => {
        if (shown(key)) return;
        if (document.hidden || document.querySelector('dialog[open]')) {
          window.setTimeout(open, 1000);
          return;
        }
        if (Date.now() - started < config.delay * 1000) return;
        dialog.showModal();
        remember(key);
      };
      window.setTimeout(open, config.delay * 1000);
      choices.forEach(button => button.addEventListener('click', async () => {
        choices.forEach(choice => { choice.disabled = true; });
        status.textContent = 'Pripremamo vaše iznenađenje…';
        try {
          const response = await fetch(dialog.dataset.answerUrl, {
            method: 'POST', credentials: 'same-origin', cache: 'no-store',
            headers: {'X-CSRFToken': config.csrf},
            body: new URLSearchParams({answer: button.dataset.giftAnswer, revision: config.revision})
          });
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || 'Ponuda trenutno nije dostupna.');
          dialog.querySelector('.gift-popup-question').hidden = true;
          const results = dialog.querySelector('.gift-popup-results');
          results.innerHTML = result.html;
          results.hidden = false;
          status.textContent = '';
          dialog.querySelector('h2').textContent = 'Izaberite svoj razlog za osmijeh';
          results.querySelectorAll('form').forEach(form => form.addEventListener('submit', async event => {
            event.preventDefault();
            const submit = form.querySelector('button');
            submit.disabled = true;
            status.textContent = 'Dodajemo poklon u korpu…';
            try {
              const purchase = await fetch(form.action, {
                method: 'POST', credentials: 'same-origin', body: new FormData(form)
              });
              if (purchase.redirected && purchase.ok) {
                window.location.assign(purchase.url);
                return;
              }
              const failure = await purchase.json();
              throw new Error(failure.error || 'Artikal nije moguće dodati. Pokušajte ponovo.');
            } catch (error) {
              status.textContent = error.message || 'Pokušajte ponovo.';
              submit.disabled = false;
            }
          }));
          results.querySelector('button:not([disabled]), a')?.focus();
        } catch (error) {
          status.textContent = error.message || 'Pokušajte ponovo.';
          choices.forEach(choice => { choice.disabled = false; });
        }
      }));
    }).catch(() => { /* The optional campaign must not interrupt shopping. */ });
})();
