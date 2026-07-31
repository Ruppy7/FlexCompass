"""Explicitly synthetic, I/O-free demonstration routes."""

from __future__ import annotations

from fastapi import APIRouter

from .matching import assess_portfolio
from .models import (
    AssetGroup,
    AssetSource,
    DemoAnalyseRequest,
    DemoAnalyseResponse,
    DemoAssetGroupResponse,
    DemoPortfolioListResponse,
    DemoReportRequest,
    DemoReportResponse,
    FitAssessment,
    GenerateAssetGroupRequest,
    Portfolio,
)
from .report_generator import generate_report
from .seed_loader import load_example_portfolios

demo_router = APIRouter(prefix="/api/demo")


def analyse_synthetic_portfolio(
    portfolio: Portfolio,
) -> list[FitAssessment]:
    """Analyse submitted synthetic assets without portal-derived evidence."""
    return assess_portfolio(portfolio, [], [])


@demo_router.get(
    "/portfolios",
    response_model=DemoPortfolioListResponse,
)
def demo_portfolios() -> DemoPortfolioListResponse:
    return DemoPortfolioListResponse(items=load_example_portfolios())


@demo_router.post(
    "/analyse",
    response_model=DemoAnalyseResponse,
)
def demo_analyse(request: DemoAnalyseRequest) -> DemoAnalyseResponse:
    assessments = analyse_synthetic_portfolio(request.portfolio)
    return DemoAnalyseResponse(
        portfolio=request.portfolio,
        assessments=assessments,
        signals_considered=0,
        sources_represented=[],
        dsos_represented=[],
    )


@demo_router.post(
    "/report",
    response_model=DemoReportResponse,
)
def demo_report(request: DemoReportRequest) -> DemoReportResponse:
    assessments = analyse_synthetic_portfolio(request.portfolio)
    markdown = generate_report(request.portfolio, assessments, [], [])
    return DemoReportResponse(
        markdown=markdown,
        portfolio=request.portfolio,
        assessments=assessments,
    )


@demo_router.post(
    "/asset-groups/generate",
    response_model=DemoAssetGroupResponse,
)
def demo_generate_asset_group(
    request: GenerateAssetGroupRequest,
) -> DemoAssetGroupResponse:
    item = AssetGroup(
        asset_group_id=(
            f"synthetic_{request.portal_id}_{request.asset_type.value}"
        ),
        source=AssetSource.synthetic,
        asset_type=request.asset_type,
        asset_count=request.count,
        rated_power_kw=1,
        controllable_power_kw=1,
        availability_percent=1,
        response_reliability_percent=1,
        baseline_assumption="Synthetic demonstration assumption.",
        metering_assumption="Synthetic demonstration assumption.",
        operational_notes=[
            "No live or current portal data is used.",
        ],
    )
    return DemoAssetGroupResponse(item=item)
