from paleo_workbench.ui.pages import activity_card, completeness_card, resource_summary
from paleo_workbench.workflow.service import REQUIRED_RESOURCE_TYPES, STEP_ORDER


def test_step_types_reuse_workflow_step_order():
    assert activity_card.STEP_TYPES is STEP_ORDER


def test_resource_types_reuse_workflow_required_types():
    assert resource_summary.RESOURCE_TYPES is REQUIRED_RESOURCE_TYPES
    assert completeness_card.RESOURCE_TYPES is REQUIRED_RESOURCE_TYPES
