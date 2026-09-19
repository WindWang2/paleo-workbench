// ui_workers.lifecycle — worker-side behavior tests that are not oracle
// replays. Currently: #1391 ragged grid_z rejection.
//
// The legacy `parameters["grid_z"]` bag can carry ragged rows (external
// project JSON). Pre-fix, any_to_grid flattened them into a Grid2D whose
// rows*cols no longer matched data.size(), and every downstream
// Grid2D::at()/marching-squares read went out of bounds. The numpy
// asarray equivalent raises, so the contract is PyValueError — which
// compile_contour_drafts_for_project then skips per-task like Python.

#include <pwb/ui_workers/contour_draft.hpp>
#include <pwb/ui_workers/worker_common.hpp>

#include <any>
#include <cstdio>
#include <optional>
#include <string>
#include <vector>

namespace {

namespace uw = pwb::ui_workers;
namespace job = pwb::job;

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const char* what) {
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::fprintf(stderr, "FAIL %s\n", what);
    }
}

uw::FactorTaskSlice ragged_task(std::any grid_z) {
    uw::FactorTaskSlice task;
    task.id = "t1";
    task.name = "ragged";
    task.status = "complete";
    task.factor_type = "factor";
    task.parameters["grid_z"] = std::move(grid_z);
    task.parameters["grid_x"] = std::vector<double>{0.0, 1.0, 2.0};
    task.parameters["grid_y"] = std::vector<double>{0.0, 1.0};
    return task;
}

// Runs the public pipeline entry; expects the ragged-grid PyValueError out
// of any_to_grid (not the unrelated missing-grid error — same exception
// class, different message) before the extract seam is ever reached.
bool throws_ragged_grid_error(uw::FactorTaskSlice task) {
    job::CancellationToken token;
    try {
        (void)uw::contour_draft_from_factor_task(
            task, std::nullopt, 5, std::nullopt, token,
            uw::ExtractLinesFn{}, uw::IdFn{});
    } catch (const uw::PyValueError& e) {
        return e.py_message() == "grid_z 维数错误";
    } catch (...) {
        return false;
    }
    return false;
}

}  // namespace

int main() {
    // vector<vector<double>> path: second row longer than the first.
    check(throws_ragged_grid_error(ragged_task(std::vector<std::vector<double>>{
              {1.0, 2.0}, {3.0, 4.0, 5.0}})),
          "ragged vector<vector<double>> grid_z must raise PyValueError");

    // vector<any> path: rows of mixed length.
    {
        std::vector<std::any> rows;
        rows.emplace_back(std::vector<double>{1.0, 2.0, 3.0});
        rows.emplace_back(std::vector<double>{4.0});
        check(throws_ragged_grid_error(ragged_task(std::move(rows))),
              "ragged vector<any> grid_z must raise PyValueError");
    }

    // Rectangular input still compiles fine (guard against over-reject).
    {
        uw::FactorTaskSlice ok_task = ragged_task(
            std::vector<std::vector<double>>{{1.0, 2.0}, {3.0, 4.0}});
        job::CancellationToken token;
        bool raised = false;
        try {
            (void)uw::contour_draft_from_factor_task(
                ok_task, std::nullopt, 5, std::nullopt, token,
                uw::ExtractLinesFn{}, uw::IdFn{});
        } catch (const uw::PyValueError&) {
            raised = true;   // grid shape was rejected — wrong
        } catch (const uw::PyImportError&) {
            // Expected: the extract seam is absent in this test — the grid
            // itself was accepted and we reached the seam boundary.
        }
        check(!raised, "rectangular grid_z must not raise PyValueError");
    }

    std::printf("ui_workers.lifecycle: %d checks, %d failures\n", g_checks,
                g_failures);
    return g_failures == 0 ? 0 : 1;
}
