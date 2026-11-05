from django.core.management.base import BaseCommand, CommandError

from worker.tasks import ping


class Command(BaseCommand):
    help = "通过真实 broker 投递诊断任务并验证 Worker 返回结果"

    def handle(self, *args, **options):
        try:
            result = ping.delay()
            payload = result.get(timeout=15)
            result.forget()
        except Exception as error:
            raise CommandError(f"Worker 联调失败：{type(error).__name__}") from None
        if payload != {"status": "ok", "service": "worker"}:
            raise CommandError("Worker 返回值不符合预期")
        self.stdout.write(self.style.SUCCESS("Worker 任务投递、执行及结果读取通过"))
