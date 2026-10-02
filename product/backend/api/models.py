import uuid
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone

class UserManager(BaseUserManager):
    use_in_migrations = True
    def create_user(self, email, password=None, **extra_fields):
        user = self.model(email=email.strip().lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    def create_superuser(self, email, password, **extra_fields):
        return self.create_user(email, password, is_staff=True, is_superuser=True, **extra_fields)

class User(AbstractUser):
    username = None
    first_name = None
    last_name = None
    email = models.EmailField(unique=True, max_length=254)
    name = models.CharField(max_length=100)
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']
    objects = UserManager()

class ImportBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

class Query(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    batch = models.ForeignKey(ImportBatch, null=True, blank=True, on_delete=models.CASCADE, related_name='queries')
    procurement = models.JSONField()
    raw_notice = models.JSONField(default=dict)
    raw_items = models.JSONField(default=list)
    draft_id = models.CharField(max_length=128, null=True)
    warnings = models.JSONField(default=list)
    saved = models.BooleanField(default=False)
    exported = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    result = models.JSONField(default=dict)
    company_profiles = models.JSONField(default=dict)
    result_version = models.CharField(max_length=64, default='input-v1')
    completed_at = models.DateTimeField(null=True)
    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['owner', '-created_at'])]

class InferenceJob(models.Model):
    """One durable work item per immutable input. A lease token fences late workers."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    query = models.OneToOneField(Query, on_delete=models.CASCADE, related_name='inference_job')
    status = models.CharField(max_length=16, default='queued', choices=[(s, s) for s in ('queued', 'running', 'complete', 'failed')])
    attempts = models.PositiveIntegerField(default=0)
    lease_token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    available_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=64, default='')
    message = models.CharField(max_length=500, default='Ожидает обработки.')
    class Meta:
        indexes = [models.Index(fields=['status', 'available_at'])]

class ExportRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    query = models.ForeignKey(Query, on_delete=models.CASCADE)
    format = models.CharField(max_length=8)
    created_at = models.DateTimeField(auto_now_add=True)

class Mutation(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    scope = models.CharField(max_length=40)
    key = models.CharField(max_length=128)
    digest = models.CharField(max_length=64)
    response = models.JSONField()
    status = models.PositiveSmallIntegerField(default=201)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['owner', 'scope', 'key'], name='unique_mutation')]

class AuthAttempt(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    window = models.BigIntegerField()
    count = models.PositiveIntegerField(default=0)

class LiveSupplierProfile(models.Model):
    inn = models.CharField(max_length=12, primary_key=True)
    profile = models.JSONField()
    checked_at = models.DateTimeField()

class SourceRefreshJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    inn = models.CharField(max_length=12, unique=True)
    status = models.CharField(max_length=20, default='queued')
    attempts = models.PositiveIntegerField(default=0)
    lease_token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    available_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    checked_at = models.DateTimeField(null=True)
    next_allowed_at = models.DateTimeField(null=True)
    input_hash = models.CharField(max_length=64, default='')
    message = models.CharField(max_length=500, default='Обновление сведений ожидает обработки.')
    class Meta:
        indexes = [models.Index(fields=['status', 'available_at'], name='source_status_available')]

class SourceEvidenceBlob(models.Model):
    content_hash = models.CharField(max_length=64, primary_key=True)
    body = models.BinaryField()
    size = models.PositiveIntegerField()
    url = models.TextField()
    fetched_at = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

class SourceEvidenceBudget(models.Model):
    """Single locked row bounds deduplicated evidence storage across workers."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    used_bytes = models.PositiveBigIntegerField(default=0)
