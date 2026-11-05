from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.embeddings import MODELS, prepare


class Command(BaseCommand):
    help = "显式下载并校验本地嵌入模型；不读取任何项目资料。"

    def add_arguments(self, parser):
        parser.add_argument("--model", choices=MODELS, default=settings.EMBEDDING_MODEL)

    def handle(self, *args, **options):
        try:
            config = prepare(options["model"])
        except Exception as error:
            raise CommandError(f"模型准备失败：{type(error).__name__}") from None
        self.stdout.write(
            f"模型已准备：{config['model_name']}，{config['dimension']} 维，"
            f"摘要 {config['artifact_digest']}"
        )
