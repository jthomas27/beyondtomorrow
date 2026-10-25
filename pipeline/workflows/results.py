"""Explicit workflow outcomes shared by CLI, email jobs and notifications."""
from typing import Literal, TypedDict


class WorkflowResult(TypedDict, total=False):
    status: Literal['complete', 'published', 'partial', 'failed']
    published_url: str
    ghost_post_id: str
    failed_stages: list[str]
    run_log: object
    total_elapsed_s: float


def failed_stages(run_log) -> list[str]:
    return [stage['stage'] for stage in run_log.summary().get('stages', [])
            if stage.get('status') == 'error'] if run_log else []


def exit_code(result) -> int:
    if isinstance(result, dict):
        if result.get('status') == 'partial':
            return 2
        if result.get('status') == 'failed':
            return 1
    return 0
