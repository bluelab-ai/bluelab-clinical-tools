from __future__ import annotations

import json
from pathlib import Path
import sys

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import app as frontend  # noqa: E402
from planning_tool.engine import population_summary  # noqa: E402


def fresh_app(monkeypatch) -> AppTest:
    monkeypatch.delenv("XLF055_APP_PASSWORD", raising=False)
    return AppTest.from_file(str(APP_ROOT / "app.py"), default_timeout=120).run()


def button(app: AppTest, label: str):
    return next(item for item in app.button if item.label == label)


def radio(app: AppTest, label: str):
    return next(item for item in app.radio if item.label == label)


def test_population_distribution_is_aggregate_and_small_cell_marked() -> None:
    expected = {
        "fas_ss": 74,
        "pps": 57,
        "d24_cured": 34,
        "d104_evaluable": 31,
    }
    for scope, source_n in expected.items():
        summary = population_summary(population_scope=scope)
        assert summary["population_scope"]["source_n"] == source_n
        assert set(summary["numeric_distributions"]) == {
            "age_years",
            "baseline_bmi",
            "baseline_vaginal_ph",
            "baseline_nugent_score",
            "baseline_av_score",
        }
        for rows in summary["numeric_distributions"].values():
            assert rows
            assert all(0 < row["count"] <= source_n for row in rows)
            assert all(0 < row["percentage"] <= 1 for row in rows)
            assert all(row["small_cell"] == (row["count"] < 5) for row in rows)


def test_comparison_height_tracks_selected_count() -> None:
    result = frontend.evaluate_scenario(
        {
            "age_years": 35.7,
            "baseline_bmi": 21.6,
            "baseline_vaginal_ph": 4.8,
            "baseline_nugent_score": 8,
            "baseline_av_score": 2,
            "any_medical_history": "no",
            "baseline_lactobacillus_grade": "III_or_IV",
            "d21_status": "pending",
            "mode": "data_supported",
        }
    )
    item = {"name": "A", "result": result}
    one = frontend.comparison_figure([item], 16 / 31, "二期已观察人群")
    four = frontend.comparison_figure(
        [{**item, "name": name} for name in ["A", "B", "C", "D"]],
        16 / 31,
        "二期已观察人群",
    )
    assert one.layout.height == 225
    assert four.layout.height > one.layout.height
    assert one.layout.transition.duration == 300


def test_comparison_keeps_numeric_names_on_a_categorical_dynamic_axis() -> None:
    result = frontend.evaluate_scenario(
        {
            "age_years": 35.7,
            "baseline_bmi": 21.6,
            "baseline_vaginal_ph": 4.8,
            "baseline_nugent_score": 8,
            "baseline_av_score": 2,
            "any_medical_history": "no",
            "baseline_lactobacillus_grade": "III_or_IV",
            "d21_status": "pending",
            "mode": "data_supported",
        }
    )
    figure = frontend.comparison_figure(
        [
            {"name": "111", "result": result},
            {"name": "情景 2", "result": result},
            {"name": "情景 4", "result": result},
        ],
        16 / 31,
        "二期已观察人群",
    )
    reduced = frontend.comparison_figure(
        [
            {"name": "111", "result": result},
            {"name": "情景 4", "result": result},
        ],
        16 / 31,
        "二期已观察人群",
    )

    assert figure.layout.yaxis.type == "category"
    assert list(figure.layout.yaxis.categoryarray) == ["情景 4", "情景 2", "111"]
    assert list(figure.data[0].y) == ["情景 4", "情景 2", "111"]
    assert figure.layout.datarevision != reduced.layout.datarevision


def test_comparison_selection_rerenders_all_remaining_scenarios(monkeypatch) -> None:
    app = fresh_app(monkeypatch)
    result = frontend.evaluate_scenario(
        {
            "age_years": 35.7,
            "baseline_bmi": 21.6,
            "baseline_vaginal_ph": 4.8,
            "baseline_nugent_score": 8,
            "baseline_av_score": 2,
            "any_medical_history": "no",
            "baseline_lactobacillus_grade": "III_or_IV",
            "d21_status": "pending",
            "mode": "data_supported",
        }
    )
    app.session_state["saved_scenarios"] = [
        {"id": "a", "name": "111", "result": result},
        {"id": "b", "name": "情景 2", "result": result},
        {"id": "c", "name": "情景 4", "result": result},
    ]
    app.session_state["comparison_selected_ids"] = ["a", "b", "c"]
    radio(app, "导航").set_value("情景对比").run()

    initial = json.loads(app.get("plotly_chart")[0].proto.spec)
    assert initial["data"][0]["y"] == ["情景 4", "情景 2", "111"]
    selector = next(
        item for item in app.multiselect if item.label == "选择要比较的情景"
    )
    selector.set_value(["a", "c"]).run()
    updated = json.loads(app.get("plotly_chart")[0].proto.spec)

    assert updated["data"][0]["y"] == ["情景 4", "111"]
    assert initial["layout"]["datarevision"] != updated["layout"]["datarevision"]


def test_population_charts_keep_sparse_upright_ticks_and_exact_small_counts() -> None:
    retention = frontend.population_retention_figure(74, 74)
    assert retention.layout.xaxis.dtick == 20
    assert retention.layout.xaxis.tickangle == 0
    distribution = frontend.population_distribution_figure(
        "baseline_nugent_score",
        [{"category": "7", "count": 3, "percentage": 1.0, "small_cell": True}],
        3,
    )
    assert list(distribution.data[0].x) == [3]
    assert list(distribution.data[0].text) == ["3人（100.0%）"]
    assert distribution.layout.xaxis.tickangle == 0


def test_sidebar_logo_matches_reference_alignment_parameters() -> None:
    app_source = (APP_ROOT / "app.py").read_text(encoding="utf-8")
    style = (APP_ROOT / "assets" / "style.css").read_text(encoding="utf-8")
    assert 'st.image(str(LOGO_PATH), width=168)' in app_source
    assert "padding-top: 0.45rem" in style
    assert "max-height: 94px" in style
    assert 'margin: 0 auto 2px' in style


def test_population_filter_can_save_and_quick_load(monkeypatch) -> None:
    app = fresh_app(monkeypatch)
    radio(app, "导航").set_value("二期人群洞察").run()
    population = next(
        item for item in app.selectbox if item.label == "第一步：分析人群"
    )
    population.select("FAS / 安全集 · 74人").run()
    fields = next(item for item in app.multiselect if item.label == "选择条件")
    fields.set_value(["既往病史", "Nugent评分"]).run()
    next(item for item in app.selectbox if item.label == "既往病史").set_value("无").run()
    name = next(item for item in app.text_input if item.label == "保存当前人群筛选")
    name.set_value("无既往病史筛选").run()
    button(app, "保存筛选").click().run()
    assert not app.exception
    saved = app.session_state["saved_population_views"]
    assert len(saved) == 1
    assert saved[0]["name"] == "无既往病史筛选"
    assert saved[0]["population_scope"] == "fas_ss"
    assert saved[0]["outcome_group"] == "all"
    assert set(saved[0]["selected_fields"]) == {
        "any_medical_history",
        "baseline_nugent_score",
    }
    assert any(item.label == "快速载入已保存的人群筛选" for item in app.selectbox)
    button(app, "载入筛选").click().run()
    assert not app.exception
    assert app.session_state["insight_population_scope"] == "fas_ss"
    assert set(app.session_state["insight_selected_fields"]) == {
        "any_medical_history",
        "baseline_nugent_score",
    }


def test_anchor_copy_and_pre_release_changelog(monkeypatch) -> None:
    app = fresh_app(monkeypatch)
    anchor = next(item for item in app.selectbox if item.label == "比较锚点")
    assert list(anchor.options)[:2] == [
        "二期已观察人群 · 51.6%（16/31）",
        "二期缺失按复发处理 · 55.9%（19/34）",
    ]
    radio(app, "导航").set_value("更新日志").run()
    assert not app.exception
    body = "\n".join(str(item.value) for item in [*app.markdown, *app.info])
    assert "暂不展示内部开发记录" in body
    assert "V2.6" not in body
