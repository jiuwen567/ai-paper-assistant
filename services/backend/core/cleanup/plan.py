from collections import defaultdict

from django.db.models.deletion import Collector
from rest_framework.exceptions import ValidationError

from core import models as m
from core.common.digests import digest
from core.manuscripts.service import manuscript_for, publish, revision_data

OWNERS = {
    m.ParseRun: ["job"],
    m.ReadingRecord: ["job"],
    m.ReviewRecord: ["job"],
    m.ReviewFinding: ["review"],
    m.ExpressionSuggestion: ["job"],
    m.ExportSource: ["snapshot"],
    m.ExportFile: ["snapshot"],
    m.ExportSnapshot: ["job"],
    m.FeedbackTaskRevision: ["task"],
    m.FeedbackCandidateDecision: ["task"],
    m.RevisionBlock: ["revision"],
    m.ImpactItem: ["run"],
}


MAX_RECORDS = 50000


def contains_id(value, identifiers):
    if isinstance(value, dict):
        return any(contains_id(child, identifiers) for child in value.values())
    if isinstance(value, list):
        return any(contains_id(child, identifiers) for child in value)
    return isinstance(value, str) and value in identifiers


class CleanupCollector(Collector):
    def can_fast_delete(self, *args, **kwargs):
        # 需要完整枚举文件、引用和业务产物，不能跳过 fast-delete 子表。
        return False

    def include(self, queryset):
        self.collect(queryset, fail_on_restricted=False)

    def identifiers(self):
        return {
            str(obj.pk)
            for model, objects in self.data.items()
            if model._meta.pk.get_internal_type() == "UUIDField"
            for obj in objects
        }

    def check_size(self):
        if sum(len(items) for items in self.data.values()) > MAX_RECORDS:
            raise ValidationError("清理范围超过单次 50000 条记录，请由维护者分批整理后再试。")


class Plan:
    def __init__(self, project, material=None):
        self.project = project
        self.material = material
        self.collector = CleanupCollector(using="default")
        if material is None:
            self.collector.include(m.Project.objects.filter(pk=project.pk))
        else:
            self.collector.include(m.Material.objects.filter(pk=material.pk, project=project))
            self.expand_material()
        self.collector.check_size()

    def expand_material(self):
        collector = self.collector
        jobs = list(m.Job.objects.filter(project=self.project))
        disclosures = list(m.DisclosureRevision.objects.filter(project=self.project))
        imports = list(
            m.ManuscriptRevision.objects.filter(manuscript__project=self.project, origin="import")
        )
        snapshots = list(m.ExportSnapshot.objects.filter(project=self.project))
        impacts = list(
            m.ImpactRun.objects.filter(change__source_version__material__project=self.project)
        )
        items = list(
            m.ImpactItem.objects.filter(run__change__source_version__material__project=self.project)
        )
        seen = set()
        while True:
            before = sum(len(rows) for rows in collector.data.values())
            collector.check_size()
            ids = collector.identifiers()
            for model, objects, field in [
                (m.Job, jobs, "input_snapshot"),
                (m.DisclosureRevision, disclosures, "facts"),
                (m.ManuscriptRevision, imports, "source"),
                (m.ExportSnapshot, snapshots, "content"),
                (m.ImpactRun, impacts, "source_snapshot"),
                (m.ImpactItem, items, "snapshot"),
            ]:
                selected = [obj.pk for obj in objects if contains_id(getattr(obj, field), ids)]
                collector.include(model.objects.filter(pk__in=selected))
            # 导入来源固定在 ContentBlock 外键；引用/采纳则从产生的版本向后追踪。
            minimum = defaultdict(lambda: 10**18)
            for citation in list(collector.data[m.ManuscriptCitation]):
                block = citation.block_version
                minimum[block.block_id] = min(minimum[block.block_id], block.number)
            decisions = list(collector.data[m.ExpressionDecision])
            for decision in decisions:
                if decision.manuscript_revision_id:
                    adopted = (
                        decision.manuscript_revision.items.filter(
                            block_id=decision.suggestion.block_version.block_id
                        )
                        .select_related("block_version")
                        .first()
                    )
                    if adopted:
                        block = adopted.block_version
                        minimum[block.block_id] = min(minimum[block.block_id], block.number)
            for block_id, number in minimum.items():
                collector.include(
                    m.BlockVersion.objects.filter(block_id=block_id, number__gte=number)
                )
            # RESTRICT 仍保留正常编辑保护；仅已确认清理会显式扩展依赖集合。
            for model, fields in list(collector.restricted_objects.items()):
                for objects in list(fields.values()):
                    collector.include(model.objects.filter(pk__in=[obj.pk for obj in objects]))
            for model, fields in OWNERS.items():
                for obj in list(collector.data[model]):
                    identity = (model, obj.pk)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    for name in fields:
                        field = model._meta.get_field(name)
                        pk = getattr(obj, field.attname)
                        if pk is not None:
                            collector.include(field.related_model.objects.filter(pk=pk))
            if before == sum(len(rows) for rows in collector.data.values()):
                break

    def manifest(self):
        targets = {
            model._meta.model_name: sorted(str(obj.pk) for obj in rows)
            for model, rows in self.collector.data.items()
            if rows
        }
        objects = {}
        for model in [m.MaterialVersion, m.ExportFile]:
            for obj in self.collector.data[model]:
                target = {"bucket": obj.bucket, "object_key": obj.object_key}
                objects[digest(target)] = target
        if self.material is None:
            # 已删业务行的旧清理也可能仍有失败对象，项目删除必须接管这些已登记路径。
            for previous in m.CleanupRequest.objects.filter(project_id=self.project.pk):
                objects.update(previous.manifest["objects"])
        return {
            "schema": 1,
            "project_id": str(self.project.pk),
            "material_id": str(self.material.pk) if self.material else None,
            "targets": targets,
            "objects": objects,
        }

    def preview(self):
        manifest = self.manifest()
        selected = {str(obj.pk) for obj in self.collector.data[m.BlockVersion]}
        manuscript = manuscript_for(self.project)
        current = revision_data(manuscript.current_revision if manuscript else None)
        removed = [block for block in current["blocks"] if block["version_id"] in selected]
        value = {"manifest": manifest, "manuscript_version": current["version"]}
        return {
            "token": digest(value),
            "counts": {name: len(ids) for name, ids in manifest["targets"].items()},
            "objects": len(manifest["objects"]),
            "removed_blocks": removed,
            "manuscript_version": current["version"],
        }

    def delete_database(self, user, request_id):
        # 当前稿保留未受影响块，删除操作只移除预览列明的派生正文，不自动补写或恢复旧文。
        if self.material:
            manuscript = manuscript_for(self.project)
            revisions = {obj.pk for obj in self.collector.data[m.ManuscriptRevision]}
            if manuscript and manuscript.current_revision_id in revisions:
                current = revision_data(manuscript.current_revision)
                deleted = {str(obj.pk) for obj in self.collector.data[m.BlockVersion]}
                retained = [
                    block for block in current["blocks"] if block["version_id"] not in deleted
                ]
                publish(
                    manuscript,
                    user,
                    {"request_key": f"cleanup:{request_id}"},
                    digest({"cleanup": str(request_id)}),
                    current["research"],
                    retained,
                    origin="cleanup",
                    source={"cleanup_id": str(request_id)},
                )
                for key in list(self.collector.field_updates):
                    if key[0].model is m.Manuscript and key[0].name == "current_revision":
                        del self.collector.field_updates[key]
        # 删除任务本身使下一次租约/权限检查停止；不要新增清单外的取消事件。
        return self.collector.delete()
