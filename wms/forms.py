from django import forms
from .models import Location, ProductLocation


class LocationForm(forms.ModelForm):
    reason = forms.CharField(label='Razlog promjene stanja', max_length=300, required=False,
                             widget=forms.TextInput(attrs={'placeholder': 'Npr. nova roba, oštećenje, otpis…'}))
    def __init__(self, *args, product=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.product = product

    def clean(self):
        data = super().clean()
        quantity = data.get('quantity')
        if quantity and not data.get('location'):
            self.add_error('location', 'Izaberite lokaciju za unesenu količinu.')
        return data

    class Meta:
        model = ProductLocation
        fields = ['location', 'quantity']
        widgets = {'quantity': forms.NumberInput(attrs={'min': 0, 'step': 1})}


class LocationCreateForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ['name']
        help_texts = {'name': 'Npr. Skladište A / Regal 02 / Polica 03'}
