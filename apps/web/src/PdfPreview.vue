<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import type { PDFDocumentLoadingTask } from "pdfjs-dist";
const props = defineProps<{ url: string; page: number }>();
const canvas = ref<HTMLCanvasElement | null>(null);
const busy = ref(false);
const error = ref("");
const rendered = ref(false);
let mounted = true;
let task: PDFDocumentLoadingTask | undefined;
async function render() {
  if (busy.value) return;
  busy.value = true; error.value = ""; rendered.value = false;
  try {
    await task?.destroy();
    const pdfjs = await import("pdfjs-dist");
    if (!mounted) return;
    pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
    const assets = `${import.meta.env.BASE_URL}pdfjs/`;
    task = pdfjs.getDocument({ cMapUrl: `${assets}cmaps/`, cMapPacked: true, standardFontDataUrl: `${assets}standard_fonts/`, wasmUrl: `${assets}wasm/`, url: props.url.split("#")[0], enableXfa: false, useSystemFonts: true, disableRange: true });
    const document = await task.promise;
    const page = await document.getPage(props.page);
    if (!mounted || !canvas.value) return;
    const original = page.getViewport({ scale: 1 });
    const scale = Math.min(2, 1400 / original.width, Math.sqrt(4_000_000 / (original.width * original.height)));
    const viewport = page.getViewport({ scale });
    canvas.value.width = Math.ceil(viewport.width);
    canvas.value.height = Math.ceil(viewport.height);
    await page.render({ canvas: canvas.value, viewport }).promise;
    if (mounted) rendered.value = true;
  } catch {
    if (mounted) error.value = "PDF 预览加载失败，可重试或下载原件。";
  } finally { busy.value = false; }
}
onMounted(render);
onUnmounted(() => { mounted = false; void task?.destroy(); });
</script>

<template>
  <div class="source-preview" :aria-busy="busy">
    <p v-if="busy" role="status">加载 PDF 页…</p>
    <p v-if="error" role="alert">{{ error }} <button @click="render">重试预览</button></p>
    <canvas ref="canvas" v-show="rendered" role="img" :aria-label="`PDF 文件第 ${page} 页`" :data-rendered="rendered" />
  </div>
</template>
