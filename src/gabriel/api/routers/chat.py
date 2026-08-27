from __future__ import annotations

from fastapi import APIRouter, Depends, status

from gabriel.api.dependencies import (
    GatewayService,
    build_command,
    get_chat_service,
    get_execution_context,
    get_gateway_service,
)
from gabriel.api.schema import ChatCreateRequest, ChatSummaryResponse, ResourceResponse
from gabriel.api.services.chat import ChatService
from gabriel.runtime.context import ExecutionContext

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/conversations", response_model=list[ChatSummaryResponse])
async def list_conversations(
    context: ExecutionContext = Depends(get_execution_context),
    service: ChatService = Depends(get_chat_service),
):
    return service.get_chat_summary(context.principal)


@router.post(
    "/conversations",
    response_model=ResourceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_chat(
    payload: ChatCreateRequest,
    context: ExecutionContext = Depends(get_execution_context),
    service: GatewayService = Depends(get_gateway_service),
) -> ResourceResponse:
    command = build_command(
        context,
        "new_chat",
        {
            "resource_type": "chat",
            "attributes": {
                "title": payload.title,
                "agentGRN": payload.agentGRN,
                "metadata": payload.metadata,
            },
        },
        action_name="chat:create",
    )
    events = await service.dispatch_command(command, context)
    created = events[0]
    return ResourceResponse(
        grn=created.payload["grn"],
        resource_type="chat",
        state="active",
        attributes=created.payload.get("attributes", {}),
    )
