// Gino's Pizza - WebRTC connection, event routing, order display, pizza tabs
// Frontend is display-only: ALL pricing comes from backend events.

let client = null;
let roomSession = null;
let isMuted = false;
let pendingTimeouts = [];

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

async function connect() {
    try {
        connectBtn.disabled = true;
        connectBtn.textContent = 'Connecting...';
        updateStatus('greeting', 'Getting token...');

        const tokenResp = await fetch('/get_token');
        const tokenData = await tokenResp.json();
        if (tokenData.error) throw new Error(tokenData.error);

        const currentToken = tokenData.token;
        const currentDestination = tokenData.address;

        console.log('Token received, destination:', currentDestination);
        updateStatus('greeting', 'Connecting to Gino...');

        if (window.SignalWire && typeof window.SignalWire.SignalWire === 'function') {
            client = await window.SignalWire.SignalWire({
                token: currentToken,
                logLevel: 'debug',
            });
        } else {
            throw new Error('SignalWire SDK not loaded');
        }

        // Client-level user events
        client.on('user_event', (params) => {
            console.log('CLIENT user_event:', params);
            handleUserEvent(params);
        });

        // Dial audio-only
        roomSession = await client.dial({
            to: currentDestination,
            audio: {
                echoCancellation: true,
                noiseSuppression: false,
                autoGainControl: false,
            },
            video: false,
            userVariables: {
                userName: "Gino's Pizza Customer",
                interface: 'web-ui',
                timestamp: new Date().toISOString(),
            },
        });

        // Room session events
        roomSession.on('call.joined', () => {
            connectBtn.style.display = 'none';
            hangupBtn.style.display = 'inline-block';
            muteBtn.style.display = 'inline-block';
            document.getElementById('voice-indicator').style.display = 'flex';
            updateStatus('greeting', 'Connected! Ready to take your order.');
            logEvent('Connected to Gino');
        });

        let disconnectTriggered = false;
        const handleDisconnect = (eventName) => {
            if (disconnectTriggered) return;
            disconnectTriggered = true;
            console.log(`Disconnect: ${eventName}`);
            setTimeout(() => {
                disconnect();
                disconnectTriggered = false;
            }, 100);
        };

        roomSession.on('call.state', (params) => {
            const s = params?.payload?.call_state || params?.call_state || params?.state;
            if (s === 'ending' || s === 'ended' || s === 'hangup') handleDisconnect('call.state');
        });
        roomSession.on('destroy', () => handleDisconnect('destroy'));
        roomSession.on('disconnected', () => handleDisconnect('disconnected'));
        roomSession.on('room.left', () => handleDisconnect('room.left'));
        roomSession.on('call.ended', () => handleDisconnect('call.ended'));

        roomSession.on('user_event', (params) => {
            console.log('ROOM user_event:', params);
            handleUserEvent(params);
        });

        await roomSession.start();
        console.log('Call started');
    } catch (error) {
        console.error('Connection error:', error);
        updateStatus('greeting', 'Connection failed. Try again.');
        connectBtn.disabled = false;
        connectBtn.textContent = 'Start Ordering';
    }
}

function disconnect() {
    if (roomSession?.localStream) {
        roomSession.localStream.getTracks().forEach(t => t.stop());
    }
    roomSession = null;

    if (client) {
        try { client.disconnect(); } catch (e) { /* ignore */ }
        client = null;
    }

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
        if (roomSession) await roomSession.hangup();
    } catch (e) {
        console.error('Hangup error:', e);
    }
    disconnect();
}

function toggleMute() {
    if (!roomSession) return;
    isMuted = !isMuted;
    try {
        const stream = roomSession.localStream || roomSession.peer?.localStream;
        if (stream) {
            stream.getAudioTracks().forEach(t => { t.enabled = !isMuted; });
        }
    } catch (e) {
        console.error('Mute error:', e);
    }
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

window.addEventListener('beforeunload', () => { if (roomSession) hangup(); });
