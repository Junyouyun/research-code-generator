from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user
from app.core.database import (
    get_conversation,
    get_or_create_project_conversation,
    list_conversation_messages,
)
from app.core.models import Conversation, ConversationMessage, User
from app.core.project_access import get_owned_project
from app.core.schemas import (
    ConversationMessageResponse,
    ConversationMessagesResponse,
    ConversationResponse,
)

router = APIRouter(tags=["conversations"])


@router.get("/projects/{project_id}/conversation", response_model=ConversationResponse)
def get_project_conversation(
    project_id: str,
    current_user: User = Depends(get_current_user),
) -> ConversationResponse:
    project = get_owned_project(project_id, current_user)
    conversation = get_or_create_project_conversation(
        project_id=project_id,
        user_id=current_user.user_id,
        title=project.original_filename,
    )
    return _conversation_response(conversation)


@router.get("/conversations/{conversation_id}/messages", response_model=ConversationMessagesResponse)
def get_conversation_messages(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
) -> ConversationMessagesResponse:
    conversation = get_conversation(conversation_id, current_user.user_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")

    messages = list_conversation_messages(conversation_id, current_user.user_id)
    return ConversationMessagesResponse(
        conversation_id=conversation_id,
        messages=[_message_response(message) for message in messages],
    )


def _conversation_response(conversation: Conversation) -> ConversationResponse:
    return ConversationResponse(
        conversation_id=conversation.conversation_id,
        user_id=conversation.user_id,
        project_id=conversation.project_id,
        title=conversation.title,
        status=conversation.status,
        short_summary=conversation.short_summary,
        summary_updated_at=conversation.summary_updated_at,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _message_response(message: ConversationMessage) -> ConversationMessageResponse:
    return ConversationMessageResponse(
        message_id=message.message_id,
        conversation_id=message.conversation_id,
        project_id=message.project_id,
        role=message.role,
        content=message.content,
        content_type=message.content_type,
        metadata=message.metadata,
        created_at=message.created_at,
    )
