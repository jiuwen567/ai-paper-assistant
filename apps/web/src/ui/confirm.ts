import { useDialog } from 'naive-ui';

export function useConfirm() {
  const dialog = useDialog();
  return (content: string, labels?: { title: string; positiveText: string; negativeText: string }) => new Promise<boolean>(resolve => {
    dialog.warning({ title: labels?.title ?? '未保存的修改', content, positiveText: labels?.positiveText ?? '放弃修改', negativeText: labels?.negativeText ?? '继续编辑',
      onPositiveClick: () => resolve(true), onNegativeClick: () => resolve(false),
      onClose: () => resolve(false), onMaskClick: () => resolve(false), onEsc: () => resolve(false),
    });
  });
}
