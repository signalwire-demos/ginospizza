// Gino's Pizza - WebRTC connection, event routing, order display, pizza tabs
// Frontend is display-only: ALL pricing comes from backend events.

let client = null;
let call = null;
let isMuted = false;
let pendingTimeouts = [];
// v4: track RxJS subscriptions + teardown/media state
let subscriptions = [];
let teardownDone = false;
let remoteAudioEl = null;
let lastRemoteSig = '';
let currentLocalStream = null;

// Pizza renderers - one per pizza
const renderers = new Map(); // pizza_index -> PizzaRenderer
let activePizzaIndex = 0;

// Order state (display only - truth is backend)
let orderState = {
    pizzas: [],
    sides: [],
    drinks: [],
    subtotal: 0,
    tax: 0,
    total: 0,
    orderNumber: null,
};

// ── UI Elements ─────────────────────────────────────────────────────────────

const connectBtn = document.getElementById('connectBtn');
const hangupBtn = document.getElementById('hangupBtn');
const muteBtn = document.getElementById('muteBtn');
const statusDiv = document.getElementById('status');
const showLogCheckbox = document.getElementById('showLog');
const eventLogContainer = document.getElementById('event-log-container');
const eventEntries = document.getElementById('event-entries');
const orderItems = document.getElementById('order-items');
const orderTotals = document.getElementById('order-totals');
const orderNumberDiv = document.getElementById('order-number');
const orderNumberValue = document.getElementById('order-number-value');
const resultMessage = document.getElementById('result-message');

// ── Status ──────────────────────────────────────────────────────────────────

function updateStatus(status, message) {
    statusDiv.className = '';
    switch (status) {
        case 'greeting':    statusDiv.className = 'status-greeting'; break;
        case 'building':    statusDiv.className = 'status-building'; break;
        case 'confirming':  statusDiv.className = 'status-confirming'; break;
        case 'payment':     statusDiv.className = 'status-payment'; break;
        case 'complete':    statusDiv.className = 'status-complete'; break;
        default:            statusDiv.className = 'status-greeting';
    }
    statusDiv.textContent = message || 'Ready';
}

// ── Toast ────────────────────────────────────────────────────────────────────

function showResult(message, duration = 3000) {
    resultMessage.textContent = message;
    resultMessage.classList.add('show');
    setTimeout(() => resultMessage.classList.remove('show'), duration);
}

// ── Event Logging ───────────────────────────────────────────────────────────

function logEvent(message, data = null, isUserEvent = false) {
    const entry = document.createElement('div');
    entry.className = isUserEvent ? 'event-entry user-event' : 'event-entry';
    const time = new Date().toLocaleTimeString();
    let dataStr = '';
    if (data) {
        try { dataStr = JSON.stringify(data, null, 2); } catch (e) { dataStr = '...'; }
    }
    entry.innerHTML = `<span style="color:#999">${time}</span> ${isUserEvent ? '&#127829; ' : ''}${message}` +
        (dataStr ? `<pre style="color:#888;margin:2px 0 0 12px;font-size:0.7rem;max-height:100px;overflow:auto">${dataStr}</pre>` : '');
    eventEntries.appendChild(entry);
    requestAnimationFrame(() => { eventEntries.scrollTop = eventEntries.scrollHeight; });
}

// ── Pizza Tab Management ────────────────────────────────────────────────────

function createPizzaCanvas(index) {
    const wrapper = document.getElementById('pizza-canvas-wrapper');

    // Hide placeholder
    const placeholder = document.getElementById('pizza-placeholder');
    if (placeholder) placeholder.style.display = 'none';

    // If renderer already exists for this index, just switch to it
    if (renderers.has(index)) {
        switchPizzaTab(index);
        return renderers.get(index);
    }

    // Hide all existing canvases
    renderers.forEach((r) => { r.container.style.display = 'none'; });

    // Create canvas
    const canvas = document.createElement('div');
    canvas.className = 'pizza-canvas';
    canvas.dataset.pizzaIndex = index;
    wrapper.appendChild(canvas);

    // Create renderer
    const renderer = new PizzaRenderer(canvas);
    renderers.set(index, renderer);

    // Update tabs
    updatePizzaTabs(index);

    console.log(`Created pizza canvas ${index}, total renderers: ${renderers.size}`);
    return renderer;
}

function updatePizzaTabs(activeIndex) {
    const tabsContainer = document.getElementById('pizza-tabs');
    tabsContainer.innerHTML = '';

    // Only show tabs if there are multiple pizzas
    if (renderers.size <= 1) {
        activePizzaIndex = activeIndex;
        return;
    }

    for (const [idx] of renderers) {
        const tab = document.createElement('button');
        tab.className = `pizza-tab${idx === activeIndex ? ' active' : ''}`;
        tab.textContent = `Pizza #${idx + 1}`;
        tab.onclick = () => switchPizzaTab(idx);
        tabsContainer.appendChild(tab);
    }

    activePizzaIndex = activeIndex;
}

function switchPizzaTab(index) {
    // Hide all canvases via renderer references (no DOM query needed)
    renderers.forEach((r) => { r.container.style.display = 'none'; });

    const renderer = renderers.get(index);
    if (renderer) {
        renderer.container.style.display = '';
        console.log(`Switched to pizza canvas ${index}`);
    }

    updatePizzaTabs(index);
}

function removePizzaCanvas(index) {
    const renderer = renderers.get(index);
    if (renderer) {
        renderer.clear();
        renderer.container.remove();
    }
    renderers.delete(index);

    if (renderers.size > 0) {
        const first = renderers.keys().next().value;
        switchPizzaTab(first);
    } else {
        const placeholder = document.getElementById('pizza-placeholder');
        if (placeholder) placeholder.style.display = '';
        document.getElementById('pizza-tabs').innerHTML = '';
    }
}

// ── Order Display ───────────────────────────────────────────────────────────

function updateOrderDisplay() {
    const hasItems = orderState.pizzas.length > 0 || orderState.sides.length > 0 || orderState.drinks.length > 0;

    if (!hasItems) {
        orderItems.innerHTML = '<div style="text-align:center;color:#999;padding:30px;">Your order will appear here</div>';
        orderTotals.style.display = 'none';
        return;
    }

    let html = '';

    // Pizzas
    orderState.pizzas.forEach((pizza, i) => {
        const summary = pizza.summary || [];
        html += `<div class="order-pizza">`;
        html += `<div class="order-pizza-header"><span>Pizza #${i + 1}</span><span>$${(pizza.price || 0).toFixed(2)}</span></div>`;
        summary.forEach(line => {
            html += `<div class="order-pizza-detail">${line}</div>`;
        });
        html += `</div>`;
    });

    // Sides
    if (orderState.sides.length > 0) {
        html += `<div class="order-extras"><div class="order-extras-title">Sides</div>`;
        orderState.sides.forEach(s => {
            html += `<div class="order-item"><span>${s.quantity}x ${s.name}</span><span>$${(s.price * s.quantity).toFixed(2)}</span></div>`;
        });
        html += `</div>`;
    }

    // Drinks
    if (orderState.drinks.length > 0) {
        html += `<div class="order-extras"><div class="order-extras-title">Drinks</div>`;
        orderState.drinks.forEach(d => {
            html += `<div class="order-item"><span>${d.quantity}x ${d.name}</span><span>$${(d.price * d.quantity).toFixed(2)}</span></div>`;
        });
        html += `</div>`;
    }

    orderItems.innerHTML = html;

    // Totals
    document.getElementById('subtotal').textContent = `$${orderState.subtotal.toFixed(2)}`;
    document.getElementById('tax').textContent = `$${orderState.tax.toFixed(2)}`;
    document.getElementById('total').textContent = `$${orderState.total.toFixed(2)}`;
    orderTotals.style.display = 'block';
}

function updateTotals(eventData) {
    if (eventData.subtotal !== undefined) orderState.subtotal = eventData.subtotal;
    if (eventData.tax !== undefined) orderState.tax = eventData.tax;
    if (eventData.total !== undefined) orderState.total = eventData.total;
}

// ── Menu Tab Auto-Selection ──────────────────────────────────────────────────

function selectMenuTab(categoryKey) {
    const tabsContainer = document.getElementById('menu-tabs');
    const contentContainer = document.getElementById('menu-content');
    if (!tabsContainer || !contentContainer) {
        console.log('selectMenuTab: containers not found');
        return;
    }

    const tab = tabsContainer.querySelector(`[data-menu-key="${categoryKey}"]`);
    if (!tab) {
        console.log(`selectMenuTab: no tab for key "${categoryKey}"`);
        return;
    }
    console.log(`selectMenuTab: switching to "${categoryKey}"`);

    tabsContainer.querySelectorAll('.menu-tab').forEach(t => t.classList.remove('active'));
    contentContainer.querySelectorAll('.menu-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    const content = document.getElementById(`menu-${categoryKey}`);
    if (content) content.classList.add('active');
}

// ── Progress Indicator ──────────────────────────────────────────────────────

function updateProgress(step) {
    const steps = ['size', 'crust', 'sauce', 'cheese', 'toppings', 'finishes'];
    const container = document.getElementById('progress-steps');
    if (!container) return;
    container.style.display = 'flex';
    const idx = steps.indexOf(step);
    container.querySelectorAll('span').forEach((el, i) => {
        el.classList.remove('active', 'done');
        if (i < idx) el.classList.add('done');
        else if (i === idx) el.classList.add('active');
    });
}

// ── User Event Handler ──────────────────────────────────────────────────────

function handleUserEvent(params) {
    console.log('RAW user_event params:', JSON.stringify(params).substring(0, 500));
    let eventData = params;
    if (params && params.event) eventData = params.event;
    if (!eventData || !eventData.type) {
        console.log('DROPPED - no type found. keys:', Object.keys(eventData || {}));
        return;
    }

    console.log('PROCESSING event:', eventData.type);

    switch (eventData.type) {
        case 'pizza_started': {
            const idx = eventData.pizza_index ?? 0;
            const renderer = createPizzaCanvas(idx);
            renderer.setSize(eventData.size || 'large');
            updateTotals(eventData);
            updateStatus('building', `Building Pizza #${idx + 1} - ${eventData.size_name || 'Large'}`);
            updateProgress('crust');
            selectMenuTab('crusts');
            logEvent(`Pizza #${idx + 1} started (${eventData.size_name})`, eventData, true);
            break;
        }

        case 'layer_added': {
            const idx = eventData.pizza_index ?? 0;
            let renderer = renderers.get(idx);
            if (!renderer) renderer = createPizzaCanvas(idx);
            renderer.addLayer(eventData);
            updateTotals(eventData);
            updateOrderDisplay();
            showResult(`Added ${eventData.label}`);
            const layerToTab = { crust: 'sauces', sauce: 'cheeses', cheese: 'toppings', topping: 'toppings', finish: 'finishes' };
            if (layerToTab[eventData.category]) selectMenuTab(layerToTab[eventData.category]);
            const layerToProgress = { crust: 'sauce', sauce: 'cheese', cheese: 'toppings', topping: 'toppings', finish: 'finishes' };
            if (layerToProgress[eventData.category]) updateProgress(layerToProgress[eventData.category]);
            const buildPrice = document.getElementById('build-price');
            const buildPriceValue = document.getElementById('build-price-value');
            if (eventData.pizza_price !== undefined) {
                buildPrice.style.display = 'block';
                buildPriceValue.textContent = `$${eventData.pizza_price.toFixed(2)}`;
            }
            logEvent(`Layer: ${eventData.label}`, eventData, true);
            break;
        }

        case 'layer_removed': {
            const idx = eventData.pizza_index ?? 0;
            const renderer = renderers.get(idx);
            if (renderer && eventData.topping_name) {
                renderer.removeTopping(eventData.topping_name);
            }
            updateTotals(eventData);
            updateOrderDisplay();
            showResult(`Removed ${eventData.label}`);
            logEvent(`Removed: ${eventData.label}`, eventData, true);
            break;
        }

        case 'pizza_completed': {
            const idx = eventData.pizza_index ?? 0;
            let renderer = renderers.get(idx);
            if (!renderer) renderer = createPizzaCanvas(idx);

            // Render any layers included (covers defaults applied by done_with_pizza)
            const completedLayers = eventData.layers || [];
            completedLayers.forEach(layer => renderer.addLayer(layer));
            renderer.lock();

            const pizza = eventData.pizza || {};
            pizza.summary = eventData.summary || [];
            orderState.pizzas[idx] = pizza;
            updateTotals(eventData);
            updateOrderDisplay();
            updateStatus('confirming', `Pizza #${idx + 1} complete!`);
            showResult(`Pizza #${idx + 1} is ready!`, 3000);
            document.getElementById('progress-steps').style.display = 'none';
            document.getElementById('build-price').style.display = 'none';
            logEvent(`Pizza #${idx + 1} completed`, eventData, true);
            break;
        }

        case 'pizza_cancelled': {
            const idx = eventData.pizza_index ?? 0;
            removePizzaCanvas(idx);
            updateTotals(eventData);
            updateOrderDisplay();
            updateStatus('greeting', 'Pizza cancelled');
            document.getElementById('progress-steps').style.display = 'none';
            document.getElementById('build-price').style.display = 'none';
            logEvent('Pizza cancelled', eventData, true);
            break;
        }

        case 'side_added':
        case 'side_removed': {
            orderState.sides = eventData.sides || [];
            updateTotals(eventData);
            updateOrderDisplay();
            selectMenuTab('drinks');
            const action = eventData.type === 'side_added' ? 'Added' : 'Removed';
            showResult(`${action} ${eventData.name || 'side'}`);
            logEvent(eventData.type, eventData, true);
            break;
        }

        case 'drink_added':
        case 'drink_removed': {
            orderState.drinks = eventData.drinks || [];
            updateTotals(eventData);
            updateOrderDisplay();
            selectMenuTab('drinks');
            const action = eventData.type === 'drink_added' ? 'Added' : 'Removed';
            showResult(`${action} ${eventData.name || 'drink'}`);
            logEvent(eventData.type, eventData, true);
            break;
        }

        case 'order_reviewed': {
            if (eventData.order) {
                orderState.pizzas = (eventData.order.pizzas || []).map((p, i) => {
                    p.summary = p.summary || orderState.pizzas[i]?.summary || [];
                    return p;
                });
                orderState.sides = eventData.order.sides || [];
                orderState.drinks = eventData.order.drinks || [];
            }
            updateTotals(eventData);
            updateOrderDisplay();
            logEvent('Order reviewed', eventData, true);
            break;
        }

        case 'order_finalized': {
            updateTotals(eventData);
            updateOrderDisplay();
            updateStatus('payment', `Order total: $${orderState.total.toFixed(2)}`);
            logEvent('Order finalized', eventData, true);
            break;
        }

        case 'payment_started': {
            orderState.orderNumber = eventData.order_number;
            orderNumberValue.textContent = eventData.order_number;
            orderNumberDiv.style.display = 'block';
            updateTotals(eventData);
            updateOrderDisplay();
            updateStatus('payment', `Order #${eventData.order_number}`);
            showResult(`Order #${eventData.order_number} placed!`, 5000);
            logEvent('Payment processed', eventData, true);
            break;
        }

        case 'order_completed': {
            for (const [idx] of renderers) removePizzaCanvas(idx);
            orderState.pizzas = [];
            orderState.sides = [];
            orderState.drinks = [];
            orderState.subtotal = 0;
            orderState.tax = 0;
            orderState.total = 0;
            updateOrderDisplay();
            updateStatus('complete', `Order #${eventData.order_number} complete!`);
            showResult('Thank you! Your pizza is on its way!', 5000);
            logEvent('Order completed', eventData, true);
            break;
        }

        case 'order_cancelled':
        case 'new_order': {
            pendingTimeouts.forEach(id => clearTimeout(id));
            pendingTimeouts = [];
            for (const [idx] of renderers) removePizzaCanvas(idx);
            orderState = { pizzas: [], sides: [], drinks: [], subtotal: 0, tax: 0, total: 0, orderNumber: null };
            orderNumberDiv.style.display = 'none';
            document.getElementById('progress-steps').style.display = 'none';
            document.getElementById('build-price').style.display = 'none';
            updateOrderDisplay();
            selectMenuTab('sizes');
            updateStatus('greeting', eventData.type === 'new_order' ? 'Ready for a new order!' : 'Order cancelled');
            logEvent(eventData.type, eventData, true);
            break;
        }

        case 'pizza_size_changed': {
            const idx = eventData.pizza_index ?? 0;
            const sizeRenderer = renderers.get(idx);
            if (sizeRenderer) sizeRenderer.setSize(eventData.size || 'large');
            const pizza = eventData.pizza || {};
            pizza.summary = eventData.summary || [];
            orderState.pizzas[idx] = pizza;
            updateTotals(eventData);
            updateOrderDisplay();
            showResult(`Changed to ${eventData.size_name}`);
            logEvent('Size changed', eventData, true);
            break;
        }

        case 'pizza_confirmed': {
            updateTotals(eventData);
            updateOrderDisplay();
            selectMenuTab('sides');
            updateStatus('confirming', 'Pizza confirmed! Adding sides & drinks...');
            document.getElementById('progress-steps').style.display = 'none';
            document.getElementById('build-price').style.display = 'none';
            logEvent('Pizza confirmed', eventData, true);
            break;
        }

        case 'pizza_modify': {
            const idx = eventData.pizza_index ?? 0;
            const renderer = renderers.get(idx);
            if (renderer) renderer.unlock();
            switchPizzaTab(idx);
            updateTotals(eventData);
            updateOrderDisplay();
            updateStatus('building', `Modifying Pizza #${idx + 1}`);
            logEvent('Modifying pizza', eventData, true);
            break;
        }

        case 'specialty_pizza': {
            // Compound event: create canvas, add all layers, complete
            const idx = eventData.pizza_index ?? 0;
            const renderer = createPizzaCanvas(idx);
            renderer.setSize(eventData.size || 'large');
            selectMenuTab('specialties');
            const layers = eventData.layers || [];
            layers.forEach((layer, i) => {
                pendingTimeouts.push(setTimeout(() => renderer.addLayer(layer), i * 150));
            });
            pendingTimeouts.push(setTimeout(() => {
                renderer.lock();
                const pizza = eventData.pizza || {};
                pizza.summary = eventData.summary || [];
                orderState.pizzas[idx] = pizza;
                updateTotals(eventData);
                updateOrderDisplay();
                updateStatus('confirming', `Pizza #${idx + 1} complete!`);
                showResult(`Pizza #${idx + 1} is ready!`, 3000);
            }, layers.length * 150 + 100));
            document.getElementById('progress-steps').style.display = 'none';
            document.getElementById('build-price').style.display = 'none';
            logEvent(`Specialty pizza #${idx + 1}`, eventData, true);
            break;
        }

        case 'toppings_done': {
            selectMenuTab('finishes');
            updateProgress('finishes');
            logEvent('Toppings done', eventData, true);
            updateStatus('building', 'Adding finishing touches...');
            break;
        }

        case 'sides_only': {
            selectMenuTab('sides');
            updateTotals(eventData);
            logEvent('Ordering sides only', eventData, true);
            break;
        }

        case 'adding_pizza': {
            selectMenuTab('specialties');
            updateTotals(eventData);
            logEvent('Adding another pizza', eventData, true);
            break;
        }

        case 'show_menu': {
            logEvent('Menu shown', eventData, true);
            break;
        }
    }
}

// ── Menu Display ────────────────────────────────────────────────────────────

async function loadMenu() {
    try {
        const resp = await fetch('/api/menu');
        const data = await resp.json();
        displayMenu(data.menu);
    } catch (e) {
        console.error('Failed to load menu:', e);
    }
}

function displayMenu(menu) {
    const tabsContainer = document.getElementById('menu-tabs');
    const contentContainer = document.getElementById('menu-content');
    tabsContainer.innerHTML = '';
    contentContainer.innerHTML = '';

    function priceTag(amount) {
        if (amount > 0) return `<span class="menu-item-price">+$${amount.toFixed(2)}</span>`;
        return `<span class="menu-item-note">included</span>`;
    }

    function freeTag(amount) {
        if (amount > 0) return `<span class="menu-item-price">+$${amount.toFixed(2)}</span>`;
        return `<span class="menu-item-note">free</span>`;
    }

    const categories = [
        {
            key: 'sizes', label: 'Sizes',
            render(items) {
                return Object.entries(items).map(([k, v]) =>
                    `<div class="menu-grid-item"><span class="menu-item-name">${v.name}</span><span class="menu-item-price">$${v.price.toFixed(2)}</span></div>`
                ).join('');
            }
        },
        {
            key: 'crusts', label: 'Crusts',
            render(items) {
                return Object.entries(items).map(([k, v]) =>
                    `<div class="menu-grid-item"><span class="menu-item-name">${v.name}</span>${priceTag(v.upcharge)}</div>`
                ).join('') + `<div class="menu-item-note" style="padding:4px 8px">Bake: Classic or Well Done</div>`;
            }
        },
        {
            key: 'sauces', label: 'Sauces',
            render(items) {
                return Object.entries(items).map(([k, v]) =>
                    `<div class="menu-grid-item"><span class="menu-item-name">${v.name}</span>${priceTag(v.upcharge)}</div>`
                ).join('') + `<div class="menu-item-note" style="padding:4px 8px">Amount: Light, Normal, or Extra</div>`;
            }
        },
        {
            key: 'cheeses', label: 'Cheese',
            render(items) {
                return Object.entries(items).map(([k, v]) =>
                    `<div class="menu-grid-item"><span class="menu-item-name">${v.name}</span>${priceTag(v.upcharge)}</div>`
                ).join('') + `<div class="menu-item-note" style="padding:4px 8px">Amount: Light, Normal, or Extra</div>`;
            }
        },
        {
            key: 'toppings', label: 'Toppings',
            render(items) {
                return Object.entries(items).map(([k, v]) =>
                    `<div class="menu-grid-item">` +
                    `<span class="menu-item-name">${v.name}</span>` +
                    `<span class="menu-item-price">$${v.price.toFixed(2)} <span class="menu-item-note">half $${(v.price / 2).toFixed(2)}</span></span>` +
                    `</div>`
                ).join('') + `<div class="menu-item-note" style="padding:4px 8px">Amount: Light, Normal, or Extra &bull; Placement: Full, Left, or Right</div>`;
            }
        },
        {
            key: 'finishes', label: 'Finishes',
            render(items) {
                return Object.entries(items).map(([k, v]) =>
                    `<div class="menu-grid-item"><span class="menu-item-name">${v.name}</span>${freeTag(v.upcharge)}</div>`
                ).join('');
            }
        },
        {
            key: 'specialties', label: 'Specialties',
            render(items) {
                return Object.entries(items).map(([k, v]) => {
                    const toppings = v.toppings.map(t => {
                        // Capitalize and clean up topping name
                        const name = t.name.replace(/_/g, ' ');
                        return name.charAt(0).toUpperCase() + name.slice(1);
                    }).join(', ');
                    const desc = `${v.crust.type.replace(/_/g, ' ')} crust, ${v.sauce.type.replace(/_/g, ' ')}, ${v.cheese.type.replace(/_/g, ' ')}, ${toppings}`;
                    return `<div class="menu-grid-item menu-specialty-item">` +
                        `<div><span class="menu-item-name">${v.name}</span>` +
                        `<div class="menu-item-note">${desc}</div></div>` +
                        `<span class="menu-item-price">$${v.discount.toFixed(2)} off</span>` +
                        `</div>`;
                }).join('');
            }
        },
        {
            key: 'sides', label: 'Sides',
            render(items) {
                return Object.entries(items).map(([k, v]) =>
                    `<div class="menu-grid-item"><span class="menu-item-name">${v.name}</span><span class="menu-item-price">$${v.price.toFixed(2)}</span></div>`
                ).join('');
            }
        },
        {
            key: 'drinks', label: 'Drinks',
            render(items) {
                return Object.entries(items).map(([k, v]) =>
                    `<div class="menu-grid-item"><span class="menu-item-name">${v.name}</span><span class="menu-item-price">$${v.price.toFixed(2)}</span></div>`
                ).join('');
            }
        },
    ];

    categories.forEach((cat, i) => {
        if (!menu[cat.key]) return;

        // Tab
        const tab = document.createElement('button');
        tab.className = `menu-tab${i === 0 ? ' active' : ''}`;
        tab.dataset.menuKey = cat.key;
        tab.textContent = cat.label;
        tab.onclick = () => {
            tabsContainer.querySelectorAll('.menu-tab').forEach(t => t.classList.remove('active'));
            contentContainer.querySelectorAll('.menu-content').forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById(`menu-${cat.key}`).classList.add('active');
        };
        tabsContainer.appendChild(tab);

        // Content
        const content = document.createElement('div');
        content.className = `menu-content${i === 0 ? ' active' : ''}`;
        content.id = `menu-${cat.key}`;

        const grid = document.createElement('div');
        grid.className = 'menu-grid';
        grid.innerHTML = cat.render(menu[cat.key]);

        content.appendChild(grid);
        contentContainer.appendChild(content);
    });
}

// ── WebRTC Connection ───────────────────────────────────────────────────────

// ── v4 helpers ────────────────────────────────────────────────────────────

function track(sub) {
    if (sub) subscriptions.push(sub);
    return sub;
}

function streamSignature(stream) {
    return stream.getTracks().map(t => t.kind + ':' + t.id).sort().join(',');
}

// Hardened token fetch: tolerate the FastAPI tuple-return array shape.
async function fetchGuestToken() {
    const resp = await fetch('/get_token');
    let data = await resp.json();
    if (Array.isArray(data)) data = data[0] || {};
    if (!resp.ok || data.error) throw new Error(data.error || `HTTP ${resp.status}`);
    if (!data.token || !data.address) throw new Error('Token response missing token/address');
    return data;
}

// Gate the dial on the client connecting (replays synchronously; never errors
// on bad creds -> needs a timeout).
function waitForConnected(swClient, timeoutMs) {
    return new Promise((resolve, reject) => {
        let settled = false;
        let sub = null;
        const timer = setTimeout(() => {
            if (settled) return;
            settled = true;
            if (sub) { try { sub.unsubscribe(); } catch (e) {} }
            reject(new Error('Timed out waiting for SignalWire connection'));
        }, timeoutMs);
        sub = swClient.isConnected$.subscribe(connected => {
            if (connected && !settled) {
                settled = true;
                clearTimeout(timer);
                setTimeout(() => { if (sub) { try { sub.unsubscribe(); } catch (e) {} } }, 0);
                resolve();
            }
        });
    });
}

// Audio-only call: attach the remote stream to a hidden <audio> so Gino is
// audible (no rootElement/auto-play in v4). Re-attach on track-set change.
function attachRemoteStream(stream) {
    if (!stream) return;
    if (!remoteAudioEl) {
        remoteAudioEl = document.createElement('audio');
        remoteAudioEl.autoplay = true;
        remoteAudioEl.setAttribute('playsinline', '');
        remoteAudioEl.style.display = 'none';
        document.body.appendChild(remoteAudioEl);
    }
    const sig = streamSignature(stream);
    if (sig !== lastRemoteSig) {
        lastRemoteSig = sig;
        remoteAudioEl.srcObject = stream;
        remoteAudioEl.play().catch(e => console.log('Remote audio play blocked:', e.message));
    }
}

async function connect() {
    try {
        connectBtn.disabled = true;
        connectBtn.textContent = 'Connecting...';
        updateStatus('greeting', 'Getting token...');

        // Reset per-connection state
        teardownDone = false;
        subscriptions = [];
        remoteAudioEl = null;
        lastRemoteSig = '';
        currentLocalStream = null;

        const tokenData = await fetchGuestToken();
        const currentToken = tokenData.token;
        const currentDestination = tokenData.address;

        console.log('Token received, destination:', currentDestination);
        updateStatus('greeting', 'Connecting to Gino...');

        const SW = window.SignalWire;
        if (!SW || typeof SW.SignalWire !== 'function') {
            throw new Error('SignalWire v4 SDK not loaded');
        }

        // v4: constructor auto-connects; guest SAT via StaticCredentialProvider
        client = new SW.SignalWire(new SW.StaticCredentialProvider({ token: currentToken }));

        track(client.errors$.subscribe(e => console.error('SDK error:', e && e.code, e && e.message)));
        track(client.warnings$.subscribe(w => console.warn('SDK warning:', w && w.code, w && w.message)));

        await waitForConnected(client, 15000);

        // Dial audio-only (no avatar video; the pizza is rendered client-side)
        call = await client.dial(currentDestination, {
            audio: true,
            video: false,
            receiveAudio: true,
            receiveVideo: false,
            userVariables: {
                userName: "Gino's Pizza Customer",
                interface: 'web-ui-v4',
            },
        });

        // Remote audio
        track(call.remoteStream$.subscribe(stream => attachRemoteStream(stream)));
        // Cache local stream for the mute fallback
        track(call.localStream$.subscribe(stream => { currentLocalStream = stream || null; }));

        // Single user_event subscription (handleUserEvent unwraps .event)
        track(call.subscribe('user_event').subscribe(evt => {
            const params = (evt && evt.params) ? evt.params : evt;
            handleUserEvent(params);
        }));

        // Lifecycle
        track(call.status$.subscribe({
            next: (status) => {
                console.log('call.status:', status);
                if (status === 'connected') {
                    onConnected();
                } else if (status === 'disconnected' || status === 'failed' || status === 'destroyed') {
                    disconnect();
                }
            },
            complete: () => disconnect(),
        }));

        console.log('Dial initiated');
    } catch (error) {
        console.error('Connection error:', error);
        updateStatus('greeting', 'Connection failed. Try again.');
        connectBtn.disabled = false;
        connectBtn.textContent = 'Start Ordering';
        disconnect();
    }
}

function onConnected() {
    connectBtn.style.display = 'none';
    hangupBtn.style.display = 'inline-block';
    muteBtn.style.display = 'inline-block';
    document.getElementById('voice-indicator').style.display = 'flex';
    updateStatus('greeting', 'Connected! Ready to take your order.');
    logEvent('Connected to Gino');
}

function disconnect() {
    if (teardownDone) return;
    teardownDone = true;

    // Unsubscribe every tracked RxJS subscription
    subscriptions.forEach(s => { try { s.unsubscribe(); } catch (e) {} });
    subscriptions = [];

    if (client) {
        try { client.disconnect(); } catch (e) { /* ignore */ }
        client = null;
    }
    call = null;
    currentLocalStream = null;

    // Remove the hidden remote-audio element
    if (remoteAudioEl) {
        remoteAudioEl.srcObject = null;
        remoteAudioEl.remove();
        remoteAudioEl = null;
    }
    lastRemoteSig = '';

    connectBtn.style.display = 'inline-block';
    connectBtn.disabled = false;
    connectBtn.textContent = 'Start Ordering';
    hangupBtn.style.display = 'none';
    muteBtn.style.display = 'none';
    muteBtn.textContent = 'Mute';
    isMuted = false;
    document.getElementById('voice-indicator').style.display = 'none';

    pendingTimeouts.forEach(id => clearTimeout(id));
    pendingTimeouts = [];
    for (const [idx] of renderers) removePizzaCanvas(idx);

    // Reset order state
    orderState = { pizzas: [], sides: [], drinks: [], subtotal: 0, tax: 0, total: 0, orderNumber: null };
    orderNumberDiv.style.display = 'none';
    updateOrderDisplay();

    updateStatus('greeting', 'Welcome to Gino\'s Pizza!');
}

async function hangup() {
    try {
        if (call) await call.hangup();
    } catch (e) {
        console.error('Hangup error:', e);
    }
    disconnect();
}

async function toggleMute() {
    if (!call) return;
    const wantMuted = !isMuted;
    let ok = false;
    try {
        if (wantMuted) {
            await call.self.mute();
        } else {
            await call.self.unmute();
        }
        ok = true;
    } catch (e) {
        console.warn('Server mute failed, using local fallback:', e.message);
    }
    if (!ok) {
        const tracks = currentLocalStream ? currentLocalStream.getAudioTracks() : [];
        tracks.forEach(t => { t.enabled = !wantMuted; });
    }
    isMuted = wantMuted;
    muteBtn.textContent = isMuted ? 'Unmute' : 'Mute';
}

// ── Event Listeners ─────────────────────────────────────────────────────────

connectBtn.addEventListener('click', connect);
hangupBtn.addEventListener('click', hangup);
muteBtn.addEventListener('click', toggleMute);

showLogCheckbox.addEventListener('change', (e) => {
    eventLogContainer.style.display = e.target.checked ? 'block' : 'none';
});

// ── Init ────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    loadMenu();
    updateStatus('greeting', 'Welcome to Gino\'s Pizza!');
    logEvent('Application initialized');
});

window.addEventListener('beforeunload', () => { if (call) hangup(); });
