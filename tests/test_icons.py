"""A stand-in picture, chosen from the name, in one place for every client."""

from fridge_api.services.icons import FALLBACK_ICON, icon_for


def test_a_dish_is_read_before_its_ingredients():
    """«Бутерброд с сыром» is a sandwich, not a cheese."""
    assert icon_for("Бутерброд с сыром и маслом") == "🥪"
    assert icon_for("Овсяная каша на молоке") == "🍲"
    assert icon_for("Сметанник") == "🍰"


def test_the_specific_wins_over_the_general():
    # «сырок» is a glazed curd bar; «сыр» is cheese. Order is what tells them
    # apart, so this is the test that catches a careless reordering.
    assert icon_for("Сырок Топтыжка малиновый") == "🧁"
    assert icon_for("Сыр полутвердый Брест-Литовск") == "🧀"


def test_the_shelf_as_it_actually_stands():
    assert icon_for("Яйцо куриное столовое С1") == "🥚"
    assert icon_for("Кефир 1% Магнит Свежесть 900 г") == "🥛"
    assert icon_for("Пончики Перекрёсток Берлинские с кремом 2x64 г") == "🥐"
    assert icon_for("Халва Восточный гость 500 г") == "🍯"
    assert icon_for("Брокколи быстрозамороженная") == "🥦"


def test_several_names_are_searched_together():
    """A lot has a display name and its product a canonical one."""
    assert icon_for(None, "Творог 5% село зеленое") == "🥣"
    assert icon_for("", None) == FALLBACK_ICON


def test_the_unknown_gets_a_parcel():
    assert icon_for("Нечто неопознанное") == FALLBACK_ICON
