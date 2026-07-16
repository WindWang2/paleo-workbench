from paleo_workbench.ui import tokens


SCREEN_INVENTORY = {
    "source": "古地理图编制系统 (standalone).html",
    "tokens": {
        "primary": tokens.PRIMARY,
        "accent": tokens.ACCENT,
        "success": tokens.SUCCESS,
        "warning": tokens.WARNING,
        "surface": tokens.BG_SIDEBAR,
        "background": tokens.BG_BODY,
        "header": tokens.BG_HEADER,
        "teal": tokens.TEAL,
    },
    "pages": [
        {"id": "dashboard", "title": "工程工作台", "purpose": "编图任务总览与运行入口"},
        {"id": "data", "title": "多源数据管理与转换", "purpose": "资源扫描、导入、分类、状态管理"},
        {"id": "well_log_prediction", "title": "测井预测", "purpose": "测井曲线展示、沉积相预测与证据贡献"},
        {"id": "seismic_prediction", "title": "地震预测", "purpose": "地震体展示、预测概率体与控制参数"},
        {"id": "sequence_framework", "title": "层序格架", "purpose": "目标层位、解释版本与层序方案管理"},
        {"id": "stratigraphy_correlation", "title": "地层对比", "purpose": "多井连井对比、相/顶叠加、CrossWell 导出"},
        {"id": "visualization", "title": "数据可视化", "purpose": "测井、地震、连井、参考资料回溯"},
        {"id": "preparation", "title": "制图数据制备", "purpose": "单因素图任务管理与预览"},
        {"id": "paleomap", "title": "古地理图编制", "purpose": "相带草图、人工编辑、图例样式"},
        {"id": "qc_export", "title": "质控与导出", "purpose": "规则检查、问题处理、成果导出"},
    ],
}
