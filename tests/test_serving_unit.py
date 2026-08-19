"""How a product is eaten: pieces or grams, answered once and kept."""

from fastapi.testclient import TestClient


def _create_product(client: TestClient, headers: dict[str, str], name: str) -> dict:
    response = client.post(
        "/products",
        json={"canonical_name": name, "piece_weight_g": "180"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_a_new_product_has_no_answer_yet(client, owner_headers):
    """Unanswered, not guessed.

    An apple and a jar of sweetener both weigh 180 g a piece, so nothing the
    enrichment knows can settle this. A default here would be a guess that
    nobody is ever asked to correct.
    """
    product = _create_product(client, owner_headers, "Яблоки свежие")
    assert product["serving_unit"] is None


def test_the_answer_is_kept_and_travels_with_the_product(client, owner_headers):
    product = _create_product(client, owner_headers, "Мороженое Экзо 520 г")

    response = client.patch(
        f"/products/{product['id']}/serving-unit",
        json={"serving_unit": "g"},
        headers=owner_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["serving_unit"] == "g"

    listed = client.get("/products", headers=owner_headers).json()
    stored = next(p for p in listed if p["id"] == product["id"])
    assert stored["serving_unit"] == "g"


def test_pieces_is_the_other_answer(client, owner_headers):
    product = _create_product(client, owner_headers, "Йогурт с ананасом")

    response = client.patch(
        f"/products/{product['id']}/serving-unit",
        json={"serving_unit": "pcs"},
        headers=owner_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["serving_unit"] == "pcs"


def test_only_the_two_units_are_accepted(client, owner_headers):
    product = _create_product(client, owner_headers, "Коржи для торта")

    response = client.patch(
        f"/products/{product['id']}/serving-unit",
        json={"serving_unit": "штук"},
        headers=owner_headers,
    )
    assert response.status_code == 422


def test_someone_elses_product_cannot_be_answered_for(
    client, owner_headers, other_owner_headers
):
    product = _create_product(client, owner_headers, "Кефир 900 г")

    response = client.patch(
        f"/products/{product['id']}/serving-unit",
        json={"serving_unit": "g"},
        headers=other_owner_headers,
    )
    assert response.status_code == 404
