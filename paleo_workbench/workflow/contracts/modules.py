"""P0 (+ real) domain workflow contracts built from audited code.

All scientific claims that are not proven in code use
EXPERT_CONFIRMATION_REQUIRED and attach ExpertConsultationQuestion.
"""

from __future__ import annotations

from paleo_workbench.workflow.contracts.models import (
    Certainty,
    DomainWorkflowContract,
    ExpertConsultationQuestion,
    ExpertQuestionCategory,
    ExpertQuestionPriority,
    ExpertQuestionStatus,
    ImplementationStatus,
    InputCardinality,
    InputRole,
    InputVersionSemantics,
    ParameterCategory,
    QCSeverity,
    WorkflowInputSpec,
    WorkflowOperationStep,
    WorkflowOutputSpec,
    WorkflowParameterSpec,
    WorkflowQCSpec,
    WorkflowSourceEvidence,
)


def _ev(path: str, symbol: str = "", description: str = "") -> WorkflowSourceEvidence:
    return WorkflowSourceEvidence(path=path, symbol=symbol, description=description)


def _q(
    id: str,
    module_id: str,
    category: ExpertQuestionCategory,
    question: str,
    behavior: str,
    why: str,
    impact: str,
    *,
    priority: ExpertQuestionPriority = ExpertQuestionPriority.P0,
    options: list[str] | None = None,
    evidence: list[WorkflowSourceEvidence] | None = None,
) -> ExpertConsultationQuestion:
    return ExpertConsultationQuestion(
        id=id,
        module_id=module_id,
        category=category,
        question=question,
        current_software_behavior=behavior,
        why_it_matters=why,
        options_if_known=options or [],
        impact_if_unresolved=impact,
        priority=priority,
        certainty=Certainty.EXPERT_CONFIRMATION_REQUIRED,
        status=ExpertQuestionStatus.OPEN,
        source_evidence=evidence or [],
    )


def build_all_contracts() -> list[DomainWorkflowContract]:
    return [
        _data_import(),
        _well_log_ingest(),
        _well_log_visualization(),
        _well_correlation(),
        _seismic_volume(),
        _horizon_interpretation(),
        _fault_interpretation(),
        _factor_interpolation(),
        _facies_prediction(),
        _paleomap_compile(),
        _quality_control(),
        _export(),
        _well_seismic_joint(),
        _geomodel_3d(),
    ]


def _data_import() -> DomainWorkflowContract:
    mid = "data_import"
    return DomainWorkflowContract(
        id=mid,
        name="Data import / data check",
        name_zh="数据导入与检查",
        category="data",
        description="Register local resources as RAW catalog inputs.",
        description_zh="将本地井/震/层位等资源登记为目录 RAW 版本。",
        implementation_status=ImplementationStatus.PRODUCTION,
        entry_points=[
            "paleo_workbench.ui.pages.data_page",
            "paleo_workbench.catalog.lifecycle.register_resource_input",
        ],
        inputs=[
            WorkflowInputSpec(
                id="source_files",
                name="源文件",
                description="磁盘上的井/震/层位等文件",
                resource_types=["well_log", "seismic", "horizon"],
                accepted_formats=["las", "sgy", "segy", "npy", "npz", "csv"],
                cardinality=InputCardinality.ONE_OR_MORE,
                required=True,
                version_semantics=InputVersionSemantics.RAW_ONLY,
                role=InputRole.PRIMARY,
                software_validation="path exists; type classifier; optional checksum",
                source_evidence=[
                    _ev(
                        "paleo_workbench.catalog.lifecycle",
                        "register_resource_input",
                    ),
                    _ev("paleo_workbench.project.models", "ResourceItem"),
                ],
            )
        ],
        operations=[
            WorkflowOperationStep(
                id="import_register",
                name="导入并登记",
                user_action="选择文件并导入工程",
                software_action="创建 ResourceItem；register_input 为 RAW DataVersion；legacy bridge",
                executor_ref="paleo_workbench.catalog.lifecycle.register_resource_input",
                source_evidence=[
                    _ev(
                        "paleo_workbench.catalog.lifecycle",
                        "register_resource_input",
                    )
                ],
            )
        ],
        outputs=[
            WorkflowOutputSpec(
                id="raw_versions",
                name="RAW 数据版本",
                asset_kind="varies",
                data_stage="raw",
                versioned=True,
                persistent=True,
                scientific_meaning="不可变原始输入快照（托管）或外部链接",
                output_class="scientific",
                downstream_usage=[
                    "well_log_visualization",
                    "seismic_volume",
                    "horizon_interpretation",
                    "factor_interpolation",
                ],
                source_evidence=[
                    _ev("paleo_workbench.catalog.models", "DataStage.RAW")
                ],
            )
        ],
        qc_rules=[
            WorkflowQCSpec(
                id="resource_present",
                name="资源列表非空",
                severity=QCSeverity.INFORMATION,
                implemented=True,
                implementation_ref="paleo_workbench.workflow.service.infer_workflow_step_status",
                check_type="presence",
            )
        ],
        upstream_contract_ids=[],
        downstream_contract_ids=[
            "well_log_ingest",
            "seismic_volume",
            "horizon_interpretation",
            "factor_interpolation",
        ],
        datarun_operations=[],
        workflow_step_types=["data_check"],
        expert_questions=[
            _q(
                "eq-data-mixed-domain",
                mid,
                ExpertQuestionCategory.DATA_QUALITY,
                "工程同时导入时间域地震与深度域井数据时，是否必须在数据检查阶段声明统一垂直域（time/depth），"
                "还是允许混用并由后续模块各自处理？",
                "ResourceItem 仅有 type/format/path，无强制垂直域一致性校验。",
                "域混用会导致层位叠合与井震标定语义不清。",
                "后续解释/单因素/编图可能在错误域上计算而不被拦截。",
                evidence=[_ev("paleo_workbench.project.models", "ResourceItem")],
            )
        ],
        source_evidence=[
            _ev("paleo_workbench.workflow.service", "STEP_ORDER"),
            _ev("paleo_workbench.catalog.lifecycle", "migrate_project_resources"),
        ],
    )


def _well_log_ingest() -> DomainWorkflowContract:
    mid = "well_log_ingest"
    return DomainWorkflowContract(
        id=mid,
        name="Well-log ingestion",
        name_zh="测井数据接入",
        category="well_log",
        description="Load LAS/well tables into project resources.",
        description_zh="将 LAS 等测井曲线接入工程资源。",
        implementation_status=ImplementationStatus.PRODUCTION,
        entry_points=[
            "paleo_workbench.ui.pages.data_page",
            "paleo_workbench.workflow.well_table",
        ],
        inputs=[
            WorkflowInputSpec(
                id="las_files",
                name="LAS 测井文件",
                resource_types=["well_log"],
                accepted_formats=["las"],
                cardinality=InputCardinality.ONE_OR_MORE,
                required=True,
                version_semantics=InputVersionSemantics.RAW_ONLY,
                source_evidence=[
                    _ev("paleo_workbench.project.models", "ResourceItem.type")
                ],
            )
        ],
        operations=[
            WorkflowOperationStep(
                id="parse_las",
                name="解析 LAS",
                user_action="导入井文件",
                software_action="解析井头/曲线元数据并登记资源（非在此阶段物化全曲线到网格）",
                executor_ref="paleo_workbench.workflow.well_table",
            )
        ],
        outputs=[
            WorkflowOutputSpec(
                id="well_resource",
                name="井资源",
                data_stage="raw",
                versioned=True,
                persistent=True,
                output_class="scientific",
                downstream_usage=["well_log_visualization", "well_correlation", "factor_interpolation"],
            )
        ],
        qc_rules=[
            WorkflowQCSpec(
                id="well_type_tag",
                name="资源类型为 well_log",
                implemented=True,
                implementation_ref="paleo_workbench.pipeline.assets.bind_prediction_assets",
                severity=QCSeverity.HARD_GATE,
            )
        ],
        upstream_contract_ids=["data_import"],
        downstream_contract_ids=[
            "well_log_visualization",
            "well_correlation",
            "factor_interpolation",
            "facies_prediction",
        ],
        expert_questions=[
            _q(
                "eq-well-depth-datum",
                mid,
                ExpertQuestionCategory.INPUT,
                "多井进入对比或采样前，是否要求全部井统一到同一种深度基准（MD/TVD/TVDSS）？"
                "若不一致，应由软件自动转换还是在接入时强制校验拦截？",
                "当前可加载任意 LAS；未发现强制统一深度基准的硬门禁。",
                "深度基准混用会破坏对比与井点平面采样。",
                "地层对比与单因素采样坐标可能错误。",
                evidence=[_ev("paleo_workbench.workflow.stratigraphy_correlation")],
            )
        ],
    )


def _well_log_visualization() -> DomainWorkflowContract:
    mid = "well_log_visualization"
    return DomainWorkflowContract(
        id=mid,
        name="Well-log visualization",
        name_zh="测井曲线显示",
        category="well_log",
        description="Native multi-track well-log display; style is display-only.",
        description_zh="多道测井显示；道样式属于显示状态，不是科学成果版本。",
        implementation_status=ImplementationStatus.PRODUCTION,
        entry_points=[
            "paleo_workbench.ui.pages.well_log_prediction_page",
            "well-log-engine multi-track session",
        ],
        inputs=[
            WorkflowInputSpec(
                id="well_logs",
                name="已接入井",
                resource_types=["well_log"],
                cardinality=InputCardinality.ONE_OR_MORE,
                required=True,
                role=InputRole.PRIMARY,
            )
        ],
        parameters=[
            WorkflowParameterSpec(
                id="track_layout",
                name="道布局/颜色",
                category=ParameterCategory.DISPLAY,
                description="道宽、颜色、可见性等显示参数",
                certainty=Certainty.KNOWN_FROM_CODE,
            )
        ],
        operations=[
            WorkflowOperationStep(
                id="open_tracks",
                name="打开多道视图",
                user_action="选择井并配置道",
                software_action="加载曲线到 native multi-track 会话并渲染",
            )
        ],
        outputs=[
            WorkflowOutputSpec(
                id="track_view",
                name="道视图状态",
                versioned=False,
                persistent=False,
                output_class="visualization",
                scientific_meaning="显示状态，非 DataVersion",
                certainty=Certainty.KNOWN_FROM_CODE,
            )
        ],
        qc_rules=[],
        upstream_contract_ids=["well_log_ingest"],
        downstream_contract_ids=["well_correlation"],
        assumptions=["道样式变更不应使科学成果 STALE（与 Stage-4/9 显示分离原则一致）"],
        expert_questions=[
            _q(
                "eq-well-required-curves",
                mid,
                ExpertQuestionCategory.GEOLOGICAL_RULE,
                "岩相/单因素采样若依赖特定曲线（如 GR/RT），软件是否应强制曲线名映射表，"
                "还是允许用户任意选择曲线别名？",
                "曲线选择主要由 UI/会话配置决定，未编码全工程强制曲线集。",
                "影响单因素采样可重复性。",
                "不同工区曲线名不一致时结果不可比。",
                priority=ExpertQuestionPriority.P1,
                evidence=[
                    _ev("paleo_workbench.ui.pages.well_log_prediction_page"),
                    _ev("paleo_workbench.workflow.well_table"),
                ],
            )
        ],
    )


def _well_correlation() -> DomainWorkflowContract:
    mid = "well_correlation"
    return DomainWorkflowContract(
        id=mid,
        name="Well correlation / tops",
        name_zh="连井对比与分层",
        category="well_log",
        description=(
            "Multi-well correlation interpretation: FormationTop + CorrelationLink "
            "saved as immutable DERIVED JSON artifact with DataRun lineage."
        ),
        description_zh=(
            "多井连井对比：分层顶（FormationTop）与对比连接（CorrelationLink）"
            "保存为不可变 DERIVED JSON 成果，并登记 DataRun 血缘。"
        ),
        implementation_status=ImplementationStatus.PRODUCTION,
        entry_points=[
            "paleo_workbench.workflow.correlation_lifecycle",
            "paleo_workbench.workflow.stratigraphy_correlation",
            "paleo_workbench.catalog.lifecycle.register_stratigraphic_correlation_run",
        ],
        inputs=[
            WorkflowInputSpec(
                id="wells",
                name="参与对比的井",
                resource_types=["well_log"],
                cardinality=InputCardinality.ONE_OR_MORE,
                required=True,
                version_semantics=InputVersionSemantics.CURRENT_VERSION,
                source_evidence=[
                    _ev(
                        "paleo_workbench.workflow.stratigraphy_correlation",
                        "list_well_log_resources",
                    ),
                    _ev(
                        "paleo_workbench.workflow.stratigraphy_models",
                        "CorrelationScientificPayload.well_version_ids",
                    ),
                ],
            )
        ],
        parameters=[
            WorkflowParameterSpec(
                id="depth_domain",
                name="深度域",
                category=ParameterCategory.SCIENTIFIC,
                description="MD/TVD/TVDSS/TWT/DEPTH/TIME — 仅声明，无自动转换",
                certainty=Certainty.KNOWN_FROM_CODE,
                expert_question_id="eq-corr-datum",
                source_evidence=[
                    _ev(
                        "paleo_workbench.workflow.stratigraphy_models",
                        "DepthDomain",
                    )
                ],
            ),
            WorkflowParameterSpec(
                id="viewport",
                name="视口/缩放",
                category=ParameterCategory.DISPLAY,
                description="不写入科学指纹",
            ),
        ],
        operations=[
            WorkflowOperationStep(
                id="edit_tops_links",
                name="编辑分层与连接",
                user_action="选择井集，编辑 FormationTop 与 CorrelationLink，撤销/重做",
                software_action="维护 CorrelationInterpretationDraft（copy-on-edit）",
                executor_ref="paleo_workbench.workflow.correlation_lifecycle",
            ),
            WorkflowOperationStep(
                id="save_version",
                name="保存对比版本",
                user_action="保存连井对比解释版本",
                software_action=(
                    "写 .correlation.json；register_stratigraphic_correlation_run；"
                    "推进 CorrelationInterpretationRef.current_version_id；无变更则 noop"
                ),
                datarun_operation="stratigraphic_correlation",
                executor_ref="paleo_workbench.workflow.correlation_lifecycle.save_correlation_draft",
            ),
        ],
        outputs=[
            WorkflowOutputSpec(
                id="correlation_version",
                name="连井对比解释版本",
                asset_kind="stratigraphic_correlation",
                format="json",
                data_stage="derived",
                versioned=True,
                persistent=True,
                output_class="scientific",
                scientific_meaning="分层顶 + 对比连接 + 深度域 + 井版本 ID（不含曲线采样）",
                downstream_usage=["factor_interpolation", "horizon_interpretation"],
                certainty=Certainty.KNOWN_FROM_CODE,
            )
        ],
        qc_rules=[
            WorkflowQCSpec(
                id="depth_domain_consistent",
                name="对比内深度域一致性",
                implemented=True,
                implementation_ref="paleo_workbench.workflow.correlation_lifecycle.detect_depth_domain_mismatch",
                severity=QCSeverity.WARNING,
                expert_confirmation_required=True,
            )
        ],
        upstream_contract_ids=["well_log_ingest", "well_log_visualization"],
        downstream_contract_ids=["factor_interpolation", "horizon_interpretation"],
        datarun_operations=["stratigraphic_correlation"],
        expert_questions=[
            _q(
                "eq-corr-datum",
                mid,
                ExpertQuestionCategory.WORKFLOW,
                "连井对比是否要求先完成统一深度基准与曲线标准化，"
                "还是允许在原始 MD 上直接对比？软件当前仅检测域混用并告警，不自动转换。",
                "DepthDomain 显式声明；detect_depth_domain_mismatch 只报告混用；无 MD↔TVDSS 转换。",
                "决定对比成果是否可进入生产编图。",
                "对比顶面与地震时域层位无法对齐。",
                evidence=[
                    _ev("paleo_workbench.workflow.stratigraphy_models", "DepthDomain"),
                    _ev(
                        "paleo_workbench.workflow.correlation_lifecycle",
                        "detect_depth_domain_mismatch",
                    ),
                ],
            )
        ],
    )


def _seismic_volume() -> DomainWorkflowContract:
    mid = "seismic_volume"
    return DomainWorkflowContract(
        id=mid,
        name="Seismic volume access",
        name_zh="地震体接入与浏览",
        category="seismic",
        description="SEG-Y RAW + lazy SeismicVolumeSource; slices are display state.",
        description_zh="SEG-Y RAW 与惰性体访问；切片为显示状态，非自动成果版本。",
        implementation_status=ImplementationStatus.PRODUCTION,
        entry_points=[
            "paleo_workbench.viz.seismic_volume_source",
            "paleo_workbench.viz.source_backed_volume_access",
        ],
        inputs=[
            WorkflowInputSpec(
                id="segy",
                name="SEG-Y 地震体",
                resource_types=["seismic"],
                accepted_formats=["sgy", "segy"],
                cardinality=InputCardinality.EXACTLY_ONE,
                required=True,
                version_semantics=InputVersionSemantics.RAW_ONLY,
                role=InputRole.PRIMARY,
                source_evidence=[
                    _ev("paleo_workbench.viz.seismic_volume_source", "SeismicVolumeSource")
                ],
            )
        ],
        parameters=[
            WorkflowParameterSpec(
                id="slice_indices",
                name="Inline/Xline/Time 切片索引",
                category=ParameterCategory.DISPLAY,
                description="视口切片位置，不构成科学依赖",
            ),
            WorkflowParameterSpec(
                id="lod_level",
                name="LOD 预览级别",
                category=ParameterCategory.ALGORITHM,
                description="渐进加载预览层级",
            ),
        ],
        operations=[
            WorkflowOperationStep(
                id="open_volume",
                name="打开地震体",
                user_action="选择 SEG-Y 资源",
                software_action="建立 SeismicVolumeSource / SourceBackedVolumeAccess，按需读切片",
                executor_ref="paleo_workbench.viz.seismic_volume_source",
            )
        ],
        outputs=[
            WorkflowOutputSpec(
                id="volume_access",
                name="运行时体访问",
                versioned=False,
                persistent=False,
                output_class="visualization",
                scientific_meaning="访问句柄；RAW 文件仍是科学源",
            )
        ],
        qc_rules=[
            WorkflowQCSpec(
                id="geometry_present",
                name="体几何/采样间隔可读",
                implemented=True,
                severity=QCSeverity.HARD_GATE,
                implementation_ref="paleo_workbench.viz.seismic_volume_source",
            )
        ],
        upstream_contract_ids=["data_import"],
        downstream_contract_ids=[
            "horizon_interpretation",
            "well_seismic_joint",
            "facies_prediction",
        ],
        expert_questions=[
            _q(
                "eq-seismic-depth-convert",
                mid,
                ExpertQuestionCategory.GEOLOGICAL_RULE,
                "当工程需要深度域层位与时间域地震叠合时，深度转换应使用统一速度模型，"
                "还是允许每个层位/井采用独立速度关系？",
                "当前体访问以 sample interval、t0 与 survey geometry 建立时域访问为主；"
                "未见统一速度模型硬门禁。",
                "决定井震联合与层位解释的域一致性。",
                "时深不一致导致错误构造解释。",
                evidence=[
                    _ev("paleo_workbench.viz.seismic_volume_source"),
                    _ev("paleo_workbench.viz.interpretation_lifecycle"),
                ],
            )
        ],
    )


def _horizon_interpretation() -> DomainWorkflowContract:
    mid = "horizon_interpretation"
    return DomainWorkflowContract(
        id=mid,
        name="Horizon interpretation",
        name_zh="层位解释",
        category="interpretation",
        description="Draft → immutable DERIVED version; never mutates RAW.",
        description_zh="草稿→不可变 DERIVED 版本；禁止直接改写 RAW。",
        implementation_status=ImplementationStatus.PRODUCTION,
        entry_points=[
            "paleo_workbench.viz.interpretation_lifecycle",
            "paleo_workbench.catalog.lifecycle.register_horizon_interpretation_run",
        ],
        inputs=[
            WorkflowInputSpec(
                id="seismic_or_seed",
                name="地震/种子网格",
                resource_types=["seismic", "horizon"],
                cardinality=InputCardinality.ZERO_OR_MORE,
                required=False,
                role=InputRole.PRIMARY,
                version_semantics=InputVersionSemantics.EXPLICIT_SELECTED_VERSION,
            ),
            WorkflowInputSpec(
                id="parent_version",
                name="父解释版本",
                cardinality=InputCardinality.ZERO_OR_ONE,
                required=False,
                role=InputRole.REFERENCE,
                version_semantics=InputVersionSemantics.EXPLICIT_SELECTED_VERSION,
                current_version_required=False,
                source_evidence=[
                    _ev(
                        "paleo_workbench.project.models",
                        "HorizonInterpretationRef.parent_version_id",
                    )
                ],
            ),
        ],
        parameters=[
            WorkflowParameterSpec(
                id="display_style",
                name="显示颜色/透明度",
                category=ParameterCategory.DISPLAY,
                description="不参与 scientific_fingerprint",
            )
        ],
        operations=[
            WorkflowOperationStep(
                id="save_version",
                name="保存解释版本",
                user_action="编辑层位草稿并保存版本",
                software_action="写 .horizon_interp.npz；register DERIVED + DataRun",
                datarun_operation="horizon_interpretation",
                executor_ref="paleo_workbench.viz.interpretation_lifecycle.save_draft_as_new_version",
            )
        ],
        outputs=[
            WorkflowOutputSpec(
                id="horizon_version",
                name="层位解释版本",
                asset_kind="horizon_interpretation",
                format="npz",
                data_stage="derived",
                versioned=True,
                persistent=True,
                output_class="scientific",
                scientific_meaning="不可变 Z 网格解释成果",
                downstream_usage=["factor_interpolation", "geomodel_3d"],
                qc_required=False,
            )
        ],
        qc_rules=[],
        upstream_contract_ids=["seismic_volume", "data_import"],
        downstream_contract_ids=["factor_interpolation", "geomodel_3d", "paleomap_compile"],
        datarun_operations=["horizon_interpretation"],
        expert_questions=[
            _q(
                "eq-horizon-merge",
                mid,
                ExpertQuestionCategory.VERSIONING,
                "多人/多轮解释分支合并时，是否允许任意切换 current_version，"
                "还是必须基于科学审定流程锁定“官方层位”？",
                "HorizonInterpretationRef.current_version_id 可由工程指针切换；"
                "Stage-9 据此判定下游新鲜度。",
                "影响单因素/预测/编图失效范围。",
                "错误锁定导致大范围重算或使用过时构造面。",
                evidence=[
                    _ev(
                        "paleo_workbench.project.models",
                        "HorizonInterpretationRef.current_version_id",
                    ),
                    _ev(
                        "paleo_workbench.workflow.current_context",
                        "resolve_current_project_version_context",
                    ),
                ],
            )
        ],
        source_evidence=[
            _ev(
                "paleo_workbench.catalog.lifecycle",
                "register_horizon_interpretation_run",
            )
        ],
    )


def _fault_interpretation() -> DomainWorkflowContract:
    mid = "fault_interpretation"
    return DomainWorkflowContract(
        id=mid,
        name="Fault interpretation",
        name_zh="断层解释",
        category="interpretation",
        description=(
            "Versioned map-plane fault polylines (DERIVED JSON). "
            "ConstraintLine break remains a separate factor-constraint path. "
            "3D synthetic faults remain DEMO."
        ),
        description_zh=(
            "版本化平面断层折线（DERIVED JSON）。ConstraintLine break 仍服务插值约束。"
            "三维合成断层仍为演示路径。"
        ),
        implementation_status=ImplementationStatus.PARTIAL,
        entry_points=[
            "paleo_workbench.workflow.fault_lifecycle",
            "paleo_workbench.catalog.lifecycle.register_fault_interpretation_run",
            "paleo_workbench.project.models.ConstraintLine",
        ],
        inputs=[
            WorkflowInputSpec(
                id="fault_polylines",
                name="断层折线（工程 CRS）",
                cardinality=InputCardinality.ZERO_OR_MORE,
                required=False,
                role=InputRole.PRIMARY,
                source_evidence=[
                    _ev(
                        "paleo_workbench.workflow.stratigraphy_models",
                        "FaultTrace",
                    )
                ],
            )
        ],
        operations=[
            WorkflowOperationStep(
                id="edit_fault",
                name="编辑断层轨迹",
                user_action="绘制/导入断层折线到工作副本",
                software_action="维护 FaultInterpretationDraft（copy-on-edit）",
            ),
            WorkflowOperationStep(
                id="save_fault_version",
                name="保存断层版本",
                user_action="保存断层解释版本",
                software_action="写 .fault_interp.json；register_fault_interpretation_run",
                datarun_operation="fault_interpretation",
                executor_ref="paleo_workbench.workflow.fault_lifecycle.save_fault_draft",
            ),
        ],
        outputs=[
            WorkflowOutputSpec(
                id="fault_version",
                name="断层解释版本",
                asset_kind="fault_interpretation",
                format="json",
                data_stage="derived",
                versioned=True,
                persistent=True,
                output_class="scientific",
                scientific_meaning="工程 CRS 下的断层折线（非屏幕坐标；非完整断距模型）",
                downstream_usage=["factor_interpolation"],
            )
        ],
        upstream_contract_ids=["data_import", "seismic_volume"],
        downstream_contract_ids=["factor_interpolation"],
        datarun_operations=["fault_interpretation"],
        expert_questions=[
            _q(
                "eq-fault-throw",
                mid,
                ExpertQuestionCategory.GEOLOGICAL_RULE,
                "单因素插值是否必须使用带断距的三维断层模型，"
                "还是平面 break/fault 折线已满足当前编图规范？",
                "FaultTrace 为平面折线；ConstraintLine break 参与 IDW；无断距场硬门禁。",
                "决定构造复杂区单因素是否合格。",
                "隔挡效果可能不符合地质规范。",
                evidence=[
                    _ev("paleo_workbench.workflow.stratigraphy_models", "FaultTrace"),
                    _ev("paleo_workbench.project.models", "ConstraintLine.role"),
                ],
            )
        ],
    )


def _factor_interpolation() -> DomainWorkflowContract:
    mid = "factor_interpolation"
    return DomainWorkflowContract(
        id=mid,
        name="Factor map interpolation",
        name_zh="单因素图插值",
        category="factor",
        description="Interpolate well/sample points to FactorGrid with scientific fingerprints.",
        description_zh="井点/样点插值为单因素网格；科学指纹驱动增量重算。",
        implementation_status=ImplementationStatus.PRODUCTION,
        entry_points=[
            "paleo_workbench.workflow.factor_interpolation",
            "paleo_workbench.workflow.factor_prepare_scheduler",
            "paleo_workbench.catalog.lifecycle.register_factor_map_run",
        ],
        inputs=[
            WorkflowInputSpec(
                id="sample_points",
                name="样点/井点数值",
                cardinality=InputCardinality.ONE_OR_MORE,
                required=True,
                role=InputRole.PRIMARY,
                scientific_constraints="parameters.sample_points 含 x,y,value",
                source_evidence=[
                    _ev("paleo_workbench.project.models", "FactorMapTask.parameters")
                ],
            ),
            WorkflowInputSpec(
                id="target_horizon",
                name="目标层位",
                # Not resource_types: code uses FactorMapTask.target_horizon string;
                # versioned horizon interpretation is optional/enhancement (see expert Q).
                cardinality=InputCardinality.EXACTLY_ONE,
                required=True,
                role=InputRole.PRIMARY,
                version_semantics=InputVersionSemantics.CURRENT_VERSION,
                current_version_required=False,
                software_validation="FactorMapTask.target_horizon 非空字符串",
                source_evidence=[
                    _ev("paleo_workbench.project.models", "FactorMapTask.target_horizon")
                ],
                expert_question_ids=["eq-factor-horizon-req"],
            ),
            WorkflowInputSpec(
                id="constraints",
                name="断层/方向约束",
                cardinality=InputCardinality.ZERO_OR_MORE,
                required=False,
                role=InputRole.CONSTRAINT,
            ),
            WorkflowInputSpec(
                id="input_resources",
                name="输入资源 ID",
                resource_types=["well_log", "horizon"],
                cardinality=InputCardinality.ZERO_OR_MORE,
                required=False,
                source_evidence=[
                    _ev(
                        "paleo_workbench.project.models",
                        "FactorMapTask.input_resource_ids",
                    )
                ],
            ),
        ],
        parameters=[
            WorkflowParameterSpec(
                id="method",
                name="插值方法",
                category=ParameterCategory.ALGORITHM,
                required=True,
                default="IDW",
                source_evidence=[
                    _ev("paleo_workbench.project.models", "FactorMapTask.method")
                ],
            ),
            WorkflowParameterSpec(
                id="power",
                name="IDW 幂次",
                category=ParameterCategory.ALGORITHM,
                value_type="float",
                certainty=Certainty.KNOWN_FROM_CODE,
                expert_question_id="eq-factor-idw-power",
            ),
            WorkflowParameterSpec(
                id="grid_n",
                name="网格分辨率",
                category=ParameterCategory.ALGORITHM,
                value_type="int",
            ),
            WorkflowParameterSpec(
                id="colormap",
                name="色标",
                category=ParameterCategory.DISPLAY,
            ),
        ],
        operations=[
            WorkflowOperationStep(
                id="interpolate",
                name="执行插值",
                user_action="选择目标层位并设置插值参数",
                software_action="读取样点/约束并执行 IDW/克里金/约束 IDW；写 FactorGrid 工件",
                datarun_operation="factor_map",
                executor_ref="paleo_workbench.workflow.factor_interpolation.apply_interpolation_to_task",
                blocking_requirements=["target_horizon", "sample_points"],
            )
        ],
        outputs=[
            WorkflowOutputSpec(
                id="factor_grid",
                name="单因素网格",
                asset_kind="factor_map_grid",
                format="npz",
                data_stage="intermediate",
                versioned=True,
                persistent=True,
                output_class="intermediate",
                scientific_meaning="数值网格 INTERMEDIATE 成果",
                downstream_usage=["facies_prediction", "paleomap_compile"],
                qc_required=False,
                source_evidence=[
                    _ev(
                        "paleo_workbench.catalog.lifecycle",
                        "register_factor_map_run",
                    )
                ],
            )
        ],
        qc_rules=[
            WorkflowQCSpec(
                id="fingerprint_clean",
                name="科学指纹 CLEAN",
                implemented=True,
                implementation_ref="paleo_workbench.workflow.interpolation_fingerprint",
                severity=QCSeverity.WARNING,
            )
        ],
        upstream_contract_ids=[
            "well_log_ingest",
            "horizon_interpretation",
            "fault_interpretation",
            "data_import",
        ],
        downstream_contract_ids=["facies_prediction", "paleomap_compile"],
        datarun_operations=["factor_map"],
        workflow_step_types=["factor_map"],
        assumptions=[
            "source_kind 可为 mock；不得将 mock 任务报告为生产完成而不标注",
        ],
        expert_questions=[
            _q(
                "eq-factor-horizon-req",
                mid,
                ExpertQuestionCategory.INPUT,
                "单因素插值是否必须绑定已版本化的层位解释面，"
                "还是仅字符串 target_horizon 名称即可（无几何约束）？",
                "FactorMapTask.target_horizon 为字符串；层位版本仅在 register 时可选并入 input_version_ids。",
                "决定构造控制是否进入科学依赖。",
                "无几何层位时网格空间意义存疑。",
                evidence=[
                    _ev("paleo_workbench.project.models", "FactorMapTask.target_horizon"),
                    _ev(
                        "paleo_workbench.catalog.lifecycle",
                        "register_factor_map_run",
                    ),
                ],
            ),
            _q(
                "eq-factor-idw-power",
                mid,
                ExpertQuestionCategory.PARAMETER,
                "IDW power / 搜索半径等默认值应为固定标准、按工区配置，还是每次任务由用户设置？",
                "算法参数来自任务 parameters 与插值指纹；无全库地质标准表。",
                "影响成果可对比性与规范符合性。",
                "不同项目不可横向对比。",
                priority=ExpertQuestionPriority.P1,
                evidence=[
                    _ev(
                        "paleo_workbench.workflow.interpolation_fingerprint",
                        "build_factor_fingerprints",
                    )
                ],
            ),
        ],
    )


def _facies_prediction() -> DomainWorkflowContract:
    mid = "facies_prediction"
    return DomainWorkflowContract(
        id=mid,
        name="Facies / seismic prediction",
        name_zh="相/地震预测",
        category="prediction",
        description="PredictionTask via mock or local adapters; default adapter is mock.",
        description_zh="通过 mock/local 适配器运行预测；默认 adapter_kind=mock。",
        implementation_status=ImplementationStatus.DEMO,  # default path is mock
        entry_points=[
            "paleo_workbench.prediction.adapters",
            "paleo_workbench.pipeline.assets.bind_prediction_assets",
            "paleo_workbench.catalog.lifecycle.register_prediction_run",
        ],
        inputs=[
            WorkflowInputSpec(
                id="factor_maps",
                name="单因素图任务",
                cardinality=InputCardinality.ZERO_OR_MORE,
                required=False,
                role=InputRole.PRIMARY,
                source_evidence=[
                    _ev(
                        "paleo_workbench.project.models",
                        "PredictionTask.input_factor_map_ids",
                    )
                ],
            ),
            WorkflowInputSpec(
                id="well_refs",
                name="井资源引用",
                resource_types=["well_log"],
                cardinality=InputCardinality.ZERO_OR_MORE,
                required=False,
                role=InputRole.CALIBRATION,
                source_evidence=[
                    _ev(
                        "paleo_workbench.pipeline.assets",
                        "WELL_KEY well_log_resource_ids",
                    )
                ],
            ),
            WorkflowInputSpec(
                id="seismic_refs",
                name="地震资源引用",
                resource_types=["seismic"],
                cardinality=InputCardinality.ZERO_OR_ONE,
                required=False,
                role=InputRole.OPTIONAL_CONTEXT,
                source_evidence=[
                    _ev(
                        "paleo_workbench.pipeline.assets",
                        "SEISMIC_KEY seismic_resource_ids",
                    )
                ],
            ),
        ],
        parameters=[
            WorkflowParameterSpec(
                id="adapter_kind",
                name="适配器类型",
                category=ParameterCategory.ALGORITHM,
                default="mock",
                source_evidence=[
                    _ev("paleo_workbench.project.models", "PredictionTask.adapter_kind")
                ],
            ),
            WorkflowParameterSpec(
                id="model_metadata",
                name="模型元数据",
                category=ParameterCategory.SCIENTIFIC,
                certainty=Certainty.INFERRED,
                expert_question_id="eq-pred-model-gate",
            ),
        ],
        operations=[
            WorkflowOperationStep(
                id="run_prediction",
                name="运行预测",
                user_action="选择因素/井震输入并启动预测",
                software_action="Mock 或 Local 适配器生成 result_summary；登记 prediction DataRun",
                datarun_operation="prediction",
                executor_ref="paleo_workbench.prediction.adapters",
            )
        ],
        outputs=[
            WorkflowOutputSpec(
                id="prediction_result",
                name="预测结果摘要",
                data_stage="derived",
                versioned=True,
                persistent=False,
                output_class="scientific",
                scientific_meaning="相概率/摘要（常驻任务内存；可选文件 DERIVED）",
                downstream_usage=["paleomap_compile", "export"],
                certainty=Certainty.KNOWN_FROM_CODE,
            )
        ],
        qc_rules=[
            WorkflowQCSpec(
                id="not_mock_for_delivery",
                name="交付前不得使用 mock 适配器",
                severity=QCSeverity.HARD_GATE,
                implemented=False,
                expert_confirmation_required=True,
                certainty=Certainty.EXPERT_CONFIRMATION_REQUIRED,
                description="软件未强制禁止 mock 进入导出",
            )
        ],
        upstream_contract_ids=[
            "factor_interpolation",
            "well_log_ingest",
            "seismic_volume",
        ],
        downstream_contract_ids=["paleomap_compile", "quality_control", "export"],
        datarun_operations=["prediction"],
        workflow_step_types=["prediction"],
        assumptions=[
            "MockPredictionAdapter 可在无因素时仍生成任务（ensure_demo_prediction）",
        ],
        expert_questions=[
            _q(
                "eq-pred-model-gate",
                mid,
                ExpertQuestionCategory.QC,
                "进入古地理编图/导出前，是否必须使用 status=production 的注册模型版本，"
                "并禁止 mock/demo 适配器结果作为正式成果？",
                "PredictionTask.adapter_kind 默认为 mock；ensure_demo_prediction 可创建 mock 任务。"
                "模型注册表存在但非强制门禁。",
                "防止演示结果被当作生产交付。",
                "交付包可能混入不可复现的 mock 输出。",
                evidence=[
                    _ev("paleo_workbench.prediction.adapters", "MockPredictionAdapter"),
                    _ev("paleo_workbench.pipeline.assets", "ensure_demo_prediction"),
                    _ev("paleo_workbench.catalog.models", "Model.status"),
                ],
            )
        ],
    )


def _paleomap_compile() -> DomainWorkflowContract:
    mid = "paleomap_compile"
    return DomainWorkflowContract(
        id=mid,
        name="Paleomap compilation",
        name_zh="古地理图编绘",
        category="mapping",
        description="PaleoMapDocument authoring; demo compile isolated from production spatial compile.",
        description_zh="古地理图文档编制；演示编译与生产空间编图隔离。",
        implementation_status=ImplementationStatus.PARTIAL,
        entry_points=[
            "paleo_workbench.pipeline.compile_map",
            "paleo_workbench.pipeline.compile_map_production",
            "paleo_workbench.ui.pages.mapping_page",
        ],
        inputs=[
            WorkflowInputSpec(
                id="target_horizon",
                name="目标层位名",
                cardinality=InputCardinality.EXACTLY_ONE,
                required=True,
                role=InputRole.PRIMARY,
            ),
            WorkflowInputSpec(
                id="prediction_or_factors",
                name="预测/单因素成果",
                cardinality=InputCardinality.ZERO_OR_MORE,
                required=False,
                role=InputRole.PRIMARY,
                certainty=Certainty.INFERRED,
            ),
        ],
        operations=[
            WorkflowOperationStep(
                id="compile",
                name="编绘/编译草图",
                user_action="在制图工作台编辑相多边形/等值线并保存",
                software_action=(
                    "生产路径：compile_map_production 消费 VECTOR_POLYGONS；"
                    "演示路径：compile_map_draft（固定方块，is_demo_draft）"
                ),
                datarun_operation="map_compile",
                executor_ref="paleo_workbench.pipeline.compile_map_production.compile_map_production",
            )
        ],
        outputs=[
            WorkflowOutputSpec(
                id="paleomap",
                name="古地理图文档",
                data_stage="derived",
                versioned=False,
                persistent=True,
                output_class="scientific",
                scientific_meaning="相带多边形与图件文档（目录版本化可选）",
                downstream_usage=["quality_control", "export"],
            )
        ],
        qc_rules=[
            WorkflowQCSpec(
                id="polygons_present",
                name="相多边形存在",
                implemented=True,
                implementation_ref="paleo_workbench.workflow.qc",
                severity=QCSeverity.WARNING,
            )
        ],
        upstream_contract_ids=["facies_prediction", "factor_interpolation", "horizon_interpretation"],
        downstream_contract_ids=["quality_control", "export"],
        datarun_operations=["map_compile"],
        workflow_step_types=["map_compile"],
        expert_questions=[
            _q(
                "eq-map-facies-ontology",
                mid,
                ExpertQuestionCategory.GEOLOGICAL_RULE,
                "相带多边形的相代码体系应由行业标准固定、按盆地配置，还是完全自由文本？",
                "facies_polygons 为文档内字典结构；未见强制相代码表。",
                "影响成果交换与统计。",
                "跨项目相名不可比。",
                priority=ExpertQuestionPriority.P1,
                evidence=[_ev("paleo_workbench.project.models", "PaleoMapDocument")],
            )
        ],
    )


def _quality_control() -> DomainWorkflowContract:
    mid = "quality_control"
    return DomainWorkflowContract(
        id=mid,
        name="Map quality control",
        name_zh="成图质量检查",
        category="qc",
        description="Basic QC rules on paleomap documents.",
        description_zh="对古地理图文档执行基础 QC 规则。",
        implementation_status=ImplementationStatus.PARTIAL,
        entry_points=["paleo_workbench.workflow.qc"],
        inputs=[
            WorkflowInputSpec(
                id="map_document",
                name="古地理图文档",
                cardinality=InputCardinality.EXACTLY_ONE,
                required=True,
                version_semantics=InputVersionSemantics.EXPLICIT_SELECTED_VERSION,
            )
        ],
        operations=[
            WorkflowOperationStep(
                id="run_qc",
                name="运行基础 QC",
                user_action="对当前图件发起质检",
                software_action="按 BASIC_QC_RULES 生成 QualityReport",
                datarun_operation="qc",
                executor_ref="paleo_workbench.workflow.qc.run_basic_qc",
            )
        ],
        outputs=[
            WorkflowOutputSpec(
                id="quality_report",
                name="质检报告",
                data_stage="output",
                versioned=False,
                persistent=True,
                output_class="export",
                scientific_meaning="问题列表与状态（warning/failed/complete）",
            )
        ],
        qc_rules=[
            WorkflowQCSpec(
                id=rule,
                name=rule,
                implemented=True,
                implementation_ref="paleo_workbench.workflow.qc.BASIC_QC_RULES",
                severity=QCSeverity.WARNING,
            )
            for rule in (
                "target_horizon_present",
                "facies_polygons_present",
                "facies_geometry_valid",
                "well_overlays_present",
                "contour_lines_present",
                "well_table_qc_clean",
            )
        ],
        upstream_contract_ids=["paleomap_compile"],
        downstream_contract_ids=["export"],
        datarun_operations=["qc"],
        workflow_step_types=["qc"],
        expert_questions=[
            _q(
                "eq-qc-hard-gates",
                mid,
                ExpertQuestionCategory.QC,
                "哪些 QC 规则必须作为 HARD_GATE 阻止导出（例如无相多边形、几何自交），"
                "哪些仅 WARNING 可带病交付？",
                "多数基础规则为 warning/error 写入报告；导出未统一强制门禁。",
                "决定交付质量底线。",
                "不合格图件可能仍被导出。",
                evidence=[
                    _ev("paleo_workbench.workflow.qc", "BASIC_QC_RULES"),
                    _ev("paleo_workbench.workflow.qc", "run_basic_qc"),
                ],
            )
        ],
    )


def _export() -> DomainWorkflowContract:
    mid = "export"
    return DomainWorkflowContract(
        id=mid,
        name="Result export",
        name_zh="成果导出",
        category="export",
        description="Export artifacts registered as OUTPUT with lineage.",
        description_zh="导出文件登记为 OUTPUT 并保留来源 lineage。",
        implementation_status=ImplementationStatus.PRODUCTION,
        entry_points=[
            "paleo_workbench.project.artifacts.record_export",
            "paleo_workbench.catalog.lifecycle.register_export_output",
        ],
        inputs=[
            WorkflowInputSpec(
                id="source_products",
                name="来源任务/版本",
                cardinality=InputCardinality.ZERO_OR_MORE,
                required=False,
                role=InputRole.PRIMARY,
                source_evidence=[
                    _ev("paleo_workbench.project.models", "ExportArtifact.source_task_ids")
                ],
            )
        ],
        operations=[
            WorkflowOperationStep(
                id="export_file",
                name="写出导出文件",
                user_action="选择格式并导出",
                software_action="写文件；register_export_output 为 OUTPUT DataVersion",
                datarun_operation="export",
            )
        ],
        outputs=[
            WorkflowOutputSpec(
                id="export_artifact",
                name="导出文件",
                data_stage="output",
                versioned=True,
                persistent=True,
                output_class="export",
                format="geojson/png/pdf/...",
            )
        ],
        qc_rules=[
            WorkflowQCSpec(
                id="checksum",
                name="导出校验和",
                implemented=True,
                implementation_ref="paleo_workbench.catalog.lifecycle.register_export_output",
                severity=QCSeverity.INFORMATION,
            )
        ],
        upstream_contract_ids=["quality_control", "paleomap_compile", "facies_prediction"],
        downstream_contract_ids=[],
        datarun_operations=["export"],
        workflow_step_types=["export"],
        expert_questions=[
            _q(
                "eq-export-package",
                mid,
                ExpertQuestionCategory.OUTPUT,
                "正式归档是否要求固定包结构（图件+报告+输入版本清单+模型版本），"
                "还是允许单文件导出即可？",
                "ExportArtifact 记录路径/格式/linked_id/source_task_ids；无强制归档包。",
                "影响成果可追溯交付。",
                "无法复现导出时的完整输入集。",
                priority=ExpertQuestionPriority.P1,
                evidence=[_ev("paleo_workbench.project.models", "ExportArtifact")],
            )
        ],
    )


def _well_seismic_joint() -> DomainWorkflowContract:
    mid = "well_seismic_joint"
    return DomainWorkflowContract(
        id=mid,
        name="Well-seismic joint view",
        name_zh="井震联合显示",
        category="joint",
        description="Progressive joint 3D / fence views over seismic + wells.",
        description_zh="井震联合三维/剖面显示（运行时场景为主）。",
        implementation_status=ImplementationStatus.PARTIAL,
        entry_points=[
            "paleo_workbench.ui.pages.well_seismic_joint_page",
            "paleo_workbench.viz.joint_host",
        ],
        inputs=[
            WorkflowInputSpec(
                id="seismic",
                name="地震体",
                resource_types=["seismic"],
                cardinality=InputCardinality.EXACTLY_ONE,
                required=True,
            ),
            WorkflowInputSpec(
                id="wells",
                name="井",
                resource_types=["well_log"],
                cardinality=InputCardinality.ZERO_OR_MORE,
                required=False,
            ),
        ],
        operations=[
            WorkflowOperationStep(
                id="open_joint",
                name="打开联合场景",
                user_action="选择地震与井并进入联合视口",
                software_action="SourceBackedVolumeAccess 渐进加载 + 井轨迹叠合",
            )
        ],
        outputs=[
            WorkflowOutputSpec(
                id="joint_scene",
                name="联合场景",
                versioned=False,
                persistent=False,
                output_class="visualization",
            )
        ],
        upstream_contract_ids=["seismic_volume", "well_log_ingest"],
        downstream_contract_ids=["horizon_interpretation"],
        expert_questions=[
            _q(
                "eq-joint-tie-tol",
                mid,
                ExpertQuestionCategory.DATA_QUALITY,
                "井震标定残差超过多少毫秒/米应判定为不合格配准？",
                "联合视口可显示井震；未见统一残差 HARD_GATE 数值标准。",
                "决定解释前数据是否可用。",
                "错位标定导致错误层位。",
                priority=ExpertQuestionPriority.P1,
                evidence=[
                    _ev("paleo_workbench.ui.pages.well_seismic_joint_page"),
                    _ev("paleo_workbench.viz.joint_host"),
                ],
            )
        ],
    )


def _geomodel_3d() -> DomainWorkflowContract:
    mid = "geomodel_3d"
    return DomainWorkflowContract(
        id=mid,
        name="3D geological modeling view",
        name_zh="三维地质建模/场景",
        category="modeling",
        description="3D geological workers; often synthetic/demo — must not claim production.",
        description_zh="三维地质场景/建模 worker；常见 synthetic/demo，不得标为生产级。",
        implementation_status=ImplementationStatus.DEMO,
        entry_points=[
            "paleo_workbench.ui.pages.geological_modeling_3d_page",
            "paleo_workbench.catalog.lifecycle.register_modeling_run",
        ],
        inputs=[
            WorkflowInputSpec(
                id="surfaces",
                name="层面/解释",
                cardinality=InputCardinality.ZERO_OR_MORE,
                required=False,
            )
        ],
        operations=[
            WorkflowOperationStep(
                id="build_scene",
                name="构建三维场景",
                user_action="启动三维建模/场景",
                software_action="worker 生成场景；demo 路径 parameters.demo=true",
                datarun_operation="modeling",
                executor_ref="paleo_workbench.catalog.lifecycle.register_modeling_run",
            )
        ],
        outputs=[
            WorkflowOutputSpec(
                id="geomodel",
                name="三维模型/场景",
                data_stage="derived",
                versioned=False,
                persistent=False,
                output_class="visualization",
                scientific_meaning="多数路径为演示/合成；真实数据路径 PARTIAL",
                certainty=Certainty.KNOWN_FROM_CODE,
            )
        ],
        upstream_contract_ids=["horizon_interpretation", "seismic_volume"],
        downstream_contract_ids=[],
        datarun_operations=["modeling"],
        expert_questions=[
            _q(
                "eq-model-validation",
                mid,
                ExpertQuestionCategory.QC,
                "何种条件下三维地质模型可从 DEMO 升级为 PRODUCTION 交付"
                "（数据来源、闭合差、井点符合率）？",
                "register_modeling_run 记录 source/demo 参数；合成路径可不带输出版本。",
                "防止演示模型被当作正式构造模型。",
                "错误构造决策。",
                evidence=[
                    _ev(
                        "paleo_workbench.catalog.lifecycle",
                        "register_modeling_run",
                    )
                ],
            )
        ],
    )
