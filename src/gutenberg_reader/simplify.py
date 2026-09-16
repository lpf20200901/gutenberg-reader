"""Traditional -> Simplified Chinese conversion, with gap repair.

The finding this module exists for
==================================

Converting Traditional to Simplified looks like a solved problem.  On Windows
it is one API call — ``LCMapStringW`` with ``LCMAP_SIMPLIFIED_CHINESE``.  It
even works: measured against a 100-character sample of high-frequency
Traditional forms, it scored **98/100**.

The problem is the other 2%.

Silently, with no error and no signal, that API leaves certain characters
untouched.  On 聊齋志異 (487,759 characters) it missed **11 forms, 4,800
occurrences** — including ``爲``, which appears **2,052 times**.  The API
happily converts ``為`` -> ``为`` (464 occurrences done correctly) but not the
variant form ``爲``.

The output is therefore not Traditional and not Simplified.  It is a *mixture*,
which reads worse than either — the reader keeps hitting characters that do not
fit the surrounding script.  This is the failure mode worth knowing about,
because it looks like success.

Measured gaps on 聊齋志異
------------------------

The gaps come in two flavours, and the second is the one that is easy to miss.

**Left untouched** — the engine simply does not convert them:

===========  ========  ==========
missed       should be occurrences
===========  ========  ==========
``爲``       ``为``    2,052
``於``       ``于``    1,701
``後``       ``后``    798
``蹟``       ``迹``    96
``衆``       ``众``    62
``牀``       ``床``    33
``盃``       ``杯``    4
``蓆``       ``席``    4
``粧``       ``妆``    2
===========  ========  ==========

**Converted to the wrong variant** — the engine does change the character, just
not to the modern Simplified form.  A patch table that only maps Traditional
sources cannot repair these, because the source is already gone by the time the
patch runs; the remap has to target the engine's *output* instead:

===========  ===========  ==========
source       engine gives should be
===========  ===========  ==========
``鍾``       ``锺``       ``钟``
``麼``       ``麽``       ``么``
===========  ===========  ==========

Two forms are deliberately **not** patched, because a blanket mapping would
introduce errors rather than remove them:

``藉`` (53 occurrences)
    A valid Simplified character in 慰藉 / 狼藉.  Only 藉口 -> 借口 should
    convert.  Context-sensitive, so left alone.
``祗`` (7 occurrences)
    A subtle variant of 祇/只.  Negligible frequency, not worth the risk.

Engines
-------

Conversion is attempted in this order, and the patch table is applied on top of
whichever engine succeeded:

1. **Windows** ``LCMapStringW`` — no dependency, but Windows-only.
2. **OpenCC** — if the ``opencc`` package happens to be installed (it is
   generally more linguistically careful than the Windows table).
3. **None** — the text is returned unchanged and ``engine`` is ``"none"``.

Use :func:`audit_gaps` to recalibrate the patch table for a *different* text:
the gaps are a property of the engine's table, but which ones actually matter
depends on what the book contains.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

# --------------------------------------------------------------------------
# the patch table
# --------------------------------------------------------------------------

#: Failure mode 1 — the engine leaves the Traditional form untouched.
#: Occurrence counts measured on 聊齋志異 (Gutenberg #51828).
SIMPLIFY_PATCH_UNCHANGED: Dict[str, str] = {
    "爲": "为",   # 2,052
    "於": "于",   # 1,701
    "後": "后",   #   798
    "蹟": "迹",   #    96
    "衆": "众",   #    62
    "牀": "床",   #    33
    "盃": "杯",   #     4
    "蓆": "席",   #     4
    "粧": "妆",   #     2
}

#: Failure mode 2 — the engine *does* convert, but to the wrong character.
#:
#: This one is easy to miss, and a patch table that only maps Traditional
#: sources cannot fix it: by the time the patch runs, the source character is
#: already gone and only the wrong output remains.  The remap has to target the
#: engine's *output*.
SIMPLIFY_PATCH_WRONG_VARIANT: Dict[str, str] = {
    "锺": "钟",   # the API emits this for 鍾 (47 occurrences) instead of 钟
    "麽": "么",   # the API emits this for 麼 (1 occurrence) instead of 么
}

#: Union of both repair tables, applied to the engine's output.
SIMPLIFY_PATCH: Dict[str, str] = {
    **SIMPLIFY_PATCH_UNCHANGED,
    **SIMPLIFY_PATCH_WRONG_VARIANT,
}

#: Deliberately excluded — see the module docstring.
SIMPLIFY_PATCH_EXCLUDED: Dict[str, str] = {"藉": "借", "祗": "只"}

_PATCH_TABLE = str.maketrans(SIMPLIFY_PATCH)

#: A representative Traditional->Simplified table, used by :func:`audit_gaps` to
#: discover which forms a conversion engine is getting wrong.  Not exhaustive by
#: design — it is a probe, not a converter.
REFERENCE_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("無", "无"), ("見", "见"), ("問", "问"), ("與", "与"), ("歸", "归"),
    ("則", "则"), ("來", "来"), ("數", "数"), ("聞", "闻"), ("婦", "妇"),
    ("門", "门"), ("時", "时"), ("複", "复"), ("視", "视"), ("將", "将"),
    ("從", "从"), ("異", "异"), ("兒", "儿"), ("餘", "余"), ("雲", "云"),
    ("間", "间"), ("當", "当"), ("馬", "马"), ("聲", "声"), ("兩", "两"),
    ("過", "过"), ("盡", "尽"), ("請", "请"), ("謂", "谓"), ("後", "后"),
    ("於", "于"), ("這", "这"), ("說", "说"), ("對", "对"), ("個", "个"),
    ("會", "会"), ("學", "学"), ("國", "国"), ("圖", "图"), ("書", "书"),
    ("車", "车"), ("東", "东"), ("鳥", "鸟"), ("魚", "鱼"), ("點", "点"),
    ("萬", "万"), ("歲", "岁"), ("龍", "龙"), ("鳳", "凤"), ("電", "电"),
    ("買", "买"), ("賣", "卖"), ("讀", "读"), ("寫", "写"), ("聽", "听"),
    ("眾", "众"), ("體", "体"), ("變", "变"), ("邊", "边"), ("還", "还"),
    ("進", "进"), ("遠", "远"), ("運", "运"), ("氣", "气"), ("愛", "爱"),
    ("歡", "欢"), ("樂", "乐"), ("話", "话"), ("語", "语"), ("詞", "词"),
    ("認", "认"), ("識", "识"), ("議", "议"), ("論", "论"), ("講", "讲"),
    ("談", "谈"), ("謝", "谢"), ("讓", "让"), ("誰", "谁"), ("讚", "赞"),
    ("幹", "干"), ("著", "着"), ("隻", "只"), ("髮", "发"), ("裏", "里"),
    ("為", "为"), ("爲", "为"), ("開", "开"), ("關", "关"), ("們", "们"), ("義", "义"),
    ("藝", "艺"), ("憶", "忆"), ("應", "应"), ("營", "营"), ("權", "权"),
    ("難", "难"), ("雖", "虽"), ("雙", "双"), ("針", "针"), ("銀", "银"),
    ("錢", "钱"), ("鐘", "钟"), ("長", "长"), ("陽", "阳"), ("陰", "阴"),
    ("陳", "陈"), ("陸", "陆"), ("隨", "随"), ("險", "险"), ("隱", "隐"),
    ("飛", "飞"), ("飯", "饭"), ("飲", "饮"), ("養", "养"), ("體", "体"),
    ("靜", "静"), ("響", "响"), ("項", "项"), ("順", "顺"), ("須", "须"),
    ("顧", "顾"), ("題", "题"), ("願", "愿"), ("類", "类"), ("風", "风"),
    ("驚", "惊"), ("鮮", "鲜"), ("鳴", "鸣"), ("麗", "丽"), ("黃", "黄"),
    ("齊", "齐"), ("齒", "齿"), ("龜", "龟"), ("爭", "争"), ("淨", "净"),
    ("盡", "尽"), ("監", "监"), ("盤", "盘"), ("種", "种"), ("稱", "称"),
    ("節", "节"), ("簡", "简"), ("紀", "纪"), ("納", "纳"), ("純", "纯"),
    ("紙", "纸"), ("級", "级"), ("細", "细"), ("終", "终"), ("結", "结"),
    ("絕", "绝"), ("給", "给"), ("統", "统"), ("經", "经"), ("綠", "绿"),
    ("維", "维"), ("網", "网"), ("緊", "紧"), ("線", "线"), ("緣", "缘"),
    ("編", "编"), ("練", "练"), ("縣", "县"), ("總", "总"), ("織", "织"),
    ("續", "续"), ("罷", "罢"), ("羅", "罗"), ("習", "习"), ("聖", "圣"),
    ("聞", "闻"), ("聯", "联"), ("聰", "聪"), ("職", "职"), ("聽", "听"),
    ("脈", "脉"), ("腳", "脚"), ("脫", "脱"), ("臉", "脸"), ("臨", "临"),
    ("舉", "举"), ("舊", "旧"), ("莊", "庄"), ("華", "华"), ("葉", "叶"),
    ("蓋", "盖"), ("蓮", "莲"), ("藥", "药"), ("蘇", "苏"), ("蘭", "兰"),
    ("處", "处"), ("虛", "虚"), ("蟲", "虫"), ("蠶", "蚕"), ("蠻", "蛮"),
    ("補", "补"), ("裝", "装"), ("裡", "里"), ("覺", "觉"), ("觀", "观"),
    ("規", "规"), ("親", "亲"), ("計", "计"), ("訂", "订"), ("討", "讨"),
    ("記", "记"), ("訪", "访"), ("設", "设"), ("許", "许"), ("訴", "诉"),
    ("評", "评"), ("詩", "诗"), ("該", "该"), ("詳", "详"), ("誌", "志"),
    ("誠", "诚"), ("誤", "误"), ("課", "课"), ("調", "调"), ("諸", "诸"),
    ("謀", "谋"), ("證", "证"), ("護", "护"), ("贊", "赞"), ("貝", "贝"),
    ("負", "负"), ("財", "财"), ("貢", "贡"), ("貧", "贫"), ("貨", "货"),
    ("販", "贩"), ("貪", "贪"), ("責", "责"), ("貴", "贵"), ("費", "费"),
    ("賊", "贼"), ("資", "资"), ("賓", "宾"), ("賞", "赏"), ("賢", "贤"),
    ("質", "质"), ("賴", "赖"), ("贈", "赠"), ("贏", "赢"), ("贖", "赎"),
    ("軌", "轨"), ("軍", "军"), ("軒", "轩"), ("軟", "软"), ("較", "较"),
    ("載", "载"), ("輔", "辅"), ("輕", "轻"), ("輝", "辉"), ("輩", "辈"),
    ("輪", "轮"), ("輸", "输"), ("轉", "转"), ("辦", "办"), ("辭", "辞"),
    ("農", "农"), ("連", "连"), ("違", "违"), ("遲", "迟"), ("選", "选"),
    ("遺", "遗"), ("鄰", "邻"), ("醜", "丑"), ("醬", "酱"), ("釋", "释"),
    ("釘", "钉"), ("釣", "钓"), ("鈍", "钝"), ("鈴", "铃"), ("鋼", "钢"),
    ("銅", "铜"), ("銷", "销"), ("銳", "锐"), ("鋪", "铺"), ("錄", "录"),
    ("錦", "锦"), ("錯", "错"), ("鎖", "锁"), ("鎮", "镇"), ("鏡", "镜"),
    ("鐵", "铁"), ("閉", "闭"), ("閏", "闰"), ("閑", "闲"), ("關", "关"),
    ("隊", "队"), ("陣", "阵"), ("階", "阶"), ("際", "际"), ("雜", "杂"),
    ("雞", "鸡"), ("離", "离"), ("霧", "雾"), ("靈", "灵"), ("韓", "韩"),
    ("頂", "顶"), ("頃", "顷"), ("預", "预"), ("領", "领"), ("頻", "频"),
    ("顆", "颗"), ("顏", "颜"), ("顯", "显"), ("飄", "飘"), ("飾", "饰"),
    ("飽", "饱"), ("饅", "馒"), ("饑", "饥"), ("騾", "骡"), ("驅", "驱"),
    ("驗", "验"), ("骯", "肮"), ("鬚", "须"), ("鬧", "闹"), ("鬱", "郁"),
    ("魯", "鲁"), ("鯉", "鲤"), ("鶴", "鹤"), ("鷹", "鹰"), ("麥", "麦"),
    ("黨", "党"), ("齋", "斋"), ("龐", "庞"), ("齡", "龄"),
)


# --------------------------------------------------------------------------
# engines
# --------------------------------------------------------------------------

def _convert_windows(text: str) -> Optional[str]:
    """Traditional -> Simplified via the OS.  Windows only."""
    try:
        import ctypes
        import ctypes.wintypes as wt
    except ImportError:
        return None

    LCMAP_SIMPLIFIED_CHINESE = 0x02000000
    LOCALE_ZH_CN = 0x0804
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        fn = k32.LCMapStringW
        fn.argtypes = [wt.DWORD, wt.DWORD, wt.LPCWSTR, ctypes.c_int,
                       wt.LPWSTR, ctypes.c_int]
        fn.restype = ctypes.c_int
        need = fn(LOCALE_ZH_CN, LCMAP_SIMPLIFIED_CHINESE, text, -1, None, 0)
        if need <= 0:
            return None
        buf = ctypes.create_unicode_buffer(need)
        got = fn(LOCALE_ZH_CN, LCMAP_SIMPLIFIED_CHINESE, text, -1, buf, need)
        return buf.value if got > 0 else None
    except Exception:
        return None


def _convert_opencc(text: str) -> Optional[str]:
    """Traditional -> Simplified via OpenCC, when it happens to be installed."""
    try:
        from opencc import OpenCC  # type: ignore
    except ImportError:
        return None
    try:
        return OpenCC("t2s").convert(text)
    except Exception:
        return None


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------

@dataclass
class Conversion:
    """Outcome of a conversion attempt."""

    text: str
    engine: str                 # "windows" | "opencc" | "none"
    engine_changed: int         # characters changed by the engine alone
    patched: int                # characters repaired by SIMPLIFY_PATCH
    total_changed: int

    @property
    def ok(self) -> bool:
        return self.engine != "none"


def to_simplified(text: str, apply_patch: bool = True) -> Conversion:
    """Convert Traditional Chinese to Simplified, repairing engine gaps.

    The patch table is applied *after* the engine, so it also covers the case
    where no engine is available at all (``engine == "none"``): a
    Windows-only-API failure should not mean zero conversion.
    """
    converted: Optional[str] = None
    engine = "none"

    for name, fn in (("windows", _convert_windows), ("opencc", _convert_opencc)):
        result = fn(text)
        if result is not None:
            converted, engine = result, name
            break

    base = converted if converted is not None else text
    engine_changed = sum(1 for a, b in zip(text, base) if a != b)

    patched = sum(base.count(k) for k in SIMPLIFY_PATCH) if apply_patch else 0
    final = base.translate(_PATCH_TABLE) if apply_patch else base

    return Conversion(
        text=final,
        engine=engine,
        engine_changed=engine_changed,
        patched=patched,
        total_changed=sum(1 for a, b in zip(text, final) if a != b),
    )


def audit_gaps(
    text: str,
    pairs: Iterable[Tuple[str, str]] = REFERENCE_PAIRS,
    engine: str = "windows",
) -> List[Tuple[str, str, int]]:
    """Find Traditional forms this engine fails to convert *in this text*.

    Returns ``[(form, expected, occurrences), ...]`` sorted by how often the
    form actually occurs, so the entries worth patching come first.

    This is the procedure that produced :data:`SIMPLIFY_PATCH`.  Re-run it for a
    new source: which gaps matter is a function of what the book contains, not
    just of the engine's table.
    """
    conv = _convert_windows if engine == "windows" else _convert_opencc

    found: List[Tuple[str, str, int]] = []
    for trad, want in pairs:
        got = conv(trad)
        if got == want:
            continue
        count = text.count(trad)
        if count:
            found.append((trad, want, count))
    found.sort(key=lambda row: -row[2])
    return found


def residual_traditional(text: str, pairs: Iterable[Tuple[str, str]] = REFERENCE_PAIRS) -> Dict[str, int]:
    """Count Traditional forms still present in converted text.

    A cheap quality gate: after conversion this should be empty apart from any
    forms you deliberately excluded.
    """
    return {trad: text.count(trad) for trad, _ in pairs if text.count(trad)}
