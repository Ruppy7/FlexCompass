import pytest
from app.models import AssetGroup, AssetSource, AssetType, Portfolio
from app.seed_loader import load_example_portfolios
from pydantic import ValidationError


def valid_asset(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "source": AssetSource.synthetic,
        "asset_type": AssetType.battery,
        "asset_count": 1,
        "rated_power_kw": 10.0,
        "controllable_power_kw": 5.0,
        "availability_percent": 0.5,
        "response_reliability_percent": 0.9,
        "regional_distribution": {"nged": 0.5},
        "postcode_distribution": {},
    }
    value.update(overrides)
    return value


@pytest.mark.parametrize(
    "overrides",
    [
        {"asset_count": 0},
        {"availability_percent": 1.01},
        {"response_reliability_percent": -0.01},
        {"controllable_power_kw": 11.0},
        {"regional_distribution": {"nged": 0.6, "spen": 0.5}},
        {"postcode_distribution": {"B1": 0.6, "B2": 0.5}},
    ],
)
def test_asset_group_rejects_impossible_inputs(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        AssetGroup(**valid_asset(**overrides))


def test_asset_group_requires_explicit_source() -> None:
    value = valid_asset()
    value.pop("source")
    with pytest.raises(ValidationError):
        AssetGroup(**value)


def test_portfolio_rejects_more_than_one_thousand_groups() -> None:
    asset = AssetGroup(**valid_asset())
    with pytest.raises(ValidationError):
        Portfolio(portfolio_id="p", portfolio_name="P", assets=[asset] * 1001)


def test_checked_in_examples_use_explicit_synthetic_sources() -> None:
    portfolios = load_example_portfolios()
    assert portfolios
    assert all(
        asset.source is AssetSource.synthetic
        for portfolio in portfolios
        for asset in portfolio.assets
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_asset_group_rejects_non_finite_numbers(value: float) -> None:
    for field in (
        "rated_power_kw",
        "controllable_power_kw",
        "availability_percent",
        "response_reliability_percent",
    ):
        with pytest.raises(ValidationError):
            AssetGroup(**valid_asset(**{field: value}))
    for field in ("regional_distribution", "postcode_distribution"):
        with pytest.raises(ValidationError):
            AssetGroup(**valid_asset(**{field: {"nged": value}}))
