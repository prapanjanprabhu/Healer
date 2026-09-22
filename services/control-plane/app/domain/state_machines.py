"""Allowed state transitions for entities with an explicit status field.

Each table maps a current state to the set of states it may legally move to.
A state absent from a table's keys, or mapped to an empty set, is terminal.
"""

from app.db.models.enums import AgentCommandStatus, DeploymentStatus, InstanceStatus


class InvalidTransition(ValueError):
    def __init__(self, current: object, target: object):
        super().__init__(f"cannot transition from {current!r} to {target!r}")
        self.current = current
        self.target = target


DEPLOYMENT_TRANSITIONS: dict[DeploymentStatus, set[DeploymentStatus]] = {
    DeploymentStatus.PENDING: {DeploymentStatus.IN_PROGRESS, DeploymentStatus.FAILED},
    DeploymentStatus.IN_PROGRESS: {DeploymentStatus.SUCCEEDED, DeploymentStatus.FAILED},
    DeploymentStatus.SUCCEEDED: {DeploymentStatus.ROLLED_BACK},
    DeploymentStatus.FAILED: {DeploymentStatus.ROLLED_BACK},
    DeploymentStatus.ROLLED_BACK: set(),
}

INSTANCE_TRANSITIONS: dict[InstanceStatus, set[InstanceStatus]] = {
    InstanceStatus.PENDING: {InstanceStatus.STARTING, InstanceStatus.FAILED},
    InstanceStatus.STARTING: {InstanceStatus.RUNNING, InstanceStatus.FAILED},
    InstanceStatus.RUNNING: {InstanceStatus.UNHEALTHY, InstanceStatus.STOPPED},
    InstanceStatus.UNHEALTHY: {
        InstanceStatus.RUNNING,
        InstanceStatus.STOPPED,
        InstanceStatus.FAILED,
    },
    InstanceStatus.STOPPED: {InstanceStatus.STARTING},
    InstanceStatus.FAILED: {InstanceStatus.STARTING},
}

AGENT_COMMAND_TRANSITIONS: dict[AgentCommandStatus, set[AgentCommandStatus]] = {
    AgentCommandStatus.PENDING: {AgentCommandStatus.SENT, AgentCommandStatus.EXPIRED},
    AgentCommandStatus.SENT: {
        AgentCommandStatus.ACKNOWLEDGED,
        AgentCommandStatus.FAILED,
        AgentCommandStatus.TIMED_OUT,
    },
    AgentCommandStatus.ACKNOWLEDGED: {
        AgentCommandStatus.RUNNING,
        AgentCommandStatus.FAILED,
        AgentCommandStatus.TIMED_OUT,
    },
    AgentCommandStatus.RUNNING: {
        AgentCommandStatus.SUCCEEDED,
        AgentCommandStatus.FAILED,
        AgentCommandStatus.TIMED_OUT,
    },
    AgentCommandStatus.SUCCEEDED: set(),
    AgentCommandStatus.FAILED: set(),
    AgentCommandStatus.TIMED_OUT: set(),
    AgentCommandStatus.EXPIRED: set(),
}


def can_transition(transitions: dict, current: object, target: object) -> bool:
    if current == target:
        return False
    return target in transitions.get(current, set())


def require_transition(transitions: dict, current: object, target: object) -> None:
    if not can_transition(transitions, current, target):
        raise InvalidTransition(current, target)
