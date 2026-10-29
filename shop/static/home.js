// Retry failed public media through the site's authenticated storage connection.
(() => {
  const header = document.getElementById('header');
  const domain = header?.dataset.publicImageDomain;
  const mediaUrl = header?.dataset.mediaUrl;
  if (!domain || !mediaUrl) return;
  const prefixes = ['brands/', 'categories/', 'products/', 'store/', 'banners/', 'seo/'];
  function retryImage(image) {
    if (!(image instanceof HTMLImageElement)) return;
    let source;
    try { source = new URL(image.currentSrc || image.src, window.location.href); } catch { return; }
    if (source.hostname !== domain || image.dataset.imageFallbackSource === source.href) return;
    const key = source.pathname.replace(/^\//, '');
    if (!prefixes.some(prefix => key.startsWith(prefix))) return;
    image.dataset.imageFallbackSource = source.href;
    image.removeAttribute('srcset');
    image.src = `${mediaUrl.replace(/\/$/, '')}/${key}?proxy=1`;
  }
  document.addEventListener('error', event => retryImage(event.target), true);
  document.querySelectorAll('img').forEach(image => {
    if (image.complete && image.naturalWidth === 0) retryImage(image);
  });
})();

const notice = document.querySelector('#notice');
function showNotice(message) { notice.querySelector('p').textContent = message; notice.showModal(); }
document.querySelectorAll('[data-info]').forEach(button => button.addEventListener('click', () => showNotice(button.dataset.info)));
notice.querySelector('button').addEventListener('click', () => notice.close());
document.querySelector('[data-newsletter]')?.addEventListener('submit', event => {
  event.preventDefault();
  showNotice('Newsletter još nije povezan s ovim projektom. E-mail adresa nije spremljena.');
});
document.querySelectorAll('[data-brand-direction]').forEach(button => {
  button.addEventListener('click', () => {
    const row = button.closest('.bera-popular-brands__carousel').querySelector('.bera-popular-brands__row');
    row.scrollBy({left: Number(button.dataset.brandDirection) * row.clientWidth / 2, behavior: 'smooth'});
  });
});

// Keep the same product selected across collections and page reloads.
const wishlistKey = 'shop-wishlist';
let wishlist = new Set();
try {
  const savedWishlist = JSON.parse(localStorage.getItem(wishlistKey) || '[]');
  if (Array.isArray(savedWishlist)) wishlist = new Set(savedWishlist.map(String));
} catch {}
const wishlistButtons = document.querySelectorAll('[data-wishlist-id]');
function renderWishlist() {
  wishlistButtons.forEach(button => {
    const selected = wishlist.has(button.dataset.wishlistId);
    button.setAttribute('aria-pressed', String(selected));
    button.setAttribute('aria-label', `${selected ? 'Ukloni sa liste želja' : 'Dodaj na listu želja'}: ${button.dataset.productName}`);
  });
  const count = document.querySelector('.nav-actions [data-wishlist-open] .action-count');
  if (count) {
    count.textContent = wishlist.size;
    count.setAttribute('aria-label', `${wishlist.size} artikala`);
  }
}
wishlistButtons.forEach(button => button.addEventListener('click', () => {
  const id = button.dataset.wishlistId;
  if (wishlist.has(id)) wishlist.delete(id);
  else wishlist.add(id);
  try { localStorage.setItem(wishlistKey, JSON.stringify([...wishlist])); } catch {}
  renderWishlist();
  renderWishlistPage();
}));
renderWishlist();

function renderWishlistPage() {
  const page = document.querySelector('[data-wishlist-page]');
  if (!page) return;
  let visible = 0;
  page.querySelectorAll('.product-card--home-reference').forEach(card => {
    const id = card.querySelector('[data-wishlist-id]').dataset.wishlistId;
    card.hidden = !wishlist.has(id);
    if (!card.hidden) visible++;
  });
  page.querySelector('[data-wishlist-empty]').hidden = visible > 0;
  page.querySelector('[data-wishlist-total]').textContent = visible;
}
const wishlistPage = document.querySelector('[data-wishlist-page]');
if (wishlistPage) {
  const url = new URL(window.location.href);
  const ids = [...wishlist].slice(0, 500).join(',');
  if ((url.searchParams.get('ids') || '') !== ids) {
    url.searchParams.set('ids', ids);
    window.location.replace(url);
  } else {
    // Discard saved references to products no longer offered in the store.
    wishlist = new Set([...wishlistPage.querySelectorAll('[data-wishlist-id]')].map(button => button.dataset.wishlistId));
    try { localStorage.setItem(wishlistKey, JSON.stringify([...wishlist])); } catch {}
    renderWishlist();
    renderWishlistPage();
  }
}
document.querySelectorAll('[data-wishlist-open]').forEach(button => {
  button.addEventListener('click', event => {
    event.preventDefault();
    const url = new URL(button.dataset.wishlistOpen, window.location.origin);
    url.searchParams.set('ids', [...wishlist].slice(0, 500).join(','));
    window.location.href = url;
  });
});
window.addEventListener('storage', event => {
  if (event.key !== wishlistKey) return;
  if (wishlistPage) { window.location.reload(); return; }
  try {
    const saved = JSON.parse(event.newValue || '[]');
    wishlist = new Set(Array.isArray(saved) ? saved.map(String) : []);
    renderWishlist();
  } catch {}
});

const mobileMenu = document.querySelector('#mobileMenu');
const mobileMenuOpen = document.querySelector('#mobileMenuOpen');
const mobileMenuClose = document.querySelector('#mobileMenuClose');
if (mobileMenu && mobileMenuOpen && mobileMenuClose) {
  mobileMenuOpen.addEventListener('click', () => {
    mobileMenu.showModal();
    mobileMenuOpen.setAttribute('aria-expanded', 'true');
    document.documentElement.classList.add('mobile-menu-is-open');
  });
  mobileMenuClose.addEventListener('click', () => mobileMenu.close());
  mobileMenu.addEventListener('close', () => {
    mobileMenuOpen.setAttribute('aria-expanded', 'false');
    document.documentElement.classList.remove('mobile-menu-is-open');
  });
  mobileMenu.querySelectorAll('a').forEach(link => link.addEventListener('click', () => mobileMenu.close()));
  mobileMenu.addEventListener('click', event => {
    if (event.target !== mobileMenu) return;
    const bounds = mobileMenu.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) mobileMenu.close();
  });
  const mobileViewport = window.matchMedia('(max-width: 900px)');
  mobileViewport.addEventListener('change', event => {
    if (!event.matches && mobileMenu.open) mobileMenu.close();
  });
}


document.querySelector('#mobileSearchOpen')?.addEventListener('click', () => {
  const search = document.querySelector('.header-search input[type="search"]');
  if (search) {
    search.focus({ preventScroll: true });
  }
});

const searchBox = document.querySelector('[data-suggestions-url]');
if (searchBox) {
  const input = searchBox.querySelector('input[type="search"]');
  const popup = searchBox.querySelector('#searchSuggestions');
  const list = popup.querySelector('ul');
  const status = popup.querySelector('[role="status"]');
  let timer;
  let controller;
  let generation = 0;
  // Sticky inputs can make the browser reveal their original layout position.
  // Restore only the scroll offset captured for this keystroke, never on a timer.
  let typingPosition = null;
  let restoreFrame = null;
  input.addEventListener('beforeinput', () => {
    typingPosition = {left: window.scrollX, top: window.scrollY};
  });
  const cancelTypingRestore = () => {
    typingPosition = null;
    if (restoreFrame !== null) cancelAnimationFrame(restoreFrame);
  };
  window.addEventListener('wheel', cancelTypingRestore, {passive: true});
  window.addEventListener('touchmove', cancelTypingRestore, {passive: true});
  input.addEventListener('blur', cancelTypingRestore);
  const preserveTypingPosition = () => {
    if (!typingPosition) return;
    const position = typingPosition;
    typingPosition = null;
    if (restoreFrame !== null) cancelAnimationFrame(restoreFrame);
    window.scrollTo({...position, behavior: 'instant'});
    restoreFrame = requestAnimationFrame(() => {
      window.scrollTo({...position, behavior: 'instant'});
      restoreFrame = null;
    });
  };
  const closeSuggestions = () => {
    popup.hidden = true;
    input.setAttribute('aria-expanded', 'false');
  };
  const openSuggestions = () => {
    popup.hidden = false;
    input.setAttribute('aria-expanded', 'true');
  };
  input.addEventListener('input', () => {
    clearTimeout(timer);
    controller?.abort();
    const current = ++generation;
    const query = input.value.trim();
    list.replaceChildren();
    preserveTypingPosition();
    if (!query) { closeSuggestions(); return; }
    status.textContent = 'Pretraživanje…';
    openSuggestions();
    timer = setTimeout(async () => {
      controller = new AbortController();
      const url = new URL(searchBox.dataset.suggestionsUrl, window.location.origin);
      url.searchParams.set('q', query);
      for (const key of ['category', 'brand', 'sale', 'bestselling']) {
        if (searchBox.dataset[key]) url.searchParams.set(key, searchBox.dataset[key]);
      }
      try {
        const response = await fetch(url, {signal: controller.signal});
        if (!response.ok) throw new Error('Search failed');
        const data = await response.json();
        if (current !== generation) return;
        status.textContent = data.products.length ? 'Prijedlozi artikala' : 'Nema pronađenih artikala.';
        list.replaceChildren();
        data.products.forEach(product => {
          const item = document.createElement('li');
          const link = document.createElement('a');
          link.href = product.url;
          const thumbnail = document.createElement('span');
          thumbnail.className = 'search-thumbnail';
          if (product.image) {
            const image = document.createElement('img');
            image.src = product.image;
            image.alt = '';
            thumbnail.append(image);
          }
          const name = document.createElement('span');
          name.className = 'search-product-name';
          name.textContent = product.name;
          const price = document.createElement('strong');
          price.textContent = product.price;
          link.append(thumbnail, name, price);
          item.append(link);
          list.append(item);
        });
      } catch (error) {
        if (error.name === 'AbortError' || current !== generation) return;
        status.textContent = 'Prijedlozi trenutno nisu dostupni. Pritisnite Enter za pretragu.';
      }
    }, 200);
  });
  searchBox.addEventListener('keydown', event => {
    const links = [...list.querySelectorAll('a')];
    if (event.key === 'Escape') {
      generation++;
      clearTimeout(timer);
      controller?.abort();
      closeSuggestions();
      input.focus({ preventScroll: true });
    } else if (event.key === 'ArrowDown' && !popup.hidden && links.length) {
      event.preventDefault();
      links[(links.indexOf(document.activeElement) + 1) % links.length].focus({ preventScroll: true });
    } else if (event.key === 'ArrowUp' && !popup.hidden && links.length) {
      event.preventDefault();
      const index = links.indexOf(document.activeElement);
      if (index <= 0) input.focus({ preventScroll: true }); else links[index - 1].focus({ preventScroll: true });
    }
  });
  searchBox.addEventListener('focusout', event => {
    if (!searchBox.contains(event.relatedTarget)) closeSuggestions();
  });
  input.addEventListener('focus', () => {
    if (input.value.trim() && list.children.length) openSuggestions();
  });
  document.addEventListener('click', event => {
    if (!searchBox.contains(event.target)) closeSuggestions();
  });
}

// Session cart: prices and availability are checked by the server.
document.querySelectorAll('[data-cart-open]').forEach(button => {
  button.addEventListener('click', () => { window.location.href = button.dataset.cartOpen; });
});
let cartToastTimer;
document.addEventListener('click', async event => {
    const button = event.target.closest('[data-cart-add]');
    if (!button || button.disabled) return;
    event.preventDefault();
    button.disabled = true;
    try {
      const response = await fetch(button.dataset.cartAdd, {
        method: 'POST',
        headers: {'X-CSRFToken': document.querySelector('#cartCsrf input').value, 'X-Requested-With': 'XMLHttpRequest'},
        body: new URLSearchParams({action: 'add', quantity: button.dataset.cartQuantity || '1'}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Dodavanje u korpu nije uspjelo.');
      if (data.meta_event) window.dispatchEvent(new CustomEvent('meta:commerce', {detail: data.meta_event}));
      document.querySelectorAll('[data-cart-count]').forEach(count => {
        count.textContent = data.count;
        count.setAttribute('aria-label', `${data.count} artikala`);
      });
      let toast = document.querySelector('.cart-toast');
      if (!toast) {
        toast = document.createElement('p');
        toast.className = 'cart-toast';
        toast.setAttribute('role', 'status');
        document.body.append(toast);
      }
      document.querySelector('#quantityOfferConfirm')?.close();
      document.querySelector('#articlePlusOffer')?.close();
      if (data.offer) showArticlePlusOffer(data.offer);
      if (button.dataset.refreshCart === 'true') { window.location.reload(); return; }
      toast.textContent = data.message || 'Artikal je dodan u korpu.';
      toast.hidden = false;
      clearTimeout(cartToastTimer);
      cartToastTimer = setTimeout(() => { toast.hidden = true; }, 2500);
    } catch (error) {
      showNotice(error.message || 'Korpa trenutno nije dostupna. Pokušajte ponovo.');
    } finally {
      button.disabled = false;
    }
});

const categoryMenu = document.querySelector('.bera-category-menu');
if (categoryMenu) {
  document.addEventListener('click', event => {
    if (!categoryMenu.contains(event.target)) categoryMenu.open = false;
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && categoryMenu.open) {
      categoryMenu.open = false;
      categoryMenu.querySelector('summary').focus();
    }
  });
}

document.querySelectorAll('[data-account-open]').forEach(button => {
  button.addEventListener('click', () => { window.location.href = button.dataset.accountOpen; });
});


function showArticlePlusOffer(offer) {
  let dialog = document.querySelector('#articlePlusOffer');
  if (!dialog) {
    dialog = document.createElement('dialog');
    dialog.id = 'articlePlusOffer';
    dialog.className = 'article-plus-offer';
    dialog.setAttribute('aria-labelledby', 'articlePlusOfferTitle');
    document.body.append(dialog);
  }
  dialog.replaceChildren();
  const heading = document.createElement('h2');
  heading.id = 'articlePlusOfferTitle';
  heading.textContent = `−${offer.percent}%`;
  const message = document.createElement('p');
  message.className = 'article-plus-offer-message';
  message.textContent = `Uz ${offer.first_name} kupite i ovaj artikal uz ${offer.percent}% popusta:`;
  const link = document.createElement('a');
  link.href = offer.url;
  const name = document.createElement('span');
  name.textContent = offer.name;
  link.append(name);
  if (offer.image) {
    const image = document.createElement('img');
    image.src = offer.image;
    image.alt = offer.name;
    link.prepend(image);
  }
  const prices = document.createElement('p');
  prices.className = 'article-plus-offer-prices';
  const original = document.createElement('s');
  original.textContent = `${offer.regular_price} KM`;
  const price = document.createElement('strong');
  price.textContent = ` ${offer.price} KM`;
  prices.append(original, price);
  const add = document.createElement('button');
  add.type = 'button';
  add.autofocus = true;
  add.dataset.cartAdd = offer.add_url;
  add.dataset.refreshCart = String(window.location.pathname === '/korpa/');
  add.textContent = `Dodaj uz ${offer.percent}% popusta`;
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'article-plus-offer-close';
  close.textContent = 'Nastavi bez ovog artikla';
  close.addEventListener('click', () => dialog.close());
  dialog.append(heading, message, link, prices, add, close);
  dialog.showModal();
}


document.addEventListener('click', event => {
  const offer = event.target.closest('[data-quantity-offer]');
  if (!offer) return;
  let dialog = document.querySelector('#quantityOfferConfirm');
  if (!dialog) {
    dialog = document.createElement('dialog');
    dialog.id = 'quantityOfferConfirm';
    dialog.className = 'quantity-offer-confirm';
    dialog.setAttribute('aria-labelledby', 'quantityOfferConfirmTitle');
    document.body.append(dialog);
  }
  dialog.replaceChildren();
  const title = document.createElement('h2');
  title.id = 'quantityOfferConfirmTitle';
  title.textContent = 'Dodati u korpu?';
  const name = document.createElement('p');
  name.className = 'quantity-confirm-name';
  name.textContent = offer.dataset.productName;
  const details = document.createElement('p');
  details.textContent = `${offer.dataset.quantity} kom · −${offer.dataset.percent}%`;
  const total = document.createElement('strong');
  total.className = 'quantity-confirm-total';
  total.textContent = `${offer.dataset.total} KM`;
  const confirm = document.createElement('button');
  confirm.type = 'button';
  confirm.autofocus = true;
  confirm.dataset.cartAdd = offer.dataset.addUrl;
  confirm.dataset.cartQuantity = offer.dataset.quantity;
  confirm.textContent = `Da, dodaj ${offer.dataset.quantity} kom`;
  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.className = 'quantity-confirm-cancel';
  cancel.textContent = 'Odustani';
  cancel.addEventListener('click', () => dialog.close());
  dialog.append(title, name, details, total, confirm, cancel);
  dialog.showModal();
});


document.addEventListener('click', event => {
  const close = event.target.closest('[data-close-quantity-offer]');
  if (close) close.closest('.cart-quantity-offers')?.remove();
});

// Preview the linked Ponuda + product without leaving the current product page.
document.addEventListener('click', event => {
  if (event.target.closest('[data-plus-preview-open]')) {
    document.querySelector('#productPlusPreview')?.showModal();
  }
  if (event.target.closest('[data-plus-preview-close]')) {
    document.querySelector('#productPlusPreview')?.close();
  }
});

const brandsDialog = document.querySelector('#brandsDialog');
document.querySelectorAll('[data-brands-open]').forEach(button => {
  button.addEventListener('click', () => brandsDialog?.showModal());
});
brandsDialog?.addEventListener('click', event => {
  if (event.target !== brandsDialog) return;
  const bounds = brandsDialog.getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) brandsDialog.close();
});

// One shared clock for all visible promotion countdowns.
const saleCountdowns = [...document.querySelectorAll('[data-sale-countdown]')];
function updateSaleCountdowns() {
  const now = Date.now();
  saleCountdowns.forEach(timer => {
    const end = Date.parse(timer.dataset.saleCountdown);
    if (!Number.isFinite(end)) { timer.hidden = true; return; }
    const seconds = Math.max(0, Math.ceil((end - now) / 1000));
    if (!seconds) {
      timer.querySelector('[data-countdown-value]').textContent = 'Istekla';
      return;
    }
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor(seconds % 3600 / 60);
    const pad = value => String(value).padStart(2, '0');
    timer.querySelector('[data-countdown-value]').textContent = `${pad(hours)}:${pad(minutes)}:${pad(seconds % 60)}`;
  });
  if (saleCountdowns.every(timer => {
    const end = Date.parse(timer.dataset.saleCountdown);
    return !Number.isFinite(end) || end <= now;
  })) clearInterval(saleCountdownInterval);
}
let saleCountdownInterval;
if (saleCountdowns.length) {
  saleCountdownInterval = setInterval(updateSaleCountdowns, 1000);
  updateSaleCountdowns();
  // Restore countdown text after Back without reloading the saved page.
  window.addEventListener('pageshow', updateSaleCountdowns);
}

const productZoomDialog = document.querySelector('#productZoomDialog');
document.querySelector('[data-product-zoom]')?.addEventListener('click', () => productZoomDialog?.showModal());
productZoomDialog?.addEventListener('click', event => {
  if (event.target !== productZoomDialog) return;
  const bounds = productZoomDialog.getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) productZoomDialog.close();
});

// Subscribe to a product's next arrival without leaving the current page.
document.addEventListener('submit', async event => {
  const form = event.target.closest('.stock-notification-form');
  if (!form) return;
  event.preventDefault();
  const button = form.querySelector('button[type="submit"]');
  const status = form.querySelector('[role="status"]');
  button.disabled = true;
  status.hidden = false;
  status.textContent = 'Spremanje prijave…';
  try {
    const response = await fetch(form.action, {method: 'POST', body: new FormData(form), credentials: 'same-origin'});
    const data = await response.json();
    status.textContent = data.message;
    if (response.ok) {
      status.textContent = '';
      status.hidden = true;
      button.textContent = 'Obavijest prijavljena';
      const details = form.querySelector('details');
      if (details) details.open = false;
    } else button.disabled = false;
  } catch {
    status.textContent = 'Prijava nije uspjela. Pokušajte ponovo.';
    button.disabled = false;
  }
});

const productShareButton = document.querySelector('[data-product-share]');
productShareButton?.addEventListener('click', async () => {
  const url = new URL(productShareButton.dataset.sharePath, window.location.origin).href;
  const status = document.querySelector('.product-share-status');
  status.hidden = true;
  if (navigator.share) {
    try {
      await navigator.share({title: productShareButton.dataset.shareTitle, url});
      return;
    } catch (error) {
      if (error.name === 'AbortError') return;
    }
  }
  try {
    await navigator.clipboard.writeText(url);
    status.textContent = 'Link artikla je kopiran.';
    status.hidden = false;
  } catch {
    window.prompt('Kopirajte link artikla:', url);
  }
});

// Product gallery: keep the large image and zoom dialog in sync.
document.querySelectorAll('[data-product-image]').forEach(button => {
  button.addEventListener('click', () => {
    const main = document.querySelector('[data-product-main-image]');
    const video = document.querySelector('[data-product-video]');
    if (video) {
      video.pause(); video.hidden = true;
      if (main) main.hidden = false;
      document.querySelector('[data-product-video-return]').hidden = false;
      const zoom = document.querySelector('[data-product-zoom]');
      if (zoom) zoom.hidden = false;
    }

    const zoom = document.querySelector('[data-product-zoom-image]');
    if (!main) return;
    if (button.dataset.productSrcset) main.setAttribute('srcset', button.dataset.productSrcset);
    else main.removeAttribute('srcset');
    main.src = button.dataset.productImage;
    if (zoom) zoom.src = button.dataset.productImage;
    document.querySelectorAll('[data-product-image]').forEach(item => {
      const active = item === button;
      item.classList.toggle('is-active', active);
      item.setAttribute('aria-pressed', String(active));
    });
  });
});


// Rotate the main banners every three seconds when several are configured.
document.querySelectorAll('[data-hero-slideshow]').forEach(slideshow => {
  const slides = Array.from(slideshow.children).filter(slide => slide.matches('section'));
  if (slides.length < 2) return;
  let current = 0;
  let paused = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const show = () => slides.forEach((slide, index) => { slide.hidden = index !== current; });
  show();
  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'hero-slideshow-pause';
  const label = () => { toggle.textContent = paused ? 'Pokreni bannere' : 'Pauziraj bannere'; };
  label();
  toggle.addEventListener('click', () => { paused = !paused; label(); });
  slideshow.append(toggle);
  setInterval(() => {
    if (paused || document.hidden || slideshow.matches(':hover') || slideshow.contains(document.activeElement)) return;
    current = (current + 1) % slides.length;
    show();
  }, 3000);
});

document.querySelector('[data-product-video-return]')?.addEventListener('click', event => {
  const video = document.querySelector('[data-product-video]');
  const image = document.querySelector('[data-product-main-image]');
  if (image) image.hidden = true;
  const zoom = document.querySelector('[data-product-zoom]');
  if (zoom) zoom.hidden = true;
  video.hidden = false;
  video.play().catch(() => {});
  event.currentTarget.hidden = true;
});


// Let the browser inspect the actual video codec instead of rejecting MOV's MIME hint.
const productVideo = document.querySelector('[data-product-video]');
if (productVideo) {
  productVideo.muted = true;
  productVideo.defaultMuted = true;
  const startVideo = () => {
    if (!productVideo.hidden) productVideo.play().catch(() => {});
  };
  productVideo.addEventListener('loadeddata', startVideo);
  productVideo.addEventListener('canplay', startVideo);
  productVideo.addEventListener('error', () => {
    const image = document.querySelector('[data-product-main-image]');
    if (image) {
      productVideo.hidden = true;
      image.hidden = false;
      const zoom = document.querySelector('[data-product-zoom]');
      if (zoom) zoom.hidden = false;
    }
    const message = document.createElement('p');
    message.className = 'product-video-error';
    message.textContent = 'Preglednik ne može pustiti ovaj video. Za podršku na svim uređajima učitajte MP4 (H.264).';
    message.setAttribute('role', 'status');
    productVideo.parentElement.append(message);
  }, { once: true });
  startVideo();
}


// Six visible desktop products; advance one card every three seconds.
document.querySelectorAll('[data-product-carousel]').forEach(section => {
  const track = section.querySelector('.home-product-carousel__track');
  if (!track || track.children.length <= 6) return;
  const desktop = window.matchMedia('(min-width: 901px)');
  let paused = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const advance = direction => {
    if (!desktop.matches) return;
    const step = track.children[0].getBoundingClientRect().width + parseFloat(getComputedStyle(track).columnGap || '12');
    const end = track.scrollWidth - track.clientWidth;
    const next = direction > 0 && track.scrollLeft >= end - 2 ? 0 : direction < 0 && track.scrollLeft <= 2 ? end : track.scrollLeft + direction * step;
    track.scrollTo({left: next, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
  };
  const controls = document.createElement('div');
  controls.className = 'product-carousel-controls';
  const button = (text, action) => {
    const element = document.createElement('button');
    element.type = 'button'; element.textContent = text;
    element.addEventListener('click', action); controls.append(element);
    return element;
  };
  button('← Prethodni', () => advance(-1));
  const pause = button(paused ? 'Pokreni' : 'Pauziraj', () => {
    paused = !paused; pause.textContent = paused ? 'Pokreni' : 'Pauziraj';
  });
  button('Sljedeći →', () => advance(1));
  section.append(controls);
  setInterval(() => {
    if (!paused && !document.hidden && !section.matches(':hover') && !section.contains(document.activeElement)) advance(1);
  }, 3000);
});

// On phones, show two purchase benefits and rotate to the next pair.
document.querySelectorAll('.mobile-home-benefits').forEach(track => {
  const phone = window.matchMedia('(max-width: 600px)');
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  let interactingUntil = 0;
  track.addEventListener('touchstart', () => { interactingUntil = Date.now() + 6000; }, {passive: true});
  setInterval(() => {
    if (!phone.matches || reduced.matches || document.hidden || Date.now() < interactingUntil || track.contains(document.activeElement)) return;
    const end = track.scrollWidth - track.clientWidth;
    if (end <= 2) return;
    track.scrollTo({left: track.scrollLeft >= end - 2 ? 0 : Math.min(end, track.scrollLeft + track.clientWidth + 10), behavior: 'smooth'});
  }, 3000);
});

const giftWrapDialog = document.querySelector('#giftWrapDialog');
document.querySelectorAll('[data-gift-open]').forEach(button => button.addEventListener('click', () => giftWrapDialog?.showModal()));
giftWrapDialog?.querySelector('[data-gift-wrap-cancel]')?.addEventListener('click', () => giftWrapDialog.close());

const loyaltyNotice = document.querySelector('#loyalty-notice');
if (loyaltyNotice) showNotice(JSON.parse(loyaltyNotice.textContent));

const giftWrapNotice = document.querySelector('#gift-wrap-notice');
if (giftWrapNotice) showNotice(JSON.parse(giftWrapNotice.textContent));
