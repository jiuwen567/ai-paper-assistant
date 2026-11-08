import { onUnmounted, ref } from "vue";
import { ApiError } from "@/api/client";

export function useAsyncState(onAccessLost?: (error: ApiError) => void | Promise<void>) {
  const busy = ref(false);
  const error = ref("");
  const message = ref("");
  let active = true;
  onUnmounted(() => {
    active = false;
  });

  async function perform(action: () => Promise<void>) {
    if (busy.value || !active) return false;
    busy.value = true;
    error.value = "";
    message.value = "";
    try {
      await action();
      return active;
    } catch (cause) {
      if (!active) return false;
      error.value = cause instanceof Error ? cause.message : "连接失败，请重试。";
      if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
        await onAccessLost?.(cause);
      }
      return false;
    } finally {
      if (active) busy.value = false;
    }
  }
  return { busy, error, message, perform, isActive: () => active };
}
