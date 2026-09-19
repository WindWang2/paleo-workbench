// providers.plugins — line-10 dynamic plugin loading acceptance matrix:
// load ok / missing file / bad ABI / missing host capability / bad
// descriptor; execute through the guarded SDK pipeline (typed invocation);
// cancel through the host bridge; and the unload lifecycle — an unload
// requested while a task is inside the module is deferred, the running task
// completes, new executions fail fast with PluginUnloadPendingError, and
// the module is finalized when the last lease releases.

#include <atomic>
#include <chrono>
#include <cstdio>
#include <functional>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include <pwb/domain/json.hpp>
#include <pwb/providers/errors.hpp>
#include <pwb/providers/execution.hpp>
#include <pwb/providers/plugin_loader.hpp>
#include <pwb/providers/registry.hpp>

using pwb::domain::Json;
namespace pp = pwb::providers;

#ifndef PWB_PLUGIN_OK
#define PWB_PLUGIN_OK "missing-path"
#endif
#ifndef PWB_PLUGIN_BADABI
#define PWB_PLUGIN_BADABI "missing-path"
#endif
#ifndef PWB_PLUGIN_BADDESC
#define PWB_PLUGIN_BADDESC "missing-path"
#endif
#ifndef PWB_PLUGIN_MISSING_CAP
#define PWB_PLUGIN_MISSING_CAP "missing-path"
#endif

int g_failures = 0;
int g_checks = 0;

void check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok) {
        std::fprintf(stderr, "FAIL %s\n", what.c_str());
        ++g_failures;
    }
}

template <typename Fn, typename Ex>
std::string expect_throw_of(Fn&& fn) {
    try {
        fn();
    } catch (const Ex& exc) {
        return exc.what();
    } catch (const std::exception& exc) {
        return std::string("<wrong type: ") + exc.what() + ">";
    }
    return "<no throw>";
}

template <typename Fn>
std::string expect_any_throw(Fn&& fn) {
    try {
        fn();
    } catch (const std::exception& exc) {
        return exc.what();
    }
    return "<no throw>";
}

void wait_until(const std::function<bool()>& predicate, int timeout_ms) {
    const auto deadline =
        std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_ms);
    while (std::chrono::steady_clock::now() < deadline) {
        if (predicate()) return;
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
}

int main() {
    // --- 失败行为矩阵 -------------------------------------------------------
    {
        pp::ProviderRegistry registry;
        pp::PluginLoader loader(registry);
        std::string error = expect_throw_of<std::function<void()>, pp::PluginLoadError>(
            [&] { loader.load("/nonexistent/path/pwb_plugin.so"); });
        check(error.find("文件不存在") != std::string::npos,
              "missing file message: " + error);
        check(loader.loaded().empty(), "no module after failed load");
        check(registry.size() == 0, "registry untouched after failed load");
    }

    // --- OK 模块：加载、typed invocation 执行、结果重组 ----------------------
    {
        pp::ProviderRegistry registry;
        pp::PluginLoader loader(registry);
        const pp::PluginInfo info = loader.load(PWB_PLUGIN_OK);
        check(info.plugin_id == "test.ok", "ok plugin id");
        check(info.abi_version == pp::kPluginAbiVersion, "ok plugin abi");
        check(info.provider_ids.size() == 2, "two providers registered");
        check(registry.size() == 2, "registry has both providers");
        check(loader.find("test.ok") != nullptr, "find ok plugin");
        check(info.to_json().value("plugin_id", "") == "test.ok",
              "plugin info json");

        // Guarded pipeline: resolve → validate inputs/params → execute.
        pp::ProviderInputs inputs;
        pp::TypedInput typed;
        typed.type_name = "PathRef";
        typed.payload = pwb::providers::PathRef{"/tmp/in.las", "las"}.to_json();
        inputs.set("source", typed);
        pp::ProviderContext context;
        Json parameters = Json::object();
        parameters["say"] = "hello";
        const pp::ProviderResult result = pp::execute_provider(
            registry, "plugin.echo", inputs, parameters, &context);
        check(result.metrics.value("echo", "") == "hello",
              "echo round trip through the ABI");
        check(result.artifacts.size() == 1 && result.artifacts[0].name == "echo",
              "artifact reconstructed");
    }

    // --- 重复加载拒绝 ---------------------------------------------------------
    {
        pp::ProviderRegistry registry;
        pp::PluginLoader loader(registry);
        loader.load(PWB_PLUGIN_OK);
        const std::string error = expect_throw_of<std::function<void()>, pp::PluginLoadError>(
            [&] { loader.load(PWB_PLUGIN_OK); });
        check(error.find("重复加载") != std::string::npos,
              "duplicate load message: " + error);
    }

    // --- ABI 不兼容 ----------------------------------------------------------
    {
        pp::ProviderRegistry registry;
        pp::PluginLoader loader(registry);
        std::string error = expect_throw_of<std::function<void()>, pp::PluginAbiError>(
            [&] { loader.load(PWB_PLUGIN_BADABI); });
        check(error.find("999999") != std::string::npos,
              "abi mismatch mentions actual: " + error);
        check(loader.loaded().empty(), "badabi module not kept");
    }

    // --- 宿主能力缺失 --------------------------------------------------------
    {
        pp::ProviderRegistry registry;
        pp::PluginLoader loader(registry);
        std::string error = expect_throw_of<std::function<void()>, pp::PluginCapabilityError>(
            [&] { loader.load(PWB_PLUGIN_MISSING_CAP); });
        check(error.find("pwb.capability.absent/1") != std::string::npos,
              "capability error names the gap: " + error);
        check(loader.loaded().empty(), "missing-cap module not kept");
        check(registry.size() == 0, "registry untouched by capability reject");
    }

    // --- 描述符无效：整个模块拒收，注册表无痕迹 ------------------------------
    {
        pp::ProviderRegistry registry;
        pp::PluginLoader loader(registry);
        std::string error = expect_throw_of<std::function<void()>, pp::PluginDescriptorError>(
            [&] { loader.load(PWB_PLUGIN_BADDESC); });
        check(error.find("Bad Provider ID") != std::string::npos,
              "descriptor error names provider: " + error);
        check(registry.size() == 0, "nothing registered from rejected module");
        check(registry.quarantined().empty(),
              "loader-level rejection is not a quarantine case");
    }

    // --- 取消桥：宿主 cancel → TaskCancelled 原样传播 -------------------------
    {
        pp::ProviderRegistry registry;
        pp::PluginLoader loader(registry);
        loader.load(PWB_PLUGIN_OK);
        pp::CancelToken token;
        pp::ProviderContext context;
        context.cancel = &token;
        Json parameters = Json::object();
        parameters["hold_ms"] = 10000;
        std::atomic<bool> done{false};
        std::string thrown;
        std::thread worker([&] {
            try {
                pp::execute_provider(registry, "plugin.slow", {}, parameters,
                                     &context);
            } catch (const pp::TaskCancelled& exc) {
                thrown = exc.what();
            } catch (const std::exception& exc) {
                thrown = std::string("<wrong type: ") + exc.what() + ">";
            }
            done = true;
        });
        std::this_thread::sleep_for(std::chrono::milliseconds(150));
        token.cancel();
        worker.join();
        check(done && !thrown.empty() && thrown.find("<wrong") == std::string::npos,
              "cancel surfaces as TaskCancelled: " + thrown);
        check(thrown.find("取消") != std::string::npos,
              "cancel message from the plugin: " + thrown);
        loader.unload("test.ok");
    }

    // --- 卸载竞态：请求卸载时任务仍在模块内 → 延迟卸载 ------------------------
    {
        pp::ProviderRegistry registry;
        {
            pp::PluginLoader loader(registry);
            loader.load(PWB_PLUGIN_OK);

            // 真实并发：一个任务正在模块内执行慢 provider。
            Json parameters = Json::object();
            parameters["hold_ms"] = 300;
            std::atomic<bool> task_done{false};
            std::string task_error;
            pp::ProviderResult task_result;
            std::thread task([&] {
                try {
                    task_result = pp::execute_provider(registry, "plugin.slow",
                                                       {}, parameters, nullptr);
                } catch (const std::exception& exc) {
                    task_error = exc.what();
                }
                task_done = true;
            });
            std::this_thread::sleep_for(std::chrono::milliseconds(80));
            const bool unloaded_now = loader.unload("test.ok");
            check(!unloaded_now, "unload deferred while a task is inside");
            check(loader.is_unload_pending("test.ok"), "pending unload visible");

            // 新执行被确定性拒绝（typed）。
            pp::ProviderContext context;
            std::string reject = expect_throw_of<std::function<void()>, pp::PluginUnloadPendingError>(
                [&] {
                    pp::IProvider& provider = registry.get("plugin.slow");
                    provider.execute({}, Json::object(), context);
                });
            check(reject.find("正在卸载") != std::string::npos,
                  "pending-unload rejection message: " + reject);

            task.join();
            check(task_done && task_error.empty(),
                  "in-flight task completed despite unload: " + task_error);
            check(task_result.metrics.value("held_ms", 0LL) == 300,
                  "in-flight task result intact");

            // 最后一个租约释放后模块真正卸载。
            wait_until([&] { return !loader.is_unload_pending("test.ok"); },
                       5000);
            check(loader.find("test.ok") == nullptr,
                  "module gone after last lease");
            check(registry.find("plugin.slow") == nullptr,
                  "providers unregistered after deferred finalize");
        }
    }

    // --- 无竞争卸载：立即完成 ------------------------------------------------
    {
        pp::ProviderRegistry registry;
        pp::PluginLoader loader(registry);
        loader.load(PWB_PLUGIN_OK);
        check(loader.unload("test.ok"), "uncontended unload succeeds");
        check(loader.find("test.ok") == nullptr, "module gone");
        check(loader.is_unload_pending("test.ok") == false, "not pending");
        check(registry.find("plugin.echo") == nullptr, "providers unregistered");
        check(loader.unload("test.ok") == true, "second unload is idempotent (gone)");
        pp::ProviderContext context;
        check(expect_any_throw([&] {
                  registry.get("plugin.echo");
              }) != "<no throw>",
              "get after unload throws");
    }

    if (g_failures == 0) {
        std::printf("providers.plugins: %d checks passed\n", g_checks);
        return 0;
    }
    std::fprintf(stderr, "providers.plugins: %d/%d checks FAILED\n", g_failures,
                 g_checks);
    return 1;
}
