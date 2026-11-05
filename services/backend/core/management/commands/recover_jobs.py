from django.core.management.base import BaseCommand

from core.jobs import recover_jobs


class Command(BaseCommand):
    help = "恢复等待入队的任务，将过期执行标记为可重试失败。"

    def handle(self, *args, **options):
        self.stdout.write(f"已检查 {recover_jobs()} 项任务。")
