# Upload slika na Renderu

Obrada je u shop/image_uploads.py. Pipeline:
form FileField.clean → optimize_image → označen ContentFile → model pre_save
→ postojeći public_images storage (R2 ili lokalni filesystem). Model pre_save
prepoznaje isti već obrađeni rezultat i ne dekodira/enkodira ga ponovo.
Postojeće spremljene slike se ne obrađuju pri običnom save() bez novog uploada.

- Logo trgovine i brendova: najviše 512 px po dužoj strani, prvo brz PNG
  (compress_level=3), zatim WebP ako PNG ne stane. AVIF se ne pokreće za logo.
- Slike artikala/kategorija: najviše 960 px. Banneri: najviše 1600 px.
- Male i RGBA slike koriste WebP (method=0, alpha_quality=100, exact=True).
- Veće RGB slike: najviše JEDAN AVIF pokušaj, quality=55, speed=10,
  max_threads=1. Pillow 12.3.0 podržava ove opcije.
- AVIF neuspjeh/nedostupan codec ili prevelik rezultat: WebP, zatim PNG ako
  WebP nije dostupan ili encoder ne radi. Najviše osam fallback koraka;
  nema neograničene pretrage kvaliteta i ponavljanja AVIF-a.
- Zadržani limiti izlaza: 15.000 bajtova, odnosno 80.000 za bannere. Ako sadržaj
  ne stane, smanjuju se kvalitet i dimenzije; detaljne/šumovite slike mogu izgubiti
  vidljive detalje. Ako limit nije dostižan, forma vraća grešku umjesto spremanja
  pogrešne/nepotpune slike.
- Ulaz najviše 20 MiB i 12 miliona piksela; veći ulaz je greška forme. JPEG draft
  i thumbnail smanjuju trošak dekodiranja i konverzije. EXIF orijentacija i alfa
  se čuvaju u rezultatu, metadata se uklanja, animacije koriste prvu sliku.
- Ekstenzija i content_type odgovaraju STVARNOM PNG/WebP/AVIF rezultatu.
  Klase AVIFFileField/AVIFUploadFormField zadržavaju imena radi kompatibilnosti
  postojećih migracija. Promjena ne zahtijeva novu migraciju.

Log `shop.image_uploads` na INFO bilježi outcome, format, attempts i elapsed_ms.
Encoder failure log ne uključuje sirovi izuzetak, naziv slike, request niti
kredencijale. Nema promjene Gunicorn timeouta ili R2 konfiguracije.

## Lokalna provjera

34 ciljana testa prolaze: upload forme/modela, POST /panel/logo/, izbjegavanje
ponovnog enkodiranja, produkt AVIF speed/thread parametri, alfa/ekstenzija/MIME,
AVIF/WebP fallback, odsustvo encodera, limit piksela, banneri, R2 i javne slike.
Cijeli skup: 285 testova; 284 prolaze. Ostaje ranije poznati pad
shop.test_premium_seo.PremiumSeoPanelTests.test_locked_access_and_settings_moved.
manage.py check, makemigrations --check --dry-run i git diff --check prolaze.

Sintetički lokalni benchmark (jedan uzorak, isti ulaz prije/poslije):
- Transparentni logo 1200×600: 71,7 ms → 8,9 ms, izlaz PNG 512×256.
- Šumovita slika artikla 1800×1200: 3966,1 ms → 114,9 ms, izlaz WebP 207×138.
  Manji izlaz posljedica je tvrdog limita 15 KB i jeftinijeg encodera.
Ovo nisu mjerenja na Render 0.5 CPU instanci niti garancija vremena svakog
pojedinačnog C codec poziva. Nakon kontrolisanog deploya pratiti elapsed_ms,
prikaz PNG/WebP/AVIF i upload stvarnog logotipa. Nije izvršen deploy/push,
produkcijska migracija ili prerada postojećih slika.

Pillow opcije:
https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html

## Svi banneri — samo AVIF, do 80 KB po slici

Sve pozicije i obje slike bannera spremaju se kao .avif / image/avif do
80.000 bajtova, najviše 1600 px. Kvalitet 80, 65, 50 pokušava se na istoj
rezoluciji; samo posljednji pokušaj smanjuje dimenzije i koristi kvalitet 45.
Najviše četiri AVIF enkodiranja, uvijek speed=10, max_threads=1. Nema ponovne
obrade pri spremanju modela. Transparentnost i omjer stranica se čuvaju.
Ako AVIF encoder nije dostupan/ne radi ili nijedan pokušaj ne stane u limit,
forma vraća grešku; ne sprema drugi format ili prevelik fajl.
Originalni kvalitet nije moguće garantovati unutar 80 KB za proizvoljnu sliku.
Postojeće datoteke nisu mijenjane: ponovo uploadovati originalni banner.

## Visoki kvalitet artikala i ostalih javnih slika

Novi uploadovi u Product.image, Category.image, Brand.logo i StoreSettings.logo
više ne koriste stari budžet 15 KB. Runtime profil je do 1.000.000 bajtova:
slike do 1920 px, logotipi do 1024 px, bez povećavanja malih originala.
Za veće RGB slike najviše jedan brz AVIF quality=85/speed=10/max_threads=1.
Fallback je WebP quality=90 ili PNG, uz očuvanu alfa transparentnost. Ako izlaz
ne stane, forma vraća grešku umjesto dodatnog rušenja kvaliteta/rezolucije.

Kartica artikla, product detail i zoom koriste isti FieldFile.url pa dobijaju
istu novu kvalitetnu datoteku. HTML/CSS i dimenzije prikaza nisu mijenjani.
Banneri su odvojeni i ostaju isključivo AVIF do 80.000 bajtova po slici.
SEO ImageField uploadovi već su čuvali originalne datoteke i nisu promijenjeni.

MAX_IMAGE_BYTES i stari help_text u model metapodacima zadržani su za
kompatibilnost migracija/generičkog helpera; runtime field/form politika koristi
novi budžet i novi help tekst. Nije potrebna nova DB migracija.

Originalni kvalitet bez gubitaka nije garantovan pri AVIF/WebP kompresiji ni
smanjenju na 1920 px, ali nema više tihog smanjivanja artikala na veoma male
rezolucije radi limita 15 KB. Već kompresovane postojeće slike se ne obrađuju;
za vraćanje detalja ponovo uploadovati originalne fajlove.

Provjere: 38 relevantnih testova prolazi (upload, banneri, R2 i share slika),
uključujući detaljnu sliku 1600×1000 čija se rezolucija čuva, visok kvalitet u
encoder opcijama i odbijanje prevelikog izlaza umjesto uništavanja detalja.
check, makemigrations --check --dry-run i git diff --check prolaze.

## Ažurirani limit samo za artikle: 30 KB

Product.image sada ima poseban runtime limit 30.000 bajtova i do 1600 px;
to zamjenjuje gornji profil 1 MB samo za artikle. Kategorije/logotipi zadržavaju
svoj veći budžet, a banneri ostaju na 80 KB. Najviše četiri brza AVIF pokušaja
(80/65/50/45, speed=10, jedna nit); prvo se zadržava rezolucija, zatim se po
potrebi proporcionalno smanjuje. Ako AVIF ne uspije/ne stane, ostaje ograničen
WebP/PNG fallback. Nema drugog obrađivanja rezultata forme pri spremanju modela.
Originalni kvalitet za svaku sliku nije moguć uz 30 KB; složene slike mogu imati
manju rezoluciju. Transparentnost se čuva, MIME i ekstenzija odgovaraju formatu.
Promjena važi za nove uploadove; postojeće datoteke nisu izmijenjene.
39 relevantnih testova prolazi; check i provjera migracija prolaze.

## Aktuelni banner profil: različite dimenzije, do 150 KB

Sve pozicije i obje slike bannera koriste AVIF do 150.000 bajtova po slici.
Prihvataju se široki, uspravni i kvadratni originali unutar postojećih ulaznih
limita (20 MiB / 12 megapiksela). Duža strana je najviše 1920 px; male slike
se ne povećavaju. Omjer stranica i transparentnost ostaju sačuvani.

Najviše šest AVIF pokušaja koristi quality=90, speed=10 i max_threads=1.
Ako rezultat prelazi limit, smanjuju se dimenzije, uz ponovno uzorkovanje iz
prvobitno pripremljene slike da se izbjegne gubitak uslijed ponovljenog resizanja.
Jednostavne slike mogu biti znatno manje od 80 KB; nema dopunjavanja fajla.
Potpuno isti kvalitet i rezolucija nisu garantovani za složene slike u 150 KB.
Greška encodera ili nedostižan limit vraća grešku forme bez spremanja slike.

Obrađeni upload se ne enkodira ponovo pri spremanju modela. Postojeće slike
zahtijevaju ponovni upload originala. Nije potrebna migracija baze.
Ovaj profil zamjenjuje ranije opisane banner limite od 80, 90 i 100 KB.
