import { onUnmounted } from "vue";

// 一次请求结束后再计时；卸载后不重排定时器，也不启动重叠请求。
export function usePolling(poll: () => Promise<void>, interval = 2000) {
  let active = true;
  let running = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  async function tick() {
    if (!active) return;
    try {
      await poll();
    } finally {
      if (active) timer = setTimeout(tick, interval);
    }
  }
  function start() {
    if (running || !active) return;
    running = true;
    void tick();
  }
  onUnmounted(() => {
    active = false;
    clearTimeout(timer);
  });
  return { start };
}
