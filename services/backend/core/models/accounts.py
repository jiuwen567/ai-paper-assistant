from django.conf import settings
from django.db import models


class WechatIdentity(models.Model):
    app_id = models.CharField(max_length=64)
    open_id = models.CharField(max_length=128)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE)
    bound_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["app_id", "open_id"], name="unique_wechat_identity"),
            models.UniqueConstraint(fields=["app_id", "user"], name="unique_user_wechat_app"),
        ]


class WechatBinding(models.Model):
    identity = models.ForeignKey("WechatIdentity", on_delete=models.CASCADE)
    code_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True)


class WechatSession(models.Model):
    identity = models.ForeignKey("WechatIdentity", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True)
