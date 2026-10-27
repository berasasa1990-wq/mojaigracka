# Dodatne slike artikla

Panel → Artikli → Dodaj/Uredi → Dodatne slike: odabrati do šest datoteka po
spremanju. Sljedeći upload dodaje slike iza postojećih; prazno polje ne briše
ranije slike. Glavna slika ostaje zasebno polje. Postojeće dodatne slike imaju
pregled u panelu.

Na stranici artikla prikazane su sličice u vertikalnoj koloni lijevo od glavne
slike, na desktopu i mobilnom prikazu. Klik na sličicu mijenja glavnu sliku i
sliku u postojećem zoom dijalogu. Dugmad su dostupna tastaturom i imaju oznaku
odabrane slike. Ako nema glavne slike, prva dodatna slika se prikazuje kao glavna.
Ako dodatnih slika nema, zadržava se postojeći prikaz jedne slike.

ProductImage sadrži FK na Product, image i position, s redoslijedom position/pk.
Slike koriste isti javni R2/local storage i isti upload profil artikla (30.000
bajtova po slici); optimizacija forme ne ponavlja se pri spremanju modela.
Putanja novih dodatnih slika je products/gallery/. Postojeće datoteke/reference
nisu prepisivane ili brisane. R2 inventar/migracija uključuje i ProductImage.
Dodatne slike ne mijenjaju postojeću glavnu share/SEO sliku artikla.

## Migracija prije korištenja

Nova migracija 0046_product_additional_images dodaje samo novu tabelu, bez
prepravljanja postojećih artikala. Prije korištenja nove verzije primijeniti je
u odgovarajućem lokalnom/Render okruženju:

```sh
python manage.py migrate
```

Ova implementacija nije izvršila migraciju nad korisničkom lokalnom ili
produkcijskom bazom niti push/deploy. Testovi primjenjuju migracije samo u
izolovanoj testnoj bazi. Ne pokretati migracije pri svakom buildu.

## Provjere

- 32 ciljana Django testa prolaze: više uploadova preko panela, ograničenje
  šest datoteka, 30 KB, bez dvostruke konverzije, neispravna datoteka bez
  parcijalnog spremanja, očuvanje/dodavanje postojećih slika, commit=False,
  zabrana anonimnog uploada i prikaz bez glavne slike; postojeći upload/R2 testovi.
- Dva JavaScript testa prolaze: klik mijenja glavnu i zoom sliku/aria stanje;
  stranice bez galerije ostaju bez greške. node --check prolazi.
- Cijeli skup: 317 testova, 316 prolazi; ostaje ranije poznati Premium SEO pad.
- manage.py check, makemigrations --check --dry-run i git diff --check prolaze.
- Browser veza nije bila dostupna u ovoj sesiji; vizuelni pregled desktop/mobile
  prikaza u stvarnom browseru nije izvršen.

## Pojedinačno uklanjanje

Uz svaku dodatnu sliku u panelu nalazi se checkbox „Obriši“. Označiti željenu
sliku i kliknuti „Spremi izmjene“. Briše se samo odabrani ProductImage zapis;
glavna slika i ostale dodatne slike ostaju. Svi ID-evi validiraju se isključivo
u galeriji uređivanog artikla. Neispravna forma ne primjenjuje brisanje.
Postojeći POST/CSRF i panel autentifikacija ostaju obavezni. Nema nove migracije.
Datoteka u storageu ne briše se automatski da se ne ošteti druga eventualna
referenca na isti object key; uklanja se iz galerije i javnog prikaza artikla.
Devet galerijskih testova prolazi, uključujući zaštitu tuđih slika i neispravne
forme, te očuvanje glavne i drugih slika.
