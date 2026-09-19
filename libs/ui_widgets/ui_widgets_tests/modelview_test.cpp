// UI-02 — model/view behavior tests (Qt, offscreen).
//
// Behavior parity with the frozen Python tests
// (tests/test_v11_performance_structural.py §1-3, §6 and
// tests/test_v11_modelview_data.py): virtual row model, same-key
// differential reset, stable-key selection, keyed reconciliation with
// zero rebuild, latest-only async query + post-shutdown rejection.

#include <QApplication>
#include <QElapsedTimer>
#include <QItemSelectionModel>
#include <QListWidget>
#include <QListWidgetItem>
#include <QTableView>
#include <QTreeWidget>
#include <QTreeWidgetItem>
#include <QVariantMap>

#include <atomic>
#include <chrono>
#include <limits>
#include <set>
#include <string>
#include <thread>

#include "pwb/ui_widgets/async_query.hpp"
#include "pwb/ui_widgets/object_table.hpp"
#include "pwb/ui_widgets/reconcile.hpp"

#include "ui_widgets_test.hpp"

using namespace pwb::ui_widgets;

// QString-aware equality (the shared harness stays Qt-free for the core
// test binary).
#define CHECK_QSTR(actual, expected)                                          \
    ::pwb_test::check_eq(((actual)).toStdString(), ((expected)).toStdString(), \
                         __FILE__, __LINE__)

namespace {

// Domain row: a QVariantMap is the C++ row-object (the Python tests use
// SimpleNamespace; the map carries the same named fields).
QVariantMap row(int i) {
    return {{"id", QString("k%1").arg(i, 6, 10, QLatin1Char('0'))},
            {"name", QString("W%1").arg(i)},
            {"value", i}};
}

QString key_of_row(const QVariant& v) {
    return v.toMap().value("id").toString();
}

std::vector<ColumnSpec> columns() {
    ColumnSpec id;
    id.key = "id";
    id.title = "ID";
    id.value = [](const QVariant& r) { return r.toMap().value("id"); };
    ColumnSpec name;
    name.key = "name";
    name.title = "名称";
    name.value = [](const QVariant& r) { return r.toMap().value("name"); };
    ColumnSpec value;
    value.key = "value";
    value.title = "数值";
    value.value = [](const QVariant& r) { return r.toMap().value("value"); };
    return {id, name, value};
}

std::vector<QVariant> rows(int n, int base = 0) {
    std::vector<QVariant> out;
    out.reserve(size_t(n));
    for (int i = base; i < base + n; ++i) out.push_back(QVariant::fromValue(row(i)));
    return out;
}

}  // namespace

// -- 1. 表虚拟化（Python test_object_table_model_100k_rows_structural）-----
PWB_TEST(object_table_100k_rows_virtual) {
    ObjectTableModel model(columns(), key_of_row);
    const auto data = rows(100000);
    model.set_rows(data);

    CHECK_EQ(model.rowCount(), 100000);
    CHECK_EQ(model.size(), 100000);
    // Mid-row data resolved on demand (no per-cell item objects — the
    // structural proxy is simply that data() serves 100k rows).
    const QModelIndex mid = model.index(50000, 0);
    CHECK_QSTR(model.data(mid).toString(), QString("k050000"));
    CHECK_QSTR(model.data(model.index(50000, 1)).toString(), QString("W50000"));
    CHECK_EQ(model.data(model.index(50000, 2)).toInt(), 50000);
    // Key lookups.
    CHECK_EQ(model.index_for_key("k099999").row(), 99999);
    CHECK_QSTR(model.row_for_key("k050000").toMap().value("name").toString(), QString("W50000"));
    CHECK_QSTR(model.all_keys()[0], QString("k000000"));
    // Row-object + row-key roles.
    CHECK_QSTR(model.data(mid, kRowKeyRole).toString(), QString("k050000"));
    CHECK(model.data(mid, kRowObjectRole).toMap().value("name").isValid());
    // Out-of-range index -> invalid QVariant (Python None).
    CHECK(!model.data(model.index(200000, 0)).isValid());
    CHECK(!model.data(QModelIndex()).isValid());
    // Header.
    CHECK_QSTR(model.headerData(1, Qt::Horizontal).toString(), QString("名称"));
}

// -- 2. 同键差分（test_set_rows_same_keys_differential_no_reset）------------
PWB_TEST(set_rows_same_keys_differential_no_reset) {
    ObjectTableModel model(columns(), key_of_row);
    model.set_rows(rows(200));

    QTableView view;
    bind_table_defaults(&view);
    view.setModel(&model);
    view.resize(640, 400);
    view.show();

    // Select k000007.
    const QModelIndex target = model.index_for_key("k000007");
    CHECK(target.isValid());
    view.selectionModel()->select(
        target, QItemSelectionModel::Select | QItemSelectionModel::Rows);

    int resets = 0;
    int changed = 0;
    QObject::connect(&model, &QAbstractItemModel::modelAboutToBeReset,
                     [&resets] { ++resets; });
    QObject::connect(&model, &QAbstractItemModel::dataChanged,
                     [&changed] { ++changed; });

    // Same key sequence, fresh row objects -> dataChanged only.
    model.set_rows(rows(200));
    CHECK_EQ(resets, 0);
    CHECK_EQ(changed, 1);
    CHECK_EQ(model.rowCount(), 200);

    // Selection survived (same index identity retained).
    const auto selected = view.selectionModel()->selectedRows();
    CHECK_EQ(selected.size(), 1);
    CHECK_QSTR(model.key_for_index(selected[0]), QString("k000007"));

    // StableSelection round-trip across a same-key refresh.
    StableSelection selection(&view);
    const auto keys = selection.capture();
    CHECK_EQ(keys.size(), 1);
    CHECK_QSTR(keys[0], QString("k000007"));
    model.set_rows(rows(200));
    selection.restore(keys);
    const auto after = view.selectionModel()->selectedRows();
    CHECK_EQ(after.size(), 1);
    CHECK_QSTR(model.key_for_index(after[0]), QString("k000007"));
    CHECK_EQ(resets, 0);

    // Key-set change (shrink) -> full reset required and emitted.
    model.set_rows(rows(100));
    CHECK_EQ(resets, 1);
    CHECK_EQ(model.rowCount(), 100);
}

// -- 3. 排序：混合类型键不抛错 + 持久索引重映射 ------------------------------
PWB_TEST(sort_mixed_values_and_persistent_remap) {
    ObjectTableModel model(columns(), key_of_row);
    // value column: int | "—" placeholder | bool | missing — the Python
    // normalized (tier, value) sort key must not raise on the mix.
    std::vector<QVariant> mixed = {
        QVariant::fromValue(QVariantMap{{"id", "a"}, {"value", 3}}),
        QVariant::fromValue(QVariantMap{{"id", "b"}, {"value", "—"}}),
        QVariant::fromValue(QVariantMap{{"id", "c"}, {"value", true}}),
        QVariant::fromValue(QVariantMap{{"id", "d"}}),  // absent value
        QVariant::fromValue(QVariantMap{{"id", "e"}, {"value", 1}}),
        QVariant::fromValue(QVariantMap{{"id", "f"}, {"value", "zzz"}}),
    };
    model.set_rows(mixed);
    model.sort(2, Qt::AscendingOrder);

    // Tier order: numeric {c=1? bool->1.0, e=1, a=3} < text {b,f} < absent {d}.
    CHECK_QSTR(model.key_for_index(model.index(0, 0)), QString("c"));
    CHECK_QSTR(model.key_for_index(model.index(1, 0)), QString("e"));
    CHECK_QSTR(model.key_for_index(model.index(2, 0)), QString("a"));
    CHECK_QSTR(model.key_for_index(model.index(5, 0)), QString("d"));

    // Descending flips the comparison (absent still last? — Python sorts
    // the whole key tuple descending, so absent tier-2 goes first).
    model.sort(2, Qt::DescendingOrder);
    CHECK_QSTR(model.key_for_index(model.index(0, 0)), QString("d"));

    // Persistent indexes track row identity through the sort.
    model.sort(2, Qt::AscendingOrder);
    const QPersistentModelIndex before = model.index_for_key("e");
    CHECK(before.isValid());
    model.sort(2, Qt::DescendingOrder);
    CHECK(before.isValid());
    CHECK_QSTR(model.key_for_index(before), QString("e"));
    CHECK_EQ(before.row(), model.index_for_key("e").row());
}

// -- 3b. #1390 — data() column bound + NaN sort key -------------------------
PWB_TEST(object_table_data_column_out_of_bounds) {
    // A foreign-model index is still isValid() — the delegate/proxy contract
    // can hand one in, and data() must not index columns_ past its size.
    ObjectTableModel narrow(columns(), key_of_row);
    narrow.set_rows(rows(3));

    std::vector<ColumnSpec> wide_cols = columns();
    for (int i = 0; i < 4; ++i) {
        ColumnSpec extra;
        extra.key = QStringLiteral("extra%1").arg(i);
        extra.title = QStringLiteral("E");
        extra.value = [](const QVariant&) { return QVariant(); };
        wide_cols.push_back(extra);
    }
    ObjectTableModel wide(wide_cols, key_of_row);
    wide.set_rows(rows(3));

    const QModelIndex foreign = wide.index(0, 6);  // valid for wide only
    CHECK(foreign.isValid());
    // Pre-fix: columns_[6] on a 3-column model — UB read. Post-fix: {}.
    CHECK(!narrow.data(foreign).isValid());
    CHECK(!narrow.data(foreign, Qt::ToolTipRole).isValid());
    // In-range foreign index still resolves normally.
    CHECK(narrow.data(wide.index(0, 0)).isValid());
    CHECK_QSTR(narrow.data(wide.index(0, 0)).toString(), QString("k000000"));
}

PWB_TEST(sort_nan_numeric_lands_in_absent_tier) {
    ObjectTableModel model(columns(), key_of_row);
    const double nan = std::numeric_limits<double>::quiet_NaN();
    std::vector<QVariant> mixed = {
        QVariant::fromValue(QVariantMap{{"id", "a"}, {"value", 3}}),
        QVariant::fromValue(QVariantMap{{"id", "n"}, {"value", nan}}),
        QVariant::fromValue(QVariantMap{{"id", "e"}, {"value", 1}}),
        QVariant::fromValue(QVariantMap{{"id", "m"}, {"value", 2}}),
    };
    model.set_rows(mixed);
    model.sort(2, Qt::AscendingOrder);
    // Numeric tier {e=1, m=2, a=3} then absent tier {n=NaN} — deterministic,
    // no strict-weak-ordering violation (pre-fix NaN made every comparison
    // false, which is UB inside std::stable_sort, not just a wrong order).
    CHECK_QSTR(model.key_for_index(model.index(0, 0)), QString("e"));
    CHECK_QSTR(model.key_for_index(model.index(1, 0)), QString("m"));
    CHECK_QSTR(model.key_for_index(model.index(2, 0)), QString("a"));
    CHECK_QSTR(model.key_for_index(model.index(3, 0)), QString("n"));
    // And again descending — Python puts absent first on reverse sort.
    model.sort(2, Qt::DescendingOrder);
    CHECK_QSTR(model.key_for_index(model.index(0, 0)), QString("n"));
}

// -- 4. 首绘有界（test_table_view_first_paint_bounded_to_viewport）----------
PWB_TEST(first_paint_bounded_to_viewport) {
    int calls = 0;
    ColumnSpec id;
    id.key = "id";
    id.title = "ID";
    id.value = [&calls](const QVariant& r) {
        ++calls;
        return r.toMap().value("id");
    };
    ColumnSpec name;
    name.key = "name";
    name.title = "名称";
    name.value = [](const QVariant& r) { return r.toMap().value("name"); };
    ObjectTableModel model({id, name}, key_of_row);
    model.set_rows(rows(100000));

    QTableView view;
    bind_table_defaults(&view);
    view.setModel(&model);
    view.resize(900, 420);
    view.show();
    QApplication::processEvents();
    // Pump a couple of event rounds for layout + first frame.
    for (int i = 0; i < 5; ++i) QApplication::processEvents();

    CHECK(calls > 0);
    CHECK(calls < 2000);
    CHECK_EQ(model.rowCount(), 100000);
}

// -- 5. reconcile 零重建（test_reconcile_10k_keys_second_call_creates_nothing）
PWB_TEST(reconcile_10k_second_call_creates_nothing) {
    QListWidget widget;
    int created = 0;
    int updated = 0;
    auto make_item = [&created](const QString&) {
        ++created;
        return new QListWidgetItem();
    };
    auto update_item = [&updated](QListWidgetItem* item, const QString& key) {
        ++updated;
        item->setText(key);
    };
    std::vector<QString> keys;
    keys.reserve(10000);
    for (int i = 0; i < 10000; ++i)
        keys.push_back(QString("r%1").arg(i, 5, 10, QLatin1Char('0')));

    const auto mapping =
        reconcile_widget_items(&widget, keys, make_item, update_item);
    CHECK_EQ(created, 10000);
    CHECK_EQ(widget.count(), 10000);
    QListWidgetItem* first = widget.item(0);
    CHECK(mapping.at("r00000") == first);

    // Second call, same key set: zero creates, identity preserved.
    updated = 0;
    const auto mapping2 =
        reconcile_widget_items(&widget, keys, make_item, update_item);
    CHECK_EQ(created, 10000);
    CHECK_EQ(updated, 10000);
    CHECK_EQ(widget.count(), 10000);
    CHECK(widget.item(0) == first);
    bool same_items = true;
    for (const QString& k : keys) {
        if (mapping2.at(k) != mapping.at(k)) same_items = false;
    }
    CHECK(same_items);
}

PWB_TEST(reconcile_removes_keyless_and_vanished) {
    QListWidget widget;
    auto make_item = [](const QString& key) {
        auto* item = new QListWidgetItem();
        item->setData(kReconcileKeyRole, key);
        return item;
    };
    auto update_item = [](QListWidgetItem* item, const QString& key) {
        item->setText(key);
    };
    // Seed: keyed a,b + one keyless item.
    reconcile_widget_items(&widget, {"a", "b"}, make_item, update_item);
    auto* keyless = new QListWidgetItem("orphan");
    widget.addItem(keyless);
    CHECK_EQ(widget.count(), 3);

    // Target {b,c}: a + keyless removed, b kept (identity), c created.
    auto* kept_b = widget.item(1);
    const auto mapping =
        reconcile_widget_items(&widget, {"b", "c"}, make_item, update_item);
    CHECK_EQ(widget.count(), 2);
    CHECK_QSTR(item_key(widget.item(0)), QString("b"));
    CHECK_QSTR(item_key(widget.item(1)), QString("c"));
    CHECK(widget.item(0) == kept_b);
    CHECK(mapping.size() == 2);
}

PWB_TEST(reconcile_dedup_and_reorder_and_tree_parent) {
    // Duplicate target keys collapse (order preserved).
    QListWidget widget;
    auto make = [](const QString&) { return new QListWidgetItem(); };
    auto update = [](QListWidgetItem* item, const QString& key) {
        item->setText(key);
    };
    reconcile_widget_items(&widget, {"x", "y", "x", "z", "y"}, make, update);
    CHECK_EQ(widget.count(), 3);
    CHECK_QSTR(item_key(widget.item(0)), QString("x"));
    CHECK_QSTR(item_key(widget.item(1)), QString("y"));
    CHECK_QSTR(item_key(widget.item(2)), QString("z"));

    // Reorder only: same objects, new order.
    QListWidgetItem* ix = widget.item(0);
    QListWidgetItem* iy = widget.item(1);
    QListWidgetItem* iz = widget.item(2);
    reconcile_widget_items(&widget, {"z", "x", "y"}, make, update);
    CHECK(widget.item(0) == iz);
    CHECK(widget.item(1) == ix);
    CHECK(widget.item(2) == iy);

    // QTreeWidget under a parent item: scoped reconcile.
    QTreeWidget tree;
    auto* parent = new QTreeWidgetItem(&tree, {"p"});
    auto make_t = [](const QString&) { return new QTreeWidgetItem(); };
    auto update_t = [](QTreeWidgetItem* item, const QString& key) {
        item->setText(0, key);
    };
    reconcile_widget_items(&tree, {"c1", "c2"}, make_t, update_t, parent);
    CHECK_EQ(parent->childCount(), 2);
    CHECK_QSTR(item_key(parent->child(0)), QString("c1"));
    reconcile_widget_items(&tree, {"c2"}, make_t, update_t, parent);
    CHECK_EQ(parent->childCount(), 1);
    CHECK_QSTR(item_key(parent->child(0)), QString("c2"));
}

// -- 6. AsyncQuery latest-only + post-shutdown rejection -------------------
PWB_TEST(async_query_latest_only_and_shutdown_rejection) {
    AsyncQuery query;
    std::vector<QVariant> fired;

    // 3 rapid submits without pumping events: only latest may deliver.
    for (int tag = 1; tag <= 3; ++tag) {
        query.submit([tag] { return QVariant(tag); },
                     [&fired](const QVariant& r) { fired.push_back(r); });
    }
    QElapsedTimer deadline;
    deadline.start();
    while (deadline.elapsed() < 5000) {
        QApplication::processEvents();
        if (fired.size() == 1 && fired[0].toInt() == 3) break;
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    CHECK_EQ(fired.size(), 1);
    CHECK_EQ(fired[0].toInt(), 3);

    // shutdown(0): a still-running worker's late result is never delivered.
    std::atomic<bool> started{false};
    query.submit(
        [&started] {
            started = true;
            std::this_thread::sleep_for(std::chrono::milliseconds(150));
            return QVariant(QString("late"));
        },
        [&fired](const QVariant& r) { fired.push_back(r); });
    for (int i = 0; i < 200 && !started.load(); ++i) {
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    CHECK(started.load());
    query.shutdown(0);
    // Pump events past the worker's finish; the late delivery must die.
    QElapsedTimer wait;
    wait.start();
    while (wait.elapsed() < 600) QApplication::processEvents();
    CHECK_EQ(fired.size(), 1);

    query.shutdown(0);
}

int main(int argc, char** argv) {
    QApplication app(argc, argv);
    return pwb_test::run_all();
}
