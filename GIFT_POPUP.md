# Poklon pop up

U `/panel/poklon-pop-up/` uključiti popup, unijeti pitanje, tekst odgovora A i B,
posebnu kategoriju za svaki odgovor, zajednički procenat sniženja i broj sekundi
prije pojavljivanja. Kliknuti „Sačuvaj“. Nova instalacija ima isključenu kampanju.

Popup radi samo na početnoj bez pretrage i filtera. Pojavljuje se jednom po sesiji
preglednika za verziju kampanje, s mogućnošću zatvaranja dugmetom ili Escape.
Dok je drugi modal otvoren ili kartica nije vidljiva, čeka s otvaranjem.
Svako spremanje postavki pokreće novu verziju kampanje.

Odgovor bira do dva različita nasumična aktivna dostupna artikla iz pripadajuće
kategorije. Uz WMS se provjerava zaliha; bez WMS svi aktivni artikli su dostupni. Ako je samo
jedan artikal dostupan, prikazuje se jedan; prazna kategorija daje poruku.
Ponovljeni odgovor u istoj sesiji ne mijenja izvučene artikle niti produžava rok.

„Kupi i obraduj“ dodaje jedan komad odabranog artikla u korpu. Cijena se računa
na serveru iz trenutne cijene artikla i postavki kampanje. Popust vrijedi za jedan
komad jednog odabranog artikla, jedan sat od odgovora. Ne zbraja se s drugim
akcijama na isti komad: primjenjuje se povoljnija cijena. Ostale količine koriste
uobičajene cijene i akcije. Standardni loyalty i dostava računaju se poslije toga.

Korpa i checkout koriste isti obračun; narudžba čuva cijenu i oznaku promocije.
Ponovljeni klik na isti izbor ne dodaje dodatni komad; drugi izbor se odbija.
Nije moguće birati artikal izvan izvučene ponude. Gašenje, izmjena kampanje,
istek roka ili promjena kategorije uklanjaju pravo na popust; cijena se ponovo
provjerava pri završetku narudžbe. Nakon kupovine ponuda se uklanja iz sesije.

Sve izmjene i izbori zahtijevaju POST i CSRF. Postavke su dostupne samo korisnicima
koji već imaju pristup panelu. Javni odgovori s ponudama koriste `no-store`.

Migracija: `shop.0047_giftpopupsettings`. Lokalno je primijenjena; na drugom
okruženju pokrenuti `python manage.py migrate` prije korištenja.

Provjere: `shop.test_gift_popup`, uz postojeće testove korpe, checkouta, narudžbi,
količinskih akcija, Ponude + i bundle setova. Vizuelna provjera u browseru nije
završena zbog greške povezivanja browser alata.
