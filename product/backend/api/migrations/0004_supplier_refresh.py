import uuid
from django.db import migrations, models
import django.utils.timezone

class Migration(migrations.Migration):
    dependencies=[('api','0003_query_company_profiles')]
    operations=[
        migrations.CreateModel(name='LiveSupplierProfile',fields=[('inn',models.CharField(max_length=12,primary_key=True,serialize=False)),('profile',models.JSONField()),('checked_at',models.DateTimeField())]),
        migrations.CreateModel(name='SourceRefreshJob',fields=[('id',models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False,serialize=False)),('inn',models.CharField(max_length=12,unique=True)),('status',models.CharField(max_length=20,default='queued')),('attempts',models.PositiveIntegerField(default=0)),('lease_token',models.UUIDField(null=True)),('lease_until',models.DateTimeField(null=True)),('available_at',models.DateTimeField(default=django.utils.timezone.now)),('created_at',models.DateTimeField(auto_now_add=True)),('checked_at',models.DateTimeField(null=True)),('next_allowed_at',models.DateTimeField(null=True)),('input_hash',models.CharField(max_length=64,default='')),('message',models.CharField(max_length=500,default='Обновление сведений ожидает обработки.'))],options={'indexes':[models.Index(fields=['status','available_at'],name='source_status_available')]}),
        migrations.CreateModel(name='SourceEvidenceBlob',fields=[('content_hash',models.CharField(max_length=64,primary_key=True,serialize=False)),('body',models.BinaryField()),('size',models.PositiveIntegerField()),('url',models.TextField()),('fetched_at',models.CharField(max_length=64)),('created_at',models.DateTimeField(auto_now_add=True))]),
        migrations.CreateModel(name='SourceEvidenceBudget',fields=[('id',models.PositiveSmallIntegerField(primary_key=True,default=1,serialize=False)),('used_bytes',models.PositiveBigIntegerField(default=0))]),
    ]
