from datetime import date

from pipeline.build.studios import Game, find_links, studio_keys, title_key

SHELL_TAGS = {1: 10, 2: 9, 3: 8, 4: 7, 5: 6}
OTHER_TAGS = {6: 10, 7: 9, 8: 8, 9: 7, 10: 6}


def game(appid, name, dev, pub=None, released=date(2025, 6, 1), reviews=100, tags=SHELL_TAGS):
    return Game(appid, name, dev, pub, f"name:{dev.lower()}", released, reviews, dict(tags))


def links(games):
    return {(x.a, x.b): x.rule for x in find_links(games)}


def test_title_key_drops_numbers_and_editions():
    assert title_key("Hentai Girl 2: Deluxe Edition™") == "hentai girl"
    assert title_key("NEKOPARA Vol. III") == "nekopara vol"


def test_self_named_shells_with_the_same_tags_are_linked():
    games = [
        game(1, "哪吒传奇", "哪吒传奇", "哪吒传奇"),
        game(2, "霸世狂刀", "霸世狂刀", "霸世狂刀", released=date(2025, 11, 1)),
        # a self-named game with different tags, and one released two years later
        game(3, "Other Game", "Other Game", tags=OTHER_TAGS),
        game(4, "龙之传奇", "龙之传奇", released=date(2027, 6, 1)),
    ]
    assert links(games) == {(1, 2): "shell"}


def test_near_identical_titles_are_linked_across_developer_names():
    games = [
        game(1, "Hentai Girl Karen", "Studio A"),
        game(2, "Hentai Girl Linda", "Studio B", released=date(2026, 3, 1)),
        game(3, "Hentai Girl Linda", "Studio C", tags=OTHER_TAGS),  # different kind of game
    ]
    assert links(games) == {(1, 2): "name"}


def test_publisher_links_only_small_look_alikes_released_close_together():
    games = [
        game(1, "Alpha", "Dev A", "Mill"),
        game(2, "Bravo", "Dev B", "Mill", released=date(2025, 9, 1)),
        game(3, "Charlie", "Dev C", "Mill", released=date(2026, 6, 1)),  # 12 months later
        game(4, "Delta", "Dev D", "Mill", reviews=50_000),  # a hit: big publishers' studios
    ]
    assert links(games) == {(1, 2): "publisher"}


def test_studio_keys_merge_transitively_and_deterministically():
    games = [
        game(1, "哪吒传奇", "哪吒传奇", "哪吒传奇"),
        game(2, "霸世狂刀", "霸世狂刀", "霸世狂刀"),
        game(3, "圣域传奇", "圣域传奇", "圣域传奇"),
        game(4, "Unrelated", "Solo Dev", tags=OTHER_TAGS),
    ]
    keys = studio_keys(games, find_links(games))
    group = {keys[g.dev_key] for g in games[:3]}
    assert len(group) == 1 and group == {min(g.dev_key for g in games[:3])}
    assert keys["name:solo dev"] == "name:solo dev"
