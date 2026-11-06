# Web 界面约定

Web 使用 Vue 3、[Naive UI](https://github.com/tusen-ai/naive-ui) 和 [Lucide](https://lucide.dev/guide/vue)。新页面复用这套组件，不另建按钮、表单、弹窗或导航样式。

## 工作台

进入项目默认打开原稿写作。新建项目先填写项目设置与 AI 规则。左侧导航区分写作、材料、审阅、反馈、依据、导出、后台任务和项目设置；手机端通过顶部导航按钮切换。

材料、审阅、依据和导出使用页内标签分组。切换工作区只隐藏已挂载面板，保留尚未保存的作者草稿。离开项目、退出及覆盖草稿需要确认；切换工作区不视为保存。

原稿以正文为主，桌面显示章节目录。块类型、移动、插入与删除在编辑位置显示，手机端保持可见。研究说明、DOCX 导入和历史对照收在折叠面板中。作者仍逐块编辑和保存明确版本，模型不直接修改原稿。

## 组件和主题

- `src/ui/theme.ts` 定义公共颜色、字号、尺寸与圆角，通过 `NConfigProvider` 应用；中文提示使用 `zhCN`。
- 按钮、导航、标签页、抽屉、文件上传、状态和确认框直接使用 Naive UI。图标使用 Lucide，尺寸通常为 16 或 18 px。
- `UiInput` 将现有字符串/数字模型映射到 `NInput`，保留原生 required、min/max、pattern 等校验和可访问名称。
- `UiSelect` 使用 `NSelect`，保留必填校验与 change 语义；`UiCheckbox` 使用 `NCheckbox`，支持布尔值与选择数组。这些适配层只处理表单语义，不承载业务请求或权限判断。
- `UiDisclosure` 使用 `NCollapse`，统一折叠外观。作者放弃草稿统一通过 `useConfirm` 和 `NDialogProvider` 确认。
- 控件必须显式传递 disabled，不能只依赖原生 fieldset 对自定义组件的禁用行为。标签、键盘焦点、错误提示和只读状态必须保留。

视觉采用灰白界面与墨色强调，4 px 间距基准、三级文本颜色。正文和原句/建议对照是页面重点，不加入虚构统计、装饰性看板或与任务无关的卡片。

设计审查参考 [unslop](https://github.com/heydamir/unslop)，作者 Damir Sokolovsky（[@heydamir](https://github.com/heydamir)），许可 CC BY 4.0。本项目按其间距、颜色、图标、文案、排版、布局、细节与动效检查方法调整已有业务界面；没有复制示例页面。Skill 是开发辅助，不作为应用运行依赖。

## 验证

`pnpm --filter @paper/web check` 和 `build` 检查类型与构建；`E2E_USE_COMPOSE=1 pnpm --filter @paper/web test:e2e` 通过实际导航验证桌面和手机端。浏览器场景保留真实 API、Worker、权限、版本冲突和作者确认检查，模型输出使用明确的自制夹具。

预览只使用自制文字和专用本地账号，不把账号、密钥或真实论文放入仓库。CI 保持现有轻量检查，完整业务浏览器回归在本地运行。
