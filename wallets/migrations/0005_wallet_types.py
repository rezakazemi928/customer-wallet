import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Count


def map_wallet_types(apps, schema_editor):
    Wallet = apps.get_model('wallets', 'Wallet')
    WalletType = apps.get_model('wallets', 'WalletType')
    alias = schema_editor.connection.alias
    duplicates = Wallet.objects.using(alias).values('user_id', 'type').annotate(total=Count('id')).filter(total__gt=1)
    if duplicates.exists():
        raise RuntimeError(
            'Multiple wallets for the same customer and type exist. Resolve these wallets '
            'and their transaction history before applying migration 0005; no wallets were merged or deleted.'
        )
    names = set(Wallet.objects.using(alias).values_list('type', flat=True)) | {'personal'}
    for name in sorted(names):
        wallet_type = WalletType.objects.using(alias).create(
            name=name, withdrawable=True, automatic_creation=(name == 'personal'),
        )
        Wallet.objects.using(alias).filter(type=name).update(wallet_type_id=wallet_type.pk)


class Migration(migrations.Migration):
    dependencies = [('wallets', '0004_delete_walletrequest')]
    operations = [
        migrations.CreateModel(
            name='WalletType',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=50, unique=True)),
                ('withdrawable', models.BooleanField(default=True)),
                ('automatic_creation', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'db_table': 'wallet_types'},
        ),
        migrations.AddField(
            model_name='wallet', name='wallet_type',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='wallets', to='wallets.wallettype'),
        ),
        migrations.RunPython(map_wallet_types),
        migrations.RemoveField(model_name='wallet', name='type'),
        migrations.AlterField(
            model_name='wallet', name='wallet_type',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                    related_name='wallets', to='wallets.wallettype'),
        ),
        migrations.AddConstraint(
            model_name='wallet',
            constraint=models.UniqueConstraint(fields=('user', 'wallet_type'), name='wallet_user_type_unique'),
        ),
    ]
