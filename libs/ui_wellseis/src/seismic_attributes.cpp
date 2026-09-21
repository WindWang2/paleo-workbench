#include <pwb/ui_wellseis/seismic_attributes.hpp>

#include <algorithm>

namespace pwb::ui_wellseis {

const std::vector<SeismicAttributeGroup>& seismic_attribute_groups() {
    static const std::vector<SeismicAttributeGroup> groups = {
        {"振幅属性", {"振幅", "包络", "RMS振幅"}},
        {"频率属性", {"瞬时频率"}},
        {"连续性属性", {"甜点", "相对阻抗"}},
        {"结构属性",
         {"瞬时相位", "Dip_IL", "Dip_XL", "方位角", "平均曲率",
          "高斯曲率", "最大曲率"}},
        {"多属性融合", {"RGB融合"}},
    };
    return groups;
}

const std::vector<std::string>& all_seismic_attributes() {
    static const std::vector<std::string> all = [] {
        std::vector<std::string> flat;
        for (const SeismicAttributeGroup& group : seismic_attribute_groups()) {
            flat.insert(flat.end(), group.attributes.begin(),
                        group.attributes.end());
        }
        return flat;
    }();
    return all;
}

bool is_known_seismic_attribute(const std::string& attribute) {
    const std::vector<std::string>& all = all_seismic_attributes();
    return std::find(all.begin(), all.end(), attribute) != all.end();
}

const std::vector<std::string>& seismic_display_modes() {
    static const std::vector<std::string> modes = {
        kDisplayModeVd, kDisplayModeWiggle};
    return modes;
}

const std::vector<SeismicAttributeGroup>& seismic_attribute_panel_groups() {
    // 07 line (cpp-closure-wave): "RGB融合" moves out of 未实现 into a
    // computable 多属性融合 group — the C++ display stack now actually
    // computes it (attribute_fusion_core fuse_rgb + closure_seismic wiring).
    // Deliberate divergence from the Python panel
    // (seismic_attribute_panel.py:32 marks it 未实现); recorded in the
    // 07 findings ledger and PR. 高斯曲率/最大曲率 stay 未实现.
    static const std::vector<SeismicAttributeGroup> groups = {
        {"振幅属性", {"振幅", "包络", "RMS振幅", "相对阻抗"}},
        {"频率属性", {"瞬时频率", "瞬时相位", "甜点"}},
        {"连续性属性", {"相干(C3)"}},
        {"构造属性", {"Dip_IL", "Dip_XL", "方位角", "平均曲率"}},
        {"多属性融合", {"RGB融合"}},
        {"未实现", {"高斯曲率", "最大曲率"}},
    };
    return groups;
}

const std::vector<std::pair<std::string, std::string>>&
computable_kernel_labels() {
    // "amplitude" is a pseudo-kernel: the 振幅 leaf maps to the viewer's
    // clear_attribute_view() path (restore the raw amplitude display). It is
    // not a science-registry algorithm id — closure_seismic special-cases it
    // before run_section_kernel, so "clear attribute view" is reachable from
    // the panel instead of being a dead end behind the export refusal.
    static const std::vector<std::pair<std::string, std::string>> labels = {
        {"amplitude", "振幅"},
        {"c3", "相干(C3)"},
        {"envelope", "包络"},
        {"rms_amplitude", "RMS振幅"},
        {"instantaneous_frequency", "瞬时频率"},
        {"instantaneous_phase", "瞬时相位"},
        {"sweetness", "甜点"},
        {"relative_impedance", "相对阻抗"},
        {"dip_il", "Dip_IL"},
        {"dip_xl", "Dip_XL"},
        {"dip_azimuth", "方位角"},
        {"curvature_mean", "平均曲率"},
        {"rgb_fusion", "RGB融合"},
    };
    return labels;
}

std::string kernel_for_label(const std::string& label) {
    for (const auto& [kernel, text] : computable_kernel_labels()) {
        if (text == label) {
            return kernel;
        }
    }
    return "";
}

}  // namespace pwb::ui_wellseis
