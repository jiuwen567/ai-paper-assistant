import hashlib
import json
import math
import struct
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.conf import settings

from core.common.errors import ParseFailure

PIPELINE_VERSION = "char256-v2/embeddings-api-v1"


SEGMENT_SIZE = 256


MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


def endpoint():
    base = settings.EMBEDDING_BASE_URL.rstrip("/")
    try:
        url = urlsplit(base)
        url.port
        valid = (
            url.hostname
            and not url.username
            and not url.password
            and not url.query
            and not url.fragment
            and not any(char.isspace() for char in base)
            and (url.scheme == "https" or (settings.DEBUG and url.scheme == "http"))
        )
    except ValueError:
        valid = False
    if not valid:
        raise ParseFailure("embedding_unconfigured", "请管理员配置有效的嵌入 API 地址。")
    return base + "/embeddings"


def configuration():
    model = settings.EMBEDDING_MODEL.strip()
    dimension = settings.EMBEDDING_DIMENSION
    if not model or len(model) > 128 or not settings.EMBEDDING_API_KEY.strip():
        raise ParseFailure("embedding_unconfigured", "请管理员配置嵌入 API 的模型和密钥。")
    if type(dimension) is not int or not 1 <= dimension <= 16000:
        raise ParseFailure("embedding_unconfigured", "请管理员配置 1–16000 的嵌入向量维度。")
    identity = {
        "endpoint": endpoint(),
        "model": model,
        "revision": settings.EMBEDDING_MODEL_REVISION,
        "dimension": dimension,
        "send_dimensions": settings.EMBEDDING_SEND_DIMENSIONS,
    }
    # 沿用索引摘要字段；API 记录配置空间摘要，不声称持有供应商的权重摘要。
    # 密钥轮换不改变向量空间，地址和密钥不进入客户端可见的任务快照。
    return {
        "model_name": model,
        "dimension": dimension,
        "artifact_digest": sha256(json.dumps(identity, sort_keys=True)),
        "pipeline_version": PIPELINE_VERSION,
        "runtime": "embeddings-api-v1",
        "model_revision": settings.EMBEDDING_MODEL_REVISION,
    }


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # 不将材料和认证头转发到配置之外的端点。


def encode(texts, config, *, query=False):
    if config != configuration():
        raise ParseFailure("embedding_changed", "嵌入模型已变化，请重建索引。")
    if (
        not texts
        or len(texts) > 8
        or any(
            not isinstance(text, str) or not text.strip() or len(text) > SEGMENT_SIZE
            for text in texts
        )
    ):
        raise ParseFailure(
            "embedding_input", "嵌入请求须包含 1–8 个非空文本片段，每段最多 256 字。"
        )
    payload = {"model": config["model_name"], "input": texts, "encoding_format": "float"}
    if settings.EMBEDDING_SEND_DIMENSIONS:
        payload["dimensions"] = config["dimension"]
    request = Request(
        endpoint(),
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + settings.EMBEDDING_API_KEY,
        },
        method="POST",
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        status = error.code
        error.close()
        raise ParseFailure(
            f"embedding_http_{status}",
            f"嵌入 API 请求失败（HTTP {status}），请核对服务配置或稍后重试。",
            status in {408, 429} or status >= 500,
        ) from None
    except (URLError, OSError, HTTPException):
        raise ParseFailure(
            "embedding_unavailable", "嵌入 API 连接失败或超时，请稍后重试。", True
        ) from None
    try:
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError
        data = json.loads(raw)["data"]
        if not isinstance(data, list) or len(data) != len(texts):
            raise ValueError
        result = [None] * len(texts)
        for item in data:
            index, vector = item["index"], item["embedding"]
            if (
                type(index) is not int
                or not 0 <= index < len(texts)
                or result[index] is not None
                or not isinstance(vector, list)
                or len(vector) != config["dimension"]
                or any(type(value) not in (float, int) for value in vector)
            ):
                raise ValueError
            # 按 PostgreSQL vector 的 float32 精度检查溢出、非有限值和零向量。
            vector = [struct.unpack("f", struct.pack("f", value))[0] for value in vector]
            if not all(math.isfinite(value) for value in vector) or not any(vector):
                raise ValueError
            result[index] = vector
        return result
    except (ValueError, KeyError, TypeError, OverflowError, struct.error):
        raise ParseFailure(
            "embedding_result", "嵌入 API 返回的向量格式无效，未发布索引。"
        ) from None
