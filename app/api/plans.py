"""계획 관리 라우터 (F3015 · F3016). 저장소는 app.state.plans (PlanStore)."""

from fastapi import APIRouter, HTTPException, Request

from ..schemas import PlanBatchIn, PlanIn, PlanOut, PlanSaved, PlanUpdate

router = APIRouter(prefix="/api/plans", tags=["plans"])
NOT_FOUND = "그런 계획이 없습니다."


def _store(request: Request):
    return request.app.state.plans


def _dump(plan: PlanIn | PlanUpdate) -> dict:
    data = plan.model_dump(exclude_unset=isinstance(plan, PlanUpdate))
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in data.items()}


def _saved(plan: dict, overlaps: list[dict]) -> PlanSaved:
    msg = "저장했습니다."
    if overlaps:
        names = ", ".join(f"{o['qual_name']}({o['plan_date']} {o.get('start_time') or '시각 미정'})" for o in overlaps)
        msg = f"저장했습니다. 같은 날짜에 시간이 겹치는 계획이 있습니다: {names}"
    return PlanSaved(plan=plan, overlaps=overlaps, message=msg)


@router.post("", response_model=PlanSaved, status_code=201)
def create_plan(plan: PlanIn, request: Request):
    """계획 1건 저장. 같은 날짜에 시간이 겹치는 계획이 있으면 저장하고 overlaps 로 알린다."""
    saved, overlaps = _store(request).create(_dump(plan))
    return _saved(saved, overlaps)


@router.post("/batch", response_model=list[PlanSaved], status_code=201)
def create_plans(body: PlanBatchIn, request: Request):
    """대화에서 만든 계획 여러 항목을 한 번에 저장한다. 항목마다 겹침을 알린다."""
    return [_saved(*_store(request).create(_dump(p))) for p in body.items]


@router.get("", response_model=list[PlanOut])
def list_plans(request: Request):
    """저장한 계획 목록 (시험일 순)."""
    return _store(request).list()


@router.get("/{plan_id}", response_model=PlanOut)
def get_plan(plan_id: int, request: Request):
    """계획 상세."""
    plan = _store(request).get(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return plan


@router.put("/{plan_id}", response_model=PlanSaved)
def update_plan(plan_id: int, changes: PlanUpdate, request: Request):
    """계획 핵심 값 수정. 수정 뒤 겹침을 다시 알린다."""
    saved, overlaps = _store(request).update(plan_id, _dump(changes))
    if saved is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return _saved(saved, overlaps)


@router.delete("/{plan_id}", status_code=204)
def delete_plan(plan_id: int, request: Request):
    """계획 삭제."""
    if not _store(request).delete(plan_id):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
