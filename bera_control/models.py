from django.db import models


class ControlState(models.Model):
    monthly_rebate = models.DecimalField('Rabat za mjesečno korištenje (%)', max_digits=5, decimal_places=2, default=0)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(monthly_rebate__gte=0, monthly_rebate__lte=100), name='monthly_rebate_range')]

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    password_hash = models.CharField(max_length=256, blank=True)
    initialized_at = models.DateTimeField(null=True)
    bootstrap_digest = models.CharField(max_length=64, blank=True)
    bootstrap_expires = models.DateTimeField(null=True)
    generation = models.PositiveIntegerField(default=0)
    failures = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True)


class ModuleSwitch(models.Model):
    code = models.CharField(max_length=30, primary_key=True)
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)


class AuditEvent(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    action = models.CharField(max_length=40)
    module = models.CharField(max_length=30, blank=True)
    previous = models.BooleanField(null=True)
    current = models.BooleanField(null=True)
    address = models.GenericIPAddressField(null=True)

    class Meta:
        ordering = ['-created_at', '-pk']


class ModuleActivation(models.Model):
    module = models.CharField(max_length=30, primary_key=True)
    code_digest = models.CharField(max_length=64)
    encrypted_code = models.TextField()
    duration_days = models.PositiveIntegerField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ModulePrice(models.Model):
    code = models.CharField(max_length=30, primary_key=True)
    purchase_price = models.DecimalField('Jednokratna kupovina (KM)', max_digits=12, decimal_places=2, default=0)
    monthly_price = models.DecimalField('Mjesečno korištenje (KM/mj)', max_digits=12, decimal_places=2, default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(purchase_price__gte=0), name='module_purchase_price_nonnegative'),
            models.CheckConstraint(condition=models.Q(monthly_price__gte=0), name='module_monthly_price_nonnegative'),
        ]
