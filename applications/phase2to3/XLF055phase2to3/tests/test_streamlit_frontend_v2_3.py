from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
APP_FILE = ROOT / "app" / "app.py"
NAVIGATION = [
    "情景探索",
    "二期人群洞察",
    "情景对比",
    "使用说明",
    "更新日志",
    "问题反馈",
]


def fresh_app() -> AppTest:
    return AppTest.from_file(str(APP_FILE), default_timeout=120).run()


def nav(app: AppTest):
    return next(item for item in app.radio if item.label == "导航")


def button(app: AppTest, label: str):
    return next(item for item in app.button if item.label == label)


def load_example(app: AppTest) -> AppTest:
    button(app, "加载演示参数").click().run()
    return app


def run_scenario(app: AppTest) -> AppTest:
    button(app, "运行情景").click().run()
    return app


def page_text(app: AppTest) -> str:
    values = []
    for collection in [
        app.markdown,
        app.caption,
        app.warning,
        app.info,
        app.error,
        app.success,
    ]:
        values.extend(str(item.value) for item in collection)
    return "\n".join(values)


def test_startup_navigation_core_empty_and_explicit_example() -> None:
    app = fresh_app()
    assert not app.exception
    assert list(nav(app).options) == NAVIGATION
    assert app.title[0].value == "情景探索"
    numeric = {
        item.label: item.value
        for item in app.number_input
        if item.label in {"年龄（岁）", "基线BMI（kg/m²）", "基线阴道pH"}
    }
    assert numeric == {
        "年龄（岁）": None,
        "基线BMI（kg/m²）": None,
        "基线阴道pH": None,
    }
    nugent = next(
        item for item in app.selectbox if item.label == "基线Nugent评分"
    )
    assert nugent.value is None
    body = page_text(app)
    assert "演示参数：35.7岁" not in body
    assert "输入说明" not in body
    assert "W012" not in body
    assert "参数注册表" not in body
    assert "不用于临床决策" in body
    assert button(app, "加载演示参数")


def test_run_demo_and_save_as_anchor_from_main_page() -> None:
    app = load_example(fresh_app())
    run_scenario(app)
    assert not app.exception
    result = app.session_state["current_result"]
    assert result["engine_status"] == "scenario_available"
    assert result["support"]["grade"] == "A"
    body = page_text(app)
    assert "D104复发探索概率" in body
    assert "来源范围内" in body
    assert "W008" not in body
    assert {item.label for item in app.metric} >= {"估计区间", "当前比较锚点"}
    assert [item.label for item in app.get("download_button")] == ["下载结果"]
    next(item for item in app.text_input if item.label == "情景名称").set_value(
        "演示情景A"
    )
    button(app, "保存并设为锚点").click().run()
    assert len(app.session_state["saved_scenarios"]) == 1
    assert app.session_state["anchor_id"] != "__population__"
    assert "已保存“演示情景A”并设为比较锚点" in page_text(app)
    nav(app).set_value("情景对比").run()
    assert not app.exception
    assert app.title[0].value == "情景对比"
    assert "演示情景A" in page_text(app)
    assert any(item.label == "比较锚点" for item in app.selectbox)


def test_core_missing_returns_plain_reason_without_fake_probability() -> None:
    app = fresh_app()
    run_scenario(app)
    assert not app.exception
    result = app.session_state["current_result"]
    assert result["engine_status"] == "anchors_only_missing_core"
    assert result["scenario_estimate"] is None
    assert "missing_core_inputs" in result["reason_codes"]
    body = page_text(app)
    assert "当前组合暂时无法估算复发概率" in body
    assert "请完整填写年龄、BMI、阴道pH和Nugent评分" in body
    assert "W011" not in body


def test_optional_missing_blocks_only_below_minimum_support() -> None:
    app = load_example(fresh_app())
    for label in ["基线AV评分", "是否有既往病史", "基线乳杆菌分级"]:
        next(item for item in app.selectbox if item.label == label).select("未提供")
    run_scenario(app)
    assert not app.exception
    result = app.session_state["current_result"]
    assert result["engine_status"] != "scenario_available"
    assert "fewer_than_five_comparable_support_fields" in result["reason_codes"]
    assert "至少提供一项" in page_text(app)


def test_d21_not_cured_shows_not_applicable() -> None:
    app = load_example(fresh_app())
    next(
        item for item in app.selectbox if item.label == "D21治愈状态"
    ).select("未治愈（本情景不适用）")
    run_scenario(app)
    assert not app.exception
    assert app.session_state["current_result"]["engine_status"] == "not_applicable"
    assert any("不计算D104复发" in item.value for item in app.info)


def test_age_extrapolation_is_explicit_and_plain_language() -> None:
    app = load_example(fresh_app())
    next(item for item in app.number_input if item.label == "年龄（岁）").set_value(55.0)
    next(
        item
        for item in app.checkbox
        if item.label == "允许年龄在18–55岁内作扩展探索"
    ).check()
    run_scenario(app)
    assert not app.exception
    assert app.session_state["current_result"]["support"]["grade"] == "C"
    assert any("年龄超出二期数据范围" in item.value for item in app.warning)
    assert "W007" not in page_text(app)


def test_all_information_pages_render_without_exception() -> None:
    app = fresh_app()
    expected_titles = {
        "二期人群洞察": "二期人群洞察",
        "使用说明": "使用说明",
        "更新日志": "更新日志",
        "问题反馈": "问题反馈",
    }
    for page, expected in expected_titles.items():
        nav(app).set_value(page).run()
        assert not app.exception
        assert app.title[0].value == expected


def test_population_insight_exposes_baseline_filter_controls() -> None:
    app = fresh_app()
    nav(app).set_value("二期人群洞察").run()
    assert not app.exception
    selector = next(
        item for item in app.multiselect if item.label == "选择条件"
    )
    assert set(selector.options) == {
        "年龄",
        "BMI",
        "阴道pH",
        "Nugent评分",
        "AV评分",
        "既往病史",
        "乳杆菌分级",
    }
    assert {item.label for item in app.metric} >= {
        "FAS / 安全集",
        "符合方案集（PPS）",
        "D24治愈目标人群",
        "D104可评价人群",
        "符合条件",
        "来源保留比例",
    }
    population = next(
        item for item in app.selectbox if item.label == "第一步：分析人群"
    )
    assert set(population.options) == {
        "FAS / 安全集 · 74人",
        "符合方案集（PPS） · 57人",
        "D24治愈目标人群 · 34人",
        "D104可评价人群 · 31人",
    }
    assert population.value == "d104_evaluable"
    outcome = next(
        item for item in app.selectbox if item.label == "第二步：结局状态"
    )
    assert set(outcome.options) == {
        "全部所选人群 · 31人",
        "D104观察复发 · 16人",
        "D104观察未复发 · 15人",
    }
    assert len(app.get("plotly_chart")) >= 2
    assert selector.max_selections == 0  # Streamlit proto: zero means unlimited.
    assert "W006" not in page_text(app)


def test_population_unknown_outcome_displays_exact_three() -> None:
    app = fresh_app()
    nav(app).set_value("二期人群洞察").run()
    population = next(
        item for item in app.selectbox if item.label == "第一步：分析人群"
    )
    population.select("D24治愈目标人群 · 34人").run()
    outcome = next(
        item for item in app.selectbox if item.label == "第二步：结局状态"
    )
    outcome.select("D104结局未知 · 3人").run()
    assert not app.exception
    metrics = {item.label: item.value for item in app.metric}
    assert metrics["符合条件"] == "3人"
    assert metrics["来源保留比例"] == "100.0%"


def test_feedback_form_saves_locally_without_claiming_delivery(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XLF055_APP_LOCAL_DATA_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setenv("XLF055_FEEDBACK_EMAIL_ENABLED", "0")
    app = fresh_app()
    nav(app).set_value("问题反馈").run()
    next(item for item in app.text_input if item.label == "问题标题").set_value(
        "合成页面验收"
    )
    next(item for item in app.text_area if item.label == "问题描述").set_value(
        "仅用于自动化验收，不包含病例数据。"
    )
    next(
        item
        for item in app.checkbox
        if "我确认反馈文字和截图" in item.label
    ).check()
    button(app, "提交反馈").click().run()
    assert not app.exception
    assert any("反馈已安全保存" in item.value for item in app.success)
    body = page_text(app)
    assert "无需重复提交" in body
    assert "worker" not in body
    assert "固定通知目标" not in body


def test_clear_session_removes_case_values_results_and_extrapolation() -> None:
    app = load_example(fresh_app())
    run_scenario(app)
    assert app.session_state["current_result"] is not None
    button(app, "清空当前会话").click().run()
    assert not app.exception
    assert app.session_state["current_result"] is None
    assert app.session_state["case_allow_age_extrapolation"] is False
    values = {
        item.label: item.value
        for item in app.number_input
        if item.label in {"年龄（岁）", "基线BMI（kg/m²）", "基线阴道pH"}
    }
    assert set(values.values()) == {None}
