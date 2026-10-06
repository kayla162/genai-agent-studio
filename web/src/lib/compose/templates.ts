import type { ChannelTemplate, TemplateId } from '@/types/contract';

export const CHANNEL_TEMPLATES: ChannelTemplate[] = [
  { id: 'ecom-main', label: '電商主圖', ratio: '1:1', width: 1600, height: 1600 },
  { id: 'scene', label: '情境圖', ratio: '4:3', width: 2048, height: 1536 },
  { id: 'ig-post', label: 'IG 貼文', ratio: '4:5', width: 1440, height: 1800 },
  { id: 'story', label: '限時動態', ratio: '9:16', width: 1152, height: 2048 },
  { id: 'banner', label: '促銷 Banner', ratio: '16:9', width: 2048, height: 1152 },
];

export function getTemplate(id: TemplateId): ChannelTemplate {
  const t = CHANNEL_TEMPLATES.find((x) => x.id === id);
  if (!t) throw new Error(`Unknown template: ${id}`);
  return t;
}
