"""Gino's Pizza - Menu data, pricing, specialty presets, and aliases."""

# ─────────────────────────────────────────────────────────────────────────────
# Size Base Prices
# ─────────────────────────────────────────────────────────────────────────────
SIZES = {
    "small":  {"name": "Small 10\"",  "price": 8.99},
    "medium": {"name": "Medium 12\"", "price": 11.99},
    "large":  {"name": "Large 14\"",  "price": 14.99},
}

# ─────────────────────────────────────────────────────────────────────────────
# Crusts
# ─────────────────────────────────────────────────────────────────────────────
CRUSTS = {
    "thin":        {"name": "Thin Crust",        "upcharge": 0.00},
    "hand_tossed": {"name": "Hand Tossed",       "upcharge": 0.00},
    "deep_dish":   {"name": "Deep Dish",         "upcharge": 2.00},
    "stuffed":     {"name": "Stuffed Crust",     "upcharge": 3.00},
}

BAKES = ["classic", "well_done"]

# ─────────────────────────────────────────────────────────────────────────────
# Sauces
# ─────────────────────────────────────────────────────────────────────────────
SAUCES = {
    "classic_red":    {"name": "Classic Red Sauce",  "upcharge": 0.00},
    "spicy_red":      {"name": "Spicy Red Sauce",    "upcharge": 0.00},
    "white_alfredo":  {"name": "White Alfredo",      "upcharge": 0.50},
    "bbq":            {"name": "BBQ Sauce",          "upcharge": 0.50},
    "none":           {"name": "No Sauce",           "upcharge": 0.00},
}

SAUCE_AMOUNTS = ["light", "normal", "extra"]

# ─────────────────────────────────────────────────────────────────────────────
# Cheese
# ─────────────────────────────────────────────────────────────────────────────
CHEESES = {
    "mozzarella":    {"name": "Mozzarella",     "upcharge": 0.00},
    "cheddar_blend": {"name": "Cheddar Blend",  "upcharge": 0.50},
    "vegan_cheese":  {"name": "Vegan Cheese",   "upcharge": 1.50},
    "none":          {"name": "No Cheese",      "upcharge": 0.00},
}

CHEESE_AMOUNTS = ["light", "normal", "extra"]

# ─────────────────────────────────────────────────────────────────────────────
# Toppings
# ─────────────────────────────────────────────────────────────────────────────
TOPPINGS = {
    "pepperoni":    {"name": "Pepperoni",      "price": 1.50},
    "mushroom":     {"name": "Mushrooms",      "price": 1.00},
    "sausage":      {"name": "Italian Sausage","price": 1.50},
    "green_pepper": {"name": "Green Peppers",  "price": 1.00},
    "onion":        {"name": "Onions",         "price": 1.00},
    "black_olive":  {"name": "Black Olives",   "price": 1.00},
    "bacon":        {"name": "Bacon",          "price": 2.00},
    "pineapple":    {"name": "Pineapple",      "price": 1.00},
    "jalapeno":     {"name": "Jalapenos",      "price": 1.00},
    "tomato":       {"name": "Tomato Slices",  "price": 1.00},
    "basil":        {"name": "Fresh Basil",    "price": 1.00},
    "ham":          {"name": "Ham",            "price": 1.50},
}

TOPPING_AMOUNTS = ["light", "normal", "extra"]
TOPPING_PLACEMENTS = ["full", "left", "right"]

# ─────────────────────────────────────────────────────────────────────────────
# Finishes
# ─────────────────────────────────────────────────────────────────────────────
FINISHES = {
    "parmesan":           {"name": "Parmesan Dusting",       "upcharge": 0.00},
    "red_pepper_flakes":  {"name": "Red Pepper Flakes",      "upcharge": 0.00},
    "garlic_butter":      {"name": "Garlic Butter Drizzle",  "upcharge": 0.50},
    "oregano":            {"name": "Oregano Sprinkle",       "upcharge": 0.00},
}

# ─────────────────────────────────────────────────────────────────────────────
# Specialty Pizzas (preset configurations)
# ─────────────────────────────────────────────────────────────────────────────
SPECIALTIES = {
    "classic_pepperoni": {
        "name": "Classic Pepperoni",
        "discount": 1.00,
        "crust":    {"type": "hand_tossed", "bake": "classic"},
        "sauce":    {"type": "classic_red",  "amount": "normal"},
        "cheese":   {"type": "mozzarella",   "amount": "normal"},
        "toppings": [{"name": "pepperoni", "placement": "full"}],
        "finishes": [],
    },
    "meat_lovers": {
        "name": "Meat Lover's",
        "discount": 2.00,
        "crust":    {"type": "hand_tossed", "bake": "classic"},
        "sauce":    {"type": "classic_red",  "amount": "normal"},
        "cheese":   {"type": "mozzarella",   "amount": "extra"},
        "toppings": [
            {"name": "pepperoni", "placement": "full"},
            {"name": "sausage",   "placement": "full"},
            {"name": "bacon",     "placement": "full"},
        ],
        "finishes": [],
    },
    "veggie_supreme": {
        "name": "Veggie Supreme",
        "discount": 1.50,
        "crust":    {"type": "thin", "bake": "classic"},
        "sauce":    {"type": "classic_red",  "amount": "normal"},
        "cheese":   {"type": "mozzarella",   "amount": "normal"},
        "toppings": [
            {"name": "mushroom",     "placement": "full"},
            {"name": "green_pepper", "placement": "full"},
            {"name": "onion",        "placement": "full"},
            {"name": "black_olive",  "placement": "full"},
        ],
        "finishes": [],
    },
    "hawaiian": {
        "name": "Hawaiian",
        "discount": 1.00,
        "crust":    {"type": "hand_tossed", "bake": "classic"},
        "sauce":    {"type": "classic_red",  "amount": "normal"},
        "cheese":   {"type": "mozzarella",   "amount": "normal"},
        "toppings": [
            {"name": "ham",       "placement": "full"},
            {"name": "pineapple", "placement": "full"},
        ],
        "finishes": [],
    },
    "margherita": {
        "name": "Margherita",
        "discount": 1.00,
        "crust":    {"type": "thin", "bake": "classic"},
        "sauce":    {"type": "classic_red",  "amount": "light"},
        "cheese":   {"type": "mozzarella",   "amount": "normal"},
        "toppings": [
            {"name": "tomato", "placement": "full"},
            {"name": "basil",  "placement": "full"},
        ],
        "finishes": ["oregano"],
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# Sides
# ─────────────────────────────────────────────────────────────────────────────
SIDES = {
    "breadsticks":  {"name": "Breadsticks",          "price": 4.99},
    "garlic_knots": {"name": "Garlic Knots",         "price": 5.99},
    "wings_buffalo": {"name": "Buffalo Wings (8pc)",  "price": 9.99},
    "wings_bbq":    {"name": "BBQ Wings (8pc)",      "price": 9.99},
    "garden_salad": {"name": "Garden Salad",         "price": 5.99},
    "caesar_salad": {"name": "Caesar Salad",         "price": 6.99},
}

# ─────────────────────────────────────────────────────────────────────────────
# Drinks
# ─────────────────────────────────────────────────────────────────────────────
DRINKS = {
    "soda_small":  {"name": "Small Soda",   "price": 1.99},
    "soda_large":  {"name": "Large Soda",   "price": 2.99},
    "water":       {"name": "Bottled Water", "price": 1.99},
    "iced_tea":    {"name": "Iced Tea",      "price": 2.49},
}

# ─────────────────────────────────────────────────────────────────────────────
# Deals
# ─────────────────────────────────────────────────────────────────────────────
DEALS = {
    "two_pizza_deal": {
        "name": "Two Pizza Deal",
        "price": 24.99,
        "description": "Any 2 large pizzas with up to 3 toppings each",
    },
    "family_feast": {
        "name": "Family Feast",
        "price": 34.99,
        "description": "2 large pizzas, breadsticks, and a 2-liter soda",
    },
}

TAX_RATE = 0.10


def get_full_menu():
    """Return the full menu as a JSON-serializable dict for the /api/menu endpoint."""
    return {
        "sizes": SIZES,
        "crusts": CRUSTS,
        "bakes": BAKES,
        "sauces": SAUCES,
        "sauce_amounts": SAUCE_AMOUNTS,
        "cheeses": CHEESES,
        "cheese_amounts": CHEESE_AMOUNTS,
        "toppings": TOPPINGS,
        "topping_amounts": TOPPING_AMOUNTS,
        "topping_placements": TOPPING_PLACEMENTS,
        "finishes": FINISHES,
        "specialties": SPECIALTIES,
        "sides": SIDES,
        "drinks": DRINKS,
        "deals": DEALS,
        "tax_rate": TAX_RATE,
    }
