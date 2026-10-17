export type Color = "violet" | "orange" | "teal" | "blue";
export type ProductId = "coffee" | "oats" | "bar";
export type ArenaStatus =
  | "ready"
  | "running"
  | "paused"
  | "stepping"
  | "awaiting_approval"
  | "completed";
export type Mode = "rule" | "llm";
export interface Product {
  id: ProductId;
  name: string;
  cost: number;
  reference_price: number;
  initial_stock: number;
  color: string;
  unit: string;
  base_demand: number;
  base_supply: number;
}
export interface MarketProduct extends Product {
  demand: number;
  supply: number;
}
export interface Scenario {
  id: string;
  name: string;
  tag: string;
  description: string;
  rent: number;
}
export interface Catalog {
  products: Product[];
  scenarios: Scenario[];
  merchant_names: string[];
  colors: Color[];
}
export interface Strategy {
  id: string;
  name: string;
  description: string;
  approach: "balanced" | "discount" | "premium" | "adaptive";
  margin: number;
  stock_days: number;
  marketing_budget: number;
  prompt: string;
  color: Color;
  built_in?: boolean;
}
export interface Stock {
  product_id: ProductId;
  name: string;
  quantity: number;
  book_value: number;
  price: number;
}
export interface Metrics {
  revenue: number;
  sold: number;
  profit: number;
  procurement: number;
  marketing: number;
  operating_cost: number;
  cost_of_goods: number;
  purchased: number;
  missed: number;
}
export interface Merchant {
  procurement?: Procurement[];
  id: number;
  slot: number;
  name: string;
  color: Color;
  strategy_id: string;
  strategy_name: string;
  mode: Mode;
  cash: number;
  equity: number;
  profit: number;
  roi: number;
  inventory: Stock[];
  total_revenue: number;
  total_sold: number;
  reputation: number;
  memory: string;
  bankrupt: boolean;
  metrics: Metrics;
  model_config?: Partial<ModelProfile>;
  workflow?: "direct" | "reviewed" | "adaptive";
  agent_options?: AgentOptions;
}
export interface MarketEvent {
  type: string;
  name: string;
  description: string;
  impact: string;
}
export interface Market {
  scenario: string;
  scenario_name: string;
  round: number;
  event: MarketEvent;
  products: MarketProduct[];
  rent: number;
  total_demand: number;
}
export interface Snapshot {
  round: number;
  market: Market;
  merchants: Merchant[];
  totals: { revenue: number; sold: number; demand: number; profit: number };
}
export interface ArenaBase {
  supply_policy: "sequential_v1" | "proportional_v1";
  id: number;
  name: string;
  scenario: string;
  seed: number;
  total_rounds: number;
  current_round: number;
  initial_capital: number;
  status: ArenaStatus;
  error: string | null;
  created_at: string;
  updated_at: string;
  experiment_id: number | null;
}
export interface ArenaSummary extends ArenaBase {
  merchants: Merchant[];
  leader: string;
  leader_profit: number;
  total_revenue: number;
  total_sold: number;
}
export interface HistoryPoint {
  round: number;
  event: string;
  merchants: {
    id: number;
    profit: number;
    revenue: number;
    sold: number;
    equity: number;
  }[];
}
export interface ProductAction {
  product_id: ProductId;
  price: number;
  purchase_quantity: number;
}
export interface Decision {
  id: number;
  merchant_id: number;
  name: string;
  color: Color;
  mode: Mode;
  round_number: number;
  plan: {
    products: ProductAction[];
    marketing_budget: number;
    summary: string;
    memory: string;
  };
  observation: Record<string, unknown>;
  tools: {
    name: string;
    arguments: Record<string, unknown>;
    result: unknown;
    executed?: boolean;
  }[];
  stages: { node: string; label: string; status: string }[];
  input_tokens: number;
  output_tokens: number;
  duration_ms: number;
  model_config: Partial<ModelProfile>;
  trace: WorkflowTrace;
}
export interface Arena extends ArenaBase {
  snapshot: Snapshot;
  history: HistoryPoint[];
  decisions: Decision[];
  tokens: { input: number; output: number };
  approvals?: Approval[];
  parent_arena_id?: number;
  fork_round?: number;
}
export interface MerchantInput {
  name: string;
  strategy_id: string;
  mode: Mode;
  color: Color;
  model_profile_id?: string;
  workflow?: "direct" | "reviewed" | "adaptive";
  agent_options?: AgentOptions;
}
export interface ArenaInput {
  name: string;
  scenario: string;
  total_rounds: number;
  seed: number;
  initial_capital: number;
  merchants: MerchantInput[];
  approval_policy?: "off" | "risk" | "all";
}
export interface LedgerEntry {
  id: number;
  round_number: number;
  merchant_name: string;
  merchant_id: number;
  kind: "purchase" | "sale" | "marketing" | "operations";
  product_id: string;
  quantity: number;
  amount: number;
  balance: number;
}
export interface ModelSettings {
  base_url: string;
  model: string;
  has_key: boolean;
  temperature: number;
  timeout: number;
  max_steps: number;
  queue: string;
  storage: string;
  provider: "compatible" | "deepseek";
  thinking: "disabled" | "enabled";
  max_tokens: number;
  input_price: number;
  output_price: number;
}
export interface ModelProfile extends Omit<ModelSettings, "queue" | "storage"> {
  id: string;
  name: string;
  enabled: boolean;
}
export interface WorkflowTrace {
  routing?: {
    objective: string;
    reason: string;
    tools: string[];
    review_required: boolean;
  };
  projection?: Projection;
  negotiation?: Negotiation;
  memory?: Experience[];
  human_response?: { action: string; reason: string; plan?: Decision["plan"] };
  candidates?: Projection[];
  reviews?: { approved: boolean; reason: string; issues: string[] }[];
  revisions?: number;
  workflow?: string;
  iterations?: {
    revision: number;
    selected_index: number;
    candidates: Projection[];
  }[];
}
export interface Projection {
  supply_assumption?: string;
  plan?: Decision["plan"];
  index: number;
  summary: string;
  score: number;
  expected_profit: number;
  worst_cash: number;
  risks: string[];
  scenarios: {
    name: string;
    profit: number;
    cash: number;
    revenue: number;
    sold: number;
    inventory: number;
  }[];
}
export interface ExecutionJob {
  id: number;
  arena_id: number;
  state: "queued" | "running" | "paused" | "failed" | "completed";
  owner: string;
  lease_version: number;
  lease_until: number;
  attempts: number;
  created_at: string;
  updated_at: string;
  error: string | null;
}
export interface ExperimentVariant {
  name: string;
  strategy_id: string;
  mode: Mode;
  workflow: "direct" | "reviewed" | "adaptive";
  agent_options?: AgentOptions;
  model_profile_id?: string;
}
export interface Experiment {
  id: number;
  name: string;
  config: {
    strategy_ids: string[];
    scenario: string;
    rounds: number;
    seeds: number[];
    mode: Mode;
    split?: "development" | "holdout";
    variants?: ExperimentVariant[];
  };
  created_at: string;
  arenas: ArenaSummary[];
  completed: number;
  status: string;
  scores: {
    strategy_id: string;
    name: string;
    color: Color;
    samples: number;
    average_profit: number;
    deviation: number;
    win_rate: number;
    confidence_interval?: [number, number] | null;
    model?: string;
    workflow?: string;
    bankruptcy_rate?: number;
    total_tokens?: number;
    average_duration_ms?: number;
    estimated_model_cost?: number | null;
    average_drawdown?: number;
    stockout_rate?: number;
    inventory_turnover?: number;
    revisions?: number;
    tool_calls?: number;
    memory_references?: number;
    prediction_mae?: number | null;
    negotiation_savings?: number;
    contracts?: number;
  }[];
  comparisons?: {
    baseline: string;
    variant: string;
    samples: number;
    average_difference: number;
    confidence_interval: [number, number] | null;
  }[];
}
export interface Overview {
  arenas: ArenaSummary[];
  strategies: Strategy[];
  stats: {
    arenas: number;
    completed: number;
    rounds: number;
    revenue: number;
    active: number;
  };
}

export interface AgentOptions {
  memory: "none" | "recent" | "episodic";
  negotiation: boolean;
  tool_budget: number;
}
export interface Approval {
  id: number;
  version: number;
  merchant_id: number;
  round_number: number;
  name: string;
  proposal: {
    plan: Decision["plan"];
    projection: Projection;
    spend: number;
    cash: number;
  };
}
export interface Experience {
  evidence_id: number;
  round: number;
  similarity: number;
  context: { event: string; demand: number; cash_before: number };
  action: Decision["plan"];
  outcome: Metrics & {
    cash: number;
    prediction_error: number | null;
    predicted_profit: number | null;
  };
  lesson: string;
}
export interface Negotiation {
  messages?: {
    product_id: string;
    agreed: boolean;
    messages: {
      sender: string;
      action: string;
      unit_price?: number;
      quantity: number;
      reason: string;
    }[];
  }[];
  contracts?: {
    product_id: string;
    supplier_id: string;
    quantity: number;
    requested_quantity: number;
    unit_price: number;
    reference_price: number;
    status: string;
  }[];
}
export interface Procurement {
  product_id: ProductId;
  requested_quantity: number;
  quantity: number;
  unit_price: number | null;
  status: "fulfilled" | "partial" | "not_ordered" | "unavailable" | "rejected";
}
export interface DecisionEvent {
  id: number;
  arena_id: number;
  round_number: number;
  merchant_id: number | null;
  node: string;
  status: string;
  label: string;
  created_at: string;
  payload: {
    merchant?: Merchant;
    market?: Market;
    evidence?: {
      cash: number;
      inventory: Stock[];
      market_event: string;
      experiences: Experience[];
    };
    decision?: Decision["plan"];
    plan?: Decision["plan"];
    candidates?: Decision["plan"][];
    evaluations?: Projection[];
    reviews?: NonNullable<WorkflowTrace["reviews"]>;
    routing?: WorkflowTrace["routing"];
    negotiation?: Negotiation;
    metrics?: Metrics;
    projection?: Projection;
    tool?: string;
    arguments?: Record<string, unknown>;
    result?: unknown;
    message?: {
      sender: string;
      action: string;
      unit_price?: number;
      quantity: number;
      reason: string;
    };
    product_id?: string;
    duration_ms?: number;
    revision?: number;
    model?: string;
    input_tokens?: number;
    output_tokens?: number;
  };
}
