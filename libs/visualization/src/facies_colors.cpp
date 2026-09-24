#include <pwb/viz/facies_colors.hpp>

// Definition moved here from well_log_document_plan.cpp so the frozen
// FACIES_COLORS vocabulary is available without the WLE host adapter
// (legend panels, non-viewer builds). Table content is verbatim.
namespace pwb::viz {

const std::vector<std::pair<std::string, std::string>>& facies_colors() {
    static const std::vector<std::pair<std::string, std::string>> table = {
        {"砂岩", "#f0d9b5"},     {"泥岩", "#d4c5a9"},     {"灰岩", "#b5d4c1"},
        {"白云岩", "#a8cdb8"},   {"页岩", "#c9bfa0"},     {"粉砂岩", "#e6c9a8"},
        {"砂坪", "#f0d9b5"},     {"泥坪", "#d4c5a9"},     {"云质坪", "#c4d4c0"},
        {"混积潮坪", "#c4d4c0"}, {"碎屑岩潮坪", "#d4c5a9"}, {"潮坪", "#d4c5a9"},
        {"混合坪", "#e2d2b5"},   {"潮汐水道", "#ebd2b0"}, {"潮汐砂脊", "#ebd2b0"},
        {"潮沟", "#ebd2b0"},     {"潮道", "#ebd2b0"},     {"泥裂", "#c0dcc0"},
        {"藻席", "#c0dcc0"},     {"泥质陆棚", "#d4c5a9"}, {"砂质陆棚", "#f0d9b5"},
        {"砂泥质陆棚", "#dccfb5"}, {"碎屑岩浅水陆棚", "#d4c5a9"},
        {"混积浅水陆棚", "#c4d4c0"}, {"陆棚", "#d9d4c8"},   {"混积", "#c4d4c0"},
        {"陆棚泥", "#d4c5a9"},   {"陆棚砂", "#f0d9b5"},   {"风暴沉积", "#dccfb5"},
        {"三角洲", "#e6c9a8"},   {"河流", "#f0d9b5"},     {"河道", "#ebd2b0"},
        {"沼泽", "#c0dcc0"},     {"三角洲前缘", "#ebd2b0"},
        {"三角洲平原", "#ebd2b0"}, {"前三角洲", "#dccfb5"},
        {"分流河道", "#ebd2b0"}, {"天然堤", "#e2d2b5"},   {"辫状河道", "#ebd2b0"},
        {"深水盆地", "#9bb5cf"}, {"深海", "#9bb5cf"},     {"半深海", "#a8c0d8"},
        {"深海平原", "#9bb5cf"}, {"海底扇", "#abc4d4"},   {"深海泥", "#9bb5cf"},
        {"浊积岩", "#adc6d9"},   {"等深积岩", "#9bb5cf"}, {"碎屑流", "#abc4d4"},
        {"湖", "#92d4f0"},       {"深湖", "#53b3df"},     {"半深湖", "#73c3ef"},
        {"浅湖", "#aae2f7"},     {"湖底泥", "#73c3ef"},
        {"碳酸盐台地", "#b5d4c1"}, {"局限台地", "#b8d4cc"},
        {"开阔台地", "#b5d4c1"}, {"台地边缘", "#94d6b5"}, {"生物礁", "#b5d4c1"},
        {"礁", "#b5d4c1"},       {"粒屑滩", "#bde3cf"},   {"滨岸", "#f0d9b5"},
        {"前滨", "#f0d9b5"},     {"临滨", "#f0d9b5"},     {"后滨", "#f0d9b5"},
        {"沿岸坝", "#f0d9b5"},   {"海滩砂", "#f0d9b5"},   {"冲越扇", "#f0d9b5"},
        {"蒸发岩", "#e8dcc8"},   {"蒸发盐", "#e8dcc8"},   {"膏盐", "#e8dcc8"},
        {"冰川", "#c8d8e4"},     {"冰碛", "#c8d8e4"},     {"火山岩", "#c4a8a0"},
        {"熔岩", "#c4a8a0"},     {"变质岩", "#bfb8b0"},   {"冲积扇", "#e6c9a8"},
        {"洪积扇", "#e6c9a8"},   {"扇中", "#e6c9a8"},     {"扇根", "#e6c9a8"},
        {"扇缘", "#e6c9a8"},     {"泥石流", "#e6c9a8"},   {"片流沉积", "#e6c9a8"},
        {"潟湖", "#b8d4cc"},     {"半咸水潟湖", "#b8d4cc"},
        {"超咸水潟湖", "#a0c7c0"},
    };
    return table;
}

}  // namespace pwb::viz
