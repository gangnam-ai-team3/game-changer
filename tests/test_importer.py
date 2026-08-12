import pytest

from connectors import ConnectorError
from connectors.importer import import_approved_csv
from contracts import ErrorCode

HEADER = "source,source_url,source_id,language,observed_at,summary,mechanism_tags\n"


def test_imports_approved_anonymous_summary(event):
    data = HEADER + (
        "reddit,https://www.reddit.com/r/PUBATTLEGROUNDS/comments/abc,post-1,en,"
        "2025-06-10T00:00:00Z,Two stage reward path is confusing,double_gacha\n"
    )
    [item] = import_approved_csv(data, event.cutoff_at)
    assert item.source_id != "post-1"
    assert item.contains_personal_data is False


@pytest.mark.parametrize(
    "data",
    [
        HEADER.replace("mechanism_tags", "username") +
        "reddit,https://www.reddit.com/r/x,post-1,en,2025-06-10T00:00:00Z,summary,user\n",
        HEADER +
        "reddit,https://evil.example/post,post-1,en,2025-06-10T00:00:00Z,summary,double_gacha\n",
        HEADER +
        "reddit,https://reddit.com/r/x/post,post-1,en,2025-06-11T00:00:00Z,summary,double_gacha\n",
    ],
)
def test_rejects_bad_csv(event, data):
    with pytest.raises(ConnectorError) as error:
        import_approved_csv(data, event.cutoff_at)
    assert error.value.code == ErrorCode.INVALID_IMPORT
