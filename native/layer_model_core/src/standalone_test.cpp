// standalone_test.cpp — numeric/behavioural verification of the layer model with g++.
//
//   env -i PATH=/usr/bin:/bin HOME=$HOME /usr/bin/g++-15 -std=c++17 -O2 -Wall -Wextra
//       layer_model.cpp standalone_test.cpp -o layer_model_selftest
//   ./layer_model_selftest
#include "layer_model.hpp"

#include <cstdio>
#include <memory>
#include <stdexcept>
#include <string>

namespace lm = pwb::layer_model;

namespace {
int g_failures = 0;

#define CHECK(cond, msg)                                                     \
    do {                                                                     \
        if (!(cond)) {                                                       \
            std::printf("[FAIL] %s (line %d)\n", (msg), __LINE__);           \
            ++g_failures;                                                    \
        }                                                                    \
    } while (0)

#define CHECK_EQ(a, b, msg)                                                  \
    do {                                                                     \
        auto _va = (a);                                                      \
        auto _vb = (b);                                                      \
        if (!(_va == _vb)) {                                                 \
            std::printf("[FAIL] %s (line %d): got %llu, want %llu\n", (msg), \
                        __LINE__, (unsigned long long)_va, (unsigned long long)_vb); \
            ++g_failures;                                                    \
        }                                                                    \
    } while (0)

std::unique_ptr<lm::MapLayer> make(const std::string& id, lm::LayerType t,
                                   const std::string& name = "") {
    return std::make_unique<lm::MapLayer>(id, name.empty() ? id : name, t);
}

void test_add_get_uniqueness() {
    lm::LayerRegistry r;
    auto* g = r.add_layer(make("grid-1", lm::LayerType::ScalarGrid, "孔隙度"));
    CHECK(g != nullptr, "add returns ptr");
    CHECK_EQ(r.size(), 1u, "size after add");
    CHECK(r.get("grid-1") == g, "get returns same ptr");
    CHECK(r.get("nope") == nullptr, "missing get -> null");

    bool threw = false;
    try { r.add_layer(make("grid-1", lm::LayerType::Contour)); }
    catch (const std::invalid_argument&) { threw = true; }
    CHECK(threw, "duplicate id rejected");
}

void test_ordering_and_move() {
    lm::LayerRegistry r;
    r.add_layer(make("a", lm::LayerType::ScalarGrid));
    r.add_layer(make("b", lm::LayerType::Contour));
    r.add_layer(make("c", lm::LayerType::Point));
    // bottom..top: a, b, c
    CHECK_EQ(r.index_of("a"), 0u, "a bottom");
    CHECK_EQ(r.index_of("c"), 2u, "c top");

    CHECK(r.move_layer("a", 2), "move a to top");
    // order now b, c, a
    CHECK_EQ(r.index_of("a"), 2u, "a now top");
    CHECK_EQ(r.index_of("b"), 0u, "b now bottom");

    CHECK(r.move_below("a", "c"), "move a below c");
    // b, a, c
    CHECK_EQ(r.index_of("a"), 1u, "a below c");
    CHECK(!r.move_layer("missing", 0), "move missing fails");
}

void test_opacity_clamp_and_revisions() {
    lm::MapLayer l("x", "x", lm::LayerType::ScalarGrid);
    const auto style0 = l.style_revision();
    l.set_opacity(5.0f);
    CHECK(l.opacity() > 0.999f && l.opacity() <= 1.0f, "opacity clamps to 1");
    l.set_opacity(-1.0f);
    CHECK(l.opacity() == 0.0f, "opacity clamps to 0");
    CHECK(l.style_revision() > style0, "opacity bumps style revision");

    const auto data0 = l.data_revision();
    l.set_extent({0.0, 0.0, 10.0, 10.0});
    CHECK(l.data_revision() > data0, "extent bumps data revision");
    CHECK(l.style_revision() == style0 + 1, "extent does NOT bump style revision");

    // Idempotent setters must not invalidate a render/cache entry.
    const auto same_data = l.data_revision();
    const auto same_style = l.style_revision();
    l.set_extent({0.0, 0.0, 10.0, 10.0});
    l.set_opacity(0.0f);
    CHECK_EQ(l.data_revision(), same_data, "unchanged data does not bump revision");
    CHECK_EQ(l.style_revision(), same_style, "unchanged style does not bump revision");
}

void test_scale_visibility() {
    lm::MapLayer l("x", "x", lm::LayerType::ScalarGrid);
    l.set_scale_range({1000.0, 50000.0});  // visible 1:1k .. 1:50k
    CHECK(l.visible_at_scale(5000.0), "in range");
    CHECK(!l.visible_at_scale(100.0), "below min");
    CHECK(!l.visible_at_scale(100000.0), "above max");
    l.set_scale_range({0.0, 0.0});
    CHECK(l.visible_at_scale(1.0) && l.visible_at_scale(1e9), "unbounded always visible");
}

void test_groups_and_effective_visibility() {
    lm::LayerRegistry r;
    r.add_layer(make("group", lm::LayerType::Group, "单因素图·孔隙度"));
    r.add_layer(make("surface", lm::LayerType::ScalarGrid), "group");
    r.add_layer(make("contour", lm::LayerType::Contour), "group");

    auto kids = r.children_of("group");
    CHECK_EQ(kids.size(), 2u, "group has 2 children");
    CHECK(r.is_effectively_visible("surface", 1000.0), "child visible when group visible");

    r.get("group")->set_visible(false);
    CHECK(!r.is_effectively_visible("surface", 1000.0), "hidden group hides child");
    r.get("group")->set_visible(true);

    // Off-scale group hides child.
    r.get("group")->set_scale_range({0.0, 500.0});
    CHECK(!r.is_effectively_visible("surface", 5000.0), "off-scale group hides child");

    r.add_layer(make("not-a-group", lm::LayerType::Point));
    bool threw = false;
    try { r.add_layer(make("invalid-child", lm::LayerType::Point), "not-a-group"); }
    catch (const std::invalid_argument&) { threw = true; }
    CHECK(threw, "non-group parent rejected");
}

void test_remove_orphans_children() {
    lm::LayerRegistry r;
    r.add_layer(make("group", lm::LayerType::Group));
    r.add_layer(make("c1", lm::LayerType::ScalarGrid), "group");
    CHECK(r.remove_layer("group"), "remove group");
    CHECK(r.get("group") == nullptr, "group gone");
    // child remains but is detached.
    CHECK(r.get("c1") != nullptr, "child remains after group removal");
    CHECK(r.children_of("group").empty(), "no children of removed group");
    CHECK(r.is_effectively_visible("c1", 1.0), "orphan visible (no parent)");
}

void test_reparent_rejects_cycles_and_non_groups() {
    lm::LayerRegistry r;
    r.add_layer(make("root", lm::LayerType::Group));
    r.add_layer(make("nested", lm::LayerType::Group), "root");
    r.add_layer(make("vector", lm::LayerType::Vector));
    r.add_layer(make("point", lm::LayerType::Point));
    CHECK(r.set_parent("vector", "nested"), "reparent below group");
    CHECK(r.parent_id("vector") == "nested", "parent changed");
    CHECK(!r.set_parent("root", "nested"), "cycle rejected");
    CHECK(!r.set_parent("point", "vector"), "non-group parent rejected on reparent");
    CHECK(r.set_parent("vector", ""), "detach to root");
    CHECK(r.parent_id("vector").empty(), "detached parent empty");
}

}  // namespace

int main() {
    test_add_get_uniqueness();
    test_ordering_and_move();
    test_opacity_clamp_and_revisions();
    test_scale_visibility();
    test_groups_and_effective_visibility();
    test_remove_orphans_children();
    test_reparent_rejects_cycles_and_non_groups();
    if (g_failures == 0) {
        std::printf("ALL LAYER_MODEL SELFTESTS PASSED\n");
        return 0;
    }
    std::printf("%d FAILURE(S)\n", g_failures);
    return 1;
}
