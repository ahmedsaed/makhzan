"""/stats and /categories — the browse tree and the homepage counters.

The invariant under test throughout is that a category is named by its `ref`
(`domain:slug`), never by slug alone. Slugs are unique per domain, so two
verticals really do both publish "measurement"; a payload keyed on slug makes
them collide in the browse bar and in React keys.
"""

from __future__ import annotations

from factories import make_category, make_product, make_supplier


async def test_stats_on_an_empty_catalogue(client):
    response = await client.get("/stats")

    assert response.status_code == 200
    assert response.json() == {"products": 0, "suppliers": 0, "categories": 0}


async def test_stats_counts_distinct_categories_of_products(client, db):
    """Uncategorized products must not inflate the category count."""
    resistors = await make_category(db, slug="resistors", name_en="Resistors")
    await make_product(db, category=resistors)
    await make_product(db, category=resistors)
    await make_product(db, category=None)
    await make_supplier(db, slug="shop-a")
    await make_supplier(db, slug="shop-b")

    body = (await client.get("/stats")).json()

    assert body == {"products": 3, "suppliers": 2, "categories": 1}


async def test_categories_identifies_each_row_by_domain_qualified_ref(client, db):
    passive = await make_category(db, slug="passive", name_en="Passive", name_ar="مكونات سلبية")

    (row,) = (await client.get("/categories")).json()

    assert row == {
        "ref": "electronics:passive",
        "domain": "electronics",
        "slug": "passive",
        "name_en": "Passive",
        "name_ar": "مكونات سلبية",
        "parent": None,
        "count": 0,
    }
    assert row["ref"] == f"{passive.domain}:{passive.slug}"


async def test_the_same_slug_in_two_domains_stays_distinguishable(client, db):
    """The collision CLAUDE.md warns about: "measurement" is both a tools leaf and
    an electronics one. Both must appear, and nothing may key on the bare slug."""
    await make_category(db, slug="measurement", domain="electronics", name_en="Measurement")
    await make_category(db, slug="measurement", domain="tools", name_en="Measuring Tools")

    rows = (await client.get("/categories")).json()

    assert [r["ref"] for r in rows] == ["electronics:measurement", "tools:measurement"]
    assert len({r["ref"] for r in rows}) == 2
    assert len({r["slug"] for r in rows}) == 1  # the slug alone would have merged them


async def test_parent_is_reported_as_a_ref_not_an_id(client, db):
    parent = await make_category(db, slug="passive", name_en="Passive")
    await make_category(db, slug="resistors", name_en="Resistors", parent=parent)

    rows = {r["slug"]: r for r in (await client.get("/categories")).json()}

    assert rows["passive"]["parent"] is None
    assert rows["resistors"]["parent"] == "electronics:passive"


async def test_a_parent_in_another_domain_is_not_matched_by_slug(client, db):
    """Two trees, same slugs, different domains. A child must point at the parent
    in its own domain — resolving the parent by slug would cross the verticals."""
    electronics_tools = await make_category(db, slug="tools", domain="electronics")
    hand_tools = await make_category(db, slug="tools", domain="tools")
    await make_category(db, slug="pliers", domain="electronics", parent=electronics_tools)
    await make_category(db, slug="pliers", domain="tools", parent=hand_tools)

    rows = (await client.get("/categories")).json()
    parents = {(r["domain"], r["slug"]): r["parent"] for r in rows}

    assert parents[("electronics", "pliers")] == "electronics:tools"
    assert parents[("tools", "pliers")] == "tools:tools"


async def test_counts_are_per_category_and_zero_when_unused(client, db):
    resistors = await make_category(db, slug="resistors", name_en="Resistors")
    capacitors = await make_category(db, slug="capacitors", name_en="Capacitors")
    await make_category(db, slug="inductors", name_en="Inductors")
    await make_product(db, category=resistors)
    await make_product(db, category=resistors)
    await make_product(db, category=capacitors)
    await make_product(db, category=None)  # uncategorized: counted nowhere

    counts = {r["slug"]: r["count"] for r in (await client.get("/categories")).json()}

    assert counts == {"resistors": 2, "capacitors": 1, "inductors": 0}


async def test_rows_are_ordered_by_domain_then_path(client, db):
    await make_category(db, slug="wire", domain="electrical", path="/wire")
    await make_category(db, slug="passive", domain="electronics", path="/passive")
    await make_category(db, slug="active", domain="electronics", path="/active")
    await make_category(db, slug="saws", domain="tools", path="/saws")

    rows = (await client.get("/categories")).json()

    assert [r["ref"] for r in rows] == [
        "electrical:wire",
        "electronics:active",
        "electronics:passive",
        "tools:saws",
    ]


async def test_the_tree_can_be_scoped_to_one_vertical(client, db):
    """Browse scoped to a vertical should not have to ship 16 domains of taxonomy
    and filter client-side."""
    await make_category(db, slug="measurement", domain="electronics", name_en="Measurement")
    await make_category(db, slug="measurement", domain="tools", name_en="Measuring Tools")
    await make_category(db, slug="saws", domain="tools", name_en="Saws")

    rows = (await client.get("/categories?domain=tools")).json()

    assert [r["ref"] for r in rows] == ["tools:measurement", "tools:saws"]


async def test_scoping_keeps_the_counts_it_would_report_unscoped(client, db):
    """Counts are global by design so they stay stable as the user filters;
    scoping the tree must not start recomputing them over the slice."""
    saws = await make_category(db, slug="saws", domain="tools")
    await make_product(db, category=saws, domain="tools")
    await make_product(db, category=saws, domain="tools")

    scoped = (await client.get("/categories?domain=tools")).json()
    unscoped = (await client.get("/categories")).json()

    assert scoped[0]["count"] == 2
    assert scoped == [r for r in unscoped if r["domain"] == "tools"]


async def test_a_scoped_child_still_names_its_parent(client, db):
    """The parent lookup runs over the whole taxonomy. Resolving it within the
    slice would report None for any parent that fell outside it."""
    parent = await make_category(db, slug="hand-tools", domain="tools", name_en="Hand Tools")
    await make_category(db, slug="saws", domain="tools", name_en="Saws", parent=parent)
    await make_category(db, slug="resistors", domain="electronics")

    rows = {r["slug"]: r for r in (await client.get("/categories?domain=tools")).json()}

    assert rows["saws"]["parent"] == "tools:hand-tools"


async def test_an_unknown_domain_is_an_empty_tree_not_an_error(client, db):
    await make_category(db, slug="saws", domain="tools")

    response = await client.get("/categories?domain=nonexistent")

    assert response.status_code == 200
    assert response.json() == []
