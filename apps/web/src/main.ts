import { createApp } from "vue";
import App from "./App.vue";
import "./style.css";
import { installUI } from "./ui/components";

createApp(App).use(installUI).mount("#app");
