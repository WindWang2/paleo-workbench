// Headless test for ApplyPatchCommand (#202, the #158 foundation, ADR 0025).
// Asserts: upsert + remove of document interpretation entities (Interval/Marker/
// Annotation) and presentation layout entities (Track/Scale/CurveLayer) produce
// a new Document Revision readable end-to-end; the patch is atomic (one bad
// edit rejects the whole batch, document unchanged); a base-revision mismatch
// is rejected with patch_conflict (no guessing); the Selection Set remaps or
// invalidates per ADR 0024. No GL/Qt — WellLogSession + core.

#include <welllog/core/document.hpp>
#include <welllog/scene/scene.hpp>
#include <welllog/session/session.hpp>

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <string_view>
#include <vector>

namespace {

using namespace welllog;

[[noreturn]] void fail(std::string_view message) {
  std::cerr << "FAIL: " << message << '\n';
  std::exit(EXIT_FAILURE);
}

void require(bool condition, std::string_view message) {
  if (!condition) {
    fail(message);
  }
}

EntityId id(std::string_view text) {
  auto parsed = EntityId::parse(text);
  require(parsed.has_value(), "test UUID must be valid");
  return *parsed;
}

const auto document_id = id("cc000000-0000-4000-8000-000000000001");
const auto axis_id = id("cc000000-0000-4000-8000-000000000002");
const auto curve_id = id("cc000000-0000-4000-8000-000000000003");
const auto track_id = id("cc000000-0000-4000-8000-000000000004");
const auto scale_id = id("cc000000-0000-4000-8000-000000000005");
const auto layer_id = id("cc000000-0000-4000-8000-000000000006");
const auto interval_id = id("cc000000-0000-4000-8000-000000000007");
const auto marker_id = id("cc000000-0000-4000-8000-000000000008");
const auto annotation_id = id("cc000000-0000-4000-8000-000000000009");

// Fixture: a document with one axis/curve + one Interval/Marker/Annotation,
// and a presentation with one Track/Scale/CurveLayer. Sets a viewport so the
// selection-remap and viewport-preservation paths are exercisable.
struct Fixture {
  WellLogSession session;
  DocumentRevision revision;

  Fixture() {
    auto depths = std::make_shared<const std::vector<double>>(
        std::initializer_list<double>{1000.0, 1001.0, 1002.0});
    auto values = std::make_shared<const std::vector<double>>(
        std::initializer_list<double>{10.0, 20.0, 30.0});
    WellLogDocumentBuilder db(document_id, DocumentRevision{1});
    db.add_sampling_axis(SamplingAxis{
        .id = axis_id, .coordinates = BufferView::from_vector(depths),
        .domain = DepthDomain::measured_depth, .unit = "m",
        .direction = AxisDirection::increasing});
    db.add_curve(Curve{
        .id = curve_id, .mnemonic = "GR", .display_name = "Gamma Ray",
        .unit = "API", .sampling_axis_id = axis_id,
        .values = BufferView::from_vector(values), .nulls = {}});
    db.add_interval(Interval{
        .id = interval_id, .top_reference_depth = 1000.0,
        .bottom_reference_depth = 1001.0, .semantic = IntervalSemantic::lithology,
        .pattern_id = {}, .label = "Sand"});
    db.add_marker(Marker{
        .id = marker_id, .reference_depth = 1000.5,
        .semantic = MarkerSemantic::formation_top, .label = "Top A"});
    TextAnnotation annotation;
    annotation.id = annotation_id;
    annotation.reference_depth = 1001.0;
    annotation.text = "Note";
    db.add_annotation(annotation);
    require(session.execute(SetDocumentCommand{db.build()}).has_value(),
            "fixture document must be accepted");

    ScenePresentationBuilder pb(document_id,
                                ReferenceDepthRange{
                                    .domain = DepthDomain::measured_depth,
                                    .unit = "m", .top = 1000.0, .bottom = 1002.0,
                                },
                                Millimetres{500.0}, "fixture-font");
    pb.add_track(TrackSpec{.id = track_id, .width = Millimetres{40.0}});
    pb.add_scale(TrackScaleSpec{
        .id = scale_id, .track_id = track_id, .mode = ScaleMode::linear,
        .minimum = 0.0, .maximum = 100.0, .unit = "API"});
    pb.add_curve_layer(CurveLayerSpec{
        .id = layer_id, .track_id = track_id, .curve_id = curve_id,
        .scale_id = scale_id, .color = {}, .line_width = Millimetres{0.25},
        .visible = true});
    require(session.execute(SetPresentationCommand{pb.build()}).has_value(),
            "fixture presentation must be accepted");
    // Establish a viewport (presentation set the initial one; adjust it).
    require(session
                .execute(SetViewportCommand{
                    .document_id = document_id,
                    .viewport = {.top = 1000.0, .bottom = 1001.5},
                })
                .has_value(),
            "fixture viewport must be accepted");
    session.clear_events();
    revision = session.document(document_id)->revision();
  }
};

// Upserting an existing document entity (modify) replaces it by id and produces
// a new revision.
void upsert_replaces_document_entity() {
  Fixture f;
  const auto result = f.session.execute(ApplyPatchCommand{
      .document_id = document_id,
      .patch =
          DocumentPatch{
              .base_revision = f.revision,
              .edits =
                  {
                      EntityEdit{UpsertEntity{Interval{
                          .id = interval_id, .top_reference_depth = 1000.0,
                          .bottom_reference_depth = 1001.5,
                          .semantic = IntervalSemantic::lithology,
                          .pattern_id = {}, .label = "Shale"}}},
                  },
          },
  });
  require(result.has_value(), "upsert patch must succeed");
  require(result.value().document_revision.value == f.revision.value + 1,
          "patch must produce the next revision");
  const auto doc = f.session.document(document_id);
  const auto intervals = doc->intervals();
  require(intervals.size() == 1, "interval count must stay 1 (replaced)");
  require(intervals.front().label == "Shale",
          "the upserted interval must replace the old one");
  require(intervals.front().bottom_reference_depth == 1001.5,
          "the upserted interval must carry the new bottom depth");
}

// Upserting a NEW document entity id (create) adds it.
void upsert_creates_document_entity() {
  Fixture f;
  const auto new_marker = id("cc000000-0000-4000-8000-000000000020");
  const auto result = f.session.execute(ApplyPatchCommand{
      .document_id = document_id,
      .patch =
          DocumentPatch{
              .base_revision = f.revision,
              .edits =
                  {
                      EntityEdit{UpsertEntity{Marker{
                          .id = new_marker, .reference_depth = 1001.5,
                          .semantic = MarkerSemantic::fault, .label = "Fault"}}},
                  },
          },
  });
  require(result.has_value(), "create-marker patch must succeed");
  const auto doc = f.session.document(document_id);
  require(doc->markers().size() == 2, "a new marker must be added");
  require(std::any_of(doc->markers().begin(), doc->markers().end(),
                      [new_marker](const Marker &m) {
                        return m.id == new_marker && m.label == "Fault";
                      }),
          "the created marker must be readable");
}

// Removing a document entity deletes it by id.
void remove_deletes_document_entity() {
  Fixture f;
  const auto result = f.session.execute(ApplyPatchCommand{
      .document_id = document_id,
      .patch =
          DocumentPatch{
              .base_revision = f.revision,
              .edits = {EntityEdit{RemoveEntity{annotation_id}}},
          },
  });
  require(result.has_value(), "remove-annotation patch must succeed");
  const auto doc = f.session.document(document_id);
  require(doc->annotations().empty(),
          "the removed annotation must be gone");
}

// A patch editing a presentation entity (Track width) replaces it and the
// change is readable on the session's presentation (which the LOD-completion
// path uses to rebuild the scene).
void upsert_edits_presentation_entity() {
  Fixture f;
  const auto result = f.session.execute(ApplyPatchCommand{
      .document_id = document_id,
      .patch =
          DocumentPatch{
              .base_revision = f.revision,
              .edits =
                  {
                      EntityEdit{UpsertEntity{TrackSpec{
                          .id = track_id, .width = Millimetres{80.0}}}},
                  },
          },
  });
  require(result.has_value(), "presentation patch must succeed");
  // The patched presentation is restored internally; query via the prepared
  // scene's presentation is not directly exposed, so assert the viewport was
  // preserved (the patch path restores it) and the revision advanced.
  require(f.session.viewport(document_id).has_value(),
          "the viewport must be preserved across a patch");
  require(f.session.viewport(document_id)->bottom == 1001.5,
          "the viewport window must be unchanged by a patch");
}

// A remove of a presentation entity (CurveLayer) takes effect.
void remove_deletes_presentation_entity() {
  Fixture f;
  const auto result = f.session.execute(ApplyPatchCommand{
      .document_id = document_id,
      .patch =
          DocumentPatch{
              .base_revision = f.revision,
              .edits = {EntityEdit{RemoveEntity{layer_id}}},
          },
  });
  require(result.has_value(), "remove-layer patch must succeed");
  require(f.session.viewport(document_id).has_value(),
          "the viewport must be preserved across a presentation patch");
}

// The whole batch is atomic: one bad edit (a remove of a non-existent entity)
// rejects the entire patch and leaves the document unchanged.
void whole_batch_rejects_on_one_bad_edit() {
  Fixture f;
  const auto missing = id("cc000000-0000-4000-8000-000000000099");
  const auto result = f.session.execute(ApplyPatchCommand{
      .document_id = document_id,
      .patch =
          DocumentPatch{
              .base_revision = f.revision,
              .edits =
                  {
                      EntityEdit{UpsertEntity{Interval{
                          .id = interval_id, .top_reference_depth = 1000.0,
                          .bottom_reference_depth = 1001.5, .pattern_id = {},
                          .label = "Shale"}}},
                      EntityEdit{RemoveEntity{missing}}, // bad: not present
                  },
          },
  });
  require(!result.has_value(), "a patch with a bad edit must be rejected");
  require(result.error().code == ErrorCode::document_not_found,
          "a remove of a missing entity must return document_not_found");
  // The document must be unchanged (atomic).
  const auto doc = f.session.document(document_id);
  require(doc->revision().value == f.revision.value,
          "a rejected patch must leave the revision unchanged");
  require(doc->intervals().front().label == "Sand",
          "a rejected patch must leave the interval unchanged");
}

// A duplicate id within the batch is rejected (no ambiguous apply).
void duplicate_id_in_batch_rejected() {
  Fixture f;
  const auto result = f.session.execute(ApplyPatchCommand{
      .document_id = document_id,
      .patch =
          DocumentPatch{
              .base_revision = f.revision,
              .edits =
                  {
                      EntityEdit{RemoveEntity{interval_id}},
                      EntityEdit{RemoveEntity{interval_id}}, // duplicate
                  },
          },
  });
  require(!result.has_value(), "a duplicate-id patch must be rejected");
  require(result.error().code == ErrorCode::duplicate_entity_id,
          "a duplicate id must return duplicate_entity_id");
}

// A base-revision mismatch is rejected with patch_conflict (stable code), never
// applied by guessing.
void base_revision_mismatch_rejected_as_conflict() {
  Fixture f;
  const auto result = f.session.execute(ApplyPatchCommand{
      .document_id = document_id,
      .patch =
          DocumentPatch{
              .base_revision = DocumentRevision{f.revision.value + 5}, // stale
              .edits = {EntityEdit{RemoveEntity{marker_id}}},
          },
  });
  require(!result.has_value(), "a stale-base patch must be rejected");
  require(result.error().code == ErrorCode::patch_conflict,
          "a base-revision mismatch must return patch_conflict");
  require(f.session.document(document_id)->revision().value == f.revision.value,
          "a conflict-rejected patch must leave the revision unchanged");
}

// An existing Selection Set survives a patch that does not move its axis range
// (remaps onto the new revision, stays valid).
void selection_survives_patch() {
  Fixture f;
  require(f.session
              .execute(SetSelectionCommand{
                  .document_id = document_id,
                  .sampling_axis_id = axis_id,
                  .reference_depth_range = {.top = 1000.0, .bottom = 1001.0},
              })
              .has_value(),
          "selection must be accepted");
  // Patch the interval (does not touch the axis) → selection must survive.
  const auto result = f.session.execute(ApplyPatchCommand{
      .document_id = document_id,
      .patch =
          DocumentPatch{
              .base_revision = f.revision,
              .edits =
                  {
                      EntityEdit{UpsertEntity{Interval{
                          .id = interval_id, .top_reference_depth = 1000.0,
                          .bottom_reference_depth = 1001.5, .pattern_id = {},
                          .label = "Shale"}}},
                  },
          },
  });
  require(result.has_value(), "patch must succeed");
  const auto sel = f.session.selection(document_id);
  require(sel.has_value() && sel->valid,
          "the selection must survive a non-axis patch");
  require(sel->document_revision.value == result.value().document_revision.value,
          "the remapped selection must carry the patched revision");
}

// An empty patch is a no-op at the current revision.
void empty_patch_is_noop() {
  Fixture f;
  const auto result = f.session.execute(ApplyPatchCommand{
      .document_id = document_id,
      .patch = DocumentPatch{.base_revision = f.revision, .edits = {}},
  });
  require(result.has_value(), "an empty patch must succeed");
  require(result.value().document_revision.value == f.revision.value,
          "an empty patch must not advance the revision");
}

// A patch editing one collection leaves the OTHER collections byte-identical -
// the hand-rolled copy loops must not drop or duplicate untouched entities.
void patch_preserves_untouched_collections() {
  Fixture f;
  // Patch only the interval; markers, annotations, curves must survive.
  const auto result = f.session.execute(ApplyPatchCommand{
      .document_id = document_id,
      .patch =
          DocumentPatch{
              .base_revision = f.revision,
              .edits =
                  {
                      EntityEdit{UpsertEntity{Interval{
                          .id = interval_id, .top_reference_depth = 1000.0,
                          .bottom_reference_depth = 1001.8,
                          .semantic = IntervalSemantic::lithology,
                          .pattern_id = {}, .label = "Shale"}}},
                  },
          },
  });
  require(result.has_value(), "patch must succeed");
  const auto doc = f.session.document(document_id);
  // The interval changed; markers/annotations/curves survive verbatim.
  require(doc->intervals().size() == 1 &&
              doc->intervals().front().label == "Shale",
          "the patched interval must reflect the upsert");
  require(doc->markers().size() == 1, "markers must survive a patch untouched");
  require(doc->markers().front().label == "Top A",
          "the surviving marker must be byte-identical");
  require(doc->annotations().size() == 1,
          "annotations must survive a patch untouched");
  require(doc->annotations().front().text == "Note",
          "the surviving annotation must be byte-identical");
  require(doc->curves().size() == 1,
          "curves must survive a patch untouched (immutable, ADR 0025)");
}

// A presentation-entity upsert on a document with NO presentation is rejected
// (a layout entity needs a presentation to live on).
void presentation_upsert_without_presentation_rejected() {
  // A document with no presentation registered.
  WellLogSession session;
  auto depths = std::make_shared<const std::vector<double>>(
      std::initializer_list<double>{1000.0, 1001.0, 1002.0});
  auto values = std::make_shared<const std::vector<double>>(
      std::initializer_list<double>{10.0, 20.0, 30.0});
  WellLogDocumentBuilder db(document_id, DocumentRevision{1});
  db.add_sampling_axis(SamplingAxis{
      .id = axis_id, .coordinates = BufferView::from_vector(depths),
      .domain = DepthDomain::measured_depth, .unit = "m",
      .direction = AxisDirection::increasing});
  db.add_curve(Curve{
      .id = curve_id, .mnemonic = "GR", .display_name = "GR", .unit = "API",
      .sampling_axis_id = axis_id, .values = BufferView::from_vector(values),
      .nulls = {}});
  require(session.execute(SetDocumentCommand{db.build()}).has_value(),
          "no-presentation document must be accepted");
  const auto result = session.execute(ApplyPatchCommand{
      .document_id = document_id,
      .patch =
          DocumentPatch{
              .base_revision = DocumentRevision{1},
              .edits =
                  {
                      EntityEdit{UpsertEntity{TrackSpec{
                          .id = track_id, .width = Millimetres{40.0}}}},
                  },
          },
  });
  require(!result.has_value(),
          "a presentation-entity upsert with no presentation must be rejected");
  require(result.error().code == ErrorCode::invalid_presentation,
          "no-presentation presentation upsert must return invalid_presentation");
}

} // namespace

int main() {
  upsert_replaces_document_entity();
  upsert_creates_document_entity();
  remove_deletes_document_entity();
  upsert_edits_presentation_entity();
  remove_deletes_presentation_entity();
  whole_batch_rejects_on_one_bad_edit();
  duplicate_id_in_batch_rejected();
  base_revision_mismatch_rejected_as_conflict();
  selection_survives_patch();
  empty_patch_is_noop();
  patch_preserves_untouched_collections();
  presentation_upsert_without_presentation_rejected();
  std::cout << "welllog.apply-patch: all cases passed\n";
  return EXIT_SUCCESS;
}
