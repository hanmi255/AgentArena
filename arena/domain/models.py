from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from urllib.parse import urlsplit


class ProductAction(BaseModel):
    product_id: Literal["coffee", "oats", "bar"]
    price: int = Field(ge=100, le=10000, description="零售价，单位分")
    purchase_quantity: int = Field(ge=0, le=250)


class Decision(BaseModel):
    """本回合的完整经营方案，金额单位均为分。"""

    products: list[ProductAction] = Field(min_length=3, max_length=3)
    marketing_budget: int = Field(ge=0, le=30000)
    summary: str = Field(min_length=1, max_length=400)
    memory: str = Field(min_length=1, max_length=600)

    @model_validator(mode="after")
    def unique_products(self):
        if {item.product_id for item in self.products} != {"coffee", "oats", "bar"}:
            raise ValueError("经营方案必须包含咖啡、燕麦与能量棒各一次")
        return self


class StrategyInput(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    description: str = Field(max_length=120)
    approach: Literal["balanced", "discount", "premium", "adaptive"]
    margin: float = Field(ge=0.1, le=1.8)
    stock_days: float = Field(ge=0.5, le=3)
    marketing_budget: int = Field(ge=0, le=30000)
    prompt: str = Field(min_length=1, max_length=6000)
    color: Literal["violet", "orange", "teal", "blue"] = "violet"


class AgentOptions(BaseModel):
    memory: Literal["none", "recent", "episodic"] = "recent"
    negotiation: bool = False
    tool_budget: int = Field(default=6, ge=1, le=10)


class RoutingPlan(BaseModel):
    objective: str = Field(min_length=1, max_length=250)
    reason: str = Field(min_length=1, max_length=400)
    tools: list[Literal["inspect_store", "observe_market", "review_history", "evaluate_plan", "recall_experience"]] = Field(max_length=5)
    review_required: bool


class NegotiationAction(BaseModel):
    action: Literal["offer", "accept", "reject"]
    unit_price: int = Field(ge=0, le=10000, description="进货单价，单位分；报价或接受必须大于 0，拒绝可填 0")
    quantity: int = Field(ge=0, le=250)
    reason: str = Field(min_length=1, max_length=250)

    @model_validator(mode="after")
    def require_trade_price(self):
        if self.action != "reject" and self.unit_price == 0:
            raise ValueError("报价或接受时进货单价必须大于 0")
        return self


class MerchantInput(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    strategy_id: str
    mode: Literal["rule", "llm"] = "rule"
    color: Literal["violet", "orange", "teal", "blue"]
    model_profile_id: str | None = None
    workflow: Literal["direct", "reviewed", "adaptive"] = "direct"
    agent_options: AgentOptions = Field(default_factory=AgentOptions)
    entrant_id: str | None = None


class ArenaInput(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    scenario: Literal["neighborhood", "festival", "supply-shock"] = "neighborhood"
    total_rounds: int = Field(default=20, ge=3, le=60)
    seed: int = Field(default=42, ge=1, le=1000000)
    initial_capital: int = Field(default=1000000, ge=300000, le=10000000)
    merchants: list[MerchantInput] = Field(min_length=2, max_length=4)
    approval_policy: Literal["off", "risk", "all"] = "off"


class ApprovalInput(BaseModel):
    action: Literal["approve", "modify", "reject"]
    version: int = Field(default=0, ge=0)
    plan: Decision | None = None
    reason: str = Field(default="", max_length=400)

    @model_validator(mode="after")
    def modification_requires_plan(self):
        if self.action == "modify" and self.plan is None:
            raise ValueError("修改审批必须提供完整经营方案")
        return self


class ForkInput(BaseModel):
    round: int = Field(ge=0)
    merchants: list[MerchantInput] | None = Field(default=None, min_length=2, max_length=4)
    approval_policy: Literal["off", "risk", "all"] = "off"


class AdvanceInput(BaseModel):
    expected_round: int = Field(ge=0)


class RunInput(BaseModel):
    interval: float = Field(default=1, ge=0, le=5)


class ModelSettings(BaseModel):
    base_url: str = Field(min_length=1, max_length=300)
    model: str = Field(max_length=100)
    api_key: str | None = Field(default=None, max_length=500)
    temperature: float = Field(default=0.5, ge=0, le=2)
    timeout: int = Field(default=60, ge=5, le=180)
    max_steps: int = Field(default=10, ge=3, le=30)
    provider: Literal["compatible", "deepseek"] = "compatible"
    thinking: Literal["disabled", "enabled"] = "disabled"
    max_tokens: int = Field(default=4096, ge=512, le=32768)
    input_price: float = Field(default=0, ge=0, le=10000)
    output_price: float = Field(default=0, ge=0, le=10000)

    @field_validator("base_url")
    @classmethod
    def normalize_url(cls, value):
        value = value.strip().rstrip("/")
        if value.endswith("/chat/completions"):
            value = value[:-len("/chat/completions")]
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("请填写有效的 API 根地址，例如 https://api.deepseek.com")
        return value

    @field_validator("model", "api_key")
    @classmethod
    def trim_values(cls, value):
        return value.strip() if value is not None else None


class ModelProfileInput(ModelSettings):
    name: str = Field(min_length=1, max_length=60)
    enabled: bool = True


class CandidatePlans(BaseModel):
    """提出两到三个完整备选经营方案。"""

    candidates: list[Decision] = Field(min_length=2, max_length=3)


class PlanReview(BaseModel):
    """对经营方案和试算结果进行独立审核。"""

    approved: bool
    issues: list[str] = Field(max_length=6)
    reason: str = Field(min_length=1, max_length=500)


class ExperimentVariant(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    strategy_id: str
    mode: Literal["rule", "llm"] = "rule"
    workflow: Literal["direct", "reviewed", "adaptive"] = "direct"
    agent_options: AgentOptions = Field(default_factory=AgentOptions)
    model_profile_id: str | None = None


class ExperimentInput(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    strategy_ids: list[str] = Field(default=[], max_length=4)
    scenario: Literal["neighborhood", "festival", "supply-shock"] = "neighborhood"
    rounds: int = Field(default=12, ge=3, le=30)
    seeds: list[int] = Field(default=[11, 23, 37], min_length=1, max_length=5)
    mode: Literal["rule", "llm"] = "rule"
    model_profile_id: str | None = None
    workflow: Literal["direct", "reviewed", "adaptive"] = "direct"
    variants: list[ExperimentVariant] = Field(default=[], max_length=4)
    split: Literal["development", "holdout"] = "holdout"

    @model_validator(mode="after")
    def unique_strategies(self):
        if len(self.variants or self.strategy_ids) < 2:
            raise ValueError("至少选择两个对照方案")
        if len(set(self.strategy_ids)) != len(self.strategy_ids):
            raise ValueError("请选择不同的策略")
        if any(seed < 1 or seed > 1000000 for seed in self.seeds):
            raise ValueError("种子必须在 1 到 1000000 之间")
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("同一实验的种子不能重复")
        return self


class SelectionInput(BaseModel):
    seeds: list[int] = Field(min_length=1, max_length=5)
    round_budget: int = Field(default=180, ge=6, le=600)

    @field_validator("seeds")
    @classmethod
    def validation_seeds(cls, values):
        if len(set(values)) != len(values) or any(value < 1 or value > 1000000 for value in values):
            raise ValueError("验证种子必须互不相同且在 1 到 1000000 之间")
        return values
