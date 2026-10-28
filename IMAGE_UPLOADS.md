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

Sve pozicije i obje slike bannera koriste WebP do 150.000 bajtova po slici.
Prihvataju se široki, uspravni i kvadratni originali unutar postojećih ulaznih
limita (20 MiB / 12 megapiksela). Duža strana je najviše 1920 px; male slike
se ne povećavaju. Omjer stranica i transparentnost ostaju sačuvani.

Najviše četiri WebP pokušaja koristi quality=90 pa 85, method=0,
alpha_quality=100 i exact=True.
Prva dva pokušaja čuvaju punu pripremljenu rezoluciju prije smanjivanja.
Ako rezultat prelazi limit, smanjuju se dimenzije, uz ponovno uzorkovanje iz
prvobitno pripremljene slike da se izbjegne gubitak uslijed ponovljenog resizanja.
Jednostavne slike mogu biti znatno manje od 80 KB; nema dopunjavanja fajla.
Potpuno isti kvalitet i rezolucija nisu garantovani za složene slike u 150 KB.
Greška encodera ili nedostižan limit vraća grešku forme bez spremanja slike.

Obrađeni upload se ne enkodira ponovo pri spremanju modela. Postojeće slike
zahtijevaju ponovni upload originala. Nije potrebna migracija baze.
Ovaj profil zamjenjuje ranije opisane banner limite od 80, 90 i 100 KB.

Banneri se prikazuju u prirodnom omjeru, punom širinom svog kontejnera, bez
nametnutog aspect-ratio i praznih bočnih traka. WebP method=0 smanjuje CPU
trošak sinhronog uploada. Limit je i dalje 150 KB. Ranije umanjene slike zahtijevaju novi upload originala.


### Prekid uploada na Renderu (28.10.2026.)

Dostavljeni log prikazuje WORKER TIMEOUT prije SIGKILL. Poruka „Perhaps out of
memory?“ nije sama po sebi potvrda OOM-a. Spori speed=4 profil zamijenjen je
brzim speed=10, uz iste quality=90/85, jednu nit i najviše četiri pokušaja.
Prije svakog pokušaja provjerava se proteklo vrijeme: nakon pet sekundi od
početka obrade forma odbija daljnje pokušaje. Već započeti nativni codec poziv
ne može se time prekinuti, pa pet sekundi nije strogi ukupni timeout. Vrijeme
slanja u R2 nije dio ove provjere. Nisu mijenjani Gunicorn timeout ni memorija.

Lokalni sintetički uzorak 1920×720 (šum, RGB), jedan AVIF quality=90:
speed=4 3,720 s; speed=10 0,125 s. Cijeli novi pipeline 0,336 s, rezultat
107.405 bajtova. Ovo nije mjerenje na Renderu niti garancija trajanja za svaki
upload. 31 test bannera i obrade slika prolazi, uključujući prekid ponovljenih
pokušaja kada je potrošen vremenski budžet.


### Daljnje smanjenje CPU troška bannera

Novi banner uploadovi sada koriste brzi WebP method=0 umjesto AVIF-a.
Ovo zamjenjuje AVIF profil iz prethodnog odjeljka o timeoutu. Budžet 150 KB,
rezolucija do 1920 px, kvalitet 90/85, najviše četiri pokušaja i provjera
proteklog vremena ostaju. Transparentnost se čuva preko alpha_quality=100 i
exact=True. Postojeći AVIF fajlovi ostaju čitljivi i nisu promijenjeni.

Lokalno poređenje jednog quality=90 enkodiranja istog sintetičkog RGB uzorka
1920×720: AVIF speed=10 CPU 0,134 s; WebP method=0 CPU 0,078 s. Ovo su vremena
samog enkodiranja, a ne garancija Render vremena ili rezultata ispod limita.
Ukupno 31 test bannera i obrade slika prolazi. Nije potrebna DB migracija.

Obrada slika je i dalje sinhrona i nije uvedeno ograničenje CPU procenta:
kratak vrh na 100% ostaje moguć. Cilj je skratiti trajanje opterećenja. Za
premještanje cijelog troška van web procesa trebala bi odvojena obrada; nije
dodavana infrastruktura za red poslova u ovoj izmjeni.


### Unaprijed pripremljen AVIF banner

Statični AVIF banner do 150.000 bajtova prolazi provjeru ispravnosti i ulazni
limit od 12 megapiksela, zatim se sprema neizmijenjen: iste bajtove, dimenzije,
kvalitet i transparentnost. Nema enkodiranja ni smanjivanja na 1920 px u ovom
slučaju. Limit od 1920 px ostaje za slike koje server automatski obrađuje.
Prevelik pripremljeni AVIF vraća jasnu grešku da ga treba smanjiti prije uploada.
Ostali formati i animacije koriste postojeći brzi WebP / prvi kadar profil.
Provjera AVIF-a uključuje dekodiranje i upload u storage, pa CPU trošak nije nula.
Test provjerava da forma i model zajedno ne pozovu encoder i da spremljena
AVIF datoteka bude identična originalu. Ukupno 33 testa bannera/uploadova prolazi.
