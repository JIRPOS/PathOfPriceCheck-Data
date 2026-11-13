from ppcdata.sources import game_bundle


def _land(tmp_path, *names):
    files = tmp_path / "files"
    files.mkdir(exist_ok=True)
    for n in names:
        (files / ("Metadata@StatDescriptions@" + n)).write_text("")


def test_csd_descriptions_are_found_main_first(tmp_path):
    _land(tmp_path, "map_stat_descriptions.csd", "stat_descriptions.csd",
          "gem_stat_descriptions.csd")
    names = [p.name.rsplit("@", 1)[-1] for p in game_bundle.description_paths(tmp_path)]
    assert names == ["stat_descriptions.csd", "gem_stat_descriptions.csd",
                     "map_stat_descriptions.csd"]


def test_pre_330_txt_descriptions_are_still_found(tmp_path):
    _land(tmp_path, "stat_descriptions.txt", "map_stat_descriptions.txt")
    names = [p.name.rsplit("@", 1)[-1] for p in game_bundle.description_paths(tmp_path)]
    assert names == ["stat_descriptions.txt", "map_stat_descriptions.txt"]


def test_one_extension_serves_the_whole_set(tmp_path):
    # A .txt left over beside a .csd main file must not join the build.
    _land(tmp_path, "stat_descriptions.csd", "map_stat_descriptions.txt")
    assert [p.suffix for p in game_bundle.description_paths(tmp_path)] == [".csd"]


def test_every_requested_path_shares_the_extension():
    for ext in game_bundle.DESCRIPTION_EXTENSIONS:
        main, optional = game_bundle._description_files(ext)
        assert all(p.endswith(ext) for p in [main] + optional)
