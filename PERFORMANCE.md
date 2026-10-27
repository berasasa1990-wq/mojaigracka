# Optimizacija brzine MojaIgracka

Mjereno lokalno na privremenoj SQLite kopiji postojeće baze, GET /, bez promjene
izvornog db.sqlite3 ili podataka. Nije mjeren Render nakon deploya.

| Mjera | Prije | Poslije |
|---|---:|---:|
| SQL upiti po početnoj stranici | 167 | 25 |
| Ponovljene provjere WMS switch/aktivacije | po 67 | po 1 |
| Warm zahtjev, jedan lokalni uzorak | 30 ms | 16–23 ms |
| HTML prijenos uz gzip | 47.829 B bez kompresije | oko 7.910 B |

Vrijeme zavisi od mašine, podataka i mreže; smanjenje broja upita je pouzdaniji
pokazatelj od jednog uzorka vremena. R2 mrežni pozivi nisu dio SQLite benchmarka.

## Implementacija

- RequestReadCacheMiddleware koristi ContextVar samo za GET/HEAD i resetuje
  kontekst i pri izuzetku. Ponavljanja upita za ModuleSwitch, ModuleActivation
  i legacy loyalty spajaju se unutar jednog zahtjeva. POST/poslovi nemaju cache.
  Naredni zahtjev ponovo čita bazu. Isteći aktivacije se provjeravaju pri svakom
  pozivu, nije keširan rezultat autorizacije preko više zahtjeva.
- Home view učitava bannere jednom, pa iz iste liste bira aktivne hero bannere,
  ponude i informaciju za default hero. Prikaz/filtriranje ostaje isti.
- Za R2 brand logo geometriju nema ponovljenog HEAD-a na svakom prikazu.
  Cache vrijedi pet minuta po storage namespaceu i nazivu; novi upload ima novo
  ime. Greška čitanja/missing logo kešira se 30 sekundi da ne blokira svaki
  artikal. Lokalni logo i dalje koristi mtime radi trenutnog osvježavanja.
  Vanjska zamjena R2 objekta pod istim imenom može zahtijevati do pet minuta.
  Postojeći default LocMemCache dovoljan je za ovu malu količinu podataka;
  svaki Gunicorn worker zagrijava svoj cache odvojeno.
- GZipMiddleware iza WhiteNoise kompresuje odgovore koji podržavaju gzip;
  Django zadržava svoju standardnu zaštitu kompresije i Vary zaglavlja.
  WhiteNoise i slike AVIF ostaju nepromijenjeni.

HTML/CSS/JavaScript, URL struktura, slike i njihovi limiti nisu mijenjani ovom
optimizacijom. Nema globalnog keširanja personalizovanih stranica/korpe, novog
Redis servisa, promjene timeouta ili migracije.

## Provjere

- 8 ciljanih performance testova prolazi: broj upita za 40 artikala, svježina
  modula između zahtjeva, POST read-after-write, cleanup pri izuzetku, istek
  aktivacije, gzip sadržaj i veličina, R2 warm/missing logo bez ponovnih poziva.
- 56 ciljanih testova promocija, BERA CONTROL/licenci i početne optimizacije
  prolazi (pokrenuto prije dodatna četiri performance testa).
- Cijeli skup tokom rada: 299 testova, 298 prolazi; jedan ranije poznati pad
  shop.test_premium_seo.PremiumSeoPanelTests.test_locked_access_and_settings_moved.
  Nakon toga dodan je još jedan prolazni performance test za missing R2 logo.
- manage.py check, makemigrations --check --dry-run i git diff --check prolaze.
- Nije izvršen push ili deploy. Produkcijsku brzinu i Core Web Vitals treba
  izmjeriti nakon kontrolisane objave; lokalni test ne simulira mrežu/Render CPU.

Promijenjeni fajlovi za brzinu: OnlineShopProject/settings.py,
bera_control/services.py, bera_licensing/services.py, shop/modules.py,
shop/views.py, shop/templatetags/brand_logos.py, shop/request_cache.py,
shop/test_performance.py i ovaj dokument. Ostale lokalne izmjene iz prethodnih
zadataka sačuvane su.

Django middleware referenca:
https://docs.djangoproject.com/en/dev/ref/middleware/#gzip-middleware
