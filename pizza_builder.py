"""Gino's Pizza - Asset path resolution, price calculation, pizza validation."""

from menu import (
    SIZES, CRUSTS, BAKES, SAUCES, SAUCE_AMOUNTS,
    CHEESES, CHEESE_AMOUNTS, TOPPINGS, TOPPING_AMOUNTS, TOPPING_PLACEMENTS,
    FINISHES, SPECIALTIES, TAX_RATE,
)


# ─────────────────────────────────────────────────────────────────────────────
# Asset Path Resolution
# ─────────────────────────────────────────────────────────────────────────────

def crust_asset(crust_type, bake="classic"):
    """Return asset path for a crust. e.g. crust/thin/crust_thin_classic.png"""
    return f"crust/{crust_type}/crust_{crust_type}_{bake}.png"


def sauce_asset(sauce_type, amount="normal"):
    """Return asset path for a sauce. e.g. sauce/bbq/sauce_bbq_extra_full.png"""
    if sauce_type == "none":
        return None
    return f"sauce/{sauce_type}/sauce_{sauce_type}_{amount}_full.png"


def cheese_asset(cheese_type, amount="normal"):
    """Return asset path for cheese. e.g. cheese/mozzarella/cheese_mozzarella_normal_full.png"""
    if cheese_type == "none":
        return f"cheese/no_cheese/cheese_none_full.png"
    return f"cheese/{cheese_type}/cheese_{cheese_type}_{amount}_full.png"


def topping_asset(topping_name, placement="full", amount="normal"):
    """Return asset path for a topping. e.g. toppings/pepperoni/topping_pepperoni_normal_full.png"""
    if placement == "left":
        suffix = "left_half"
    elif placement == "right":
        suffix = "right_half"
    else:
        suffix = "full"
    return f"toppings/{topping_name}/topping_{topping_name}_{amount}_{suffix}.png"


def finish_asset(finish_type):
    """Return asset path for a finish. e.g. finish/parmesan/finish_parmesan_light_full.png"""
    return f"finish/{finish_type}/finish_{finish_type}_light_full.png"


# ─────────────────────────────────────────────────────────────────────────────
# Price Calculation
# ─────────────────────────────────────────────────────────────────────────────

def calculate_pizza_price(pizza):
    """Calculate the price of a single pizza dict.

    Returns the total price as a float rounded to 2 decimal places.
    """
    size = pizza.get("size", "large")
    base = SIZES.get(size, SIZES["large"])["price"]

    crust = pizza.get("crust") or {}
    crust_type = crust.get("type", "hand_tossed")
    crust_up = CRUSTS.get(crust_type, {}).get("upcharge", 0)

    sauce = pizza.get("sauce") or {}
    sauce_type = sauce.get("type", "classic_red")
    sauce_up = SAUCES.get(sauce_type, {}).get("upcharge", 0)

    cheese = pizza.get("cheese") or {}
    cheese_type = cheese.get("type", "mozzarella")
    cheese_up = CHEESES.get(cheese_type, {}).get("upcharge", 0)

    topping_total = 0.0
    for t in pizza.get("toppings", []):
        tp = TOPPINGS.get(t["name"], {}).get("price", 0)
        if t.get("placement") in ("left", "right"):
            tp = round(tp / 2, 2)
        topping_total += tp

    finish_total = 0.0
    for f in pizza.get("finishes", []):
        finish_total += FINISHES.get(f, {}).get("upcharge", 0)

    # Apply specialty discount if applicable
    discount = pizza.get("discount", 0)

    total = base + crust_up + sauce_up + cheese_up + topping_total + finish_total - discount
    return round(max(total, 0), 2)


def calculate_order_totals(order):
    """Calculate subtotal, tax, and total for the full order.

    Returns (subtotal, tax, total) tuple.
    """
    subtotal = 0.0

    for p in order.get("pizzas", []):
        subtotal += p.get("price", 0)

    for s in order.get("sides", []):
        subtotal += s.get("price", 0) * s.get("quantity", 1)

    for d in order.get("drinks", []):
        subtotal += d.get("price", 0) * d.get("quantity", 1)

    subtotal = round(subtotal, 2)
    tax = round(subtotal * TAX_RATE, 2)
    total = round(subtotal + tax, 2)
    return subtotal, tax, total


# ─────────────────────────────────────────────────────────────────────────────
# Pizza State Helpers
# ─────────────────────────────────────────────────────────────────────────────

def new_pizza(size="large"):
    """Return a fresh pizza dict with defaults."""
    return {
        "size": size,
        "crust": None,
        "sauce": None,
        "cheese": None,
        "toppings": [],
        "finishes": [],
        "price": SIZES.get(size, SIZES["large"])["price"],
        "discount": 0,
    }


def new_order():
    """Return a fresh order dict."""
    return {
        "pizzas": [],
        "sides": [],
        "drinks": [],
        "subtotal": 0.00,
        "tax": 0.00,
        "total": 0.00,
        "order_number": None,
    }


def build_specialty(specialty_key, size="large"):
    """Build a complete pizza dict from a specialty preset."""
    spec = SPECIALTIES.get(specialty_key)
    if not spec:
        return None

    pizza = new_pizza(size)
    pizza["crust"] = dict(spec["crust"])
    pizza["sauce"] = dict(spec["sauce"])
    pizza["cheese"] = dict(spec["cheese"])
    pizza["toppings"] = [dict(t) for t in spec["toppings"]]
    pizza["finishes"] = list(spec.get("finishes", []))
    pizza["discount"] = spec.get("discount", 0)
    pizza["specialty"] = specialty_key
    pizza["price"] = calculate_pizza_price(pizza)
    return pizza


def get_pizza_layers(pizza):
    """Return a list of layer dicts for the frontend renderer.

    Each layer has: category, asset_path, z_index, label
    """
    layers = []

    if pizza.get("crust"):
        c = pizza["crust"]
        layers.append({
            "category": "crust",
            "asset_path": crust_asset(c["type"], c.get("bake", "classic")),
            "z_index": 10,
            "label": CRUSTS.get(c["type"], {}).get("name", c["type"]),
        })

    if pizza.get("sauce") and pizza["sauce"].get("type") != "none":
        s = pizza["sauce"]
        layers.append({
            "category": "sauce",
            "asset_path": sauce_asset(s["type"], s.get("amount", "normal")),
            "z_index": 20,
            "label": SAUCES.get(s["type"], {}).get("name", s["type"]),
        })

    if pizza.get("cheese"):
        ch = pizza["cheese"]
        layers.append({
            "category": "cheese",
            "asset_path": cheese_asset(ch["type"], ch.get("amount", "normal")),
            "z_index": 30,
            "label": CHEESES.get(ch["type"], {}).get("name", ch["type"]),
        })

    for i, t in enumerate(pizza.get("toppings", [])):
        layers.append({
            "category": "topping",
            "asset_path": topping_asset(t["name"], t.get("placement", "full"), t.get("amount", "normal")),
            "z_index": 40 + i,
            "label": TOPPINGS.get(t["name"], {}).get("name", t["name"]),
            "topping_name": t["name"],
            "placement": t.get("placement", "full"),
            "amount": t.get("amount", "normal"),
        })

    for i, f in enumerate(pizza.get("finishes", [])):
        layers.append({
            "category": "finish",
            "asset_path": finish_asset(f),
            "z_index": 90 + i,
            "label": FINISHES.get(f, {}).get("name", f),
        })

    return layers


def pizza_summary(pizza):
    """Return a human-readable summary of a pizza for the order panel."""
    parts = []
    size_info = SIZES.get(pizza.get("size", "large"), {})
    parts.append(size_info.get("name", pizza.get("size", "Large")))

    if pizza.get("crust"):
        parts.append(CRUSTS.get(pizza["crust"]["type"], {}).get("name", ""))

    if pizza.get("sauce") and pizza["sauce"].get("type") != "none":
        s = pizza["sauce"]
        amt = f" ({s.get('amount', 'normal')})" if s.get("amount") != "normal" else ""
        parts.append(SAUCES.get(s["type"], {}).get("name", "") + amt)

    if pizza.get("cheese") and pizza["cheese"].get("type") != "none":
        ch = pizza["cheese"]
        amt = f" ({ch.get('amount', 'normal')})" if ch.get("amount") != "normal" else ""
        parts.append(CHEESES.get(ch["type"], {}).get("name", "") + amt)

    for t in pizza.get("toppings", []):
        placement = ""
        if t.get("placement") in ("left", "right"):
            placement = f" ({t['placement']} half)"
        parts.append(TOPPINGS.get(t["name"], {}).get("name", t["name"]) + placement)

    for f in pizza.get("finishes", []):
        parts.append(FINISHES.get(f, {}).get("name", f))

    return parts
