"""Уведомления в кабинете: клиентам - о событиях заявки, сотрудникам - о назначении, запросах
и напоминаниях. По условиям кейса email и SMS не используются."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, CompanyMember, Notification, User
from app.models.enums import NotificationType
from app.services.errors import NotFoundError


def add(
    session: AsyncSession,
    user_ids: list[uuid.UUID],
    application: Application | None,
    type: NotificationType,
    title: str,
    body: str,
) -> None:
    """Добавляет уведомления в сессию; коммит - на вызывающем."""
    for user_id in dict.fromkeys(user_ids):
        session.add(
            Notification(
                user_id=user_id,
                application_id=application.id if application else None,
                type=type,
                title=title,
                body=body,
            )
        )


async def to_company(
    session: AsyncSession,
    application: Application,
    type: NotificationType,
    title: str,
    body: str,
) -> None:
    """Всем представителям компании-заёмщика."""
    members = await session.scalars(
        select(CompanyMember.user_id).where(CompanyMember.company_id == application.company_id)
    )
    add(session, list(members), application, type, title, body)


async def list_for(
    session: AsyncSession, user: User, *, unread_only: bool, limit: int, offset: int
) -> tuple[list[Notification], int, int]:
    """Уведомления пользователя, новые первыми; плюс число непрочитанных."""
    query = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    unread = await session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
    )
    rows = await session.scalars(
        query.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
    )
    return list(rows), total or 0, unread or 0


async def mark_read(session: AsyncSession, user: User, notification_id: uuid.UUID) -> None:
    notification = await session.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise NotFoundError("Уведомление не найдено")
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        await session.commit()


async def mark_all_read(session: AsyncSession, user: User) -> None:
    await session.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    await session.commit()
