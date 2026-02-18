"""
抽牌插件 - 塔罗单张抽牌，回复图片+文本
"""
import json
import random
from pathlib import Path
from io import BytesIO

from nonebot import on, on_regex
from nonebot.adapters.onebot.v11 import Message, MessageSegment

_ROOT = Path(__file__).resolve().parents[2]
TAROT_DIR = _ROOT / "Assets" / "抽牌"
IMAGE_DIR = TAROT_DIR / "image"

_matcher = on_regex(r'^抽牌$', priority=10, block=True)


def _load_tarot():
    with (TAROT_DIR / "batarot.json").open("r", encoding="utf-8") as f:
        return json.load(f)["cards"]


def _read_image(pic: str, reverse: bool) -> BytesIO | None:
    path = IMAGE_DIR / f"{pic}.png"
    if not path.is_file():
        return None
    data = path.read_bytes()
    if not reverse:
        return BytesIO(data)
    from PIL import Image
    img = Image.open(BytesIO(data)).convert("RGB")
    out = BytesIO()
    img.transpose(Image.Transpose.ROTATE_180).save(out, format="PNG")
    out.seek(0)
    return out


@_matcher.handle()
async def _handle_tarot():
    cards = _load_tarot()
    card_key = random.choice(list(cards.keys()))
    card = cards[card_key]
    is_up = random.choice([True, False])
    direction = "up" if is_up else "down"
    name_cn = card["name_cn"]
    name_en = card["name_en"]
    meaning = card["meaning"][direction]
    pos_text = "正位" if is_up else "逆位"

    bio = _read_image(card["pic"], not is_up)
    msg = Message([
        MessageSegment.text(f'你今天抽到的卡牌是：\n\n    "{name_cn}({name_en})({pos_text})"\n\n'),
        MessageSegment.image(bio),
        MessageSegment.text("———— 其寓意为 ————\n"),
        MessageSegment.text(meaning),
        MessageSegment.text("喵~"),
    ])

    await _matcher.finish(msg)
