#!/usr/bin/env bash
# =============================================================================
# Gino's Pizza SWAIG Flow Test Harness
#
# Tests all SWAIG functions and the full pizza ordering flow using
# swaig-test with accumulated global_data state.
#
# Usage:  ./test_flow.sh [--debug]
# =============================================================================

SWAIG="swaig-test"
AGENT="app.py"
PASS=0
FAIL=0
CALL_ID="test-$(date +%s)"
DEBUG=false

for arg in "$@"; do
    case "$arg" in
        --debug|-d) DEBUG=true ;;
    esac
done

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m'

# ── helpers ──────────────────────────────────────────────────────────────────

check() {
    local label="$1"
    local pattern="$2"
    local byte_len char_len pad
    byte_len=$(printf '%s' "$label" | wc -c)
    char_len=${#label}
    pad=$((57 + byte_len - char_len))
    printf "${CYAN}  %-${pad}s${NC}" "$label"
    if echo "$OUTPUT" | grep -qi "$pattern"; then
        printf "${GREEN}PASS${NC}\n"
        ((PASS++))
    else
        printf "${RED}FAIL${NC} — expected '%s'\n" "$pattern"
        echo "      Got: $(echo "$OUTPUT" | head -2)"
        ((FAIL++))
    fi
}

run() {
    if $DEBUG; then
        printf "\n${DIM}  ▸ swaig-test %s${NC}\n" "$*"
    fi
    OUTPUT=$("$SWAIG" "$AGENT" "$@" 2>/dev/null) || true
    if $DEBUG; then
        echo "$OUTPUT" | while IFS= read -r line; do
            printf "${DIM}    %s${NC}\n" "$line"
        done
    fi
}

section() {
    printf "\n${YELLOW}━━ %s ━━${NC}\n" "$1"
}

# Extract set_global_data JSON from OUTPUT (after Actions: header)
extract_global_data() {
    echo "$OUTPUT" | sed -n '/^Actions:$/,$ p' | sed '1d' | \
        jq -s -c '[.[] | select(has("set_global_data")) | .set_global_data] | add // empty' 2>/dev/null
}

# Wrap GD accumulator as --custom-data JSON
cd_gd() {
    echo "$GD" | jq -c '{global_data: .}'
}

# Run swaig-test with GD as custom-data, then merge any set_global_data into GD
run_and_merge() {
    run --custom-data "$(cd_gd)" "$@"
    local new_data
    new_data=$(extract_global_data)
    if [ -n "$new_data" ]; then
        GD=$(echo "$GD" | jq -c --argjson new "$new_data" '. + $new')
    fi
}

# =============================================================================
printf "\n${YELLOW}╔══════════════════════════════════════════════════════════╗${NC}\n"
printf "${YELLOW}║          Gino's Pizza SWAIG Flow Test Harness            ║${NC}\n"
printf "${YELLOW}╚══════════════════════════════════════════════════════════╝${NC}\n"
printf "  Call ID: ${CYAN}%s${NC}\n" "$CALL_ID"

# Initialize global data
GD='{"current_pizza":null,"order":{"pizzas":[],"sides":[],"drinks":[],"subtotal":0,"tax":0,"total":0,"order_number":null}}'

# =============================================================================
section "1. start_pizza"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec start_pizza --size large
check "Start large pizza → response" "Starting\|Large\|crust"
check "  → pizza_started event" "pizza_started"
check "  → change_step: choose_crust" "choose_crust"

# =============================================================================
section "2. select_crust"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec select_crust --crust_type thin
check "Select thin crust → response" "Thin\|classic\|well done"
check "  → change_step: choose_bake" "choose_bake"

# =============================================================================
section "3. select_bake"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec select_bake --bake well_done
check "Select well done → response" "well done\|sauce"
check "  → layer_added event (crust)" "layer_added"
check "  → change_step: choose_sauce" "choose_sauce"

# =============================================================================
section "4. select_sauce"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec select_sauce --sauce_type classic_red
check "Select classic red → asks amount" "light\|normal\|extra"
check "  → change_step: choose_sauce_amount" "choose_sauce_amount"

# No sauce path
run --raw --call-id "${CALL_ID}-nosause" --custom-data "$(cd_gd)" --exec select_sauce --sauce_type none
check "No sauce → skips to cheese" "choose_cheese"

# =============================================================================
section "5. select_sauce_amount"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec select_sauce_amount --amount extra
check "Extra sauce → response" "extra\|cheese"
check "  → layer_added event (sauce)" "layer_added"
check "  → change_step: choose_cheese" "choose_cheese"

# =============================================================================
section "6. select_cheese"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec select_cheese --cheese_type mozzarella
check "Select mozzarella → asks amount" "light\|normal\|extra"
check "  → change_step: choose_cheese_amount" "choose_cheese_amount"

# No cheese path
run --raw --call-id "${CALL_ID}-nocheese" --custom-data "$(cd_gd)" --exec select_cheese --cheese_type none
check "No cheese → skips to toppings" "add_toppings"

# =============================================================================
section "7. select_cheese_amount"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec select_cheese_amount --amount normal
check "Normal cheese → response" "normal\|toppings"
check "  → layer_added event (cheese)" "layer_added"
check "  → change_step: add_toppings" "add_toppings"

# =============================================================================
section "8. add_topping"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec add_topping --topping pepperoni
check "Add pepperoni → response" "Pepperoni"
check "  → layer_added event (topping)" "layer_added"

run_and_merge --raw --call-id "$CALL_ID" --exec add_topping --topping mushroom --placement left
check "Add mushroom left half → response" "Mushroom\|left"

run_and_merge --raw --call-id "$CALL_ID" --exec add_topping --topping jalapeno --amount extra
check "Add extra jalapeno → response" "Jalapeno\|extra"

# Duplicate topping
run_and_merge --raw --call-id "$CALL_ID" --exec add_topping --topping pepperoni
check "Duplicate pepperoni → already have" "already"

# =============================================================================
section "9. remove_topping"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec remove_topping --topping jalapeno
check "Remove jalapeno → response" "Removed\|Jalapeno"
check "  → layer_removed event" "layer_removed"

# Remove non-existent
run_and_merge --raw --call-id "$CALL_ID" --exec remove_topping --topping bacon
check "Remove non-existent → not on pizza" "don.t have"

# =============================================================================
section "10. done_with_toppings"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec done_with_toppings
check "Done with toppings → asks finishes" "finish\|parmesan\|oregano"
check "  → change_step: add_finishes" "add_finishes"

# =============================================================================
section "11. select_finish"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec select_finish --finish_type parmesan
check "Add parmesan → response" "Parmesan"
check "  → layer_added event (finish)" "layer_added"

# Duplicate finish
run_and_merge --raw --call-id "$CALL_ID" --exec select_finish --finish_type parmesan
check "Duplicate finish → already have" "Already"

# =============================================================================
section "12. done_with_pizza"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec done_with_pizza
check "Done with pizza → response" "looks great\|another pizza\|sides"
check "  → pizza_completed event" "pizza_completed"
check "  → change_step: confirming_pizza" "confirming_pizza"

# =============================================================================
section "13. change_pizza_size"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec change_pizza_size --size small
check "Change to small → response" "Small\|Changed"
check "  → pizza_size_changed event" "pizza_size_changed"

# =============================================================================
section "14. confirm_pizza → ordering_sides"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec confirm_pizza
check "Confirm pizza → sides/drinks" "sides\|drinks"
check "  → change_step: ordering_sides" "ordering_sides"

# =============================================================================
section "15. order_specialty"
# =============================================================================

run_and_merge --raw --call-id "${CALL_ID}-spec" --exec order_specialty --specialty_name hawaiian --size medium
check "Hawaiian medium → response" "Hawaiian"
check "  → specialty_pizza event" "specialty_pizza"
check "  → change_step: confirming_pizza" "confirming_pizza"

# Invalid specialty
run --raw --call-id "${CALL_ID}-spec-bad" --exec order_specialty --specialty_name nonexistent --size large
check "Bad specialty → error" "couldn.t find"

# =============================================================================
section "16. add_side / remove_side"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec add_side --item breadsticks
check "Add breadsticks → response" "Breadsticks"
check "  → side_added event" "side_added"

run_and_merge --raw --call-id "$CALL_ID" --exec add_side --item wings_buffalo --quantity 2
check "Add 2x buffalo wings → response" "Buffalo Wings"

run_and_merge --raw --call-id "$CALL_ID" --exec remove_side --item breadsticks
check "Remove breadsticks → response" "Removed\|Breadsticks"
check "  → side_removed event" "side_removed"

# Remove non-existent
run_and_merge --raw --call-id "$CALL_ID" --exec remove_side --item caesar_salad
check "Remove non-existent side → not in order" "isn.t"

# =============================================================================
section "17. add_drink / remove_drink"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec add_drink --item soda_large --quantity 2
check "Add 2x large soda → response" "Large Soda"
check "  → drink_added event" "drink_added"

run_and_merge --raw --call-id "$CALL_ID" --exec add_drink --item water
check "Add water → response" "Water"

run_and_merge --raw --call-id "$CALL_ID" --exec remove_drink --item water
check "Remove water → response" "Removed\|Water"
check "  → drink_removed event" "drink_removed"

# =============================================================================
section "18. review_order"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec review_order
check "Review order → response" "order\|screen"
check "  → order_reviewed event" "order_reviewed"

# =============================================================================
section "19. finalize_order"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec finalize_order
check "Finalize → total shown" "total\|\\$"
check "  → order_finalized event" "order_finalized"
check "  → change_step: payment" "payment"

# Empty order
run --raw --call-id "${CALL_ID}-empty" --exec finalize_order
check "Empty order → error" "empty"

# =============================================================================
section "20. process_payment"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec process_payment
check "Process payment → order number" "order number\|[0-9]"
check "  → payment_started event" "payment_started"
check "  → change_step: order_complete_pending" "order_complete_pending"

# =============================================================================
section "21. complete_order"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec complete_order
check "Complete order → thank you" "thank you\|all set\|Enjoy"
check "  → order_completed event" "order_completed"
check "  → change_step: order_complete" "order_complete"

# =============================================================================
section "22. new_order"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec new_order
check "New order → welcome back" "Welcome\|Ready\|another"
check "  → new_order event" "new_order"
check "  → change_step: greeting" "greeting"

# =============================================================================
section "23. cancel_pizza"
# =============================================================================

# Start a pizza then cancel it
GD_CANCEL="$GD"
run --raw --call-id "${CALL_ID}-cancel" --custom-data "$(echo "$GD_CANCEL" | jq -c '{global_data: .}')" --exec start_pizza --size large
run --raw --call-id "${CALL_ID}-cancel" --custom-data "$(echo "$GD_CANCEL" | jq -c '{global_data: .}')" --exec cancel_pizza
check "Cancel pizza → response" "cancelled"
check "  → pizza_cancelled event" "pizza_cancelled"

# =============================================================================
section "24. cancel_order"
# =============================================================================

run --raw --call-id "${CALL_ID}-co" --custom-data "$(cd_gd)" --exec cancel_order
check "Cancel order → response" "cancelled"
check "  → order_cancelled event" "order_cancelled"
check "  → change_step: greeting" "greeting"

# =============================================================================
section "25. order_sides_only"
# =============================================================================

run --raw --call-id "${CALL_ID}-sides" --exec order_sides_only
check "Sides only → response" "sides\|drinks"
check "  → sides_only event" "sides_only"
check "  → change_step: ordering_sides" "ordering_sides"

# =============================================================================
section "26. add_another_pizza"
# =============================================================================

run_and_merge --raw --call-id "$CALL_ID" --exec add_another_pizza
check "Add another → asks specialty or custom" "specialty\|Specialty\|custom\|Custom"
check "  → change_step: greeting" "greeting"

# =============================================================================
section "27. show_menu"
# =============================================================================

run --raw --call-id "${CALL_ID}-menu" --exec show_menu
check "Show menu → response" "menu\|screen"
check "  → show_menu event" "show_menu"

# =============================================================================
section "28. modify_pizza (from confirming)"
# =============================================================================

# Build and complete a pizza, then modify
GD_MOD='{"current_pizza":null,"order":{"pizzas":[{"size":"large","crust":{"type":"thin","bake":"classic"},"sauce":{"type":"classic_red","amount":"normal"},"cheese":{"type":"mozzarella","amount":"normal"},"toppings":[{"name":"pepperoni","placement":"full","amount":"normal"}],"finishes":[],"price":16.49,"index":0}],"sides":[],"drinks":[],"subtotal":16.49,"tax":1.65,"total":18.14,"order_number":null}}'

run --raw --call-id "${CALL_ID}-mod" --custom-data "{\"global_data\":$GD_MOD}" --exec modify_pizza
check "Modify pizza → response" "modify\|change\|toppings"
check "  → pizza_modify event" "pizza_modify"
check "  → change_step: add_toppings" "add_toppings"

# =============================================================================
section "29. Sauce type variations"
# =============================================================================

GD_SAUCE='{"current_pizza":{"size":"large","crust":{"type":"hand_tossed","bake":"classic"},"sauce":null,"cheese":null,"toppings":[],"finishes":[],"price":14.99,"discount":0,"index":0},"order":{"pizzas":[],"sides":[],"drinks":[],"subtotal":0,"tax":0,"total":0,"order_number":null}}'

run --raw --call-id "${CALL_ID}-sauce-spicy" --custom-data "{\"global_data\":$GD_SAUCE}" --exec select_sauce --sauce_type spicy_red
check "Spicy red sauce → response" "Spicy Red"

run --raw --call-id "${CALL_ID}-sauce-alfredo" --custom-data "{\"global_data\":$GD_SAUCE}" --exec select_sauce --sauce_type white_alfredo
check "White alfredo → response" "White Alfredo"

run --raw --call-id "${CALL_ID}-sauce-bbq" --custom-data "{\"global_data\":$GD_SAUCE}" --exec select_sauce --sauce_type bbq
check "BBQ sauce → response" "BBQ"

# =============================================================================
section "30. Cheese type variations"
# =============================================================================

GD_CHEESE='{"current_pizza":{"size":"large","crust":{"type":"hand_tossed","bake":"classic"},"sauce":{"type":"classic_red","amount":"normal"},"cheese":null,"toppings":[],"finishes":[],"price":14.99,"discount":0,"index":0},"order":{"pizzas":[],"sides":[],"drinks":[],"subtotal":0,"tax":0,"total":0,"order_number":null}}'

run --raw --call-id "${CALL_ID}-cheese-cheddar" --custom-data "{\"global_data\":$GD_CHEESE}" --exec select_cheese --cheese_type cheddar_blend
check "Cheddar blend → response" "Cheddar Blend"

run --raw --call-id "${CALL_ID}-cheese-vegan" --custom-data "{\"global_data\":$GD_CHEESE}" --exec select_cheese --cheese_type vegan_cheese
check "Vegan cheese → response" "Vegan Cheese"

# =============================================================================
section "31. Topping right placement"
# =============================================================================

GD_TOP='{"current_pizza":{"size":"large","crust":{"type":"hand_tossed","bake":"classic"},"sauce":{"type":"classic_red","amount":"normal"},"cheese":{"type":"mozzarella","amount":"normal"},"toppings":[],"finishes":[],"price":14.99,"discount":0,"index":0},"order":{"pizzas":[],"sides":[],"drinks":[],"subtotal":0,"tax":0,"total":0,"order_number":null}}'

run --raw --call-id "${CALL_ID}-top-right" --custom-data "{\"global_data\":$GD_TOP}" --exec add_topping --topping bacon --placement right
check "Bacon right half → response" "right\|Bacon"
check "  → layer_added event" "layer_added"

# =============================================================================
section "32. Finish type variations"
# =============================================================================

GD_FINISH='{"current_pizza":{"size":"large","crust":{"type":"hand_tossed","bake":"classic"},"sauce":{"type":"classic_red","amount":"normal"},"cheese":{"type":"mozzarella","amount":"normal"},"toppings":[{"name":"pepperoni","placement":"full","amount":"normal"}],"finishes":[],"price":16.49,"discount":0,"index":0},"order":{"pizzas":[],"sides":[],"drinks":[],"subtotal":0,"tax":0,"total":0,"order_number":null}}'

run --raw --call-id "${CALL_ID}-fin-rp" --custom-data "{\"global_data\":$GD_FINISH}" --exec select_finish --finish_type red_pepper_flakes
check "Red pepper flakes → response" "Red Pepper"

run --raw --call-id "${CALL_ID}-fin-oreg" --custom-data "{\"global_data\":$GD_FINISH}" --exec select_finish --finish_type oregano
check "Oregano → response" "Oregano"

run --raw --call-id "${CALL_ID}-fin-garlic" --custom-data "{\"global_data\":$GD_FINISH}" --exec select_finish --finish_type garlic_butter
check "Garlic butter → response" "Garlic Butter"

# =============================================================================
section "33. Specialty variations"
# =============================================================================

run --raw --call-id "${CALL_ID}-spec-pep" --exec order_specialty --specialty_name classic_pepperoni --size large
check "Classic Pepperoni → response" "Pepperoni"
check "  → specialty_pizza event" "specialty_pizza"

run --raw --call-id "${CALL_ID}-spec-meat" --exec order_specialty --specialty_name meat_lovers --size medium
check "Meat Lovers → response" "Meat Lover"
check "  → specialty_pizza event" "specialty_pizza"

run --raw --call-id "${CALL_ID}-spec-veg" --exec order_specialty --specialty_name veggie_supreme --size small
check "Veggie Supreme → response" "Veggie Supreme"
check "  → specialty_pizza event" "specialty_pizza"

run --raw --call-id "${CALL_ID}-spec-marg" --exec order_specialty --specialty_name margherita --size large
check "Margherita → response" "Margherita"
check "  → specialty_pizza event" "specialty_pizza"

# =============================================================================
section "34. Full multi-pizza flow"
# =============================================================================

# Fresh state for multi-pizza test
GD_MULTI='{"current_pizza":null,"order":{"pizzas":[],"sides":[],"drinks":[],"subtotal":0,"tax":0,"total":0,"order_number":null}}'
MPC="${CALL_ID}-multi"

# Pizza 1: custom build
run --raw --call-id "$MPC" --custom-data "{\"global_data\":$GD_MULTI}" --exec start_pizza --size large
GD_MULTI=$(echo "$OUTPUT" | sed -n '/^Actions:$/,$ p' | sed '1d' | jq -s -c '[.[] | select(has("set_global_data")) | .set_global_data] | add // empty' 2>/dev/null)
[ -z "$GD_MULTI" ] && GD_MULTI='{}'
check "Multi: start pizza 1" "Large\|crust"

run --raw --call-id "$MPC" --custom-data "{\"global_data\":$GD_MULTI}" --exec select_crust --crust_type deep_dish
GD_MULTI=$(echo "$OUTPUT" | sed -n '/^Actions:$/,$ p' | sed '1d' | jq -s -c '[.[] | select(has("set_global_data")) | .set_global_data] | add // empty' 2>/dev/null)
[ -z "$GD_MULTI" ] && GD_MULTI='{}'
check "Multi: deep dish crust" "Deep Dish"

run --raw --call-id "$MPC" --custom-data "{\"global_data\":$GD_MULTI}" --exec select_bake --bake classic
GD_MULTI=$(echo "$OUTPUT" | sed -n '/^Actions:$/,$ p' | sed '1d' | jq -s -c '[.[] | select(has("set_global_data")) | .set_global_data] | add // empty' 2>/dev/null)
[ -z "$GD_MULTI" ] && GD_MULTI='{}'

run --raw --call-id "$MPC" --custom-data "{\"global_data\":$GD_MULTI}" --exec select_sauce --sauce_type bbq
GD_MULTI=$(echo "$OUTPUT" | sed -n '/^Actions:$/,$ p' | sed '1d' | jq -s -c '[.[] | select(has("set_global_data")) | .set_global_data] | add // empty' 2>/dev/null)
[ -z "$GD_MULTI" ] && GD_MULTI='{}'

run --raw --call-id "$MPC" --custom-data "{\"global_data\":$GD_MULTI}" --exec select_sauce_amount --amount light
GD_MULTI=$(echo "$OUTPUT" | sed -n '/^Actions:$/,$ p' | sed '1d' | jq -s -c '[.[] | select(has("set_global_data")) | .set_global_data] | add // empty' 2>/dev/null)
[ -z "$GD_MULTI" ] && GD_MULTI='{}'

run --raw --call-id "$MPC" --custom-data "{\"global_data\":$GD_MULTI}" --exec select_cheese --cheese_type cheddar_blend
GD_MULTI=$(echo "$OUTPUT" | sed -n '/^Actions:$/,$ p' | sed '1d' | jq -s -c '[.[] | select(has("set_global_data")) | .set_global_data] | add // empty' 2>/dev/null)
[ -z "$GD_MULTI" ] && GD_MULTI='{}'

run --raw --call-id "$MPC" --custom-data "{\"global_data\":$GD_MULTI}" --exec select_cheese_amount --amount extra
GD_MULTI=$(echo "$OUTPUT" | sed -n '/^Actions:$/,$ p' | sed '1d' | jq -s -c '[.[] | select(has("set_global_data")) | .set_global_data] | add // empty' 2>/dev/null)
[ -z "$GD_MULTI" ] && GD_MULTI='{}'

run --raw --call-id "$MPC" --custom-data "{\"global_data\":$GD_MULTI}" --exec add_topping --topping bacon
GD_MULTI=$(echo "$OUTPUT" | sed -n '/^Actions:$/,$ p' | sed '1d' | jq -s -c '[.[] | select(has("set_global_data")) | .set_global_data] | add // empty' 2>/dev/null)
[ -z "$GD_MULTI" ] && GD_MULTI='{}'

run --raw --call-id "$MPC" --custom-data "{\"global_data\":$GD_MULTI}" --exec done_with_toppings
GD_MULTI=$(echo "$OUTPUT" | sed -n '/^Actions:$/,$ p' | sed '1d' | jq -s -c '[.[] | select(has("set_global_data")) | .set_global_data] | add // empty' 2>/dev/null)
[ -z "$GD_MULTI" ] && GD_MULTI='{}'

run --raw --call-id "$MPC" --custom-data "{\"global_data\":$GD_MULTI}" --exec done_with_pizza
GD_MULTI=$(echo "$OUTPUT" | sed -n '/^Actions:$/,$ p' | sed '1d' | jq -s -c '[.[] | select(has("set_global_data")) | .set_global_data] | add // empty' 2>/dev/null)
[ -z "$GD_MULTI" ] && GD_MULTI='{}'
check "Multi: pizza 1 completed" "pizza_completed"

# Pizza 2: specialty from confirming_pizza
run --raw --call-id "$MPC" --custom-data "{\"global_data\":$GD_MULTI}" --exec order_specialty --specialty_name margherita --size small
GD_MULTI=$(echo "$OUTPUT" | sed -n '/^Actions:$/,$ p' | sed '1d' | jq -s -c '[.[] | select(has("set_global_data")) | .set_global_data] | add // empty' 2>/dev/null)
[ -z "$GD_MULTI" ] && GD_MULTI='{}'
check "Multi: pizza 2 (Margherita) added" "Margherita"

# Confirm and go to sides
run --raw --call-id "$MPC" --custom-data "{\"global_data\":$GD_MULTI}" --exec confirm_pizza
GD_MULTI=$(echo "$OUTPUT" | sed -n '/^Actions:$/,$ p' | sed '1d' | jq -s -c '[.[] | select(has("set_global_data")) | .set_global_data] | add // empty' 2>/dev/null)
[ -z "$GD_MULTI" ] && GD_MULTI='{}'
check "Multi: confirmed → ordering_sides" "ordering_sides"

# Add sides and finalize
run --raw --call-id "$MPC" --custom-data "{\"global_data\":$GD_MULTI}" --exec add_side --item garlic_knots
GD_MULTI=$(echo "$OUTPUT" | sed -n '/^Actions:$/,$ p' | sed '1d' | jq -s -c '[.[] | select(has("set_global_data")) | .set_global_data] | add // empty' 2>/dev/null)
[ -z "$GD_MULTI" ] && GD_MULTI='{}'
check "Multi: added garlic knots" "Garlic Knots"

run --raw --call-id "$MPC" --custom-data "{\"global_data\":$GD_MULTI}" --exec finalize_order
GD_MULTI=$(echo "$OUTPUT" | sed -n '/^Actions:$/,$ p' | sed '1d' | jq -s -c '[.[] | select(has("set_global_data")) | .set_global_data] | add // empty' 2>/dev/null)
[ -z "$GD_MULTI" ] && GD_MULTI='{}'
check "Multi: finalized with total" "\\$"

run --raw --call-id "$MPC" --custom-data "{\"global_data\":$GD_MULTI}" --exec process_payment
GD_MULTI=$(echo "$OUTPUT" | sed -n '/^Actions:$/,$ p' | sed '1d' | jq -s -c '[.[] | select(has("set_global_data")) | .set_global_data] | add // empty' 2>/dev/null)
[ -z "$GD_MULTI" ] && GD_MULTI='{}'
check "Multi: payment processed" "order number"

run --raw --call-id "$MPC" --custom-data "{\"global_data\":$GD_MULTI}" --exec complete_order
check "Multi: order complete" "all set\|Enjoy\|thank"

# =============================================================================
section "35. Cancel pizza with existing completed pizzas"
# =============================================================================

GD_CANCEL2='{"current_pizza":{"size":"medium","crust":null,"sauce":null,"cheese":null,"toppings":[],"finishes":[],"price":11.99,"discount":0,"index":1},"order":{"pizzas":[{"size":"large","crust":{"type":"thin","bake":"classic"},"sauce":{"type":"classic_red","amount":"normal"},"cheese":{"type":"mozzarella","amount":"normal"},"toppings":[],"finishes":[],"price":14.99,"index":0}],"sides":[],"drinks":[],"subtotal":14.99,"tax":1.50,"total":16.49,"order_number":null}}'

run --raw --call-id "${CALL_ID}-cancel2" --custom-data "{\"global_data\":$GD_CANCEL2}" --exec cancel_pizza
check "Cancel pizza (has existing) → confirming_pizza" "confirming_pizza"
check "  → pizza_cancelled event" "pizza_cancelled"

# =============================================================================
section "36. Cancel order mid-build"
# =============================================================================

GD_MIDBUILD='{"current_pizza":{"size":"large","crust":{"type":"thin","bake":"classic"},"sauce":null,"cheese":null,"toppings":[],"finishes":[],"price":14.99,"discount":0,"index":0},"order":{"pizzas":[],"sides":[],"drinks":[],"subtotal":0,"tax":0,"total":0,"order_number":null}}'

run --raw --call-id "${CALL_ID}-cancelm" --custom-data "{\"global_data\":$GD_MIDBUILD}" --exec cancel_order
check "Cancel order mid-build → greeting" "greeting"
check "  → order_cancelled event" "order_cancelled"

# =============================================================================
section "37. Skip finishes (done_with_pizza from add_finishes)"
# =============================================================================

GD_SKIPFIN='{"current_pizza":{"size":"large","crust":{"type":"hand_tossed","bake":"classic"},"sauce":{"type":"classic_red","amount":"normal"},"cheese":{"type":"mozzarella","amount":"normal"},"toppings":[{"name":"pepperoni","placement":"full","amount":"normal"}],"finishes":[],"price":16.49,"discount":0,"index":0},"order":{"pizzas":[],"sides":[],"drinks":[],"subtotal":0,"tax":0,"total":0,"order_number":null}}'

run --raw --call-id "${CALL_ID}-skipfin" --custom-data "{\"global_data\":$GD_SKIPFIN}" --exec done_with_pizza
check "Skip finishes → pizza_completed" "pizza_completed"
check "  → change_step: confirming_pizza" "confirming_pizza"

# =============================================================================
section "38. Finalize with sides only (no pizza)"
# =============================================================================

GD_SIDESONLY='{"current_pizza":null,"order":{"pizzas":[],"sides":[{"key":"breadsticks","name":"Breadsticks","price":4.99,"quantity":1}],"drinks":[{"key":"water","name":"Bottled Water","price":1.99,"quantity":1}],"subtotal":6.98,"tax":0.70,"total":7.68,"order_number":null}}'

run --raw --call-id "${CALL_ID}-sidesonly" --custom-data "{\"global_data\":$GD_SIDESONLY}" --exec finalize_order
check "Finalize sides-only → total" "\\$"
check "  → change_step: payment" "payment"

# =============================================================================
section "39. order_specialty from ordering_sides"
# =============================================================================

GD_SIDES_SPEC='{"current_pizza":null,"order":{"pizzas":[{"size":"large","crust":{"type":"hand_tossed","bake":"classic"},"sauce":{"type":"classic_red","amount":"normal"},"cheese":{"type":"mozzarella","amount":"normal"},"toppings":[],"finishes":[],"price":14.99,"index":0}],"sides":[{"key":"breadsticks","name":"Breadsticks","price":4.99,"quantity":1}],"drinks":[],"subtotal":19.98,"tax":2.00,"total":21.98,"order_number":null}}'

run --raw --call-id "${CALL_ID}-sides-spec" --custom-data "{\"global_data\":$GD_SIDES_SPEC}" --exec order_specialty --specialty_name classic_pepperoni --size large
check "Specialty from sides → Pepperoni" "Pepperoni"
check "  → confirming_pizza" "confirming_pizza"

# =============================================================================
section "40. add_another_pizza from ordering_sides"
# =============================================================================

run --raw --call-id "${CALL_ID}-sides-add" --custom-data "{\"global_data\":$GD_SIDES_SPEC}" --exec add_another_pizza
check "Add another from sides → greeting" "greeting"
check "  → asks specialty or custom" "specialty\|Specialty\|custom\|Custom"

# =============================================================================
section "41. Modify round-trip (modify → add topping → done)"
# =============================================================================

GD_MODRT='{"current_pizza":null,"order":{"pizzas":[{"size":"large","crust":{"type":"thin","bake":"classic"},"sauce":{"type":"classic_red","amount":"normal"},"cheese":{"type":"mozzarella","amount":"normal"},"toppings":[{"name":"pepperoni","placement":"full","amount":"normal"}],"finishes":["parmesan"],"price":16.49,"index":0,"summary":["Large 14\"","Thin Crust","Classic Red Sauce","Mozzarella","Pepperoni","Parmesan Dusting"]}],"sides":[],"drinks":[],"subtotal":16.49,"tax":1.65,"total":18.14,"order_number":null}}'
MRT="${CALL_ID}-modrt"

# Modify
run --raw --call-id "$MRT" --custom-data "{\"global_data\":$GD_MODRT}" --exec modify_pizza
GD_MODRT2=$(echo "$OUTPUT" | sed -n '/^Actions:$/,$ p' | sed '1d' | jq -s -c '[.[] | select(has("set_global_data")) | .set_global_data] | add // empty' 2>/dev/null)
[ -z "$GD_MODRT2" ] && GD_MODRT2='{}'
check "Modify round-trip: modify → add_toppings" "add_toppings"

# Add another topping
run --raw --call-id "$MRT" --custom-data "{\"global_data\":$GD_MODRT2}" --exec add_topping --topping sausage
GD_MODRT2=$(echo "$OUTPUT" | sed -n '/^Actions:$/,$ p' | sed '1d' | jq -s -c '[.[] | select(has("set_global_data")) | .set_global_data] | add // empty' 2>/dev/null)
[ -z "$GD_MODRT2" ] && GD_MODRT2='{}'
check "Modify round-trip: added sausage" "Sausage"

# Done with toppings
run --raw --call-id "$MRT" --custom-data "{\"global_data\":$GD_MODRT2}" --exec done_with_toppings
GD_MODRT2=$(echo "$OUTPUT" | sed -n '/^Actions:$/,$ p' | sed '1d' | jq -s -c '[.[] | select(has("set_global_data")) | .set_global_data] | add // empty' 2>/dev/null)
[ -z "$GD_MODRT2" ] && GD_MODRT2='{}'
check "Modify round-trip: done toppings → add_finishes" "add_finishes"

# Done with pizza (skip finishes)
run --raw --call-id "$MRT" --custom-data "{\"global_data\":$GD_MODRT2}" --exec done_with_pizza
check "Modify round-trip: done → confirming_pizza" "confirming_pizza"
check "  → pizza_completed event" "pizza_completed"

# =============================================================================
section "42. Pizza size variations"
# =============================================================================

run --raw --call-id "${CALL_ID}-sm" --exec start_pizza --size small
check "Start small pizza → Small 10\"" "Small"

run --raw --call-id "${CALL_ID}-md" --exec start_pizza --size medium
check "Start medium pizza → Medium 12\"" "Medium"

# =============================================================================
# Summary
# =============================================================================
printf "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
TOTAL=$((PASS + FAIL))
printf "  Total:  %d\n" "$TOTAL"
printf "  ${GREEN}Passed: %d${NC}\n" "$PASS"
printf "  ${RED}Failed: %d${NC}\n" "$FAIL"
if [ "$FAIL" -eq 0 ]; then
    printf "\n${GREEN}All tests passed!${NC}\n\n"
else
    printf "\n${RED}%d test(s) failed.${NC}\n\n" "$FAIL"
    exit 1
fi
