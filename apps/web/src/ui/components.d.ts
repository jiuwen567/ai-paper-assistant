export {};
declare module 'vue' {
  export interface GlobalComponents {
    UiDisclosure: typeof import('./UiDisclosure.vue')['default'];
    NButton: typeof import('naive-ui')['NButton'];
    NTag: typeof import('naive-ui')['NTag'];
    NEmpty: typeof import('naive-ui')['NEmpty'];
    NAlert: typeof import('naive-ui')['NAlert'];
    NCollapse: typeof import('naive-ui')['NCollapse'];
    NCollapseItem: typeof import('naive-ui')['NCollapseItem'];
    UiInput: typeof import('./UiInput.vue')['default'];
    UiSelect: typeof import('./UiSelect.vue')['default'];
    UiCheckbox: typeof import('./UiCheckbox.vue')['default'];
  }
}
