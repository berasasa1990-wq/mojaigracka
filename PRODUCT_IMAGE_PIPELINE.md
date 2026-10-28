# Responsive slike artikala za R2

Novi upload u `Product.image` ili `ProductImage.image` generiše tri verzije:

| Verzija | Najveće dimenzije | Okvirni cilj |
| --- | --- | --- |
| thumbnail | 300 × 300 px | 10–15 KB |
| card | 500 × 500 px | 15–30 KB |
| main | 800 × 800 px | 30–60 KB |

KB ciljevi nisu limiti. Slike se ne povećavaju, ne cropuju i ne razvlače. Kodiranje
je na fiksnom kvalitetu, bez petlje koja ruši kvalitet ili rezoluciju radi veličine.
Zato fotografija sa mnogo sitnih detalja može biti veća od cilja. Nema dopunjavanja
jednostavnih malih fajlova do donje ciljne granice.

## Obrada

`image_uploads.py` zadržava postojeće klase radi kompatibilnosti migracija.
Za artikle poziva `product_images.prepare_product_image()` tokom validacije forme
ili direktnog model/FieldFile uploada. Označeni rezultat forme koristi se pri
spremanju bez drugog dekodiranja/enkodiranja. Glavna verzija zamjenjuje izvor u
polju `image`; thumbnail i card su novi objekti povezani kroz `image_variants` JSON.
Izvorni upload novih slika ne čuva se kao četvrti objekt.

WebP kvalitet 85, method=0, alpha_quality=100 i exact=True su osnovni profil.
EXIF orijentacija primjenjuje se prije obrade; EXIF, XMP i ostali izvorni metapodaci
ne prenose se u rezultate. Ugrađeni ICC se koristi za pretvaranje u sRGB, a alfa
kanal ostaje sačuvan. 16-bitni PNG se pravilno normalizuje, bez klipovanja u bijelo.
LANCZOS resize zadržava omjer i detalje. Animacije koriste prvi kadar. Ulazni limiti
ostaju 20 MiB i 12 megapiksela; neispravne slike daju grešku forme.

`PRODUCT_IMAGE_TRY_AVIF=false` je sigurna početna postavka. Ako se uključi, pokušava
se **najviše jedno** AVIF enkodiranje po uploadu: samo thumbnail do 300 px, kvalitet
85, 4:4:4, speed=10, jedna nit. AVIF se koristi samo ako pokušaj traje najviše
80 ms i fajl je manji od već dobijenog WebP-a. Spor/neuspješan pokušaj koristi
WebP; kartica i glavna slika uvijek koriste WebP. Nema AVIF petlje ni AVIF-a na
punoj ulaznoj rezoluciji. Native codec poziv ne može se prekinuti timerom; zato je
probni posao mali, a AVIF podrazumijevano isključen.

## Storage i trajanje zahtjeva

Obrađeni ContentFile ima MIME koji odgovara stvarnom formatu i ekstenziji.
Svi objekti idu u postojeći public R2 bucket, s jedinstvenim naslovnim ključevima
`mojaigracka.com - naziv artikla - <token>`. Ne prepisuju se niti brišu stari objekti.
`public_images` ostaje izvor za URL/open; privatni/default storage nije promijenjen.

Poseban `public_image_uploads` alias koristi isti bucket i vjerodajnice, uz
connect_timeout=2 s, read_timeout=5 s, jedan pokušaj i bez dodatnih transfer niti.
Tri slanja idu kroz najviše tri mrežne niti i čekaju se prije izlaska iz zahtjeva.
Ovo smanjuje serijsko čekanje R2 i uklanja ponovljene spore pokušaje. Ne mijenja
Gunicorn timeout i nije apsolutna garancija trajanja cijelog HTTP zahtjeva: ulazna
mreža, DNS, baza i opterećenje servera i dalje utiču na vrijeme.

Ako neki upload ne uspije, manifest ne ulazi u bazu. Panel prikazuje poruku, a
postojeća DB referenca i R2 objekti ostaju. Djelimično poslani novi objekti mogu
ostati bez reference; automatsko brisanje nije uvedeno po zahtjevu korisnika.
Logovi `shop.product_images` daju trajanje i veličine varijanti, a
`product_image_store` odvojeno mjeri storage/mrežu, bez provider tajni.

## Prikaz i postojeće slike

Kartice koriste card src sa stvarnim width-descriptor `srcset` i `sizes`.
Glavna slika artikla ima visok prioritet; slike ispod prvog ekrana su lazy.
Galerija koristi male thumbnaile, a promjena slike ažurira glavni srcset i zoom.
AVIF thumbnail ima `<picture>`/type i WebP fallback; ne miješaju se AVIF i WebP
u isti img srcset. Srcset se zasniva na stvarnoj širini, i za uspravne slike.

Stari zapisi bez manifesta koriste postojeći URL. Nema generisanja pri GET-u,
masovne obrade, data migracije slika ili čišćenja R2. Obična izmjena teksta artikla
ne sprema novu sliku. `save(update_fields=['image'])` uključuje i manifest.
Inventar postojećeg `migrate_public_images` uključuje manifest ključeve; ta komanda
nije pokrenuta s `--apply`.

## Migracija i objava

Pripremljena je aditivna migracija
`0048_product_image_variants_productimage_image_variants` (dva JSON polja).
Prije pokretanja novog koda na odgovarajućem okruženju pokrenuti:

```sh
python manage.py migrate
```

Nije izvršen deploy, push, produkcijska migracija niti izmjena postojećih slika.
Migracija nije primijenjena na radnu lokalnu bazu: razvojni server također treba
ovu migraciju prije upotrebe novog koda. Test runner je primjenjuje u privremenoj bazi.

## Lokalni benchmark

Pillow 12.3.0, arm64; medijana tri ponavljanja, sintetički
ulazi 1600×1200. Mjeri dekodiranje, pripremu i tri enkodiranja; ne uključuje R2
mrežu, produkcijski Render CPU ili trajanje cijelog HTTP zahtjeva.

| Uzorak | Obrada (medijana) | thumbnail | card | main |
| --- | --- | --- | --- | --- |
| gradient-text.png | 42.32 ms | 0.63 KB | 1.24 KB | 2.31 KB |
| high-detail-noise.png | 77.52 ms | 18.73 KB | 68.70 KB | 211.14 KB |
| transparent.png | 48.02 ms | 10.47 KB | 18.80 KB | 31.79 KB |

Detaljni izvještaji su u `artifacts/image_pipeline/webp.json` i
`artifacts/image_pipeline/avif-probe.json`. U probnom AVIF benchmarku odabran je
WebP jer je AVIF izlaz bio veći; trajanje pokušaja bilježi se u JSON izvještaju.
Vrlo detaljan šum namjerno prelazi ciljeve, bez dodatnog smanjenja kvaliteta.

Reprodukcija, bez upisa slika/baze/R2:

```sh
DJANGO_ENV=development venv/bin/python manage.py benchmark_product_images --runs 3
DJANGO_ENV=development venv/bin/python manage.py benchmark_product_images --runs 3 --try-avif
DJANGO_ENV=development venv/bin/python manage.py benchmark_product_images --input /putanja/slika.jpg
```

Testovi pokrivaju fiksan kvalitet, meke ciljeve, boje/ICC/16-bit, EXIF, alfa,
proporcije, AVIF mjerenje/fallback, MIME u stvarnom S3 pozivu preko Stubbera,
manifest, tri skladišne verzije, galeriju, srcset, paralelni transport, greške
storagea i očuvanje starih referenci i objekata.
