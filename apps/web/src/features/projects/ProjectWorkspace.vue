<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { ApiError } from "@/api/client";
import type { Project } from "./types";
import ProjectSettings from "./ProjectSettings.vue";
import { workspaceTabs } from "@/app/workspaces";
import UiTabs from "@/ui/UiTabs.vue";
import OverviewPanel from "@/features/projects/OverviewPanel.vue";
import LibraryPanel from "@/features/library/LibraryPanel.vue";
import ReadingPanel from "@/features/reading/ReadingPanel.vue";
import ReviewPanel from "@/features/reviews/ReviewPanel.vue";
import ExpressionPanel from "@/features/expressions/ExpressionPanel.vue";
import DisclosurePanel from "@/features/disclosures/DisclosurePanel.vue";
import ExportPanel from "@/features/exports/ExportPanel.vue";
import FeedbackPanel from "@/features/feedback/FeedbackPanel.vue";
import ImpactPanel from "@/features/impacts/ImpactPanel.vue";
import GraphPanel from "@/features/graph/GraphPanel.vue";
import ManuscriptPanel from "@/features/manuscripts/ManuscriptPanel.vue";
import JobsPanel from "@/features/jobs/JobsPanel.vue";
import MaterialsPanel from "@/features/materials/MaterialsPanel.vue";
const props = defineProps<{
  project: Project;
  userId: number;
  workspace: string;
  tab?: string;
  disabled: boolean;
}>();
const emit = defineEmits<{
  navigate: [key: string, tab?: string];
  accessLost: [error: ApiError];
  dirtyChange: [dirty: boolean];
  saved: [project: Project];
  reload: [];
  back: [];
}>();
const materialTab = ref("files"),
  reviewTab = ref("diagnosis"),
  evidenceTab = ref("graph"),
  deliveryTab = ref("export");
const readingDirty = ref(false),
  manuscriptDirty = ref(false),
  disclosureDirty = ref(false);
const feedbackDirty = ref(false),
  graphDirty = ref(false),
  impactDirty = ref(false),
  exportDirty = ref(false);
const settingsDirty = ref<Record<string, boolean>>({});
const dirty = computed(
  () =>
    readingDirty.value ||
    manuscriptDirty.value ||
    disclosureDirty.value ||
    feedbackDirty.value ||
    graphDirty.value ||
    impactDirty.value ||
    exportDirty.value ||
    Object.values(settingsDirty.value).some(Boolean),
);
watch(dirty, (value) => emit("dirtyChange", value));
const tabs = {
  materials: materialTab,
  review: reviewTab,
  evidence: evidenceTab,
  delivery: deliveryTab,
};
watch(
  () => [props.workspace, props.tab],
  () => {
    const tab = tabs[props.workspace as keyof typeof tabs];
    if (tab) tab.value = props.tab || workspaceTabs[props.workspace]![0]!;
  },
  { immediate: true },
);
for (const [key, tab] of Object.entries(tabs)) {
  watch(tab, (value) => {
    if (props.workspace === key && value !== (props.tab || workspaceTabs[key]![0]))
      emit("navigate", key, value);
  });
}
</script>
<template>
  <div :inert="disabled">
    <OverviewPanel
      v-if="workspace === 'overview'"
      :key="project.id"
      :project="project"
      @navigate="(key, tab) => emit('navigate', key, tab)"
      @access-lost="(cause) => emit('accessLost', cause)"
    />
    <div v-show="workspace === 'materials'" class="workspace-panel">
      <UiTabs
        class="workspace-tabs"
        v-model="materialTab"
        :options="[
          { value: 'files', label: '文件材料' },
          { value: 'library', label: '检索与证据卡' },
          { value: 'reading', label: 'AI 阅读' },
        ]"
      />
      <MaterialsPanel
        v-show="materialTab === 'files'"
        :key="project.id"
        :project="project"
        :user-id="userId"
        @access-lost="(cause) => emit('accessLost', cause)"
      />
      <LibraryPanel
        v-show="materialTab === 'library'"
        :key="project.id"
        :project="project"
        @access-lost="(cause) => emit('accessLost', cause)"
      />
      <ReadingPanel
        @dirty-change="readingDirty = $event"
        v-show="materialTab === 'reading'"
        :key="project.id"
        :project="project"
        @access-lost="(cause) => emit('accessLost', cause)"
      />
    </div>
    <div v-show="workspace === 'review'" class="workspace-panel">
      <UiTabs
        class="workspace-tabs"
        v-model="reviewTab"
        :options="[
          { value: 'diagnosis', label: '原稿诊断' },
          { value: 'expression', label: '表达建议' },
        ]"
      />
      <ReviewPanel
        v-show="reviewTab === 'diagnosis'"
        :key="project.id"
        :project="project"
        @access-lost="(cause) => emit('accessLost', cause)"
      />
      <ExpressionPanel
        v-show="reviewTab === 'expression'"
        :key="project.id"
        :project="project"
        @access-lost="(cause) => emit('accessLost', cause)"
      />
    </div>
    <div v-show="workspace === 'evidence'" class="workspace-panel">
      <UiTabs
        class="workspace-tabs"
        v-model="evidenceTab"
        :options="[
          { value: 'graph', label: '依据关系' },
          { value: 'impact', label: '变更影响' },
        ]"
      />
      <GraphPanel
        v-show="evidenceTab === 'graph'"
        :key="project.id"
        :project="project"
        @dirty-change="graphDirty = $event"
        @access-lost="(cause) => emit('accessLost', cause)"
      />
      <ImpactPanel
        v-show="evidenceTab === 'impact'"
        :key="project.id"
        :project="project"
        @dirty-change="impactDirty = $event"
        @access-lost="(cause) => emit('accessLost', cause)"
      />
    </div>
    <div v-show="workspace === 'delivery'" class="workspace-panel">
      <UiTabs
        class="workspace-tabs"
        v-model="deliveryTab"
        :options="[
          { value: 'export', label: '导出文档' },
          { value: 'disclosure', label: 'AI 使用说明' },
        ]"
      />
      <ExportPanel
        v-show="deliveryTab === 'export'"
        :key="project.id"
        :project="project"
        :manuscript-dirty="manuscriptDirty"
        :disclosure-dirty="disclosureDirty"
        @dirty-change="exportDirty = $event"
        @access-lost="(cause) => emit('accessLost', cause)"
      />
      <DisclosurePanel
        v-show="deliveryTab === 'disclosure'"
        :key="project.id"
        :project="project"
        @dirty-change="disclosureDirty = $event"
        @access-lost="(cause) => emit('accessLost', cause)"
      />
    </div>
    <ManuscriptPanel
      :active="workspace === 'writing'"
      v-show="workspace === 'writing'"
      :key="project.id"
      :project="project"
      @dirty-change="manuscriptDirty = $event"
      @access-lost="(cause) => emit('accessLost', cause)"
    />
    <FeedbackPanel
      v-show="workspace === 'feedback'"
      :key="project.id"
      :project="project"
      @dirty-change="feedbackDirty = $event"
      @access-lost="(cause) => emit('accessLost', cause)"
    />
    <JobsPanel
      v-show="workspace === 'jobs'"
      :key="project.id"
      :project="project"
      @access-lost="(cause) => emit('accessLost', cause)"
    />

    <ProjectSettings
      v-show="workspace === 'settings'"
      :project="project"
      :disabled="disabled"
      @saved="emit('saved', $event)"
      @access-lost="emit('accessLost', $event)"
      @dirty-change="(key, value) => (settingsDirty[key] = value)"
      @reload="emit('reload')"
      @back="emit('back')"
    />
  </div>
</template>
