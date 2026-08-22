"""A stand-in picture for food that has none yet.

Lived in the web UI as a chain of JavaScript regexes, which meant it was the
web UI's alone: GlucoTracker showed the first letter of the name in a grey box
while the same shelf in a browser showed a bowl of soup. A rule derived from
nothing but the product's name has no business being in a client — it belongs
where the name does.
"""

from __future__ import annotations

import re

#: First match wins, so the specific comes before the general: «сырок» is a
#: glazed curd bar and «сыр» is cheese, and the order is what tells them apart.
_RULES: tuple[tuple[str, str], ...] = (
    # Dishes before their ingredients: «Бутерброд с сыром» is a sandwich, and
    # «Овсяная каша на молоке» is porridge, whatever else the name mentions.
    (r"сметанник", "🍰"),
    (r"сэндвич|бутерброд", "🥪"),
    (r"каша", "🍲"),
    (r"пончик|круассан|бурэкас|треугольник|выпечк|коржи|слойк|булоч", "🥐"),
    (r"сырок", "🧁"),
    (r"творог", "🥣"),
    (r"сыр", "🧀"),
    (r"йогурт", "🍧"),
    (r"сливк|молок|кефир", "🥛"),
    (r"сметан", "🥣"),
    (r"шницель|куриц|индейк|азу|мяс|филе|цыпл", "🍗"),
    (r"чечевиц", "🥣"),
    (r"гречк|крупа", "🍲"),
    (r"томат|помидор", "🍅"),
    (r"брокколи", "🥦"),
    (r"капуст", "🥬"),
    (r"овощ|смесь", "🥗"),
    (r"лук", "🧅"),
    (r"яйц", "🥚"),
    (r"яблок", "🍎"),
    (r"лимон", "🍋"),
    (r"мандарин|апельсин", "🍊"),
    (r"ежевик|голубик|ягод|клубник|малин", "🫐"),
    (r"морожен", "🍦"),
    (r"лепешк|лепёшк|блин|лаваш|батон|хлеб", "🥞"),
    (r"чак-чак|козинак|халва", "🍯"),
    (r"сухарик", "🥨"),
    (r"шоколад|twix|батончик|конфет|драже|skittles|m&m|карамель", "🍫"),
    (r"френч-дог|сосиск", "🌭"),
    (r"картофел", "🍟"),
    (r"чай|greenfield|curtis", "🫖"),
    (r"кола|напит|сок|вода", "🥤"),
    (r"сахар", "🧂"),
    (r"масло", "🫒"),
    (r"майонез", "🍶"),
    (r"жвачк|mentos|pure fresh", "🍬"),
    (r"протеин|casein|bombbar", "💪"),
)

_COMPILED = tuple((re.compile(pattern, re.IGNORECASE), icon) for pattern, icon in _RULES)

#: Nothing matched. A parcel is honest: something is in there, unnamed.
FALLBACK_ICON = "📦"


def icon_for(*names: str | None) -> str:
    """The emoji that stands for this food until a photograph exists.

    Takes several names because a lot has a display name and its product has a
    canonical one, and either may be the one that says «творог».
    """
    haystack = " ".join(name for name in names if name)
    if not haystack.strip():
        return FALLBACK_ICON
    for pattern, icon in _COMPILED:
        if pattern.search(haystack):
            return icon
    return FALLBACK_ICON
