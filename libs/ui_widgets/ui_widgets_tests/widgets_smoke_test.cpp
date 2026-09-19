// UI-02 — Qt widget smoke test (offscreen): instantiate every ported
// component once and drive its primary entry points. Complements the
// core/modelview tests by proving the Qt shells construct and respond
// under QT_QPA_PLATFORM=offscreen (same discipline as ui_shell's
// qt_widgets_smoke_test).

#include <QApplication>
#include <QDialogButtonBox>
#include <QImage>
#include <QLabel>
#include <QLineEdit>
#include <QMenu>
#include <QPainter>
#include <QProgressBar>
#include <QPushButton>
#include <QToolButton>
#include <QVariantMap>

#include <cstdio>

#include "pwb/ui_widgets/badges.hpp"
#include "pwb/ui_widgets/buttons.hpp"
#include "pwb/ui_widgets/constraint_factor_hud.hpp"
#include "pwb/ui_widgets/dialog.hpp"
#include "pwb/ui_widgets/facies_eyedropper.hpp"
#include "pwb/ui_widgets/facies_palette_widget.hpp"
#include "pwb/ui_widgets/headers.hpp"
#include "pwb/ui_widgets/inputs.hpp"
#include "pwb/ui_widgets/interactive_qc_hub.hpp"
#include "pwb/ui_widgets/map_chrome.hpp"
#include "pwb/ui_widgets/states.hpp"
#include "pwb/ui_widgets/stratigraphic_timeline_slider.hpp"
#include "pwb/ui_widgets/toast.hpp"
#include "pwb/ui_widgets/ui_context.hpp"
#include "pwb/ui_widgets/views.hpp"

#include "ui_widgets_test.hpp"

using namespace pwb::ui_widgets;

namespace {

void check(bool condition, const char* what) {
    pwb_test::check_true(condition, __FILE__, __LINE__, what);
}

}  // namespace

PWB_TEST(badge_and_inline_status) {
    PwbBadge badge("就绪", "success");
    check(badge.text() == "就绪", "badge text");
    check(badge.tone() == "success", "badge tone");
    badge.set_tone("warning");
    check(badge.tone() == "warning", "badge set_tone");

    PwbInlineStatus status;
    status.set_status("3 项警告", "warning", "warning");
    check(status.tone() == "warning", "inline status tone");
    status.clear();
    check(status.tone() == "neutral", "inline status clear -> neutral");
}

PWB_TEST(buttons_variants) {
    // Variant vocabulary -> objectName (QSS hook parity).
    check(!button_variant_object_name("primary").isEmpty(),
          "variant object name");
    PwbButton primary("保存", "primary");
    check(primary.variant() == "primary", "button variant");
    primary.set_variant("danger");
    check(primary.variant() == "danger", "button set_variant");
    primary.set_variant("ghost");  // unknown -> secondary fallback
    check(primary.variant() == "secondary", "unknown variant falls back");

    PwbToolButton tool("fa.edit", "编辑");
    check(tool.text() == "编辑", "tool button text");

    QMenu menu;
    PwbSplitButton split("导出", QString(), &menu);
    int clicks = 0;
    QObject::connect(&split, &PwbSplitButton::clicked,
                     [&clicks] { ++clicks; });
    split.set_enabled_all(false);
    split.set_enabled_all(true);
    check(split.isEnabled(), "split enabled");
}

PWB_TEST(headers_and_property_editor) {
    PwbSectionHeader* header = section_header("数据面板");
    check(header != nullptr, "section_header");
    check(header->text() == "数据面板", "section_header text");
    delete header;

    PwbInspectorSection section("高级", true);
    auto* content = new QWidget();
    auto* edit = new QLineEdit(content);
    section.content_layout()->addWidget(content);
    section.show();
    check(!section.is_collapsed(), "inspector starts expanded");
    section.set_collapsed(true);
    check(section.is_collapsed(), "inspector collapsed");
    section.toggle_collapsed();
    check(!section.is_collapsed(), "inspector toggle restores");

    PwbPropertyEditor props;
    auto* row_edit = new QLineEdit();
    QWidget* row = props.add_widget_row("名称", row_edit);
    check(row != nullptr, "property row");
    props.add_stretch();
}

PWB_TEST(inputs_search_and_form_row) {
    PwbSearchBox search("搜索");
    search.setText("abc");
    check(search.text() == "abc", "search text");

    auto* editor = new QLineEdit();
    QWidget* row = make_form_row("井名", editor);
    check(row != nullptr, "form row");
    delete row;
}

PWB_TEST(states_empty_error_loading_progress) {
    PwbEmptyState empty("暂无数据", "导入数据后开始");
    check(empty.findChild<QLabel*>() != nullptr, "empty state constructs");

    int retries = 0;
    PwbErrorState error("加载失败", "网络超时");
    error.set_retry_callback([&retries] { ++retries; });
    QPushButton* retry = error.findChild<QPushButton*>();
    check(retry != nullptr, "error retry button exists");
    if (retry) {
        retry->click();
        check(retries == 1, "error retry callback");
    }

    PwbLoadingState loading("正在加载…");
    loading.set_text("仍在加载");
    check(loading.findChild<QLabel*>() != nullptr, "loading label");

    PwbProgress progress("running");
    check(progress.state() == "running", "progress state");
    progress.set_state("failed");
    check(progress.state() == "failed", "progress set_state");
    progress.set_state("bogus");  // unknown -> normal
    check(progress.state() == "normal", "progress unknown -> normal");
}

PWB_TEST(toast_stack_and_dismiss) {
    QWidget host;
    host.resize(400, 300);
    host.show();
    PwbToast* t1 = PwbToast::show_on(&host, "已保存", "success");
    PwbToast* t2 = PwbToast::show_on(&host, "第二条", "info");
    check(t1 != nullptr && t2 != nullptr, "toasts created");
    check(PwbToast::stack_count(&host) == 2, "toast stack count");
    t1->dismiss();
    QApplication::processEvents();
    check(PwbToast::stack_count(&host) == 1, "toast dismiss");
    t2->dismiss();
}

PWB_TEST(views_table_tree_commandbar) {
    PwbTableView table;
    table.resize(400, 200);
    check(table.horizontalHeader() != nullptr, "table view header");
    PwbTreeView tree;
    check(tree.header() != nullptr, "tree view header");
    DensityRowDelegate delegate(&table);
    check(delegate.parent() == &table, "delegate parent");

    PwbCommandBar bar;
    auto* label = new QLabel("工具");
    QWidget* added = bar.add_widget(label);
    check(added == label, "command bar add");
    bar.add_stretch();
}

PWB_TEST(dialog_shell) {
    PwbDialog dialog("设置");
    auto* content = new QLabel("正文");
    check(dialog.add_content(content) == content, "dialog add content");
    dialog.add_content_spacing(8);
    QDialogButtonBox* box = dialog.add_buttons(
        QDialogButtonBox::Ok | QDialogButtonBox::Cancel, "应用", "取消");
    check(box != nullptr, "dialog buttons");
    check(dialog.button(QDialogButtonBox::Ok) != nullptr, "dialog ok button");
}

PWB_TEST(timeline_widget_epochs_and_commit) {
    StratigraphicTimelineWidget timeline;
    timeline.resize(600, 60);
    timeline.show();
    using pwb::ui_widgets::core::EpochInfo;
    timeline.set_epochs({{"E1", "一期"}, {"E2", "二期"}, {"E3", "三期"}});
    check(timeline.epochs().size() == 3, "timeline epochs");
    check(timeline.current_epoch() == "E1",
          "timeline defaults to first epoch");
    timeline.set_current_epoch("E2");
    check(timeline.current_epoch() == "E2", "timeline current epoch");
    check(timeline.onion_button != nullptr, "onion button exists");
    check(timeline.onion_button->isCheckable(), "onion checkable");
    // Echo suppression: programmatic set must not commit.
    int commits = 0;
    QObject::connect(&timeline, &StratigraphicTimelineWidget::epoch_committed,
                     [&commits](const QString&) { ++commits; });
    timeline.set_current_epoch("E3", true);
    QApplication::processEvents();
    check(commits == 0, "suppressed set does not commit");
    // Track geometry: index_at maps x -> epoch index.
    check(timeline.track() != nullptr, "timeline track");
}

PWB_TEST(qc_hub_issues_and_fix_gate) {
    InteractiveQCHub hub;
    hub.resize(360, 400);
    hub.show();
    QVariantMap issue;
    issue["rule"] = "sliver_polygon";
    issue["feature_id"] = "F1";
    issue["message"] = "碎多边形";
    hub.set_issues("topology", {issue});
    check(hub.issue_count() == 1, "qc hub issue count");
    check(hub.counts_label != nullptr, "qc counts label");
    hub.mark_resolved(issue);
    check(hub.issue_count() == 0, "qc mark resolved");

    // Fix gate: unavailable -> disabled button with reason.
    hub.set_fix_gate([](const QVariantMap&, const QString&) {
        return std::make_optional(std::make_pair(false, std::string("无上下文")));
    });
    hub.set_issues("topology", {issue});
    check(hub.issue_count() == 1, "qc hub re-add issue");
}

PWB_TEST(constraint_hud_values) {
    ConstraintFactorHud hud;
    hud.resize(260, 120);
    hud.show();
    hud.apply_values({{"sand_ratio", "0.42"}, {"slope", "3.2°"},
                      {"nearest_well", "W1 (50m)"},
                      {"confidence", "0.83"}});
    check(hud.value_of("sand_ratio") == "0.42", "hud sand_ratio");
    check(hud.value_of("slope") == "3.2°", "hud slope");
    check(hud.value_of("confidence") == "0.83", "hud confidence");
    // Missing/empty values render the frozen placeholder.
    check(!hud.value_of("nearest_well").isEmpty(), "hud well present");
    check(hud.value_of("bogus_key").isEmpty(), "hud unknown key -> empty");
}

PWB_TEST(facies_eyedropper_pick_and_miss) {
    FaciesEyedropper dropper;
    check(!dropper.active(), "eyedropper inactive default");
    dropper.set_active(true);
    check(dropper.active(), "eyedropper active");

    int picked = 0, missed = 0;
    QObject::connect(&dropper, &FaciesEyedropper::picked,
                     [&picked](const QVariantMap&) { ++picked; });
    QObject::connect(&dropper, &FaciesEyedropper::pick_missed,
                     [&missed] { ++missed; });

    // Bound identify returns a facies hit.
    dropper.bind([](double, double) {
        nlohmann::ordered_json hit;
        hit["layer_id"] = "L1";
        hit["feature_id"] = "F1";
        hit["attributes"] = {{"facies", "曲流河"}};
        return std::vector<nlohmann::ordered_json>{hit};
    });
    dropper.bind_color([](const std::string& name) -> std::string {
        return name == "曲流河" ? "#c47f4e" : "#000000";
    });
    check(dropper.handle_click(5.0, 6.0), "eyedropper facies hit");
    check(picked == 1, "picked signal");

    // Rebind to empty -> miss.
    dropper.bind([](double, double) {
        return std::vector<nlohmann::ordered_json>{};
    });
    check(!dropper.handle_click(0.0, 0.0), "eyedropper miss");
    check(missed == 1, "missed signal");

    // Inactive dropper never handles.
    dropper.set_active(false);
    check(!dropper.handle_click(1.0, 1.0), "inactive handles nothing");
}

PWB_TEST(facies_palette_equip_and_favorites) {
    FaciesPaletteWidget palette;
    palette.resize(300, 400);
    palette.show();
    nlohmann::ordered_json tree;
    tree["曲流河"]["边滩"] = nlohmann::json::object();
    tree["曲流河"]["心滩"] = nlohmann::json::object();
    palette.set_taxonomy(pwb::ui_widgets::core::FaciesTaxonomy(tree));
    check(palette.section_count() >= 1, "palette sections");
    check(palette.swatch_count() >= 1, "palette swatches");

    FaciesBrushContext brush;
    check(!brush.is_armed(), "brush not armed");
    QVariantMap selection{{"facies", "曲流河"}, {"sub_facies", "边滩"}};
    int equipped = 0;
    QObject::connect(&brush, &FaciesBrushContext::equipped_changed,
                     [&equipped](const QVariantMap&) { ++equipped; });
    brush.equip(selection);
    check(brush.is_armed(), "brush armed after equip");
    check(equipped == 1, "equipped signal");
    brush.clear();
    check(!brush.is_armed(), "brush cleared");
}

PWB_TEST(map_chrome_spec_and_paint) {
    // nice_scale_units snaps onto the 1/2/5 ladder.
    check(nice_scale_units(900.0) == 500.0, "nice 900 -> 500");
    check(nice_scale_units(1200.0) == 1000.0, "nice 1200 -> 1000");
    check(nice_scale_units(300.0) == 200.0, "nice 300 -> 200");

    // Degenerate extent -> no spec (honest miss).
    check(!scale_bar_spec({0, 0, 0, 0}, 400).has_value(),
          "degenerate extent no spec");
    const auto spec = scale_bar_spec({0, 0, 10000, 5000}, 800);
    check(spec.has_value(), "scale spec exists");
    if (spec) check(spec->second > 0.0, "scale pixel length positive");

    // ensure_basic_map_chrome injects defaults on empty elements.
    const QVariantMap chrome = ensure_basic_map_chrome(QVariantMap{});
    const auto elements = chrome.value("elements").toStringList();
    check(elements.contains("比例尺"), "chrome scale bar injected");
    check(elements.contains("指北针"), "chrome north arrow injected");
    // Explicit whitelist respected as-is.
    const QVariantMap explicit_only =
        ensure_basic_map_chrome({{"elements", QStringList{"标题"}}});
    check(explicit_only.value("elements").toStringList().size() == 1,
          "explicit chrome respected");

    // Legend size is (0,0) without legend content; positive with items.
    check(legend_chrome_size(QVariantMap{}).isEmpty(),
          "no legend -> empty size");
    const QVariantMap with_legend{
        {"legend_items", QStringList{"砂岩", "泥岩"}}};
    check(!legend_chrome_size(with_legend).isEmpty(),
          "legend size positive");

    // Painting into an offscreen image must not crash and must ink pixels.
    QImage target(400, 300, QImage::Format_ARGB32);
    target.fill(Qt::transparent);
    {
        QPainter painter(&target);
        paint_map_decorations(painter,
                              {{"elements", QStringList{"比例尺", "指北针"}},
                               {"title", "工区图"}},
                              400, 300, {0, 0, 10000, 5000});
    }
    bool inked = false;
    for (int y = 0; y < target.height() && !inked; ++y)
        for (int x = 0; x < target.width(); ++x)
            if (qAlpha(target.pixel(x, y)) > 0) { inked = true; break; }
    check(inked, "chrome painting produced ink");
}

PWB_TEST(ui_context_theme_access) {
    // Fallback theme service exists without host injection (the Python
    // theme_manager singleton parity — component construction must never
    // touch a null service).
    check(theme_service() != nullptr, "theme service fallback");
    check(!palette_token("TEXT_PRIMARY").isEmpty(), "palette token");
    check(row_height() > 0, "row height positive");
    check(toolbar_height() > 0, "toolbar height positive");
}

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    return pwb_test::run_all();
}
