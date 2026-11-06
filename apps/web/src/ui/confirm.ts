import { useDialog } from 'naive-ui';

export function useConfirm() {
  const dialog = useDialog();
  return (content: string) => new Promise<boolean>(resolve => {
    dialog.warning({ title: '未保存的修改', content, positiveText: '放弃修改', negativeText: '继续编辑',
      onPositiveClick: () => resolve(true), onNegativeClick: () => resolve(false),
      onClose: () => resolve(false), onMaskClick: () => resolve(false), onEsc: () => resolve(false),
    });
  });
}
