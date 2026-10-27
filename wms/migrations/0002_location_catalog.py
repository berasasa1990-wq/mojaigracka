from django.db import migrations, models
import django.db.models.deletion


def migrate_locations(apps, schema_editor):
    ProductLocation = apps.get_model('wms', 'ProductLocation')
    Location = apps.get_model('wms', 'Location')
    alias = schema_editor.connection.alias
    for entry in ProductLocation.objects.using(alias).all().iterator():
        name = entry.legacy_location.strip()
        if name:
            location, _ = Location.objects.using(alias).get_or_create(name=name)
            entry.location_id = location.pk
            entry.save(using=alias, update_fields=['location'])


def restore_locations(apps, schema_editor):
    ProductLocation = apps.get_model('wms', 'ProductLocation')
    alias = schema_editor.connection.alias
    for entry in ProductLocation.objects.using(alias).select_related('location').iterator():
        entry.legacy_location = entry.location.name if entry.location_id else ''
        entry.save(using=alias, update_fields=['legacy_location'])


class Migration(migrations.Migration):
    dependencies = [('wms', '0001_initial')]
    operations = [
        migrations.CreateModel(
            name='Location',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120, unique=True, verbose_name='Naziv lokacije')),
            ],
            options={'ordering': ['name']},
        ),
        migrations.RenameField(model_name='productlocation', old_name='location', new_name='legacy_location'),
        migrations.AddField(
            model_name='productlocation', name='location',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='product_locations', to='wms.location', verbose_name='Lokacija u skladištu'),
        ),
        migrations.RunPython(migrate_locations, restore_locations),
        migrations.RemoveField(model_name='productlocation', name='legacy_location'),
    ]
