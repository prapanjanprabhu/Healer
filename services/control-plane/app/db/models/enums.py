import enum


class ServerOS(str, enum.Enum):
    WINDOWS = "windows"
    LINUX = "linux"


class ServerStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    UNREACHABLE = "unreachable"
    DECOMMISSIONED = "decommissioned"


class AgentStatus(str, enum.Enum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    DEGRADED = "degraded"


class AgentCommandType(str, enum.Enum):
    """The only command types an Agent will ever execute — no arbitrary
    shell/command message exists anywhere in the protocol. See
    protocols/v1/command-envelope.schema.json.
    """

    INSPECT_HOST = "inspect_host"
    VALIDATE_APP = "validate_app"
    DEPLOY_RELEASE = "deploy_release"
    START_INSTANCE = "start_instance"
    STOP_INSTANCE = "stop_instance"
    RESTART_INSTANCE = "restart_instance"
    INSPECT_INSTANCE = "inspect_instance"
    COLLECT_LOGS = "collect_logs"
    COLLECT_METRICS = "collect_metrics"
    UPDATE_PROXY = "update_proxy"


class AgentCommandStatus(str, enum.Enum):
    PENDING = "pending"  # created, not yet sent (agent was offline)
    SENT = "sent"  # transmitted to the agent, awaiting acknowledgement
    ACKNOWLEDGED = "acknowledged"  # agent confirmed receipt
    RUNNING = "running"  # agent is executing it
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"  # expires_at passed with no terminal event
    EXPIRED = "expired"  # expires_at passed before ever being sent


class AdapterType(str, enum.Enum):
    WINDOWS_WAITRESS_SERVICE = "windows-waitress-service"
    LINUX_DOCKER = "linux-docker"


class SourceType(str, enum.Enum):
    GIT = "git"
    FOLDER = "folder"
    DOCKERFILE = "dockerfile"  # a folder/git checkout containing a Dockerfile
    IMAGE = "image"  # a pre-built image reference, no source code at all


class ReleaseStatus(str, enum.Enum):
    PENDING = "pending"
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"


class InstanceStatus(str, enum.Enum):
    PENDING = "pending"
    STARTING = "starting"
    RUNNING = "running"
    UNHEALTHY = "unhealthy"
    STOPPED = "stopped"
    FAILED = "failed"


class DeploymentStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class DeploymentStepStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class HealthCheckType(str, enum.Enum):
    HTTP = "http"
    TCP = "tcp"
