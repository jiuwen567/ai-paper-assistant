import { router } from "@/app/router";
import { createApp } from "vue";
import App from "@/app/App.vue";
import "@/app/styles.css";
import { installUI } from "@/ui/components";

createApp(App).use(router).use(installUI).mount("#app");
