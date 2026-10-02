from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('api', '0002_query_completed_at_query_result_query_result_version_and_more')]
    operations = [migrations.AddField(model_name='query', name='company_profiles', field=models.JSONField(default=dict))]
