"""Planning estimates use only a merchant's observation, never future settlement RNG."""

import math

from arena.domain.models import Decision
from arena.domain.procurement import POLICY


def simulate_plan(observation, plan):
    decision = Decision.model_validate(plan)
    store, market = observation["store"], observation["market"]
    shared = observation.get("supply_policy") == POLICY
    products = {item["id"]: item for item in market["products"]}
    inventory = {item["product_id"]: item for item in store["inventory"]}
    purchase_cost = sum(item.purchase_quantity * products[item.product_id]["cost"] for item in decision.products)
    requested = purchase_cost + decision.marketing_budget + market["rent"]
    risks = []
    if requested > store["cash"]:
        risks.append(f"采购、营销及租金合计 ¥{requested / 100:.2f}，超过当前现金 ¥{store['cash'] / 100:.2f}")
    for item in decision.products:
        if item.purchase_quantity > products[item.product_id]["supply"]:
            risks.append(f"{products[item.product_id]['name']}计划采购超过市场总供应")
    scenarios = []
    for label, multiplier in [("低需求", 0.7), ("基准需求", 1.0), ("高需求", 1.2)]:
        cash = store["cash"]
        revenue = cogs = holding = sold = leftover = 0
        for item in decision.products:
            product, stock = products[item.product_id], inventory[item.product_id]
            supply = product["supply"]
            if shared:
                # Rival orders are private: vary their assumed demand with the scenario.
                rival_demand = product["demand"] / observation["merchant_count"] * max(0, observation["merchant_count"] - 1)
                rival_demand *= 1.3 if label == "低需求" else 0.7 if label == "高需求" else 1
                total_orders = item.purchase_quantity + rival_demand
                if total_orders > supply:
                    supply = int(supply * item.purchase_quantity / total_orders)
            quantity = min(item.purchase_quantity, supply, max(0, cash - market["rent"] - (decision.marketing_budget if shared else 0)) // product["cost"])
            cash -= quantity * product["cost"]
            available = stock["quantity"] + quantity
            book_value = stock["book_value"] + quantity * product["cost"]
            own_weight = math.exp(3 * (product["reference_price"] - item.price) / product["reference_price"])
            own_weight *= (1 + math.sqrt(decision.marketing_budget / 100) / 18) * store["reputation"]
            rival_weights = []
            for rival in observation["competitors"]:
                price = next(value["price"] for value in rival["prices"] if value["product_id"] == item.product_id)
                rival_weights.append(math.exp(3 * (product["reference_price"] - price) / product["reference_price"]))
            share = own_weight / (own_weight + sum(rival_weights))
            acceptable = max(0.0, min(1.0, (1.65 - item.price / product["reference_price"]) / 0.85))
            sales = min(available, round(product["demand"] * multiplier * share * acceptable))
            cost = round(book_value * sales / available) if available else 0
            revenue += sales * item.price
            cogs += cost
            holding += book_value - cost
            sold += sales
            leftover += available - sales
        advertising = min(decision.marketing_budget, max(0, cash - market["rent"]))
        fees = market["rent"] + round(holding * 0.012)
        closing_cash = max(0, cash - advertising + revenue - fees)
        scenarios.append({"name": label, "profit": revenue - cogs - advertising - fees,
                          "cash": closing_cash, "revenue": revenue, "sold": sold, "inventory": leftover})
    worst = min(item["cash"] for item in scenarios)
    if worst < market["rent"] * 2:
        risks.append("低需求情景下现金缓冲不足两轮租金")
    expected = scenarios[1]["profit"]
    downside = min(item["profit"] for item in scenarios)
    return {"expected_profit": expected, "worst_cash": worst, "score": round(expected * 0.7 + downside * 0.3) - len(risks) * 100000,
            "purchase_cost": purchase_cost, "risks": risks, "scenarios": scenarios,
            "supply_assumption": "按公开需求估计其他商店订单并比例分货；协商成功与进价尚不确定，实际到货可能更少" if shared else "按旧版轮换采购规则估算"}


def budget_plan(observation, plan):
    """Repair only the rule baseline; model proposals must pass their own review."""
    decision = Decision.model_validate(plan)
    products = {item["id"]: item for item in observation["market"]["products"]}
    available = max(0, observation["store"]["cash"] - observation["market"]["rent"] * 3)
    marketing = min(decision.marketing_budget, available // 5)
    available -= marketing
    actions = []
    for item in decision.products:
        cost = products[item.product_id]["cost"]
        quantity = min(item.purchase_quantity, products[item.product_id]["supply"] // observation["merchant_count"], available // cost)
        available -= cost * quantity
        actions.append(item.model_copy(update={"purchase_quantity": quantity}))
    return decision.model_copy(update={"products": actions, "marketing_budget": marketing}).model_dump()
