from django import forms
from .models import StoreSettings


class LogoForm(forms.ModelForm):
    class Meta:
        model = StoreSettings
        fields = ['logo']



from .models import Brand, Category, Product, Banner
from django.core.validators import MinValueValidator


class BrandForm(forms.ModelForm):
    class Meta:
        model = Brand
        fields = ['name', 'logo']


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name', 'image']


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'image', 'description', 'price', 'original_price', 'brand', 'category', 'stock', 'is_out_of_stock', 'is_active', 'is_featured']

    def clean_price(self):
        value = self.cleaned_data['price']
        MinValueValidator(0)(value)
        return value

    def clean_original_price(self):
        value = self.cleaned_data.get('original_price')
        if value is not None:
            MinValueValidator(0)(value)
        return value


class BannerForm(forms.ModelForm):
    class Meta:
        model = Banner
        fields = ['position', 'title', 'eyebrow', 'subtitle', 'button_text', 'features', 'image', 'secondary_image', 'url', 'is_active']
        widgets = {'title': forms.Textarea(attrs={'rows': 2})}

    def clean(self):
        data = super().clean()
        if data.get('position') != 'hero' and not data.get('image'):
            self.add_error('image', 'Dodajte sliku za ovu poziciju bannera.')
        return data

    def clean_url(self):
        value = self.cleaned_data['url'].strip()
        if value and not (value.startswith(('https://', 'http://', '#')) or (value.startswith('/') and not value.startswith('//'))):
            raise forms.ValidationError('Unesite lokalni link /... ili http(s):// adresu.')
        return value


class SaleProductSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if hasattr(value, 'instance'):
            product = value.instance
            option['attrs']['data-regular'] = '1' if product.is_active and not (product.original_price and product.original_price > product.price) else '0'
        return option


class SaleForm(forms.ModelForm):
    field_order = ['sale_type', 'product', 'discount_percent', 'price', 'plus_product', 'plus_percent', 'quantity_percent_2', 'quantity_percent_3', 'quantity_percent_over_3', 'bundle_products', 'bundle_percent']
    discount_percent = forms.DecimalField(label='Sniženje (%)', required=False, min_value=0.01, max_value=100, max_digits=5, decimal_places=2)
    product = forms.ModelChoiceField(queryset=Product.objects.all(), label='Artikal', widget=SaleProductSelect)

    class Meta:
        model = Product
        fields = ['sale_type', 'plus_product', 'plus_percent', 'quantity_percent_2', 'quantity_percent_3', 'quantity_percent_over_3', 'bundle_products', 'bundle_percent', 'price', 'original_price']
        labels = {'price': 'Nova cijena (KM)', 'original_price': 'Redovna cijena'}
        widgets = {'original_price': forms.HiddenInput(), 'bundle_products': forms.CheckboxSelectMultiple()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['plus_product'].queryset = Product.objects.filter(is_active=True)
        self.fields['bundle_products'].queryset = Product.objects.filter(is_active=True)
        self.fields['bundle_products'].label = 'Artikli u setu'
        self.fields['bundle_products'].help_text = 'Odaberite najmanje dva artikla. Set sadrži po jedan komad svakog artikla.'
        sale_type = self.data.get('sale_type') if self.is_bound else self.instance.sale_type
        if sale_type == 'bundle':
            self.fields['product'].required = False
            self.fields['product'].disabled = False
            if not self.is_bound and self.instance.pk:
                self.initial['bundle_products'] = [self.instance.pk, *self.instance.bundle_products.values_list('pk', flat=True)]
        self.is_plus = (self.data.get('sale_type') if self.is_bound else self.instance.sale_type) == 'article_plus'
        self.fields['price'].required = False
        self.fields['price'].min_value = 0
        if not self.is_bound and self.instance.sale_type != 'regular':
            self.initial['price'] = None

    def clean(self):
        data = super().clean()
        if self.is_plus:
            product = data.get('product')
            other = data.get('plus_product')
            percent = data.get('plus_percent')
            if not other:
                self.add_error('plus_product', 'Odaberite drugi artikal.')
            if product and other and product.pk == other.pk:
                self.add_error('plus_product', 'Odaberite artikal različit od prvog.')
            if product and (not product.is_active or (product.original_price and product.original_price > product.price)):
                self.add_error('product', 'Prvi artikal mora biti aktivan i imati regularnu cijenu.')
            if percent is None or not 0 < percent <= 100:
                self.add_error('plus_percent', 'Unesite procenat veći od 0 i do 100.')
            if product:
                data['price'] = product.price
                data['original_price'] = product.original_price
            return data
        data['plus_product'] = None
        data['plus_percent'] = None
        product = data.get('product')
        if data.get('sale_type') == 'bundle':
            members = data.get('bundle_products')
            if members is None or len(members) < 2:
                self.add_error('bundle_products', 'Odaberite najmanje dva artikla za set.')
            if data.get('bundle_percent') is None:
                self.add_error('bundle_percent', 'Unesite procenat sniženja seta.')
            if members:
                # Keep existing storage identity when editing; all members are equal in the UI.
                product = next((member for member in members if member.pk == self.instance.pk), members[0])
                data['product'] = product
                data['price'], data['original_price'] = product.price, product.original_price
            else:
                data['price'] = self.instance.price if self.instance.pk else 0
            return data
        if data.get('sale_type') == 'quantity':
            for name in ['quantity_percent_2', 'quantity_percent_3', 'quantity_percent_over_3']:
                if data.get(name) is None:
                    self.add_error(name, 'Unesite procenat od 0 do 100.')
            if product:
                data['price'] = product.original_price if product.original_price and product.original_price > product.price else product.price
                data['original_price'] = None
                if not product.is_active:
                    self.add_error('product', 'Odaberite aktivan artikal.')
            return data
        if data.get('sale_type') != 'regular':
            self.add_error('sale_type', 'Postavke ove vrste akcije još nisu definisane.')
            if product:
                data['price'], data['original_price'] = product.price, product.original_price
            return data
        if not product:
            return data
        from decimal import Decimal, ROUND_HALF_UP
        regular = product.original_price if product.original_price and product.original_price > product.price else product.price
        percent, price = data.get('discount_percent'), data.get('price')
        if percent is not None and price is not None:
            self.add_error(None, 'Unesite procenat sniženja ili novu cijenu, samo jedno od ta dva.')
        elif percent is not None:
            price = (regular * (1 - percent / Decimal('100'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        elif price is None:
            self.add_error(None, 'Unesite procenat sniženja ili novu cijenu.')
        if price is not None and not 0 <= price < regular:
            self.add_error('price', 'Nova cijena mora biti manja od redovne i ne može biti negativna.')
        data['price'] = price if price is not None else product.price
        data['original_price'] = regular

        return data


from django.contrib.auth.forms import AuthenticationForm


class PanelLoginForm(AuthenticationForm):
    username = forms.CharField(label='Korisničko ime')
    password = forms.CharField(label='Lozinka', strip=False, widget=forms.PasswordInput)
    error_messages = {
        'invalid_login': 'Korisničko ime ili lozinka nisu ispravni.',
        'inactive': 'Ovaj nalog nije aktivan.',
    }

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not (user.is_staff or user.is_superuser):
            raise forms.ValidationError('Ovaj nalog nema pristup panelu.', code='no_panel_access')


from .models import Order


class CheckoutForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['customer_name', 'email', 'phone', 'address', 'city', 'postal_code', 'note']
        widgets = {'note': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        autocomplete = ['name', 'email', 'tel', 'street-address', 'address-level2', 'postal-code']
        for name, hint in zip(self.Meta.fields, autocomplete):
            self.fields[name].required = True
            self.fields[name].widget.attrs['autocomplete'] = hint


class StoreSettingsForm(forms.ModelForm):
    class Meta:
        model = StoreSettings
        fields = ['delivery_price', 'free_delivery_threshold']


class FeaturedProductsForm(forms.Form):
    products = forms.ModelMultipleChoiceField(
        label='Artikli za izdvojenu ponudu',
        queryset=Product.objects.filter(is_active=True).order_by('name'),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text='Označeni artikli prikazuju se na početnoj stranici kao izdvojeni.',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial['products'] = Product.objects.filter(is_active=True, is_featured=True)

    def save(self):
        from django.db import transaction
        with transaction.atomic():
            Product.objects.filter(is_featured=True).update(is_featured=False)
            Product.objects.filter(pk__in=self.cleaned_data['products']).update(is_featured=True)


from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model


class CustomerRegistrationForm(UserCreationForm):
    email = forms.EmailField(label='E-mail')

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ['username', 'first_name', 'last_name', 'email']
        labels = {'username': 'Korisničko ime', 'first_name': 'Ime', 'last_name': 'Prezime'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].label = 'Lozinka'
        self.fields['password2'].label = 'Potvrdi lozinku'
        self.fields['password1'].widget.attrs['autocomplete'] = 'new-password'
        self.fields['password2'].widget.attrs['autocomplete'] = 'new-password'


class CustomerProfileForm(forms.ModelForm):
    email = forms.EmailField(label='E-mail')

    class Meta:
        model = get_user_model()
        fields = ['first_name', 'last_name', 'email']
        labels = {'first_name': 'Ime', 'last_name': 'Prezime'}


class CustomerLoginForm(AuthenticationForm):
    username = forms.CharField(label='Korisničko ime', widget=forms.TextInput(attrs={'autocomplete': 'username'}))
    password = forms.CharField(label='Lozinka', strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}))
    error_messages = {'invalid_login': 'Korisničko ime ili lozinka nisu ispravni.', 'inactive': 'Ovaj nalog nije aktivan.'}


from django.forms import BaseModelFormSet, modelformset_factory
from .models import LoyaltyTier


class LoyaltyTierFormSet(BaseModelFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        ranges = []
        for form in self.forms:
            data = form.cleaned_data
            if not data or data.get('DELETE'):
                continue
            low, high = data['minimum'], data.get('maximum')
            if high is not None and high <= low:
                raise forms.ValidationError('Iznos do mora biti veći od iznosa od.')
            ranges.append((low, high))
        ranges.sort(key=lambda r: r[0])
        for previous, current in zip(ranges, ranges[1:]):
            if previous[1] is None or current[0] < previous[1]:
                raise forms.ValidationError('Rasponi potrošnje se ne smiju preklapati.')


LoyaltySettingsFormSet = modelformset_factory(LoyaltyTier, fields=['minimum', 'maximum', 'percent'], formset=LoyaltyTierFormSet, extra=1, can_delete=True)
