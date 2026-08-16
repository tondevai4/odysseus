# routes/oracle.py
"""
Multi-persona strategic debate and decision matrix evaluator.
Simulates Growth Advocate vs. Risk Cynic vs. Pragmatic Operator personas to score high-stakes decisions.
"""
import json
import logging
import uuid
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, Field

from core.database import SessionLocal, OracleDecision, utcnow_naive

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Oracle Strategic Decisions"])


class OracleDecisionRequest(BaseModel):
    title: str = Field(..., description="Decision title (e.g. Expand into Enterprise Tier)")
    premise: str = Field(..., description="Context, trade-offs, and details of the decision")
    options: Optional[List[str]] = Field(default_factory=list, description="Candidate options")


def _evaluate_deterministic_debate(title: str, premise: str) -> Dict[str, Any]:
    """Structured heuristic debate matrix when LLM is offline."""
    return {
        "critique_growth": (
            f"Growth Persona: '{title}' unlocks compounding upside by expanding addressable capacity. "
            "Maximizing distribution leverage early prevents competitor lock-in."
        ),
        "critique_risk": (
            f"Risk Persona: Downside exposure in '{title}' stems from capital diversion and operational friction. "
            "Failure to validate baseline demand before commitment could lead to sunk costs."
        ),
        "synthesis_score": 82.5,
        "verdict": (
            f"Pragmatic Verdict on '{title}': Execute in small iterative phases. "
            "Gate full commitment on reaching early leading indicators within 30 days."
        ),
    }


@router.post("/api/oracle/decide")
async def evaluate_decision_matrix(body: OracleDecisionRequest, request: Request):
    """Run a multi-persona debate to evaluate risk, growth, and synthesize a score."""
    decision_id = f"od-{uuid.uuid4().hex[:10]}"
    debate_result = None

    # Check for LLM client in app state
    llm_client = getattr(request.app.state, "llm_client", None)
    if llm_client:
        try:
            prompt = (
                f"You are the YVES Strategic Decision Oracle. Analyze this decision via a 3-persona debate:\n\n"
                f"Decision Title: {body.title}\n"
                f"Premise: {body.premise}\n"
                f"Options: {', '.join(body.options) if body.options else 'Standard proceed vs defer'}\n\n"
                "Return a strict JSON object with these exact keys:\n"
                "- critique_growth: (Advocate for growth and upside)\n"
                "- critique_risk: (Cynical critique of failure modes)\n"
                "- synthesis_score: (Float from 0 to 100 representing strategic value)\n"
                "- verdict: (Actionable pragmatic recommendation)\n"
            )
            raw = await llm_client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
                temperature=0.3,
            )
            debate_result = json.loads(raw)
        except Exception as e:
            logger.warning(f"LLM decision debate fallback: {e}")

    if not debate_result or not isinstance(debate_result, dict):
        debate_result = _evaluate_deterministic_debate(body.title, body.premise)

    growth = str(debate_result.get("critique_growth", ""))
    risk = str(debate_result.get("critique_risk", ""))
    score = float(debate_result.get("synthesis_score", 75.0))
    verdict = str(debate_result.get("verdict", ""))

    try:
        with SessionLocal() as db:
            decision = OracleDecision(
                id=decision_id,
                title=body.title,
                premise=body.premise,
                critique_growth=growth,
                critique_risk=risk,
                synthesis_score=score,
                verdict=verdict,
            )
            db.add(decision)
            db.commit()

            return {
                "success": True,
                "id": decision_id,
                "decision": {
                    "id": decision_id,
                    "title": decision.title,
                    "premise": decision.premise,
                    "critique_growth": decision.critique_growth,
                    "critique_risk": decision.critique_risk,
                    "synthesis_score": decision.synthesis_score,
                    "verdict": decision.verdict,
                    "created_at": decision.created_at.isoformat(),
                },
            }
    except Exception as e:
        logger.error(f"Failed to persist oracle decision: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")


@router.get("/api/oracle/decisions")
async def list_oracle_decisions(limit: int = Query(default=30, ge=1, le=200)):
    """Retrieve past strategic decision debate evaluations."""
    try:
        with SessionLocal() as db:
            decisions = (
                db.query(OracleDecision)
                .order_by(OracleDecision.created_at.desc())
                .limit(limit)
                .all()
            )
            return {
                "decisions": [
                    {
                        "id": d.id,
                        "title": d.title,
                        "premise": d.premise,
                        "critique_growth": d.critique_growth,
                        "critique_risk": d.critique_risk,
                        "synthesis_score": d.synthesis_score,
                        "verdict": d.verdict,
                        "created_at": d.created_at.isoformat(),
                    }
                    for d in decisions
                ],
                "total": len(decisions),
            }
    except Exception as e:
        logger.error(f"Failed to list oracle decisions: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")


def setup_oracle_decision_routes() -> APIRouter:
    return router
