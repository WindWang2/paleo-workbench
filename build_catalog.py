"""Build master catalog + description files for all 312 SVG icons."""
import os, json
from pathlib import Path

OUTDIR = str(Path(__file__).resolve().parent / "svg_output")
DESCDIR = os.path.join(OUTDIR, "descriptions")
os.makedirs(DESCDIR, exist_ok=True)

# ──────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────
catalog = []

CAT_MAP = {
    "岩石纹理": "textures", "断层": "faults", "构造边界": "boundaries",
    "井型田设施": "wells", "储层含油性": "reservoirs", "地层沉积相": "strata",
    "地理注记": "geo", "地震符号": "seismic", "褶皱构造": "folds",
    "矿区储量": "mining", "基本岩类": "basic_rocks",
}

LARGE_CATALOG_PREFIXES = ("fig_0001_", "fig_0002_", "fig_0003_", "fig_0004_",
                          "fig_0005_", "fig_0006_", "fig_0007_", "fig_0008_",
                          "fig_0009_", "fig_0010_", "fig_0011_")

def add(cat, fname, zh, en, spec, code, color, usage):
    # Skip large catalog pages (not individual icons)
    if any(fname.startswith(p) for p in LARGE_CATALOG_PREFIXES):
        return
    svg_path = os.path.join(OUTDIR, CAT_MAP[cat], f"{fname}.svg")
    if not os.path.exists(svg_path):
        # Try alternate filenames
        alt = None
        if cat == "矿区储量" and fname == "mine_production":
            alt = os.path.join(OUTDIR, "mining", "mine_production_block.svg")
        if alt and os.path.exists(alt):
            svg_path = alt
            fname = "mine_production_block"
        else:
            print(f"  SKIP (no SVG): {CAT_MAP[cat]}/{fname}.svg")
            return
    entry = {
        "category": cat, "file": f"{fname}.svg",
        "chinese_name": zh, "english_name": en,
        "specification": spec, "symbol_code": code,
        "color": color, "usage": usage,
    }
    catalog.append(entry)
    return entry

def write_desc(entry):
    """Write a per-icon markdown description file."""
    safe = entry["file"].replace(".svg", "")
    md = os.path.join(DESCDIR, f"desc_{safe}.md")
    with open(md, 'w', encoding='utf-8') as f:
        f.write(f"# {entry['english_name']} / {entry['chinese_name']}\n\n")
        f.write(f"| Field | Value |\n|---|---|\n")
        f.write(f"| File | `{entry['file']}` |\n")
        f.write(f"| Category | {entry['category']} |\n")
        f.write(f"| Chinese Name | {entry['chinese_name']} |\n")
        f.write(f"| English Name | {entry['english_name']} |\n")
        f.write(f"| Specification | {entry['specification']} |\n")
        f.write(f"| Symbol Code | `{entry['symbol_code']}` |\n")
        f.write(f"| Primary Color | `{entry['color']}` |\n\n")
        f.write(f"## Usage\n\n{entry['usage']}\n\n")
        f.write(f"## Source\n\nReconstructed from Q/HS 1011—2016 *勘探管理图件图册编制规范* "
                f"(Chinese Oil & Gas Exploration Map Compilation Standard).\n")

# ──────────────────────────────────────────────
# TEXTURES (26)
# ──────────────────────────────────────────────
T = "岩石纹理"
add(T, "tex_sandstone_fine",      "细砂岩",       "Fine Sandstone",      "附录F.1 表F.1", "TEX-F1-1H/C",  "#E8D5B5", "细砂颗粒点状填充(2×2 tile)，沉积岩-砂岩类。")
add(T, "tex_sandstone_medium",    "中砂岩",       "Medium Sandstone",    "附录F.1 表F.1", "TEX-F1-2H/C",  "#E8D5B5", "中等砂颗粒点状填充(3×3 tile)，沉积岩-砂岩类。")
add(T, "tex_sandstone_coarse",    "粗砂岩",       "Coarse Sandstone",    "附录F.1 表F.1", "TEX-F1-3H/C",  "#E8D5B5", "大砂颗粒点状填充(5×5 tile)，沉积岩-砂岩类。")
add(T, "tex_sandstone_pebbly",    "砾质砂岩",     "Pebbly Sandstone",    "附录F.1 表F.1", "TEX-F1-4H/C",  "#E8D5B5", "大圆(8×8)加小圆点混合pattern，砾质砂岩。")
add(T, "tex_conglomerate_cobble", "巨砾砾岩",     "Cobble Conglomerate", "附录F.1 表F.1", "TEX-F1-5H/C",  "#D0C0A0", "极大砾石填充(15×15 tile)，巨砾砾岩。")
add(T, "tex_conglomerate_pebble", "砾石砾岩",     "Pebble Conglomerate", "附录F.1 表F.1", "TEX-F1-6H/C",  "#D0C0A0", "大砾石填充(10×10 tile)，砾石砾岩。")
add(T, "tex_siltstone",           "粉砂岩",       "Siltstone",           "附录F.1 表F.1", "TEX-F1-7H/C",  "#DCD4C4", "微粒填充(2×2浅色 tile)，粉砂岩。")
add(T, "tex_mudstone",            "泥岩",         "Mudstone",            "附录F.1 表F.1", "TEX-F1-8H/C",  "#C8C0B0", "均匀填充pattern，泥岩。")
add(T, "tex_mudstone_silty",      "含粉砂泥岩",   "Silty Mudstone",      "附录F.1 表F.1", "TEX-F1-9H/C",  "#C8C0B0", "均匀填充加微粒点缀，含粉砂泥岩。")
add(T, "tex_shale_thin",          "薄层页岩",     "Thin-bedded Shale",   "附录F.1 表F.1", "TEX-F1-10H/C", "#B0C4D8", "细水平线(2px) pattern，薄层页岩。")
add(T, "tex_shale_thick",         "厚层页岩",     "Thick-bedded Shale",  "附录F.1 表F.1", "TEX-F1-11H/C", "#B0C4D8", "粗水平线(4px) pattern，厚层页岩。")
add(T, "tex_shale_carbonaceous",  "碳质页岩",     "Carbonaceous Shale",  "附录F.1 表F.1", "TEX-F1-12H/C", "#6A5A4A", "密集黑点填充pattern，碳质页岩。")
add(T, "tex_limestone_micritic",  "泥晶灰岩",     "Micritic Limestone",  "附录F.1 表F.1", "TEX-F1-13H/C", "#F0E8D8", "密集细点 pattern，泥晶灰岩。")
add(T, "tex_limestone_bio",       "生物灰岩",     "Bio-limestone",       "附录F.1 表F.1", "TEX-F1-14H/C", "#F0E8D8", "圆点加短线(化石) pattern，生物灰岩。")
add(T, "tex_limestone_oolitic",   "鲕粒灰岩",     "Oolitic Limestone",   "附录F.1 表F.1", "TEX-F1-15H/C", "#F0E8D8", "同心圆(鲕粒) pattern，鲕粒灰岩。")
add(T, "tex_limestone_cherty",    "燧石灰岩",     "Cherty Limestone",    "附录F.1 表F.1", "TEX-F1-16H/C", "#E8E0D0", "黑色小圆(燧石结核) pattern，燧石灰岩。")
add(T, "tex_reef_limestone",      "礁灰岩",       "Reef Limestone",      "附录F.1 表F.1", "TEX-F1-17H/C", "#F8F0E0", "不规则块状(珊瑚礁) pattern，礁灰岩。")
add(T, "tex_dolomite",            "白云岩",       "Dolomite",            "附录F.1 表F.1", "TEX-F1-18H/C", "#E0D8C8", "晶粒状正方形 pattern，白云岩。")
add(T, "tex_dolomite_granular",   "晶粒白云岩",   "Granular Dolomite",   "附录F.1 表F.1", "TEX-F1-19H/C", "#E0D8C8", "密集小正方形 pattern，晶粒白云岩。")
add(T, "tex_marl",                "泥灰岩",       "Marl",                "附录F.1 表F.1", "TEX-F1-20H/C", "#D8D0C0", "石灰+泥质混合 pattern，泥灰岩。")
add(T, "tex_gypsum",              "石膏",         "Gypsum",              "附录F.2 表F.2", "TEX-F2-1H/C",  "#F0EEE8", "透明晶质纹理 pattern，石膏。")
add(T, "tex_salt",                "岩盐",         "Rock Salt",           "附录F.2 表F.2", "TEX-F2-2H/C",  "#F5F5F0", "透明水纹纹理 pattern，岩盐。")
add(T, "tex_tuff",                "凝灰岩",       "Tuff",                "附录F.2 表F.2", "TEX-F2-3H/C",  "#C8C0B0", "火山碎屑点 pattern，凝灰岩。")
add(T, "tex_volcanic_breccia",    "火山角砾岩",   "Volcanic Breccia",    "附录F.2 表F.2", "TEX-F2-4H/C",  "#B8B0A0", "大碎屑斑块 pattern，火山角砾岩。")
add(T, "tex_coal",                "煤层",         "Coal",                "附录F.2 表F.2", "TEX-F2-5H/C",  "#2a2a2a", "黑色均匀填充，煤层。")
add(T, "tex_oil_sand",            "油砂",         "Oil Sand",            "附录F.3 表F.3", "TEX-F3-1H/C",  "#8B7355", "砂质加油斑纹理 pattern，油砂。")

# ── FAULTS (34) ────────────────────────────────
F1 = "断层"
add(F1, "fault_normal_g1",        "正断层一級",     "Normal Fault Grade 1",    "附录K.1 表K.1", "DC-K1-1H/C",  "#000", "黑色粗线+大三角，正断层一級。")
add(F1, "fault_normal_g2",        "正断层二級",     "Normal Fault Grade 2",    "附录K.1 表K.1", "DC-K1-2H/C",  "#000", "黑色线+中等三角，正断层二級。")
add(F1, "fault_normal_g3",        "正断层三級",     "Normal Fault Grade 3",    "附录K.1 表K.1", "DC-K1-3H/C",  "#000", "黑色细线+密集小三角，三級。")
add(F1, "fault_normal_g4",        "正断层四級",     "Normal Fault Grade 4",    "附录K.1 表K.1", "DC-K1-4H/C",  "#000", "黑色细线+最小三角，四級。")
add(F1, "fault_normal_inferred",  "推测正断层",     "Inferred Normal Fault",   "附录K.1 表K.1", "DC-K1-5H/C",  "#666", "灰色虚线+三角，推测正断层。")
add(F1, "fault_normal_ungraded",  "正断层(未分级)", "Normal Fault Ungraded",   "附录K.1 表K.1", "DC-K1-NG/C",  "#000", "黑色线+中等三角，未分级正断层。")
add(F1, "fault_reverse_g1",       "逆断层一級",     "Reverse Fault Grade 1",   "附录K.1 表K.1", "DC-K1-6H/C",  "#000", "黑色粗线+大三角(上盘)，逆断层一級。")
add(F1, "fault_reverse_g2",       "逆断层二級",     "Reverse Fault Grade 2",   "附录K.1 表K.1", "DC-K1-7H/C",  "#000", "黑色线+中等三角，逆断层二級。")
add(F1, "fault_reverse_g3",       "逆断层三級",     "Reverse Fault Grade 3",   "附录K.1 表K.1", "DC-K1-8H/C",  "#000", "黑色细线+小三角，三級。")
add(F1, "fault_reverse_g4",       "逆断层四級",     "Reverse Fault Grade 4",   "附录K.1 表K.1", "DC-K1-9H/C",  "#000", "黑色细线+最小三角，四級。")
add(F1, "fault_reverse_inferred", "推测逆断层",     "Inferred Reverse Fault",  "附录K.1 表K.1", "DC-K1-10H/C", "#666", "灰色虚线+三角，推测逆断层。")
add(F1, "fault_reverse_ungraded", "逆断层(未分级)", "Reverse Fault Ungraded",  "附录K.1 表K.1", "DC-K1-RG/C",  "#000", "黑色线+中等三角，未分级逆断层。")
add(F1, "fault_thrust_g1",        "逆冲断层一級",   "Thrust Fault Grade 1",    "附录K.1 表K.1", "DC-K1-11H/C", "#000", "黑色粗线+大三角，逆冲断层一級。")
add(F1, "fault_thrust_g2",        "逆冲断层二級",   "Thrust Fault Grade 2",    "附录K.1 表K.1", "DC-K1-12H/C", "#000", "黑色线+中等三角，二級。")
add(F1, "fault_thrust_g3",        "逆冲断层三級",   "Thrust Fault Grade 3",    "附录K.1 表K.1", "DC-K1-13H/C", "#000", "黑色细线+小三角，三級。")
add(F1, "fault_thrust_g4",        "逆冲断层四級",   "Thrust Fault Grade 4",    "附录K.1 表K.1", "DC-K1-14H/C", "#000", "黑色细线+最小三角，四級。")
add(F1, "fault_thrust_inferred",  "推测逆冲断层",   "Inferred Thrust Fault",   "附录K.1 表K.1", "DC-K1-15H/C", "#666", "灰色虚线+三角，推测逆冲断层。")
add(F1, "fault_thrust_ungraded",  "逆冲断层(未分级)","Thrust Fault Ungraded",   "附录K.1 表K.1", "DC-K1-TG/C",  "#000", "黑色线+中等三角，未分级逆冲断层。")
add(F1, "fault_strike_g1",        "平移断层一級",   "Strike-Slip Grade 1",     "附录K.1 表K.1", "DC-K1-16H/C", "#000", "黑色粗线+横线标记，平移一級。")
add(F1, "fault_strike_g2",        "平移断层二級",   "Strike-Slip Grade 2",     "附录K.1 表K.1", "DC-K1-17H/C", "#000", "黑色线+中等横线标记。")
add(F1, "fault_strike_g3",        "平移断层三級",   "Strike-Slip Grade 3",     "附录K.1 表K.1", "DC-K1-18H/C", "#000", "黑色细线+小横线标记。")
add(F1, "fault_strike_g4",        "平移断层四級",   "Strike-Slip Grade 4",     "附录K.1 表K.1", "DC-K1-19H/C", "#000", "黑色细线+最小横线标记。")
add(F1, "fault_strike_inferred",  "推测平移断层",   "Inferred Strike-Slip",    "附录K.1 表K.1", "DC-K1-20H/C", "#666", "灰色虚线+横线，推测平移断层。")
add(F1, "fault_strike_ungraded",  "平移断层(未分级)","Strike-Slip Ungraded",    "附录K.1 表K.1", "DC-K1-SG/C",  "#000", "黑色线+横线标记，未分级平移。")
add(F1, "fault_regional_sag",     "区域性凹陷断裂", "Regional Sag Fault",      "附录K.2 表K.2", "DC-K2-1H/C",  "#D71414", "红色长虚线(15,5)，区域性大断裂。")
add(F1, "fault_detach_g1",        "滑脱断层一級",   "Detachment Fault Grade 1","附录K.2 表K.2", "DC-K2-2H/C",  "#D71414", "红色粗线+大三角，滑脱断层一級。")
add(F1, "fault_detach_g2",        "滑脱断层二級",   "Detachment Fault Grade 2","附录K.2 表K.2", "DC-K2-3H/C",  "#D71414", "红色线+中等三角。")
add(F1, "fault_detach_g3",        "滑脱断层三級",   "Detachment Fault Grade 3","附录K.2 表K.2", "DC-K2-4H/C",  "#D71414", "红色细线+小三角。")
add(F1, "fault_detach_g4",        "滑脱断层四級",   "Detachment Fault Grade 4","附录K.2 表K.2", "DC-K2-5H/C",  "#D71414", "红色细线+最小三角。")
add(F1, "fault_detach_inferred",  "推测滑脱断层",   "Inferred Detachment",     "附录K.2 表K.2", "DC-K2-6H/C",  "#D71414", "红色虚线+三角，推测滑脱。")
add(F1, "fault_complex_zone",     "断裂复杂带",     "Fault Complex Zone",      "附录K.2",       "DC-KZ-1H/C",  "#D71414", "密集断线区域，断裂复杂带。")
add(F1, "fault_fault_contact",    "断层接触",       "Fault Contact",           "附录K.2",       "DC-KZ-2H/C",  "#000",   "断线+接触标记，断层接触。")
add(F1, "fault_uncertain",        "断层(不确定)",   "Uncertain Fault",         "附录K.2",       "DC-KZ-3H/C",  "#CCC",   "浅灰线，不确定断层。")
add(F1, "fault_section_fault",    "断层剖面",       "Fault Section Profile",   "附录K.3",       "DC-PROF-H/C", "#000",   "剖面图中断层线及位移标记。")

# ── BOUNDARIES (33) ────────────────────────────
B1 = "构造边界"
add(B1, "bnd_basin_boundary",         "盆地边界",        "Basin Boundary",           "附录L.1 表L.1", "XZBH-L1-1H/C", "#008000", "绿色粗实线，盆地边界。")
add(B1, "bnd_basin_boundary_inferred","推测盆地边界",   "Inferred Basin Boundary",  "附录L.1 表L.1", "XZBH-L1-2H/C", "#008000", "绿色虚线，推测盆地边界。")
add(B1, "bnd_overlap_line",           "超覆线",          "Overlap Line",             "附录L.1 表L.1", "CHF-L1-1H/C",  "#D71414", "红色箭头线，超覆界线。")
add(B1, "bnd_overlap_inferred",       "推测超覆线",      "Inferred Overlap",         "附录L.1 表L.1", "CHF-L1-2H/C",  "#D71414", "红色虚线+箭头，推测超覆。")
add(B1, "bnd_pinchout_line",          "尖灭线",          "Pinchout Line",            "附录L.1 表L.1", "JML-L1-1H/C",  "#D71414", "红色三角线，地层尖灭。")
add(B1, "bnd_pinchout_inferred",      "推测尖灭线",      "Inferred Pinchout",        "附录L.1 表L.1", "JML-L1-2H/C",  "#D71414", "红色虚线+三角，推测尖灭。")
add(B1, "bnd_erosion_line",           "剥蚀线",          "Erosion Line",             "附录L.1 表L.1", "BQX-L1-1H/C",  "#D71414", "红色波浪线+V标记，剥蚀线。")
add(B1, "bnd_erosion_inferred",       "推测剥蚀线",      "Inferred Erosion",         "附录L.1 表L.1", "BQX-L1-2H/C",  "#D71414", "红色虚线+波浪，推测剥蚀。")
add(B1, "bnd_unconformity",           "不整合面",        "Unconformity",             "附录L.1 表L.1", "BQH-L1-1H/C",  "#D71414", "红色断波线，角度不整合。")
add(B1, "bnd_unconformity_inf",       "推测不整合",      "Inferred Unconformity",    "附录L.1 表L.1", "BQH-L1-2H/C",  "#D71414", "红色虚线，推测不整合。")
add(B1, "bnd_strat_boundary",         "地层界线",        "Stratigraphic Boundary",   "附录L.1 表L.1", "DCBJ-L1-1H/C", "#000",   "黑色实线，地层分界。")
add(B1, "bnd_fault_line",             "断层线",          "Fault Line",               "附录L.1 表L.1", "DCX-L1-1H/C",  "#000",   "黑色粗线+断距，断层线。")
add(B1, "bnd_fault_nose",             "断鼻",            "Fault Nose",               "附录L.1 表L.1", "DB-L1-1H/C",   "#000",   "弧线+断线，断鼻构造。")
add(B1, "bnd_anticline",              "背斜",            "Anticline Boundary",       "附录L.1 表L.1", "BX-L1-1H/C",   "#000",   "向上弧线+轴，背斜边界。")
add(B1, "bnd_half_anticline",         "半背斜",          "Half Anticline",           "附录L.1 表L.1", "BBX-L1-1H/C",  "#000",   "半弧线，半背斜。")
add(B1, "bnd_uplift",                 "凸起",            "Uplift",                   "附录L.1 表L.1", "TQ-L1-1H/C",   "#008000", "绿色椭圆，凸起构造。")
add(B1, "bnd_low_uplift",             "低凸起",          "Low Uplift",               "附录L.1 表L.1", "DTQ-L1-1H/C",  "#008000", "绿色小椭圆，低凸起。")
add(B1, "bnd_low_uplift_2",           "低凸起(变体)",    "Low Uplift Variant",       "附录L.1 表L.1", "DTQ-L1-2H/C",  "#008000", "绿色扁椭圆，低凸起变体。")
add(B1, "bnd_slope",                  "斜坡",            "Slope Zone",               "附录L.1 表L.1", "XP-L1-1H/C",   "#008000", "绿色斜线填充，斜坡带。")
add(B1, "bnd_suture_line",            "缝合线",          "Suture Line",              "附录L.1 表L.1", "FHX-L1-1H/C",  "#000",   "黑色粗线带齿，缝合线。")
add(B1, "bnd_section_line",           "剖面线",          "Section Line",             "附录L.1 表L.1", "PMX-L1-1H/C",  "#000",   "粗虚线+A-B标注，剖面线。")
add(B1, "bnd_contour_def",            "等深线",          "Depth Contour",            "附录L.1 表L.1", "DSX-L1-1H/C",  "#0071FF", "蓝色波浪线，等深线。")
add(B1, "bnd_contour_inf",            "推测等深线",      "Inferred Depth Contour",   "附录L.1 表L.1", "DSX-L1-2H/C",  "#0071FF", "蓝色虚线波浪，推测等深。")
add(B1, "bnd_shallow_dep",            "浅凹陷",          "Shallow Depression",       "附录L.1 表L.1", "QAJ-L1-1H/C",  "#008000", "绿色浅凹，浅凹陷。")
add(B1, "bnd_med_dep",                "中凹陷",          "Medium Depression",        "附录L.1 表L.1", "ZAJ-L1-1H/C",  "#008000", "绿色中等凹，中凹陷。")
add(B1, "bnd_deep_dep",               "深凹陷",          "Deep Depression",          "附录L.1 表L.1", "SAJ-L1-1H/C",  "#008000", "绿色深凹，深凹陷。")
add(B1, "bnd_nose_structure",         "鼻状构造",        "Nose Structure",           "附录L.1 表L.1", "BZG-L1-1H/C",  "#000",   "黑色尖鼻形，鼻状构造。")
add(B1, "bnd_sand_body_supp",         "砂岩体边界",      "Sand Body Boundary",       "附录L.1 表L.1", "SYT-L1-1H/C",  "#D71414", "红色点线，砂岩体边界。")
add(B1, "bnd_zone_g1",                "I级构造分区",     "Grade I Zone",             "附录L.2",       "JGZ-L2-1H/C",  "#000",   "粗黑线，I级构造分区。")
add(B1, "bnd_zone_g1_inferred",       "推测I级分区",     "Inferred Grade I Zone",    "附录L.2",       "JGZ-L2-2H/C",  "#666",   "虚线，推测I级分区。")
add(B1, "bnd_zone_g2",                "II级构造分区",    "Grade II Zone",            "附录L.2",       "JGZ-L2-3H/C",  "#333",   "粗线，II级分区。")
add(B1, "bnd_zone_g3",                "III级构造分区",   "Grade III Zone",           "附录L.2",       "JGZ-L2-4H/C",  "#666",   "中线，III级分区。")
add(B1, "bnd_trap_1",                 "一类圈闭",        "Class 1 Trap",             "附录L.3",       "QLB-L3-1H/C",  "#FE9999", "粉红菱形，一类圈闭。")
add(B1, "bnd_trap_2",                 "二类圈闭",        "Class 2 Trap",             "附录L.3",       "QLB-L3-2H/C",  "#FECC33", "黄色菱形，二类圈闭。")
add(B1, "bnd_attitude",               "地层产状",        "Attitude Symbol",          "附录L.4",       "DCCZ-L4-1H/C", "#000",   "长线+短垂线(走向/倾向)。")

# ── WELLS (33) ────────────────────────────────
W = "井型田设施"
add(W, "well_wildcat",          "野猫井",       "Wildcat Well",            "附录G.1 表G.1", "JW-G1-1H/C",  "#333",    "圆圈+十字，野猫井(初探井)。")
add(W, "well_spudded",          "已钻井",       "Spudded Well",            "附录G.1 表G.1", "JW-G1-2H/C",  "#333",    "圆圈+实心点，已钻井。")
add(W, "well_parameter",        "参数井",       "Parameter Well",          "附录G.1 表G.1", "JW-G1-3H/C",  "#333",    "圆圈+参字，参数井。")
add(W, "well_scientific",       "科学探索井",   "Scientific Well",         "附录G.1 表G.1", "JW-G1-4H/C",  "#333",    "圆圈+科字，科学探索井。")
add(W, "well_oiltest",          "试油井",       "Oil Test Well",           "附录G.1 表G.1", "JW-G1-5H/C",  "#333",    "圆圈+试字，试油井。")
add(W, "well_appraisal",        "评价井",       "Appraisal Well",          "附录G.1 表G.1", "JW-G1-6H/C",  "#00AA00", "绿边圆圈+十字，评价井。")
add(W, "well_sidetrack",        "侧钻井",       "Sidetrack Well",          "附录G.1 表G.1", "JW-G1-7H/C",  "#333",    "圆圈+侧线，侧钻井。")
add(W, "well_geo_junk",         "地质报废",     "Geological Abandoned",    "附录G.1 表G.1", "JW-G1-8H/C",  "#999",    "灰色虚线圈+地字，地质报废。")
add(W, "well_eng_junk",         "工程报废",     "Engineering Abandoned",   "附录G.1 表G.1", "JW-G1-9H/C",  "#999",    "灰色虚线圈+工字，工程报废。")
add(W, "well_no_show",          "未见显示",     "No Show",                 "附录G.1 表G.1", "JW-G1-10H/C", "#999",    "虚线圈+无字，无显示。")
add(W, "well_show",             "油气显示",     "Show Well",               "附录G.1 表G.1", "JW-G1-11H/C", "#FF6600", "橙色圈+显字，油气显示。")
add(W, "well_vertical_well",    "直井",         "Vertical Well",           "附录G.2 表G.2", "JW-G2-1H/C",  "#333",    "直线轨迹，直井。")
add(W, "well_directional_well", "定向井",       "Directional Well",        "附录G.2 表G.2", "JW-G2-2H/C",  "#333",    "折线轨迹，定向井。")
add(W, "well_horizontal_well",  "水平井",       "Horizontal Well",         "附录G.2 表G.2", "JW-G2-3H/C",  "#333",    "L形轨迹，水平井。")
add(W, "well_oil_prod",         "采油井",       "Oil Producer",            "附录G.2 表G.2", "JW-G2-4H/C",  "#00AA00", "圆圈+油字+绿边，采油井。")
add(W, "well_gas_prod",         "采气井",       "Gas Producer",            "附录G.2 表G.2", "JW-G2-5H/C",  "#FF3300", "圆圈+气字+红边，采气井。")
add(W, "well_water_prod",       "注水井",       "Water Injector",          "附录G.2 表G.2", "JW-G2-6H/C",  "#0071FF", "圆圈+水字+蓝边，注水井。")
add(W, "well_faultblock",       "断块井",       "Fault Block Well",        "附录G.2 表G.2", "JW-G2-7H/C",  "#333",    "圆圈+断字，断块井。")
add(W, "well_oil_layer",        "油层",         "Oil Pay Zone",            "附录G.2 表G.2", "JW-G2-8H/C",  "#2ECC71", "圆圈+油字+绿底，油层。")
add(W, "well_gas_layer",        "气层",         "Gas Pay Zone",            "附录G.2 表G.2", "JW-G2-9H/C",  "#FF9900", "圆圈+气字+橙底，气层。")
add(W, "well_oilgas_layer",     "油气层",       "O-G Pay Zone",            "附录G.2 表G.2", "JW-G2-10H/C", "#F1C40F", "圆圈+油气字+黄底，油气同层。")
add(W, "well_oil_water",        "油水层",       "Oil-Water Zone",          "附录G.2 表G.2", "JW-G2-11H/C", "#27AE60", "圆圈+上下分色，油水同层。")
add(W, "well_gas_water",        "气水层",       "Gas-Water Zone",          "附录G.2 表G.2", "JW-G2-12H/C", "#E67E22", "圆圈+气水标注，气水同层。")
add(W, "well_oil_bearing_w",    "含油水层",     "Oil-bearing Water",       "附录G.2 表G.2", "JW-G2-13H/C", "#6B8E23", "圆圈+油水标注，含油水层。")
add(W, "well_gas_bearing_w",    "含气水层",     "Gas-bearing Water",       "附录G.2 表G.2", "JW-G2-14H/C", "#D35400", "圆圈+气水标注，含气水层。")
add(W, "well_oilgas_show",      "油气显示层",   "O-G Show Zone",           "附录G.2 表G.2", "JW-G2-15H/C", "#FF6600", "圆圈+油气显示，油气显示层。")
add(W, "well_minor_oil",        "油浸",         "Minor Oil",               "附录G.2 表G.2", "JW-G2-16H/C", "#9ACD32", "圆圈+浅油斑，油浸级。")
add(W, "well_minor_gas",        "气浸",         "Minor Gas",               "附录G.2 表G.2", "JW-G2-17H/C", "#F39C12", "圆圈+浅气斑，气浸级。")
add(W, "well_planned",          "计划井",       "Planned Well",            "附录G.2 表G.2", "JW-G2-18H/C", "#999",    "虚线圈+待字，计划井。")
add(W, "well_prod_platform",    "生产平台",     "Production Platform",     "附录G.3 表G.3", "SP-G3-1H/C",  "#FF9900", "矩形+延伸臂，生产平台。")
add(W, "well_wellhead_plat",    "井口平台",     "Wellhead Platform",       "附录G.3 表G.3", "SP-G3-2H/C",  "#FF9900", "小矩形，井口平台。")
add(W, "well_section_well",     "连井剖面",     "Well Tie Section",        "附录G.3 表G.3", "SP-G3-3H/C",  "#333",    "剖面中井符号连线。")
add(W, "well_pipeline",         "管道",         "Pipeline",                "附录G.3 表G.3", "SP-G3-4H/C",  "#0071FF", "双线，海底管道。")

# ── RESERVOIRS (37) ────────────────────────────
R = "储层含油性"
add(R, "res_conformable_contact",    "整合接触",       "Conformable Contact",      "附录D.1 表D.1", "JCLX-D1-1H/C", "#000",   "平行直线，整合接触关系。")
add(R, "res_parallel_unconformity",  "平行不整合",     "Parallel Unconformity",    "附录D.1 表D.1", "JCLX-D1-2H/C", "#000",   "波浪断线，平行不整合。")
add(R, "res_angular_unconformity",   "角度不整合",     "Angular Unconformity",     "附录D.1 表D.1", "JCLX-D1-3H/C", "#000",   "斜线截断平行线，角度不整合。")
add(R, "res_res_fault",              "断层接触",       "Fault Contact",            "附录D.1 表D.1", "JCLX-D1-4H/C", "#000",   "断线+箭头，断层接触。")
add(R, "res_res_pinchout",           "尖灭",           "Pinchout",                 "附录D.1 表D.1", "JCLX-D1-5H/C", "#D71414","变细尖灭线，地层尖灭。")
add(R, "res_oil_layer",              "油层",           "Oil Layer",                "附录D.2 表D.2", "YCMD-D2-1H/C", "#2ECC71","绿色填充，含油层。")
add(R, "res_gas_layer",              "气层",           "Gas Layer",                "附录D.2 表D.2", "QCMD-D2-2H/C", "#FF9900","橙色填充，含气层。")
add(R, "res_oilgas_layer",           "油气同层",       "O-G Layer",                "附录D.2 表D.2", "YQTD-D2-3H/C", "#F1C40F","黄绿填充，油气同层。")
add(R, "res_water_layer",            "水层",           "Water Layer",              "附录D.2 表D.2", "SCTD-D2-4H/C", "#3498DB","蓝色填充，水层。")
add(R, "res_not_penetrated",         "未钻穿",         "Not Penetrated",           "附录D.2 表D.2", "WZC-D2-5H/C",  "#CCC",   "灰色填充，未钻穿层。")
add(R, "res_oil_water_same",         "油水同层",       "Oil-Water Layer",          "附录D.2 表D.2", "YSTD-D2-1H/C", "#27AE60","上下分色，油水同层。")
add(R, "res_gas_water_same",         "气水同层",       "Gas-Water Layer",          "附录D.2 表D.2", "QSTD-D2-2H/C", "#E67E22","上下分色，气水同层。")
add(R, "res_possible_oil",           "可能油层",       "Possible Oil",             "附录D.2 表D.2", "KNY-D2-3H/C",  "#9ACD32","浅绿，可能油层。")
add(R, "res_possible_gas",           "可能气层",       "Possible Gas",             "附录D.2 表D.2", "KNQ-D2-4H/C",  "#F39C12","浅橙，可能气层。")
add(R, "res_possible_gas2",          "可能气层(变体)", "Possible Gas Variant",     "附录D.2 表D.2", "KNQ-D2-5H/C",  "#F5B041","浅橙变体，可能气层。")
add(R, "res_gas_soaking",            "气浸",           "Gas Soaking",              "附录D.3 表D.3", "QJ-D3-1H/C",   "#F5B041","橙斑，气浸级。")
add(R, "res_gas_stain",              "气染",           "Gas Stain",                "附录D.3 表D.3", "QR-D3-2H/C",   "#F8C471","浅橙斑，气染级。")
add(R, "res_gas_trace",              "气迹",           "Gas Trace",                "附录D.3 表D.3", "QZ-D3-3H/C",   "#FAD7A0","极浅橙斑，气迹级。")
add(R, "res_oil_soaking",            "油浸",           "Oil Soaking",              "附录D.3 表D.3", "YJ-D3-1H/C",   "#6B8E23","暗绿斑，油浸级。")
add(R, "res_oil_stain",              "油斑",           "Oil Stain",                "附录D.3 表D.3", "YB-D3-2H/C",   "#556B2F","深绿斑，油斑级。")
add(R, "res_oil_trace",              "油迹",           "Oil Trace",                "附录D.3 表D.3", "YZ-D3-3H/C",   "#8FBC8F","浅绿斑，油迹级。")
add(R, "res_oil_bearing",            "含油",           "Oil-bearing",              "附录D.3 表D.3", "HY-D3-5H/C",   "#9ACD32","黄绿填充，含油。")
add(R, "res_oil_bearing_water",      "含油水层",       "Oil-bearing Water",        "附录D.3 表D.3", "HYS-D3-6H/C",  "#7F8C8D","灰绿，含油水层。")
add(R, "res_oil_sand_log",           "油砂",           "Oil Sand Log",             "附录D.3 表D.3", "YS-D3-7H/C",   "#8B7355","砂质+油斑，油砂。")
add(R, "res_fluorescence",           "荧光",           "Fluorescence",             "附录D.3 表D.3", "YG-D3-8H/C",   "#D3D3D3","灰荧光纹理，荧光级。")
add(R, "res_log_oil_layer",          "测井油层",       "Log Oil Layer",            "附录D.4 表D.4", "CLJ-D4-1H/C",  "#2ECC71","绿色曲线，测井油层。")
add(R, "res_log_gas_layer",          "测井气层",       "Log Gas Layer",            "附录D.4 表D.4", "CLJ-D4-2H/C",  "#FF9900","橙色曲线，测井气层。")
add(R, "res_log_oil_water",          "测井油水同层",   "Log O-W Same Layer",       "附录D.4 表D.4", "CLJ-D4-3H/C",  "#F1C40F","黄绿曲线，油水同层。")
add(R, "res_log_oil_water2",         "测井油水层(变体)","Log O-W Variant",          "附录D.4 表D.4", "CLJ-D4-4H/C",  "#F39C12","橙黄曲线，油水层变体。")
add(R, "res_log_poor_oil",           "测井差油层",     "Log Poor Oil",             "附录D.4 表D.4", "CLJ-D4-5H/C",  "#9ACD32","浅绿曲线，差油层。")
add(R, "res_log_dry",                "测井干层",       "Log Dry Layer",            "附录D.4 表D.4", "CLJ-D4-6H/C",  "#CCC",   "灰色曲线，干层。")
add(R, "res_layer_marker",           "标志层",         "Marker Bed",               "附录D.5",       "BZC-D5-1H/C",  "#F39C12","黄线，区域标志层。")
add(R, "res_sand_layer_supp",        "砂岩补充符号",   "Sand Layer Supplement",    "附录D.5",       "SYBZ-D5-2H/C", "#E8D5B5","点线，砂岩补充标注。")
add(R, "res_water_flooded",          "水淹层",         "Water-flooded Zone",       "附录D.5 表D.5", "SYC-D5-1H/C",  "#5DADE2","中蓝纹理，水淹。")
add(R, "res_strong_flooded",         "强水淹层",       "Strong Water-flooded",     "附录D.5 表D.5", "SYC-D5-2H/C",  "#3498DB","深蓝纹理，强水淹。")
add(R, "res_liq_hc_inclusion",       "液态烃包裹体",   "Liquid HC Inclusion",      "附录D.6 表D.6", "BGTJ-D6-1H/C", "#FFD700","金黄色圆圈，液态烃。")
add(R, "res_gas_hc_inclusion",       "气态烃包裹体",   "Gas HC Inclusion",         "附录D.6 表D.6", "BGTJ-D6-2H/C", "#FFF",   "白圈+灰边，气态烃。")
add(R, "res_brine_inclusion",        "盐水包裹体",     "Brine Inclusion",          "附录D.6 表D.6", "BGTJ-D6-3H/C", "#CCC",   "灰圈，盐水包裹体。")
add(R, "res_hc_brine_inclusion",     "油气盐水包裹体", "HC-Brine Inclusion",       "附录D.6 表D.6", "BGTJ-D6-4H/C", "#F39C12","双色圆，油气盐水。")

# ── STRATA (29) ────────────────────────────────
S = "地层沉积相"
add(S, "strat_quaternary",         "第四系",         "Quaternary",               "附录N.1 表N.1", "DCND-N1-1C",   "#f5ecd7", "Q字母，浅黄填充，最新地质年代。")
add(S, "strat_neogene",            "新近系",         "Neogene",                  "附录N.1 表N.1", "DCND-N1-2C",   "#FFE4B5", "N字母，浅橙填充。")
add(S, "strat_paleogene",          "古近系",         "Paleogene",                "附录N.1 表N.1", "DCND-N1-3C",   "#B0E0E6", "E字母，浅蓝填充。")
add(S, "strat_cretaceous",         "白垩系",         "Cretaceous",               "附录N.1 表N.1", "DCND-N1-4C",   "#DEB887", "K字母，浅棕填充。")
add(S, "strat_jurassic",           "侏罗系",         "Jurassic",                 "附录N.1 表N.1", "DCND-N1-5C",   "#D2B48C", "J字母，浅棕填充。")
add(S, "strat_triassic",           "三叠系",         "Triassic",                 "附录N.1 表N.1", "DCND-N1-6C",   "#C8A882", "T字母，棕色填充。")
add(S, "strat_permian",            "二叠系",         "Permian",                  "附录N.1 表N.1", "DCND-N1-7C",   "#C0A080", "P字母，深棕填充。")
add(S, "strat_carboniferous",      "石炭系",         "Carboniferous",            "附录N.1 表N.1", "DCND-N1-8C",   "#B89878", "C字母，更深棕填充。")
add(S, "strat_devonian",           "泥盆系",         "Devonian",                 "附录N.1 表N.1", "DCND-N1-9C",   "#B09070", "D字母，泥盆纪地层。")
add(S, "strat_silurian",           "志留系",         "Silurian",                 "附录N.1 表N.1", "DCND-N1-10C",  "#A88868", "S字母，志留纪地层。")
add(S, "strat_ordovician",         "奥陶系",         "Ordovician",               "附录N.1 表N.1", "DCND-N1-11C",  "#A08060", "O字母，奥陶纪地层。")
add(S, "strat_cambrian",           "寒武系",         "Cambrian",                 "附录N.1 表N.1", "DCND-N1-12C",  "#987858", "∈符号，寒武纪地层。")
add(S, "strat_proterozoic",        "元古界",         "Proterozoic",              "附录N.1 表N.1", "DCND-N1-13C",  "#908070", "Pt字母，元古代地层。")
add(S, "strat_archean",            "太古界",         "Archean",                  "附录N.1 表N.1", "DCND-N1-14C",  "#887060", "Ar字母，太古代地层。")
add(S, "strat_continental_facies", "陆相沉积",       "Continental Facies",       "附录O.1 表O.1", "CJX-O1-1C",    "#E8D5B0", "浅棕填充，陆相环境。")
add(S, "strat_fluvial",            "河流相",         "Fluvial Facies",           "附录O.1 表O.1", "HLX-O1-5C",    "#E8D5B0", "河道纹理，河流相。")
add(S, "strat_lacustrine",         "湖泊相",         "Lacustrine Facies",        "附录O.1 表O.1", "HPX-O1-6C",    "#D5E8D0", "波纹纹理，湖泊相。")
add(S, "strat_alluvial_fan",       "洪积相",         "Alluvial Fan",             "附录O.1 表O.1", "HJX-O1-3C",    "#E8DCC0", "扇形填充，洪积相。")
add(S, "strat_aeolian",            "沙漠相",         "Aeolian Facies",           "附录O.1 表O.1", "SMX-O1-2C",    "#F5E6C8", "沙丘纹理，沙漠相。")
add(S, "strat_glacial",            "冰川相",         "Glacial Facies",           "附录O.1 表O.1", "BCX-O1-4C",    "#E8EEF0", "擦痕纹理，冰川相。")
add(S, "strat_deltaic",            "三角洲相",       "Deltaic Facies",           "附录O.2 表O.2", "SJZX-O2-1C",   "#E8D5B0", "三角形沉积体，三角洲。")
add(S, "strat_delta",              "三角洲",         "Delta Facies",             "附录O.2 表O.2", "SJZ-O2-2C",    "#E8D5B0", "三角填充，三角洲。")
add(S, "strat_coastal_shallow",    "滨海亚浅海",     "Coastal-Subtidal",         "附录O.2 表O.2", "BHQH-O2-3C",   "#C8E6F0", "浅蓝填充，滨海-亚浅海。")
add(S, "strat_coastal",            "滨海相",         "Coastal Facies",           "附录O.2 表O.2", "BHX-O2-4C",    "#C8E6F0", "波浪纹理，滨海相。")
add(S, "strat_shallow_marine",     "浅海相",         "Shallow Marine",           "附录O.3 表O.3", "QHX-O3-1C",    "#A8D8EA", "中蓝填充，浅海相。")
add(S, "strat_semideep_marine",    "次深海相",       "Semi-Deep Marine",         "附录O.3 表O.3", "CSHX-O3-2C",   "#7EC8E3", "较深蓝，次深海相。")
add(S, "strat_deep_marine",        "深海相",         "Deep Marine",              "附录O.3 表O.3", "SHX-O3-3C",    "#4AA8C8", "深蓝填充，深海相。")
add(S, "strat_provenance",         "物源方向",       "Provenance Direction",     "附录O.4 表O.4", "WYFX-O4-1C",   "#D71414", "红色箭头，物源方向。")
add(S, "strat_sedimentary_boundary","沉积界线",      "Sedimentary Boundary",     "附录O.5 表O.5", "CJJX-O5-2C",   "#B8956A", "虚线，沉积相边界。")

# ── GEOGRAPHIC (27) ────────────────────────────
G = "地理注记"
add(G, "geo_national_boundary",     "国界",         "National Boundary",        "附录H.1 表H.1", "XZQH-H1-1H/C", "#000",    "粗实线+方块，国家边界。")
add(G, "geo_provincial_boundary",   "省界",         "Provincial Boundary",      "附录H.1 表H.1", "XZQH-H1-2H/C", "#000",    "实线+圆点，省级边界。")
add(G, "geo_regional_boundary",     "地区界",       "Regional Boundary",        "附录H.1 表H.1", "XZQH-H1-3H/C", "#000",    "细线+空心圆，地区级边界。")
add(G, "geo_coastline",             "海岸线",       "Coastline",                "附录H.4 表H.4", "HAX-H4-1H/C",  "#0071FF", "蓝色波浪线，海岸线。")
add(G, "geo_isobath",               "等深线",       "Isobath",                  "附录H.4 表H.4", "HAX-H4-2H/C",  "#0071FF", "蓝色虚线波浪，海底等深线。")
add(G, "geo_island_reef",           "岛礁",         "Island/Reef",              "附录H.4 表H.4", "HAX-H4-3H/C",  "#EC2667", "粉红椭圆，岛屿/礁石。")
add(G, "geo_sea_area",              "海水域",       "Sea Water Area",           "附录H.4 表H.4", "HAX-H4-4H/C",  "#D0E4CE", "浅绿填充，海域范围。")
add(G, "geo_lake",                  "湖泊",         "Lake",                     "附录H.4 表H.4", "HUP-H4-5H/C",  "#0071FF", "蓝色椭圆，湖泊。")
add(G, "geo_river",                 "河流",         "River",                    "附录H.4 表H.4", "HEL-H4-9H/C",  "#0071FF", "蓝色粗波浪线，常年河。")
add(G, "geo_intermittent_river",    "时令河",       "Intermittent River",       "附录H.4 表H.4", "HEL-H4-10H/C", "#0071FF", "蓝色虚线波浪，季节性河。")
add(G, "geo_canal",                 "运河",         "Canal",                    "附录H.4 表H.4", "HEL-H4-11H/C", "#0071FF", "蓝色双平行线，人工运河。")
add(G, "geo_dam",                   "堤坝",         "Dam/Levee",                "附录H.4 表H.4", "DIB-H4-13H/C", "#000",    "黑蓝双线，堤坝工程。")
add(G, "geo_reservoir_water",       "水库",         "Reservoir",                "附录H.4 表H.4", "SHK-H4-14H/C", "#0071FF", "蓝色三角，水库。")
add(G, "geo_peak",                  "山峰/标高",    "Peak/Elevation",           "附录H.5 表H.5", "DIX-H5-6H/C",  "#996633", "棕三角+标高文字。")
add(G, "geo_crater",                "火山口",       "Crater",                   "附录H.5 表H.5", "DIX-H5-7H/C",  "#FF0000", "红色双圈，火山口。")
add(G, "geo_forest",                "森林",         "Forest",                   "附录H.5 表H.5", "ZIB-H5-8H/C",  "#00CC00", "绿色三角树形，森林。")
add(G, "geo_single_tree",           "独立树",       "Single Tree",              "附录H.5 表H.5", "ZIB-H5-9H/C",  "#00CC00", "绿圈+棕干，单棵树。")
add(G, "geo_shrub",                 "灌木林",       "Shrub",                    "附录H.5 表H.5", "ZIB-H5-10H/C", "#00CC00", "绿色椭圆，灌木丛。")
add(G, "geo_highway",               "高速公路",     "Highway",                  "附录H.6 表H.6", "JIAOT-H6-1C",  "#FF9900", "橙色粗线，高速公路。")
add(G, "geo_general_road",          "普通公路",     "General Road",             "附录H.6 表H.6", "JIAOT-H6-2C",  "#000",    "黑色细线，普通公路。")
add(G, "geo_railway",               "普通铁路",     "Railway",                  "附录H.6 表H.6", "JIAOT-H6-4C",  "#000",    "黑白双线+竖线，铁路。")
add(G, "geo_airport",               "机场",         "Airport",                  "附录H.6 表H.6", "JIAOT-H6-7C",  "#0000FF", "蓝色椭圆+横线，机场。")
add(G, "geo_port",                  "码头港口",     "Port/Wharf",               "附录H.6 表H.6", "JIAOT-H6-8C",  "#0000FF", "蓝色矩形+延伸线，港口。")
add(G, "geo_well_label",            "井位标注",     "Well Label",               "附录P.3 表P.3", "JWBZ-P3-2H/C", "#000",    "井名+圆圈，标注井位。")
add(G, "geo_basin_label",           "盆地构造标注", "Basin Label",              "附录P.3 表P.3", "GZBZ-P3-3H/C", "#000",    "盆地名称标注。")
add(G, "geo_field_label",           "油气田标注",   "Field Label",              "附录P.3 表P.3", "YQBZ-P3-4H/C", "#00AA00", "油气田名+绿圆点。")
add(G, "geo_reservoir_section",     "油藏剖面",     "Reservoir Section",        "附录P.3 表P.3", "YCPM-P3-5H/C", "#000",    "剖面图位置标注。")

# ── SEISMIC (17) ───────────────────────────────
SM = "地震符号"
add(SM, "seis_2d_crossing_grid",   "二维测线(交叉网格)", "2D Seismic Crossing Grid", "附录D.10",  "SEC-A7-1H/C",  "#D71414", "红色交叉斜线，二维测线网格。")
add(SM, "seis_2d_dense_grid",       "二维测线(密集)",    "2D Dense Grid",            "附录D.10",  "SEC-A7-2H/C",  "#D71414", "密集红色交叉线。")
add(SM, "seis_2d_sparse",           "二维测线(稀疏)",    "2D Sparse Line",           "附录D.10",  "SEC-A7-3H/C",  "#D71414", "稀疏红色单线。")
add(SM, "seis_2d_direction",        "测线方向标注",      "Line Direction Label",     "附录D.10",  "SEC-A7-4H/C",  "#D71414", "红色线+箭头+方向标注。")
add(SM, "seis_3d_coverage",         "三维勘探区域",      "3D Survey Area",           "附录D.11",  "SEC-A7-5H/C",  "#1A54B4", "蓝色网格填充，三维勘探。")
add(SM, "seis_3d_full_fold",        "三维满覆盖",        "3D Full-fold",             "附录D.11",  "SEC-A7-6H/C",  "#1A54B4", "蓝色网格+粗边框，满覆盖。")
add(SM, "seis_3d_partial",          "三维部分覆盖",      "3D Partial Coverage",      "附录D.11",  "SEC-A7-7H/C",  "#1A54B4", "蓝色网格+虚线边框。")
add(SM, "seis_3d_label_purple",     "三维标注(粉紫)",    "3D Label Purple",          "附录D.11",  "SEC-A7-8H/C",  "#9B59B6", "粉紫圆角矩形，3D区块标注。")
add(SM, "seis_3d_label_blue",       "三维标注(浅蓝)",    "3D Label Blue",            "附录D.11",  "SEC-A7-9H/C",  "#3498DB", "浅蓝圆角矩形，3D区块标注。")
add(SM, "seis_drill_exploration",   "探井(已钻)",       "Exploration Well",         "附录D.12",  "DRL-A8-1H/C",  "#D71414", "红色圆圈+井字，已钻探井。")
add(SM, "seis_drill_parameter",     "参数井",           "Parameter Well",           "附录D.12",  "DRL-A8-2H/C",  "#333",   "黑色圆圈+参字+十字。")
add(SM, "seis_drill_appraisal",     "评价井",           "Appraisal Well",           "附录D.12",  "DRL-A8-3H/C",  "#00AA00","绿色圆圈+评字。")
add(SM, "seis_drill_development",   "开发井",           "Development Well",         "附录D.12",  "DRL-A8-4H/C",  "#FF9900","橙色圆圈+开字。")
add(SM, "seis_drill_show",          "油气显示井",       "Show Well",                "附录D.12",  "DRL-A8-5H/C",  "#FF6600","橙色半透明+显字。")
add(SM, "seis_drill_abandoned",     "报废井",           "Abandoned Well",           "附录D.12",  "DRL-A8-6H/C",  "#666",   "灰色虚线+废字。")
add(SM, "seis_section_seismic",     "地震剖面线",       "Seismic Section Line",     "附录D.12",  "SEC-A7-10H/C", "#D71414","红色虚线+A-B，剖面线。")
add(SM, "seis_section_welltie",     "连井剖面线",       "Well-Tie Section",         "附录D.12",  "SEC-A7-11H/C", "#333",   "虚线+彩色圆点，连井剖面。")

# ── FOLDS (23) ────────────────────────────────
F = "褶皱构造"
add(F, "fold_anticline",           "背斜",            "Anticline",             "附录I.3 表I.3", "ZZGZ-I3-1H/C", "#C87830","向上拱起弧线+轴箭头。")
add(F, "fold_syncline",            "向斜",            "Syncline",              "附录I.3 表I.3", "ZZGZ-I3-2H/C", "#C87830","向下弯曲弧线。")
add(F, "fold_tight_anticline",     "紧闭背斜",        "Tight Anticline",       "附录I.3 表I.3", "ZZGZ-I3-3H/C", "#C87830","多个紧密向上弧形。")
add(F, "fold_open_anticline",      "开阔背斜",        "Open Anticline",        "附录I.3 表I.3", "ZZGZ-I3-4H/C", "#C87830","宽幅向上弧形。")
add(F, "fold_overturned_anticline","倒转背斜",        "Overturned Anticline",  "附录I.3 表I.3", "ZZGZ-I3-5H/C", "#C87830","一侧倒转弧形。")
add(F, "fold_recumbent_fold",      "平卧褶皱",        "Recumbent Fold",        "附录I.3 表I.3", "ZZGZ-I3-6H/C", "#C87830","水平线+下方弧形。")
add(F, "fold_isoclinal_fold",      "等斜褶皱",        "Isoclinal Fold",        "附录I.3 表I.3", "ZZGZ-I3-7H/C", "#C87830","两翼等倾角弧形。")
add(F, "fold_chevron_fold",        "尖棱褶皱",        "Chevron Fold",          "附录I.3 表I.3", "ZZGZ-I3-8H/C", "#C87830","V形尖角折线。")
add(F, "fold_box_fold",            "箱状褶皱",        "Box Fold",              "附录I.3 表I.3", "ZZGZ-I3-9H/C", "#C87830","矩形框状折线。")
add(F, "fold_jug_handle_fold",     "隔档式褶皱",      "Jug-Handle Fold",       "附录I.3 表I.3", "ZZGZ-I3-10H/C","#C87830","两弧形+中间竖线。")
add(F, "fold_trough_fold",         "隔槽式褶皱",      "Trough Fold",           "附录I.3 表I.3", "ZZGZ-I3-11H/C","#C87830","两竖线+中间弧形。")
add(F, "fold_structural_terrace",  "构造阶地",        "Structural Terrace",    "附录I.3 表I.3", "ZZGZ-I3-12H/C","#C87830","折线+底边线。")
add(F, "fold_dome",                "穹隆构造",        "Dome Structure",        "附录I.3 表I.3", "ZZGZ-I3-13H/C","#C87830","双层椭圆+中心线。")
add(F, "fold_basin_structure",     "盆地构造",        "Basin Structure",       "附录I.3 表I.3", "ZZGZ-I3-14H/C","#C87830","双层椭圆。")
add(F, "fold_flexure",             "挠曲",            "Flexure",               "附录I.3 表I.3", "ZZGZ-I3-15H/C","#C87830","宽幅波浪形线。")
add(F, "fold_diapir",              "刺穿构造",        "Diapir",                "附录I.3 表I.3", "ZZGZ-I3-16H/C","#C87830","中间尖突曲线。")
add(F, "fold_fold_axis",           "褶皱轴线",        "Fold Axis",             "附录I.3 表I.3", "ZZGZ-I3-17H/C","#000",   "直线+菱形箭头。")
add(F, "fold_hinge_line",          "枢纽线",          "Hinge Line",            "附录I.3 表I.3", "ZZGZ-I3-18H/C","#000",   "虚线。")
add(F, "fold_plunging_end",        "倾伏端",          "Plunging End",          "附录I.3 表I.3", "ZZGZ-I3-19H/C","#000",   "线+指向箭头。")
add(F, "fold_strong_reflection",   "强反射",          "Strong Reflection",     "附录I.3 表I.3", "ZZGZ-I3-20H/C","#000",   "粗实线。")
add(F, "fold_weak_reflection",     "弱反射",          "Weak Reflection",       "附录I.3 表I.3", "ZZGZ-I3-21H/C","#999",   "细虚线。")
add(F, "fold_chaotic_reflection",  "杂乱反射",        "Chaotic Reflection",    "附录I.3 表I.3", "ZZGZ-I3-22H/C","#000",   "不规则折线。")
add(F, "fold_blank_reflection",    "空白反射",        "Blank Reflection",      "附录I.3 表I.3", "ZZGZ-I3-23H/C","#CCC",   "细灰线，无反射。")

# ── MINING (19) ────────────────────────────────
M = "矿区储量"
add(M, "mine_self_explore",        "自营勘查矿区",  "Self-Operated Block",       "附录D.8", "MIN-D8-1H/C",  "#FFCCCC","粉红填充矩形，自营勘查。")
add(M, "mine_joint_explore",        "联合勘查矿区",  "Joint Exploration Block",   "附录D.8", "MIN-D8-2H/C",  "#CCFFCC","绿色填充矩形，联合勘查。")
add(M, "mine_cooperation",          "合作矿区",      "Cooperation Block",         "附录D.8", "MIN-D8-3H/C",  "#CCE5FF","蓝色填充矩形，合作矿区。")
add(M, "mine_production",           "开采矿区",      "Production Block",          "附录D.8", "MIN-D8-4H/C",  "#E0CCFF","紫色填充矩形，开采矿区。")
add(M, "mine_self_contract",        "自营合同区",    "Self-Operated Contract",    "附录D.9", "COOP-D9-1H/C", "#FFE4E1","浅红填充，自营合同。")
add(M, "mine_joint_contract",       "合作合同区",    "Joint Contract",            "附录D.9", "COOP-D9-2H/C", "#E0F0FF","浅蓝填充，合作合同。")
add(M, "mine_contract_boundary",    "合同区块边界",  "Contract Boundary",         "附录D.9", "COOP-D9-3H/C", "#0071FF","蓝色实线矩形框。")
add(M, "mine_contract_number",      "合同区块编号",  "Contract Number",           "附录D.9", "COOP-D9-4H/C", "#0071FF","蓝色框+编号如15/06。")
add(M, "mine_proved_reserve",       "探明储量",      "Proved Reserve",            "附录J.1", "RES-J3-1H/C",  "#00AA00","绿色圆圈+探明文字。")
add(M, "mine_controlled_reserve",   "控制储量",      "Controlled Reserve",        "附录J.1", "RES-J3-2H/C",  "#66BB6A","浅绿圆圈+控制文字。")
add(M, "mine_forecast_reserve",     "预测储量",      "Forecast Reserve",          "附录J.1", "RES-J3-3H/C",  "#FFEB3B","黄色圆圈+预测文字。")
add(M, "mine_prospective",          "远景资源量",    "Prospective Resource",      "附录J.1", "RES-J3-4H/C",  "#FFF",   "白色虚线圆圈。")
add(M, "mine_trap_class1",          "一类圈闭",      "Class 1 Trap",              "附录I.2", "QUANB-B2-36C",  "#FE9999","粉红菱形，一类圈闭。")
add(M, "mine_trap_class2",          "二类圈闭",      "Class 2 Trap",              "附录I.2", "QUANB-B2-37C",  "#FECC33","黄色菱形，二类圈闭。")
add(M, "mine_oil_field",            "油田",          "Oil Field",                 "附录J.1", "YTCL-J1-1H/C",  "#00AA00","绿点+油字，油田位置。")
add(M, "mine_gas_field",            "气田",          "Gas Field",                 "附录J.1", "QTCL-J1-2H/C",  "#FF3300","红点+气字，气田位置。")
add(M, "mine_oilgas_boundary",      "油气水边界线",  "O-G-W Boundary",            "附录J.2", "YQSX-J2-1H/C",  "#000",   "粗实线，油气水边界。")
add(M, "mine_mining_boundary",      "矿区边界线",    "Mining Boundary",           "附录H.2", "KQBJ-H2-1H/C",  "#0071FF","蓝色实线，矿区边界。")
add(M, "mine_mining_boundary_inf",  "预测矿区边界",  "Predicted Boundary",        "附录H.2", "KQBJ-H2-2H/C",  "#0071FF","蓝色虚线，预测矿区边界。")

# ── BASIC ROCKS (34) ───────────────────────────
B = "基本岩类"
add(B, "rock_sedimentary_rock",   "沉积岩",       "Sedimentary Rock",      "附录M.1.1 表M.1.1", "ROCK-M1-1H/C", "#f4e4c1","点状填充，沉积岩类。")
add(B, "rock_magmatic_rock",      "岩浆岩",       "Magmatic Rock",         "附录M.1.1 表M.1.1", "ROCK-M1-2H/C", "#d4c8b8","晶质填充，岩浆岩类。")
add(B, "rock_metamorphic_rock",   "变质岩",       "Metamorphic Rock",      "附录M.1.1 表M.1.1", "ROCK-M1-3H/C", "#b8a898","片状填充，变质岩类。")
add(B, "rock_conglomerate_basic", "砾岩",         "Conglomerate",          "附录M.1.1 表M.1.1", "ROCK-M1-4H/C", "#d8c8a8","砾石填充，砾岩。")
add(B, "rock_sandstone_basic",    "砂岩",         "Sandstone",             "附录M.1.1 表M.1.1", "ROCK-M1-5H/C", "#f4e4c1","砂质填充，砂岩。")
add(B, "rock_siltstone_basic",    "粉砂岩",       "Siltstone",             "附录M.1.1 表M.1.1", "ROCK-M1-6H/C", "#e8dcc8","粉砂质填充，粉砂岩。")
add(B, "rock_shale_basic",        "页岩",         "Shale",                 "附录M.1.1 表M.1.1", "ROCK-M1-7H/C", "#b8c5d6","页理填充，页岩。")
add(B, "rock_limestone_basic",    "石灰岩",       "Limestone",             "附录M.1.1 表M.1.1", "ROCK-M1-8H/C", "#f0e8d8","生物碎屑填充，石灰岩。")
add(B, "rock_dolomite_basic",     "白云岩",       "Dolomite",              "附录M.1.1 表M.1.1", "ROCK-M1-9H/C", "#e5ddd0","晶粒填充，白云岩。")
add(B, "rock_mudstone_basic",     "泥岩",         "Mudstone",              "附录M.1.1 表M.1.1", "ROCK-M1-10H/C","#d5d0c8","均匀填充，泥岩。")
add(B, "rock_coal_basic",         "煤",           "Coal",                  "附录M.1.1 表M.1.1", "ROCK-M1-11H/C","#2a2a2a","黑色填充，煤层。")
add(B, "rock_volcanic_basic",     "火山岩",       "Volcanic Rock",         "附录M.1.1 表M.1.1", "ROCK-M1-12H/C","#5a5850","火山碎屑填充。")
add(B, "rock_intrusive_basic",    "侵入岩",       "Intrusive Rock",        "附录M.1.1 表M.1.1", "ROCK-M1-13H/C","#d4c8b8","花岗质填充。")
add(B, "rock_quartz",             "石英",         "Quartz",                "附录M.1.2",         "CLST-M1-1H/C","#666",  "六边形，石英碎屑。")
add(B, "rock_feldspar",           "长石",         "Feldspar",              "附录M.1.2",         "CLST-M1-2H/C","#666",  "旋转正方形，长石碎屑。")
add(B, "rock_lithic_fragment",    "岩屑",         "Lithic Fragment",       "附录M.1.2",         "CLST-M1-3H/C","#666",  "不规则多边形，岩屑。")
add(B, "rock_grain_coarse",       "粗粒",         "Coarse Grain",          "附录M.1.3",         "GRAN-M1-1H/C","#c4a473","大圆点，粗粒结构。")
add(B, "rock_grain_medium",       "中粒",         "Medium Grain",          "附录M.1.3",         "GRAN-M1-2H/C","#d4b483","中圆点，中粒结构。")
add(B, "rock_grain_fine",         "细粒",         "Fine Grain",            "附录M.1.3",         "GRAN-M1-3H/C","#d4c4a0","小圆点，细粒结构。")
add(B, "rock_grain_silt",         "粉砂级",       "Silt Grade",            "附录M.1.3",         "GRAN-M1-4H/C","#e0d5c0","微小圆点，粉砂级。")
add(B, "rock_mineral_quartz",     "石英(矿物)",   "Quartz Mineral",        "附录M.2.7",         "MIN-M2-1H/C", "#888",  "六边形，石英矿物。")
add(B, "rock_mineral_feldspar",   "长石(矿物)",   "Feldspar Mineral",      "附录M.2.7",         "MIN-M2-2H/C", "#888",  "旋转正方形。")
add(B, "rock_mineral_mica",       "云母",         "Mica",                  "附录M.2.7",         "MIN-M2-3H/C", "#888",  "长菱形，云母矿物。")
add(B, "rock_mineral_calcite",    "方解石",       "Calcite",               "附录M.2.7",         "MIN-M2-4H/C", "#888",  "五边形，方解石矿物。")
add(B, "rock_fossil_bivalvia",    "瓣鳃类",       "Bivalvia",              "附录M.2.8",         "FOSS-M2-1H/C","#666",  "椭圆+中线，瓣鳃化石。")
add(B, "rock_fossil_gastropoda",  "腹足类",       "Gastropoda",            "附录M.2.8",         "FOSS-M2-2H/C","#666",  "螺旋形，腹足化石。")
add(B, "rock_fossil_ammonite",    "菊石",         "Ammonite",              "附录M.2.8",         "FOSS-M2-3H/C","#666",  "圆圈+旋线，菊石化石。")
add(B, "rock_fossil_trilobite",   "三叶虫",       "Trilobite",             "附录M.2.8",         "FOSS-M2-4H/C","#666",  "椭圆+附肢，三叶虫化石。")
add(B, "rock_bedding_horizontal", "水平层理",     "Horizontal Bedding",    "附录M.2.9",         "STRU-M2-1H/C","#666",  "平行水平线，水平层理。")
add(B, "rock_bedding_wavy",       "波状层理",     "Wavy Bedding",          "附录M.2.9",         "STRU-M2-2H/C","#666",  "波浪平行线，波状层理。")
add(B, "rock_bedding_cross",      "交错层理",     "Cross-bedding",         "附录M.2.9",         "STRU-M2-3H/C","#666",  "斜交平行线，交错层理。")
add(B, "rock_bedding_lenticular", "透镜状层理",   "Lenticular Bedding",    "附录M.2.9",         "STRU-M2-4H/C","#666",  "交错椭圆，透镜层理。")
add(B, "rock_mud_crack",          "泥裂",         "Mud Crack",             "附录M.2.9",         "STRU-M2-5H/C","#666",  "多边形裂纹，泥裂。")
add(B, "rock_rain_print",         "雨痕",         "Rain Print",            "附录M.2.9",         "STRU-M2-6H/C","#666",  "小圆圈，雨痕构造。")

if __name__ == "__main__":
    # ──────────────────────────────────────────────
    # Write catalog.json
    # ──────────────────────────────────────────────
    with open(os.path.join(OUTDIR, "catalog.json"), 'w', encoding='utf-8') as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    # Write individual description files
    for entry in catalog:
        write_desc(entry)

    # Summary
    from collections import Counter
    cat_counts = Counter(e['category'] for e in catalog)
    print(f"\nTotal catalog entries: {len(catalog)}")
    print(f"Description files:    {len(os.listdir(DESCDIR))}")
    print()
    for k, v in sorted(cat_counts.items()):
        print(f"  {v:3d}  {k}")
