#!/usr/bin/env python3
"""Gino's Pizza - AI Voice-Driven Pizza Ordering Agent with visual pizza builder."""

import json
import random
import os
import time
import logging
import threading
import warnings
from pathlib import Path
from dotenv import load_dotenv
from signalwire import AgentBase, AgentServer
from signalwire.core.function_result import SwaigFunctionResult
from signalwire.rest import RestClient
from fastapi.responses import JSONResponse

from menu import (
    SIZES, CRUSTS, BAKES, SAUCES, SAUCE_AMOUNTS,
    CHEESES, CHEESE_AMOUNTS, TOPPINGS, TOPPING_AMOUNTS, TOPPING_PLACEMENTS,
    FINISHES, SPECIALTIES, SIDES, DRINKS, TAX_RATE,
    get_full_menu,
)
from pizza_builder import (
    crust_asset, sauce_asset, cheese_asset, topping_asset, finish_asset,
    calculate_pizza_price, calculate_order_totals,
    new_pizza, new_order, build_specialty, get_pizza_layers, pizza_summary,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# SWML Handler Registration (same pattern as Holy Guacamole)
# ─────────────────────────────────────────────────────────────────────────────
swml_handler_info = {
    "id": None,
    "address_id": None,
    "address": None,
}
# Reason the last handler-setup attempt didn't complete (surfaced via /get_token)
swml_setup_error = None
# Serializes the lazy /get_token re-registration so workers don't race
_swml_setup_lock = threading.Lock()


def get_signalwire_host():
    space = os.getenv("SIGNALWIRE_SPACE_NAME", "")
    if not space:
        return None
    return space if "." in space else f"{space}.signalwire.com"


def find_resource_address(addresses, agent_name):
    expected = f"/public/{agent_name}"
    for addr in addresses:
        if addr.get("channels", {}).get("audio", "") == expected:
            return addr
    for addr in addresses:
        ch = addr.get("channels", {}).get("audio", "")
        if ch.startswith("/public/") and not any(c.isdigit() for c in ch.split("/")[-1][:3]):
            return addr
    return addresses[0] if addresses else None


def build_rest_client():
    """Construct a RestClient from env, or None if credentials are incomplete.

    RestClient() with no args reads SIGNALWIRE_API_TOKEN / SIGNALWIRE_SPACE, which
    do NOT match this demo's SIGNALWIRE_TOKEN / SIGNALWIRE_SPACE_NAME convention --
    so always pass project/token/host explicitly.
    """
    sw_host = get_signalwire_host()
    project = os.getenv("SIGNALWIRE_PROJECT_ID", "")
    token = os.getenv("SIGNALWIRE_TOKEN", "")
    if not all([sw_host, project, token]):
        return None
    return RestClient(project=project, token=token, host=sw_host)


def find_existing_handler(client, agent_name):
    try:
        # swml_webhooks == External SWML Handler; response shape matches the
        # legacy REST endpoint 1:1.
        for handler in client.fabric.swml_webhooks.list().get("data", []):
            swml_webhook = handler.get("swml_webhook", {})
            name = swml_webhook.get("name") or handler.get("display_name")
            if name == agent_name:
                hid = handler.get("id")
                addrs = client.fabric.swml_webhooks.list_addresses(hid).get("data", [])
                ra = find_resource_address(addrs, agent_name)
                if ra:
                    return {
                        "id": hid,
                        "name": name,
                        "url": swml_webhook.get("primary_request_url", ""),
                        "address_id": ra["id"],
                        "address": ra["channels"]["audio"],
                    }
    except Exception as e:
        logger.error(f"Error finding handler: {e}")
    return None


def setup_swml_handler():
    global swml_setup_error

    agent_name = os.getenv("AGENT_NAME", "ginospizza")
    proxy_url = os.getenv("SWML_PROXY_URL_BASE", os.getenv("APP_URL", ""))
    auth_user = os.getenv("SWML_BASIC_AUTH_USER", "signalwire")
    auth_pass = os.getenv("SWML_BASIC_AUTH_PASSWORD", "")

    client = build_rest_client()
    if client is None:
        swml_setup_error = "SignalWire credentials not configured"
        logger.warning(f"{swml_setup_error} - skipping handler setup")
        return
    if not proxy_url:
        swml_setup_error = "SWML_PROXY_URL_BASE/APP_URL not set"
        logger.warning(f"{swml_setup_error} - skipping handler setup")
        return

    if auth_user and auth_pass and "://" in proxy_url:
        scheme, rest = proxy_url.split("://", 1)
        swml_url = f"{scheme}://{auth_user}:{auth_pass}@{rest}/swml"
    else:
        swml_url = f"{proxy_url}/swml"

    existing = find_existing_handler(client, agent_name)
    if existing:
        swml_handler_info["id"] = existing["id"]
        swml_handler_info["address_id"] = existing["address_id"]
        swml_handler_info["address"] = existing["address"]
        try:
            client.fabric.swml_webhooks.update(
                existing["id"],
                primary_request_url=swml_url,
                primary_request_method="POST",
            )
            logger.info(f"Updated SWML handler: {existing['name']}")
        except Exception as e:
            logger.error(f"Failed to update handler: {e}")
        swml_setup_error = None
    else:
        try:
            with warnings.catch_warnings():
                # create() emits a DeprecationWarning steering phone-number setups
                # toward phone_numbers.set_swml_webhook; a standalone dialable
                # handler (guest tokens dial its /public/{name} address) is intended.
                warnings.simplefilter("ignore", DeprecationWarning)
                handler = client.fabric.swml_webhooks.create(
                    name=agent_name,
                    used_for="calling",
                    primary_request_url=swml_url,
                    primary_request_method="POST",
                )
            hid = handler.get("id")
            swml_handler_info["id"] = hid
            addrs = client.fabric.swml_webhooks.list_addresses(hid).get("data", [])
            ra = find_resource_address(addrs, agent_name)
            if ra:
                swml_handler_info["address_id"] = ra["id"]
                swml_handler_info["address"] = ra["channels"]["audio"]
                swml_setup_error = None
            else:
                swml_setup_error = "No address found for created handler"
            logger.info(f"Created SWML handler '{agent_name}'")
        except Exception as e:
            swml_setup_error = f"Failed to create handler: {e}"
            logger.error(swml_setup_error)
            time.sleep(0.5)
            existing = find_existing_handler(client, agent_name)
            if existing:
                swml_handler_info.update({
                    "id": existing["id"],
                    "address_id": existing["address_id"],
                    "address": existing["address"],
                })
                swml_setup_error = None


# ═════════════════════════════════════════════════════════════════════════════
# Agent Definition
# ═════════════════════════════════════════════════════════════════════════════

class GinosPizzaAgent(AgentBase):
    """Gino - Your Gino's Pizza Order Assistant"""

    def __init__(self):
        super().__init__(
            name="Gino",
            route="/swml",
            record_call=True,
        )

        # ── Personality ──────────────────────────────────────────────────
        self.prompt_add_section(
            "Personality",
            "You are Gino, a passionate Italian-American pizzaiolo who's been making pizza for 30 years. "
            "You're warm, expressive, and genuinely love what you do. Use occasional Italian expressions "
            "like 'Bellissimo!', 'Mamma mia!', 'Perfetto!', 'Che bella pizza!'. "
            "You have strong (friendly) opinions about pizza — if someone orders pineapple you might playfully say "
            "'Ah, the Hawaiian! My cousin Vinnie swears by it, me, I'm not so sure... but hey, the customer is always right!' "
            "Give brief, appetizing descriptions when relevant: 'Our white alfredo is nice and creamy', "
            "'The BBQ sauce has a great smoky kick', 'Extra cheese? Now you're talking my language!' "
            "The customer has a screen showing their pizza being built visually and their order summary, "
            "so NEVER read back the full order or list all the layers - they can see it! "
            "Keep responses concise — one or two sentences max. Be enthusiastic but not annoying. "
            "CRITICAL: When the customer orders a specialty by name (pepperoni pizza, meat lovers, veggie supreme, hawaiian, margherita), "
            "you MUST use order_specialty - NEVER use start_pizza for these. order_specialty handles everything automatically."
        )


        # ── Voice ────────────────────────────────────────────────────────
        self.add_language("English", "en-US", "inworld.Gianni:inworld-tts-1.5-max")
        self.add_hints([
            "Gino's", "Gino", "pepperoni", "mozzarella", "mozz", "marinara",
            "alfredo", "al fredo", "deep dish", "stuffed crust", "hand tossed",
            "thin crust", "well done", "half and half", "breadsticks", "garlic knots",
            "jalapeno", "jalapenos", "hala peen yo", "basil", "margherita",
            "mar gah ree tah", "oregano", "ham", "tomato", "Hawaiian",
            "pineapple", "sausage", "mushroom", "mushrooms", "black olive",
            "black olives", "green pepper", "green peppers", "onion", "onions",
            "bacon", "cheddar", "vegan", "parmesan", "red pepper flakes",
            "garlic butter", "caesar", "buffalo", "BBQ",
        ])

        self.set_post_prompt("Summarize the pizza order conversation.")

        # ── State Machine ────────────────────────────────────────────────
        self._define_state_machine()

        # ── Tools ────────────────────────────────────────────────────────
        self._define_tools()

    # ─────────────────────────────────────────────────────────────────────
    # State Machine
    # ─────────────────────────────────────────────────────────────────────
    def _define_state_machine(self):
        contexts = self.define_contexts()
        ctx = contexts.add_context("default") \
            .add_section("Goal", "Take pizza orders and build them visually on the customer's screen.")

        # GREETING
        ctx.add_step("greeting") \
            .add_section("Task", "Welcome the customer and find out what they want") \
            .add_bullets("Process", [
                "If this is the start of the call, welcome them warmly to Gino's Pizza",
                "Ask if they'd like a specialty or a custom pizza",
                "Mention our specialties: Classic Pepperoni, Meat Lover's, Veggie Supreme, Hawaiian, and Margherita",
                "ALWAYS ask what SIZE they want: small (10 inch), medium (12 inch), or large (14 inch)",
                "IMPORTANT: If they name a specialty (pepperoni, meat lovers, veggie, hawaiian, margherita), use order_specialty with the size",
                "If they want custom, use start_pizza with the size, which will move to building step",
                "Do NOT proceed without knowing the size first",
                "If they only want sides or drinks (no pizza), use order_sides_only",
                "If they ask about the menu, use show_menu",
            ]) \
            .set_step_criteria("Customer has chosen size and type of pizza") \
            .set_functions(["start_pizza", "order_specialty", "order_sides_only", "show_menu"]) \
            .set_valid_steps(["choose_crust", "confirming_pizza", "ordering_sides"])

        # CHOOSE CRUST
        ctx.add_step("choose_crust") \
            .add_section("Task", "Ask what crust type. If they also mention bake preference (well done), include it.") \
            .add_bullets("Process", [
                "Ask: thin, hand tossed, deep dish, or stuffed crust?",
                "Call select_crust with their choice",
                "If they also mention bake preference (e.g. 'thin crust well done'), include the bake parameter too",
            ]) \
            .set_step_criteria("Customer picks a crust") \
            .set_functions(["select_crust", "cancel_pizza", "cancel_order", "show_menu"]) \
            .set_valid_steps(["choose_bake", "choose_sauce", "confirming_pizza", "greeting"])

        # CHOOSE BAKE
        ctx.add_step("choose_bake") \
            .add_section("Task", "Ask how they want the crust baked") \
            .add_bullets("Process", [
                "Ask: classic or well done?",
                "Call select_bake with their choice",
            ]) \
            .set_step_criteria("Customer picks a bake level") \
            .set_functions(["select_bake", "cancel_pizza", "cancel_order"]) \
            .set_valid_steps(["choose_sauce", "confirming_pizza", "greeting"])

        # CHOOSE SAUCE
        ctx.add_step("choose_sauce") \
            .add_section("Task", "Ask what sauce they want") \
            .add_bullets("Process", [
                "Ask: classic red, spicy red, white alfredo, BBQ, or no sauce?",
                "Call select_sauce with their choice",
            ]) \
            .set_step_criteria("Customer picks a sauce") \
            .set_functions(["select_sauce", "cancel_pizza", "cancel_order"]) \
            .set_valid_steps(["choose_sauce_amount", "choose_cheese", "confirming_pizza", "greeting"])

        # CHOOSE SAUCE AMOUNT
        ctx.add_step("choose_sauce_amount") \
            .add_section("Task", "Ask how much sauce they want") \
            .add_bullets("Process", [
                "Ask: light, normal, or extra?",
                "Call select_sauce_amount with their choice",
                "If they chose no sauce, this was already skipped",
            ]) \
            .set_step_criteria("Customer picks sauce amount") \
            .set_functions(["select_sauce_amount", "cancel_pizza", "cancel_order"]) \
            .set_valid_steps(["choose_cheese", "confirming_pizza", "greeting"])

        # CHOOSE CHEESE
        ctx.add_step("choose_cheese") \
            .add_section("Task", "Ask what cheese they want") \
            .add_bullets("Process", [
                "Ask: mozzarella, cheddar blend, vegan cheese, or no cheese?",
                "Call select_cheese with their choice",
            ]) \
            .set_step_criteria("Customer picks a cheese") \
            .set_functions(["select_cheese", "cancel_pizza", "cancel_order"]) \
            .set_valid_steps(["choose_cheese_amount", "add_toppings", "confirming_pizza", "greeting"])

        # CHOOSE CHEESE AMOUNT
        ctx.add_step("choose_cheese_amount") \
            .add_section("Task", "Ask how much cheese they want") \
            .add_bullets("Process", [
                "Ask: light, normal, or extra?",
                "Call select_cheese_amount with their choice",
                "If they chose no cheese, this was already skipped",
            ]) \
            .set_step_criteria("Customer picks cheese amount") \
            .set_functions(["select_cheese_amount", "cancel_pizza", "cancel_order"]) \
            .set_valid_steps(["add_toppings", "confirming_pizza", "greeting"])

        # ADD TOPPINGS
        ctx.add_step("add_toppings") \
            .add_section("Task", "Ask what toppings they want") \
            .add_bullets("Process", [
                "Ask what toppings they'd like",
                "12 options: pepperoni, mushrooms, sausage, green peppers, onions, black olives, bacon, pineapple, jalapenos, tomato, basil, ham",
                "Call add_topping for each topping they want (defaults: placement=full, amount=normal)",
                "Only ask about placement or amount if the customer specifically mentions it",
                "They can add multiple toppings - keep asking until they're done",
                "If they don't want any toppings, call done_with_toppings immediately",
                "When done with toppings, call done_with_toppings",
                "CRITICAL: Call add_topping for EACH topping separately",
            ]) \
            .set_step_criteria("Customer says they're done with toppings") \
            .set_functions(["add_topping", "remove_topping", "done_with_toppings", "cancel_pizza", "cancel_order", "show_menu"]) \
            .set_valid_steps(["add_finishes", "confirming_pizza", "greeting"])

        # ADD FINISHES
        ctx.add_step("add_finishes") \
            .add_section("Task", "Ask if they want any finishing touches") \
            .add_bullets("Process", [
                "Ask: 'Want any extras on top? We can add a parmesan dusting, red pepper flakes, an oregano sprinkle, or a garlic butter drizzle'",
                "Call select_finish for each one they want",
                "If they don't want any finishes, call done_with_pizza immediately",
                "When done, call done_with_pizza to complete the pizza",
            ]) \
            .set_step_criteria("Customer is done with finishes") \
            .set_functions(["select_finish", "done_with_pizza", "cancel_pizza", "cancel_order", "show_menu"]) \
            .set_valid_steps(["confirming_pizza", "greeting"])

        # CONFIRMING PIZZA
        ctx.add_step("confirming_pizza") \
            .add_section("Task", "Confirm the completed pizza") \
            .add_bullets("Process", [
                "The customer can see the pizza on their screen",
                "Ask if the pizza looks good",
                "If they just want to change the SIZE, use change_pizza_size - do NOT go through the full modify flow",
                "If they want to change toppings, use modify_pizza which goes to the toppings step where they can add/remove toppings, then finish",
                "If they want another pizza:",
                "  - If they name a SPECIALTY (pepperoni, meat lovers, veggie, hawaiian, margherita), ask the SIZE then use order_specialty",
                "  - If they want CUSTOM, ask the SIZE then use add_another_pizza",
                "If they're done with pizzas, ask about sides and drinks",
                "If confirmed and no more pizzas, use confirm_pizza to move to ordering_sides",
            ]) \
            .set_step_criteria("Customer confirms pizza or wants to add sides") \
            .set_functions(["confirm_pizza", "change_pizza_size", "modify_pizza", "add_another_pizza", "order_specialty", "cancel_pizza", "cancel_order", "show_menu"]) \
            .set_valid_steps(["add_toppings", "confirming_pizza", "ordering_sides", "greeting"])

        # ORDERING SIDES
        ctx.add_step("ordering_sides") \
            .add_section("Task", "Add sides and drinks to the order") \
            .add_bullets("Process", [
                "First ask about sides, then ask about drinks",
                "Use add_side and add_drink for each item",
                "They can also add another pizza from here",
                "When they're done, use finalize_order",
            ]) \
            .set_step_criteria("Customer says they're done ordering") \
            .set_functions([
                "add_side", "remove_side", "add_drink", "remove_drink",
                "review_order", "finalize_order", "add_another_pizza", "order_specialty",
                "cancel_order", "show_menu",
            ]) \
            .set_valid_steps(["choose_crust", "confirming_pizza", "payment", "greeting"])

        # PAYMENT
        ctx.add_step("payment") \
            .add_section("Task", "Process payment and give order number") \
            .add_bullets("Process", [
                "Tell them the total from ${global_data.order.total}",
                "Call process_payment to generate the order number",
            ]) \
            .set_step_criteria("Payment processed") \
            .set_functions(["process_payment", "cancel_order"]) \
            .set_valid_steps(["order_complete_pending", "greeting"])

        # ORDER COMPLETE PENDING
        ctx.add_step("order_complete_pending") \
            .add_section("Task", "Give the order number and thank the customer") \
            .add_bullets("Process", [
                "Give them the order number",
                "Thank them for ordering from Gino's Pizza",
                "Call complete_order to finish",
            ]) \
            .set_step_criteria("Order completed") \
            .set_functions(["complete_order"]) \
            .set_valid_steps(["order_complete"])

        # ORDER COMPLETE
        ctx.add_step("order_complete") \
            .add_section("Task", "Order is complete") \
            .add_bullets("Process", [
                "Thank the customer warmly",
                "Tell them their pizza will be ready soon",
                "If they want another order, use new_order",
            ]) \
            .set_functions(["new_order"]) \
            .set_valid_steps(["greeting"])

    # ─────────────────────────────────────────────────────────────────────
    # SWAIG Tools
    # ─────────────────────────────────────────────────────────────────────
    def _define_tools(self):

        def get_state(raw_data):
            """Extract current_pizza and order from global_data."""
            gd = (raw_data or {}).get("global_data", {})
            cp = gd.get("current_pizza")
            order = gd.get("order")
            if order is None:
                order = new_order()
            return cp, order, gd

        def save_state(result, current_pizza, order, gd):
            """Persist state back into global_data and update order totals."""
            order["subtotal"], order["tax"], order["total"] = calculate_order_totals(order)
            gd["current_pizza"] = current_pizza
            gd["order"] = order
            result.update_global_data(gd)
            return result

        def order_totals_payload(order):
            """Return the standard totals dict included in every event."""
            return {
                "subtotal": order["subtotal"],
                "tax": order["tax"],
                "total": order["total"],
            }

        def emit(result, event_data):
            """Emit a user event to the frontend via SWML user_event."""
            logger.info(f"EMIT EVENT: {event_data.get('type', 'unknown')} -> {event_data}")
            result.swml_user_event(event_data)
            return result

        # ── start_pizza ──────────────────────────────────────────────────

        @self.tool(
            name="start_pizza",
            description="Start building a new custom pizza. Call this first before adding layers.",
            parameters={
                "type": "object",
                "properties": {
                    "size": {
                        "type": "string",
                        "description": "Pizza size",
                        "enum": list(SIZES.keys()),
                    },
                },
                "required": ["size"],
            },
            wait_file="/keyspressing.mp3",
        )
        def start_pizza(args, raw_data):
            logger.info(f"TOOL CALLED: start_pizza args={args}")
            cp, order, gd = get_state(raw_data)
            size = args.get("size", "large")
            if size not in SIZES:
                size = "large"

            cp = new_pizza(size)
            pizza_index = len(order["pizzas"])
            cp["index"] = pizza_index

            result = SwaigFunctionResult(
                f"Great! Starting a {SIZES[size]['name']} pizza. What crust would you like? "
                "We have thin, hand tossed, deep dish, or stuffed crust."
            )
            save_state(result, cp, order, gd)

            emit(result,{
                "type": "pizza_started",
                "pizza_index": pizza_index,
                "size": size,
                "size_name": SIZES[size]["name"],
                **order_totals_payload(order),
            })
            result.swml_change_step("choose_crust")
            return result

        # ── order_specialty ──────────────────────────────────────────────

        @self.tool(
            name="order_specialty",
            description="Order a specialty pizza by name. Must include size (small/medium/large).",
            parameters={
                "type": "object",
                "properties": {
                    "specialty_name": {
                        "type": "string",
                        "description": "Specialty pizza name",
                        "enum": list(SPECIALTIES.keys()),
                    },
                    "size": {
                        "type": "string",
                        "description": "Pizza size",
                        "enum": list(SIZES.keys()),
                    },
                },
                "required": ["specialty_name", "size"],
            },
            wait_file="/keyspressing.mp3",
        )
        def order_specialty(args, raw_data):
            logger.info(f"TOOL CALLED: order_specialty args={args}")
            cp, order, gd = get_state(raw_data)
            spec_key = args["specialty_name"]
            size = args.get("size", "large")

            pizza = build_specialty(spec_key, size)
            if not pizza:
                return SwaigFunctionResult(
                    "I couldn't find that specialty. We have Classic Pepperoni, "
                    "Meat Lover's, Veggie Supreme, Hawaiian, and Margherita."
                )

            pizza_index = len(order["pizzas"])
            pizza["index"] = pizza_index
            pizza["summary"] = pizza_summary(pizza)

            order["pizzas"].append(pizza)
            order["subtotal"], order["tax"], order["total"] = calculate_order_totals(order)
            cp = None  # no pizza being built

            spec_name = SPECIALTIES[spec_key]["name"]
            result = SwaigFunctionResult(
                f"One {SIZES[size]['name']} {spec_name} coming right up! "
                "Your pizza is on the screen. Would you like another pizza, "
                "or shall we move on to sides and drinks?"
            )
            save_state(result, cp, order, gd)

            # Emit single compound event with all layers for frontend to unpack
            layers = get_pizza_layers(pizza)
            emit(result,{
                "type": "specialty_pizza",
                "pizza_index": pizza_index,
                "size": size,
                "size_name": SIZES[size]["name"],
                "layers": layers,
                "pizza": pizza,
                "summary": pizza_summary(pizza),
                **order_totals_payload(order),
            })
            result.swml_change_step("confirming_pizza")
            return result

        # ── show_menu ────────────────────────────────────────────────────

        @self.tool(
            name="show_menu",
            description="Tell the customer to check the menu on their screen",
            parameters={"type": "object", "properties": {}, "required": []},
        )
        def show_menu(args, raw_data):
            result = SwaigFunctionResult(
                "Everything's on the menu on your screen! We have sizes from small to large, "
                "four crust types, various sauces and cheeses, eight topping options, "
                "plus sides and drinks. Or try one of our specialty pizzas!"
            )
            emit(result,{"type": "show_menu"})
            return result

        # ── select_crust ─────────────────────────────────────────────────

        @self.tool(
            name="select_crust",
            description="Set the crust type for the current pizza. Optionally include bake preference.",
            parameters={
                "type": "object",
                "properties": {
                    "crust_type": {
                        "type": "string",
                        "description": "Crust type",
                        "enum": list(CRUSTS.keys()),
                    },
                    "bake": {
                        "type": "string",
                        "description": "Bake level (optional, defaults to classic)",
                        "enum": BAKES,
                    },
                },
                "required": ["crust_type"],
            },
            wait_file="/keyspressing.mp3",
        )
        def select_crust(args, raw_data):
            logger.info(f"TOOL CALLED: select_crust args={args}")
            cp, order, gd = get_state(raw_data)
            if not cp:
                return SwaigFunctionResult("No pizza started yet.")

            crust_type = args["crust_type"]
            if crust_type not in CRUSTS:
                return SwaigFunctionResult(f"We don't have that crust. Options: {', '.join(CRUSTS.keys())}")

            bake = args.get("bake", "classic")
            cp["crust"] = {"type": crust_type, "bake": bake}
            cp["price"] = calculate_pizza_price(cp)

            crust_name = CRUSTS[crust_type]["name"]

            if "bake" in args:
                # Bake was explicitly provided, skip choose_bake
                bake_str = " well done" if bake == "well_done" else " classic"
                result = SwaigFunctionResult(
                    f"{crust_name}{bake_str}! Now, what sauce would you like? "
                    "Classic red, spicy red, white alfredo, BBQ, or no sauce?"
                )
                save_state(result, cp, order, gd)
                emit(result, {
                    "type": "layer_added",
                    "pizza_index": cp.get("index", 0),
                    "category": "crust",
                    "asset_path": crust_asset(crust_type, bake),
                    "z_index": 10,
                    "label": f"{crust_name} ({bake})",
                    "pizza_price": cp["price"],
                    **order_totals_payload(order),
                })
                result.swml_change_step("choose_sauce")
            else:
                # No bake provided, ask about it
                result = SwaigFunctionResult(
                    f"{crust_name}, great choice! Would you like that classic or well done?"
                )
                save_state(result, cp, order, gd)
                result.swml_change_step("choose_bake")
            return result

        # ── select_bake ──────────────────────────────────────────────────

        @self.tool(
            name="select_bake",
            description="Set the bake level for the current pizza crust",
            parameters={
                "type": "object",
                "properties": {
                    "bake": {
                        "type": "string",
                        "description": "Bake level",
                        "enum": BAKES,
                    },
                },
                "required": ["bake"],
            },
            wait_file="/keyspressing.mp3",
        )
        def select_bake(args, raw_data):
            logger.info(f"TOOL CALLED: select_bake args={args}")
            cp, order, gd = get_state(raw_data)
            if not cp:
                return SwaigFunctionResult("No pizza started yet.")

            bake = args["bake"]
            if not cp.get("crust"):
                return SwaigFunctionResult("Please select a crust type first.")

            cp["crust"]["bake"] = bake

            # Re-emit the crust layer with the correct bake asset
            crust_type = cp["crust"]["type"]
            crust_name = CRUSTS[crust_type]["name"]
            bake_str = " well done" if bake == "well_done" else " classic"

            result = SwaigFunctionResult(
                f"{crust_name}{bake_str}! Now, what sauce would you like? "
                "Classic red, spicy red, white alfredo, BBQ, or no sauce?"
            )
            save_state(result, cp, order, gd)
            emit(result, {
                "type": "layer_added",
                "pizza_index": cp.get("index", 0),
                "category": "crust",
                "asset_path": crust_asset(crust_type, bake),
                "z_index": 10,
                "label": f"{crust_name} ({bake})",
                "pizza_price": cp["price"],
                **order_totals_payload(order),
            })
            result.swml_change_step("choose_sauce")
            return result

        # ── select_sauce ─────────────────────────────────────────────────

        @self.tool(
            name="select_sauce",
            description="Set the sauce type for the current pizza",
            parameters={
                "type": "object",
                "properties": {
                    "sauce_type": {
                        "type": "string",
                        "description": "Sauce type",
                        "enum": list(SAUCES.keys()),
                    },
                },
                "required": ["sauce_type"],
            },
            wait_file="/keyspressing.mp3",
        )
        def select_sauce(args, raw_data):
            logger.info(f"TOOL CALLED: select_sauce args={args}")
            cp, order, gd = get_state(raw_data)
            if not cp:
                return SwaigFunctionResult("No pizza started yet.")

            sauce_type = args["sauce_type"]
            cp["sauce"] = {"type": sauce_type, "amount": "normal"}
            cp["price"] = calculate_pizza_price(cp)

            sauce_name = SAUCES.get(sauce_type, {}).get("name", sauce_type)

            if sauce_type == "none":
                result = SwaigFunctionResult(
                    "No sauce it is! What cheese would you like? "
                    "Mozzarella, cheddar blend, vegan cheese, or no cheese?"
                )
                save_state(result, cp, order, gd)
                result.swml_change_step("choose_cheese")
            else:
                result = SwaigFunctionResult(
                    f"{sauce_name}, nice! How much - light, normal, or extra?"
                )
                save_state(result, cp, order, gd)
                result.swml_change_step("choose_sauce_amount")
            return result

        # ── select_sauce_amount ──────────────────────────────────────────

        @self.tool(
            name="select_sauce_amount",
            description="Set the sauce amount for the current pizza",
            parameters={
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "string",
                        "description": "Sauce amount",
                        "enum": SAUCE_AMOUNTS,
                    },
                },
                "required": ["amount"],
            },
            wait_file="/keyspressing.mp3",
        )
        def select_sauce_amount(args, raw_data):
            logger.info(f"TOOL CALLED: select_sauce_amount args={args}")
            cp, order, gd = get_state(raw_data)
            if not cp:
                return SwaigFunctionResult("No pizza started yet.")

            amount = args["amount"]
            if not cp.get("sauce"):
                return SwaigFunctionResult("Please select a sauce type first.")

            cp["sauce"]["amount"] = amount
            cp["price"] = calculate_pizza_price(cp)

            sauce_type = cp["sauce"]["type"]
            sauce_name = SAUCES.get(sauce_type, {}).get("name", sauce_type)

            result = SwaigFunctionResult(
                f"{amount} {sauce_name}! What cheese would you like? "
                "Mozzarella, cheddar blend, vegan cheese, or no cheese?"
            )
            save_state(result, cp, order, gd)
            asset = sauce_asset(sauce_type, amount)
            if asset:
                emit(result, {
                    "type": "layer_added",
                    "pizza_index": cp.get("index", 0),
                    "category": "sauce",
                    "asset_path": asset,
                    "z_index": 20,
                    "label": f"{sauce_name} ({amount})",
                    "pizza_price": cp["price"],
                    **order_totals_payload(order),
                })
            result.swml_change_step("choose_cheese")
            return result

        # ── select_cheese ────────────────────────────────────────────────

        @self.tool(
            name="select_cheese",
            description="Set the cheese type for the current pizza",
            parameters={
                "type": "object",
                "properties": {
                    "cheese_type": {
                        "type": "string",
                        "description": "Cheese type",
                        "enum": list(CHEESES.keys()),
                    },
                },
                "required": ["cheese_type"],
            },
            wait_file="/keyspressing.mp3",
        )
        def select_cheese(args, raw_data):
            logger.info(f"TOOL CALLED: select_cheese args={args}")
            cp, order, gd = get_state(raw_data)
            if not cp:
                return SwaigFunctionResult("No pizza started yet.")

            cheese_type = args["cheese_type"]
            cp["cheese"] = {"type": cheese_type, "amount": "normal"}
            cp["price"] = calculate_pizza_price(cp)

            cheese_name = CHEESES.get(cheese_type, {}).get("name", cheese_type)

            if cheese_type == "none":
                result = SwaigFunctionResult(
                    "No cheese! What toppings would you like?"
                )
                save_state(result, cp, order, gd)
                emit(result, {
                    "type": "layer_added",
                    "pizza_index": cp.get("index", 0),
                    "category": "cheese",
                    "asset_path": cheese_asset("none"),
                    "z_index": 30,
                    "label": cheese_name,
                    "pizza_price": cp["price"],
                    **order_totals_payload(order),
                })
                result.swml_change_step("add_toppings")
            else:
                result = SwaigFunctionResult(
                    f"{cheese_name}! How much - light, normal, or extra?"
                )
                save_state(result, cp, order, gd)
                result.swml_change_step("choose_cheese_amount")
            return result

        # ── select_cheese_amount ─────────────────────────────────────────

        @self.tool(
            name="select_cheese_amount",
            description="Set the cheese amount for the current pizza",
            parameters={
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "string",
                        "description": "Cheese amount",
                        "enum": CHEESE_AMOUNTS,
                    },
                },
                "required": ["amount"],
            },
            wait_file="/keyspressing.mp3",
        )
        def select_cheese_amount(args, raw_data):
            logger.info(f"TOOL CALLED: select_cheese_amount args={args}")
            cp, order, gd = get_state(raw_data)
            if not cp:
                return SwaigFunctionResult("No pizza started yet.")

            amount = args["amount"]
            if not cp.get("cheese"):
                return SwaigFunctionResult("Please select a cheese type first.")

            cp["cheese"]["amount"] = amount
            cp["price"] = calculate_pizza_price(cp)

            cheese_type = cp["cheese"]["type"]
            cheese_name = CHEESES.get(cheese_type, {}).get("name", cheese_type)

            result = SwaigFunctionResult(
                f"{amount} {cheese_name}! Now what toppings would you like?"
            )
            save_state(result, cp, order, gd)
            emit(result, {
                "type": "layer_added",
                "pizza_index": cp.get("index", 0),
                "category": "cheese",
                "asset_path": cheese_asset(cheese_type, amount),
                "z_index": 30,
                "label": f"{cheese_name} ({amount})",
                "pizza_price": cp["price"],
                **order_totals_payload(order),
            })
            result.swml_change_step("add_toppings")
            return result

        # ── add_topping ──────────────────────────────────────────────────

        @self.tool(
            name="add_topping",
            description="Add a topping to the current pizza. Can specify amount (light/normal/extra) and placement (full/left/right).",
            parameters={
                "type": "object",
                "properties": {
                    "topping": {
                        "type": "string",
                        "description": "Topping name",
                        "enum": list(TOPPINGS.keys()),
                    },
                    "placement": {
                        "type": "string",
                        "description": "Where to place the topping",
                        "enum": TOPPING_PLACEMENTS,
                    },
                    "amount": {
                        "type": "string",
                        "description": "How much topping (light, normal, or extra)",
                        "enum": TOPPING_AMOUNTS,
                    },
                },
                "required": ["topping"],
            },
            wait_file="/keyspressing.mp3",
        )
        def add_topping(args, raw_data):
            logger.info(f"TOOL CALLED: add_topping args={args}")
            cp, order, gd = get_state(raw_data)
            if not cp:
                return SwaigFunctionResult("No pizza started yet.")

            topping = args["topping"]
            placement = args.get("placement", "full")
            amount = args.get("amount", "normal")

            if topping not in TOPPINGS:
                return SwaigFunctionResult(
                    f"We don't have {topping}. Options: {', '.join(TOPPINGS.keys())}"
                )

            # Check for duplicate
            for t in cp["toppings"]:
                if t["name"] == topping and t["placement"] == placement:
                    return SwaigFunctionResult(f"You already have {TOPPINGS[topping]['name']} on your pizza!")

            cp["toppings"].append({"name": topping, "placement": placement, "amount": amount})
            cp["price"] = calculate_pizza_price(cp)

            topping_name = TOPPINGS[topping]["name"]
            placement_str = f" on the {placement} half" if placement != "full" else ""
            amount_str = f" ({amount})" if amount != "normal" else ""
            result = SwaigFunctionResult(
                f"Added {topping_name}{amount_str}{placement_str}! "
                "Want any more toppings, or are you ready for a finish?"
            )
            save_state(result, cp, order, gd)

            z_index = 40 + len(cp["toppings"]) - 1
            emit(result,{
                "type": "layer_added",
                "pizza_index": cp.get("index", 0),
                "category": "topping",
                "asset_path": topping_asset(topping, placement, amount),
                "z_index": z_index,
                "label": topping_name,
                "topping_name": topping,
                "placement": placement,
                "amount": amount,
                "pizza_price": cp["price"],
                **order_totals_payload(order),
            })
            return result

        # ── remove_topping ───────────────────────────────────────────────

        @self.tool(
            name="remove_topping",
            description="Remove a topping from the current pizza",
            parameters={
                "type": "object",
                "properties": {
                    "topping": {
                        "type": "string",
                        "description": "Topping to remove",
                        "enum": list(TOPPINGS.keys()),
                    },
                },
                "required": ["topping"],
            },
            wait_file="/keyspressing.mp3",
        )
        def remove_topping(args, raw_data):
            cp, order, gd = get_state(raw_data)
            if not cp:
                return SwaigFunctionResult("No pizza started yet.")

            topping = args["topping"]
            original_len = len(cp["toppings"])
            cp["toppings"] = [t for t in cp["toppings"] if t["name"] != topping]

            if len(cp["toppings"]) == original_len:
                return SwaigFunctionResult(f"You don't have {TOPPINGS.get(topping, {}).get('name', topping)} on this pizza.")

            cp["price"] = calculate_pizza_price(cp)

            topping_name = TOPPINGS.get(topping, {}).get("name", topping)
            result = SwaigFunctionResult(f"Removed {topping_name} from your pizza.")
            save_state(result, cp, order, gd)

            emit(result,{
                "type": "layer_removed",
                "pizza_index": cp.get("index", 0),
                "category": "topping",
                "topping_name": topping,
                "label": topping_name,
                **order_totals_payload(order),
            })
            return result

        # ── done_with_toppings ────────────────────────────────────────────

        @self.tool(
            name="done_with_toppings",
            description="Customer is done adding toppings, move to finishes",
            parameters={"type": "object", "properties": {}, "required": []},
            wait_file="/keyspressing.mp3",
        )
        def done_with_toppings(args, raw_data):
            logger.info(f"TOOL CALLED: done_with_toppings")
            cp, order, gd = get_state(raw_data)
            result = SwaigFunctionResult(
                "Bellissimo! Want any extras on top? A parmesan dusting, red pepper flakes, "
                "oregano sprinkle, or garlic butter drizzle? Or just say done!"
            )
            save_state(result, cp, order, gd)
            emit(result, {
                "type": "toppings_done",
                "pizza_index": cp.get("index", 0) if cp else 0,
                **order_totals_payload(order),
            })
            result.swml_change_step("add_finishes")
            return result

        # ── select_finish ────────────────────────────────────────────────

        @self.tool(
            name="select_finish",
            description="Add a finish to the current pizza (parmesan, red_pepper_flakes, oregano, garlic_butter)",
            parameters={
                "type": "object",
                "properties": {
                    "finish_type": {
                        "type": "string",
                        "description": "Finish type",
                        "enum": list(FINISHES.keys()),
                    },
                },
                "required": ["finish_type"],
            },
            wait_file="/keyspressing.mp3",
        )
        def select_finish(args, raw_data):
            cp, order, gd = get_state(raw_data)
            if not cp:
                return SwaigFunctionResult("No pizza started yet.")

            ft = args["finish_type"]
            if ft not in FINISHES:
                return SwaigFunctionResult(f"Options: {', '.join(FINISHES.keys())}")

            if ft in cp["finishes"]:
                return SwaigFunctionResult(f"Already have {FINISHES[ft]['name']} on this pizza!")

            cp["finishes"].append(ft)
            cp["price"] = calculate_pizza_price(cp)

            finish_name = FINISHES[ft]["name"]
            result = SwaigFunctionResult(
                f"Added {finish_name}! Any other finishes, or shall I wrap up this pizza?"
            )
            save_state(result, cp, order, gd)

            z_index = 90 + len(cp["finishes"]) - 1
            emit(result,{
                "type": "layer_added",
                "pizza_index": cp.get("index", 0),
                "category": "finish",
                "asset_path": finish_asset(ft),
                "z_index": z_index,
                "label": finish_name,
                "pizza_price": cp["price"],
                **order_totals_payload(order),
            })
            return result

        # ── done_with_pizza ──────────────────────────────────────────────

        @self.tool(
            name="done_with_pizza",
            description="Finalize the current pizza and add it to the order",
            parameters={"type": "object", "properties": {}, "required": []},
            wait_file="/keyspressing.mp3",
        )
        def done_with_pizza(args, raw_data):
            logger.info(f"TOOL CALLED: done_with_pizza args={args}")
            cp, order, gd = get_state(raw_data)
            if not cp:
                return SwaigFunctionResult("No pizza being built right now.")

            if not cp.get("crust"):
                cp["crust"] = {"type": "hand_tossed", "bake": "classic"}
            if not cp.get("sauce"):
                cp["sauce"] = {"type": "classic_red", "amount": "normal"}
            if not cp.get("cheese"):
                cp["cheese"] = {"type": "mozzarella", "amount": "normal"}

            cp["price"] = calculate_pizza_price(cp)
            cp["summary"] = pizza_summary(cp)
            order["pizzas"].append(cp)
            order["subtotal"], order["tax"], order["total"] = calculate_order_totals(order)

            pizza_index = cp.get("index", len(order["pizzas"]) - 1)
            layers = get_pizza_layers(cp)

            msg = (
                f"Pizza #{pizza_index + 1} looks great! "
                "Would you like another pizza, or shall we add some sides and drinks?"
            )
            if len(order["pizzas"]) == 0 and len(cp.get("toppings", [])) == 1:
                msg += " Want to try our Two Pizza Deal? Two large pizzas for $24.99!"
            result = SwaigFunctionResult(msg)

            gd["current_pizza"] = None
            gd["order"] = order
            result.update_global_data(gd)

            emit(result, {
                "type": "pizza_completed",
                "pizza_index": pizza_index,
                "pizza": cp,
                "layers": layers,
                "summary": cp["summary"],
                **order_totals_payload(order),
            })
            result.swml_change_step("confirming_pizza")
            return result

        # ── cancel_pizza ─────────────────────────────────────────────────

        @self.tool(
            name="cancel_pizza",
            description="Cancel the current pizza being built",
            parameters={"type": "object", "properties": {}, "required": []},
            wait_file="/keyspressing.mp3",
        )
        def cancel_pizza(args, raw_data):
            cp, order, gd = get_state(raw_data)
            pizza_index = cp.get("index", 0) if cp else 0

            result = SwaigFunctionResult(
                "No problem, pizza cancelled. Would you like to start a new one?"
            )
            gd["current_pizza"] = None
            gd["order"] = order
            result.update_global_data(gd)

            emit(result,{
                "type": "pizza_cancelled",
                "pizza_index": pizza_index,
                **order_totals_payload(order),
            })

            if order["pizzas"]:
                result.swml_change_step("confirming_pizza")
            else:
                result.swml_change_step("greeting")
            return result

        # ── confirm_pizza ────────────────────────────────────────────────

        @self.tool(
            name="confirm_pizza",
            description="Customer confirms the pizza looks good, move to sides/drinks",
            parameters={"type": "object", "properties": {}, "required": []},
            wait_file="/keyspressing.mp3",
        )
        def confirm_pizza(args, raw_data):
            cp, order, gd = get_state(raw_data)
            msg = (
                "Awesome! Would you like to add any sides or drinks? "
                "We have breadsticks, garlic knots, wings, salads, and drinks!"
            )
            if not order.get("sides"):
                msg += " How about some garlic knots or breadsticks on the side?"
            result = SwaigFunctionResult(msg)
            save_state(result, cp, order, gd)
            emit(result, {
                "type": "pizza_confirmed",
                "order": order,
                **order_totals_payload(order),
            })
            result.swml_change_step("ordering_sides")
            return result

        # ── modify_pizza ─────────────────────────────────────────────────

        @self.tool(
            name="modify_pizza",
            description="Go back to modify the last completed pizza",
            parameters={"type": "object", "properties": {}, "required": []},
            wait_file="/keyspressing.mp3",
        )
        def modify_pizza(args, raw_data):
            cp, order, gd = get_state(raw_data)
            if not order["pizzas"]:
                return SwaigFunctionResult("No pizza to modify.")

            # Pop last pizza back into current_pizza
            pizza_index = cp.get("index", len(order["pizzas"]) - 1) if cp else len(order["pizzas"]) - 1
            cp = order["pizzas"].pop()
            order["subtotal"], order["tax"], order["total"] = calculate_order_totals(order)

            result = SwaigFunctionResult(
                "OK, let's modify that pizza. What toppings would you like to add or remove? "
                "When you're done, say finished."
            )
            save_state(result, cp, order, gd)
            emit(result, {
                "type": "pizza_modify",
                "pizza_index": cp.get("index", pizza_index),
                **order_totals_payload(order),
            })
            result.swml_change_step("add_toppings")
            return result

        # ── change_pizza_size ─────────────────────────────────────────────

        @self.tool(
            name="change_pizza_size",
            description="Change the size of the last completed pizza without modifying anything else",
            parameters={
                "type": "object",
                "properties": {
                    "size": {
                        "type": "string",
                        "description": "New pizza size",
                        "enum": list(SIZES.keys()),
                    },
                },
                "required": ["size"],
            },
            wait_file="/keyspressing.mp3",
        )
        def change_pizza_size(args, raw_data):
            logger.info(f"TOOL CALLED: change_pizza_size args={args}")
            cp, order, gd = get_state(raw_data)
            if not order["pizzas"]:
                return SwaigFunctionResult("No pizza to resize.")

            new_size = args["size"]
            pizza = order["pizzas"][-1]
            pizza["size"] = new_size
            pizza["price"] = calculate_pizza_price(pizza)

            size_name = SIZES[new_size]["name"]
            result = SwaigFunctionResult(
                f"Changed to {size_name}! Does that look good now?"
            )
            save_state(result, cp, order, gd)
            emit(result, {
                "type": "pizza_size_changed",
                "pizza_index": pizza.get("index", len(order["pizzas"]) - 1),
                "size": new_size,
                "size_name": size_name,
                "pizza": pizza,
                "summary": pizza_summary(pizza),
                **order_totals_payload(order),
            })
            return result

        # ── add_another_pizza ────────────────────────────────────────────

        @self.tool(
            name="add_another_pizza",
            description="Customer wants another pizza. Transitions to choose specialty or custom + size.",
            parameters={"type": "object", "properties": {}, "required": []},
            wait_file="/keyspressing.mp3",
        )
        def add_another_pizza(args, raw_data):
            cp, order, gd = get_state(raw_data)

            result = SwaigFunctionResult(
                "Let's add another pizza! Would you like one of our specialties - "
                "Classic Pepperoni, Meat Lover's, Veggie Supreme, Hawaiian, or Margherita? "
                "Or would you like to build a custom one? And what size - small, medium, or large?"
            )
            save_state(result, cp, order, gd)
            emit(result, {
                "type": "adding_pizza",
                **order_totals_payload(order),
            })
            result.swml_change_step("greeting")
            return result

        # ── order_sides_only ─────────────────────────────────────────────

        @self.tool(
            name="order_sides_only",
            description="Customer wants to order only sides and drinks, no pizza",
            parameters={"type": "object", "properties": {}, "required": []},
            wait_file="/keyspressing.mp3",
        )
        def order_sides_only(args, raw_data):
            logger.info(f"TOOL CALLED: order_sides_only")
            cp, order, gd = get_state(raw_data)
            result = SwaigFunctionResult(
                "No problem! What sides or drinks can I get you? "
                "We have breadsticks, garlic knots, wings, salads, and drinks!"
            )
            save_state(result, cp, order, gd)
            emit(result, {
                "type": "sides_only",
                **order_totals_payload(order),
            })
            result.swml_change_step("ordering_sides")
            return result

        # ── add_side ─────────────────────────────────────────────────────

        @self.tool(
            name="add_side",
            description="Add a side item to the order",
            parameters={
                "type": "object",
                "properties": {
                    "item": {
                        "type": "string",
                        "description": "Side item",
                        "enum": list(SIDES.keys()),
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "How many",
                        "minimum": 1,
                        "maximum": 10,
                    },
                },
                "required": ["item"],
            },
            wait_file="/keyspressing.mp3",
        )
        def add_side(args, raw_data):
            cp, order, gd = get_state(raw_data)
            item_key = args["item"]
            qty = args.get("quantity", 1)

            if item_key not in SIDES:
                return SwaigFunctionResult(f"We don't have that. Options: {', '.join(SIDES.keys())}")

            side_info = SIDES[item_key]

            # Check if already in order
            for s in order["sides"]:
                if s["key"] == item_key:
                    s["quantity"] += qty
                    break
            else:
                order["sides"].append({
                    "key": item_key,
                    "name": side_info["name"],
                    "price": side_info["price"],
                    "quantity": qty,
                })

            msg = f"Added {qty}x {side_info['name']}! Anything else?"
            if not order.get("drinks"):
                msg += " Want a drink to go with that?"
            result = SwaigFunctionResult(msg)
            save_state(result, cp, order, gd)

            emit(result,{
                "type": "side_added",
                "item": item_key,
                "name": side_info["name"],
                "price": side_info["price"],
                "quantity": qty,
                "sides": order["sides"],
                **order_totals_payload(order),
            })
            return result

        # ── remove_side ──────────────────────────────────────────────────

        @self.tool(
            name="remove_side",
            description="Remove a side item from the order",
            parameters={
                "type": "object",
                "properties": {
                    "item": {
                        "type": "string",
                        "description": "Side to remove",
                        "enum": list(SIDES.keys()),
                    },
                },
                "required": ["item"],
            },
            wait_file="/keyspressing.mp3",
        )
        def remove_side(args, raw_data):
            cp, order, gd = get_state(raw_data)
            item_key = args["item"]
            original_len = len(order["sides"])
            order["sides"] = [s for s in order["sides"] if s["key"] != item_key]

            if len(order["sides"]) == original_len:
                return SwaigFunctionResult("That item isn't in your order.")

            result = SwaigFunctionResult(f"Removed {SIDES.get(item_key, {}).get('name', item_key)}.")
            save_state(result, cp, order, gd)

            emit(result,{
                "type": "side_removed",
                "item": item_key,
                "sides": order["sides"],
                **order_totals_payload(order),
            })
            return result

        # ── add_drink ────────────────────────────────────────────────────

        @self.tool(
            name="add_drink",
            description="Add a drink to the order",
            parameters={
                "type": "object",
                "properties": {
                    "item": {
                        "type": "string",
                        "description": "Drink item",
                        "enum": list(DRINKS.keys()),
                    },
                    "quantity": {
                        "type": "integer",
                        "description": "How many",
                        "minimum": 1,
                        "maximum": 10,
                    },
                },
                "required": ["item"],
            },
            wait_file="/keyspressing.mp3",
        )
        def add_drink(args, raw_data):
            cp, order, gd = get_state(raw_data)
            item_key = args["item"]
            qty = args.get("quantity", 1)

            if item_key not in DRINKS:
                return SwaigFunctionResult(f"We don't have that. Options: {', '.join(DRINKS.keys())}")

            drink_info = DRINKS[item_key]

            for d in order["drinks"]:
                if d["key"] == item_key:
                    d["quantity"] += qty
                    break
            else:
                order["drinks"].append({
                    "key": item_key,
                    "name": drink_info["name"],
                    "price": drink_info["price"],
                    "quantity": qty,
                })

            result = SwaigFunctionResult(f"Added {qty}x {drink_info['name']}! Anything else?")
            save_state(result, cp, order, gd)

            emit(result,{
                "type": "drink_added",
                "item": item_key,
                "name": drink_info["name"],
                "price": drink_info["price"],
                "quantity": qty,
                "drinks": order["drinks"],
                **order_totals_payload(order),
            })
            return result

        # ── remove_drink ─────────────────────────────────────────────────

        @self.tool(
            name="remove_drink",
            description="Remove a drink from the order",
            parameters={
                "type": "object",
                "properties": {
                    "item": {
                        "type": "string",
                        "description": "Drink to remove",
                        "enum": list(DRINKS.keys()),
                    },
                },
                "required": ["item"],
            },
            wait_file="/keyspressing.mp3",
        )
        def remove_drink(args, raw_data):
            cp, order, gd = get_state(raw_data)
            item_key = args["item"]
            original_len = len(order["drinks"])
            order["drinks"] = [d for d in order["drinks"] if d["key"] != item_key]

            if len(order["drinks"]) == original_len:
                return SwaigFunctionResult("That drink isn't in your order.")

            result = SwaigFunctionResult(f"Removed {DRINKS.get(item_key, {}).get('name', item_key)}.")
            save_state(result, cp, order, gd)

            emit(result,{
                "type": "drink_removed",
                "item": item_key,
                "drinks": order["drinks"],
                **order_totals_payload(order),
            })
            return result

        # ── review_order ─────────────────────────────────────────────────

        @self.tool(
            name="review_order",
            description="Send the full order summary to the customer's screen",
            parameters={"type": "object", "properties": {}, "required": []},
            wait_file="/keyspressing.mp3",
        )
        def review_order(args, raw_data):
            cp, order, gd = get_state(raw_data)
            order["subtotal"], order["tax"], order["total"] = calculate_order_totals(order)

            result = SwaigFunctionResult(
                "Your full order is on the screen. Take a look and let me know if everything's good!"
            )
            save_state(result, cp, order, gd)

            emit(result,{
                "type": "order_reviewed",
                "order": order,
                **order_totals_payload(order),
            })
            return result

        # ── finalize_order ───────────────────────────────────────────────

        @self.tool(
            name="finalize_order",
            description="Lock the order and move to payment",
            parameters={"type": "object", "properties": {}, "required": []},
            wait_file="/keyspressing.mp3",
        )
        def finalize_order(args, raw_data):
            cp, order, gd = get_state(raw_data)

            if not order["pizzas"] and not order["sides"] and not order["drinks"]:
                return SwaigFunctionResult("Your order is empty! Let's add something first.")

            order["subtotal"], order["tax"], order["total"] = calculate_order_totals(order)

            result = SwaigFunctionResult(
                f"Your order total is ${order['total']:.2f}. Ready to place the order?"
            )
            save_state(result, cp, order, gd)

            emit(result,{
                "type": "order_finalized",
                "order": order,
                **order_totals_payload(order),
            })
            result.swml_change_step("payment")
            return result

        # ── process_payment ──────────────────────────────────────────────

        @self.tool(
            name="process_payment",
            description="Generate an order number and process the payment",
            parameters={"type": "object", "properties": {}, "required": []},
            wait_file="/keyspressing.mp3",
        )
        def process_payment(args, raw_data):
            cp, order, gd = get_state(raw_data)

            order_number = random.randint(100, 999)
            order["order_number"] = order_number

            result = SwaigFunctionResult(
                f"Your order number is {order_number}. "
                "Your pizza will be ready shortly! Thank you for ordering from Gino's Pizza!"
            )
            save_state(result, cp, order, gd)

            emit(result,{
                "type": "payment_started",
                "order_number": order_number,
                **order_totals_payload(order),
            })
            result.swml_change_step("order_complete_pending")
            return result

        # ── complete_order ───────────────────────────────────────────────

        @self.tool(
            name="complete_order",
            description="Mark the order as complete",
            parameters={"type": "object", "properties": {}, "required": []},
            wait_file="/keyspressing.mp3",
        )
        def complete_order(args, raw_data):
            cp, order, gd = get_state(raw_data)
            order_number = order.get("order_number", "")

            result = SwaigFunctionResult(
                f"Order #{order_number} is all set! Thank you for choosing Gino's Pizza. Enjoy!"
            )
            save_state(result, cp, order, gd)

            emit(result,{
                "type": "order_completed",
                "order_number": order_number,
                **order_totals_payload(order),
            })
            result.swml_change_step("order_complete")
            return result

        # ── cancel_order ─────────────────────────────────────────────────

        @self.tool(
            name="cancel_order",
            description="Cancel the entire order and start fresh",
            parameters={"type": "object", "properties": {}, "required": []},
            wait_file="/keyspressing.mp3",
        )
        def cancel_order(args, raw_data):
            gd = (raw_data or {}).get("global_data", {})
            fresh_order = new_order()

            result = SwaigFunctionResult("Order cancelled. Would you like to start a new one?")
            gd["current_pizza"] = None
            gd["order"] = fresh_order
            result.update_global_data(gd)

            emit(result,{
                "type": "order_cancelled",
                **order_totals_payload(fresh_order),
            })
            result.swml_change_step("greeting")
            return result

        # ── new_order ────────────────────────────────────────────────────

        @self.tool(
            name="new_order",
            description="Start a completely new order after completing one",
            parameters={"type": "object", "properties": {}, "required": []},
            wait_file="/keyspressing.mp3",
        )
        def new_order_tool(args, raw_data):
            gd = (raw_data or {}).get("global_data", {})
            fresh_order = new_order()

            result = SwaigFunctionResult(
                "Welcome back! Ready to build another amazing pizza? "
                "Would you like a custom pizza or one of our specialties?"
            )
            gd["current_pizza"] = None
            gd["order"] = fresh_order
            result.update_global_data(gd)

            emit(result,{
                "type": "new_order",
                **order_totals_payload(fresh_order),
            })
            result.swml_change_step("greeting")
            return result

    def on_summary(self, summary=None, raw_data=None):
        if summary:
            logger.info(f"Call summary: {summary}")
        if raw_data:
            calls_dir = Path(__file__).parent / "calls"
            calls_dir.mkdir(exist_ok=True)
            call_id = raw_data.get("call_id", "unknown")
            out_path = calls_dir / f"{call_id}.json"
            try:
                out_path.write_text(json.dumps(raw_data, indent=2, default=str))
                logger.info(f"Saved call data to {out_path}")
            except Exception as e:
                logger.error(f"Failed to save call data: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# Server Setup
# ═════════════════════════════════════════════════════════════════════════════

def create_server():
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 5000))

    server = AgentServer(host=host, port=port)
    server.register(GinosPizzaAgent(), "/swml")

    # Health check
    @server.app.get("/health")
    def health_check():
        return {"status": "healthy", "agent": "ginospizza"}

    @server.app.get("/ready")
    def ready_check():
        if swml_handler_info.get("address"):
            return {"status": "ready", "address": swml_handler_info["address"]}
        return {"status": "initializing"}

    # Token endpoint
    @server.app.get("/get_token")
    def get_token():
        # Handler registration may have been skipped/failed at startup (e.g. proxy
        # URL not yet set). Lazily retry once, serialized so workers don't race.
        if not swml_handler_info.get("address_id"):
            with _swml_setup_lock:
                if not swml_handler_info.get("address_id"):
                    setup_swml_handler()

        if not swml_handler_info.get("address_id"):
            return JSONResponse(
                {"error": f"SWML handler not registered: {swml_setup_error or 'check startup logs'}"},
                status_code=500,
            )

        client = build_rest_client()
        if client is None:
            return JSONResponse({"error": "SignalWire credentials not configured"}, status_code=500)

        try:
            expire_at = int(time.time()) + 3600 * 24
            guest = client.fabric.tokens.create_guest_token(
                allowed_addresses=[swml_handler_info["address_id"]],
                expire_at=expire_at,
            )
            return {"token": guest.get("token", ""), "address": swml_handler_info["address"]}
        except Exception as e:
            logger.error(f"Token request failed: {e}")
            return JSONResponse({"error": str(e)}, status_code=500)

    # Menu API
    @server.app.get("/api/menu")
    async def get_menu():
        return {"menu": get_full_menu()}

    # Serve web frontend (assets are inside web/assets/)
    web_dir = Path(__file__).parent / "web"
    if web_dir.exists():
        server.serve_static_files(str(web_dir))

    # Setup SWML handler
    setup_swml_handler()

    return server


server = create_server()
app = server.app

if __name__ == "__main__":
    server.run()
