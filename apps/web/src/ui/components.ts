import type { App } from 'vue';
import { NButton, NTag, NEmpty, NAlert, NCollapse, NCollapseItem } from 'naive-ui';
import UiDisclosure from '@/ui/UiDisclosure.vue';
import UiInput from '@/ui/UiInput.vue';
import UiSelect from '@/ui/UiSelect.vue';
import UiCheckbox from '@/ui/UiCheckbox.vue';
const components = { UiDisclosure, NButton, NTag, NEmpty, NAlert, NCollapse, NCollapseItem, UiInput, UiSelect, UiCheckbox };
export function installUI(app: App) { for (const [name, component] of Object.entries(components)) app.component(name, component); }
