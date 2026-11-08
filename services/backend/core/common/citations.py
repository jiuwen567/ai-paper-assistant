import re
from decimal import Decimal, InvalidOperation

from rest_framework import serializers

from core.common.errors import ParseFailure
from core.common.serializers import StrictSerializer


class CitationInput(StrictSerializer):
    chunk_id = serializers.UUIDField()
    quote = serializers.CharField(max_length=600)


def numbers(text):
    try:
        return {
            Decimal(value)
            for value in re.findall(r"(?<![\d.])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", text)
        }
    except InvalidOperation as error:
        raise ParseFailure("reading_number_invalid", "提取数值无法核对。") from error
