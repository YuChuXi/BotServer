"""
抽牌插件 - 塔罗单张抽牌，回复图片+文本；同一 QQ 同一天抽到同一张牌；启动时预构建全部 Message
"""
import hashlib
import json
from datetime import datetime
from pathlib import Path
from io import BytesIO

from nonebot import on_regex
from nonebot.adapters.onebot.v11 import Message, MessageSegment

_ROOT = Path(__file__).resolve().parents[2]
TAROT_DIR = _ROOT / "Assets" / "抽牌"
IMAGE_DIR = TAROT_DIR / "image"

_tarot_cards: dict | None = None
_tarot_message_cache: dict[tuple[str, bool], Message] = {}

_matcher = on_regex(r'^抽[牌|卡]$', priority=10, block=True)


def _load_tarot() -> dict:
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


def _build_one_message(cards: dict, card_key: str, is_up: bool) -> Message:
    card = cards[card_key]
    direction = "up" if is_up else "down"
    name_cn = card["name_cn"]
    name_en = card["name_en"]
    meaning = card["meaning"][direction]
    pos_text = "正位" if is_up else "逆位"
    bio = _read_image(card["pic"], not is_up)
    segs = [
        MessageSegment.text(f'你今天抽到的卡牌是：\n\n    "{name_cn}({name_en})({pos_text})"\n\n'),
        MessageSegment.text("———— 其寓意为 ————\n"),
        MessageSegment.text(meaning),
        MessageSegment.text("喵~"),
    ]
    if bio is not None:
        segs.insert(1, MessageSegment.image(bio))
    return Message(segs)


async def _build_tarot_cache():
    global _tarot_cards, _tarot_message_cache
    _tarot_cards = _load_tarot()
    for card_key in _tarot_cards:
        for is_up in (True, False):
            _tarot_message_cache[(card_key, is_up)] = _build_one_message(_tarot_cards, card_key, is_up)


def _daily_draw(user_id: int) -> tuple[str, bool]:
    """同一 QQ 同一天返回同一 (card_key, is_up)；日期按服务器当地时间。"""
    today = datetime.now().date().isoformat()
    key = f"{user_id}_{today}"
    h = hashlib.sha256(key.encode()).hexdigest()
    n = int(h[:16], 16)
    card_keys = sorted(_tarot_cards.keys())
    card_key = card_keys[n % len(card_keys)]
    is_up = (n >> 32) % 2 == 0
    return card_key, is_up


@_matcher.handle()
async def _handle_tarot(event):
    if not _tarot_message_cache:
        await _build_tarot_cache()

    card_key, is_up = _daily_draw(event.user_id)
    msg = _tarot_message_cache[(card_key, is_up)]
    await _matcher.finish(msg)
