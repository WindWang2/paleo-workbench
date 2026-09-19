#pragma once

// Port of paleo_workbench/ui/workstation/composite_attribute_table.py
// (UI-13). QGIS「打开属性表」窗口语义：行 = 要素，列 = 字段 schema（+
// 要素额外属性键）。编辑一律落 VectorEditSession.change_attribute——
// undo/redo/commit/project 版本链与画布数字化完全一致；表选择与图层
// 选集双向同步；多选支持批量字段修改。编辑权威只在会话。
//
// V9 W5：列元数据经 attribute_schema 单一派生（ValueMap/Range/
// CheckBox 控件词表与 QGIS provider 一致）；表头点击数值列按数值排
// 序；单元格编辑器按控件词表生成；状态行呈现 QGIS provider schema
// 一致性标注（synced/drift/unavailable——只呈现不阻塞）。

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <tuple>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/ui_composite/attribute_schema.hpp>
#include <pwb/ui_widgets/core/facies_taxonomy.hpp>

#include <QAbstractTableModel>
#include <QComboBox>
#include <QDialog>
#include <QLabel>
#include <QLineEdit>
#include <QStyledItemDelegate>
#include <QTableView>

namespace pwb::ui_composite {

using pwb::domain::Json;

class CompositeEditController;
class CompositeEditControllerObject;
class VectorLayer;
class VectorEditSession;
struct VectorFeature;

// QTableView with the QTableWidget accessors the differential tests use.
class AttributeTableView : public QTableView {
    Q_OBJECT
public:
    explicit AttributeTableView(QWidget* parent = nullptr);

    int rowCount() const;   // QTableWidget parity (test surface)
    int columnCount() const;
    QString item_text(int row, int column) const;
    QVariant item_data(int row, int column,
                       int role = Qt::UserRole) const;
    QString horizontal_header_text(int column) const;
    void sortItems(int column,
                   Qt::SortOrder order = Qt::AscendingOrder);
};

class AttributeTableModel : public QAbstractTableModel {
    Q_OBJECT
public:
    explicit AttributeTableModel(QObject* parent = nullptr);

    // columns_provider resolves header labels lazily (dialog owns the
    // descriptor cache).
    std::function<QString(const AttributeFieldMeta&)> header_for;
    std::function<const VectorFeature*(const std::string&)> feature_for;

    void reset_from_layer(const std::vector<std::string>& fids,
                          const std::vector<AttributeFieldMeta>& columns,
                          bool editable);

    int rowCount(const QModelIndex& parent = {}) const override;
    int columnCount(const QModelIndex& parent = {}) const override;
    QVariant headerData(int section, Qt::Orientation orientation,
                        int role = Qt::DisplayRole) const override;
    Qt::ItemFlags flags(const QModelIndex& index) const override;
    QVariant data(const QModelIndex& index,
                  int role = Qt::DisplayRole) const override;
    bool setData(const QModelIndex& index, const QVariant& value,
                 int role = Qt::EditRole) override;
    void sort(int column, Qt::SortOrder order) override;

    void emit_rows(const std::vector<std::string>& fids,
                   const std::map<std::string, int>* row_by_id = nullptr);

    // Write seam (dialog-owned; returns false = gate/constraint refused).
    std::function<bool(const std::string& fid, const std::string& key,
                       const std::string& kind, const QString& text)>
        write_attribute;

    const std::vector<std::string>& fids() const { return fids_; }

private:
    std::vector<std::string> fids_;
    std::vector<AttributeFieldMeta> columns_;
    bool editable_ = false;
};

// 按字段元数据生成编辑器（QGIS 编辑控件词表的表内对应物）。相带三字
// 段为词表级联：选项由 taxonomy provider 动态生成，子级按同行父级值
// 过滤（grill Q3-d/Q1）——静态 choices 为空的 choice 字段走此通道。
class FieldEditorDelegate : public QStyledItemDelegate {
    Q_OBJECT
public:
    FieldEditorDelegate(
        std::function<const std::vector<AttributeFieldMeta>&()>
            columns_provider,
        std::function<const pwb::ui_widgets::core::FaciesTaxonomy*()>
            taxonomy_provider,
        QWidget* parent = nullptr);

    QWidget* createEditor(QWidget* parent, const QStyleOptionViewItem&,
                          const QModelIndex& index) const override;
    void setEditorData(QWidget* editor,
                       const QModelIndex& index) const override;
    void setModelData(QWidget* editor, QAbstractItemModel* model,
                      const QModelIndex& index) const override;

private:
    std::optional<QStringList> facies_choices(
        const QModelIndex& index, const AttributeFieldMeta& field) const;
    int column_of(const std::string& key) const;

    std::function<const std::vector<AttributeFieldMeta>&()>
        columns_provider_;
    std::function<const pwb::ui_widgets::core::FaciesTaxonomy*()>
        taxonomy_provider_;
};

class CompositeAttributeTableDialog : public QDialog {
    Q_OBJECT
public:
    // notifier: 控制器 Qt 事件面（CompositeEditControllerObject）；可空
    // ——无注入时表格仍可手工 refresh（宿主自己接线也可传别的对象，
    // 只需暴露同名信号则用 notifier 参数传它并自行 connect）。
    CompositeAttributeTableDialog(
        CompositeEditController* controller, const std::string& layer_id,
        CompositeEditControllerObject* notifier = nullptr,
        QWidget* parent = nullptr);

    // 注入词表 provider（controller.facies_taxonomy_provider parity）。
    void set_taxonomy_provider(
        std::function<const pwb::ui_widgets::core::FaciesTaxonomy*()>
            provider);

    void refresh();

    // QGIS provider parity probe 注入（canvas._mirror_schema_json
    // parity）；无 probe = unavailable。
    void set_schema_probe(MirrorSchemaProbe probe) {
        schema_probe_ = std::move(probe);
    }

    AttributeTableView* table = nullptr;

signals:
    void feature_activated(const QString& feature_id);
    // 「指定相带…」请求（宿主弹级联对话框；仅相带家族图层出现菜单项）。
    void assign_facies_requested();

public slots:
    void on_content_changed(const QString& layer_id);
    void on_state_changed();

private:
    friend class AttributeTableModel;

    VectorLayer* layer() const;
    std::vector<VectorFeature> features() const;
    const VectorFeature* feature(const std::string& feature_id) const;
    const std::vector<AttributeFieldMeta>& columns();
    void invalidate_columns() { columns_cache_.reset(); }

    std::pair<std::string, std::string> qgis_parity(
        const std::vector<AttributeFieldMeta>& columns);
    static QString header_for(const AttributeFieldMeta& field);
    QString status_text(int feature_count, int column_count,
                        VectorLayer* layer, bool editable,
                        const std::string& gate_reason,
                        const std::string& parity_state,
                        const std::string& parity_detail) const;
    std::map<std::string, int> row_map() const;
    void sync_selection_from_layer(VectorLayer* layer);
    void on_sort_changed(int column, Qt::SortOrder order);

    VectorEditSession* edit_session();
    // 写入单元格；false = 被门禁/约束拒绝（调用方须恢复渲染）。
    bool write_attribute(const std::string& feature_id,
                         const std::string& key, const std::string& kind,
                         const QString& text);
    bool unique_value_taken(const AttributeFieldMeta& field,
                            const std::string& feature_id,
                            const QVariant& value) const;
    void apply_batch();
    void on_selection_changed();
    void on_cell_double_clicked(const QModelIndex& index);
    void on_context_menu(const QPoint& position);
    bool refresh_changed_features();

    CompositeEditController* controller_ = nullptr;
    std::string layer_id_;
    AttributeTableModel* model_ = nullptr;
    QLabel* info_ = nullptr;
    QComboBox* batch_field_ = nullptr;
    QLineEdit* batch_value_ = nullptr;

    std::optional<std::vector<AttributeFieldMeta>> columns_cache_;
    MirrorSchemaProbe schema_probe_;

    bool suppress_selection_sync_ = false;
    bool suppress_item_changed_ = false;
    bool suppress_content_refresh_ = false;

    // 差量刷新基线（C-P0-3）：(session, packed revision, columns,
    // {fid: row})。无基线 = 首个 content_changed 走全量 refresh。
    struct RefreshState {
        VectorEditSession* session = nullptr;
        qint64 revision = 0;
        std::vector<AttributeFieldMeta> columns;
        std::map<std::string, int> row_by_id;
    };
    std::optional<RefreshState> refresh_state_;
    std::pair<std::string, std::string> parity_state_{"unavailable", ""};
    std::function<const pwb::ui_widgets::core::FaciesTaxonomy*()>
        taxonomy_provider_holder_;
};

}  // namespace pwb::ui_composite
