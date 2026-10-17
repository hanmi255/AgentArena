"""Small business-only model inputs; omit UI labels and connection metadata."""


def store_facts(store):
    return {key: store[key] for key in (
        "cash", "equity", "profit", "inventory", "reputation", "memory", "metrics"
    )}


def market_facts(market):
    return {
        "round": market["round"], "event": market["event"], "rent": market["rent"],
        "total_demand": market["total_demand"],
        "products": [{key: product[key] for key in (
            "id", "cost", "reference_price", "demand", "supply"
        )} for product in market["products"]],
    }


def decision_context(observation):
    return {
        "store": store_facts(observation["store"]),
        "market": market_facts(observation["market"]),
        "competitors": observation["competitors"],
        "history": observation["history"],
        "remaining_rounds": observation["remaining_rounds"],
        "experiences": observation.get("experiences", []),
        "supply_policy": observation.get("supply_policy", "sequential_v1"),
    }
