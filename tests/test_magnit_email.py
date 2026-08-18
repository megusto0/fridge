from decimal import Decimal
from email.message import EmailMessage

from fastapi.testclient import TestClient

from fridge_api.parsers.magnit_email import parse_magnit_receipt_email


def magnit_receipt_message(*, sender: str = "info@ofd-magnit.ru") -> bytes:
    html = """
    <html><body><table>
      <tr><td>КАССОВЫЙ ЧЕК</td></tr>
      <tr><td>ПРИХОД</td></tr>
      <tr><td>АО "ТАНДЕР"</td></tr>
      <tr><td>ИНН 2310031475</td></tr>
      <tr><td>17.08.2026 15:57</td></tr>
      <tr><td>N: 454</td></tr>

      <tr><th>НАИМ. ПР.</th><th>КОЛИЧ. ПР.</th><th>Ц. ЗА ЕД. ПР.</th><th>СУММА ПР.</th></tr>
      <tr><td>Вода Мензелинская минеральная 1.5л</td><td>1</td><td>34.36</td><td>34.36</td></tr>
      <tr><td>ПРИЗНАК ПР. РАСЧЕТА</td><td>ТМ</td></tr>
      <tr><td>МЕРА КОЛИЧЕСТВА ПР. РАСЧЕТА</td><td>шт. или ед.</td></tr>
      <tr><td>КОД ТОВАРА</td><td>0104604369000143215/Oayr</td></tr>

      <tr><td>Вода Мензелинская минеральная 1.5л</td><td>1</td><td>34.36</td><td>34.36</td></tr>
      <tr><td>ПРИЗНАК ПР. РАСЧЕТА</td><td>ТМ</td></tr>
      <tr><td>МЕРА КОЛИЧЕСТВА ПР. РАСЧЕТА</td><td>шт. или ед.</td></tr>
      <tr><td>КОД ТОВАРА</td><td>0104604369000143215/Other</td></tr>

      <tr><td>Лук красный</td><td>0.46</td><td>91.54</td><td>42.11</td></tr>
      <tr><td>ПРИЗНАК ПР. РАСЧЕТА</td><td>ТОВАР</td></tr>
      <tr><td>МЕРА КОЛИЧЕСТВА ПР. РАСЧЕТА</td><td>кг</td></tr>

      <tr><td>Пакет-майка Магнит большой 15кг</td><td>1</td><td>0.01</td><td>0.01</td></tr>
      <tr><td>ПРИЗНАК ПР. РАСЧЕТА</td><td>ТОВАР</td></tr>
      <tr><td>МЕРА КОЛИЧЕСТВА ПР. РАСЧЕТА</td><td>шт. или ед.</td></tr>

      <tr><td>Доставка заказа</td><td>1</td><td>0.00</td><td>0.00</td></tr>
      <tr><td>ПРИЗНАК ПР. РАСЧЕТА</td><td>УСЛУГА</td></tr>
      <tr><td>МЕРА КОЛИЧЕСТВА ПР. РАСЧЕТА</td><td>шт. или ед.</td></tr>

      <tr><td>Номер заказа</td><td>g4-TEST</td></tr>
      <tr><td>ИТОГО:</td><td>110.84</td></tr>
      <tr><td>N ККТ:</td><td>0009457022028142</td></tr>
      <tr><td>N ФД:</td><td>23275</td></tr>
      <tr><td>N ФН:</td><td>7384441001764355</td></tr>
      <tr><td>ФП</td><td>0420512788</td></tr>
    </table></body></html>
    """
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "buyer@example.com"
    message["Subject"] = "Чек 0420512788 и подарок от МАГНИТ"
    message["Message-ID"] = "<receipt-test@ofd-magnit.ru>"
    message.set_content("HTML receipt attached")
    message.add_alternative(html, subtype="html")
    return message.as_bytes()


def test_parser_aggregates_marked_items_and_classifies_inventory() -> None:
    payload = parse_magnit_receipt_email(magnit_receipt_message())

    assert payload.fiscal_fn == "7384441001764355"
    assert payload.fiscal_fd == "23275"
    assert payload.fiscal_fp == "0420512788"
    assert payload.total_minor == 11084
    assert payload.source_message_id == "receipt-test@ofd-magnit.ru"
    assert payload.purchased_at.isoformat() == "2026-08-17T15:57:00+03:00"
    assert len(payload.items) == 4

    water = payload.items[0]
    assert water.quantity == Decimal("2")
    assert water.unit == "pcs"
    assert water.gtin == "04604369000143"
    assert water.package_quantity == Decimal("1.5")
    assert water.package_unit == "л"
    assert water.total_minor == 6872
    assert water.inventory_effect is False

    onion = payload.items[1]
    assert onion.quantity == Decimal("0.46")
    assert onion.unit == "kg"
    assert onion.inventory_effect is True
    assert payload.items[2].inventory_effect is False
    assert payload.items[3].inventory_effect is False


def test_import_email_preserves_non_inventory_lines_without_creating_lots(
    client: TestClient,
    owner_headers: dict[str, str],
) -> None:
    headers = {**owner_headers, "Content-Type": "message/rfc822"}
    response = client.post(
        "/receipts/import-email", headers=headers, content=magnit_receipt_message()
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] is True
    assert body["inventory_lots_created"] == 1
    assert body["enrichment_jobs_created"] == 1
    assert len(body["receipt"]["lines"]) == 4
    assert sum(line["inventory_effect"] for line in body["receipt"]["lines"]) == 1

    inventory = client.get("/inventory", headers=owner_headers).json()
    assert len(inventory) == 1
    by_name = {lot["display_name"]: lot for lot in inventory}
    assert "Вода Мензелинская минеральная 1.5л" not in by_name
    assert Decimal(by_name["Лук красный"]["original_quantity"]) == Decimal("0.46")

    duplicate = client.post(
        "/receipts/import-email", headers=headers, content=magnit_receipt_message()
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["created"] is False


def test_import_email_rejects_untrusted_sender(
    client: TestClient,
    owner_headers: dict[str, str],
) -> None:
    headers = {**owner_headers, "Content-Type": "message/rfc822"}
    response = client.post(
        "/receipts/import-email",
        headers=headers,
        content=magnit_receipt_message(sender="attacker@example.com"),
    )
    assert response.status_code == 422
