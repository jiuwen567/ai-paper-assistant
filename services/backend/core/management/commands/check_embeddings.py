from django.core.management.base import BaseCommand, CommandError

from core.embeddings import configuration, encode
from core.parsing import ParseFailure


class Command(BaseCommand):
    help = "使用自制短文本验证嵌入 API 配置和向量维度，不读取项目资料。"

    def handle(self, *args, **options):
        try:
            config = configuration()
            encode(["嵌入 API 连通性检查。", "这是自制的软件验收文本。"], config)
        except ParseFailure as error:
            raise CommandError(f"{error.code}：{error.message}") from None
        self.stdout.write(f"嵌入 API 检查通过：{config['model_name']}，{config['dimension']} 维。")
