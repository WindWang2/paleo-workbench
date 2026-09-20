#!/usr/bin/env bash
# 05 线 — 门禁内验证脚本（资源门全程包装；仿 run-viz-a-gate.sh 纪律）。
# 用法：bash docs/development/cpp-closure-wave/05-well-crosswell/verify.sh
# 每步失败即退出（失败传播契约——绝不假绿）。

set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$ROOT"
GATE=scripts/cpp-migration/invoke-resource-gate.sh
BUILD=build/05-well
CFG=Release
CMAKE_ARGS="Ninja;-DCMAKE_MAKE_PROGRAM=$HOME/tools/ninja-bin/ninja;-DPWB_BUILD_PLATFORM=ON;-DPWB_BUILD_DATA=ON;-DPWB_BUILD_SCIENCE=ON;-DPWB_BUILD_VIZ_B=ON;-DPWB_BUILD_CONV_29=ON;-DPWB_BUILD_MAPPING_KERNEL=ON;-DPWB_SCIENCE_BUILD_VIEWER=ON"
# cmake/ninja 用户级安装（本机系统无；见协调登记的环境警告）。
export PATH="$HOME/tools/cmake-4.1.2-linux-x86_64/bin:$PATH"
# vendored QGIS 只读复用主工作区（本机无 <repo>/main sibling 布局；
# cache 优先于 env——build 树一旦写错路径必须清掉重来）。
_paleo_main=/home/kevin/project/paleo-workbench
export PALEO_QGIS_SOURCE_DIR="$_paleo_main/third_party/qgis"
export PALEO_QGIS_SDK_DIR="$_paleo_main/native/qgis_render_bridge/build/qgis-vendor/output"
export PALEO_QGIS_BUILD_DIR="$_paleo_main/native/qgis_render_bridge/build/qgis-vendor"

must() {
    local name="$1"; shift
    if ! "$@"; then
        echo "VERIFY_FAIL step=$name" >&2
        exit 1
    fi
    echo "VERIFY_OK step=$name"
}

# 等锁重试（exit 75 → 退避重试；其他码 = 真失败）。
gate() {
    local name="$1"; shift
    local log="/tmp/well05_gate_${name}.log"
    for i in $(seq 1 90); do
        "$GATE" "$@" > "$log" 2>&1
        code=$?
        tail -3 "$log"
        if [ $code -eq 0 ]; then
            echo "VERIFY_OK step=$name"
            return 0
        fi
        if [ $code -ne 75 ]; then
            echo "VERIFY_FAIL step=$name gate_exit=$code log=$log" >&2
            return 1
        fi
        echo "gate busy (attempt $i) — backoff 45s"
        sleep 45
    done
    echo "VERIFY_FAIL step=$name reason=queue_timeout" >&2
    return 1
}

# 1) configure（幂等）
gate configure Configure -s . -b "$BUILD" -c "$CFG" -j 4 -a "$CMAKE_ARGS" || exit 1

# 2) 构建本线闭包（worker 核 + WLE 桥 + 页面 + dock/app 源 + 测试目标）
#    + 受影响既有回归（viz_a/viz_b 二进制——pattern/导出复验用）。
gate build Build -s . -b "$BUILD" -c "$CFG" -j 4 \
    -t 'ui_workers.oracle;ui_workers.lifecycle;ui_workers.well_xml;well.load_path;well.vizb_las_path;well.dock_lifecycle;well.presenter_flow;viz_a.las_preview_core;viz_a.las_preview_wle;viz_a.wle_load;viz_a.consistency;viz_a.patterns;viz_a.viewer_flow;viz_a.install_cover;viz_b.cross_well.oracle;viz_b.cross_well.qt_smoke;viz_b.well_tie.oracle;viz_b.integration;viz_b.engines_example;viz_b.dock_smoke' || exit 1

# 3) 受影响测试 第一遍
gate test1 Test -s . -b "$BUILD" -c "$CFG" -j 2 -r '^(ui_workers\.|well\.|viz_a\.|viz_b\.)' || exit 1

# 4) 受影响测试 第二遍（确定性回归）
gate test2 Test -s . -b "$BUILD" -c "$CFG" -j 2 -r '^(ui_workers\.|well\.|viz_a\.|viz_b\.)' || exit 1

# 5) MALLOC 审计（本线测试）
gate malloc Exec -s . -b "$BUILD" -c "$CFG" -j 2 -- env MALLOC_CHECK_=3 ctest --test-dir "$BUILD" -C "$CFG" -R '^(well\.|ui_workers\.)' --output-on-failure || exit 1

# 6) app 生产接线编译覆盖（pwb-platform：main_window 05 钩子 + viz_a/b 安装块）
gate app Build -s . -b "$BUILD" -c "$CFG" -j 4 -t 'pwb-platform' || exit 1

echo "VERIFY_ALL_GREEN"
