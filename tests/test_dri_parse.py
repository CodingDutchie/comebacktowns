from pipeline.transform.dri import parse_round_page, round_number

LAYOUT_A = """
<h1>Downtown Revitalization Initiative Round Seven</h1>
<h2 class="t-section__title">Capital Region</h2>
<div><p><strong>Lake George</strong></p><p>The Town and Village of Lake George DRI application focuses on improving things.</p>
<p><a href="#">Capital Region Press Release</a></p></div>
<h2 class="t-section__title">Mohawk Valley</h2>
<p><strong>Herkimer</strong></p><p>The Village of Herkimer's application won a $10 million award.</p>
<h2 class="t-section__title">Mid-Hudson</h2>
<p><strong>Highland Falls</strong></p><p>Gets $4.5 million.</p>
<p><strong>Montgomery</strong></p><p>The Village of Montgomery proposes $7.5 million in project opportunities.</p>
<p><strong>Mid-Hudson Press Release</strong></p>
"""

LAYOUT_B = """
<p><strong>Communities selected in Round One of the DRI were:</strong></p>
<p><a href="#e">Southern Tier – Elmira</a><br>
<a href="#g">Capital Region – Glens Falls</a><br>
<a href="#m">Mid-Hudson – Middletown</a></p>
"""


def test_round_number_words_and_digits():
    assert round_number("dri_downtown-revitalization-initiative-round-seven.html") == 7
    assert round_number("NY Forward Round 4") == 4


def test_layout_a_regions_names_and_amounts():
    awards = parse_round_page(LAYOUT_A, program="nyf", round_no=2, standard_award=4_500_000)
    got = [(a.region, a.community, a.amount, a.amount_source) for a in awards]
    assert got == [
        ("Capital Region", "Lake George", 4_500_000, "program_standard"),
        ("Mohawk Valley", "Herkimer", 10_000_000, "page"),
        ("Mid-Hudson", "Highland Falls", 4_500_000, "page"),
        ("Mid-Hudson", "Montgomery", 4_500_000, "program_standard"),
    ]


def test_layout_b_dash_lines():
    awards = parse_round_page(LAYOUT_B, program="dri", round_no=1, standard_award=10_000_000)
    assert [(a.region, a.community) for a in awards] == [
        ("Southern Tier", "Elmira"),
        ("Capital Region", "Glens Falls"),
        ("Mid-Hudson", "Middletown"),
    ]
    assert all(a.amount == 10_000_000 and a.amount_source == "program_standard" for a in awards)
