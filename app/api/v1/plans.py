import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.auth import User
from app.models.study_plan import SavedStudyPlan
from app.schemas.study_plan import (
    SavedStudyPlanCreate,
    SavedStudyPlanOut,
    SavedStudyPlanUpdate,
)

router = APIRouter()


@router.get("", response_model=list[SavedStudyPlanOut])
async def list_saved_plans(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    rows = await db.scalars(
        select(SavedStudyPlan)
        .where(SavedStudyPlan.user_id == user.id)
        .order_by(SavedStudyPlan.updated_at.desc())
    )
    return list(rows)


@router.post("", response_model=SavedStudyPlanOut, status_code=status.HTTP_201_CREATED)
async def save_plan(
    body: SavedStudyPlanCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    plan = SavedStudyPlan(
        user_id=user.id,
        title=body.title.strip(),
        plan=body.plan.model_dump(mode="json"),
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    return plan


async def _owned_plan(plan_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession):
    plan = await db.scalar(
        select(SavedStudyPlan).where(
            SavedStudyPlan.id == plan_id, SavedStudyPlan.user_id == user_id
        )
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="Saved study plan not found")
    return plan


@router.get("/{plan_id}", response_model=SavedStudyPlanOut)
async def get_saved_plan(
    plan_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _owned_plan(plan_id, user.id, db)


@router.put("/{plan_id}", response_model=SavedStudyPlanOut)
async def update_saved_plan(
    plan_id: uuid.UUID,
    body: SavedStudyPlanUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    plan = await _owned_plan(plan_id, user.id, db)
    changes = body.model_dump(exclude_unset=True)
    if "title" in changes and changes["title"] is not None:
        plan.title = changes["title"].strip()
    if "plan" in changes and changes["plan"] is not None:
        plan.plan = changes["plan"]
    await db.commit()
    await db.refresh(plan)
    return plan


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_plan(
    plan_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    plan = await _owned_plan(plan_id, user.id, db)
    await db.delete(plan)
    await db.commit()
