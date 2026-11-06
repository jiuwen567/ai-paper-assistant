import type { App } from 'vue';
import { NButton, NTag, NEmpty, NAlert, NCollapse, NCollapseItem } from 'naive-ui';
import UiDisclosure from './UiDisclosure.vue';
import UiInput from './UiInput.vue';
import UiSelect from './UiSelect.vue';
import UiCheckbox from './UiCheckbox.vue';
const components = { UiDisclosure, NButton, NTag, NEmpty, NAlert, NCollapse, NCollapseItem, UiInput, UiSelect, UiCheckbox };
export function installUI(app: App) { for (const [name, component] of Object.entries(components)) app.component(name, component); }
