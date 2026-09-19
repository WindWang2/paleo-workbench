#include "pwb/ui_workstation/stage_actions.hpp"

#include <array>
#include <cstdint>
#include <cstring>

namespace pwb::ui_workstation {

const std::map<std::string, std::string>& stage_action_dispatch_table() {
    // Python dispatch() handler dict, verbatim (alias entries resolve
    // to the same dispatch key).
    static const std::map<std::string, std::string> table = {
        {"load_initial_facies", "load_initial_facies"},
        {"add_well_prediction_overlay", "add_well_prediction_overlay"},
        {"add_seismic_prediction_overlay",
         "add_seismic_prediction_overlay"},
        {"well_prediction_point_to_surface",
         "well_prediction_point_to_surface"},
        {"run_well_facies_mock", "run_well_facies_mock"},
        {"run_seismic_facies_mock", "run_seismic_facies_mock"},
        {"toggle_prediction_confidence", "toggle_prediction_confidence"},
        {"create_facies_draft", "create_facies_draft"},
        {"open_factor_workbench", "open_factor_workbench"},
        {"run_factor", "open_factor_workbench"},
        {"overlay_factor_results", "overlay_factor_results"},
        {"commit_constraints", "commit_constraints"},
        {"select_evidence", "select_evidence"},
        {"freeze_input_set", "freeze_evidence_set"},
        {"create_integrated_draft", "create_integrated_draft"},
        {"create_integrated_boundary", "create_integrated_boundary"},
        {"run_fusion", "run_fusion"},
        {"run_qa", "run_qa"},
        {"commit_interpretation", "commit_interpretation"},
        {"assemble_map_product", "assemble_map_product"},
        {"stage_save", "stage_save"},
        {"stage_qc", "run_qa"},
    };
    return table;
}

std::string stage_action_dispatch_key(const std::string& action_id) {
    const auto it = stage_action_dispatch_table().find(action_id);
    return it != stage_action_dispatch_table().end() ? it->second : "";
}

bool is_known_stage_action(const std::string& action_id) {
    return stage_action_dispatch_table().count(action_id) != 0;
}

const char* kStageActionHorizonMessage =
    "请先设定编图层位（相图按层位进行）";

bool stage_action_requires_horizon(const std::string& action_id) {
    // Python _REQUIRES_HORIZON frozenset, verbatim.
    static const std::set<std::string> horizon_gated = {
        "load_initial_facies",
        "add_well_prediction_overlay",
        "add_seismic_prediction_overlay",
        "well_prediction_point_to_surface",
        "run_well_facies_mock",
        "run_seismic_facies_mock",
        "toggle_prediction_confidence",
        "create_facies_draft",
        "open_factor_workbench",
        "run_factor",
        "overlay_factor_results",
        "select_evidence",
        "create_integrated_draft",
        "create_integrated_boundary",
        "run_fusion",
        "run_qa",
        "assemble_map_product",
        "stage_qc",
    };
    return horizon_gated.count(action_id) != 0;
}

const std::set<std::string>& blank_facies_values() {
    static const std::set<std::string> values = {"", "空白相"};
    return values;
}

const std::vector<std::string>& facies_fallback_palette() {
    static const std::vector<std::string> palette = {
        "#c47f4e", "#e8c46b", "#8fc7c2", "#d9a066",
        "#eae2b0", "#6fb3b8", "#3d6b8e", "#9b6b9e",
    };
    return palette;
}

namespace {

// Minimal MD5 (RFC 1321) — the fallback palette index is
// int(md5(name).hexdigest(), 16) % 8, so exact parity needs the real
// algorithm, not any stable hash.
struct Md5 {
    std::uint32_t a = 0x67452301, b = 0xefcdab89, c = 0x98badcfe,
                d = 0x10325476;
    std::uint64_t bytes = 0;
    std::array<std::uint8_t, 64> buf{};
    std::size_t buflen = 0;

    static std::uint32_t rotl(std::uint32_t x, int n) {
        return (x << n) | (x >> (32 - n));
    }

    void block(const std::uint8_t* p) {
        static const std::uint32_t K[64] = {
            0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee,
            0xf57c0faf, 0x4787c62a, 0xa8304613, 0xfd469501,
            0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be,
            0x6b901122, 0xfd987193, 0xa679438e, 0x49b40821,
            0xf61e2562, 0xc040b340, 0x265e5a51, 0xe9b6c7aa,
            0xd62f105d, 0x02441453, 0xd8a1e681, 0xe7d3fbc8,
            0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed,
            0xa9e3e905, 0xfcefa3f8, 0x676f02d9, 0x8d2a4c8a,
            0xfffa3942, 0x8771f681, 0x6d9d6122, 0xfde5380c,
            0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70,
            0x289b7ec6, 0xeaa127fa, 0xd4ef3085, 0x04881d05,
            0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665,
            0xf4292244, 0x432aff97, 0xab9423a7, 0xfc93a039,
            0x655b59c3, 0x8f0ccc92, 0xffeff47d, 0x85845dd1,
            0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1,
            0xf7537e82, 0xbd3af235, 0x2ad7d2bb, 0xeb86d391,
        };
        static const int S[64] = {
            7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22,
            5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
            4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23,
            6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21,
        };
        std::uint32_t m[16];
        for (int i = 0; i < 16; ++i) {
            m[i] = static_cast<std::uint32_t>(p[i * 4]) |
                   (static_cast<std::uint32_t>(p[i * 4 + 1]) << 8) |
                   (static_cast<std::uint32_t>(p[i * 4 + 2]) << 16) |
                   (static_cast<std::uint32_t>(p[i * 4 + 3]) << 24);
        }
        std::uint32_t aa = a, bb = b, cc = c, dd = d;
        for (int i = 0; i < 64; ++i) {
            std::uint32_t f;
            int g;
            if (i < 16) {
                f = (bb & cc) | (~bb & dd);
                g = i;
            } else if (i < 32) {
                f = (dd & bb) | (~dd & cc);
                g = (5 * i + 1) % 16;
            } else if (i < 48) {
                f = bb ^ cc ^ dd;
                g = (3 * i + 5) % 16;
            } else {
                f = cc ^ (bb | ~dd);
                g = (7 * i) % 16;
            }
            const std::uint32_t tmp = dd;
            dd = cc;
            cc = bb;
            bb = bb + rotl(aa + f + K[i] + m[g], S[i]);
            aa = tmp;
        }
        a += aa;
        b += bb;
        c += cc;
        d += dd;
    }

    void update(const std::uint8_t* p, std::size_t n) {
        bytes += n;
        while (n > 0) {
            const std::size_t take = std::min(n, 64 - buflen);
            std::memcpy(buf.data() + buflen, p, take);
            buflen += take;
            p += take;
            n -= take;
            if (buflen == 64) {
                block(buf.data());
                buflen = 0;
            }
        }
    }

    // We only need the low 32 bits of the digest (mod 8 needs the low
    // 3 bits — md5's last dword, little-endian, is 'd').
    std::uint64_t digest_mod(std::uint64_t mod) {
        const std::uint64_t bitlen = bytes * 8;
        std::uint8_t pad = 0x80;
        update(&pad, 1);
        std::uint8_t zero = 0;
        while (buflen != 56) update(&zero, 1);
        std::uint8_t len[8];
        for (int i = 0; i < 8; ++i) {
            len[i] = static_cast<std::uint8_t>((bitlen >> (i * 8)) & 0xff);
        }
        update(len, 8);
        // Python int(hexdigest,16) is the full 128-bit big-endian
        // number; mod 8 depends only on the last hex digit = the low
        // nibble of the digest's last byte (d's high byte, LE output).
        return ((d >> 24) & 0x7) % mod;  // last hex digit mod 8
    }
};

}  // namespace

std::string facies_category_color(
    const std::string& value, const std::string& feature_color,
    const std::map<std::string, std::string>& known_fills) {
    std::string fill = feature_color;
    // str.strip() parity (ASCII whitespace; facies names are UTF-8).
    const auto start = fill.find_first_not_of(" \t\n\r");
    fill = start == std::string::npos ? "" : fill.substr(start);
    if (fill.empty()) {
        const auto it = known_fills.find(value);
        if (it != known_fills.end()) fill = it->second;
    }
    if (!fill.empty()) return fill;
    Md5 md5;
    md5.update(reinterpret_cast<const std::uint8_t*>(value.data()),
               value.size());
    return facies_fallback_palette()[md5.digest_mod(
        facies_fallback_palette().size())];
}

std::string dispatch_stage_action(
    const std::string& action_id, bool mapping_horizon_set,
    const std::map<std::string, StageActionHandler>& handlers) {
    if (stage_action_requires_horizon(action_id) && !mapping_horizon_set) {
        return kStageActionHorizonMessage;
    }
    const std::string key = stage_action_dispatch_key(action_id);
    if (key.empty()) {
        return "未知阶段动作：" + action_id;
    }
    const auto it = handlers.find(key);
    if (it == handlers.end() || !it->second) {
        // No bound handler — the shell reports honestly instead of
        // pretending the action ran.
        return "阶段动作未接入：" + action_id;
    }
    try {
        it->second();
    } catch (const std::exception& exc) {
        return "阶段动作失败（" + action_id + "）：" + exc.what();
    } catch (...) {
        return "阶段动作失败（" + action_id + "）：未知错误";
    }
    return "";
}

}  // namespace pwb::ui_workstation
