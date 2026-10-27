# Obavijesti o dolasku artikala

Kupci se prijavljuju na kartici ili stranici nedostupnog artikla. Prijavljeni kupac koristi email naloga, a gost unosi email. Jedna adresa ima jednu prijavu po artiklu. Nakon slanja kupac se može ponovo prijaviti kada artikal nestane.

Postaviti SMTP varijable okruženja prije pokretanja aplikacije:

- `EMAIL_HOST`: SMTP server
- `EMAIL_PORT`: npr. `587`
- `EMAIL_HOST_USER` i `EMAIL_HOST_PASSWORD`: SMTP pristupni podaci
- `EMAIL_USE_TLS=true` za STARTTLS ili `EMAIL_USE_SSL=true` za SSL (koristiti samo jednu opciju)
- `DEFAULT_FROM_EMAIL`: potvrđena adresa pošiljaoca

Obavijesti se šalju nakon potvrđene promjene artikla u bazi, prema istim pravilima dostupnosti kao korpa: WMS količina kada je modul uključen, inače oznaka „Nije na stanju”. Neaktivni artikli se ne šalju. Email sadrži naziv i link na artikal, sa domenom korištenom pri prijavi.

Neuspješne isporuke ostaju na čekanju. Za periodično ponovno slanje pokretati:

```sh
python manage.py send_stock_notifications
```

Ova komanda obrađuje i promjene napravljene direktnim ažuriranjem baze koje zaobilaze Django signale. SMTP isporuka ne pruža garanciju tačno jednog emaila ako proces padne nakon slanja, a prije spremanja potvrde u bazu.
