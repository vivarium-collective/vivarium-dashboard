from vivarium_workbench.lib.capabilities import CAPABILITY_TAGS, CATEGORY_TO_TAG


def test_vocabulary_has_expected_tags():
    for tag in ["observables", "mass", "bulk_counts", "fluxes",
                "listeners", "growth_division", "3d_pack"]:
        assert tag in CAPABILITY_TAGS
        assert isinstance(CAPABILITY_TAGS[tag], str) and CAPABILITY_TAGS[tag]


def test_category_map_targets_real_tags():
    # every category maps to a defined tag
    for cat, tag in CATEGORY_TO_TAG.items():
        assert tag in CAPABILITY_TAGS
    # the five explorer categories are covered
    assert set(CATEGORY_TO_TAG) == {
        "Mass", "Bulk molecules", "Fluxes", "Listeners", "Growth & division"}
