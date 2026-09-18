import pytest

from pipeline.qa import QAError
from pipeline.qa.towns import validate_towns
from pipeline.scope import assign_slugs, build_towns, slugify, split_legal_name


def test_split_legal_name():
    assert split_legal_name("Catskill village") == ("Catskill", "village")
    assert split_legal_name("Kingston city") == ("Kingston", "city")
    assert split_legal_name("Bigplace CDP") == ("Bigplace", "cdp")


def test_slugify():
    assert slugify("Saint Johnsville") == "saint-johnsville"
    assert slugify("Coxsackie") == "coxsackie"
    assert slugify("Mt. Kisco") == "mt-kisco"


def test_build_towns_filters_and_joins(popest_bytes, gazetteer_zip, scope):
    towns = build_towns(popest_bytes, gazetteer_zip, scope)
    by_slug = {t.slug: t for t in towns}
    assert set(by_slug) == {"catskill-ny", "kingston-ny", "twin-greene-ny", "twin-columbia-ny"}
    catskill = by_slug["catskill-ny"]
    assert catskill.geoid == "3613002" and catskill.legal_type == "village"
    assert catskill.county == "Greene" and catskill.county_fips == "039"
    assert catskill.region == "Capital Region"
    assert (catskill.lat, catskill.lon) == (42.214901, -73.858674)
    assert catskill.pop_latest == 3900 and catskill.pop_latest_year == 2024
    # Kingston sits in Ulster -> Hudson Valley
    assert by_slug["kingston-ny"].region == "Hudson Valley"
    # a place split across counties takes the county with most of its people
    assert by_slug["twin-columbia-ny"].county == "Columbia"
    # excluded: CDP, under 1,000, county outside scope, town-of, other state
    assert "bigplace-ny" not in by_slug and "tiny-ny" not in by_slug
    assert "elsewhere-ny" not in by_slug
    assert all(t.geoid.startswith("36") for t in towns)
    assert [t.geoid for t in towns] == sorted(t.geoid for t in towns)


def test_missing_coordinates_fail_loudly(popest_bytes, scope):
    import zipfile
    from io import BytesIO

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "g.txt",
            "USPS\tGEOID\tNAME\tINTPTLAT\tINTPTLONG\nNY\t3639727\tKingston city\t41.9\t-74.0\n",
        )
    with pytest.raises(ValueError, match="Catskill village"):
        build_towns(popest_bytes, buf.getvalue(), scope)


def test_validate_towns_rejects_duplicates_and_bad_coords(popest_bytes, gazetteer_zip, scope):
    towns = build_towns(popest_bytes, gazetteer_zip, scope)
    validate_towns(towns, scope)
    towns[0].slug = towns[1].slug
    towns[1].lat = 10.0
    with pytest.raises(QAError) as exc:
        validate_towns(towns, scope)
    text = str(exc.value)
    assert "duplicate slug" in text and "outside New York" in text


def test_validate_towns_enforces_count_gate(popest_bytes, gazetteer_zip, scope):
    towns = build_towns(popest_bytes, gazetteer_zip, scope)
    strict = {**scope, "expected_count": {"min": 120, "max": 180}}
    with pytest.raises(QAError, match="expected between 120 and 180"):
        validate_towns(towns, strict)


def test_assign_slugs_disambiguates_by_county(popest_bytes, gazetteer_zip, scope):
    towns = build_towns(popest_bytes, gazetteer_zip, scope)
    for t in towns:
        t.slug = ""
    assign_slugs(towns)
    assert sorted(t.slug for t in towns if t.name == "Twin") == [
        "twin-columbia-ny",
        "twin-greene-ny",
    ]
