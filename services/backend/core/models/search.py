import uuid

from django.db import models
from pgvector.django import VectorField


class EmbeddingIndex(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.OneToOneField("Job", on_delete=models.CASCADE, related_name="embedding_index")
    model_name = models.CharField(max_length=128)
    dimension = models.PositiveIntegerField()
    artifact_digest = models.CharField(max_length=64)
    pipeline_version = models.CharField(max_length=64)
    published_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ChunkEmbedding(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    index = models.ForeignKey("EmbeddingIndex", on_delete=models.CASCADE, related_name="segments")
    chunk = models.ForeignKey("SourceChunk", on_delete=models.CASCADE, related_name="embeddings")
    start = models.PositiveIntegerField()
    end = models.PositiveIntegerField()
    text_sha256 = models.CharField(max_length=64)
    vector = VectorField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["index", "chunk", "start"], name="unique_embedding_segment"
            ),
            models.CheckConstraint(
                condition=models.Q(end__gt=models.F("start")), name="embedding_nonempty_segment"
            ),
        ]
