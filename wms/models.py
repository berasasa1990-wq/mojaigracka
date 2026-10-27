from django.db import models


class StockMovement(models.Model):
    product = models.ForeignKey('shop.Product', on_delete=models.SET_NULL, null=True, related_name='stock_movements')
    product_name = models.CharField(max_length=255)
    change = models.IntegerField()
    stock_before = models.PositiveIntegerField()
    stock_after = models.PositiveIntegerField()
    reason = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']


class Location(models.Model):
    name = models.CharField('Naziv lokacije', max_length=120, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class ProductLocation(models.Model):
    quantity = models.PositiveIntegerField('Količina na lokaciji', default=0)
    product = models.OneToOneField('shop.Product', on_delete=models.CASCADE, related_name='warehouse_location')
    location = models.ForeignKey(Location, verbose_name='Lokacija u skladištu', on_delete=models.PROTECT, null=True, blank=True, related_name='product_locations')

    def __str__(self):
        return str(self.location) if self.location else '—'
