from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from core.common.serializers import StrictSerializer
from core.models import Manuscript, RevisionBlock
from core.projects.access import VersionConflict


class LocationInput(StrictSerializer):
    manuscript_version = serializers.IntegerField(min_value=1, allow_null=True)
    block_id = serializers.UUIDField(allow_null=True)

    def validate(self, data):
        if (data["manuscript_version"] is None) != (data["block_id"] is None):
            raise ValidationError("稿件版本和正文块须同时选择，或同时留空。")
        return data


def select_location(project_id, data):
    if data["manuscript_version"] is None:
        return None, None
    manuscript = get_object_or_404(
        Manuscript.objects.select_related("current_revision"), project_id=project_id
    )
    revision = manuscript.current_revision
    if revision is None or revision.number != data["manuscript_version"]:
        raise VersionConflict("原稿已有新版本，请重新关联处理位置。")
    item = get_object_or_404(
        revision.items.select_related("block_version"), block_id=data["block_id"]
    )
    return revision, item.block_version


def location_data(revision, block):
    if revision is None:
        return None
    original = revision.items.get(block_version=block)
    manuscript = Manuscript.objects.select_related("current_revision").get(
        pk=revision.manuscript_id
    )
    current = RevisionBlock.objects.filter(
        revision=manuscript.current_revision, block_id=block.block_id
    ).first()
    return {
        "manuscript_version": revision.number,
        "block_id": str(block.block_id),
        "block_version_id": str(block.pk),
        "position": original.position + 1,
        "text": block.text,
        "stale": current is None or current.block_version_id != block.pk,
        "current_version": manuscript.current_revision.number if manuscript.current_revision else 0,
        "current_position": current.position + 1 if current else None,
    }
