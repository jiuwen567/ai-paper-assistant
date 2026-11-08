from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import APIException

from core.materials.service import fail_upload, reconcile_upload
from core.models import MaterialVersion


class Command(BaseCommand):
    help = "对账已登记且已上传但尚未发布的对象；不扫描或删除其他存储对象。"

    def handle(self, *args, **options):
        versions = list(
            MaterialVersion.objects.exclude(status="available")
            .exclude(sha256="")
            .filter(Q(lease_until=None) | Q(lease_until__lte=timezone.now()))
            .order_by("updated_at")[:100]
        )
        for version in versions:
            try:
                reconcile_upload(version.pk)
            except APIException:
                fail_upload(version.pk, version.generation, "authorization_changed")
        available = MaterialVersion.objects.filter(
            pk__in=[v.pk for v in versions], status="available"
        ).count()
        self.stdout.write(f"检查 {len(versions)} 项，已可用 {available} 项，其余保留错误状态。")
