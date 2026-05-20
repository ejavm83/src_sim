"""시뮬레이션 결과 패널 오케스트레이터."""

from __future__ import annotations

from config import SimulationConfig
from metrics import Metrics
from report import Analysis
from ui.advanced_panel import render_advanced_panel
from ui.bottleneck_panel import render_bottleneck_panel
from ui.buffer_panel import render_buffer_panel
from ui.daily_panel import render_daily_panel
from ui.flow_panel import render_flow_panel
from ui.insights_panel import render_insights_panel
from ui.kpi_panel import render_kpi_panel


def render_results(
    metrics: Metrics,
    cfg: SimulationConfig,
    analysis: Analysis,
) -> None:
    render_kpi_panel(metrics, cfg, analysis)
    render_flow_panel(metrics, cfg, analysis)
    render_bottleneck_panel(metrics, cfg, analysis)
    render_buffer_panel(metrics, cfg)
    render_insights_panel(analysis)
    render_daily_panel(analysis)
    render_advanced_panel(metrics, cfg, expanded=False)
