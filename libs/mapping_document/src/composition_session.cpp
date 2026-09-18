#include <pwb/mapping_document/composition_session.hpp>

#include <algorithm>
#include <utility>

namespace pwb::mapping_document {

namespace {

// Stable sort by z_index (Python list.sort is stable; ties keep list order).
void sort_by_z(Composition& doc) {
    std::stable_sort(doc.elements.begin(), doc.elements.end(),
                     [](const ComposerElement& left, const ComposerElement& right) {
                         return left.z_index < right.z_index;
                     });
}

std::string quoted(const std::string& id) {
    // Python !r for the message texts: single-quoted repr.
    std::string out = "'";
    for (char c : id) {
        if (c == '\'') out += "\\'";
        out.push_back(c);
    }
    out.push_back('\'');
    return out;
}

// The session defines same-named members; this wrapper reaches the CONV-02
// kernel free function from inside lambdas.
inline void kernel_add_element(Composition& doc, ComposerElement element) {
    add_element(doc, std::move(element));
}
inline void kernel_set_paper(Composition& doc, const std::string& paper_size,
                             const std::string& orientation) {
    set_paper(doc, paper_size, orientation);
}

ComposerElement& find_ref(Composition& doc, const std::string& element_id) {
    ComposerElement* element = find_element(doc, element_id);
    if (element == nullptr) {
        throw UnknownElementError("no composition element " + quoted(element_id));
    }
    return *element;
}

}  // namespace

// ---------------------------------------------------------------------------
// CompositionFactory
// ---------------------------------------------------------------------------

CompositionFactory::CompositionFactory(SpecProvider provider)
    : provider_(std::move(provider)) {}

std::string CompositionFactory::id_body() const {
    if (id_generator_) return id_generator_();
    char buffer[32];
    std::snprintf(buffer, sizeof(buffer), "%010llx",
                  static_cast<unsigned long long>(next_id_++));
    return buffer;
}

void CompositionFactory::set_element_id_generator(
    std::function<std::string()> generator) {
    id_generator_ = std::move(generator);
}

ComposerElement CompositionFactory::create(const std::string& element_type,
                                           std::optional<double> x_mm,
                                           std::optional<double> y_mm,
                                           std::optional<double> width_mm,
                                           std::optional<double> height_mm,
                                           Json properties) const {
    std::array<double, 4> geometry{0.0, 0.0, 1.0, 1.0};
    Json defaults = Json::object();
    if (provider_) {
        if (const ElementSpec* spec = provider_(element_type)) {
            geometry = spec->default_geometry;
            if (spec->default_properties.is_object()) {
                defaults = spec->default_properties;  // deep copy via assignment
            }
        }
    }
    if (!properties.is_object() && !properties.is_null()) {
        throw std::invalid_argument(
            "composition factory: properties must be an object");
    }
    if (properties.is_object()) {
        // Python: {**deepcopy(spec.default_properties), **dict(properties)}
        // — shallow top-level merge, later keys win.
        for (auto it = properties.begin(); it != properties.end(); ++it) {
            defaults[it.key()] = it.value();
        }
    }
    ComposerElement element;
    element.id = new_element_id();
    element.element_type = element_type;
    element.x_mm = x_mm.value_or(geometry[0]);
    element.y_mm = y_mm.value_or(geometry[1]);
    element.width_mm = width_mm.value_or(geometry[2]);
    element.height_mm = height_mm.value_or(geometry[3]);
    element.properties = defaults;
    return element;
}

Composition CompositionFactory::create_document(const std::string& title,
                                                const std::string& paper_size,
                                                const std::string& orientation,
                                                double dpi) const {
    Composition doc;
    doc.id = "comp_" + id_body();
    doc.title = title;
    doc.dpi = dpi;
    set_paper(doc, paper_size, orientation);  // throws on unknown size
    return doc;
}

// ---------------------------------------------------------------------------
// CompositionEditSession
// ---------------------------------------------------------------------------

CompositionEditSession::CompositionEditSession(Composition& document,
                                               CompositionFactory factory)
    : document_(&document), factory_(std::move(factory)) {}

const ComposerElement& CompositionEditSession::require(
    const std::string& element_id) const {
    return find_ref(*document_, element_id);
}

const ComposerElement& CompositionEditSession::require_mutable(
    const std::string& element_id) const {
    const ComposerElement& element = require(element_id);
    if (element.locked) {
        throw ComposerError(
            "composition element " + quoted(element.id) +
            " is locked; unlock it before move/scale/configure/remove/duplicate");
    }
    return element;
}

void CompositionEditSession::discard(const std::string& element_id) {
    auto& elements = document_->elements;
    for (auto it = elements.begin(); it != elements.end(); ++it) {
        if (it->id == element_id) {
            elements.erase(it);
            return;
        }
    }
}

ComposerElement CompositionEditSession::add_element(const std::string& element_type,
                                                    std::optional<double> x_mm,
                                                    std::optional<double> y_mm,
                                                    std::optional<double> width_mm,
                                                    std::optional<double> height_mm,
                                                    Json properties) {
    ComposerElement element =
        factory_.create(element_type, x_mm, y_mm, width_mm, height_mm, properties);
    const std::string id = element.id;
    stack_.execute(std::make_unique<LambdaCommand>(
        "add " + element.element_type, RevisionKind::kLayout,
        [this, element]() { kernel_add_element(*document_, element); },
        [this, id]() { discard(id); }));
    return element;
}

void CompositionEditSession::insert_element(ComposerElement element) {
    const std::string id = element.id;
    stack_.execute(std::make_unique<LambdaCommand>(
        "insert " + element.element_type, RevisionKind::kLayout,
        [this, element]() { kernel_add_element(*document_, element); },
        [this, id]() { discard(id); }));
}

std::optional<ComposerElement> CompositionEditSession::remove_element(
    const std::string& element_id) {
    ComposerElement* element = find_element(*document_, element_id);
    if (element == nullptr) return std::nullopt;
    require_mutable(element_id);  // locked refusal before any capture
    const std::size_t index =
        static_cast<std::size_t>(element - document_->elements.data());
    const ComposerElement removed = *element;
    stack_.execute(std::make_unique<LambdaCommand>(
        "remove " + removed.element_type, RevisionKind::kLayout,
        [this, element_id]() { discard(element_id); },
        [this, removed, index]() {
            auto& elements = document_->elements;
            // Python revert inserts at the captured index; no re-sort.
            const std::size_t at = std::min(index, elements.size());
            elements.insert(elements.begin() + static_cast<std::ptrdiff_t>(at),
                            removed);
        }));
    return removed;
}

void CompositionEditSession::move_element(const std::string& element_id,
                                          double x_mm, double y_mm) {
    const ComposerElement& current = require_mutable(element_id);
    const double old_x = current.x_mm;
    const double old_y = current.y_mm;
    stack_.execute(std::make_unique<LambdaCommand>(
        "move", RevisionKind::kLayout,
        [this, element_id, x_mm, y_mm]() {
            ComposerElement& element = find_ref(*document_, element_id);
            element.x_mm = x_mm;
            element.y_mm = y_mm;
        },
        [this, element_id, old_x, old_y]() {
            // Resolve at revert time: the vector may have been re-sorted.
            ComposerElement& element = find_ref(*document_, element_id);
            element.x_mm = old_x;
            element.y_mm = old_y;
        }));
}

void CompositionEditSession::scale_element(const std::string& element_id,
                                           double width_mm, double height_mm) {
    // Python order: the locked refusal precedes the positivity check.
    const ComposerElement& current = require_mutable(element_id);
    if (width_mm <= 0.0 || height_mm <= 0.0) {
        throw std::invalid_argument("component size must be positive");
    }
    const double old_w = current.width_mm;
    const double old_h = current.height_mm;
    stack_.execute(std::make_unique<LambdaCommand>(
        "scale", RevisionKind::kLayout,
        [this, element_id, width_mm, height_mm]() {
            ComposerElement& element = find_ref(*document_, element_id);
            element.width_mm = width_mm;
            element.height_mm = height_mm;
        },
        [this, element_id, old_w, old_h]() {
            ComposerElement& element = find_ref(*document_, element_id);
            element.width_mm = old_w;
            element.height_mm = old_h;
        }));
}

void CompositionEditSession::configure_element(const std::string& element_id,
                                               Json properties) {
    // Python order: the locked refusal precedes the properties check.
    require_mutable(element_id);
    if (!properties.is_object()) {
        throw std::invalid_argument(
            "configure: properties must be an object (Python Mapping)");
    }
    const Json old_properties =
        find_ref(*document_, element_id).properties;  // full revert capture
    const Json updates = properties;
    stack_.execute(std::make_unique<LambdaCommand>(
        "configure", RevisionKind::kLayout,
        [this, element_id, updates]() {
            ComposerElement& element = find_ref(*document_, element_id);
            for (auto it = updates.begin(); it != updates.end(); ++it) {
                element.properties[it.key()] = it.value();  // update() merge
            }
        },
        [this, element_id, old_properties]() {
            find_ref(*document_, element_id).properties = old_properties;
        }));
}

std::optional<ComposerElement> CompositionEditSession::duplicate_element(
    const std::string& element_id) {
    const ComposerElement* element = find_element(*document_, element_id);
    if (element == nullptr) return std::nullopt;
    require_mutable(element_id);
    ComposerElement clone;
    clone.id = factory_.new_element_id();
    clone.element_type = element->element_type;
    clone.x_mm = element->x_mm + 5.0;
    clone.y_mm = element->y_mm + 5.0;
    clone.width_mm = element->width_mm;
    clone.height_mm = element->height_mm;
    clone.z_index = element->z_index + 1;
    clone.visible = element->visible;
    clone.locked = false;  // 复制件默认可编辑
    clone.properties = element->properties;
    const std::string clone_id = clone.id;
    stack_.execute(std::make_unique<LambdaCommand>(
        "duplicate", RevisionKind::kLayout,
        [this, clone]() { kernel_add_element(*document_, clone); },
        [this, clone_id]() { discard(clone_id); }));
    return clone;
}

void CompositionEditSession::set_locked(const std::string& element_id, bool locked) {
    const bool old = require(element_id).locked;
    stack_.execute(std::make_unique<LambdaCommand>(
        "lock", RevisionKind::kLayout,
        [this, element_id, locked]() {
            find_ref(*document_, element_id).locked = locked;
        },
        [this, element_id, old]() {
            find_ref(*document_, element_id).locked = old;
        }));
}

void CompositionEditSession::set_element_visible(const std::string& element_id,
                                                 bool visible) {
    const bool old = require(element_id).visible;
    stack_.execute(std::make_unique<LambdaCommand>(
        "visibility", RevisionKind::kLayout,
        [this, element_id, visible]() {
            find_ref(*document_, element_id).visible = visible;
        },
        [this, element_id, old]() {
            find_ref(*document_, element_id).visible = old;
        }));
}

void CompositionEditSession::bring_to_front(const std::string& element_id) {
    require(element_id);
    // Python: max/min over the element z's, default=0 only for an EMPTY
    // document — the seed value must not participate as a candidate.
    long long top = document_->elements.front().z_index;
    for (const ComposerElement& other : document_->elements) {
        top = std::max(top, other.z_index);
    }
    stack_.execute(std::make_unique<LambdaCommand>(
        "bring_to_front", RevisionKind::kLayout,
        [this, element_id, top]() {
            ComposerElement& element = find_ref(*document_, element_id);
            element.z_index = top + 1;
            sort_by_z(*document_);
        },
        [this, element_id, top]() {
            ComposerElement& element = find_ref(*document_, element_id);
            element.z_index = top;
            sort_by_z(*document_);
        }));
}

void CompositionEditSession::send_to_back(const std::string& element_id) {
    require(element_id);
    long long bottom = document_->elements.front().z_index;
    for (const ComposerElement& other : document_->elements) {
        bottom = std::min(bottom, other.z_index);
    }
    stack_.execute(std::make_unique<LambdaCommand>(
        "send_to_back", RevisionKind::kLayout,
        [this, element_id, bottom]() {
            ComposerElement& element = find_ref(*document_, element_id);
            element.z_index = bottom - 1;
            sort_by_z(*document_);
        },
        [this, element_id, bottom]() {
            ComposerElement& element = find_ref(*document_, element_id);
            element.z_index = bottom;
            sort_by_z(*document_);
        }));
}

void CompositionEditSession::raise_element(const std::string& element_id) {
    const long long old = find_ref(*document_, element_id).z_index;
    stack_.execute(std::make_unique<LambdaCommand>(
        "raise", RevisionKind::kLayout,
        [this, element_id, old]() {
            ComposerElement& element = find_ref(*document_, element_id);
            element.z_index = old + 1;
            sort_by_z(*document_);
        },
        [this, element_id, old]() {
            ComposerElement& element = find_ref(*document_, element_id);
            element.z_index = old;
            sort_by_z(*document_);
        }));
}

void CompositionEditSession::set_paper(const std::string& paper_size,
                                       const std::string& orientation) {
    std::string canonical;
    std::pair<double, double> edges{0.0, 0.0};
    if (!known_paper_size(paper_size, canonical, edges)) {
        throw std::invalid_argument("unknown paper size '" + paper_size + "'");
    }
    struct PaperState {
        std::string paper_size;
        std::string orientation;
        double width_mm;
        double height_mm;
    } const old{document_->paper_size, document_->orientation,
                document_->width_mm, document_->height_mm};
    stack_.execute(std::make_unique<LambdaCommand>(
        "set_paper", RevisionKind::kLayout,
        [this, paper_size, orientation]() {
            kernel_set_paper(*document_, paper_size, orientation);
        },
        [this, old]() {
            document_->paper_size = old.paper_size;
            document_->orientation = old.orientation;
            document_->width_mm = old.width_mm;
            document_->height_mm = old.height_mm;
        }));
}

void CompositionEditSession::set_title(const std::string& title) {
    const std::string old = document_->title;
    stack_.execute(std::make_unique<LambdaCommand>(
        "set_title", RevisionKind::kLayout,
        [this, title]() { document_->title = title; },
        [this, old]() { document_->title = old; }));
}

void CompositionEditSession::set_metadata(const std::string& key, Json value) {
    struct MetaState {
        bool had_entry = false;
        Json entry;
    } old;
    if (document_->metadata.is_object() && document_->metadata.contains(key)) {
        old.had_entry = true;
        old.entry = document_->metadata.at(key);
    }
    stack_.execute(std::make_unique<LambdaCommand>(
        "set_metadata", RevisionKind::kLayout,
        [this, key, value]() {
            if (!document_->metadata.is_object()) {
                document_->metadata = Json::object();
            }
            document_->metadata[key] = value;
        },
        [this, key, old]() {
            if (!document_->metadata.is_object()) return;
            if (old.had_entry) {
                document_->metadata[key] = old.entry;
            } else {
                document_->metadata.erase(key);
            }
        }));
}

long long bind_template(Composition& document, const Json& binding_context) {
    if (!binding_context.is_object()) return 0;
    long long resolved = 0;
    for (ComposerElement& element : document.elements) {
        if (!element.properties.is_object()) continue;
        const auto binding_it = element.properties.find("data_binding");
        if (binding_it == element.properties.end() || !binding_it->is_object()) {
            continue;
        }
        const Json binding = *binding_it;  // copy: properties mutate below
        const bool has_key = binding.contains("key") && !binding.at("key").is_null();
        const std::string key =
            has_key && binding.at("key").is_string()
                ? binding.at("key").get<std::string>()
                : (has_key ? binding.at("key").dump() : std::string());
        if (key.empty() || !binding_context.contains(key)) continue;
        Json updates = binding_context.at(key);
        // Python `if fields:` — an EMPTY fields list is falsy and does not
        // filter; only a non-empty list restricts the update keys.
        if (binding.contains("fields") && binding.at("fields").is_array()
            && !binding.at("fields").empty()) {
            Json filtered = Json::object();
            for (const auto& field : binding.at("fields")) {
                if (field.is_string()
                    && updates.contains(field.get<std::string>())) {
                    const std::string name = field.get<std::string>();
                    filtered[name] = updates.at(name);
                }
            }
            updates = std::move(filtered);
        }
        if (!updates.is_object()) continue;
        for (auto it = updates.begin(); it != updates.end(); ++it) {
            element.properties[it.key()] = it.value();
        }
        ++resolved;
    }
    return resolved;
}

}  // namespace pwb::mapping_document
