from fridge_api.domain import is_fridge_inventory_item


def test_food_stays_in_fridge() -> None:
    for name in (
        "Творог Село Зеленое 5% 200г",
        "Лук красный",
        "Кола без сахара 1 л",
        "Кефир М Свежесть 1% 900 г",
        "Сахарная пудра Магнит 250 г",
    ):
        assert is_fridge_inventory_item(name) is True, name


def test_household_water_and_gum_are_excluded() -> None:
    for name in (
        "Вода Мензелинская минеральная 1.5л",
        "Вода минеральная природная питьевая",
        "Жевательная резинка Pure Fresh Виноград Mentos 15.5г",
        "Полотенца бумажные Магнит 2 слоя",
        "Туалетная бумага Магнит влажная 80 шт",
        "Салфетка Магнит из микрофибры",
        "Губка для посуды Магнит",
        "Батарейки Gigacel AAA 10 шт",
        "Пакет-майка Магнит большой 15кг",
        "Доставка заказа",
        "Стакан Магнит одноразовый кристалл 200 мл 6 шт",
    ):
        assert is_fridge_inventory_item(name) is False, name


def test_service_flag_excludes_line() -> None:
    assert is_fridge_inventory_item("Что угодно", calculation_subject="УСЛУГА") is False
