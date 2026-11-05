"""本地 CPU 嵌入；只在显式准备命令中下载，业务请求不访问模型仓库。"""

import hashlib
import json
import math
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path

from django.conf import settings
from fastembed import TextEmbedding

from core.parsing import ParseFailure

MODELS = {"BAAI/bge-small-zh-v1.5": 512, "BAAI/bge-small-en-v1.5": 384}
PIPELINE_VERSION = (
    f"char256-v1/fastembed-{version('fastembed')}/ort-{version('onnxruntime')}"
    f"/tokenizers-{version('tokenizers')}"
)
SEGMENT_SIZE = 256


def sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


def directory_digest(directory):
    digest = hashlib.sha256()
    # 快照文件为模型权重、分词器与配置；摘要不含机器路径。
    for path in sorted(Path(directory).rglob("*")):
        if path.is_file() and ".cache" not in path.relative_to(directory).parts:
            digest.update(str(path.relative_to(directory)).encode())
            with path.open("rb") as stream:
                while data := stream.read(1024 * 1024):
                    digest.update(data)
    return digest.hexdigest()


def manifest_path(model_name):
    if model_name not in MODELS:
        raise ParseFailure("embedding_model", "嵌入模型不在服务端允许列表中。")
    return Path(settings.EMBEDDING_CACHE_DIR) / f"{model_name.replace('/', '--')}.json"


def prepare(model_name):
    manifest = manifest_path(model_name)
    model = TextEmbedding(
        model_name=model_name, cache_dir=str(manifest.parent), threads=2, cuda=False
    )
    directory = Path(model.model._model_dir)
    data = {
        "model_name": model_name,
        "dimension": MODELS[model_name],
        "artifact_digest": directory_digest(directory),
        "directory": str(directory.relative_to(manifest.parent.resolve())),
        "runtime": version("fastembed"),
        "pipeline_version": PIPELINE_VERSION,
    }
    temporary = manifest.with_suffix(".tmp")
    temporary.write_text(json.dumps(data), encoding="utf-8")
    temporary.replace(manifest)
    load_model.cache_clear()
    return data


def configuration():
    model_name = settings.EMBEDDING_MODEL
    path = manifest_path(model_name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (
            data["model_name"] != model_name
            or data["dimension"] != MODELS[model_name]
            or data["runtime"] != version("fastembed")
            or data["pipeline_version"] != PIPELINE_VERSION
        ):
            raise ValueError
        return data
    except (OSError, ValueError, KeyError, TypeError):
        raise ParseFailure(
            "embedding_not_ready", "本地检索模型未就绪，请管理员准备后重试。", True
        ) from None


@lru_cache(maxsize=2)
def load_model(model_name, artifact_digest, directory, cache_dir):
    path = (Path(cache_dir) / directory).resolve()
    if (
        not path.is_relative_to(Path(cache_dir).resolve())
        or directory_digest(path) != artifact_digest
    ):
        raise ParseFailure("embedding_artifact", "本地模型文件校验失败，请重新准备并重建索引。")
    return TextEmbedding(
        model_name=model_name,
        specific_model_path=str(path),
        cache_dir=cache_dir,
        local_files_only=True,
        threads=2,
        cuda=False,
    )


def encode(texts, config, *, query=False):
    if config != configuration():
        raise ParseFailure("embedding_changed", "嵌入模型已变化，请重建索引。")
    model = load_model(
        config["model_name"],
        config["artifact_digest"],
        config["directory"],
        str(settings.EMBEDDING_CACHE_DIR),
    )
    vectors = model.query_embed(texts) if query else model.embed(texts, batch_size=8)
    result = [vector.tolist() for vector in vectors]
    if len(result) != len(texts) or any(
        len(vector) != config["dimension"]
        or not all(math.isfinite(value) for value in vector)
        or sum(value * value for value in vector) == 0
        for vector in result
    ):
        raise ParseFailure("embedding_result", "嵌入结果格式无效，未发布索引。")
    return result
