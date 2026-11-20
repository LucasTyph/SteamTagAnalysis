import copy

from pipeline.export import check

META = {
    "counts": {
        "games": 60_000,
        "developers": 35_000,
        "tags": 446,
        "pairs": 17_000,
        "triples": 71_000,
        "timeline_games": 5_000,
    },
    "analysis": {"cv_r2": 0.30, "recovery_median": 0.99},
}


def test_normal_month_passes():
    new = copy.deepcopy(META)
    new["counts"]["games"] = 61_200
    new["counts"]["pairs"] = 16_400
    new["analysis"]["cv_r2"] = 0.31
    assert check.problems(META, new) == []


def test_lost_games_timelines_or_bad_model_are_refused():
    new = copy.deepcopy(META)
    new["counts"]["games"] = 30_000  # half the GetItems batches failed
    new["counts"]["timeline_games"] = 1_200  # the histogram fetch stopped early
    new["analysis"]["recovery_median"] = 0.7
    found = check.problems(META, new)
    assert len(found) == 3
    assert any(p.startswith("games") for p in found)
    assert any(p.startswith("timeline games") for p in found)


def test_first_run_without_previous_counts_only_checks_the_model():
    assert check.problems({}, META) == []
