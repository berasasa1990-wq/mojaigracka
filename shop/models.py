from .image_uploads import AVIFFileField
from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class Brand(models.Model):
    name = models.CharField('Naziv', max_length=150)
    logo = AVIFFileField('Logo', upload_to='brands/', blank=True)

    class Meta:
        verbose_name = 'Brend'
        verbose_name_plural = 'Brendovi'
        ordering = ['name']

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('brand', kwargs={'brand_pk': self.pk})

    def __str__(self):
        return self.name


class Category(models.Model):
    name = models.CharField('Naziv', max_length=150)
    image = AVIFFileField('Slika', upload_to='categories/', blank=True)

    class Meta:
        verbose_name = 'Kategorija'
        verbose_name_plural = 'Kategorije'
        ordering = ['name']

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('category', kwargs={'category_pk': self.pk})

    def __str__(self):
        return self.name


class ProductQuerySet(models.QuerySet):
    def on_sale(self):
        return self.filter(models.Q(sale_type='bundle', bundle_percent__gt=0, bundle_products__isnull=False) | models.Q(sale_type='quantity', quantity_percent_2__isnull=False, quantity_percent_3__isnull=False, quantity_percent_over_3__isnull=False) | models.Q(original_price__gt=models.F('price')) | models.Q(
            sale_type='article_plus', plus_product__is_active=True, plus_percent__gt=0, plus_percent__lte=100,
        ) & ~models.Q(plus_product_id=models.F('pk')) & (models.Q(original_price__isnull=True) | models.Q(original_price__lte=models.F('price')))).distinct()

    def bestsellers(self):
        return self.annotate(
            order_count=models.Count(
                'order_items__order', distinct=True,
                filter=models.Q(order_items__order__status__in=['placed', 'completed']),
            )
        ).filter(order_count__gt=0).order_by('-order_count', '-created_at', '-pk')


class Product(models.Model):
    class SaleType(models.TextChoices):
        REGULAR = 'regular', 'Regularno sniženje'
        ARTICLE_PLUS = 'article_plus', 'Ponuda +'
        QUANTITY = 'quantity', 'Količinsko sniženje'
        BUNDLE = 'bundle', 'Bundle set'

    quantity_percent_2 = models.DecimalField('Popust za 2 komada (%)', max_digits=5, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(100)])
    quantity_percent_3 = models.DecimalField('Popust za 3 komada (%)', max_digits=5, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(100)])
    quantity_percent_over_3 = models.DecimalField('Popust za više od 3 komada (%)', max_digits=5, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(100)])
    bundle_products = models.ManyToManyField('self', verbose_name='Dodatni artikli u setu', symmetrical=False, blank=True, related_name='bundle_parents')
    bundle_percent = models.DecimalField('Sniženje seta (%)', max_digits=5, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0.01), MaxValueValidator(100)])
    plus_product = models.ForeignKey('self', verbose_name='Drugi artikal', on_delete=models.SET_NULL, null=True, blank=True, related_name='plus_offers')
    plus_percent = models.DecimalField('Popust na drugi artikal (%)', max_digits=5, decimal_places=2, null=True, blank=True)
    sale_type = models.CharField('Vrsta akcije', max_length=20, choices=SaleType.choices, default=SaleType.REGULAR)
    objects = ProductQuerySet.as_manager()

    name = models.CharField('Naziv', max_length=255)
    description = models.TextField('Opis', blank=True)
    image = AVIFFileField('Slika', upload_to='products/', blank=True)
    price = models.DecimalField('Cijena', max_digits=10, decimal_places=2)
    original_price = models.DecimalField('Stara cijena', max_digits=10, decimal_places=2, null=True, blank=True)
    brand = models.ForeignKey(Brand, verbose_name='Brend', on_delete=models.SET_NULL, null=True, blank=True)
    category = models.ForeignKey(Category, verbose_name='Kategorija', on_delete=models.SET_NULL, null=True, blank=True)
    stock = models.PositiveIntegerField('Količina na stanju', default=0)
    is_out_of_stock = models.BooleanField('Nije na stanju', default=False)
    is_active = models.BooleanField('Prikaži u trgovini', default=True)
    is_featured = models.BooleanField('Izdvojena ponuda', default=False)
    is_bestselling = models.BooleanField('Najprodavaniji', default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Artikal'
        verbose_name_plural = 'Artikli'
        ordering = ['-created_at', '-pk']

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('product_detail', kwargs={'pk': self.pk})

    def quantity_discount_percent(self, quantity):
        if self.sale_type != 'quantity' or quantity < 2:
            return 0
        return (self.quantity_percent_2 if quantity == 2 else self.quantity_percent_3 if quantity == 3 else self.quantity_percent_over_3) or 0

    @property
    def has_article_plus(self):
        return (self.sale_type == 'article_plus' and self.plus_product_id
                and self.plus_product_id != self.pk and self.plus_product.is_active
                and self.plus_percent and 0 < self.plus_percent <= 100
                and not (self.original_price and self.original_price > self.price))

    @property
    def discount_percent(self):
        if self.original_price and self.original_price > self.price:
            from decimal import Decimal, ROUND_HALF_UP
            return int(((self.original_price - self.price) * Decimal(100) / self.original_price).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        return 0

    def __str__(self):
        return self.name


class StoreSettings(models.Model):
    free_delivery_threshold = models.DecimalField('Besplatna dostava od (KM)', max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)], help_text='Ostavite prazno ako nema besplatne dostave prema iznosu.')
    delivery_price = models.DecimalField('Cijena dostave (KM)', max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)], help_text='Unesite 0 za besplatnu dostavu.')
    logo = AVIFFileField('Logo trgovine', upload_to='store/', blank=True)

    def delivery_cost(self, subtotal):
        if self.free_delivery_threshold is not None and subtotal >= self.free_delivery_threshold:
            return 0
        return self.delivery_price

    class Meta:
        verbose_name = 'Podešavanje trgovine'
        verbose_name_plural = 'Podešavanje trgovine'


class Banner(models.Model):
    POSITION_CHOICES = [
        ('hero', 'Glavni banner'), ('offer_left', 'Lijeva ponuda'),
        ('offer_right', 'Desna ponuda'), ('footer', 'Donji banner'),
    ]
    title = models.CharField('Naslov', max_length=150)
    image = AVIFFileField('Slika', upload_to='banners/', blank=True)
    secondary_image = AVIFFileField('Dodatna slika', upload_to='banners/', blank=True)
    eyebrow = models.CharField('Tekst iznad naslova', max_length=150, blank=True)
    features = models.CharField('Artikli ispod dugmeta', max_length=300, blank=True, help_text='Odvojite nazive znakom |, npr. iPhone|MacBook|AirPods|Apple Watch')
    subtitle = models.TextField('Opis bannera', blank=True)
    button_text = models.CharField('Tekst dugmeta', max_length=80, blank=True, default='Istraži ponudu')
    position = models.CharField('Pozicija', max_length=20, choices=POSITION_CHOICES)
    url = models.CharField('Link', max_length=300, blank=True, help_text='Lokalni link /... ili https://...')
    is_active = models.BooleanField('Prikaži banner', default=True)

    class Meta:
        verbose_name = 'Banner'
        verbose_name_plural = 'Banneri'
        ordering = ['position', 'pk']
        constraints = [models.UniqueConstraint(fields=['position'], condition=~models.Q(position='hero'), name='unique_nonhero_banner_position')]

    @property
    def feature_items(self):
        return [item.strip() for item in self.features.split('|') if item.strip()]

    def __str__(self):
        return self.title


class Order(models.Model):
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="shop_orders")
    STATUS_CHOICES = [
        ('draft', 'U pripremi'), ('placed', 'Naručeno'),
        ('completed', 'Završeno'), ('cancelled', 'Otkazano'),
    ]
    customer_name = models.CharField('Ime i prezime', max_length=150, blank=True)
    email = models.EmailField('E-mail', blank=True)
    phone = models.CharField('Telefon', max_length=40, blank=True)
    address = models.CharField('Adresa', max_length=255, blank=True)
    city = models.CharField('Grad', max_length=100, blank=True)
    postal_code = models.CharField('Poštanski broj', max_length=20, blank=True)
    note = models.TextField('Napomena', blank=True)
    delivery_price = models.DecimalField('Cijena dostave', max_digits=10, decimal_places=2, default=0)
    loyalty_percent = models.DecimalField('Loyalty popust (%)', max_digits=5, decimal_places=2, default=0)
    loyalty_discount = models.DecimalField('Loyalty popust (KM)', max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField('Ukupno', max_digits=12, decimal_places=2, default=0)
    status = models.CharField('Status', max_length=12, choices=STATUS_CHOICES, default='placed')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Narudžba'
        verbose_name_plural = 'Narudžbe'


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='order_items')
    unit_price = models.DecimalField('Jedinična cijena', max_digits=10, decimal_places=2, default=0)
    quantity = models.PositiveIntegerField('Količina', default=1)

    class Meta:
        verbose_name = 'Stavka narudžbe'
        verbose_name_plural = 'Stavke narudžbe'
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gte=1), name='order_item_quantity_positive')]


import uuid
import secrets

def generate_loyalty_number():
    while True:
        digits = f"{secrets.randbelow(100_000_000):08d}"
        number = f"{digits[:4]}-{digits[4:]}"
        if not LoyaltyCard.objects.filter(number=number).exists():
            return number

from django.core.validators import MaxValueValidator


class LoyaltyCard(models.Model):
    customer = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='loyalty_card')
    number = models.CharField(max_length=9, default=generate_loyalty_number, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)


class LoyaltyTier(models.Model):
    minimum = models.DecimalField('Potrošnja od (KM)', max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    maximum = models.DecimalField('Potrošnja do (KM)', max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    percent = models.DecimalField('Popust (%)', max_digits=5, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(100)])

    class Meta:
        ordering = ['minimum']


class AdminLoginNonce(models.Model):
    digest = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()


class SiteModule(models.Model):
    code = models.CharField('Modul', max_length=30, unique=True, choices=[('loyalty', 'Loyalty')])
    enabled = models.BooleanField('Uključen', default=True)
    paid_until = models.DateTimeField('Aktivan do', null=True, blank=True, help_text='Prazno znači bez vremenskog ograničenja.')
    revision = models.PositiveBigIntegerField(default=0, editable=False)
    updated_at = models.DateTimeField('Ažurirano', auto_now=True)

    class Meta:
        verbose_name = 'Modul'
        verbose_name_plural = 'Moduli'

    def __str__(self):
        return self.get_code_display()
