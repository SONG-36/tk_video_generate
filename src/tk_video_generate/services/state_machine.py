from __future__ import annotations

from tk_video_generate.enums import TaskStatus

ALLOWED_TRANSITIONS = {
    TaskStatus.QUEUED: {TaskStatus.SUBMITTING, TaskStatus.CANCELLED},
    TaskStatus.SUBMITTING: {TaskStatus.SUBMITTED, TaskStatus.FAILED},
    TaskStatus.SUBMITTED: {TaskStatus.POLLING, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.POLLING: {TaskStatus.POLLING, TaskStatus.DOWNLOADING, TaskStatus.FAILED},
    TaskStatus.DOWNLOADING: {TaskStatus.SUCCEEDED, TaskStatus.FAILED},
    TaskStatus.FAILED: {TaskStatus.QUEUED},
}


class InvalidStateTransitionError(ValueError):
    pass


def ensure_transition_allowed(current: TaskStatus, target: TaskStatus) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidStateTransitionError(
            f"Illegal task transition: {current.value} -> {target.value}"
        )
