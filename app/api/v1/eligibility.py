from app.schemas.elective_ranking import ElectivePriorityInput, ElectivePriorityResult
from app.schemas.eligibility import EligibilityResult, StudentEligibilityInput
from app.services.elective_ranking import get_elective_priorities
from app.services.eligibility_service import get_eligible_subjects
from fastapi import APIRouter

router = APIRouter()


@router.post("/eligible-subjects", response_model=EligibilityResult)
async def eligible_subjects(body: StudentEligibilityInput) -> EligibilityResult:
    return get_eligible_subjects(body)


@router.post("/elective-priorities", response_model=ElectivePriorityResult)
async def elective_priorities(body: ElectivePriorityInput) -> ElectivePriorityResult:
    return get_elective_priorities(body)
