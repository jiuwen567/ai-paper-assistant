import uuid

from django.conf import settings
from django.db import models


class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    name = models.CharField(max_length=120)
    paper_type = models.CharField(max_length=80, blank=True)
    requirements = models.TextField(blank=True)
    template = models.CharField(max_length=120, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class ProjectMember(models.Model):
    class Role(models.TextChoices):
        AUTHOR = "author", "作者"
        REVIEWER = "reviewer", "审阅者"

    project = models.ForeignKey("Project", on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=16, choices=Role.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "user"], name="unique_project_member"),
            models.CheckConstraint(
                condition=models.Q(role__in=["author", "reviewer"]), name="valid_project_role"
            ),
        ]


class ProjectPolicy(models.Model):
    project = models.ForeignKey("Project", on_delete=models.CASCADE, related_name="policies")
    version = models.PositiveIntegerField()
    source = models.CharField(max_length=500, blank=True)
    source_version = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    verified = models.BooleanField(default=False)
    allowed_actions = models.JSONField(default=list)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "version"], name="unique_project_policy"),
            models.CheckConstraint(
                condition=models.Q(verified=True) | models.Q(allowed_actions=[]),
                name="unverified_policy_disables_ai",
            ),
            models.CheckConstraint(
                condition=models.Q(verified=False)
                | (~models.Q(source="") & ~models.Q(source_version="")),
                name="verified_policy_has_source",
            ),
        ]
