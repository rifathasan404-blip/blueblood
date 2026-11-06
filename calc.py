"""The month's money rules, taken from the `Final` sheet of the Excel file.

Kept free of database and HTTP code so it can be tested directly.
"""
import math

# Tiny float noise (3000.0000000001) must not make ROUNDUP add a whole taka.
PRECISION = 6


def roundup(x):
    """Excel's ROUNDUP(x, 0): rounds away from zero, so -1079.1 becomes -1080."""
    x = round(x, PRECISION)
    return math.copysign(math.ceil(abs(x)), x) if x else 0.0


def per_head(bill, people):
    if not people:
        return 0.0
    share = bill["amount"] / people
    return roundup(share) if bill["round_up"] else share


def calculate(sides, members, meals, bazar, bills, payments):
    """meals/bazar/payments map member id -> total for the month.

    sides:   id, name, bills_charged, addon
    members: id, name, side_id, rent
    bills:   id, side_id (None = shared by everyone), amount, round_up
    """
    total_meals = sum(meals.get(m["id"], 0) for m in members)
    total_bazar = sum(bazar.get(m["id"], 0) for m in members)
    meal_rate = total_bazar / total_meals if total_meals else 0.0

    head_count = {s["id"]: 0 for s in sides}
    for m in members:
        head_count[m["side_id"]] += 1

    bill_rows, shared_per_head = [], 0.0
    side_per_head = {s["id"]: 0.0 for s in sides}
    for b in bills:
        sid = b["side_id"]
        people = len(members) if sid is None else head_count.get(sid, 0)
        share = per_head(b, people)
        bill_rows.append({"id": b["id"], "per_head": share, "people": people})
        if sid is None:
            shared_per_head += share
        else:
            side_per_head[sid] += share

    service = {}
    side_rows = []
    for s in sides:
        charged = side_per_head[s["id"]] if s["bills_charged"] else 0.0
        service[s["id"]] = shared_per_head + charged + s["addon"]
        side_rows.append({
            "id": s["id"],
            "people": head_count[s["id"]],
            "bills_per_head": side_per_head[s["id"]],
            "service_charge": service[s["id"]],
            "total_due": 0.0,
        })
    rows_by_side = {r["id"]: r for r in side_rows}

    rows = []
    for m in members:
        qty = meals.get(m["id"], 0)
        spent = bazar.get(m["id"], 0)
        cost = meal_rate * qty
        balance = cost - spent          # + owes the flat, - gets money back
        charge = service[m["side_id"]]
        total = m["rent"] + charge + balance
        paid = payments.get(m["id"], 0)
        due = roundup(total - paid)
        rows_by_side[m["side_id"]]["total_due"] += due
        rows.append({
            "id": m["id"],
            "meals": qty,
            "meal_cost": cost,
            "bazar": spent,
            "balance": balance,
            "rent": m["rent"],
            "service": charge,
            "service_plus_meal": roundup(charge + balance),
            "total": total,
            "paid": paid,
            "due": due,
        })

    return {
        "total_meals": total_meals,
        "total_bazar": total_bazar,
        "meal_rate": meal_rate,
        "shared_per_head": shared_per_head,
        "bills": bill_rows,
        "sides": side_rows,
        "members": rows,
        "total_paid": sum(r["paid"] for r in rows),
        "total_due": sum(r["due"] for r in rows),
    }
