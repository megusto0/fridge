from __future__ import annotations

import json
import re
import subprocess


BRANDS = [
    "село зеленое", "село зелёное", "epica", "эпика", "магнит", "свежесть", "м свежесть", "м кухня",
    "мираторг", "premiere of taste", "простоквашино", "домик в деревне", "глазовская птица",
    "landkaas", "увелка", "нытвенский", "маслозавод нытвенский", "planto", "планто", "слобода",
    "green ribbon", "грин риббон", "яратель", "yaratelle", "greenfield", "гринфилд", "экзо", "магнат"
]

DESCRIPTORS = [
    r"натуральный(?:\s+состав)?(?:\s+без\s+сахара)?",
    r"без\s+сахара",
    r"быстрозамороженн\w*",
    r"замороженн\w*",
    r"стерилизованн\w*",
    r"питьев\w*",
    r"столов\w*",
    r"колот\w*",
    r"ядрица",
    r"экстра",
    r"новый\s+урожай",
    r"в\s+собственном\s+соку",
    r"соцветиями",
    r"охлажденн\w*",
    r"охл\.?",
    r"с\s+мясом",
    r"дизайн\s+упаковки.*",
    r"цвет\s+яиц.*",
    r"в\s+ассортименте"
]

INSTR_MAP = {
    "творог": "творогом",
    "йогурт": "йогуртом",
    "чечевица": "чечевицей",
    "красная чечевица": "красной чечевицей",
    "индейка": "индейкой",
    "азу из индейки": "индейкой",
    "куриный шницель": "куриным шницелем",
    "шницель": "шницелем",
    "гречка": "гречкой",
    "брокколи": "брокколи",
    "овощи": "овощами",
    "карибская смесь": "овощами",
    "томаты": "томатами",
    "ежевика": "ежевикой",
    "яблоки": "яблоками",
    "яйца": "яйцом",
    "сметана": "сметаной",
    "кефир": "кефиром",
    "сыр": "сыром"
}


def clean_food_name(text: str) -> str:
    s = text.lower()
    s = re.sub(r"[«\"].*?[»\"]", "", s)
    s = re.sub(r"\b\d+(?:[.,]\d+)?\s*(?:%|г|гр|кг|мл|л|шт|пак)\.?\b", "", s)
    for b in BRANDS:
        s = re.sub(rf"\b{re.escape(b)}\b", "", s)
    for d in DESCRIPTORS:
        s = re.sub(rf"\b{d}\b", "", s)
    s = re.sub(r"[^а-яa-z\s-]", "", s)
    s = re.sub(r"\s+", " ", s).strip()

    if "творог" in s:
        return "Творог"
    if "йогурт" in s:
        return "Йогурт"
    if "чечевиц" in s:
        return "Чечевица"
    if "индейк" in s or "азу" in s:
        return "Индейка"
    if "шницель" in s:
        return "Куриный шницель"
    if "гречк" in s or "гречнев" in s:
        return "Гречка"
    if "брокколи" in s:
        return "Брокколи"
    if "карибск" in s or "смесь" in s:
        return "Овощи"
    if "томат" in s:
        return "Томаты"
    if "ежевик" in s:
        return "Ежевика"
    if "яблок" in s:
        return "Яблоки"
    if "яйц" in s:
        return "Яйца"
    if "сметан" in s:
        return "Сметана"
    if "кефир" in s:
        return "Кефир"
    if "сыр" in s:
        return "Сыр"

    words = s.capitalize().split()
    return " ".join(words[:2]) if words else "Блюдо"


def _clean_single_food(text: str) -> str:
    s = text.strip()
    s = re.sub(r"[«\"].*?[»\"]", "", s)
    s = re.sub(r"\b\d+(?:[.,]\d+)?\s*(?:%|г|гр|кг|мл|л|шт|пак)\.?\b", "", s, flags=re.I)
    for b in BRANDS:
        s = re.sub(rf"\b{re.escape(b)}\b", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" ,.-")
    words = s.split()
    return " ".join(words[:4]) if words else "Новый милпреп"


def fast_dish_name(ingredients: list[str]) -> str:
    valid = [i for i in ingredients if i.strip()]
    if not valid:
        return "Новый милпреп"
    if len(valid) == 1:
        return _clean_single_food(valid[0])

    cleaned = [clean_food_name(i) for i in valid]
    if not cleaned:
        return "Новый милпреп"

    c1 = cleaned[0]
    c2 = cleaned[1]

    # Special dairy/dessert combinations
    if (c1 == "Творог" and c2 == "Йогурт") or (c1 == "Йогурт" and c2 == "Творог"):
        if len(cleaned) > 2:
            c3 = cleaned[2]
            instr3 = INSTR_MAP.get(c3.lower(), c3.lower())
            return f"Творог с йогуртом и {instr3}"
        return "Творог с йогуртом"

    # Special poultry + legume/grain
    if (c1 == "Индейка" and c2 == "Чечевица") or (c1 == "Чечевица" and c2 == "Индейка"):
        if len(cleaned) > 2 and cleaned[2] in ["Овощи", "Томаты", "Брокколи"]:
            return "Индейка с чечевицей и овощами"
        return "Индейка с чечевицей"

    instr2 = INSTR_MAP.get(c2.lower(), c2.lower())
    if len(cleaned) > 2 and cleaned[2] in ["Овощи", "Томаты", "Брокколи"]:
        return f"{c1} с {instr2} и овощами"
    return f"{c1} с {instr2}"


def hermes_dish_name(
    ingredients: list[str], *, executable: str, timeout_seconds: float
) -> str | None:
    fallback = fast_dish_name(ingredients)
    clean_ingredients = [clean_food_name(i) for i in ingredients if i.strip()]
    prompt = (
        "Придумай краткое естественное кулинарное название готового блюда по ингредиентам. "
        "КРИТИЧЕСКИ ВАЖНО: Название должно состоять максимум из 2–4 слов (не более 4 слов!). "
        "Никаких названий брендов, граммов, процентов или лишних слов. "
        "Верни только JSON вида {\"name\": \"...\"}. "
        "Примеры хороших названий: \"Творог с йогуртом\", \"Индейка с чечевицей\", \"Курица с брокколи\", \"Гречка по-купечески\". "
        "Состав: " + "; ".join(clean_ingredients)
    )
    try:
        completed = subprocess.run(
            [executable, "-z", prompt, "--reasoning", "minimal"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd="/media/megusto/storage/fridge",
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    text = completed.stdout.strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    name = payload.get("name") if isinstance(payload, dict) else None
    if not isinstance(name, str):
        return None
    name = " ".join(name.split()).strip(" .\"'")
    words = name.split()
    if len(words) > 4:
        name = " ".join(words[:4])
    if not name or name.casefold() == fallback.casefold():
        return name or None
    return name
