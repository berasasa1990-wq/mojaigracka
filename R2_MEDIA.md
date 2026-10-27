# Javne slike — Cloudflare R2

Projekat koristi Django 6.1.2 i STORAGES (Django 4.2+). Nema starog
DEFAULT_FILE_STORAGE niti ranijeg S3 backenda. Ne uvodimo zastarjele postavke
za Django verzije koje ovaj projekat ne podržava.

STORAGES.default ostaje FileSystemStorage. STORAGES.staticfiles ostaje WhiteNoise
u produkciji. MEDIA_ROOT ostaje lokalni izvor; MEDIA_URL=/media/ ostaje radi
kompatibilnosti postojećih URL-ova. Samo eksplicitna javna polja koriste
STORAGES.public_images: Product.image, Brand.logo, Category.image,
StoreSettings.logo, Banner.image, Banner.secondary_image, SEOSettings.social_image
i SEOSettings.favicon. Nema promjene privatnih storagea ili drugih datoteka.

S R2 storageom URL slike je npr.
https://media.mojaigracka.com/products/postojeca-slika.avif — isti object key
kao naziv u bazi, bez dodatnog media/ prefiksa. Postojeći javni /media/... URL-ovi
preusmjeravaju se na R2; privatne putanje se ne preusmjeravaju. Obrada logotipa
čita storage.open() umjesto lokalnog .path, uz isti obračun dimenzija. Obrada
uploadova i konverzija AVIF nisu promijenjeni.

## Cloudflare i Render Environment

1. Kreirati R2 bucket mojaigracka-media, samo za javne slike.
2. R2 API credentials: Object Read & Write, ograničeno na taj bucket.
3. U bucket Settings povezati Custom Domain media.mojaigracka.com i sačekati
   aktivan DNS/TLS. Sam CNAME i AWS_S3_CUSTOM_DOMAIN ne uključuju javni pristup.
4. U Render Environment dodati (bez navodnika):

```text
AWS_ACCESS_KEY_ID=<R2 Access Key ID>
AWS_SECRET_ACCESS_KEY=<R2 Secret Access Key>
AWS_STORAGE_BUCKET_NAME=mojaigracka-media
AWS_S3_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
AWS_S3_CUSTOM_DOMAIN=media.mojaigracka.com
AWS_S3_REGION_NAME=auto
R2_ENABLED=false
```

R2_ENABLED=false služi za pripremu/migraciju bez prebacivanja aktivnih slika.
Nakon provjera postaviti true. Ako R2_ENABLED nije naveden, potpuna R2
konfiguracija automatski uključuje R2. Bez svih R2 varijabli ostaje dosadašnji
lokalni storage. Djelimične varijable ili eksplicitni true bez kredencijala
prekidaju pokretanje; ne postoji tihi fallback pri greškama R2 mreže/pristupa.
U R2 modu novi upload ne smije biti preusmjeren na privremeni Render disk.

Backend koristi custom_domain, querystring_auth=False, default_acl=None,
file_overwrite=False, HTTPS i region auto. Ne šalje ACL. Ključevi ostaju u
environmentu; provjere ne ispisuju kredencijale ili sadržaj provider izuzetaka.
Ne uključivati boto3/botocore DEBUG logove. Obični upload ide server → R2, pa
CORS nije potreban za postojeće HTML img elemente. Direktan browser upload
nije dio ove izmjene.

## Sigurna migracija

Ne pokretati migraciju slika automatski tokom builda.

1. Napraviti backup baze i lokalnih media fajlova. Zaustaviti izmjene slika dok
   traje završno kopiranje/provjera. Inventar se mora odnositi na bazu koja će
   se koristiti u produkciji. Lokalna SQLite baza i Render PostgreSQL mogu imati
   različite reference. Ne pretpostavljati da su isti podaci.
2. Sačuvati originalne fajlove na pouzdanom računaru. R2_ENABLED=false uz sve R2
   varijable omogućava testiranje i kopiranje prije prebacivanja aplikacije.
3. Na računaru s izvornim slikama i pristupom odgovarajućoj bazi:

```sh
./venv/bin/python manage.py migrate_public_images --source-root /apsolutna/putanja/media
```

   Podrazumijevano DRY RUN. Čita isključivo javna polja i prijavljuje nedostajuće
   fajlove. Ne mijenja bazu ni datoteke. Iz ove lokalne provjere: 33 jedinstvene
   reference, sve dostupne; 88 lokalnih fajlova ukupno (nije sve referencirano).
   Slike koje su već nestale s Render Free diska moraju se oporaviti iz originala.
4. Pregledati inventar, zatim eksplicitno kopirati:

```sh
./venv/bin/python manage.py migrate_public_images --source-root /apsolutna/putanja/media --apply
```

   Postojeći isti objekti provjeravaju se SHA-256 i preskaču. Različiti sadržaj
   pod istim keyem je konflikt i nikada se ne prepisuje. Kopije se ponovo čitaju
   iz R2 i provjeravaju SHA-256. Nazivi i reference u bazi ostaju isti. Komanda
   ništa ne briše, ne prenosi nereferencirane/privatne fajlove i završava greškom
   ako nešto nedostaje. Zaustaviti konkurentne uploadove tokom kopiranja;
   ako se desi kolizija, sačuvani dodatni objekat ostaje za ručni pregled.
5. Eksplicitna mrežna provjera (dodaje jednu jedinstvenu test PNG sliku):

```sh
./venv/bin/python manage.py check_r2_images --upload
```

   Provjerava upload, autentificirano čitanje, HTTPS javni URL bez potpisa i
   anonimni GET sa sadržajem identičnim uploadu. Test objekat se ne briše
   automatski; može se ručno ukloniti u Cloudflare panelu. Bez --upload komanda
   provjerava samo dostupnost konfiguracije.
6. Provjeriti javne URL-ove nekoliko STVARNIH starih slika i njihov sadržaj;
   zatim R2_ENABLED=true, kontrolisani deploy, te provjeriti novi upload,
   početnu stranicu, artikle, logo, bannere i share.jpg. Primijeniti state
   migraciju 0045_public_image_storage kroz postojeći kontrolisani postupak;
   ona ne prepisuje vrijednosti slikovnih polja i ne seli datoteke.
7. Čuvati lokalne kopije i inventar. Pri rollbacku, dok su uploadovi zaustavljeni,
   prvo kopirati nove R2 objekte nazad u lokalni izvor i provjeriti reference;
   tek onda isključiti R2. Isključivanje R2 samo po sebi ne vraća R2 datoteke.

Na Free Render planu provjere i migraciju pokrenuti lokalno uz sigurno podešen
pristup pravoj Mojaigracka PostgreSQL bazi (External URL) i R2 environment.
Ne koristiti source dev.sh nakon podešavanja DATABASE_URL: taj helper namjerno
briše DATABASE_URL radi lokalne izolacije. Ne slati ključeve/URL baze u chat.
Nemojte koristiti bazu ili ključeve CarpologijaBH.

## Provjere prije deploya

Ciljani testovi pokrivaju pravi django-storages/boto3 request contract uz Stubber
(bez mreže): upload bez ACL-a, read-back i javni URL; izolaciju default/private
storagea; nepotpunu konfiguraciju; dry-run/kopiranje/idempotentnost/konflikte;
nedostajuće izvore i traversal; stare media URL-ove i eksplicitni mrežni probe.
Postojeći testovi uploadova, AVIF-a, bannera, SEO-a i share slika se zadržavaju.
Stvarni bucket/public domain nisu provjereni bez korisničkih kredencijala.

### Rezultati implementacije (2026-10-27)

- 34 ciljana testa: svi prolaze, uključujući 11 R2 testova.
- Cijeli skup pokrenut tokom implementacije: 275 testova, 274 prolaze,
  jedan ranije poznat pad:
  shop.test_premium_seo.PremiumSeoPanelTests.test_locked_access_and_settings_moved.
  Nakon tog pokretanja dodana su još tri ciljana testa koja prolaze.
- Produkcijski check --deploy uz testnu R2 konfiguraciju: prolazi uz očekivano
  security.W004 (HSTS namjerno isključen). Ne kontaktira stvarni bucket/bazu.
- Produkcijski collectstatic: prolazi, WhiteNoise ostaje aktivan.
- makemigrations --check --dry-run: No changes detected.
- pip check i git diff --check: prolaze.
- Lokalni inventar: 33 reference, nula nedostajućih izvora; samo dry-run.
- Nije izvršen upload na pravi R2, migracija baze, push ili deploy.

Bez R2 varijabli fallback je lokalni filesystem; to ne čini Render Free disk
trajnim. Za trajno produkcijsko čuvanje omogućiti i provjeriti R2 prije novih
uploadova. Postojeći objekti nisu automatski kopirani niti obrisani.

Službene reference:
- https://django-storages.readthedocs.io/en/latest/backends/s3_compatible/cloudflare-r2.html
- https://developers.cloudflare.com/r2/examples/aws/boto3/
