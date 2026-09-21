#include "pwb/ui_stageflow/surface_state.hpp"

namespace pwb::ui_stageflow {

SurfaceState surface_state_for(SurfaceKind kind) {
    SurfaceState state;
    state.kind = kind;
    switch (kind) {
        case SurfaceKind::Ready:
            state.title = "就绪";
            state.hint = "数据与图层均为当前状态。";
            break;
        case SurfaceKind::Loading:
            state.title = "正在加载…";
            state.hint = "正在读取数据，完成后自动显示。";
            break;
        case SurfaceKind::Busy:
            state.title = "后台计算中";
            state.hint = "任务在后台运行，可继续其他操作；进度见任务中心。";
            break;
        case SurfaceKind::Queued:
            state.title = "排队中";
            state.hint = "任务已提交，等待计算资源。";
            break;
        case SurfaceKind::Cancelled:
            state.title = "已取消";
            state.hint = "任务被取消，结果未采用。可重新发起。";
            break;
        case SurfaceKind::Stale:
            state.title = "结果已过期";
            state.hint = "输入在计算后发生了变化。请重新计算后再用于编图。";
            state.retry_action_id = "surface.recompute";
            break;
        case SurfaceKind::Degraded:
            state.title = "降级完成";
            state.hint = "任务完成但有警告，结果可用性受限。";
            break;
        case SurfaceKind::MissingSource:
            state.title = "来源缺失";
            state.hint = "所需的数据源不存在或已被移动。请重新关联来源。";
            state.retry_action_id = "surface.relink";
            break;
        case SurfaceKind::Unsupported:
            state.title = "此版本暂不支持";
            state.hint = "该能力尚未在本产品中开放。";
            break;
        case SurfaceKind::Error:
            state.title = "加载失败";
            state.hint = "发生错误。可重试；若持续失败请查看日志。";
            state.retry_action_id = "surface.retry";
            break;
        case SurfaceKind::NoProject:
            state.title = "未打开工程";
            state.hint = "从「工程」菜单新建或打开工程后开始。";
            break;
        case SurfaceKind::NoLayer:
            state.title = "暂无图层";
            state.hint = "当前上下文没有可显示的图层。";
            break;
        case SurfaceKind::NoSelection:
            state.title = "未选择对象";
            state.hint = "在地图或面板中选择对象后此处显示详情。";
            break;
        case SurfaceKind::Empty:
            state.title = "暂无内容";
            state.hint = "尚无内容可显示。";
            break;
    }
    return state;
}

SurfaceTokenKey surface_token_key(SurfaceKind kind) {
    SurfaceTokenKey key;
    switch (kind) {
        case SurfaceKind::Ready:
            key.category = "freshness";
            key.value = "current";
            break;
        case SurfaceKind::Loading:
        case SurfaceKind::Busy:
        case SurfaceKind::Queued:
            key.category = "task";
            key.value = "running";
            break;
        case SurfaceKind::Cancelled:
            key.category = "task";
            key.value = "cancelled";
            break;
        case SurfaceKind::Stale:
            key.category = "freshness";
            key.value = "stale";
            break;
        case SurfaceKind::Degraded:
            key.category = "task";
            key.value = "degraded";
            break;
        case SurfaceKind::MissingSource:
            key.category = "freshness";
            key.value = "missing";
            break;
        case SurfaceKind::Unsupported:
            key.category = "backend";
            key.value = "missing";
            break;
        case SurfaceKind::Error:
            key.category = "task";
            key.value = "failed";
            break;
        case SurfaceKind::NoProject:
        case SurfaceKind::NoLayer:
        case SurfaceKind::NoSelection:
        case SurfaceKind::Empty:
            key.category = "readiness";
            key.value = "info";
            break;
    }
    return key;
}

SurfaceState surface_for_task(bool running, bool queued, bool cancelled,
                              bool failed, const std::string& error,
                              const std::string& subject) {
    // Order mirrors what the user can act on: failure beats cancellation
    // beats progress. Fail-closed — contradictory flags resolve to the
    // most conservative honest surface.
    if (failed) {
        auto state = surface_state_for(SurfaceKind::Error);
        state.title = subject + "：计算失败";
        if (!error.empty()) state.hint = error;
        return state;
    }
    if (cancelled) {
        auto state = surface_state_for(SurfaceKind::Cancelled);
        state.title = subject + "：已取消";
        return state;
    }
    if (running) {
        auto state = surface_state_for(SurfaceKind::Busy);
        state.title = subject + "：计算中";
        return state;
    }
    if (queued) {
        auto state = surface_state_for(SurfaceKind::Queued);
        state.title = subject + "：排队中";
        return state;
    }
    return surface_state_for(SurfaceKind::Ready);
}

SurfaceState surface_for_factor(bool computing, bool stale, bool missing_input,
                                bool failed, const std::string& subject) {
    if (failed) {
        auto state = surface_state_for(SurfaceKind::Error);
        state.title = subject + "：计算失败";
        return state;
    }
    if (computing) {
        auto state = surface_state_for(SurfaceKind::Busy);
        state.title = subject + "：计算中";
        state.hint = "单因素计算进行中，主地图暂时显示上次完成的结果或占位。";
        return state;
    }
    if (missing_input) {
        auto state = surface_state_for(SurfaceKind::MissingSource);
        state.title = subject + "：输入缺失";
        return state;
    }
    if (stale) {
        auto state = surface_state_for(SurfaceKind::Stale);
        state.title = subject + "：已过期";
        state.hint = "约束或输入在计算后发生了变化；过期结果不应直接用于综合编图。";
        return state;
    }
    return surface_state_for(SurfaceKind::Ready);
}

}  // namespace pwb::ui_stageflow
