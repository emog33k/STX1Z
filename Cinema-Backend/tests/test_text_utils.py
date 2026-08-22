import pytest

from app.core.text import MAX_NAME_LENGTH, has_slug, make_slug, normalize_name


@pytest.mark.parametrize("raw, expected", [
    ("Довод", "довод"),
    ("  ДОВОД  ", "довод"),
    ("Пре   стиж", "пре стиж"),
    ("The\tMatrix", "the matrix"),
])
def test_normalize_name_collapses_case_and_spaces(raw, expected):
    assert normalize_name(raw) == expected


def test_normalize_name_does_not_exceed_column_length():
    # NFKC разворачивает лигатуры, поэтому строка может стать длиннее исходной
    assert len(normalize_name("\ufb01" * MAX_NAME_LENGTH)) == MAX_NAME_LENGTH


@pytest.mark.parametrize("raw, expected", [
    ("Научная Фантастика", "научная-фантастика"),
    ("  боевик  ", "боевик"),
    ("sci-fi", "sci-fi"),
    ("Sci  Fi", "sci-fi"),
])
def test_make_slug(raw, expected):
    assert make_slug(raw) == expected


def test_make_slug_is_case_insensitive():
    assert make_slug("Фантастика") == make_slug("фантастика")


@pytest.mark.parametrize("raw", ["!!!", "---", "   ", "###", "\U0001f3ac"])
def test_make_slug_rejects_names_without_letters(raw):
    with pytest.raises(ValueError):
        make_slug(raw)
    assert has_slug(raw) is False


def test_has_slug_accepts_normal_name():
    assert has_slug("Драма") is True
