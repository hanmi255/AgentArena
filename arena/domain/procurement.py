"""Round-wide wholesale clearing, independent of model execution order."""

POLICY = "proportional_v1"
LEGACY_POLICY = "sequential_v1"


def allocate_orders(previous, plans, market, agreements, seed):
    """Fund binding orders first, then apportion each product by largest remainder."""
    merchants = sorted(previous["merchants"], key=lambda item: item["slot"])
    orders = {merchant["id"]: {} for merchant in merchants}
    for merchant in merchants:
        if merchant["bankrupt"]:
            continue
        plan = plans[merchant["id"]]
        cash = max(0, merchant["cash"] - market["rent"] - plan["marketing_budget"])
        actions = {item["product_id"]: item for item in plan["products"]}
        for product in market["products"]:
            product_id = product["id"]
            action = actions[product_id]
            negotiated = merchant["id"] in agreements
            agreement = agreements.get(merchant["id"], {}).get(product_id)
            if negotiated and agreement is None:
                continue
            if agreement:
                if agreement["expires_round"] != market["round"] or agreement["unit_price"] <= 0 or agreement["quantity"] <= 0:
                    raise ValueError("无效或已过期的采购协议")
                if agreement["quantity"] > action["purchase_quantity"]:
                    raise ValueError("采购协议超过批准的采购数量")
            price = agreement["unit_price"] if agreement else product["cost"]
            quantity = min(agreement["quantity"] if agreement else action["purchase_quantity"],
                           product["supply"], cash // price)
            cash -= quantity * price
            if quantity:
                orders[merchant["id"]][product_id] = {
                    "product_id": product_id, "supplier_id": "wholesale", "unit_price": price,
                    "reference_price": product["cost"], "expires_round": market["round"],
                    "requested_quantity": quantity, "quantity": quantity,
                }

    offset = (seed + market["round"] - 1) % len(merchants)
    priority = {merchant["id"]: index for index, merchant in enumerate(merchants[offset:] + merchants[:offset])}
    for product in market["products"]:
        bidders = [(merchant_id, items[product["id"]]) for merchant_id, items in orders.items() if product["id"] in items]
        total = sum(order["requested_quantity"] for _, order in bidders)
        if total > product["supply"]:
            for _, order in bidders:
                order["quantity"] = order["requested_quantity"] * product["supply"] // total
            remaining = product["supply"] - sum(order["quantity"] for _, order in bidders)
            ranked = sorted(bidders, key=lambda item: (
                -(item[1]["requested_quantity"] * product["supply"] % total), priority[item[0]],
            ))
            for _, order in ranked[:remaining]:
                order["quantity"] += 1
        for _, order in bidders:
            order["status"] = "fulfilled" if order["quantity"] else "unavailable"
    return orders


def purchase_outcomes(merchant, plan, market, agreements, entries):
    """Derive displayed delivery facts from the ledger, including legacy rounds."""
    products = {item["id"]: item for item in market["products"]}
    agreed = {item["product_id"]: item for item in agreements}
    purchases = {item["product_id"]: item for item in entries
                 if item["merchant_id"] == merchant["id"] and item["kind"] == "purchase"}
    negotiated = merchant.get("agent_options", {}).get("negotiation", False)
    outcomes = []
    for action in plan["products"]:
        product_id = action["product_id"]
        entry = purchases.get(product_id)
        agreement = agreed.get(product_id)
        quantity = entry["quantity"] if entry else 0
        requested = action["purchase_quantity"]
        price = (-entry["amount"] // quantity if entry else
                 agreement["unit_price"] if agreement else
                 None if negotiated else products[product_id]["cost"])
        status = ("fulfilled" if quantity >= requested and quantity else "partial" if quantity else
                  "not_ordered" if not requested or merchant["bankrupt"] else
                  "unavailable" if products[product_id]["supply"] == 0 else
                  "rejected" if negotiated and not agreement else "unavailable")
        outcomes.append({"product_id": product_id, "requested_quantity": requested, "quantity": quantity,
                         "unit_price": price, "status": status})
    return outcomes
