import copy
import math
import random

from arena.domain.catalog import PRODUCTS, SCENARIOS


def conditions(scenario_id: str, seed: int, round_number: int):
    scenario = next(item for item in SCENARIOS if item["id"] == scenario_id)
    randomizer = random.Random(seed + round_number * 10000)
    event = {"type": "normal", "name": "平稳营业", "description": "商圈客流保持稳定", "impact": "正常交易"}
    demand_multiplier = 1.0
    supply_multiplier = 1.0
    cost_multiplier = 1.0
    product_boost = ""
    if round_number % 7 == 0:
        event = {"type": "scarcity", "name": "供应延迟", "description": "供应商到货减少，采购成本上升", "impact": "供给 −40% · 进价 +15%"}
        supply_multiplier, cost_multiplier = 0.6, 1.15
    elif round_number % 5 == 0:
        event = {"type": "festival", "name": "街区音乐节", "description": "活动带动客流，能量补给需求增加", "impact": "客流 +35%"}
        demand_multiplier, product_boost = 1.35, "bar"
    elif round_number % 4 == 0:
        event = {"type": "rain", "name": "午后阵雨", "description": "客流回落，咖啡需求相对坚挺", "impact": "客流 −18%"}
        demand_multiplier, product_boost = 0.82, "coffee"
    elif round_number % 3 == 0:
        event = {"type": "discount", "name": "供应商让利", "description": "本回合可享受批发折扣", "impact": "进价 −12%"}
        cost_multiplier = 0.88
    goods = []
    for product in PRODUCTS:
        demand = round(product["base_demand"] * scenario["demand_multiplier"] * demand_multiplier * randomizer.uniform(0.9, 1.1))
        if product["id"] == product_boost:
            demand = round(demand * 1.18)
        goods.append({
            **product,
            "cost": round(product["cost"] * cost_multiplier),
            "demand": demand,
            "supply": round(product["base_supply"] * scenario["supply_multiplier"] * supply_multiplier),
        })
    return {"scenario": scenario_id, "scenario_name": scenario["name"], "round": round_number,
            "event": event, "products": goods, "rent": scenario["rent"], "total_demand": sum(item["demand"] for item in goods)}


def settle(previous, plans, market, initial_capital, seed, contracts=None, reserve_marketing=False):
    """Deterministic settlement. Money is integer cents; models never mutate balances."""
    merchants = copy.deepcopy(previous["merchants"])
    entries = []
    round_number = market["round"]
    supply = {product["id"]: product["supply"] for product in market["products"]}
    contracts = contracts or {}
    for items in contracts.values():
        for product_id, contract in items.items():
            if contract["expires_round"] != round_number or contract["unit_price"] <= 0 or contract["quantity"] < 0:
                raise ValueError("无效或已过期的供货合同")
            supply[product_id] -= contract["quantity"]
            if supply[product_id] < 0:
                raise ValueError("供货合同超出共享库存")
    price_map = {product["id"]: product for product in market["products"]}
    metrics = {item["id"]: {"revenue": 0, "sold": 0, "procurement": 0, "marketing": 0, "operating_cost": 0,
                              "cost_of_goods": 0, "purchased": 0, "missed": 0} for item in merchants}

    def transact(merchant, kind, amount, quantity=0, product_id=""):
        merchant["cash"] += amount
        entries.append({"merchant_id": merchant["id"], "kind": kind, "amount": amount,
                        "quantity": quantity, "product_id": product_id, "balance": merchant["cash"]})

    # Rotate access to shared wholesale stock to avoid a permanent first-mover advantage.
    offset = (seed + round_number - 1) % len(merchants)
    purchasing_order = merchants[offset:] + merchants[:offset]
    for merchant in purchasing_order:
        if merchant["bankrupt"]:
            continue
        plan = plans[merchant["id"]]
        for action in plan["products"]:
            stock = next(item for item in merchant["inventory"] if item["product_id"] == action["product_id"])
            product = price_map[action["product_id"]]
            stock["price"] = action["price"]
            # Reserve the daily rent before procurement and advertising.
            available_cash = max(0, merchant["cash"] - market["rent"] - (plan["marketing_budget"] if reserve_marketing else 0))
            negotiated = merchant["id"] in contracts
            contract = contracts.get(merchant["id"], {}).get(product["id"], {})
            unit_price = contract.get("unit_price", product["cost"])
            available = contract.get("quantity", 0) if negotiated else supply[product["id"]]
            quantity = min(action["purchase_quantity"], available, available_cash // unit_price)
            if negotiated and quantity != available:
                raise ValueError("已预留合同无法按批准方案交付")
            if quantity:
                cost = quantity * unit_price
                stock["quantity"] += quantity
                stock["book_value"] += cost
                if not negotiated:
                    supply[product["id"]] -= quantity
                transact(merchant, "purchase", -cost, quantity, product["id"])
                metrics[merchant["id"]]["procurement"] += cost
                metrics[merchant["id"]]["purchased"] += quantity
        advertising = min(plan["marketing_budget"], max(0, merchant["cash"] - market["rent"]))
        transact(merchant, "marketing", -advertising)
        metrics[merchant["id"]]["marketing"] = advertising
        merchant["memory"] = plan["memory"]

    randomizer = random.Random(seed + round_number * 10000 + 1)
    for product in market["products"]:
        sold = {merchant["id"]: 0 for merchant in merchants}
        stocks = {merchant["id"]: next(item for item in merchant["inventory"] if item["product_id"] == product["id"]) for merchant in merchants}
        for _ in range(product["demand"]):
            willingness = product["reference_price"] * randomizer.uniform(0.8, 1.65)
            eligible = [merchant for merchant in merchants if not merchant["bankrupt"] and stocks[merchant["id"]]["quantity"] > sold[merchant["id"]] and stocks[merchant["id"]]["price"] <= willingness]
            if not eligible:
                continue
            weights = []
            for merchant in eligible:
                price = stocks[merchant["id"]]["price"]
                price_weight = math.exp(3 * (product["reference_price"] - price) / product["reference_price"])
                marketing_weight = 1 + math.sqrt(metrics[merchant["id"]]["marketing"] / 100) / 18
                weights.append(price_weight * marketing_weight * merchant["reputation"])
            buyer_choice = randomizer.choices(eligible, weights=weights, k=1)[0]
            sold[buyer_choice["id"]] += 1
        for merchant in merchants:
            stock = stocks[merchant["id"]]
            quantity = sold[merchant["id"]]
            if quantity:
                cogs = round(stock["book_value"] * quantity / stock["quantity"])
                stock["quantity"] -= quantity
                stock["book_value"] -= cogs
                revenue = quantity * stock["price"]
                transact(merchant, "sale", revenue, quantity, product["id"])
                metrics[merchant["id"]]["revenue"] += revenue
                metrics[merchant["id"]]["sold"] += quantity
                metrics[merchant["id"]]["cost_of_goods"] += cogs
            if stock["quantity"] == 0:
                metrics[merchant["id"]]["missed"] += 1

    for merchant in merchants:
        daily = metrics[merchant["id"]]
        if merchant["bankrupt"]:
            merchant["metrics"] = {**daily, "profit": 0}
            continue
        holding_cost = round(sum(item["book_value"] for item in merchant["inventory"]) * 0.012)
        operating_cost = min(merchant["cash"], market["rent"] + holding_cost)
        transact(merchant, "operations", -operating_cost)
        daily["operating_cost"] = operating_cost
        equity = merchant["cash"] + sum(item["book_value"] for item in merchant["inventory"])
        old_equity = next(item["equity"] for item in previous["merchants"] if item["id"] == merchant["id"])
        daily["profit"] = equity - old_equity
        merchant.update(equity=equity, profit=equity - initial_capital, roi=round((equity - initial_capital) / initial_capital * 100, 2), metrics=daily)
        merchant["total_revenue"] += daily["revenue"]
        merchant["total_sold"] += daily["sold"]
        merchant["reputation"] = round(min(1.25, max(0.8, merchant["reputation"] + daily["marketing"] / 2000000 - daily["missed"] * 0.008)), 4)
        merchant["bankrupt"] = equity < market["rent"]
    snapshot = {
        "round": round_number, "market": market, "merchants": merchants,
        "totals": {"revenue": sum(item["metrics"]["revenue"] for item in merchants),
                   "sold": sum(item["metrics"]["sold"] for item in merchants),
                   "demand": market["total_demand"], "profit": sum(item["profit"] for item in merchants)},
    }
    return snapshot, entries
