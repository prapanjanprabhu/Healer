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
    DEPLOY = "deploy"
    INSTANCE_START = "instance_start"
    INSTANCE_STOP = "instance_stop"
    INSTANCE_RESTART = "instance_restart"


class AgentCommandStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    ACKED = "acked"
    FAILED = "failed"
    EXPIRED = "expired"


class AdapterType(str, enum.Enum):
    WINDOWS_WAITRESS_SERVICE = "windows-waitress-service"
    LINUX_DOCKER = "linux-docker"


class SourceType(str, enum.Enum):
    GIT = "git"
    FOLDER = "folder"


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
