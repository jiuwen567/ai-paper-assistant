import type { GlobalThemeOverrides } from 'naive-ui';

// 所有工作区共用一套主题；业务组件不重新定义控件颜色和尺寸。
export const theme: GlobalThemeOverrides = {
  common: {
    primaryColor: '#303c49', primaryColorHover: '#48596a', primaryColorPressed: '#202c39', primaryColorSuppl: '#303c49',
    textColorBase: '#24282e', textColor1: '#24282e', textColor2: '#525b66', textColor3: '#77808b',
    bodyColor: '#f7f8fa', cardColor: '#ffffff', borderColor: '#e2e5e9', dividerColor: '#eceef1',
    borderRadius: '6px', fontSize: '14px', fontWeightStrong: '600',
    fontFamily: '"PingFang SC", "Microsoft YaHei", system-ui, sans-serif',
    heightMedium: '36px', heightSmall: '30px',
  },
  Button: { fontWeight: '500' },
  Menu: { itemHeight: '40px', itemColorActive: '#e9edf2', itemColorActiveHover: '#e3e8ef', itemTextColorActive: '#243447', itemIconColorActive: '#243447' },
};
