from app.db.models.enums import AgentCommandType

# Which human permission (see app/domain/permissions.py) is required to
# submit each structured command type. Administrator's "*" always passes;
# this only matters for Operator/Viewer.
COMMAND_TYPE_PERMISSIONS: dict[AgentCommandType, str] = {
    AgentCommandType.INSPECT_HOST: "view",
    AgentCommandType.VALIDATE_APP: "view",
    AgentCommandType.INSPECT_INSTANCE: "view",
    AgentCommandType.COLLECT_LOGS: "view",
    AgentCommandType.COLLECT_METRICS: "view",
    AgentCommandType.DEPLOY_RELEASE: "deploy",
    AgentCommandType.UPDATE_PROXY: "deploy",
    AgentCommandType.START_INSTANCE: "scale",
    AgentCommandType.STOP_INSTANCE: "stop",
    AgentCommandType.RESTART_INSTANCE: "restart",
}


def permission_for(command_type: AgentCommandType) -> str:
    return COMMAND_TYPE_PERMISSIONS[command_type]
