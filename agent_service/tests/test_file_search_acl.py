import pytest

from agent_service.file_search_acl import (
    MAX_FILTER_GROUPS,
    PUBLIC_GROUP_KEY,
    filter_for,
    group_metadata_key,
    upload_metadata_for,
)


def _metadata_dict(entries) -> dict[str, str]:
    return {entry.key: entry.string_value for entry in entries}


# --- group_metadata_key ------------------------------------------------------


def test_group_metadata_key_is_deterministic() -> None:
    assert group_metadata_key("cs-team") == group_metadata_key("cs-team")


def test_group_metadata_key_is_filter_safe() -> None:
    key = group_metadata_key("CS 團隊 (support)")
    assert key.startswith("grp_")
    assert all(char.isalnum() or char == "_" for char in key)
    assert '"' not in key


def test_group_metadata_key_never_collides_for_distinct_groups() -> None:
    # These two would collapse to the same slug ("grp_cs_team...") under a
    # naive sanitiser that just replaces non-alnum characters with "_".
    key_a = group_metadata_key("cs team")
    key_b = group_metadata_key("cs-team")
    assert key_a != key_b

    # A larger sweep of distinct, tricky names must all map to distinct keys.
    names = [
        "cs-team",
        "cs_team",
        "cs team",
        "CS-TEAM",
        "cs--team",
        "all-employees",
        "all employees",
        "客服團隊",
        "客服 團隊",
        'x" OR grp_public="1',
        "x OR grp_public=1",
    ]
    keys = [group_metadata_key(name) for name in names]
    assert len(set(keys)) == len(names)


def test_group_metadata_key_cannot_collide_with_public_sentinel() -> None:
    assert group_metadata_key("public") != PUBLIC_GROUP_KEY


def test_group_metadata_key_rejects_empty_group() -> None:
    with pytest.raises(ValueError):
        group_metadata_key("")


# --- upload_metadata_for -----------------------------------------------------


def test_upload_metadata_for_empty_allowed_groups_is_public_sentinel_only() -> None:
    entries = upload_metadata_for([])
    assert _metadata_dict(entries) == {PUBLIC_GROUP_KEY: "1"}


def test_upload_metadata_for_none_allowed_groups_is_public_sentinel_only() -> None:
    entries = upload_metadata_for(None)
    assert _metadata_dict(entries) == {PUBLIC_GROUP_KEY: "1"}


def test_upload_metadata_for_restricted_document_has_no_public_sentinel() -> None:
    entries = upload_metadata_for(["cs-team"])
    metadata = _metadata_dict(entries)
    assert PUBLIC_GROUP_KEY not in metadata
    assert metadata == {group_metadata_key("cs-team"): "1"}


def test_upload_metadata_for_deduplicates_groups() -> None:
    entries = upload_metadata_for(["cs-team", "cs-team"])
    assert len(entries) == 1


# --- filter_for ---------------------------------------------------------------


def test_filter_for_matches_measured_probe_cs_team_only() -> None:
    result = filter_for(["cs-team"])
    assert result == f'{PUBLIC_GROUP_KEY}="1" OR {group_metadata_key("cs-team")}="1"'


def test_filter_for_empty_groups_still_filters_to_public_not_none() -> None:
    result = filter_for([])
    assert result == f'{PUBLIC_GROUP_KEY}="1"'
    assert result is not None


def test_filter_for_none_groups_still_filters_to_public() -> None:
    result = filter_for(None)
    assert result == f'{PUBLIC_GROUP_KEY}="1"'


def test_filter_for_never_returns_none() -> None:
    # A caller with no groups must still see public documents; "no filter"
    # would instead return every restricted document too, so None is never
    # a correct answer from this function.
    assert filter_for([]) is not None
    assert filter_for(["some-group"]) is not None


def test_filter_for_ors_across_multiple_groups() -> None:
    result = filter_for(["cs-team", "hr-team"])
    assert result == (
        f'{PUBLIC_GROUP_KEY}="1" OR {group_metadata_key("cs-team")}="1"'
        f' OR {group_metadata_key("hr-team")}="1"'
    )


def test_filter_for_deduplicates_groups() -> None:
    result = filter_for(["cs-team", "cs-team"])
    assert result.count("OR") == 1  # public OR one group, no repeats


# --- end-to-end semantic equivalence with Hybrid's ACL rule -----------------


def test_encoding_reproduces_hybrid_semantics_public_doc_visible_to_all() -> None:
    # A document with empty allowed_groups (public) must be matched by a
    # filter built for ANY caller, including one with unrelated groups or no
    # groups at all.
    doc_metadata = _metadata_dict(upload_metadata_for([]))
    for caller_groups in ([], ["random-group"], ["cs-team", "hr-team"]):
        query_filter = filter_for(caller_groups)
        assert PUBLIC_GROUP_KEY in doc_metadata
        assert f'{PUBLIC_GROUP_KEY}="1"' in query_filter


def test_encoding_reproduces_hybrid_semantics_restricted_doc_hidden_from_others() -> None:
    doc_metadata = _metadata_dict(upload_metadata_for(["cs-team"]))
    # A caller in an unrelated group (or no groups) gets a filter whose keys
    # do not intersect the document's metadata keys at all.
    outsider_filter = filter_for(["hr-team"])
    assert group_metadata_key("cs-team") not in outsider_filter
    assert set(doc_metadata) & {PUBLIC_GROUP_KEY} == set()

    member_filter = filter_for(["cs-team"])
    assert f'{group_metadata_key("cs-team")}="1"' in member_filter


# --- injection safety ---------------------------------------------------------


def test_group_name_quote_cannot_restructure_filter() -> None:
    malicious = 'cs-team" OR grp_public="1'
    result = filter_for([malicious])
    # The raw malicious text must never appear verbatim in the filter; only
    # its opaque hashed key form may appear.
    assert malicious not in result
    # Structurally it is still exactly "public OR <one hashed key>" — one
    # clause per group, regardless of what characters the group name has.
    assert result == f'{PUBLIC_GROUP_KEY}="1" OR {group_metadata_key(malicious)}="1"'
    assert result.count(" OR ") == 1


def test_group_name_with_or_keyword_cannot_add_clauses() -> None:
    malicious = "a-team OR b-team"
    result = filter_for([malicious])
    assert result.count(" OR ") == 1  # public OR the (single) hashed group key
    assert result == f'{PUBLIC_GROUP_KEY}="1" OR {group_metadata_key(malicious)}="1"'


# --- over-limit behaviour -----------------------------------------------------


def test_filter_for_raises_when_group_count_exceeds_cap() -> None:
    groups = [f"group-{i}" for i in range(MAX_FILTER_GROUPS + 1)]
    with pytest.raises(ValueError, match="MAX_FILTER_GROUPS"):
        filter_for(groups)


def test_filter_for_accepts_exactly_the_cap() -> None:
    groups = [f"group-{i}" for i in range(MAX_FILTER_GROUPS)]
    result = filter_for(groups)
    assert result is not None
    assert result.count(" OR ") == MAX_FILTER_GROUPS  # public + N groups
