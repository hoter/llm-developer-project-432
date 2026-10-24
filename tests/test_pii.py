"""PII: маскирование и контрольные суммы, чтобы не ломать данные."""
from app.guardrails import pii


def test_phone_and_email_are_masked():
    result = pii.mask("Звоните +7 926 555-14-08 или пишите a.smirnova@technodom.example")

    assert "926" not in result.text
    assert "a.smirnova" not in result.text
    assert "[телефон №1]" in result.text
    assert "[почта №1]" in result.text
    assert result.counts == {"email": 1, "phone": 1}
    assert {entity.kind for entity in result.entities} == {"email", "phone"}


def test_inn_with_valid_checksum_is_masked():
    result = pii.mask("ИНН компании: 7712345671")
    assert "[ИНН №1]" in result.text
    assert "7712345671" not in result.text


def test_inn_with_bad_checksum_is_left_alone():
    result = pii.mask("Артикул 7712345670 и дата 2024010112")
    assert "7712345670" in result.text
    assert not result.found


def test_card_number_uses_luhn():
    valid = pii.mask("Карта 4111 1111 1111 1111")
    invalid = pii.mask("Номер 4111 1111 1111 1112")

    assert "[карта №1]" in valid.text
    assert "4111" not in valid.text
    assert "4111 1111 1111 1112" in invalid.text
    assert not invalid.found


def test_products_and_quantities_are_not_touched():
    text = "Артикул KTL-1700, мощность 800 Вт, объём 1,7 л, цена 2 990 ₽"
    result = pii.mask(text)
    assert result.text == text
    assert not result.found
