import { createFromIconfontCN } from '@ant-design/icons';

const scriptUrl = import.meta.env.VITE_ICON_FONT_URL;

const IconFont = scriptUrl
  ? createFromIconfontCN({ scriptUrl })
  : createFromIconfontCN({ scriptUrl: '//at.alicdn.com/t/font_8d5l8fzk5b87iudi.js' });

export default IconFont;
