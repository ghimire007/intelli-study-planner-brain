from app.schemas.eligibility import EligibilityResult, StudentEligibilityInput
from app.services.eligibility_service import get_eligible_subjects
from fastapi import APIRouter

router = APIRouter()


@router.post("/eligible-subjects", response_model=EligibilityResult)
async def eligible_subjects(body: StudentEligibilityInput) -> EligibilityResult:
    return get_eligible_subjects(body)
