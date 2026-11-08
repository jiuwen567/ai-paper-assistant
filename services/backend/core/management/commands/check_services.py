import json

from django.core.management.base import BaseCommand, CommandError

from core.system.health import readiness


class Command(BaseCommand):
    help = "检查数据库迁移、pgvector、Neo4j、S3、Redis 与 Worker"

    def handle(self, *args, **options):
        result = readiness()
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
        if result["status"] != "ok":
            raise CommandError("存在不可用服务，请检查容器状态和本地配置。")
