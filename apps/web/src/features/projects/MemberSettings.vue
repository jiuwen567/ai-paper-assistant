<script setup lang="ts">
import { onMounted, ref } from "vue";
import { request, type ApiError } from "@/api/client";
import type { Page } from "@/api/types";
import { useAsyncState } from "@/composables/useAsyncState";
import AsyncFeedback from "@/ui/AsyncFeedback.vue";
import { roleName } from "@/app/workspaces";
import type { Member, Project } from "./types";
const props = defineProps<{ project: Project; disabled?: boolean }>();
const emit = defineEmits<{ saved: [project: Project]; accessLost: [error: ApiError] }>();
const { busy, error, message, perform, isActive } = useAsyncState((cause) => emit("accessLost", cause));
const members = ref<Page<Member> | null>(null);
const memberPage = ref(1);
const memberName = ref("");
const memberRole = ref<Member["role"]>("reviewer");
async function loadMembers(page = 1) {
  const result = await request<Page<Member>>(`projects/${props.project.id}/members/?page=${page}`);
  if (!isActive()) return;
  members.value = result;
  memberPage.value = page;
}
async function saveMember() {
  const project = await request<Project>(`projects/${props.project.id}/members/`, "POST", {
    username: memberName.value,
    role: memberRole.value,
    version: props.project.version,
  });
  if (!isActive()) return;
  emit("saved", project);
  memberName.value = "";
  await loadMembers();
  message.value = "成员权限已保存。";
}
async function removeMember(member: Member) {
  const project = await request<Project>(
    `projects/${props.project.id}/members/${member.user_id}/`,
    "DELETE",
    { version: props.project.version },
  );
  if (!isActive()) return;
  emit("saved", project);
  await loadMembers();
  message.value = "成员访问权限已移除。";
}
onMounted(() => perform(loadMembers));
</script>
<template>
  <AsyncFeedback :busy="busy" :error="error" :message="message" />
  <section>
    <h2>项目成员</h2>
    <p>{{ project.owner_name }} · 创建者 / 作者</p>
    <ul class="member-list">
      <li v-for="member in members?.results" :key="member.user_id">
        <span>{{ member.username }} · {{ roleName(member.role) }}</span>
        <NButton
          v-if="project.is_owner"
          :aria-label="`移除 ${member.username}`"
          @click="perform(() => removeMember(member))"
          :disabled="busy || disabled"
          >移除</NButton
        >
      </li>
    </ul>
    <div v-if="members && (members.next || members.previous)" class="actions" aria-label="成员分页">
      <NButton
        @click="perform(() => loadMembers(memberPage - 1))"
        :disabled="busy || !members.previous"
        >上一页成员</NButton
      >
      <NButton @click="perform(() => loadMembers(memberPage + 1))" :disabled="busy || !members.next"
        >下一页成员</NButton
      >
    </div>
    <form v-if="project.is_owner" class="editor" @submit.prevent="perform(saveMember)">
      <fieldset :disabled="busy || disabled">
        <label
          >成员用户名<UiInput
            v-model="memberName"
            required
            maxlength="150"
            :disabled="busy || disabled"
            :aria-label="'成员用户名'"
        /></label>
        <label
          >成员角色<UiSelect
            v-model="memberRole"
            :disabled="busy || disabled"
            :options="[
              { value: 'reviewer', label: '审阅者（只读）' },
              { value: 'author', label: '作者（可编辑项目与规则）' },
            ]"
            :aria-label="'成员角色'"
        /></label>
        <NButton attr-type="submit" :disabled="busy || disabled" type="primary"
          >添加或更新成员</NButton
        >
      </fieldset>
    </form>
  </section>
</template>
