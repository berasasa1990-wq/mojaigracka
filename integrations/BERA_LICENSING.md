# BERA IT licence – instalacija i ugovor protokola

## Analiza i obuhvat

Projekt koristi Django 6.1.2, `shop`, standardni auth/session/CSRF middleware,
SQLite i prilagođeni panel za aktivne staff/superuser korisnike. Django admin je
ograničen na superuser. Nema Celery/Redis konfiguracije niti Render manifesta.
Postojeći hourly backup pokreće se kroz shop signals; licenciranje ne dodaje
thread u web procese. Postoje testovi shop prodaje, akcija, panela, uploadova i backupa.
Nema postojećih class-based premium viewova ni premium background poslova.

Implementiran je samo Loyalty: `LoyaltyTier`, `LoyaltyCard`, historijska polja na
Order i raniji `SiteModule`/HMAC kontrolni API. B2B, WMS, analytics, newsletter,
gift_vouchers, scratch_cards i booking su registrirani kodovi, bez implementacije.
Obični katalog, zalihe i promocije nisu automatski proglašeni premium modulima.

| Ulazna tačka | Zaštita kada je loyalty u enforced listi |
| --- | --- |
| `/panel/loyalty/`, GET/POST rasponi | postojeći server guard poziva novu provjeru, zaključano vraća 404 |
| `/korpa/loyalty/`, POST | bez licence uklanja primjenu iz sesije |
| `shop.loyalty.loyalty_status` | vraća nulti popust bez licence |
| korpa i checkout GET/POST | obračun kroz `applied_loyalty_percent` ponovo provjerava pravo |
| registracija korisnika (post_save signal) | ne izdaje novu karticu kada je nova licenca zaključana |
| `/nalog/` | kartica se ne kreira niti prikazuje kada je zaključano; profil i narudžbe ostaju dostupni |
| `/api/modules/loyalty/` | stari kontrolni API vraća 410, ne može dodijeliti prava |
| Django admin SiteModule | polja samo za čitanje; lokalni enabled nije izvor prava |
| budući view/API/job | koristiti dekorator, mixin ili `require_module` na poslovnoj operaciji |

`loyalty_amount` je čista matematička funkcija; sadašnji pozivi dobijaju procenat
iz zaštićenog obračuna. Buduće automatizacije moraju provjeriti pravo prije rada.
Ranije narudžbe i podaci modula se ne brišu. Osnovna prodaja i backup nisu zaključani.

## Instalacija i env

```
venv/bin/pip install -r requirements.txt
venv/bin/python manage.py migrate
venv/bin/python manage.py sync_bera_license --force
```

Nova aditivna migracija je `bera_licensing/0001_initial.py`: LicenseState i
ActivationRequest. Ne mijenja postojeće shop tabele. Migraciju pokrenuti kao
release/pre-deploy korak prije novog web koda. Postojeća lokalna baza nije migrirana
u sklopu implementacije; testovi koriste zasebnu test bazu.

| Varijabla | Lokalno | Render |
| --- | --- | --- |
| BERA_LICENSE_SERVER_URL | HTTPS test server ili isti centralni endpoint | https://bera-it.com/api/v1/licensing/ |
| BERA_LICENSE_INSTALLATION_ID | zaseban registriran dev ID | jedinstven ID klijentske produkcije |
| BERA_LICENSE_API_CREDENTIAL | zaseban dev credential | tajni instalacijski credential u Render env |
| BERA_LICENSE_PUBLIC_KEY | standardni base64 sirovog 32-byte Ed25519 javnog ključa | centralni javni ključ |
| BERA_LICENSE_REFRESH_INTERVAL | 300 sekundi (minimum 30) | 300 |
| BERA_LICENSE_GRACE_PERIOD | 86400 sekundi, ili 0 bez grace | najviše dozvoljeno trajanje grace nakon isteka |
| BERA_LICENSE_ENFORCED_MODULES | prazno za postojeći režim; `loyalty` za test zaštite | prvo prazno, tek nakon provjere `loyalty` |
| BERA_PLATFORM_VERSION | verzija izdanja, default 1.0.0 | stvarna verzija platforme |

DEBUG ne zaobilazi licencu. Nikad ne koristiti produkcijski ID/credential u dev-u.
Zaštita se aktivira isključivo serverskom konfiguracijom, a promjene modula poslije
toga dolaze potpisanim dokumentima, bez deploya ili restartovanja.

Render: web i licencni worker moraju koristiti istu trajnu bazu. Za odvojene Render
servise koristiti zajednički PostgreSQL i prilagoditi postojeći DATABASES/driver;
trenutni projekt nema produkcijsku DB konfiguraciju. Lokalni SQLite fajl na dva
odvojena servisa nije zajednički storage. Alternativno scheduler u istom servisu
može pokretati komandu uz isti trajni SQLite disk (jedna instanca). Ne stavljati
SQLite na ephemeral filesystem i ne dijeliti ga mrežnim filesystemom.

Pokrenuti odvojeni background worker:

```
python manage.py sync_bera_license --watch
```

Ili vanjski scheduler svakih pet minuta:

```
python manage.py sync_bera_license
```

`--force` preskače interval, ali nikada aktivnu lease drugog workera. Atomski DB
lease traje 60 sekundi; mrežni timeout je 10 sekundi. Obični web zahtjevi samo čitaju
bazu i provjeravaju potpis, bez HTTP poziva. Nema potrebe za javnim webhookom.

## Centralni BERA IT server

Ovaj repo sadrži klijenta, ne izvorni kod sajta bera-it.com. Na centralnom serveru
implementirati `POST /api/v1/licensing/sync/`, registraciju instalacija i upravljanje
modulima. Bearer credential mora biti vezan za tačno jednu instalaciju; hashirati
ga u centralnoj bazi, ograničiti učestalost i omogućiti rotaciju. Privatni Ed25519
ključ ostaje isključivo na centralnom serveru.

Zahtjev: Authorization: Bearer <installation credential>, Content-Type application/json:

```json
{"installation_id":"<registered-id>","platform_version":"1.0.0","protocol_version":1}
```

Odgovor JSON ima samo jedan dokument (bez envelope-a):

```json
{
  "installation_id": "<registered-id>",
  "protocol_version": 1,
  "license_version": 1,
  "issued_at": "2026-10-23T10:00:00+00:00",
  "expires_at": "2026-10-23T11:00:00+00:00",
  "grace_until": "2026-10-24T11:00:00+00:00",
  "modules": {"loyalty": true},
  "signature": "<base64-ed25519-signature>"
}
```

Svako polje osim signature ulazi u potpis: Python `json.dumps(payload,
sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('utf-8')`.
Verzija protokola je obavezna i potpisana. Vrijednosti modula su strogi boolean.
Vrijeme mora imati zonu; issued_at < expires_at <= grace_until. Maksimalni dopušteni
budući issued_at je 60 sekundi. HTTPS certifikat se provjerava, redirect nije dozvoljen,
a odgovor je ograničen na 64 KiB. Provjera Ed25519 koristi standardni cryptography
API: https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/ .

Za isti license_version server mora vratiti identičan dokument. Svaka promjena,
uključujući obnavljanje vremena isteka, zahtijeva strogo veću verziju. issued_at ne
smije ići unazad. Klijent odbacuje starije verzije i konfliktne iste verzije; identičan
odgovor je idempotentan i ne produžava potpisane rokove. Centralni server treba
obnavljati kratkotrajne dokumente i trajno čuvati rastuću verziju po instalaciji.

Grace traje do manjeg od potpisanog grace_until i expires_at + lokalni limit. Nove
već istekle licence se ne prihvataju. Kod greške ostaje zadnja validna licenca;
nakon grace premium se zaključava. Izostavljen modul znači zaključano.

Lokalna promjena booleana u potpisanom dokumentu ne daje prava. Osoba koja ima
punu kontrolu nad kodom/env/bazom može izmijeniti program ili vratiti kompletnu
staru bazu; klijentsko licenciranje ne može spriječiti takav napad. Sačuvati backup
verzija na centralnom serveru, ograničiti DB pristup i nakon restorea sinhronizirati
prije puštanja premium operacija. Rotaciju javnog ključa planirati kao konfiguracijski
release. Stari potpisani cache mora se moći zamijeniti novijom validnom licencom.

## Postepeno uključivanje i provjera

1. Deploy migracije i infrastrukturu s praznim BERA_LICENSE_ENFORCED_MODULES.
2. Registrirati različite dev/prod instalacije na centralnom serveru i postaviti env.
3. Pokrenuti ručni sync i pregledati read-only LicenseState u superuser adminu:
   document, version, last_attempt, last_success i fiksni last_error kod bez tajni.
4. U test okruženju uključiti `BERA_LICENSE_ENFORCED_MODULES=loyalty`.
5. Potpisati noviju licencu s loyalty=true, sync, provjeriti karticu, panel i popust.
6. Potpisati sljedeću verziju s loyalty=false, sync; direktni panel URL i ručni POST
   ne daju prava, checkout nastavlja bez loyalty popusta, podaci ostaju sačuvani.
7. Isključiti test server, provjeriti grace, zatim istek. Testirati i novu instalaciju
   bez cache-a. Tek nakon tih provjera uključiti zaštitu u produkciji.

Automatska provjera: `python manage.py test bera_licensing shop --noinput`.

Sekcija „Dodatni moduli” prikazuje status, opis i rok. Dugme evidentira zahtjev u
lokalnoj ActivationRequest listi i upućuje na BERA IT kontakt; ne šalje ga centralnom
serveru jer takav endpoint nije definisan. Za automatsku dostavu treba poseban,
autentificiran centralni endpoint i retry queue. Nijedan zahtjev ne daje pravo rada.

## Granice pokrivenosti

Sedam neimplementiranih modula nema poslovne ulazne tačke za zaštitu. Njihov budući
kod mora koristiti `module_required`, `ModuleRequiredMixin.module_code` i
`require_module` u poslovnim/background operacijama. Nezaštićeni ostaju osnovna
prodaja, katalog, akcije, korisnici, zalihe, narudžbe i backup po namjernoj politici.
Prazna enforced lista ostavlja raniji Loyalty/SiteModule/HMAC režim aktivnim; to je
migracijski režim i nije novi autoritativni sistem. Za produkcijsko licenciranje
obavezno završiti rollout. Centralni admin, payment integracija i stvarni Render
deploy nisu dio ovog lokalnog repozitorija niti su izvršeni ovim promjenama.

## Fajlovi i validacija implementacije

Kreirano u `bera_licensing/`: apps.py, checks.py, models.py, registry.py,
security.py, client.py, services.py, decorators.py, mixins.py, context_processors.py,
admin.py, views.py, management/commands/sync_bera_license.py,
migrations/0001_initial.py, tests/test_licensing.py i package __init__.py fajlovi.
Kreiran je i ovaj dokument `integrations/BERA_LICENSING.md`.

Izmijenjeno: OnlineShopProject/settings.py, OnlineShopProject/urls.py,
requirements.txt, shop/modules.py, shop/module_api.py, shop/admin.py,
shop/views.py, shop/signals.py, shop/templates/shop/panel.html i
integrations/MODULE_CONTROL.md. Postojeće migracije i poslovni podaci nisu mijenjani.

Provjera 23.10.2026:

- `manage.py test bera_licensing shop --noinput`: **104 testa, OK** (9,686 s).
- `manage.py check`: bez problema.
- `manage.py makemigrations --check --dry-run`: nema nedostajućih migracija.
- Testiran je stvarni konkurentni pristup iz dvije niti uz odvojene Django DB
  konekcije (samo jedan remote fetch), uz provjeru zajedničkog trajnog stanja.
- Live centralni server, stvarni produkcijski PostgreSQL i Render deploy nisu
  testirani; za njih su potrebni server implementacija, kredencijali i infrastruktura.
