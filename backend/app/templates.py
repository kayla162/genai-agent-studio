"""通路模板：與 web/src/lib/compose/templates.ts 相同。"""

from app.contract import ChannelTemplate, TemplateId
from app.errors import Invalid

CHANNEL_TEMPLATES: list[ChannelTemplate] = [
    ChannelTemplate(id='ecom-main', label='電商主圖', ratio='1:1', width=1600, height=1600),
    ChannelTemplate(id='scene', label='情境圖', ratio='4:3', width=2048, height=1536),
    ChannelTemplate(id='ig-post', label='IG 貼文', ratio='4:5', width=1440, height=1800),
    ChannelTemplate(id='story', label='限時動態', ratio='9:16', width=1152, height=2048),
    ChannelTemplate(id='banner', label='促銷 Banner', ratio='16:9', width=2048, height=1152),
]


def get_template(template_id: TemplateId) -> ChannelTemplate:
    for t in CHANNEL_TEMPLATES:
        if t.id == template_id:
            return t
    raise Invalid(f'沒有這個通路模板：{template_id}')
