from generate_podcast import derive_speaker_key, build_speaker_mapping, DEFAULT_LANGUAGE


def test_fallback_uses_named_roles():
    mapping = build_speaker_mapping(DEFAULT_LANGUAGE, None)
    assert derive_speaker_key("daniel", mapping) == mapping["daniel"]
    assert derive_speaker_key("annabelle", mapping) == mapping["annabelle"]


def test_fallback_male_female_markers():
    mapping = build_speaker_mapping(DEFAULT_LANGUAGE, None)
    assert derive_speaker_key("some female name", mapping) in (
        mapping["annabelle"],
        mapping["female"],
        mapping["daniel"],
        mapping["male"],
    )
    assert derive_speaker_key("random male", mapping) in (
        mapping["daniel"],
        mapping["male"],
    )
